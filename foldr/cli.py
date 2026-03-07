"""
cli.py — FOLDR v2 command-line interface

Commands
--------
  foldr <path>                  organize a directory
  foldr undo                    undo the last run
  foldr undo --id <id>          undo a specific run
  foldr history                 list past runs
  foldr history --clear         delete all history

Organize flags
--------------
  --dry-run
  --recursive
  --max-depth N
  --follow-symlinks
  --config <path>               custom foldr.toml
  --ignore <pattern>            repeatable

Examples
--------
  foldr ~/Downloads
  foldr ~/Downloads --dry-run
  foldr ~/Downloads --recursive
  foldr ~/Downloads --recursive --max-depth 3
  foldr ~/Downloads --recursive --ignore "node_modules/" --ignore "*.tmp"
  foldr ~/Downloads --config ~/my-foldr.toml
  foldr undo
  foldr undo --id 2026-03-07_15-20-00
  foldr history
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich import box
from pyfiglet import Figlet

from foldr.organizer import organize_folder
from foldr.history import (
    UndoResult,
    delete_run,
    latest_run,
    list_runs,
    load_run,
    save_run,
    undo_run,
)
from foldr.config_loader import resolve_custom_config


# ─── Shared console ───────────────────────────────────────────────────────────

console = Console()


# ─── Banner ───────────────────────────────────────────────────────────────────

def _banner() -> None:
    figlet = Figlet(font="slant")
    console.print(figlet.renderText("FOLDR"), style="bold cyan", end="")
    console.print(
        Panel.fit(
            "[bold]File Organizer CLI[/bold]  [dim cyan]v2[/dim cyan]\n"
            "Organize files by extension — safe, fast, predictable\n\n"
            "[dim]Built by Muhammad Qasim (@qasimio)[/dim]\n"
            "[dim]Run [bold]foldr --help[/bold] for full usage[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


# ─── Argument parser ──────────────────────────────────────────────────────────

def _make_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="foldr",
        description="FOLDR — organize files by extension",
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=True,
    )

    sub = parser.add_subparsers(dest="command")

    # ── undo ─────────────────────────────────────────────────────────────────
    undo_p = sub.add_parser("undo", help="Undo a previous run")
    undo_p.add_argument(
        "--id",
        metavar="RUN_ID",
        default=None,
        help="Run ID to undo (default: latest run)",
    )
    undo_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview undo without moving files",
    )

    # ── history ───────────────────────────────────────────────────────────────
    hist_p = sub.add_parser("history", help="View or clear run history")
    hist_p.add_argument(
        "--clear",
        action="store_true",
        help="Delete all history entries",
    )

    # ── organize (default, no subcommand) ─────────────────────────────────────
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=None,
        help="Directory to organize",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without moving any files",
    )

    rec = parser.add_argument_group(
        "Recursive Engine",
        "Organize nested directory structures",
    )
    rec.add_argument(
        "--recursive",
        action="store_true",
        help="Descend into subdirectories",
    )
    rec.add_argument(
        "--max-depth",
        type=int,
        metavar="N",
        default=None,
        help="Maximum recursion depth (requires --recursive)",
    )
    rec.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symlinked directories (disabled by default, loops detected)",
    )

    cfg = parser.add_argument_group(
        "Configuration",
        "Custom rules and ignore patterns",
    )
    cfg.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        default=None,
        help="Path to a foldr.toml custom config file",
    )
    cfg.add_argument(
        "--ignore",
        action="append",
        metavar="PATTERN",
        dest="ignore_patterns",
        default=[],
        help=(
            "Ignore pattern (repeatable). Examples:\n"
            "  --ignore 'node_modules/'  --ignore '*.tmp'  --ignore '.env'"
        ),
    )

    return parser


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _warn(msg: str) -> None:
    console.print(Panel.fit(msg, border_style="yellow"))


def _error(msg: str, code: int = 1) -> None:
    console.print(Panel.fit(msg, border_style="red"))
    sys.exit(code)


def _rule(title: str = "") -> None:
    console.print(Rule(title, style="dim cyan"))


def _print_actions(actions: list[str], limit: int = 200) -> None:
    if not actions:
        console.print("[dim]  No files to move.[/dim]")
        return

    shown = actions[:limit]
    for action in shown:
        console.print(f"  [green]→[/green] {action}")

    if len(actions) > limit:
        remaining = len(actions) - limit
        console.print(
            f"\n  [dim]… and {remaining} more action(s). "
            "Run with [bold]--dry-run[/bold] to see all.[/dim]"
        )


def _print_summary(base: Path, result: dict) -> None:
    console.print()
    _rule("Summary")
    console.print()

    # mode badge
    if result["dry_run"]:
        mode_text = Text("● DRY RUN", style="bold yellow")
    else:
        mode_text = Text("● EXECUTED", style="bold green")
    console.print(mode_text)

    # recursive line
    if result.get("recursive"):
        depth = result["max_depth"] or "unlimited"
        symlinks = "yes" if result.get("follow_symlinks") else "no"
        dirs = result.get("dirs_processed", 1)
        console.print(
            f"  [dim]recursive[/dim]  depth=[cyan]{depth}[/cyan]  "
            f"symlinks=[cyan]{symlinks}[/cyan]  "
            f"dirs-processed=[cyan]{dirs}[/cyan]"
        )

    # ignore patterns in use
    patterns = result.get("ignore_patterns", [])
    if patterns:
        console.print(f"  [dim]ignoring:[/dim] {', '.join(patterns)}")

    console.print()

    # category table — only non-zero rows
    non_zero = {k: v for k, v in result["categories"].items() if v > 0}
    if non_zero:
        t = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold cyan",
            show_footer=False,
            padding=(0, 2),
        )
        t.add_column("Category", style="cyan", no_wrap=True)
        t.add_column("Files moved", justify="right", style="bold")

        total_moved = sum(non_zero.values())
        for name, count in sorted(non_zero.items(), key=lambda x: -x[1]):
            bar = "█" * min(count, 30)
            t.add_row(name, f"{bar}  {count}")

        console.print(t)
        console.print(f"  [bold]Total moved:[/bold]       {total_moved}")
    else:
        console.print("  [dim]No matching files found.[/dim]")

    console.print(f"  [bold]Total items scanned:[/bold]  {result['total_items']}")
    console.print(f"  [bold]Skipped directories:[/bold]  {result['skipped_directories']}")
    console.print(f"  [bold]Other (unmatched):[/bold]    {result['other_files']}")
    console.print()


# ─── Organize command ─────────────────────────────────────────────────────────

def _cmd_organize(args) -> None:
    # ── validate path ────────────────────────────────────────────────────────
    if args.path is None:
        _error(
            "[bold red]No directory specified.[/bold red]\n\n"
            "Usage:  [bold]foldr <directory>[/bold]\n"
            "        [bold]foldr --help[/bold]"
        )

    base = args.path.expanduser().resolve()

    if not base.exists() or not base.is_dir():
        _error(
            "[bold red]Invalid directory path.[/bold red]\n\n"
            f"Path: [dim]{base}[/dim]\n"
            "Make sure it exists and is a directory.\n"
            'Paths with spaces must be quoted:  foldr "D:\\My Downloads"'
        )

    # ── flag validation ───────────────────────────────────────────────────────
    if args.max_depth is not None and not args.recursive:
        _warn(
            "[bold yellow]--max-depth has no effect without --recursive.[/bold yellow]\n"
            "Add [bold]--recursive[/bold] to enable nested traversal."
        )

    if args.follow_symlinks and not args.recursive:
        _warn(
            "[bold yellow]--follow-symlinks has no effect without --recursive.[/bold yellow]\n"
            "Add [bold]--recursive[/bold] to enable nested traversal."
        )

    if args.max_depth is not None and args.max_depth < 1:
        _error("[bold red]--max-depth must be ≥ 1.[/bold red]")

    # ── recursive safety nudge ────────────────────────────────────────────────
    if args.recursive and not args.dry_run:
        console.print(
            Panel.fit(
                "[bold yellow]⚠  Recursive mode is active.[/bold yellow]\n\n"
                "[bold]Files in all subdirectories will be moved.[/bold]\n"
                "Run with [bold]--dry-run[/bold] first to preview safely.\n\n"
                "[dim]Press Ctrl-C to cancel.[/dim]",
                border_style="yellow",
            )
        )

    # ── custom config ─────────────────────────────────────────────────────────
    custom_config = resolve_custom_config(
        args.config if hasattr(args, "config") else None
    )
    if custom_config:
        console.print(
            f"  [dim cyan]Custom config loaded:[/dim cyan] "
            f"{args.config or '~/.config/foldr/config.toml'} "
            f"({len(custom_config)} categories)"
        )

    # ── run with progress spinner ─────────────────────────────────────────────
    console.print()
    _rule("Actions")
    console.print()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=28),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )

    with progress:
        task = progress.add_task("[cyan]Scanning…", total=None)
        result = organize_folder(
            base,
            dry_run=args.dry_run,
            recursive=args.recursive,
            max_depth=args.max_depth,
            follow_symlinks=args.follow_symlinks,
            custom_config=custom_config,
            ignore_patterns=args.ignore_patterns or [],
        )
        progress.update(task, description="[green]Done", completed=1, total=1)

    _print_actions(result["actions"])
    _print_summary(base, result)

    # ── save history (execute mode only) ──────────────────────────────────────
    if not args.dry_run and result.get("records"):
        from foldr.history import _run_id
        run_id = _run_id()
        hist_path = save_run(run_id, base, result)
        total_moved = sum(result["categories"].values())
        console.print(
            f"  [dim]Run saved → {hist_path.name}  "
            f"({total_moved} files moved)  "
            "Use [bold]foldr undo[/bold] to reverse.[/dim]"
        )

    console.print()


# ─── Undo command ─────────────────────────────────────────────────────────────

def _cmd_undo(args) -> None:
    _rule("Undo")
    console.print()

    run = None
    if args.id:
        run = load_run(args.id)
        if run is None:
            _error(
                f"[bold red]Run not found:[/bold red] [dim]{args.id}[/dim]\n\n"
                "Use [bold]foldr history[/bold] to see available runs."
            )
    else:
        run = latest_run()
        if run is None:
            _error(
                "[bold red]No history found.[/bold red]\n\n"
                "Nothing to undo — no previous runs recorded."
            )

    files_count = len(run.get("moves", []))
    timestamp = run.get("timestamp", run["id"])
    base = run.get("base", "?")

    console.print(f"  [bold]Run:[/bold]       {run['id']}")
    console.print(f"  [bold]Timestamp:[/bold] {timestamp}")
    console.print(f"  [bold]Directory:[/bold] {base}")
    console.print(f"  [bold]Files:[/bold]     {files_count}")
    console.print()

    if files_count == 0:
        console.print("  [dim]Nothing to undo for this run.[/dim]")
        return

    # confirmation
    if not args.dry_run:
        label = "DRY RUN" if args.dry_run else "LIVE"
        try:
            answer = console.input(
                f"  [bold yellow]Restore {files_count} file(s) to original locations? (y/n):[/bold yellow] "
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim]Cancelled.[/dim]")
            return

        if answer.strip().lower() not in ("y", "yes"):
            console.print("  [dim]Aborted.[/dim]")
            return

    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=28),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Restoring…", total=None)
        undo_result = undo_run(run, dry_run=args.dry_run)
        progress.update(task, description="[green]Done", completed=1, total=1)

    # results
    mode = "[bold yellow]DRY RUN[/bold yellow]" if args.dry_run else "[bold green]EXECUTED[/bold green]"
    console.print(f"  Mode: {mode}")
    console.print(f"  [green]Restored:[/green]  {len(undo_result.restored)}")
    console.print(f"  [yellow]Skipped:[/yellow]   {len(undo_result.skipped)}")
    console.print(f"  [red]Errors:[/red]    {len(undo_result.errors)}")

    if undo_result.skipped:
        console.print("\n  [dim]Skipped (file no longer at destination):[/dim]")
        for dst, reason in undo_result.skipped[:10]:
            console.print(f"    [dim]• {Path(dst).name} — {reason}[/dim]")

    if undo_result.errors:
        console.print("\n  [red]Errors:[/red]")
        for dst, err in undo_result.errors[:10]:
            console.print(f"    [red]• {Path(dst).name} — {err}[/red]")

    console.print()


# ─── History command ──────────────────────────────────────────────────────────

def _cmd_history(args) -> None:
    _rule("Run History")
    console.print()

    if args.clear:
        runs = list_runs()
        if not runs:
            console.print("  [dim]No history to clear.[/dim]")
            return
        try:
            answer = console.input(
                f"  [bold yellow]Delete {len(runs)} history entries? (y/n):[/bold yellow] "
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim]Cancelled.[/dim]")
            return
        if answer.strip().lower() not in ("y", "yes"):
            console.print("  [dim]Aborted.[/dim]")
            return
        for run in runs:
            delete_run(run["id"])
        console.print(f"  [green]Cleared {len(runs)} entries.[/green]")
        return

    runs = list_runs()
    if not runs:
        console.print("  [dim]No history yet. Run [bold]foldr <directory>[/bold] to get started.[/dim]")
        return

    t = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        padding=(0, 2),
    )
    t.add_column("ID / Timestamp", style="cyan", no_wrap=True)
    t.add_column("Directory", style="dim", overflow="fold")
    t.add_column("Files", justify="right", style="bold")
    t.add_column("Mode", justify="center")
    t.add_column("Recursive", justify="center")

    for run in runs:
        mode = "[yellow]DRY[/yellow]" if run.get("dry_run") else "[green]EXEC[/green]"
        rec = "[cyan]yes[/cyan]" if run.get("recursive") else "no"
        t.add_row(
            run["id"],
            run.get("base", "?"),
            str(run.get("files_moved", "?")),
            mode,
            rec,
        )

    console.print(t)
    console.print(
        f"  [dim]{len(runs)} run(s)  ·  "
        "Use [bold]foldr undo[/bold] to reverse the latest  ·  "
        "[bold]foldr history --clear[/bold] to delete all[/dim]"
    )
    console.print()


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    _banner()

    parser = _make_parser()
    args, extras = parser.parse_known_args()

    # unquoted path with spaces guard
    if extras and args.command is None:
        _error(
            "[bold red]Unexpected arguments detected.[/bold red]\n\n"
            "Your path may contain spaces but was not quoted.\n\n"
            "[bold]Correct usage:[/bold]\n"
            '  foldr "D:\\My Downloads" --dry-run\n\n'
            "[dim]Shells treat spaces as argument separators.[/dim]",
            code=2,
        )

    if args.command == "undo":
        _cmd_undo(args)
    elif args.command == "history":
        _cmd_history(args)
    else:
        _cmd_organize(args)


if __name__ == "__main__":
    main()