import argparse
from pathlib import Path
from pyfiglet import Figlet
from rich.console import Console
from rich.panel import Panel
from .organizer import organize_folder


def main():
    console = Console()

    figlet = Figlet(font="slant")
    banner = figlet.renderText("FOLDR")

    console.print(banner, style="bold cyan")
    console.print(
        Panel.fit(
            "[bold]File Organizer CLI[/bold]\n"
            "Organize files by extension\n\n"
            "[dim]Built by Muhammad Qasim (@Kas-sim)[/dim]\n"
            "[dim]Run `foldr --help` for usage and examples (paths with spaces must be quoted).[/dim]",
            border_style="cyan"
        )
    )

    parser = argparse.ArgumentParser(
        description="Organize files in a directory by extension.",
        epilog=(
            "NOTE:\n"
            "  If the path contains spaces, wrap it in quotes.\n\n"
            "EXAMPLES:\n"
            "  foldr \"D:\\My Downloads\"\n"
            "  foldr \"C:\\Users\\Name\\Desktop Files\" --dry-run\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "path",
        type=Path,
        help="Directory to organize"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving files"
    )

    args, extras = parser.parse_known_args()

    if extras:
        console.print(
            Panel.fit(
                "[bold red]Invalid path format detected.[/bold red]\n\n"
                "It looks like your directory path contains spaces but was not wrapped in quotes.\n\n"
                "[bold]Correct usage:[/bold]\n"
                "  foldr \"D:\\Devshelf videos\"\n\n"
                "[dim]Shells treat spaces as separators unless the path is quoted.[/dim]",
                border_style="red"
            )
    )
    raise SystemExit(2)

    base = args.path.expanduser().resolve()

    if not base.exists():
        console.print(
            Panel.fit(
                "[bold red]Invalid path provided.[/bold red]\n\n"
                "If your directory path contains spaces, make sure to wrap it in quotes.\n\n"
                "Example:\n"
                "  foldr \"D:\\My Downloads\" --dry-run",
                border_style="red"
            )
    )
    raise SystemExit(1)
    
    result = organize_folder(base, dry_run=args.dry_run)

    mode = "DRY RUN" if args.dry_run else "EXECUTED"
    console.print(f"\n[bold]Mode:[/bold] {mode}\n")

    for action in result["actions"]:
        console.print(action)

    console.print(f"\n[bold]{base} contains:[/bold]\n")
    console.print(f"Total items: {result['total_items']}")
    console.print(f"Skipped directories: {result['skipped_directories']}")

    for name, count in result["categories"].items():
        console.print(f"{name}: {count}")

    console.print(f"Other files: {result['other_files']}")


if __name__ == "__main__":
    main()