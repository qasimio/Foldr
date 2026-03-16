"""
foldr.watch
~~~~~~~~~~~
Watch mode: persistent background directory organizer.

Two modes
---------
1. Foreground (interactive):
     foldr watch ~/Downloads
     Shows live log. Press Ctrl+C to stop.

2. Background daemon:
     foldr _watch-daemon ~/Downloads
     Called internally by cli.py when spawning a detached process.
     Writes logs to ~/.foldr/watch_logs/<dir>.log
     Updates ~/.foldr/watches.json on each file processed.

Key design decisions
--------------------
- NO user approval per-file: the user already approved when they ran
  `foldr watch`. After that, every file is organized automatically,
  silently, no prompts.

- Event scoping: on_created only organizes the SPECIFIC file that arrived,
  not the entire directory. This prevents re-moving already-organized files.

- Cross-OS src_path normalization: watchdog can return bytes or str or
  a memoryview on different platforms. Handled explicitly.

- In-progress download detection: skips .crdownload/.part etc. and
  waits for file to stabilize (size unchanged for 0.3s) before moving.

- Watch/unwatch pair:
    foldr watch ~/Downloads     → start (background daemon)
    foldr unwatch ~/Downloads   → stop
    foldr watches               → list all active watches
"""
from __future__ import annotations
import os, sys, time, logging, platform, threading
from pathlib import Path
from datetime import datetime, timezone

from foldr.term import (
    RESET, BOLD, FG_DIM, FG_MUTED, ACCENT, COL_OK, COL_WARN, COL_ERR,
    cat_fg, cat_icon,
)
from foldr.organizer import organize_folder, _matches_any
from foldr.history   import save_history

_IN_PROGRESS = {
    ".crdownload", ".part", ".tmp", ".download", ".partial",
    ".!ut", ".ytdl", ".aria2", ".opdownload",
}

_LOG_DIR = Path.home() / ".foldr" / "watch_logs"


def _normalize_path(src) -> Path:
    """
    Normalize watchdog src_path which can be str, bytes, bytearray,
    or memoryview depending on OS and watchdog version.
    """
    if isinstance(src, memoryview):
        src = bytes(src)
    if isinstance(src, (bytes, bytearray)):
        src = src.decode(errors="replace")
    return Path(str(src))


def _file_stable(p: Path, timeout: float = 1.0) -> bool:
    """
    Wait until a file stops growing (download complete).
    Returns False if the file disappears.
    """
    try:
        prev = p.stat().st_size
        time.sleep(0.3)
        if not p.exists(): return False
        curr = p.stat().st_size
        return curr == prev
    except OSError:
        return False


