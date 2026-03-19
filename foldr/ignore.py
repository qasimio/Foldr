"""
ignore.py — FOLDR v0.2.1 ignore rules

Supports:
  - .foldrignore file in the target directory
  - Extra patterns passed via --ignore CLI flag
  - Wildcard glob patterns (fnmatch)
  - Directory-specific patterns (trailing /)
  - Extension patterns (*.tmp)
  - Exact file/directory names
"""

from __future__ import annotations

import fnmatch
from pathlib import Path


FOLDRIGNORE_FILE = ".foldrignore"

# Patterns always ignored regardless of user config
ALWAYS_IGNORE_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv"}
ALWAYS_IGNORE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}


class IgnoreRules:
    def __init__(self, base: Path, extra_patterns: list[str] | None = None):
        self._file_patterns: list[str] = []
        self._dir_patterns: list[str] = []

        # Load .foldrignore
        ignore_file = base / FOLDRIGNORE_FILE
        if ignore_file.exists():
            self._load_file(ignore_file)

        # Load extra CLI patterns
        for pat in (extra_patterns or []):
            self._classify_pattern(pat.strip())

    def _load_file(self, path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self._classify_pattern(line)

    def _classify_pattern(self, pattern: str) -> None:
        if pattern.endswith("/"):
            self._dir_patterns.append(pattern.rstrip("/"))
        else:
            self._file_patterns.append(pattern)

    def matches_file(self, path: Path) -> bool:
        name = path.name
        if name in ALWAYS_IGNORE_FILES:
            return True
        for pat in self._file_patterns:
            if fnmatch.fnmatch(name, pat):
                return True
        return False

    def matches_dir(self, path: Path) -> bool:
        name = path.name
        if name in ALWAYS_IGNORE_DIRS:
            return True
        for pat in self._dir_patterns:
            if fnmatch.fnmatch(name, pat):
                return True
        # Dir patterns can also match file patterns (e.g. "build" ignores dir named "build")
        for pat in self._file_patterns:
            if fnmatch.fnmatch(name, pat):
                return True
        return False