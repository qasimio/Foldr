"""
foldr.prefs
~~~~~~~~~~~
User preferences stored in ~/.foldr/prefs.json

Handles:
  - Output mode: "tui" | "cli"  (user picks once, saved forever)
  - Theme choice (future)
  - Any other persistent user preference

Read by cli.py to decide rendering mode.
Written by `foldr config` command or first-run prompt.
"""
from __future__ import annotations
import json
from pathlib import Path

_PREFS_PATH = Path.home() / ".foldr" / "prefs.json"
_DEFAULTS: dict = {
    "mode":    "tui",     # "tui" | "cli"
    "version": 4,
}


def _load() -> dict:
    if _PREFS_PATH.exists():
        try:
            return {**_DEFAULTS, **json.loads(_PREFS_PATH.read_text())}
        except Exception:
            pass
    return dict(_DEFAULTS)


def _save(prefs: dict) -> None:
    _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_PATH.write_text(json.dumps(prefs, indent=2))


def get(key: str, default=None):
    return _load().get(key, default)


def set_pref(key: str, value) -> None:
    p = _load()
    p[key] = value
    _save(p)


def get_mode() -> str:
    """Return "tui" or "cli"."""
    return _load().get("mode", "tui")


def set_mode(mode: str) -> None:
    assert mode in ("tui", "cli")
    set_pref("mode", mode)


def all_prefs() -> dict:
    return _load()