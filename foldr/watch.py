"""
foldr.watch
~~~~~~~~~~~
Watch mode for FOLDR v4.

What it does
------------
Monitors a directory using the OS filesystem event API (watchdog).
Every time a new file appears, it automatically organizes it into the
correct category folder — just like running `foldr <dir>` but instantly.

Use cases
---------
  - Auto-sort Downloads: files land → instantly categorized
  - Server ingest: drop files into a folder → auto-filed
  - Any "hot folder" workflow

How to stop
-----------
  Press Ctrl+C in the terminal. Watch mode will finish any in-progress
  move before stopping cleanly.

Edge cases handled
------------------
  - In-progress downloads: .crdownload/.part files are skipped until complete
  - Rapid-fire events: 300ms debounce before processing
  - Files that vanish (renamed/deleted during the gap): silently skipped
"""
from __future__ import annotations
import sys, time
from pathlib import Path

from foldr.term import (
    RESET, BOLD, FG_DIM, FG_MUTED, ACCENT, COL_OK, COL_WARN, cat_fg, cat_icon,
)
from foldr.organizer import organize_folder
from foldr.history   import save_history

_IN_PROGRESS = {".crdownload", ".part", ".tmp", ".download", ".partial", ".!ut"}


def run_watch(
    base: Path,
    template: dict,
    dry_run: bool = False,
    extra_ignore: list[str] | None = None,
    smart: bool = False,
    use_tui: bool = False,
) -> None:
    """
    Block until Ctrl+C, organizing files as they arrive.

    Arguments
    ---------
    base          : directory to watch
    template      : category template (from config)
    dry_run       : if True, print what would happen but don't move
    extra_ignore  : patterns to skip (from --ignore)
    smart         : use MIME detection (from --smart)
    use_tui       : show TUI WatchScreen instead of plain log
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events    import FileSystemEventHandler
    except ImportError:
        print(
            f"\n  {COL_WARN}watchdog is not installed.{RESET}\n\n"
            f"  Install it:  pip install watchdog\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # TUI or plain log
    watch_scr = None
    if use_tui:
        try:
            from foldr.tui import WatchScreen
            watch_scr = WatchScreen(base, dry_run)
        except Exception:
            watch_scr = None

    def _log(filename: str, dest: str, category: str) -> None:
        if watch_scr:
            watch_scr.add_event(filename, dest, category)
        else:
            tag  = f"  {COL_WARN}preview{RESET}" if dry_run else f"  {COL_OK}→{RESET}"
            ts   = time.strftime("%H:%M:%S")
            col  = cat_fg(category)
            ico  = cat_icon(category)
            print(f"{tag}  {FG_MUTED}{ts}{RESET}  {col}{ico} {BOLD}{filename:<38}{RESET}  {FG_MUTED}→{RESET}  {col}{dest}/{RESET}")

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory: return
            if isinstance(event.src_path, (bytes, bytearray, memoryview)):
                if isinstance(event.src_path, memoryview):
                    src_path = event.src_path.tobytes().decode()
                elif isinstance(event.src_path, (bytes, bytearray)):
                    src_path = event.src_path.decode()
                else:
                    src_path = str(event.src_path)
            else:
                src_path = event.src_path
            p = Path(str(src_path))

            # Skip in-progress downloads
            if p.suffix.lower() in _IN_PROGRESS: return

            # Debounce: wait for writes to finish
            time.sleep(0.3)
            if not p.exists(): return

            result = organize_folder(
                base=base,
                dry_run=dry_run,
                recursive=False,
                extra_ignore=extra_ignore or [],
                category_template=template or None,
            )
            if result.records and not dry_run:
                save_history(result.records, base, dry_run=False, op_type="organize")
            for r in result.records:
                _log(r.filename, Path(r.destination).parent.name, r.category)

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=False)
    observer.start()

    try:
        if use_tui and watch_scr:
            watch_scr.run_blocking()
        else:
            mode = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
            print(f"\n  Watching  {ACCENT+BOLD}{base}{RESET}  [{mode}]")
            print(f"  {FG_MUTED}Ctrl+C to stop.{RESET}\n")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  {FG_MUTED}Stopping watch mode…{RESET}")
    finally:
        observer.stop()
        observer.join()

    if watch_scr:
        watch_scr.stop()