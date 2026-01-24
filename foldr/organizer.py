import shutil
from pathlib import Path
from foldr.config import CATEGORIES_TEMPLATE


def organize_folder(base: Path, dry_run: bool = False) -> dict:
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError("Path must be an existing directory.")

    categories = {
        name: {
            "folder": base / data["folder"],
            "ext": set(data["ext"]),
            "count": 0,
        }
        for name, data in CATEGORIES_TEMPLATE.items()
    }

    if not dry_run:
        for cat in categories.values():
            cat["folder"].mkdir(exist_ok=True)

    destination_folders = {cat["folder"] for cat in categories.values()}

    skipped_directories = 0
    other_files = 0
    actions = []

    def move_file(destination: Path, source: Path):
        target = destination / source.name

        if not target.exists():
            actions.append(f"{source.name} -> {destination.name}")
            if not dry_run:
                shutil.move(source, target)
            return

        counter = 1
        while True:
            new_name = f"{source.stem}({counter}){source.suffix}"
            target = destination / new_name
            if not target.exists():
                actions.append(f"{source.name} -> {new_name}")
                if not dry_run:
                    shutil.move(source, target)
                break
            counter += 1

    entries = list(base.iterdir())

    for entry in entries:
        if entry.is_dir():
            if entry not in destination_folders:
                skipped_directories += 1
            continue

        ext = entry.suffix.lower()
        moved = False

        for cat in categories.values():
            if ext in cat["ext"]:
                cat["count"] += 1
                move_file(cat["folder"], entry)
                moved = True
                break

        if not moved:
            other_files += 1

    if not dry_run:
        for folder in destination_folders:
            if folder.exists() and not any(folder.iterdir()):
                folder.rmdir()

    return {
        "total_items": len(entries),
        "skipped_directories": skipped_directories,
        "categories": {name: data["count"] for name, data in categories.items()},
        "other_files": other_files,
        "actions": actions,
        "dry_run": dry_run,
    }