"""
foldr.watch
~~~~~~~~~~~
Background directory watcher for FOLDR v2.1.

What it does
------------
1. Runs an initial full-directory scan immediately on start.
2. Watches for new / moved / modified files and organizes them automatically.
3. Files moved back to root are re-organized (no session state blocks them).
4. Files already inside a FOLDR category folder are skipped (loop prevention).

Cross-platform backends (watchdog)
------------------------------------
  Linux   : inotify  (kernel-native, 0% CPU when idle)
  macOS   : kqueue / FSEvents (0% CPU when idle)
  Windows : ReadDirectoryChangesW (0% CPU when idle)

Root causes of the Linux "nothing moves" bug — now fixed
---------------------------------------------------------
BUG 1 (critical): `from foldr.organizer import _matches_any` was at the
TOP of `_organize_one`, outside any try/except. If that private symbol does
not exist, ImportError propagates into `_processor`, KILLING the thread on
the first event. The observer kept running; events queued; nothing moved.
FIX: ignore matching is now done with stdlib fnmatch, no private import needed.

BUG 2 (critical): `_processor` had no try/except around `_organize_one`.
Any unhandled exception killed the thread permanently.
FIX: every call is wrapped in try/except with full traceback logging.

No startup / boot registration — watch runs until shutdown or `foldr unwatch`.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import shutil
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from foldr.term import (
    ACCENT, BOLD, COL_OK, COL_WARN, FG_MUTED, RESET,
    cat_fg, cat_icon,
)
from foldr.history import save_history

# Extensions that indicate a file is still being written / downloaded
_IN_PROGRESS: frozenset[str] = frozenset({
    ".crdownload", ".part", ".tmp", ".download",
    ".partial", ".!ut", ".ytdl", ".aria2", ".opdownload",
})

_LOG_DIR = Path.home() / ".foldr" / "watch_logs"


# ── Utilities ──────────────────────────────────────────────────────────────────

def _normalize_path(src: object) -> Path:
    """
    Normalize watchdog src_path to Path.
    watchdog may return str, bytes, bytearray, or memoryview depending on OS.
    """
    if isinstance(src, memoryview):
        src = bytes(src)
    if isinstance(src, (bytes, bytearray)):
        return Path(src.decode(errors="replace"))
    return Path(str(src))


def _file_stable(p: Path) -> bool:
    """Return True when the file has stopped growing."""
    try:
        before = p.stat().st_size
    except OSError:
        return False
    time.sleep(0.5)
    try:
        return p.stat().st_size == before
    except OSError:
        return False


def _get_logger(base: Path) -> logging.Logger:
    """Return a per-directory file logger (~/.foldr/watch_logs/<dir>.log)."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe     = base.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    log_file = _LOG_DIR / f"{safe}.log"
    name     = f"foldr.watch.{safe}"
    logger   = logging.getLogger(name)
    if not logger.handlers:
        h = logging.FileHandler(log_file, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
    return logger


def _log_file_path(base: Path) -> Path:
    safe = base.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return _LOG_DIR / f"{safe}.log"


def _category_folder_names(template: dict | None) -> set[str]:
    """
    Return the folder names FOLDR creates inside the watched dir.
    Used for loop prevention. Zero private imports from organizer.
    """
    from foldr.config import CATEGORIES_TEMPLATE
    tmpl = template or CATEGORIES_TEMPLATE
    return {v["folder"] for v in tmpl.values()}


def _matches_ignore(filename: str, patterns: list[str]) -> bool:
    """
    Check whether filename matches any ignore pattern.
    Self-contained — uses stdlib fnmatch only.
    No private organizer imports needed.
    """
    if not patterns:
        return False
    low = filename.lower()
    for pat in patterns:
        clean = pat.rstrip("/")
        if fnmatch.fnmatch(filename, clean) or fnmatch.fnmatch(low, clean.lower()):
            return True
    return False


# ── Single-file organizer ──────────────────────────────────────────────────────

def _organize_one(
    file_path: Path,
    base: Path,
    template: dict | None,
    dry_run: bool,
    ignore_patterns: list[str],
    logger: logging.Logger,
    cat_folders: set[str],
) -> tuple[str, str] | None:
    """
    Attempt to move one file to its category folder.

    Returns (category_name, dest_folder_name) on success.
    Returns None if the file should be skipped.

    Loop prevention: files already inside a FOLDR category folder return None.
    Stateless: no session set, so files moved back to root get organized again.

    NO private imports from organizer.py — only public API and stdlib.
    """
    from foldr.config import CATEGORIES_TEMPLATE

    tmpl = template or CATEGORIES_TEMPLATE

    if not file_path.exists() or not file_path.is_file():
        return None

    try:
        file_parent   = file_path.parent.resolve()
        base_resolved = base.resolve()

        if file_parent != base_resolved:
            try:
                rel_parts = file_parent.relative_to(base_resolved).parts
            except ValueError:
                return None   # outside base entirely

            # File is in a direct child of base
            if rel_parts and rel_parts[0] in cat_folders:
                return None   # already in a FOLDR category folder

    except OSError:
        return None

    # Ignore patterns — self-contained, no private imports
    if _matches_ignore(file_path.name, ignore_patterns):
        logger.info("SKIP (ignored)      %s", file_path.name)
        return None

    # Classify by extension
    ext         = file_path.suffix.lower()
    cat_name:   str | None = None
    dest_folder: str | None = None

    for name, cat in tmpl.items():
        if ext in cat.get("ext", set()):
            cat_name    = name
            dest_folder = cat["folder"]
            break

    if not cat_name or not dest_folder:
        logger.info("SKIP (unknown ext)  %s", file_path.name)
        return None

    dest_dir  = base / dest_folder
    dest_path = dest_dir / file_path.name

    try:
        if file_path.resolve() == dest_path.resolve():
            return None
    except OSError:
        pass

    if dry_run:
        logger.info("PREVIEW  %s  ->  %s/", file_path.name, dest_folder)
        return cat_name, dest_folder

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        stem, suf, n = file_path.stem, file_path.suffix, 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_({n}){suf}"
            n += 1

    shutil.move(str(file_path), str(dest_path))
    logger.info("MOVED  %s  ->  %s/", file_path.name, dest_folder)
    return cat_name, dest_folder


# ── Core watcher ───────────────────────────────────────────────────────────────

def run_watch(
    base: Path,
    template: dict | None = None,
    dry_run: bool = False,
    recursive: bool = False,
    extra_ignore: list[str] | None = None,
    daemon_mode: bool = False,
) -> None:
    """
    Organize base immediately, then watch for future changes forever.

    Blocks until the process is killed (daemon_mode=True) or Ctrl+C (foreground).

    Parameters
    ----------
    base         : directory to watch and organize
    template     : category template; None = built-in defaults
    dry_run      : log but do not move files
    recursive    : also watch and organize subdirectories
    extra_ignore : glob patterns to skip (from --ignore flag)
    daemon_mode  : True when running as a background subprocess
    """
    try:
        from watchdog.observers import Observer              # type: ignore[import]
        from watchdog.events    import FileSystemEventHandler  # type: ignore[import]
    except ImportError:
        msg = "\n  watchdog not installed. Run: pip install watchdog\n"
        if daemon_mode:
            _get_logger(base).error("watchdog not installed")
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    logger          = _get_logger(base)
    ignore_patterns = list(extra_ignore or [])
    cat_folders     = _category_folder_names(template)

    def _log_move(filename: str, dest: str, category: str) -> None:
        logger.info("MOVED  %s  ->  %s/", filename, dest)
        if not daemon_mode:
            tag = f"  {COL_WARN}preview{RESET}" if dry_run else f"  {COL_OK}->{RESET}"
            ts  = time.strftime("%H:%M:%S")
            col = cat_fg(category)
            ico = cat_icon(category)
            print(
                f"{tag}  {FG_MUTED}{ts}{RESET}  "
                f"{col}{ico} {BOLD}{filename:<38}{RESET}  "
                f"{FG_MUTED}->{RESET}  {col}{dest}/{RESET}"
            )
            sys.stdout.flush()

    # ── Step 1: Register PID before anything else ─────────────────────────────
    if daemon_mode:
        try:
            from foldr.watches import _load, _save, add_watch
            data = _load()
            key  = str(base.resolve())
            if key in data:
                data[key]["pid"] = os.getpid()
                _save(data)
            else:
                add_watch(base, pid=os.getpid(), dry_run=dry_run, recursive=recursive)
            logger.info("PID registered  pid=%d", os.getpid())
        except Exception:
            logger.warning("PID registration failed:\n%s", traceback.format_exc())

    # ── Step 2: Initial scan ───────────────────────────────────────────────────
    logger.info("INITIAL SCAN START  recursive=%s", recursive)
    try:
        from foldr.organizer import organize_folder
        scan = organize_folder(
            base=base,
            dry_run=dry_run,
            recursive=recursive,
            extra_ignore=ignore_patterns,
            category_template=template,
        )
        n = len(scan.records)
        logger.info("INITIAL SCAN DONE  organized=%d", n)
        if n > 0:
            if not dry_run:
                save_history(scan.records, base, dry_run)
            for r in scan.records:
                _log_move(r.filename, Path(r.destination).parent.name, r.category)
        else:
            logger.info("INITIAL SCAN: already tidy")
    except Exception:
        logger.error("INITIAL SCAN FAILED:\n%s", traceback.format_exc())
        if not daemon_mode:
            print(
                f"\n  Initial scan error — see log:\n  {_log_file_path(base)}\n",
                file=sys.stderr,
            )

    # ── Step 3: Event queue ────────────────────────────────────────────────────
    _pending: dict[str, float] = {}
    _lock    = threading.Lock()
    _stop    = threading.Event()

    def _enqueue(path_str: str) -> None:
        if not path_str:
            return
        p = Path(path_str)
        try:
            base_res    = base.resolve()
            file_parent = p.parent.resolve()
            try:
                rel = file_parent.relative_to(base_res)
            except ValueError:
                return
            if rel.parts and rel.parts[0] in cat_folders:
                return
            if not recursive and file_parent != base_res:
                return
            if p.suffix.lower() in _IN_PROGRESS:
                return
        except OSError:
            return
        with _lock:
            _pending[str(p)] = time.monotonic()

    class _Handler(FileSystemEventHandler):   # type: ignore[misc]
        def on_created(self, event: object) -> None:    # type: ignore[override]
            if not getattr(event, "is_directory", False):
                _enqueue(str(_normalize_path(getattr(event, "src_path", ""))))

        def on_modified(self, event: object) -> None:   # type: ignore[override]
            if not getattr(event, "is_directory", False):
                _enqueue(str(_normalize_path(getattr(event, "src_path", ""))))

        def on_moved(self, event: object) -> None:      # type: ignore[override]
            if not getattr(event, "is_directory", False):
                dest = getattr(event, "dest_path", None)
                if dest:
                    _enqueue(str(_normalize_path(dest)))

    def _processor() -> None:
        """
        Drain the pending queue every 500 ms.
        Wrapped in try/except so a single bad file never kills the thread.
        """
        while not _stop.is_set():
            time.sleep(0.5)
            now = time.monotonic()
            with _lock:
                due = [ps for ps, t in list(_pending.items()) if now - t >= 0.5]
                for ps in due:
                    del _pending[ps]

            for ps in due:
                p = Path(ps)
                if not p.exists():
                    continue
                if not _file_stable(p):
                    continue

                try:
                    outcome = _organize_one(
                        p, base, template, dry_run,
                        ignore_patterns, logger, cat_folders,
                    )
                except Exception:
                    logger.error(
                        "_organize_one error for %s:\n%s", ps, traceback.format_exc()
                    )
                    continue

                if outcome is None:
                    continue

                cat, dest = outcome
                _log_move(p.name, dest, cat)

                if not dry_run:
                    try:
                        from foldr.organizer import OperationRecord
                        rec = OperationRecord(
                            op_id=uuid.uuid4().hex[:8],
                            source=ps,
                            destination=str(base / dest / p.name),
                            filename=p.name,
                            category=cat,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        save_history([rec], base, dry_run)
                    except Exception:
                        logger.warning("save_history failed:\n%s", traceback.format_exc())

                    if daemon_mode:
                        try:
                            from foldr.watches import increment_count
                            increment_count(base)
                        except Exception:
                            pass

    threading.Thread(target=_processor, daemon=True, name="foldr-processor").start()

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=recursive)
    observer.start()
    logger.info("OBSERVER STARTED  path=%s  recursive=%s", base, recursive)

    if daemon_mode:
        try:
            while not _stop.is_set():
                time.sleep(2)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            _stop.set()
            observer.stop()
            observer.join()
            logger.info("WATCH STOP  %s", base)
        return

    mode_str = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
    print(
        f"\n  Watching  {ACCENT}{BOLD}{base}{RESET}  [{mode_str}]\n"
        f"  {FG_MUTED}Existing files organized above (initial scan).{RESET}\n"
        f"  {FG_MUTED}New, moved, or re-dropped files organized automatically.{RESET}\n"
        f"  {FG_MUTED}Log: {_log_file_path(base)}{RESET}\n"
        f"  {FG_MUTED}Press Ctrl+C to stop.{RESET}\n"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  {FG_MUTED}Stopping...{RESET}")
    finally:
        _stop.set()
        observer.stop()
        observer.join()