def _get_watch_logger(base: Path) -> logging.Logger:
    """Get/create a logger that writes to ~/.foldr/watch_logs/<dirname>.log"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = base.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    log_file  = _LOG_DIR / f"{safe_name}.log"

    logger = logging.getLogger(f"foldr.watch.{safe_name}")
    if not logger.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ── Single-file organizer (scoped to one file) ─────────────────────────────────

def _organize_one(
    file_path: Path,
    base: Path,
    template: dict | None,
    dry_run: bool,
    ignore_patterns: list[str],
    logger: logging.Logger,
) -> tuple[str, str] | None:
    """
    Move a single file into its category folder within base.
    Returns (category, dest_folder_name) or None if skipped/error.
    """
    from foldr.config import CATEGORIES_TEMPLATE
    from foldr.organizer import _classify_file

    tmpl = template or CATEGORIES_TEMPLATE

    # Re-check file exists and is in base
    if not file_path.exists(): return None
    if not file_path.is_file(): return None
    if file_path.parent.resolve() != base.resolve(): return None  # already in sub-dir

    # Apply ignore rules
    if _matches_any(file_path.name, str(file_path), ignore_patterns):
        logger.info(f"SKIP (ignored)  {file_path.name}")
        return None

    # Classify
    cat, dest_folder = _classify_file(file_path, tmpl)
    if not cat or not dest_folder:
        logger.info(f"SKIP (unknown ext)  {file_path.name}")
        return None

    dest_dir  = base / dest_folder
    dest_path = dest_dir / file_path.name

    # Conflict resolution
    if dest_path == file_path:
        logger.info(f"SKIP (already there)  {file_path.name}")
        return None

    if dry_run:
        logger.info(f"PREVIEW  {file_path.name}  ->  {dest_folder}/")
        return cat, dest_folder

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        stem = file_path.stem; suf = file_path.suffix; n = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_({n}){suf}"; n+=1

    import shutil
    shutil.move(str(file_path), str(dest_path))
    logger.info(f"MOVED  {file_path.name}  ->  {dest_folder}/")
    return cat, dest_folder


# ── Core watcher (runs in foreground) ────────────────────────────────────────

def run_watch(
    base: Path,
    template: dict | None = None,
    dry_run: bool = False,
    extra_ignore: list[str] | None = None,
    use_tui: bool = False,
    daemon_mode: bool = False,
) -> None:
    """
    Block until Ctrl+C (or process kill in daemon mode).

    Arguments
    ---------
    base          : directory to watch
    template      : category template (from config)
    dry_run       : log only, don't move files
    extra_ignore  : patterns from --ignore flag
    use_tui       : show TUI WatchScreen (foreground only)
    daemon_mode   : True when running as background daemon
                    (uses file logging, updates watches.json counts)
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events    import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    except ImportError:
        _msg = (
            "\n  watchdog is not installed.\n\n"
            "  Install it:  pip install watchdog\n"
        )
        if daemon_mode:
            logger = _get_watch_logger(base)
            logger.error("watchdog not installed")
        else:
            print(_msg, file=sys.stderr)
        sys.exit(1)

    logger         = _get_watch_logger(base)
    ignore_patterns = list(extra_ignore or [])
    watch_scr       = None

    if use_tui and not daemon_mode:
        try:
            from foldr.tui import WatchScreen
            watch_scr = WatchScreen(base, dry_run)
        except Exception:
            watch_scr = None

    def _log_event(filename: str, dest: str, category: str) -> None:
        if watch_scr:
            watch_scr.add_event(filename, dest, category)
        elif not daemon_mode:
            tag = f"  {COL_WARN}preview{RESET}" if dry_run else f"  {COL_OK}->{RESET}"
            ts  = time.strftime("%H:%M:%S")
            col = cat_fg(category)
            ico = cat_icon(category)
            print(f"{tag}  {FG_MUTED}{ts}{RESET}  {col}{ico} {BOLD}{filename:<38}{RESET}  {FG_MUTED}->{RESET}  {col}{dest}/{RESET}")
            sys.stdout.flush()

    # Batch collector — debounce rapid events
    _pending: dict[str, float] = {}   # path → time first seen
    _lock    = threading.Lock()
    _processed_in_session: set[str] = set()  # avoid re-processing

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory: return
            p = _normalize_path(event.src_path)
            # Only process files directly in base (not in sub-dirs)
            try:
                if p.parent.resolve() != base.resolve(): return
            except Exception: return
            # Skip in-progress
            if p.suffix.lower() in _IN_PROGRESS: return
            with _lock:
                _pending[str(p)] = time.monotonic()

        def on_modified(self, event):
            # Some editors/downloaders fire modified instead of created
            if event.is_directory: return
            p = _normalize_path(event.src_path)
            try:
                if p.parent.resolve() != base.resolve(): return
            except Exception: return
            if p.suffix.lower() in _IN_PROGRESS: return
            with _lock:
                _pending[str(p)] = time.monotonic()

    def _processor():
        """Runs in a thread. Processes debounced events every 0.5s."""
        while not _stop.is_set():
            time.sleep(0.5)
            now = time.monotonic()
            with _lock:
                due = [ps for ps, t in list(_pending.items())
                       if now - t > 0.5]  # 500ms debounce
                for ps in due:
                    del _pending[ps]

            for ps in due:
                p = Path(ps)
                if str(p) in _processed_in_session: continue
                if not p.exists(): continue
                if not _file_stable(p): continue

                result = _organize_one(
                    p, base, template, dry_run, ignore_patterns, logger
                )
                if result:
                    cat, dest = result
                    _processed_in_session.add(str(p))
                    _log_event(p.name, dest, cat)

                    if not dry_run:
                        # Save to history (single-file record)
                        from foldr.organizer import OperationRecord
                        import uuid
                        rec = OperationRecord(
                            op_id=uuid.uuid4().hex[:8],
                            source=str(p),
                            destination=str(base/dest/p.name),
                            filename=p.name,
                            category=cat,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        save_history([rec], base, dry_run=False, op_type="organize")

                        # Update daemon counter
                        if daemon_mode:
                            try:
                                from foldr.watches import increment_count
                                increment_count(base)
                            except Exception:
                                pass

    _stop = threading.Event()
    processor_thread = threading.Thread(target=_processor, daemon=True)
    processor_thread.start()

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=False)
    observer.start()

    if daemon_mode:
        logger.info(f"WATCH START  {base}  dry_run={dry_run}")
        try:
            while not _stop.is_set():
                time.sleep(2)
                # Heartbeat in log every 60s
        except KeyboardInterrupt:
            pass
        finally:
            _stop.set(); observer.stop(); observer.join()
            logger.info(f"WATCH STOP  {base}")
        return

    # Foreground mode
    try:
        if use_tui and watch_scr:
            watch_scr.run_blocking()
        else:
            mode = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
            print(f"\n  Watching  {ACCENT+BOLD}{base}{RESET}  [{mode}]")
            print(f"  {FG_MUTED}New files dropped here will be organized automatically.{RESET}")
            print(f"  {FG_MUTED}Press Ctrl+C to stop.  Run 'foldr watches' to check status.{RESET}\n")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  {FG_MUTED}Stopping...{RESET}")
    finally:
        _stop.set(); observer.stop(); observer.join()
        if watch_scr: watch_scr.stop()
