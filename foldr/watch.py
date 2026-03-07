"""
foldr.watch
~~~~~~~~~~~
Watch mode for FOLDR v4.

Uses watchdog (OS-native filesystem events) to monitor a directory
and automatically organize new files as they arrive.

Behaviour
---------
- Only monitors the root directory (non-recursive by default)
- Waits 300ms after a creation event before processing (handles
  partial writes / downloads in progress)
- Skips in-progress file extensions (.crdownload, .part, .tmp)
- Skips files already inside FOLDR category folders
- Prints a timestamped log line per organized file
- Runs until Ctrl+C
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

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
    """
    Start the filesystem watcher for `base`.
    Blocks until KeyboardInterrupt.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        console.print(
            Panel.fit(
                "[bold red]watchdog is required for watch mode.[/bold red]\n\n"
                "Install it:\n  [bold]pip install watchdog[/bold]",
                border_style="red",
            )
        )
        sys.exit(1)  # Required to prevent UnboundLocalError/NameError crash later

    class FoldrHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            
            src_path = Path(event.src_path)
            
            # Skip in-progress file extensions
            if src_path.suffix.lower() in _IN_PROGRESS_EXTS:
                return
                
            # Allow time for partial writes to finalize
            time.sleep(0.3)
            
            # Ensure file wasn't moved/deleted right after creation
            if not src_path.exists():
                return

            result = organize_folder(
                base=base,
                dry_run=dry_run,
                recursive=False,
                extra_ignore=extra_ignore,
                category_template=template,
                smart=smart,
            )

            # Ensure 'actions' attribute exists and parse results to output
            if hasattr(result, "actions") and result.actions:
                for action in result.actions:
                    parts = action.split("→", 1)
                    fname = parts[0].strip()
                    dest  = parts[1].strip() if len(parts) == 2 else ""
                    prefix = "  [dim](dry)[/dim]" if dry_run else " "
                    console.print(
                        f"{prefix}  [green]→[/green] [white]{fname}[/white]"
                        f"  [dim]→[/dim]  [cyan]{dest}[/cyan]"
                    )

    observer = Observer()
    observer.schedule(FoldrHandler(), str(base), recursive=False)
    observer.start()

    mode_label = "[bold yellow]DRY RUN[/bold yellow]" if dry_run else "[bold green]LIVE[/bold green]"
    console.print(
        Panel.fit(
            f"[bold cyan]Watching[/bold cyan]  [white]{base}[/white]\n"
            f"Mode  {mode_label}\n\n"
            "[dim]Files dropped here will be organized automatically.[/dim]\n"
            "[dim]Press [bold]Ctrl+C[/bold] to stop.[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopping watch mode...[/dim]")
    finally:
        observer.stop()
        observer.join()