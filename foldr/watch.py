"""
foldr.watch
~~~~~~~~~~~
Background directory watcher for FOLDR v4.

Modes
-----
1. Foreground (foldr watch ~/Downloads):
   Prints a live log to stdout. Ctrl+C to stop.

2. Background daemon (foldr _watch-daemon ~/Downloads):
   Spawned by foldr.watches.spawn_daemon(). Runs silently,
   writes to ~/.foldr/watch_logs/<dirname>.log, updates
   the file count in watches.json.

Key design decisions
--------------------
- No user approval per file. The user approved the whole directory
  when they ran 'foldr watch'.

- Event scoping: each file system event organizes ONLY the specific
  file that triggered it — not the whole directory. This prevents
  re-moving already-organized files.

- Cross-OS src_path handling: watchdog can return str, bytes,
  bytearray, or memoryview. Normalized at entry.

- Debounce: 500 ms window collapses rapid events (e.g. file writes
  that fire multiple events) into a single organize call.

- In-progress detection: files with download-in-progress extensions
  are skipped until they stop growing.
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
    ACCENT,
    BOLD,
    COL_OK,
    COL_WARN,
    FG_MUTED,
    RESET,
    cat_fg,
    cat_icon,
)
from foldr.history import save_history
from foldr.organizer import _classify_file, _matches_any

# Extensions that indicate the file is still being written
_IN_PROGRESS: frozenset[str] = frozenset({
    ".crdownload", ".part", ".tmp", ".download",
    ".partial", ".!ut", ".ytdl", ".aria2", ".opdownload",
})

_LOG_DIR = Path.home() / ".foldr" / "watch_logs"


# ── Utilities ──────────────────────────────────────────────────────────────────

def _normalize_path(src: object) -> Path:
    """
    Normalize watchdog's src_path to a Path.
    watchdog may return str, bytes, bytearray, or memoryview
    depending on the OS and version.
    """
    if isinstance(src, memoryview):
        src = bytes(src)
    if isinstance(src, (bytes, bytearray)):
        return Path(src.decode(errors="replace"))
    return Path(str(src))


def _file_stable(p: Path) -> bool:
    """
    Return True when the file has stopped growing (download complete).
    Waits 300 ms and compares file sizes.
    """
    try:
        before = p.stat().st_size
    except OSError:
        return False
    time.sleep(0.3)
    try:
        after = p.stat().st_size
        return after == before
    except OSError:
        return False


def _get_logger(base: Path) -> logging.Logger:
    """Return a file logger for this watched directory."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitize directory name for use as filename
    safe = (
        base.name
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )
    log_file = _LOG_DIR / f"{safe}.log"
    name     = f"foldr.watch.{safe}"
    logger   = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ── Single-file organizer ──────────────────────────────────────────────────────

def _organize_one(
    file_path: Path,
    base: Path,
    template: dict | None,
    dry_run: bool,
    ignore_patterns: list[str],
    logger: logging.Logger,
) -> tuple[str, str] | None:
    """
    Organize exactly one file into its category folder.
    Returns (category, dest_folder_name) on success, None if skipped.
    """
    from foldr.config import CATEGORIES_TEMPLATE

    tmpl = template or CATEGORIES_TEMPLATE

    # Guard: file must still exist and be directly inside base
    if not file_path.exists() or not file_path.is_file():
        return None
    try:
        if file_path.parent.resolve() != base.resolve():
            return None  # already in a category subfolder
    except OSError:
        return None

    # Ignore rules
    if _matches_any(file_path.name, str(file_path), ignore_patterns):
        logger.info("SKIP (ignored)      %s", file_path.name)
        return None

    # Classify by extension
    cat, dest_folder = _classify_file(file_path, tmpl)
    if not cat or not dest_folder:
        logger.info("SKIP (unknown ext)  %s", file_path.name)
        return None

    dest_dir  = base / dest_folder
    dest_path = dest_dir / file_path.name

    if dest_path == file_path:
        logger.info("SKIP (already here) %s", file_path.name)
        return None

    if dry_run:
        logger.info("PREVIEW  %s  ->  %s/", file_path.name, dest_folder)
        return cat, dest_folder

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Resolve name conflicts
    if dest_path.exists():
        stem, suf, n = file_path.stem, file_path.suffix, 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_({n}){suf}"
            n += 1

    shutil.move(str(file_path), str(dest_path))
    logger.info("MOVED  %s  ->  %s/", file_path.name, dest_folder)
    return cat, dest_folder


