"""
foldr.cli
~~~~~~~~~
FOLDR v3 — interactive CLI built on Rich + Textual-free patterns.

Commands
--------
  foldr <path>                        organize root only
  foldr <path> --recursive            organize all subdirectories
  foldr <path> --recursive --max-depth 2
  foldr <path> --recursive --follow-symlinks
  foldr <path> --dry-run              preview only
  foldr <path> --config foldr.toml    custom categories
  foldr <path> --ignore "*.log" "*.tmp"
  foldr undo                          undo last operation
  foldr undo --id <id>                undo specific operation
  foldr undo --dry-run                preview undo
  foldr history                       list recent operations
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pyfiglet import Figlet
from rich import box
from rich.columns import Columns
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
from rich.prompt import Confirm
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .organizer import OrganizeResult, organize_folder
from .config_loader import load_template
from .history import (
    UndoResult,
    get_history_entry,
    get_latest_history,
    list_history,
    save_history,
    undo_operation,
)


console = Console()


# ──────────────────────────────────────────────────────────────────────────────
# Banner
# ──────────────────────────────────────────────────────────────────────────────

def _banner() -> None:
    figlet = Figlet(font="slant")
    console.print(figlet.renderText("FOLDR"), style="bold cyan", end="")
    console.print(
        Panel.fit(
            "[bold white]File Organizer CLI[/bold white] [dim cyan]v3[/dim cyan]\n"
            "[dim]Organize files by extension · Recursive · Undo · Config[/dim]\n\n"
            "[dim]Built by Muhammad Qasim ([cyan]@qasimio[/cyan])[/dim]\n"
            "[dim]Run [bold]foldr --help[/bold] for usage · paths with spaces must be quoted[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foldr",
        description="Organize files in a directory by extension.",
        epilog=(
            "EXAMPLES:\n"
            "  foldr ~/Downloads\n"
            "  foldr ~/Downloads --dry-run\n"
            "  foldr ~/Downloads --recursive --max-depth 2\n"
            "  foldr ~/Downloads --ignore '*.log' 'node_modules/'\n"
            "  foldr ~/Downloads --config ~/foldr.toml\n"
            "  foldr undo\n"
            "  foldr undo --id a1b2c3\n"
            "  foldr history\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "path",
        nargs="?",
        type=str,
        help=(
            "Directory to organize, OR a sub-command:\n"
            "  undo     — restore files from last (or --id) operation\n"
            "  history  — list recent operations"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without moving files")

    rg = parser.add_argument_group("Recursive Engine")
    rg.add_argument("--recursive", action="store_true", help="Descend into subdirectories")
    rg.add_argument("--max-depth", type=int, metavar="N", default=None,
                    help="Max recursion depth (requires --recursive)")
    rg.add_argument("--follow-symlinks", action="store_true",
                    help="Follow symlinked directories (default: off)")

    ig = parser.add_argument_group("Ignore Rules")
    ig.add_argument("--ignore", nargs="+", metavar="PATTERN", default=None,
                    help="Patterns to ignore, e.g. '*.log' 'node_modules/'")

    cg = parser.add_argument_group("Configuration")
    cg.add_argument("--config", type=Path, metavar="FILE",
                    help="Path to a foldr.toml config file")

    ug = parser.add_argument_group("Undo")
    ug.add_argument("--id", type=str, metavar="ID",
                    help="Specific operation ID to undo (use with: foldr undo)")

    return parser


# ──────────────────────────────────────────────────────────────────────────────
# Shared UI helpers
# ──────────────────────────────────────────────────────────────────────────────

def _warn(msg: str) -> None:
    console.print(Panel.fit(msg, border_style="yellow"))


def _error(msg: str) -> None:
    console.print(Panel.fit(msg, border_style="red"))


def _success(msg: str) -> None:
    console.print(Panel.fit(msg, border_style="green"))


def _rule(title: str = "") -> None:
    console.print(Rule(title, style="dim cyan"))


# ──────────────────────────────────────────────────────────────────────────────
# Organize command rendering
# ──────────────────────────────────────────────────────────────────────────────

def _render_actions(result: OrganizeResult, base: Path) -> None:
    _rule("Actions")

    if not result.actions:
        console.print("  [dim]No files to organize.[/dim]\n")
        return

    # Group actions by source directory prefix
    root_actions = []
    sub_actions: dict[str, list[str]] = {}

    for action in result.actions:
        if action.startswith("["):
            bracket_end = action.index("]")
            prefix = action[1:bracket_end]
            rest = action[bracket_end + 2:]
            sub_actions.setdefault(prefix, []).append(rest)
        else:
            root_actions.append(action)

    # Root-level
    if root_actions:
        console.print(f"  [dim bold]{base.name}/[/dim bold]")
        for a in root_actions:
            parts = a.split("→")
            if len(parts) == 2:
                src = parts[0].strip()
                dst = parts[1].strip()
                console.print(f"    [green]→[/green] [white]{src}[/white]  [dim]→[/dim]  [cyan]{dst}[/cyan]")
            else:
                console.print(f"    [green]→[/green] {a}")

    # Sub-directory groups
    for prefix, actions in sub_actions.items():
        console.print(f"\n  [dim bold]{prefix}/[/dim bold]")
        for a in actions:
            parts = a.split("→")
            if len(parts) == 2:
                src = parts[0].strip()
                dst = parts[1].strip()
                console.print(f"    [green]→[/green] [white]{src}[/white]  [dim]→[/dim]  [cyan]{dst}[/cyan]")
            else:
                console.print(f"    [green]→[/green] {a}")

    console.print()


def _render_summary(result: OrganizeResult, base: Path, log_path: Path | None) -> None:
    _rule("Summary")

    # Mode + flags row
    mode_text = (
        "[bold yellow]● DRY RUN[/bold yellow]"
        if result.dry_run
        else "[bold green]● EXECUTED[/bold green]"
    )
    console.print(f"  Mode  {mode_text}")

    if result.recursive:
        depth_label = str(result.max_depth) if result.max_depth is not None else "[dim]unlimited[/dim]"
        sym_label = "[green]yes[/green]" if result.follow_symlinks else "[dim]no[/dim]"
        console.print(
            f"  Recursive  [cyan]yes[/cyan]   "
            f"Max depth  {depth_label}   "
            f"Symlinks  {sym_label}   "
            f"Dirs scanned  [cyan]{result.dirs_processed}[/cyan]"
        )

    if result.ignored_files or result.ignored_dirs:
        console.print(
            f"  Ignored  [yellow]{result.ignored_files} files[/yellow]  "
            f"[yellow]{result.ignored_dirs} dirs[/yellow]"
        )

    console.print()

    # Category table
    non_zero = {k: v for k, v in result.categories.items() if v > 0}
    if non_zero:
        table = Table(
            box=box.MINIMAL_DOUBLE_HEAD,
            show_header=True,
            header_style="bold cyan",
            border_style="dim",
            padding=(0, 2),
        )
        table.add_column("Category", style="cyan", no_wrap=True)
        table.add_column("Files", justify="right", style="white")
        table.add_column("Visual", no_wrap=True)

        max_count = max(non_zero.values())
        bar_width = 20
        for name, count in sorted(non_zero.items(), key=lambda x: -x[1]):
            filled = int((count / max_count) * bar_width)
            bar = "[cyan]" + "█" * filled + "[/cyan]" + "[dim]" + "░" * (bar_width - filled) + "[/dim]"
            table.add_row(name, str(count), bar)

        console.print(table)
        console.print()

    # Stats row
    total_moved = sum(non_zero.values())
    console.print(
        f"  [bold]Total scanned[/bold]  [white]{result.total_items}[/white]   "
        f"[bold]Moved[/bold]  [green]{total_moved}[/green]   "
        f"[bold]Skipped dirs[/bold]  {result.skipped_directories}   "
        f"[bold]Unmatched[/bold]  {result.other_files}"
    )

    if log_path:
        console.print(f"\n  [dim]History saved → {log_path}[/dim]")
        console.print(f"  [dim]Undo with: [bold]foldr undo[/bold][/dim]")

    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Progress spinner for actual runs
# ──────────────────────────────────────────────────────────────────────────────

def _run_with_progress(
    base: Path,
    dry_run: bool,
    recursive: bool,
    max_depth: int | None,
    follow_symlinks: bool,
    extra_ignore: list[str] | None,
    template: dict,
) -> OrganizeResult:
    """Run organize_folder with a live spinner for non-dry real runs."""
    if dry_run:
        # Dry runs are instant; no spinner needed
        return organize_folder(
            base=base, dry_run=True, recursive=recursive,
            max_depth=max_depth, follow_symlinks=follow_symlinks,
            extra_ignore=extra_ignore, category_template=template,
        )

    progress = Progress(
        SpinnerColumn(spinner_name="dots", style="cyan"),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30, style="cyan", complete_style="green"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    task = progress.add_task("Organizing files…", total=None)

    with progress:
        result = organize_folder(
            base=base, dry_run=False, recursive=recursive,
            max_depth=max_depth, follow_symlinks=follow_symlinks,
            extra_ignore=extra_ignore, category_template=template,
        )
        progress.update(task, completed=1, total=1)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Organize command
# ──────────────────────────────────────────────────────────────────────────────

def cmd_organize(args: argparse.Namespace) -> None:
    # Validation: unquoted path with spaces
    # (parser.parse_known_args handled in main)

    # Validate flags
    if args.max_depth is not None and not args.recursive:
        _warn("[bold yellow]--max-depth has no effect without --recursive.[/bold yellow]\nAdd [bold]--recursive[/bold] to enable nested traversal.")

    if args.follow_symlinks and not args.recursive:
        _warn("[bold yellow]--follow-symlinks has no effect without --recursive.[/bold yellow]")

    if args.max_depth is not None and args.recursive and args.max_depth < 1:
        _error("[bold red]--max-depth must be ≥ 1[/bold red]")
        raise SystemExit(1)

    base = Path(args.path).expanduser().resolve()

    if not base.exists() or not base.is_dir():
        _error(
            "[bold red]Invalid directory path.[/bold red]\n\n"
            "Make sure the path exists and is a directory.\n"
            "If it contains spaces, wrap it in quotes.\n\n"
            f"Received: [dim]{base}[/dim]"
        )
        raise SystemExit(1)

    # Load config / template
    try:
        template, config_label = load_template(args.config)
    except (FileNotFoundError, RuntimeError) as e:
        _error(f"[bold red]Config error:[/bold red] {e}")
        raise SystemExit(1)

    if config_label:
        console.print(f"  [dim]Using config: {config_label}[/dim]\n")

    # Safety nudge for recursive + real run
    if args.recursive and not args.dry_run:
        console.print(
            Panel.fit(
                "[bold yellow]⚠  Recursive mode is active.[/bold yellow]\n\n"
                "Files in [bold]all subdirectories[/bold] will be lifted into\n"
                f"category folders at [cyan]{base.name}/[/cyan].\n\n"
                "Run with [bold]--dry-run[/bold] first to preview.",
                border_style="yellow",
            )
        )

    # Run
    result = _run_with_progress(
        base=base,
        dry_run=args.dry_run,
        recursive=args.recursive,
        max_depth=args.max_depth,
        follow_symlinks=args.follow_symlinks,
        extra_ignore=args.ignore,
        template=template,
    )

    # Save history
    log_path = save_history(result.records, base, dry_run=args.dry_run)

    # Render
    _render_actions(result, base)
    _render_summary(result, base, log_path)


# ──────────────────────────────────────────────────────────────────────────────
# Undo command
# ──────────────────────────────────────────────────────────────────────────────

def cmd_undo(args: argparse.Namespace) -> None:
    _rule("Undo")

    # Load log
    if args.id:
        log_data = get_history_entry(args.id)
        if log_data is None:
            _error(f"[bold red]No operation found with ID or filename containing:[/bold red] {args.id}")
            raise SystemExit(1)
    else:
        log_data = get_latest_history()
        if log_data is None:
            _warn("[bold yellow]No operation history found.[/bold yellow]\nRun [bold]foldr history[/bold] to see past operations.")
            raise SystemExit(0)

    # Show what we're about to undo
    total = log_data.get("total_files", 0)
    base = log_data.get("base", "unknown")
    ts = log_data.get("timestamp", "")[:19].replace("T", " ")
    op_id = log_data.get("id", "?")

    console.print(
        Panel.fit(
            f"[bold]Operation ID[/bold]  [cyan]{op_id}[/cyan]\n"
            f"[bold]Directory   [/bold]  [dim]{base}[/dim]\n"
            f"[bold]Timestamp   [/bold]  [dim]{ts} UTC[/dim]\n"
            f"[bold]Files       [/bold]  [white]{total}[/white]",
            border_style="cyan",
            title="[bold]Operation to undo[/bold]",
        )
    )
    console.print()

    if args.dry_run:
        console.print("[dim italic]  (dry-run — no files will be moved)\n[/dim italic]")

    # Show preview of first 10 records
    records = log_data.get("records", [])
    for record in list(reversed(records))[:10]:
        dest = Path(record["destination"])
        src = Path(record["source"])
        console.print(
            f"  [yellow]←[/yellow] [white]{record['filename']}[/white]  "
            f"[dim]{dest.parent.name}/[/dim] → [cyan]{src.parent.name}/[/cyan]"
        )
    if len(records) > 10:
        console.print(f"  [dim]… and {len(records) - 10} more[/dim]")

    console.print()

    # Confirmation (skip for dry-run)
    if not args.dry_run:
        if not Confirm.ask(
            f"  [bold]Restore {total} file(s) to original locations?[/bold]",
            default=False,
            console=console,
        ):
            console.print("\n  [dim]Undo cancelled.[/dim]\n")
            raise SystemExit(0)

    # Execute undo
    undo_result = undo_operation(log_data, dry_run=args.dry_run)

    _rule("Results")
    if undo_result.restored:
        for msg in undo_result.restored:
            console.print(f"  [green]✓[/green] {msg}")
    if undo_result.skipped:
        console.print()
        for msg in undo_result.skipped:
            console.print(f"  [yellow]⚠[/yellow] {msg}")
    if undo_result.errors:
        console.print()
        for msg in undo_result.errors:
            console.print(f"  [red]✗[/red] {msg}")

    console.print()
    status = "[bold green]✓ Undo complete[/bold green]" if not undo_result.errors else "[bold red]✗ Undo completed with errors[/bold red]"
    if args.dry_run:
        status = "[bold yellow]● Dry-run preview complete[/bold yellow]"
    console.print(f"  {status}")
    console.print(
        f"  [dim]{len(undo_result.restored)} restored · "
        f"{len(undo_result.skipped)} skipped · "
        f"{len(undo_result.errors)} errors[/dim]"
    )
    if undo_result.log_deleted:
        console.print("  [dim]History entry removed.[/dim]")
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# History command
# ──────────────────────────────────────────────────────────────────────────────

def cmd_history() -> None:
    _rule("Operation History")

    entries = list_history(limit=20)

    if not entries:
        _warn(
            "[bold yellow]No history found.[/bold yellow]\n\n"
            "History is stored at [dim]~/.foldr/history/[/dim]\n"
            "after each non-dry-run operation."
        )
        return

    table = Table(
        box=box.MINIMAL_DOUBLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        padding=(0, 2),
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Timestamp (UTC)", style="dim")
    table.add_column("Files", justify="right")
    table.add_column("Directory", style="dim", overflow="fold")

    for e in entries:
        ts = e["timestamp"][:19].replace("T", " ") if e["timestamp"] else "—"
        table.add_row(
            e["id"],
            ts,
            str(e["total_files"]),
            e["base"],
        )

    console.print(table)
    console.print()
    console.print("  [dim]Undo latest:         [bold]foldr undo[/bold][/dim]")
    console.print("  [dim]Undo specific:       [bold]foldr undo --id <ID>[/bold][/dim]")
    console.print("  [dim]Preview undo:        [bold]foldr undo --dry-run[/bold][/dim]")
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    _banner()

    parser = _build_parser()
    args, extras = parser.parse_known_args()

    # Sub-commands: undo, history
    if args.path in ("undo", "history", None):
        if args.path == "history":
            cmd_history()
            return
        if args.path == "undo":
            cmd_undo(args)
            return
        # No path at all
        parser.print_help()
        raise SystemExit(0)

    # Unquoted path-with-spaces guard
    if extras:
        _error(
            "[bold red]Invalid path format detected.[/bold red]\n\n"
            "It looks like your directory path contains spaces but was not quoted.\n\n"
            "[bold]Correct usage:[/bold]\n"
            "  foldr \"D:\\My Downloads\" --dry-run\n\n"
            "[dim]Shells treat spaces as argument separators unless the path is quoted.[/dim]"
        )
        raise SystemExit(2)

    cmd_organize(args)


if __name__ == "__main__":
    main()