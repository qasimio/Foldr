"""
foldr.cli
~~~~~~~~~
FOLDR v4 — full CLI.

Commands
--------
  foldr                              → organize current directory (interactive prompt)
  foldr <path>                       → organize
  foldr <path> --dry-run
  foldr <path> --recursive [--max-depth N] [--follow-symlinks]
  foldr <path> --smart
  foldr <path> --deduplicate [keep-newest|keep-largest|keep-oldest]
  foldr <path> --ignore "*.log" "tmp/"
  foldr <path> --config foldr.toml
  foldr <path> --verbose / --quiet
  foldr <path> --interactive         → TUI preview before executing
  foldr watch <path>                 → watch mode (live file organizer)
  foldr undo [--id ID] [--dry-run]
  foldr history [--all]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pyfiglet import Figlet
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# Assumed structure based on file imports
from foldr.config_loader import load_template
from foldr.dedup import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs import remove_empty_dirs, scan_empty_dirs
from foldr.organizer import organize_folder
from foldr.watch import run_watch

console = Console()


def cmd_watch(target: str | None, args: argparse.Namespace) -> None:
    """Handle the 'watch' subcommand logic."""
    target_path = Path(target).resolve() if target else Path.cwd()
    
    if not target_path.exists() or not target_path.is_dir():
        console.print(f"[bold red]Error:[/bold red] Watch target '{target_path}' is not a valid directory.")
        sys.exit(1)
        
    template_result = load_template(args.config) if hasattr(args, 'config') and args.config else {}
    template = template_result[0] if isinstance(template_result, tuple) else template_result
    
    run_watch(
        base=target_path,
        template=template,
        dry_run=args.dry_run,
        extra_ignore=args.ignore,
    )


def cmd_undo(args: argparse.Namespace) -> None:
    """Handle the 'undo' subcommand logic."""
    console.print("[dim]Undo command initialized (placeholder).[/dim]")
    # TODO: Implement undo logic using undo history records


def cmd_history(args: argparse.Namespace) -> None:
    """Handle the 'history' subcommand logic."""
    console.print("[dim]History command initialized (placeholder).[/dim]")
    # TODO: Implement history printing


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FOLDR v4 — File Organizer",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Path is positioned flexibly so we can intercept subcommands manually
    parser.add_argument("path", nargs="?", help="Directory to organize, or command (watch/undo/history)")
    
    # Standard flags
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--recursive", action="store_true", help="Organize subdirectories too")
    parser.add_argument("--max-depth", type=int, help="Maximum recursion depth")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symbolic links")
    parser.add_argument("--smart", action="store_true", help="Use AI/Smart categorization")
    parser.add_argument("--deduplicate", choices=["keep-newest", "keep-largest", "keep-oldest"], help="Deduplicate files")
    parser.add_argument("--ignore", nargs="+", help="Patterns to ignore (e.g., '*.log' 'tmp/')")
    parser.add_argument("--config", help="Path to custom config file")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--quiet", action="store_true", help="Quiet output")
    parser.add_argument("--interactive", action="store_true", help="TUI preview before executing")
    
    # Undo / History specific flags
    parser.add_argument("--id", help="Transaction ID for undo")
    parser.add_argument("--all", action="store_true", help="Show all history")

    args, _ = parser.parse_known_args()

    # Title header display
    if not args.quiet:
        fig = Figlet(font="slant")
        title = fig.renderText("FOLDR")
        console.print(f"[bold cyan]{title}[/bold cyan]")

    # Subcommand routing
    if args.path == "undo":
        cmd_undo(args)
        return

    if args.path == "history":
        cmd_history(args)
        return

    if args.path == "watch":
        # foldr watch <dir>
        # argparse consumed "watch" as `path`; the actual target dir was not
        # parsed. Extract it from sys.argv manually.
        raw = sys.argv[1:]
        try:
            watch_idx = raw.index("watch")
            # Next positional arg after "watch" (ignore flags)
            candidates = [a for a in raw[watch_idx+1:] if not a.startswith("-")]
            watch_target = candidates[0] if candidates else None
        except (ValueError, IndexError):
            watch_target = None
            
        cmd_watch(watch_target, args)
        return

    # No path → default to cwd
    if args.path is None:
        # Show a quick prompt so the user knows what's happening
        cwd = Path.cwd()
        console.print(
            Panel.fit(
                f"[bold]No directory specified.[/bold]\n\n"
                f"Target: [cyan]{cwd}[/cyan]\n\n"
                "[dim]To organize a different directory, pass it as the first argument.[/dim]",
                border_style="cyan",
            )
        )
        if not Confirm.ask(
            f"  Organize [bold]{cwd.name}[/bold] (current directory)?",
            default=False,
            console=console,
        ):
            console.print("  [dim]Cancelled.[/dim]\n")
            raise SystemExit(0)
            
        target_dir = cwd
    else:
        target_dir = Path(args.path).resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        console.print(f"[bold red]Error:[/bold red] '{target_dir}' is not a valid directory.")
        sys.exit(1)

    # Standard Execution
    console.print(Rule(f"Organizing {target_dir.name}", style="cyan"))
    template_result = load_template(args.config) if args.config else {}
    template = template_result[0] if isinstance(template_result, tuple) else template_result
    
    result = organize_folder(
        base=target_dir,
        dry_run=args.dry_run,
        recursive=args.recursive,
        extra_ignore=args.ignore,
        category_template=template,
    )
    
    # Output wrap up
    if hasattr(result, "actions") and result.actions and not args.quiet:
        console.print(f"\n[green]Successfully completed {len(result.actions)} actions.[/green]")


if __name__ == "__main__":
    main()