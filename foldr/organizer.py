"""
organizer.py — FOLDR v2 core engine

THE FIX (nested-folder bug):
  In v2's previous attempt, build_category_map(base) was called per-subdirectory,
  producing lol/Code/, lol/Videos/ etc.

  The correct design: build_category_map is called ONCE with the run root.
  ALL files from ALL depths are moved into root-level output folders only.
  lol/script.py  →  <root>/Code/script.py   (never lol/Code/script.py)
"""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path
from typing import NamedTuple

from foldr.config import CATEGORIES_TEMPLATE


# ─── Data types ──────────────────────────────────────────────────────────────

class MoveRecord(NamedTuple):
    """One file-move event. Written to history JSON for undo."""
    source: Path
    destination: Path
    category: str
    source_dir: Path


# ─── Category map ─────────────────────────────────────────────────────────────

def build_category_map(
    root: Path,
    custom_config: dict | None = None,
) -> dict[str, dict]:
    """
    Build category → {folder, ext, count} map.

    Output folders are ALWAYS rooted at `root`, regardless of which
    subdirectory a file is found in. This is the core fix.

    custom_config entries win on name collision with the built-in template.
    """
    template = dict(CATEGORIES_TEMPLATE)
    if custom_config:
        for name, data in custom_config.items():
            template[name] = data

    return {
        name: {
            "folder": root / data["folder"],   # ← always root-relative
            "ext": set(data["ext"]),
            "count": 0,
        }
        for name, data in template.items()
    }


# ─── Ignore rules ─────────────────────────────────────────────────────────────

def load_ignore_patterns(
    base: Path,
    extra_patterns: list[str] | None = None,
) -> list[str]:
    """
    Merge patterns from .foldrignore in `base` with any CLI-supplied patterns.
    Blank lines and # comments are skipped.
    """
    patterns: list[str] = []

    ignore_file = base / ".foldrignore"
    if ignore_file.exists():
        for line in ignore_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)

    if extra_patterns:
        patterns.extend(extra_patterns)

    return patterns


def _is_ignored(path: Path, patterns: list[str], base: Path) -> bool:
    """
    Return True if `path` matches any ignore pattern.

    Rules:
      node_modules/   → directory named node_modules
      *.tmp           → any file/dir matching *.tmp
      .env            → exact filename
      src/*.py        → matched against relative path
    """
    if not patterns:
        return False

    name = path.name
    try:
        rel = str(path.relative_to(base))
    except ValueError:
        rel = name

    for pat in patterns:
        is_dir_pat = pat.endswith("/")
        clean = pat.rstrip("/")

        if is_dir_pat:
            if path.is_dir() and fnmatch.fnmatch(name, clean):
                return True
        else:
            if fnmatch.fnmatch(name, clean):
                return True
            if fnmatch.fnmatch(rel, clean):
                return True

    return False


# ─── File mover ───────────────────────────────────────────────────────────────

def _move_file(
    destination: Path,
    source: Path,
    category: str,
    dry_run: bool,
    actions: list[str],
    records: list[MoveRecord],
    source_dir: Path,
) -> None:
    target = destination / source.name

    if not target.exists():
        actions.append(f"{source.name}  →  {destination.name}/")
        records.append(MoveRecord(source, target, category, source_dir))
        if not dry_run:
            shutil.move(str(source), str(target))
        return

    counter = 1
    while True:
        new_name = f"{source.stem}({counter}){source.suffix}"
        target = destination / new_name
        if not target.exists():
            actions.append(
                f"{source.name}  →  {destination.name}/{new_name}  [renamed]"
            )
            records.append(MoveRecord(source, target, category, source_dir))
            if not dry_run:
                shutil.move(str(source), str(target))
            break
        counter += 1


# ─── Directory traversal ──────────────────────────────────────────────────────

