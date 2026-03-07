"""
foldr.empty_dirs
~~~~~~~~~~~~~~~~
Empty directory scanning and optional removal for FOLDR v4.

Design
------
- Scan finds ALL empty directories under `base` (including nested ones
  that only contain other empty dirs — "recursively empty").
- Removal is opt-in and always confirmed by the user via the CLI.
- FOLDR's own output directories are never reported even if empty
  (they are cleaned by the organizer after a run already).
- Symlinked directories are never removed.

A "recursively empty" directory is one that contains no files anywhere
in its subtree — only empty directories or nothing.
"""
from __future__ import annotations

import os
from pathlib import Path

from foldr.models import EmptyDirScanResult


def _is_recursively_empty(path: Path) -> bool:
    """Return True if `path` contains no files anywhere in its subtree."""
    try:
        for root, dirs, files in os.walk(path):
            if files:
                return False
            # Filter out symlinks to dirs which os.walk follows
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        return True
    except PermissionError:
        return False


def scan_empty_dirs(
    base: Path,
    exclude: set[Path] | None = None,
    recursive: bool = True,
) -> EmptyDirScanResult:
    """
    Find all recursively-empty directories under `base`.

    `exclude`   : paths to skip (e.g. FOLDR output folders)
    `recursive` : if False, only checks immediate children
    """
    result = EmptyDirScanResult()
    exclude = exclude or set()

    try:
        children = list(base.iterdir())
    except PermissionError:
        return result

    for child in children:
        if not child.is_dir():
            continue
        if child.is_symlink():
            continue
        if child in exclude:
            continue

        if _is_recursively_empty(child):
            result.found.append(child)
        elif recursive:
            # Recurse to find nested empty dirs
            sub = scan_empty_dirs(child, exclude=exclude, recursive=True)
            result.found.extend(sub.found)

    # Sort deepest first so we can remove leaves before parents
    result.found.sort(key=lambda p: len(p.parts), reverse=True)
    return result


def remove_empty_dirs(paths: list[Path], dry_run: bool = False) -> EmptyDirScanResult:
    """
    Remove a list of empty directories (deepest first is assumed).

    Returns result with `removed` and `skipped` populated.
    """
    result = EmptyDirScanResult(found=list(paths))

    # Sort deepest first to avoid "directory not empty" errors
    sorted_paths = sorted(paths, key=lambda p: len(p.parts), reverse=True)

    for path in sorted_paths:
        if not path.exists():
            result.skipped.append(path)
            continue
        if path.is_symlink():
            result.skipped.append(path)
            continue
        if not _is_recursively_empty(path):
            result.skipped.append(path)
            continue

        if dry_run:
            result.removed.append(path)
            continue

        try:
            # rmdir only works on truly empty dirs; walk deepest-first
            for root, dirs, files in os.walk(path, topdown=False):
                if not files:
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass
            if path.exists():
                result.skipped.append(path)
            else:
                result.removed.append(path)
        except OSError:
            result.skipped.append(path)

    return result