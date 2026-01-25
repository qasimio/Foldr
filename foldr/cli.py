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
            "[dim]Run `foldr --help` to see available options.[/dim]",
            border_style="cyan"
        )
    )

    parser = argparse.ArgumentParser(
        description="Organize files in a directory by extension."
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

    args = parser.parse_args()
    base = args.path.expanduser().resolve()

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