def _collect_subdirs(
    base: Path,
    root_dest_folders: set[Path],
    ignore_patterns: list[str],
    ignore_root: Path,
    max_depth: int | None,
    follow_symlinks: bool,
    _depth: int = 1,
    _seen: set[int] | None = None,
) -> list[tuple[Path, int]]:
    """
    Return sorted list of (subdir, depth) for all safe dirs under `base`.

    Safety:
    1. Never descend into root-level output folders.
    2. Skip symlinks by default; follow with inode loop-detection if opted in.
    3. Skip permission-denied dirs silently.
    4. Respect ignore patterns.
    """
    if _seen is None:
        _seen = set()

    results: list[tuple[Path, int]] = []

    try:
        children = sorted(base.iterdir())
    except PermissionError:
        return results

    for child in children:
        if not child.is_dir():
            continue

        # 1. never re-enter output folders
        if child in root_dest_folders:
            continue

        # 4. ignore rules
        if _is_ignored(child, ignore_patterns, ignore_root):
            continue

        # 2–3. symlink safety
        if child.is_symlink():
            if not follow_symlinks:
                continue
            try:
                real = child.resolve()
                inode = real.stat().st_ino
            except OSError:
                continue
            if inode in _seen:
                continue
            _seen.add(inode)

        try:
            child.stat()
        except PermissionError:
            continue

        results.append((child, _depth))

        if max_depth is None or _depth < max_depth:
            results.extend(
                _collect_subdirs(
                    base=child,
                    root_dest_folders=root_dest_folders,
                    ignore_patterns=ignore_patterns,
                    ignore_root=ignore_root,
                    max_depth=max_depth,
                    follow_symlinks=follow_symlinks,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
            )

    return results


# ─── Single-directory scan ────────────────────────────────────────────────────

def _scan_dir(
    scan_dir: Path,
    categories: dict[str, dict],
    root_dest_folders: set[Path],
    ignore_patterns: list[str],
    ignore_root: Path,
    dry_run: bool,
    actions: list[str],
    records: list[MoveRecord],
) -> tuple[int, int, int]:
    """
    Scan one directory and route its files to root-level output folders.
    Returns (total_entries, skipped_dirs, other_files).
    """
    try:
        entries = list(scan_dir.iterdir())
    except PermissionError:
        return 0, 0, 0

    skipped_dirs = 0
    other_files = 0

    for entry in entries:
        if _is_ignored(entry, ignore_patterns, ignore_root):
            continue

        if entry.is_dir():
            if entry not in root_dest_folders:
                skipped_dirs += 1
            continue

        # broken symlink
        if entry.is_symlink() and not entry.exists():
            continue

        ext = entry.suffix.lower()
        moved = False

        for cat_name, cat in categories.items():
            if ext in cat["ext"]:
                cat["count"] += 1
                _move_file(
                    destination=cat["folder"],
                    source=entry,
                    category=cat_name,
                    dry_run=dry_run,
                    actions=actions,
                    records=records,
                    source_dir=scan_dir,
                )
                moved = True
                break

        if not moved:
            other_files += 1

    return len(entries), skipped_dirs, other_files


# ─── Public API ───────────────────────────────────────────────────────────────

def organize_folder(
    base: Path,
    dry_run: bool = False,
    recursive: bool = False,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
    custom_config: dict | None = None,
    ignore_patterns: list[str] | None = None,
) -> dict:
    """
    Organise files in `base`.

    v1-compatible return dict with additional v2 keys.
    `records` contains MoveRecord instances used by the undo system.
    """
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError("Path must be an existing directory.")

    # Build category map ONCE at root level — this is the nested-folder fix
    categories = build_category_map(base, custom_config)
    root_dest_folders = {cat["folder"] for cat in categories.values()}

    if not dry_run:
        for cat in categories.values():
            cat["folder"].mkdir(exist_ok=True)

    effective_ignore = load_ignore_patterns(base, ignore_patterns)

    actions: list[str] = []
    records: list[MoveRecord] = []
    total_items = 0
    total_skipped = 0
    total_other = 0
    dirs_processed = 0

    # scan root
    items, skipped, other = _scan_dir(
        scan_dir=base,
        categories=categories,
        root_dest_folders=root_dest_folders,
        ignore_patterns=effective_ignore,
        ignore_root=base,
        dry_run=dry_run,
        actions=actions,
        records=records,
    )
    total_items += items
    total_skipped += skipped
    total_other += other
    dirs_processed += 1

    # scan subdirs
    if recursive:
        subdirs = _collect_subdirs(
            base=base,
            root_dest_folders=root_dest_folders,
            ignore_patterns=effective_ignore,
            ignore_root=base,
            max_depth=max_depth,
            follow_symlinks=follow_symlinks,
        )

        for subdir, _ in subdirs:
            rel = subdir.relative_to(base)
            sub_actions: list[str] = []

            items, skipped, other = _scan_dir(
                scan_dir=subdir,
                categories=categories,
                root_dest_folders=root_dest_folders,
                ignore_patterns=effective_ignore,
                ignore_root=base,
                dry_run=dry_run,
                actions=sub_actions,
                records=records,
            )

            for a in sub_actions:
                actions.append(f"[dim][{rel}][/dim] {a}")

            total_items += items
            total_skipped += skipped
            total_other += other
            dirs_processed += 1

    # remove empty output folders (execute mode)
    if not dry_run:
        for folder in root_dest_folders:
            if folder.exists() and folder.is_dir():
                try:
                    if not any(folder.iterdir()):
                        folder.rmdir()
                except OSError:
                    pass

    return {
        # v1-compatible
        "total_items": total_items,
        "skipped_directories": total_skipped,
        "categories": {name: data["count"] for name, data in categories.items()},
        "other_files": total_other,
        "actions": actions,
        "dry_run": dry_run,
        # v2
        "records": records,
        "recursive": recursive,
        "dirs_processed": dirs_processed,
        "max_depth": max_depth,
        "follow_symlinks": follow_symlinks,
        "ignore_patterns": effective_ignore,
    }