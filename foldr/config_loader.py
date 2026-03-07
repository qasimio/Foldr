"""
foldr.config_loader
~~~~~~~~~~~~~~~~~~~~
Loads and merges category configuration for FOLDR v3.

Priority (highest → lowest)
---------------------------
1. --config <path> (explicit CLI flag)
2. ~/.config/foldr/config.toml  (Linux/macOS)
   %USERPROFILE%\\.foldr\\config.toml  (Windows)
3. Built-in CATEGORIES_TEMPLATE

A user config is *merged*: user-defined categories override or extend
built-in ones.  Set merge = false in [foldr] to replace entirely.
"""
from __future__ import annotations

import platform
from pathlib import Path
from copy import deepcopy

from foldr.config import CATEGORIES_TEMPLATE

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli
    except ImportError:
        tomllib = None  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Default user config locations
# ──────────────────────────────────────────────────────────────────────────────

def _default_config_path() -> Path:
    if platform.system() == "Windows":
        base = Path.home() / ".foldr"
    else:
        xdg = Path.home() / ".config"
        base = xdg / "foldr"
    return base / "config.toml"


# ──────────────────────────────────────────────────────────────────────────────
# TOML parsing
# ──────────────────────────────────────────────────────────────────────────────

def _parse_toml(path: Path) -> dict:
    if tomllib is None:
        raise RuntimeError(
            "TOML config requires Python 3.11+ or `pip install tomli`."
        )
    with open(path, "rb") as f:
        return tomllib.load(f)


def _toml_to_template(data: dict) -> dict:
    """
    Convert a parsed TOML dict into the CATEGORIES_TEMPLATE format.

    Expected TOML structure
    -----------------------
    [Images]
    extensions = [".png", ".jpg"]
    folder = "Images"          # optional, defaults to category name

    [foldr]
    merge = true               # optional, default true
    """
    template: dict = {}
    for section, value in data.items():
        if section == "foldr":
            continue  # meta-section
        if not isinstance(value, dict):
            continue
        exts = value.get("extensions") or value.get("ext") or []
        folder = value.get("folder", section)
        template[section] = {
            "folder": folder,
            "ext": set(e.lower() for e in exts),
        }
    return template


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def load_template(config_path: Path | None = None) -> tuple[dict, str | None]:
    """
    Return (merged_template, source_label).

    source_label is a human-readable string for the CLI to display,
    or None if using built-in defaults.
    """
    # Try explicit path first, then user default
    path: Path | None = None
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        path = config_path
        label = str(config_path)
    else:
        default = _default_config_path()
        if default.exists():
            path = default
            label = str(default)
        else:
            return deepcopy(CATEGORIES_TEMPLATE), None

    raw = _parse_toml(path)
    user_template = _toml_to_template(raw)

    # Merge behaviour
    foldr_meta = raw.get("foldr", {})
    should_merge = foldr_meta.get("merge", True)

    if should_merge:
        merged = deepcopy(CATEGORIES_TEMPLATE)
        for name, data in user_template.items():
            if name in merged:
                # Extend existing category's extensions
                merged[name]["ext"] = merged[name]["ext"] | data["ext"]
            else:
                merged[name] = data
        return merged, label
    else:
        return user_template, label