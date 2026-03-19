"""
foldr.watch
~~~~~~~~~~~
Background directory watcher for FOLDR v2.1.

What it does
------------
1. Runs an initial scan of the directory (organizes existing files).
2. Watches for new / moved / modified files and organizes them immediately.
3. Files moved back to root get re-organized (no _seen_in_session set).
4. Category-folder files are skipped to prevent infinite loops.

Cross-platform file events
--------------------------
  Linux   : inotify  (0% CPU when idle)
  macOS   : kqueue / FSEvents
  Windows : ReadDirectoryChangesW

No rich, no pyfiglet, no TUI — plain terminal output.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from foldr.term import (
    ACCENT, BOLD, COL_OK, COL_WARN, FG_MUTED, RESET,
    cat_fg, cat_icon,
)
from foldr.history import save_history

_IN_PROGRESS: frozenset[str] = frozenset({
    ".crdownload", ".part", ".tmp", ".download",
    ".partial", ".!ut", ".ytdl", ".aria2", ".opdownload",
})

_LOG_DIR = Path.home() / ".foldr" / "watch_logs"


def _matches_ignore(filename: str, patterns: list[str]) -> bool:
    """
    Check whether filename matches any ignore pattern.
    Uses stdlib fnmatch only — zero dependency on organizer private API.
    """
    import fnmatch
    if not patterns:
        return False
    low = filename.lower()
    for pat in patterns:
        clean = pat.rstrip("/")
        if fnmatch.fnmatch(filename, clean) or fnmatch.fnmatch(low, clean.lower()):
            return True
    return False


# ── Utilities ──────────────────────────────────────────────────────────────────

def _normalize_path(src: object) -> Path:
    """Normalize watchdog src_path (str/bytes/bytearray/memoryview)."""
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
    time.sleep(0.4)
    try:
        return p.stat().st_size == before
    except OSError:
        return False


def _get_logger(base: Path) -> logging.Logger:
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


def _category_folder_names(template: dict | None) -> set[str]:
    """Return the set of folder names FOLDR creates (for loop prevention)."""
    from foldr.config import CATEGORIES_TEMPLATE
    tmpl = template or CATEGORIES_TEMPLATE
    return {v["folder"] for v in tmpl.values()}


# ── Single-file organizer ──────────────────────────────────────────────────────

def _organize_one(
    file_path: Path,
    base: Path,
    template: dict | None,
    dry_run: bool,
    ignore_patterns: list[str],
    logger: logging.Logger,
    cat_folders: set[str],
) -> tuple[str, Path] | None:
    """
    Organize exactly one file.

    Loop prevention: if the file is currently inside a FOLDR category folder,
    skip it. This replaces _seen_in_session — it's stateless and correct even
    when files are moved back to root.
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
                rel = file_parent.relative_to(base_resolved)
                if rel.parts and rel.parts[0] in cat_folders:
                    return None   # already in a category folder
            except ValueError:
                return None       # outside base
    except OSError:
        return None

    # Ignore rules — inline fnmatch, no private organizer imports
    if ignore_patterns and _matches_ignore(file_path.name, ignore_patterns):
        logger.info("SKIP (ignored)      %s", file_path.name)
        return None

    # Classify
    ext = file_path.suffix.lower()
    cat_name: str | None = None
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
        return cat_name, dest_path

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        stem, suf, n = file_path.stem, file_path.suffix, 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_({n}){suf}"
            n += 1

    shutil.move(str(file_path), str(dest_path))
    logger.info("MOVED  %s  ->  %s/", file_path.name, dest_path.parent.name)
    return cat_name, dest_path


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

    Parameters
    ----------
    base          : directory to watch
    template      : category template (None = built-in defaults)
    dry_run       : log but don't move files
    recursive     : watch subdirectories too
    extra_ignore  : patterns from --ignore flag
    daemon_mode   : True when spawned as background daemon
    """
    try:
        from watchdog.observers import Observer               # type: ignore[import]
        from watchdog.events import FileSystemEventHandler   # type: ignore[import]
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

    def _log(filename: str, dest: Path | str, category: str) -> None:
        dest_name = Path(dest).parent.name
        logger.info("-> %s  =>  %s/", filename, dest_name)
        if not daemon_mode:
            tag = f"  {COL_WARN}preview{RESET}" if dry_run else f"  {COL_OK}->{RESET}"
            ts  = time.strftime("%H:%M:%S")
            col = cat_fg(category)
            ico = cat_icon(category)
            print(
                f"{tag}  {FG_MUTED}{ts}{RESET}  "
                f"{col}{ico} {BOLD}{filename:<38}{RESET}  "
                f"{FG_MUTED}->{RESET}  {col}{dest_name}/{RESET}"
            )
            sys.stdout.flush()

    # ── Step 1: initial scan ───────────────────────────────────────────────────
    logger.info("INITIAL SCAN  %s  recursive=%s", base, recursive)
    try:
        from foldr.organizer import organize_folder
        result = organize_folder(
            base=base,
            dry_run=dry_run,
            recursive=recursive,
            extra_ignore=ignore_patterns,
            category_template=template,
        )
        n = len(result.records)
        logger.info("INITIAL SCAN: %d files organized", n)
        if n > 0 and not dry_run:
            save_history(result.records, base, dry_run)
        for r in result.records:
            _log(r.filename, Path(r.destination), r.category)
    except Exception:
        import traceback as _tb
        logger.error("INITIAL SCAN ERROR:\n%s", _tb.format_exc())
        if not daemon_mode:
            import traceback as _tb2
            print(f"\n  Watch initial scan failed. See log for details.", file=sys.stderr)

    # ── Step 2: update PID in watches.json (daemon restart fix) ───────────────
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
        except Exception as exc:
            logger.warning("PID update failed: %s", exc)

    # ── Step 3: event watcher ──────────────────────────────────────────────────
    _pending: dict[str, float] = {}
    _lock    = threading.Lock()
    _stop    = threading.Event()

    def _enqueue(path_str: str) -> None:
        p = Path(path_str)
        try:
            base_res = base.resolve()
            parent   = p.parent.resolve()
            try:
                rel = parent.relative_to(base_res)
                if rel.parts and rel.parts[0] in cat_folders:
                    return   # already in a category folder — ignore
            except ValueError:
                return       # outside base
            if not recursive and parent != base_res:
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
            # Fires when a file is dragged / moved INTO the watched folder
            if not getattr(event, "is_directory", False):
                dest = getattr(event, "dest_path", None)
                if dest:
                    _enqueue(str(_normalize_path(dest)))

    def _processor() -> None:
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
                    import traceback
                    logger.error("_organize_one error for %s:\n%s", ps, traceback.format_exc())
                    continue
                if outcome is None:
                    continue
                cat, dest_path = outcome
                _log(p.name, dest_path, cat)
                if not dry_run:
                    from foldr.organizer import OperationRecord
                    rec = OperationRecord(
                        op_id=uuid.uuid4().hex[:8],
                        source=ps,
                        destination=str(dest_path),
                        filename=p.name,
                        category=cat,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    save_history([rec], base, dry_run)
                    if daemon_mode:
                        try:
                            from foldr.watches import increment_count
                            increment_count(base)
                        except Exception:
                            pass

    threading.Thread(target=_processor, daemon=True).start()

    observer = None
    start_errors: list[str] = []

    try:
        from watchdog.observers import Observer  # type: ignore[import]
        observer = Observer()
        observer.schedule(_Handler(), str(base), recursive=recursive)
        observer.start()
    except Exception as exc:
        start_errors.append(f"watchdog: {exc!s}")
        try:
            from watchdog.observers.polling import PollingObserver  # type: ignore[import]
            observer = PollingObserver(timeout=1.0)
            observer.schedule(_Handler(), str(base), recursive=recursive)
            observer.start()
            logger.warning("Using polling observer fallback for %s", base)
            if not daemon_mode:
                print(f"  {FG_MUTED}watchdog backend unavailable, using polling observer.{RESET}")
        except Exception as exc2:
            start_errors.append(f"polling: {exc2!s}")
            msg = "Could not start filesystem watcher: " + "; ".join(start_errors)
            logger.error(msg)
            if not daemon_mode:
                print(f"\n  {msg}", file=sys.stderr)
            sys.exit(1)

    if daemon_mode:
        logger.info("WATCHING  %s", base)
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

    # Foreground
    mode = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
    print(
        f"\n  Watching  {ACCENT}{BOLD}{base}{RESET}  [{mode}]\n"
        f"  {FG_MUTED}New and modified files will be organized automatically.{RESET}\n"
        f"  {FG_MUTED}Files moved back to root will be re-organized.{RESET}\n"
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