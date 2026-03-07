"""
foldr.organizer
~~~~~~~~~~~~~~~
Core file-organisation engine for FOLDR v4.
"""
from __future__ import annotations
import fnmatch, shutil, uuid
from datetime import datetime, timezone
from pathlib import Path

from foldr.config import CATEGORIES_TEMPLATE
from foldr.models import OperationRecord, OrganizeResult


def _build_categories(base: Path, template: dict) -> dict:
    return {
        name: {
            "folder": base / data["folder"],
            "ext":    set(e.lower() for e in data["ext"]),
            "count":  0,
        }
        for name, data in template.items()
    }

def _dest_folders(cats: dict) -> set[Path]:
    return {c["folder"] for c in cats.values()}

def _load_foldrignore(base: Path) -> list[str]:
    f = base / ".foldrignore"
    if not f.exists():
        return []
    lines = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines

def _matches(name: str, rel: str, patterns: list[str]) -> bool:
    for p in patterns:
        bare = p.rstrip("/")
        if fnmatch.fnmatch(name, bare) or fnmatch.fnmatch(rel, bare):
            return True
    return False

def _move_file(dest: Path, src: Path, category: str,
               dry_run: bool, result: OrganizeResult,
               rel_prefix: str = "") -> None:
    target = dest / src.name
    if target.exists():
        n = 1
        while True:
            candidate = dest / f"{src.stem}({n}){src.suffix}"
            if not candidate.exists():
                target = candidate
                break
            n += 1

    label = f"[{rel_prefix}] " if rel_prefix else ""
    disp  = target.name if target.name != src.name else ""
    result.actions.append(f"{label}{src.name} → {dest.name}/{disp}")

    result.records.append(OperationRecord(
        op_id       = str(uuid.uuid4()),
        source      = str(src),
        destination = str(target),
        filename    = src.name,
        category    = category,
        timestamp   = datetime.now(timezone.utc).isoformat(),
    ))
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))

def _organize_dir(directory: Path, root_cats: dict,
                  root_dests: set[Path], dry_run: bool,
                  patterns: list[str], root_base: Path,
                  result: OrganizeResult) -> None:
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
            if entry in root_dests:
                continue
            if _matches(entry.name, rel, patterns):
                result.ignored_dirs += 1
                continue
            result.skipped_directories += 1
            continue

        if _matches(entry.name, rel, patterns):
            result.ignored_files += 1
            continue

        ext   = entry.suffix.lower()
        moved = False
        for cat_name, cat in root_cats.items():
            if ext in cat["ext"]:
                cat["count"] += 1
                pfx = str(directory.relative_to(root_base)) if directory != root_base else ""
                _move_file(cat["folder"], entry, cat_name, dry_run, result, pfx)
                moved = True
                break
        if not moved:
            result.other_files += 1

def _collect_subdirs(base: Path, max_depth: int | None,
                     follow_symlinks: bool, root_dests: set[Path],
                     patterns: list[str], root_base: Path,
                     _depth: int = 1, _seen: set[int] | None = None) -> list[Path]:
    if _seen is None:
        _seen = set()
    out: list[Path] = []
    try:
        children = list(base.iterdir())
    except PermissionError:
        return out

    for child in children:
        if not child.is_dir() or child in root_dests:
            continue
        try:
            rel = str(child.relative_to(root_base))
        except ValueError:
            rel = child.name
        if _matches(child.name, rel, patterns):
            continue
        if child.is_symlink():
            if not follow_symlinks:
                continue
            try:
                inode = child.resolve().stat().st_ino
            except OSError:
                continue
            if inode in _seen:
                continue
            _seen.add(inode)
        try:
            child.stat()
        except PermissionError:
            continue
        out.append(child)
        if max_depth is None or _depth < max_depth:
            out.extend(_collect_subdirs(child, max_depth, follow_symlinks,
                                        root_dests, patterns, root_base,
                                        _depth+1, _seen))
    return out


def organize_folder(
    base: Path,
    dry_run: bool = False,
    recursive: bool = False,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
    extra_ignore: list[str] | None = None,
    category_template: dict | None = None,
    smart: bool = False,
) -> OrganizeResult:
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError("Path must be an existing directory.")

    template   = category_template if category_template is not None else CATEGORIES_TEMPLATE
    root_cats  = _build_categories(base, template)
    root_dests = _dest_folders(root_cats)

    patterns = _load_foldrignore(base)
    if extra_ignore:
        patterns.extend(extra_ignore)

    result = OrganizeResult(
        dry_run=dry_run, recursive=recursive,
        max_depth=max_depth, follow_symlinks=follow_symlinks,
        categories={n: 0 for n in root_cats},
    )

    _organize_dir(base, root_cats, root_dests, dry_run, patterns, base, result)
    result.dirs_processed = 1

    if recursive:
        for sub in _collect_subdirs(base, max_depth, follow_symlinks,
                                    root_dests, patterns, base):
            _organize_dir(sub, root_cats, root_dests, dry_run, patterns, base, result)
            result.dirs_processed += 1

    result.categories = {n: c["count"] for n, c in root_cats.items()}

    if not dry_run:
        for folder in root_dests:
            if folder.exists() and folder.is_dir():
                try:
                    if not any(folder.iterdir()):
                        folder.rmdir()
                except OSError:
                    pass
    return result