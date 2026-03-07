import shutil
from pathlib import Path
from foldr.config import CATEGORIES_TEMPLATE


def _build_categories(base: Path) -> dict:
    """Build the categories map with absolute destination folders."""
    return {
        name: {
            "folder": base / data["folder"],
            "ext": set(data["ext"]),
            "count": 0,
        }
        for name, data in CATEGORIES_TEMPLATE.items()
    }


def _resolve_destination_folders(categories: dict) -> set:
    """Return set of all destination folder paths (used to skip them during traversal)."""
    return {cat["folder"] for cat in categories.values()}


def _move_file(destination: Path, source: Path, dry_run: bool, actions: list) -> None:
    """
    Move a file to destination, automatically resolving name conflicts.
    Appends a human-readable action string to `actions`.
    """
    target = destination / source.name

    if not target.exists():
        actions.append(f"{source.name} -> {destination.name}/")
        if not dry_run:
            shutil.move(source, target)
        return

    counter = 1
    while True:
        new_name = f"{source.stem}({counter}){source.suffix}"
        target = destination / new_name
        if not target.exists():
            actions.append(f"{source.name} -> {destination.name}/{new_name} (renamed)")
            if not dry_run:
                shutil.move(source, target)
            break
        counter += 1


def _organize_single_dir(
    base: Path,
    dry_run: bool,
    root_destination_folders: set,
) -> dict:
    """
    Organize the files directly inside `base`.
    Returns a per-directory result dict.
    """
    categories = _build_categories(base)
    local_dest_folders = _resolve_destination_folders(categories)

    if not dry_run:
        for cat in categories.values():
            cat["folder"].mkdir(exist_ok=True)

    # Combine root-level and local-level destination folders so we never
    # accidentally descend into or move organised output folders.
    all_dest_folders = root_destination_folders | local_dest_folders

    skipped_directories = 0
    other_files = 0
    actions = []

    entries = list(base.iterdir())

    for entry in entries:
        if entry.is_dir():
            if entry not in all_dest_folders:
                skipped_directories += 1
            continue

        ext = entry.suffix.lower()
        moved = False

        for cat in categories.values():
            if ext in cat["ext"]:
                cat["count"] += 1
                _move_file(cat["folder"], entry, dry_run, actions)
                moved = True
                break

        if not moved:
            other_files += 1

    if not dry_run:
        for folder in local_dest_folders:
            if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                try:
                    folder.rmdir()
                except OSError:
                    pass  # non-fatal: another process may have written here

    return {
        "total_items": len(entries),
        "skipped_directories": skipped_directories,
        "categories": {name: data["count"] for name, data in categories.items()},
        "other_files": other_files,
        "actions": actions,
        "dry_run": dry_run,
    }


def _collect_subdirectories(
    base: Path,
    max_depth: int | None,
    follow_symlinks: bool,
    root_destination_folders: set,
    _current_depth: int = 1,
    _seen_inodes: set | None = None,
) -> list[tuple[Path, int]]:
    """
    Recursively collect (path, depth) tuples for all safe subdirectories.

    Safety guarantees
    -----------------
    - Symlinked directories are skipped unless `follow_symlinks=True`.
    - Already-visited real inodes are skipped to prevent infinite loops caused
      by circular symlinks even when `follow_symlinks=True`.
    - Organised output folders (root_destination_folders) are never descended into.
    - max_depth=None means unlimited depth.
    """
    if _seen_inodes is None:
        _seen_inodes = set()

    results: list[tuple[Path, int]] = []

    try:
        children = list(base.iterdir())
    except PermissionError:
        return results

    for child in children:
        if not child.is_dir():
            continue

        # --- safety: skip organised output folders ---
        if child in root_destination_folders:
            continue

        # --- safety: skip symlinks unless opted in ---
        if child.is_symlink():
            if not follow_symlinks:
                continue
            # Even if following symlinks, track real inodes to detect loops
            try:
                real = child.resolve()
                inode = real.stat().st_ino
            except OSError:
                continue  # broken symlink
            if inode in _seen_inodes:
                continue  # loop detected
            _seen_inodes.add(inode)

        # --- safety: restrict read access ---
        try:
            child.stat()
        except PermissionError:
            continue

        results.append((child, _current_depth))

        # recurse if within depth budget
        if max_depth is None or _current_depth < max_depth:
            results.extend(
                _collect_subdirectories(
                    child,
                    max_depth=max_depth,
                    follow_symlinks=follow_symlinks,
                    root_destination_folders=root_destination_folders,
                    _current_depth=_current_depth + 1,
                    _seen_inodes=_seen_inodes,
                )
            )

    return results


def organize_folder(
    base: Path,
    dry_run: bool = False,
    recursive: bool = False,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
) -> dict:
    """
    Organise files inside `base`, optionally recursing into subdirectories.

    Parameters
    ----------
    base          : root directory to organise
    dry_run       : when True, log actions without moving anything
    recursive     : descend into subdirectories
    max_depth     : maximum recursion depth (None = unlimited; ignored when recursive=False)
    follow_symlinks : include symlinked directories in traversal (default False)
    """
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError("Path must be an existing directory.")

    # Build root-level destination folders once so the recursive walk can avoid
    # them completely; they should never be traversed or reorganised.
    root_categories = _build_categories(base)
    root_dest_folders = _resolve_destination_folders(root_categories)

    # --- organise the root directory ---
    root_result = _organize_single_dir(
        base,
        dry_run=dry_run,
        root_destination_folders=root_dest_folders,
    )

    if not recursive:
        return root_result

    # --- recursive walk ---
    subdirs = _collect_subdirectories(
        base,
        max_depth=max_depth,
        follow_symlinks=follow_symlinks,
        root_destination_folders=root_dest_folders,
    )

    # Aggregate totals across all directories
    combined_actions = list(root_result["actions"])
    combined_categories = dict(root_result["categories"])
    total_items = root_result["total_items"]
    total_skipped = root_result["skipped_directories"]
    total_other = root_result["other_files"]
    dirs_processed = [base]

    for subdir, depth in subdirs:
        sub_result = _organize_single_dir(
            subdir,
            dry_run=dry_run,
            root_destination_folders=root_dest_folders,
        )

        # Prefix each action with relative path for clarity
        rel = subdir.relative_to(base)
        for action in sub_result["actions"]:
            combined_actions.append(f"[{rel}] {action}")

        for name, count in sub_result["categories"].items():
            combined_categories[name] = combined_categories.get(name, 0) + count

        total_items += sub_result["total_items"]
        total_skipped += sub_result["skipped_directories"]
        total_other += sub_result["other_files"]
        dirs_processed.append(subdir)

    return {
        "total_items": total_items,
        "skipped_directories": total_skipped,
        "categories": combined_categories,
        "other_files": total_other,
        "actions": combined_actions,
        "dry_run": dry_run,
        # v2 extras
        "recursive": recursive,
        "dirs_processed": len(dirs_processed),
        "max_depth": max_depth,
        "follow_symlinks": follow_symlinks,
    }