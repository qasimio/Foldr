"""
foldr.watch
~~~~~~~~~~~
Watch mode for FOLDR v4 — with optional curses live display.
"""
from __future__ import annotations

import curses
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from foldr.organizer import organize_folder

console = Console()

_IN_PROGRESS_EXTS = {".crdownload", ".part", ".tmp", ".download", ".partial"}


def run_watch(
    base: Path,
    template: dict,
    dry_run: bool = False,
    extra_ignore: list[str] | None = None,
    smart: bool = False,
) -> None:
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        console.print(
            Panel.fit(
                "[bold red]watchdog is required for watch mode.[/bold red]\n\n"
                "Install it with:\n  [bold]pip install watchdog[/bold]",
                border_style="red",
            )
        )
        sys.exit(1)

    # Decide display mode
    use_tui = sys.stdout.isatty()

    # ── TUI display thread ──────────────────────────────────────────────────
    if use_tui:
        from foldr.tui import init_colors, WatchDisplay
        import threading

        _display: WatchDisplay | None = None
        _stdscr = None
        _lock = threading.Lock()

        def _tui_main(stdscr):
            nonlocal _display, _stdscr
            init_colors()
            _stdscr = stdscr
            _display = WatchDisplay(stdscr, base, dry_run)
            _display.draw()
            try:
                while True:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass

        tui_thread = threading.Thread(
            target=lambda: curses.wrapper(_tui_main), daemon=True
        )
        tui_thread.start()
        time.sleep(0.2)  # let curses init

        def _on_file(filename: str, dest: str, category: str) -> None:
            if _display:
                with _lock:
                    _display.add_event(filename, dest, category)

    else:
        # Plain-text fallback
        mode_label = "[bold yellow]DRY RUN[/bold yellow]" if dry_run else "[bold green]LIVE[/bold green]"
        console.print(
            Panel.fit(
                f"[bold cyan]Watching[/bold cyan]  [white]{base}[/white]\n"
                f"Mode  {mode_label}\n\n"
                "[dim]Files dropped here will be organized automatically.\n"
                "Press [bold]Ctrl+C[/bold] to stop.[/dim]",
                border_style="cyan",
            )
        )

        def _on_file(filename: str, dest: str, category: str) -> None:
            prefix = "  [dim](dry)[/dim]" if dry_run else " "
            console.print(
                f"{prefix}  [green]→[/green] [white]{filename}[/white]"
                f"  [dim]→[/dim]  [cyan]{dest}[/cyan]"
            )

    # ── Event handler ────────────────────────────────────────────────────────
    class FoldrHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            src_path = Path(event.src_path if isinstance(event.src_path, str) else (event.src_path.decode('utf-8', errors='replace') if isinstance(event.src_path, bytes) else str(event.src_path)))
            if src_path.suffix.lower() in _IN_PROGRESS_EXTS:
                return
            time.sleep(0.3)
            if not src_path.exists():
                return

            result = organize_folder(
                base=base,
                dry_run=dry_run,
                recursive=False,
                extra_ignore=extra_ignore,
                category_template=template if template else None,
                smart=smart,
            )

            if result.records:
                for r in result.records:
                    dest = Path(r.destination).parent.name
                    _on_file(r.filename, dest + "/", r.category)

    observer = Observer()
    observer.schedule(FoldrHandler(), str(base), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if not use_tui:
            console.print("\n[dim]Stopping watch mode…[/dim]")
    finally:
        observer.stop()
        observer.join()