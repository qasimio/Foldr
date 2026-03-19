"""
foldr.dedup
~~~~~~~~~~~
Duplicate file detection for FOLDR v0.2.1.

Algorithm
---------
1. Group files by size (fast pre-filter; different sizes can't be equal)
2. For size-collision groups, compute SHA-256 of full file content
3. Groups with 2+ files sharing the same hash are duplicates

Strategies
----------
keep-newest   : keep the most recently modified file
keep-largest  : keep the largest (they're identical, but largest = safest
                if partial corruption ever occurred — rare but principled)
keep-oldest   : keep the oldest (original provenance)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from foldr.models import DedupeStrategy, DuplicateGroup


_CHUNK = 65_536  # 64 KB read chunks


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(_CHUNK):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def find_duplicates(paths: list[Path]) -> list[DuplicateGroup]:
    """
    Scan `paths` for duplicate files.
    Returns groups where len(files) >= 2.
    """
    # Stage 1: group by size
    by_size: dict[int, list[Path]] = {}
    for p in paths:
        try:
            size = p.stat().st_size
        except OSError:
            continue
        by_size.setdefault(size, []).append(p)

    # Stage 2: hash size-collision groups
    by_hash: dict[str, list[Path]] = {}
    for size, group in by_size.items():
        if len(group) < 2:
            continue  # unique size → can't be duplicate
        for p in group:
            digest = _sha256(p)
            if digest:
                by_hash.setdefault(digest, []).append(p)

    return [
        DuplicateGroup(sha256=digest, files=files)
        for digest, files in by_hash.items()
        if len(files) >= 2
    ]


def resolve_strategy(group: DuplicateGroup, strategy: DedupeStrategy) -> DuplicateGroup:
    """
    Decide which file to keep and which to remove.
    Mutates and returns the group.
    """
    files = group.files

    if strategy == DedupeStrategy.KEEP_NEWEST:
        key = lambda p: p.stat().st_mtime if p.exists() else 0
        group.keep = max(files, key=key)
    elif strategy == DedupeStrategy.KEEP_OLDEST:
        key = lambda p: p.stat().st_mtime if p.exists() else float("inf")
        group.keep = min(files, key=key)
    elif strategy == DedupeStrategy.KEEP_LARGEST:
        key = lambda p: p.stat().st_size if p.exists() else 0
        group.keep = max(files, key=key)
    else:
        group.keep = files[0]

    group.remove = [f for f in files if f != group.keep]
    return group


def collect_files(base: Path, recursive: bool, max_depth: int | None) -> list[Path]:
    """Collect all files under `base` for duplicate scanning."""
    results: list[Path] = []

    def _walk(directory: Path, depth: int) -> None:
        try:
            for entry in directory.iterdir():
                if entry.is_file() and not entry.is_symlink():
                    results.append(entry)
                elif entry.is_dir() and not entry.is_symlink():
                    if recursive and (max_depth is None or depth < max_depth):
                        _walk(entry, depth + 1)
        except PermissionError:
            pass

    _walk(base, 1)
    return results