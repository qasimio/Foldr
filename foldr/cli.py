import argparse
from pathlib import Path
from pyfiglet import Figlet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from .organizer import organize_folder


def _print_banner(console: Console) -> None:
    figlet = Figlet(font="slant")
    banner = figlet.renderText("FOLDR")
    console.print(banner, style="bold cyan")
    console.print(
        Panel.fit(
            "[bold]File Organizer CLI[/bold] [dim]v2[/dim]\n"
            "Organize files by extension\n\n"
            "[dim]Built by Muhammad Qasim (@qasimio)[/dim]\n"
            "[dim]Run `foldr --help` for usage and examples "
            "(paths with spaces must be quoted).[/dim]",
            border_style="cyan",
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Organize files in a directory by extension.",
        epilog=(
            "NOTE:\n"
            "  If the path contains spaces, wrap it in quotes.\n\n"
            "EXAMPLES:\n"
            "  foldr \"D:\\My Downloads\"\n"
            "  foldr ~/Downloads --dry-run\n"
            "  foldr ~/Downloads --recursive\n"
            "  foldr ~/Downloads --recursive --max-depth 2\n"
            "  foldr ~/Downloads --recursive --follow-symlinks\n"
            "  foldr \"C:\\Users\\Name\\Desktop Files\" --dry-run --recursive\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "path",
        type=Path,
        help="Directory to organize",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving files",
    )

    # ── v2: Recursive Engine ────────────────────────────────────────────────
    recursive_group = parser.add_argument_group(
        "Recursive Engine (v2)",
        "Options for organizing nested directory structures",
    )
    recursive_group.add_argument(
        "--recursive",
        action="store_true",
        help=(
            "Organize files inside subdirectories as well.\n"
            "Existing folder hierarchy is preserved — folders are never collapsed."
        ),
    )
    recursive_group.add_argument(
        "--max-depth",
        type=int,
        metavar="N",
        default=None,
        help=(
            "Limit recursion depth when --recursive is used.\n"
            "  --max-depth 1 → immediate subdirectories only\n"
            "  --max-depth 2 → two levels deep\n"
            "  (omit for unlimited depth)"
        ),
    )
    recursive_group.add_argument(
        "--follow-symlinks",
        action="store_true",
        help=(
            "Follow symbolic links to directories during recursive traversal.\n"
            "Disabled by default to prevent infinite loops.\n"
            "Circular symlinks are still detected and skipped automatically."
        ),
    )

    return parser


def _print_actions(console: Console, actions: list[str]) -> None:
    if not actions:
        console.print("[dim]No files to move.[/dim]")
        return
    for action in actions:
        console.print(f"  [green]→[/green] {action}")


def _print_summary(console: Console, base: Path, result: dict) -> None:
    console.print()

    # Mode badge
    mode = "[bold yellow]DRY RUN[/bold yellow]" if result["dry_run"] else "[bold green]EXECUTED[/bold green]"
    console.print(f"[bold]Mode:[/bold] {mode}")

    if result.get("recursive"):
        depth_label = str(result["max_depth"]) if result["max_depth"] is not None else "unlimited"
        symlink_label = "yes" if result.get("follow_symlinks") else "no (safe default)"
        console.print(
            f"[bold]Recursive:[/bold] yes  "
            f"[bold]Max depth:[/bold] {depth_label}  "
            f"[bold]Follow symlinks:[/bold] {symlink_label}  "
            f"[bold]Dirs processed:[/bold] {result.get('dirs_processed', 1)}"
        )

    console.print()

    # Category table (only non-zero rows)
    non_zero = {k: v for k, v in result["categories"].items() if v > 0}
    if non_zero:
        table = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold cyan",
            title=f"[bold]{base}[/bold] — summary",
            title_style="dim",
        )
        table.add_column("Category", style="cyan")
        table.add_column("Files moved", justify="right")
        for name, count in sorted(non_zero.items(), key=lambda x: -x[1]):
            table.add_row(name, str(count))
        console.print(table)

    console.print(f"[bold]Total items scanned:[/bold]  {result['total_items']}")
    console.print(f"[bold]Skipped directories:[/bold]  {result['skipped_directories']}")
    console.print(f"[bold]Other (unmatched) files:[/bold] {result['other_files']}")


def main() -> None:
    console = Console()
    _print_banner(console)

    parser = _build_parser()
    args, extras = parser.parse_known_args()

    # Detect unquoted paths with spaces
    if extras:
        console.print(
            Panel.fit(
                "[bold red]Invalid path format detected.[/bold red]\n\n"
                "It looks like your directory path contains spaces but was not wrapped in quotes.\n\n"
                "[bold]Correct usage:[/bold]\n"
                "  foldr \"D:\\Devshelf videos\" --dry-run\n\n"
                "[dim]Shells treat spaces as separators unless the path is quoted.[/dim]",
                border_style="red",
            )
        )
        raise SystemExit(2)

    # Validate --max-depth
    if args.max_depth is not None:
        if not args.recursive:
            console.print(
                Panel.fit(
                    "[bold yellow]--max-depth has no effect without --recursive.[/bold yellow]\n"
                    "Add [bold]--recursive[/bold] to enable nested traversal.",
                    border_style="yellow",
                )
            )
        elif args.max_depth < 1:
            console.print(
                Panel.fit(
                    "[bold red]--max-depth must be a positive integer (e.g. 1, 2, 3).[/bold red]",
                    border_style="red",
                )
            )
            raise SystemExit(1)

    # Validate --follow-symlinks without --recursive
    if args.follow_symlinks and not args.recursive:
        console.print(
            Panel.fit(
                "[bold yellow]--follow-symlinks has no effect without --recursive.[/bold yellow]\n"
                "Add [bold]--recursive[/bold] to enable nested traversal.",
                border_style="yellow",
            )
        )

    base = args.path.expanduser().resolve()

    if not base.exists() or not base.is_dir():
        console.print(
            Panel.fit(
                "[bold red]Invalid directory path.[/bold red]\n\n"
                "Make sure the path exists and is a directory.\n"
                "If it contains spaces, wrap it in quotes.\n\n"
                "Example:\n"
                "  foldr \"D:\\My Downloads\" --dry-run",
                border_style="red",
            )
        )
        raise SystemExit(1)

    # Warn about recursive without dry-run
    if args.recursive and not args.dry_run:
        console.print(
            Panel.fit(
                "[bold yellow]⚠  Recursive mode is active.[/bold yellow]\n\n"
                "Files in [bold]all subdirectories[/bold] will be moved.\n"
                "Consider running with [bold]--dry-run[/bold] first to preview changes.",
                border_style="yellow",
            )
        )

    result = organize_folder(
        base,
        dry_run=args.dry_run,
        recursive=args.recursive,
        max_depth=args.max_depth,
        follow_symlinks=args.follow_symlinks,
    )

    console.print("\n[bold underline]Actions[/bold underline]\n")
    _print_actions(console, result["actions"])
    _print_summary(console, base, result)


if __name__ == "__main__":
    main()