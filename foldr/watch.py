"""
foldr.watch
~~~~~~~~~~~
Watch mode — uses watchdog + optional WatchScreen TUI.
"""
from __future__ import annotations
import sys, time, threading
from pathlib import Path

from foldr.organizer import organize_folder
from foldr import output as out
from foldr.ansi import BCYAN, BYELLOW, BGREEN, RESET, BOLD, MUTED

_IN_PROGRESS = {".crdownload", ".part", ".tmp", ".download", ".partial"}


def run_watch(
    base: Path,
    template: dict,
    dry_run: bool = False,
    extra_ignore: list[str] | None = None,
    smart: bool = False,
    use_tui: bool = True,
) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events    import FileSystemEventHandler
    except ImportError:
        out.error(
            "watchdog is required for watch mode.\n"
            "  Install: pip install watchdog"
        )
        sys.exit(1)

    # ── Set up display ────────────────────────────────────────────────────────
    watch_scr = None
    if use_tui:
        from foldr.tui import WatchScreen
        watch_scr = WatchScreen(base, dry_run)

    def _on_event(filename: str, dest: str, category: str) -> None:
        if watch_scr:
            watch_scr.add_event(filename, dest, category)
        elif not getattr(out, 'args_quiet', False):
            tag = f"  {BYELLOW}{BOLD}[DRY]{RESET}" if dry_run else "     "
            from foldr.ansi import cat_col, cat_icon
            col  = cat_col(category)
            icon = cat_icon(category)
            print(
                f"{tag}  {col}{icon}{RESET}  "
                f"{col}{BOLD}{filename:<40}{RESET}  "
                f"{MUTED}→{RESET}  {col}{dest}/{RESET}"
            )

    # ── Watchdog handler ──────────────────────────────────────────────────────
    class FoldrHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            src_path = event.src_path if isinstance(event.src_path, str) else bytes(event.src_path).decode('utf-8')
            p = Path(src_path)
            if p.suffix.lower() in _IN_PROGRESS:
                return
            time.sleep(0.3)
            if not p.exists():
                return

            result = organize_folder(
                base=base,
                dry_run=dry_run,
                recursive=False,
                extra_ignore=extra_ignore or [],
                category_template=template or None,
                smart=smart,
            )
            for r in result.records:
                dest = Path(r.destination).parent.name
                _on_event(r.filename, dest, r.category)

    observer = Observer()
    observer.schedule(FoldrHandler(), str(base), recursive=False)
    observer.start()

    if use_tui and watch_scr:
        # Run TUI in main thread, watchdog in background
        try:
            watch_scr.run_blocking()
        except KeyboardInterrupt:
            pass
        finally:
            watch_scr.stop()
    else:
        mode = f"{BYELLOW}DRY RUN{RESET}" if dry_run else f"{BGREEN}LIVE{RESET}"
        print(f"\n  {BCYAN}Watching:{RESET}  {base}  [{mode}]")
        print(f"  {MUTED}Press Ctrl+C to stop.{RESET}\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n  {MUTED}Stopping…{RESET}")

    observer.stop()
    observer.join()

# monkey-patch quiet flag for non-tty output.py usage
setattr(out, 'args_quiet', False)