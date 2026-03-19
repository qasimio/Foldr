"""
foldr.watch
~~~~~~~~~~~
Background directory watcher for FOLDR v2.1.

What it does
------------
1. Registers the daemon PID in watches.json immediately (before anything else).
2. Runs an initial scan so existing unorganized files are moved right away.
3. Watches forever for new / moved / modified files and organizes them.
4. Files moved back to root get re-organized (no _seen_in_session blocking).
5. Category-folder files are skipped to prevent infinite loops.

Bug fixes in this version
--------------------------
- Removed dependency on private `_matches_any` from organizer.py.
  Ignore matching is now done inline with fnmatch — no private API needed.
- Daemon stderr is redirected to the log file (not DEVNULL) so crashes
  are visible: check ~/.foldr/watch_logs/<dirname>.log
- PID is registered in watches.json BEFORE the initial scan, so
  `foldr watches` shows the entry immediately even during a slow first scan.
- Initial scan errors are logged with full tracebacks, not swallowed silently.

Cross-platform
--------------
  Linux   : inotify  (0% CPU when idle)
  macOS   : kqueue / FSEvents
  Windows : ReadDirectoryChangesW

No rich, no pyfiglet, no TUI — plain terminal output only.
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

_IN_PROGRESS: frozenset[str] = frozenset({
    ".crdownload", ".part", ".tmp", ".download",
    ".partial", ".!ut", ".ytdl", ".aria2", ".opdownload",
})

_LOG_DIR = Path.home() / ".foldr" / "watch_logs"


# ── Utilities ──────────────────────────────────────────────────────────────────

def _normalize_path(src: object) -> Path:
    """Normalize watchdog src_path (str / bytes / bytearray / memoryview)."""
    if isinstance(src, memoryview):
        src = bytes(src)
    if isinstance(src, (bytes, bytearray)):
        return Path(src.decode(errors="replace"))
    return Path(str(src))


def _file_stable(p: Path, wait: float = 0.4) -> bool:
    """Return True when the file has stopped growing (download complete)."""
    try:
        before = p.stat().st_size
    except OSError:
        return False
    time.sleep(wait)
    try:
        return p.stat().st_size == before
    except OSError:
        return False


def _get_logger(base: Path) -> logging.Logger:
    """Return a per-directory file logger."""
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


def _log_path(base: Path) -> Path:
    safe = base.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    return _LOG_DIR / f"{safe}.log"


def _category_folder_names(template: dict | None) -> set[str]:
    """
    Return the set of folder names FOLDR creates inside the watched dir.
    Used to skip already-organized files (loop prevention).
    Does NOT import private functions from organizer.
    """
    from foldr.config import CATEGORIES_TEMPLATE
    tmpl = template or CATEGORIES_TEMPLATE
    return {v["folder"] for v in tmpl.values()}


def _matches_ignore(name: str, patterns: list[str]) -> bool:
    """
    Return True if `name` matches any ignore pattern.
    Self-contained — does not use private organizer internals.
    """
    for pattern in patterns:
        pat = pattern.rstrip("/")
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(name.lower(), pat.lower()):
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
    Move one file to its category folder.
    Returns (category_name, dest_folder_name) or None if skipped.

    Loop prevention: files already inside a FOLDR category folder are skipped.
    Re-org: files moved back to root will be organized again (no session set).
    """
    from foldr.config import CATEGORIES_TEMPLATE

    tmpl = template or CATEGORIES_TEMPLATE

    # File must exist and be a real file
    if not file_path.exists() or not file_path.is_file():
        return None

    # Determine whether file is directly in base or in a subdir
    try:
        file_parent   = file_path.parent.resolve()
        base_resolved = base.resolve()

        if file_parent != base_resolved:
            # File is in a subdirectory — check if it's inside a category folder
            try:
                rel_parts = file_parent.relative_to(base_resolved).parts
            except ValueError:
                return None  # outside base entirely — ignore

            if rel_parts and rel_parts[0] in cat_folders:
                # Already in a FOLDR category folder — do not re-move
                return None
            # Otherwise it's a genuine subdirectory file (recursive mode)
    except OSError:
        return None

    # Apply ignore patterns (self-contained, no private imports)
    if ignore_patterns and _matches_ignore(file_path.name, ignore_patterns):
        logger.info("SKIP (ignored)      %s", file_path.name)
        return None

    # Classify by extension
    ext      = file_path.suffix.lower()
    cat_name: str | None    = None
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

    # Skip if already in the right place
    try:
        if file_path.resolve() == dest_path.resolve():
            return None
    except OSError:
        pass

    if dry_run:
        logger.info("PREVIEW  %s  ->  %s/", file_path.name, dest_folder)
        return cat_name, dest_folder

    # Move
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
    Start the FOLDR watcher for `base`. Blocks until stopped.

    Execution order
    ---------------
    1. Register PID in watches.json immediately (so `foldr watches` works).
    2. Organize all existing files in base (initial scan).
    3. Watch for new/moved/modified files forever.

    Parameters
    ----------
    base         : directory to watch and organize
    template     : category template dict (None = built-in defaults)
    dry_run      : log moves but don't actually move files
    recursive    : also watch and organize subdirectories
    extra_ignore : glob patterns to skip (from --ignore flag)
    daemon_mode  : True when running as a background daemon process
    """
    try:
        from watchdog.observers import Observer               # type: ignore[import]
        from watchdog.events    import FileSystemEventHandler  # type: ignore[import]
    except ImportError:
        msg = "\n  watchdog is not installed. Run:  pip install watchdog\n"
        if daemon_mode:
            # Can't use logger yet — write directly
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            _log_path(base).open("a").write(
                f"{datetime.now().isoformat()}  ERROR    watchdog not installed\n"
            )
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    logger          = _get_logger(base)
    ignore_patterns = list(extra_ignore or [])
    cat_folders     = _category_folder_names(template)

    # ── STEP 1: Register PID immediately ──────────────────────────────────────
    # This must happen BEFORE the initial scan so that `foldr watches` shows
    # the entry right away, even during a slow first organization pass.
    # On reboot: the daemon restarts with a new PID — write it here so the
    # old (dead) PID is replaced before get_watches() can clean it up.
    if daemon_mode:
        try:
            from foldr.watches import _load, _save, add_watch
            data = _load()
            key  = str(base.resolve())
            if key in data:
                data[key]["pid"] = os.getpid()
                _save(data)
            else:
                # Entry was deleted (e.g. manual edit) — recreate it
                add_watch(
                    base, pid=os.getpid(),
                    dry_run=dry_run, recursive=recursive,
                )
            logger.info("PID registered: %d  base: %s", os.getpid(), base)
        except Exception:
            logger.warning("PID registration failed:\n%s", traceback.format_exc())

    # ── Helper: format one event line for terminal / log ──────────────────────
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

    # ── STEP 2: Initial scan ───────────────────────────────────────────────────
    logger.info("INITIAL SCAN START  path=%s  recursive=%s", base, recursive)
    initial_scan_ok = False
    try:
        from foldr.organizer import organize_folder
        scan_result = organize_folder(
            base=base,
            dry_run=dry_run,
            recursive=recursive,
            extra_ignore=ignore_patterns,
            category_template=template,
        )
        n = len(scan_result.records)
        logger.info("INITIAL SCAN DONE  organized=%d", n)
        initial_scan_ok = True

        if n > 0:
            if not dry_run:
                save_history(scan_result.records, base, dry_run)
            for r in scan_result.records:
                _log_move(r.filename, Path(r.destination).parent.name, r.category)
        else:
            logger.info("INITIAL SCAN: directory already tidy")

    except Exception:
        tb = traceback.format_exc()
        logger.error("INITIAL SCAN FAILED:\n%s", tb)
        if not daemon_mode:
            print(f"\n  Initial scan error (check log for details):\n{tb}",
                  file=sys.stderr)

    # ── STEP 3: File system event watcher ─────────────────────────────────────
    _pending: dict[str, float] = {}
    _lock    = threading.Lock()
    _stop    = threading.Event()

    def _enqueue(path_str: str) -> None:
        """Add a file path to the pending queue for processing."""
        if not path_str:
            return
        p = Path(path_str)
        try:
            base_res    = base.resolve()
            file_parent = p.parent.resolve()

            # Check if path is inside base at all
            try:
                rel = file_parent.relative_to(base_res)
            except ValueError:
                return  # file is outside the watched directory

            # Skip files already inside a FOLDR category folder
            if rel.parts and rel.parts[0] in cat_folders:
                return

            # In non-recursive mode, only handle files directly in base
            if not recursive and file_parent != base_res:
                return

            # Skip in-progress downloads
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
            # Some editors and download managers fire modified instead of created
            if not getattr(event, "is_directory", False):
                _enqueue(str(_normalize_path(getattr(event, "src_path", ""))))

        def on_moved(self, event: object) -> None:      # type: ignore[override]
            # Fired when a file is dragged/moved INTO the watched folder from elsewhere
            if not getattr(event, "is_directory", False):
                dest = getattr(event, "dest_path", None)
                if dest:
                    _enqueue(str(_normalize_path(dest)))

    def _processor() -> None:
        """Background thread: drain the pending queue every 500 ms."""
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
                    logger.error("_organize_one error for %s:\n%s",
                                 ps, traceback.format_exc())
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
                        logger.warning("save_history failed:\n%s",
                                       traceback.format_exc())

                    if daemon_mode:
                        try:
                            from foldr.watches import increment_count
                            increment_count(base)
                        except Exception:
                            pass

    # Start processor thread and observer
    processor_thread = threading.Thread(target=_processor, daemon=True, name="foldr-processor")
    processor_thread.start()

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=recursive)
    observer.start()
    logger.info("OBSERVER STARTED  path=%s  recursive=%s", base, recursive)

    # ── Daemon mode: block until killed ───────────────────────────────────────
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

    # ── Foreground mode: print status and wait for Ctrl+C ─────────────────────
    mode = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
    print(
        f"\n  Watching  {ACCENT}{BOLD}{base}{RESET}  [{mode}]\n"
        f"  {FG_MUTED}Existing files were organized above (initial scan).{RESET}\n"
        f"  {FG_MUTED}New files, moved files, and re-dropped files will be organized automatically.{RESET}\n"
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