"""
foldr.history
~~~~~~~~~~~~~
Operation history logging and undo system for FOLDR v3.

History location
----------------
  Linux/macOS : ~/.foldr/history/
  Windows     : %USERPROFILE%\\.foldr\\history\\

Each run produces a JSON file named by timestamp + short UUID:
  2026-03-07_15-20-33_a1b2c3.json

Undo reads the latest log (or a specific --id) and moves files back.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foldr.organizer import OperationRecord


# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

def history_dir() -> Path:
    return Path.home() / ".foldr" / "history"


def _ensure_history_dir() -> Path:
    d = history_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Save
# ──────────────────────────────────────────────────────────────────────────────

def save_history(records: list, base: Path, dry_run: bool) -> Path | None:
    """Persist operation records to a JSON log. Returns the log path, or None for dry-runs."""
    if dry_run or not records:
        return None

    d = _ensure_history_dir()
    now = datetime.now(timezone.utc)
    short_id = records[0].op_id.replace("-", "")[:6]
    filename = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{short_id}.json"
    log_path = d / filename

    payload = {
        "id": short_id,
        "timestamp": now.isoformat(),
        "base": str(base),
        "total_files": len(records),
        "records": [
            {
                "op_id": r.op_id,
                "source": r.source,
                "destination": r.destination,
                "filename": r.filename,
                "category": r.category,
                "timestamp": r.timestamp,
            }
            for r in records
        ],
    }
    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return log_path


# ──────────────────────────────────────────────────────────────────────────────
# List
# ──────────────────────────────────────────────────────────────────────────────

def list_history(limit: int = 10) -> list[dict]:
    """Return recent history entries (newest first)."""
    d = history_dir()
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), reverse=True)[:limit]
    entries = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entries.append({
                "id": data.get("id", f.stem),
                "filename": f.name,
                "timestamp": data.get("timestamp", ""),
                "base": data.get("base", ""),
                "total_files": data.get("total_files", 0),
                "path": f,
            })
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def get_history_entry(id_or_filename: str) -> dict | None:
    """Load a specific history entry by short ID or filename."""
    d = history_dir()
    if not d.exists():
        return None
    for f in d.glob("*.json"):
        if id_or_filename in f.name:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["path"] = f
                return data
            except (json.JSONDecodeError, OSError):
                return None
    return None


def get_latest_history() -> dict | None:
    entries = list_history(limit=1)
    if not entries:
        return None
    entry = entries[0]
    try:
        data = json.loads(entry["path"].read_text(encoding="utf-8"))
        data["path"] = entry["path"]
        return data
    except (json.JSONDecodeError, OSError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Undo result
# ──────────────────────────────────────────────────────────────────────────────

class UndoResult:
    __slots__ = ("restored", "skipped", "errors", "log_deleted")

    def __init__(self):
        self.restored: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[str] = []
        self.log_deleted: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Undo
# ──────────────────────────────────────────────────────────────────────────────

def undo_operation(log_data: dict, dry_run: bool = False) -> UndoResult:
    """
    Restore files from a history log entry.
    Reverses each record: destination → source.
    Skips missing files gracefully.
    """
    result = UndoResult()
    records = log_data.get("records", [])

    for record in reversed(records):
        dest = Path(record["destination"])
        src = Path(record["source"])

        if not dest.exists():
            result.skipped.append(
                f"{record['filename']} — not at {dest.parent.name}/ (already moved?)"
            )
            continue

        if dry_run:
            result.restored.append(f"{record['filename']}: {dest.parent.name}/ → {src.parent.name}/")
            continue

        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            target = src
            if target.exists():
                counter = 1
                while True:
                    candidate = src.parent / f"{src.stem}_restored({counter}){src.suffix}"
                    if not candidate.exists():
                        target = candidate
                        break
                    counter += 1
            shutil.move(str(dest), str(target))
            result.restored.append(f"{record['filename']}: {dest.parent.name}/ → {target.parent.name}/")
        except OSError as e:
            result.errors.append(f"{record['filename']}: {e}")

    if not dry_run and not result.errors:
        try:
            log_path = log_data.get("path")
            if log_path and Path(log_path).exists():
                Path(log_path).unlink()
                result.log_deleted = True
        except OSError:
            pass

    return result

# Foldr can undo - stores history - like git - we can rollback to previous state if needed - in case of mistakes or just to see what was done before
# properly log its action into .foldr/history
# Each run produces a JSON file named by timestamp + short UUID:
#   2026-03-07_15-20-33_a1b2c3.json
# Undo reads the latest log (or a specific --id) and moves files
# user can rollback if not liked (with approval)
# user can ask FOLDR to --ignore ''certain files or folders from being moved, and these will be respected in undo as well
# just like .gitignore
# user can add its own config - the way user want to organize (the default) and the custom (overwrite - builtin=False) and merge (builtin + custom - builtin=True) - and this will be respected in undo as well