# ── Core watcher ───────────────────────────────────────────────────────────────

def run_watch(
    base: Path,
    template: dict | None = None,
    dry_run: bool = False,
    extra_ignore: list[str] | None = None,
    daemon_mode: bool = False,
) -> None:
    """
    Block until Ctrl+C (foreground) or process termination (daemon).

    Parameters
    ----------
    base          : directory to watch
    template      : category template (or None to use built-in defaults)
    dry_run       : log moves but don't actually move files
    extra_ignore  : additional ignore patterns from --ignore flag
    daemon_mode   : when True, use file-only logging and update watches.json
    """
    try:
        from watchdog.observers import Observer                          # type: ignore[import]
        from watchdog.events import FileSystemEventHandler              # type: ignore[import]
    except ImportError:
        msg = "\n  watchdog not installed.\n  Run: pip install watchdog\n"
        if daemon_mode:
            _get_logger(base).error("watchdog not installed")
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    logger          = _get_logger(base)
    ignore_patterns = list(extra_ignore or [])

    def _log_event(filename: str, dest: str, category: str) -> None:
        """Print to stdout (foreground only) and always write to log file."""
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

    # Debounce: collect events then process in bulk every 500 ms
    _pending: dict[str, float] = {}
    _lock    = threading.Lock()
    _seen_in_session: set[str] = set()
    _stop    = threading.Event()

    class _Handler(FileSystemEventHandler):  # type: ignore[misc]
        def _enqueue(self, event: object) -> None:
            if getattr(event, "is_directory", False):
                return
            p = _normalize_path(getattr(event, "src_path", ""))
            try:
                if p.parent.resolve() != base.resolve():
                    return
            except OSError:
                return
            if p.suffix.lower() in _IN_PROGRESS:
                return
            with _lock:
                _pending[str(p)] = time.monotonic()

        def on_created(self, event: object) -> None:   # type: ignore[override]
            self._enqueue(event)

        def on_modified(self, event: object) -> None:  # type: ignore[override]
            # Some browsers/downloaders fire modified, not created
            self._enqueue(event)

    def _processor() -> None:
        while not _stop.is_set():
            time.sleep(0.5)
            now = time.monotonic()
            with _lock:
                due = [ps for ps, t in list(_pending.items()) if now - t >= 0.5]
                for ps in due:
                    del _pending[ps]

            for ps in due:
                if ps in _seen_in_session:
                    continue
                p = Path(ps)
                if not p.exists():
                    continue
                if not _file_stable(p):
                    continue

                outcome = _organize_one(
                    p, base, template, dry_run, ignore_patterns, logger
                )
                if outcome is None:
                    continue

                cat, dest = outcome
                _seen_in_session.add(ps)
                _log_event(p.name, dest, cat)

                if not dry_run:
                    # Record in history so the user can undo
                    from foldr.organizer import OperationRecord  # local import avoids cycles
                    rec = OperationRecord(
                        op_id=uuid.uuid4().hex[:8],
                        source=ps,
                        destination=str(base / dest / p.name),
                        filename=p.name,
                        category=cat,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    save_history(
                        [rec], base, dry_run=False, op_type="organize"
                    )
                    # Update daemon counter in watches.json
                    if daemon_mode:
                        try:
                            from foldr.watches import increment_count
                            increment_count(base)
                        except Exception:
                            pass

    processor = threading.Thread(target=_processor, daemon=True)
    processor.start()

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=False)
    observer.start()

    if daemon_mode:
        logger.info("WATCH START  %s  dry_run=%s", base, dry_run)
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

    # Foreground mode
    mode = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
    print(
        f"\n  Watching  {ACCENT + BOLD}{base}{RESET}  [{mode}]\n"
        f"  {FG_MUTED}New files will be organized automatically.{RESET}\n"
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