import argparse
from pathlib import Path
from .organizer import organize_folder


def main():
    parser = argparse.ArgumentParser(
        description="Organize files in a directory by extension.\nBuilt by Muhammad Qasim @Kas-sim\n"
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
    print(f"\nMode: {mode}\n")

    for action in result["actions"]:
        print(action)

    print(f"\n{base} contains:\n")
    print(f"Total items: {result['total_items']}")
    print(f"Skipped directories: {result['skipped_directories']}")

    for name, count in result["categories"].items():
        print(f"{name}: {count}")

    print(f"Other files: {result['other_files']}")

if __name__ == "__main__":
    main()