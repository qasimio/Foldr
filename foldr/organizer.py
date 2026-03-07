"""
foldr.organizer
~~~~~~~~~~~~~~~
Core file-organisation engine for FOLDR v4.
"""
from __future__ import annotations

import fnmatch
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from foldr.config import CATEGORIES_TEMPLATE
from foldr.models import OperationRecord, OrganizeResult


def _build_categories(base: Path, template: dict) -> dict:
    return {
        name: {
            "folder": base / data["folder"],
            "ext": set(e.lower() for e in data["ext"]),
            "count": 0,
        }
        for name, data in template.items()
    }


def _dest_folders(categories: dict) -> set[Path]:
    return {cat["folder"] for cat in categories.values()}


def _load_foldrignore(base: Path) -> list[str]:
    ignore_file = base / ".foldrignore"
    if not ignore_file.exists():
        return []
    patterns: list[str] = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _matches_any(name: str, rel_path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/"):
            if fnmatch.fnmatch(name, pattern.rstrip("/")) or fnmatch.fnmatch(rel_path, pattern.rstrip("/")):
                return True
        else:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return True
    return False


def _move_file(
    destination: Path,
    source: Path,
    category: str,
    dry_run: bool,
    result: OrganizeResult,
    rel_prefix: str = "",
) -> None:
    target = destination / source.name

    if target.exists():
        counter = 1
        while True:
            candidate = destination / f"{source.stem}({counter}){source.suffix}"
            if not candidate.exists():
                target = candidate
                break
            counter += 1

    label = f"[{rel_prefix}] " if rel_prefix else ""
    display = target.name if target.name != source.name else ""
    result.actions.append(
        f"{label}{source.name} → {destination.name}/{display}"
    )

    record = OperationRecord(
        op_id=str(uuid.uuid4()),
        source=str(source),
        destination=str(target),
        filename=source.name,
        category=category,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    result.records.append(record)

    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))


def _organize_dir(
    directory: Path,
    root_categories: dict,
    root_dest_folders: set[Path],
    dry_run: bool,
    ignore_patterns: list[str],
    root_base: Path,
    result: OrganizeResult,
) -> None:
    try:
        entries = list(directory.iterdir())
    except PermissionError:
        return

    result.total_items += len(entries)

    for entry in entries:
        try:
            rel = str(entry.relative_to(root_base))
        except ValueError:
            rel = entry.name

        if entry.is_dir():
            if entry in root_dest_folders:
                continue
            if _matches_any(entry.name, rel, ignore_patterns):
                result.ignored_dirs += 1
                continue
            result.skipped_directories += 1
            continue

        if _matches_any(entry.name, rel, ignore_patterns):
            result.ignored_files += 1
            continue

        ext = entry.suffix.lower()
        moved = False

        for cat_name, cat in root_categories.items():
            if ext in cat["ext"]:
                cat["count"] += 1
                rel_prefix = (
                    str(directory.relative_to(root_base))
                    if directory != root_base else ""
                )
                _move_file(
                    destination=cat["folder"],
                    source=entry,
                    category=cat_name,
                    dry_run=dry_run,
                    result=result,
                    rel_prefix=rel_prefix,
                )
                moved = True
                break

        if not moved:
            result.other_files += 1


def _collect_subdirs(
    base: Path,
    max_depth: int | None,
    follow_symlinks: bool,
    root_dest_folders: set[Path],
    ignore_patterns: list[str],
    root_base: Path,
    _depth: int = 1,
    _seen: set[int] | None = None,
) -> list[Path]:
    if _seen is None:
        _seen = set()

    result: list[Path] = []

    try:
        children = list(base.iterdir())
    except PermissionError:
        return result

    for child in children:
        if not child.is_dir():
            continue
        if child in root_dest_folders:
            continue

        try:
            rel = str(child.relative_to(root_base))
        except ValueError:
            rel = child.name
        if _matches_any(child.name, rel, ignore_patterns):
            continue

        if child.is_symlink():
            if not follow_symlinks:
                continue
            try:
                real_inode = child.resolve().stat().st_ino
            except OSError:
                continue
            if real_inode in _seen:
                continue
            _seen.add(real_inode)

        try:
            child.stat()
        except PermissionError:
            continue

        result.append(child)

        if max_depth is None or _depth < max_depth:
            result.extend(
                _collect_subdirs(
                    child, max_depth, follow_symlinks,
                    root_dest_folders, ignore_patterns, root_base,
                    _depth + 1, _seen,
                )
            )

    return result


def organize_folder(
    base: Path,
    dry_run: bool = False,
    recursive: bool = False,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
    extra_ignore: list[str] | None = None,
    category_template: dict | None = None,
    smart: bool = False,  # accepted but no-op unless python-magic present
) -> OrganizeResult:
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError("Path must be an existing directory.")

    template = category_template if category_template is not None else CATEGORIES_TEMPLATE
    root_categories = _build_categories(base, template)
    root_dest_folders = _dest_folders(root_categories)

    ignore_patterns = _load_foldrignore(base)
    if extra_ignore:
        ignore_patterns.extend(extra_ignore)

    result = OrganizeResult(
        dry_run=dry_run,
        recursive=recursive,
        max_depth=max_depth,
        follow_symlinks=follow_symlinks,
        categories={name: 0 for name in root_categories},
    )

    _organize_dir(
        directory=base,
        root_categories=root_categories,
        root_dest_folders=root_dest_folders,
        dry_run=dry_run,
        ignore_patterns=ignore_patterns,
        root_base=base,
        result=result,
    )
    result.dirs_processed = 1

    if recursive:
        subdirs = _collect_subdirs(
            base=base,
            max_depth=max_depth,
            follow_symlinks=follow_symlinks,
            root_dest_folders=root_dest_folders,
            ignore_patterns=ignore_patterns,
            root_base=base,
        )
        for subdir in subdirs:
            _organize_dir(
                directory=subdir,
                root_categories=root_categories,
                root_dest_folders=root_dest_folders,
                dry_run=dry_run,
                ignore_patterns=ignore_patterns,
                root_base=base,
                result=result,
            )
            result.dirs_processed += 1

    result.categories = {name: cat["count"] for name, cat in root_categories.items()}

    if not dry_run:
        for folder in root_dest_folders:
            if folder.exists() and folder.is_dir():
                try:
                    if not any(folder.iterdir()):
                        folder.rmdir()
                except OSError:
                    pass

    return result