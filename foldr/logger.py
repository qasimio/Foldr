"""
foldr.logger
~~~~~~~~~~~~
Structured logging and output verbosity for FOLDR v4.

Verbosity levels
----------------
  quiet   : only errors and final summary counts
  normal  : actions + summary (default)
  verbose : everything including skipped/ignored files, MIME overrides,
            empty dir scan results, timing

Log storage
-----------
Structured JSON operation logs → ~/.foldr/logs/
  2026-03-07_15-20-33_a1b2c3_operation.json

Schema
------
{
  "operation_id": "a1b2c3",
  "timestamp": "...",
  "base": "/path",
  "dry_run": false,
  "recursive": true,
  "files_moved": [{"filename": ..., "source": ..., "destination": ..., "category": ...}],
  "files_skipped": [{"filename": ..., "reason": ...}],
  "files_ignored": [...],
  "duplicates_found": int,
  "empty_dirs_found": int,
  "duration_seconds": 1.23
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foldr.models import OrganizeResult


class Verbosity(Enum):
    QUIET   = auto()
    NORMAL  = auto()
    VERBOSE = auto()


def logs_dir() -> Path:
    return Path.home() / ".foldr" / "logs"


def _ensure_logs_dir() -> Path:
    d = logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_operation_log(
    result: "OrganizeResult",
    base: Path,
    duration_seconds: float,
    operation_id: str,
) -> Path | None:
    """Write a structured JSON operation log. Returns log path or None on dry-run."""
    if result.dry_run:
        return None

    d = _ensure_logs_dir()
    now = datetime.now(timezone.utc)
    filename = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{operation_id}_operation.json"
    log_path = d / filename

    files_moved = [
        {
            "filename": r.filename,
            "source": r.source,
            "destination": r.destination,
            "category": r.category,
            "timestamp": r.timestamp,
        }
        for r in result.records
    ]

    payload = {
        "operation_id": operation_id,
        "timestamp": now.isoformat(),
        "base": str(base),
        "dry_run": result.dry_run,
        "recursive": result.recursive,
        "max_depth": result.max_depth,
        "follow_symlinks": result.follow_symlinks,
        "files_moved": files_moved,
        "files_skipped": [],   # future: populate from result
        "files_ignored": result.ignored_files,
        "dirs_ignored": result.ignored_dirs,
        "duplicates_found": len(result.duplicates),
        "empty_dirs_found": len(result.empty_dirs_found),
        "mime_overrides": result.mime_overrides,
        "duration_seconds": round(duration_seconds, 3),
        "summary": {
            cat: count
            for cat, count in result.categories.items()
            if count > 0
        },
    }

    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return log_path