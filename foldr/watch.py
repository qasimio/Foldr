"""
foldr.watch
~~~~~~~~~~~
Watch mode for FOLDR v4 — no Rich dependency.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

from foldr.term import (
    RESET, BOLD, MUTED, BCYN, BGRN, BYLW, cat_fg, cat_icon,
)
from foldr.organizer import organize_folder

_IN_PROGRESS = {".crdownload", ".part", ".tmp", ".download", ".partial"}


def run_watch(
    base: Path,
    template: dict,
    dry_run: bool = False,
    extra_ignore: list[str] | None = None,
    smart: bool = False,
    use_tui: bool = False,
) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events    import FileSystemEventHandler
    except ImportError:
        print(f"  {BYLW}watchdog required for watch mode:{RESET}  pip install watchdog",
              file=sys.stderr)
        sys.exit(1)

    # Set up TUI display if available
    watch_scr = None
    if use_tui:
        try:
            from foldr.tui import WatchScreen
            watch_scr = WatchScreen(base, dry_run)
        except Exception:
            watch_scr = None

    def _log_event(filename: str, dest: str, category: str) -> None:
        if watch_scr:
            watch_scr.add_event(filename, dest, category)
        else:
            tag = f"  {BYLW}[DRY]{RESET}" if dry_run else "     "
            col  = cat_fg(category)
            icon = cat_icon(category)
            ts   = time.strftime("%H:%M:%S")
            print(f"{tag}  {MUTED}{ts}{RESET}  {col}{icon} {BOLD}{filename:<40}{RESET}  "
                  f"{MUTED}→{RESET}  {col}{dest}/{RESET}")

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory: return
            src_path = event.src_path if isinstance(event.src_path, str) else str(event.src_path)
            p = Path(src_path)
            if p.suffix.lower() in _IN_PROGRESS: return
            time.sleep(0.3)
            if not p.exists(): return
            result = organize_folder(
                base=base, dry_run=dry_run, recursive=False,
                extra_ignore=extra_ignore or [],
                category_template=template or None,
            )
            for r in result.records:
                _log_event(r.filename, Path(r.destination).parent.name, r.category)

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=False)
    observer.start()

    if use_tui and watch_scr:
        try:
            watch_scr.run_blocking()
        except KeyboardInterrupt:
            pass
        finally:
            watch_scr.stop()
    else:
        mode = f"{BYLW}DRY RUN{RESET}" if dry_run else f"{BGRN}LIVE{RESET}"
        print(f"\n  {BCYN}Watching:{RESET}  {base}  [{mode}]")
        print(f"  {MUTED}Ctrl+C to stop.{RESET}\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n  {MUTED}Stopping…{RESET}")

    observer.stop()
    observer.join()

"""
# fixed watch
            if event.is_directory: return
            src_path = event.src_path if isinstance(event.src_path, str) else str(event.src_path)
            p = Path(src_path)
            if p.suffix.lower() in _IN_PROGRESS: return
"""