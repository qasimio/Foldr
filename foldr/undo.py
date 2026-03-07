"""
undo.py — FOLDR v3 undo & recovery system

Reads JSON history files from ~/.foldr/history/ and moves files back
to their original locations.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from .organizer import load_history, latest_history_id, list_history


def undo_run(
    run_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Reverse a previous organize_folder run.

    Parameters
    ----------
    run_id  : specific run ID to undo (default: latest)
    dry_run : preview only

    Returns a result dict with keys: run_id, restored, skipped, errors, actions
    """
    target_id = run_id or latest_history_id()
    if target_id is None:
        raise FileNotFoundError("No FOLDR history found. Nothing to undo.")

    history = load_history(target_id)
    entries = history.get("entries", [])

    restored = 0
    skipped = 0
    errors = []
    actions = []

    for entry in reversed(entries):  # reverse: undo newest moves first
        src = Path(entry["src"])   # original location
        dst = Path(entry["dst"])   # where foldr moved it to

        if not dst.exists():
            skipped += 1
            actions.append(f"[yellow]SKIP[/yellow] {dst.name} (already moved or deleted)")
            continue

        # Ensure original parent dir exists
        if not src.parent.exists():
            try:
                if not dry_run:
                    src.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                errors.append(str(e))
                actions.append(f"[red]ERROR[/red] {dst.name}: {e}")
                continue

        # Conflict check at restore target
        restore_target = src
        if src.exists() and src != dst:
            stem = src.stem
            suffix = src.suffix
            counter = 1
            while restore_target.exists():
                restore_target = src.parent / f"{stem}_restored({counter}){suffix}"
                counter += 1

        actions.append(f"{dst.name} → {restore_target.parent.name}/")

        if not dry_run:
            try:
                shutil.move(str(dst), str(restore_target))
                restored += 1
            except OSError as e:
                errors.append(str(e))
                actions.append(f"[red]ERROR[/red] {dst.name}: {e}")
        else:
            restored += 1

    return {
        "run_id": target_id,
        "restored": restored,
        "skipped": skipped,
        "errors": errors,
        "actions": actions,
        "dry_run": dry_run,
        "total": len(entries),
    }