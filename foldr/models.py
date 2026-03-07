"""
foldr.models
~~~~~~~~~~~~
Shared data structures for FOLDR v4.
All dataclasses live here so every module imports from one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


@dataclass
class OperationRecord:
    """Single file-move record, used for undo and history display."""
    op_id: str
    source: str
    destination: str
    filename: str
    category: str
    timestamp: str


@dataclass
class OrganizeResult:
    """Everything the CLI and callers need after an organize run."""
    total_items: int = 0
    skipped_directories: int = 0
    other_files: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    records: list[OperationRecord] = field(default_factory=list)
    dry_run: bool = False
    recursive: bool = False
    dirs_processed: int = 1
    max_depth: int | None = None
    follow_symlinks: bool = False
    ignored_files: int = 0
    ignored_dirs: int = 0
    verbose_log: list[str] = field(default_factory=list)
    empty_dirs_found: list[Path] = field(default_factory=list)
    duplicates: list["DuplicateGroup"] = field(default_factory=list)
    mime_overrides: int = 0


class DedupeStrategy(Enum):
    KEEP_NEWEST  = auto()
    KEEP_LARGEST = auto()
    KEEP_OLDEST  = auto()


@dataclass
class DuplicateGroup:
    sha256: str
    files: list[Path]
    keep: Path | None = None
    remove: list[Path] = field(default_factory=list)


@dataclass
class EmptyDirScanResult:
    found: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


@dataclass
class UndoResult:
    restored: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    log_deleted: bool = False
    log_archived: bool = False