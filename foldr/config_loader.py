"""
foldr.config_loader
~~~~~~~~~~~~~~~~~~~~
Category configuration loader for FOLDR v4.

Config search order  (highest priority first)
----------------------------------------------
1. --config <file>             explicit flag on CLI
2. ~/.foldr/config.toml        auto-created with boilerplate on first run
3. Built-in CATEGORIES_TEMPLATE (always used when no config file exists)

Config file format
------------------
The config.toml file that FOLDR generates for you is self-documenting.
It contains every built-in category commented out, so you can uncomment
and edit the ones you want to change.

merge = true (default) → your changes extend the built-ins
merge = false          → your file replaces the built-ins entirely

Error handling
--------------
If the config file has a syntax error, FOLDR reports the exact line,
skips the file, and falls back to built-in defaults so you can still
use FOLDR while you fix the config.
"""
from __future__ import annotations

import platform
from copy import deepcopy
from pathlib import Path

from foldr.config import CATEGORIES_TEMPLATE

# Try stdlib tomllib (Python 3.11+), then tomli (pip install tomli)
try:
    import tomllib                   # type: ignore[import]
except ImportError:
    try:
        import tomli as tomllib      # type: ignore[import]
    except ImportError:
        tomllib = None               # type: ignore[assignment]


# ── Default config location ────────────────────────────────────────────────────

def config_dir() -> Path:
    """Return the FOLDR config directory (~/.foldr on all platforms)."""
    return Path.home() / ".foldr"


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def _default_config_paths() -> list[Path]:
    """Candidate paths in priority order (exposed for tests)."""
    return [default_config_path()]


# ── Boilerplate generator ──────────────────────────────────────────────────────

_BOILERPLATE = """\
# FOLDR category configuration
# ─────────────────────────────────────────────────────────────────────────────
#
# HOW THIS FILE WORKS
# -------------------
# FOLDR uses this file to decide where each file type gets moved.
# By default (merge = true) your changes EXTEND the built-in categories.
# Set merge = false to REPLACE the built-ins entirely with only what's here.
#
# QUICK EXAMPLES
# ──────────────
# Add a new file type to an existing category:
#
#   [Documents]
#   extensions = [".tex", ".bib"]       # these are added to the built-ins
#
# Create a brand new category:
#
#   [RAW Photos]
#   folder     = "RAW_Photos"           # folder name inside the target dir
#   extensions = [".raw", ".cr2", ".nef", ".arw", ".dng"]
#
# Rename the folder an existing category uses:
#
#   [Code]
#   folder = "Source_Code"              # default was "Code"
#
# Replace built-ins entirely (only your categories will be used):
#
#   [foldr]
#   merge = false
#
# ─────────────────────────────────────────────────────────────────────────────

[foldr]
# merge = true   # true = extend built-ins  |  false = replace built-ins
merge = true


# ── Uncomment and edit any section below to customise it ──────────────────────

# [Documents]
# extensions = [".pages", ".numbers", ".key"]

# [Images]
# extensions = [".heic", ".avif"]

# [Code]
# folder = "Source_Code"

# [Videos]
# extensions = [".ts"]

# ── Add your own categories below ─────────────────────────────────────────────

# [RAW Photos]
# folder     = "RAW_Photos"
# extensions = [".raw", ".cr2", ".nef", ".arw", ".orf", ".dng"]

# [Design]
# folder     = "Design"
# extensions = [".fig", ".sketch", ".xd", ".psd", ".ai"]

# [Datasets]
# folder     = "Datasets"
# extensions = [".parquet", ".feather", ".hdf5", ".h5", ".npy", ".npz"]
"""


def ensure_config_exists() -> Path:
    """
    Create ~/.foldr/config.toml with boilerplate if it doesn't exist yet.
    Returns the path (whether it existed or was just created).
    Called automatically when FOLDR first runs.
    """
    path = default_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_BOILERPLATE, encoding="utf-8")
    return path


# ── TOML parsing ───────────────────────────────────────────────────────────────

def _parse_toml(path: Path) -> dict | None:
    """
    Parse a TOML file. Returns None if tomllib is unavailable.
    Raises a descriptive RuntimeError on syntax errors instead of crashing.
    """
    if tomllib is None:
        return None       # no TOML support — fall back to built-ins silently

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        # Surface a clear, actionable error message
        raise RuntimeError(
            f"\n"
            f"  Config file has a syntax error:\n"
            f"    {path}\n"
            f"\n"
            f"  {exc}\n"
            f"\n"
            f"  Fix the error or delete the file to reset to defaults.\n"
            f"  FOLDR is now using built-in category defaults.\n"
        ) from exc


def _toml_to_template(data: dict) -> dict:
    """Convert parsed TOML dict → internal categories format."""
    template: dict = {}
    for section, value in data.items():
        if section == "foldr" or not isinstance(value, dict):
            continue
        exts   = value.get("extensions") or value.get("ext") or []
        folder = value.get("folder", section)
        template[section] = {
            "folder": folder,
            "ext":    set(e.lower().strip() for e in exts if e.strip()),
        }
    return template


def _load_and_merge(path: Path) -> tuple[dict, bool]:
    """
    Load a config file and merge with built-ins if requested.
    Returns (template_dict, had_error).
    had_error=True means we fell back to defaults due to a parse error.
    """
    raw = _parse_toml(path)
    if raw is None:
        return deepcopy(CATEGORIES_TEMPLATE), False   # no tomllib, use defaults

    user_t       = _toml_to_template(raw)
    should_merge = raw.get("foldr", {}).get("merge", True)

    if should_merge:
        merged = deepcopy(CATEGORIES_TEMPLATE)
        for name, data in user_t.items():
            if name in merged:
                merged[name]["ext"] = merged[name]["ext"] | data["ext"]
                if "folder" in data:
                    merged[name]["folder"] = data["folder"]
            else:
                merged[name] = data
        return merged, False
    else:
        return user_t, False


# ── Public API ─────────────────────────────────────────────────────────────────

def load_template(
    config_path: Path | None = None,
) -> tuple[dict, str | None]:
    """
    Return (template_dict, source_label).

    source_label is a human-readable path string for display,
    or None if using built-in defaults.

    This function NEVER crashes on a bad config file — it prints a warning
    and falls back to built-in defaults so FOLDR always keeps working.
    """
    # Explicit --config flag
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                f"  Tip: your auto-generated config is at {default_config_path()}"
            )
        try:
            tmpl, _ = _load_and_merge(config_path)
            return tmpl, str(config_path)
        except RuntimeError as e:
            import sys
            print(str(e), file=sys.stderr)
            return deepcopy(CATEGORIES_TEMPLATE), None

    # Auto-discover
    for candidate in _default_config_paths():
        if candidate.exists():
            try:
                tmpl, _ = _load_and_merge(candidate)
                return tmpl, str(candidate)
            except RuntimeError as e:
                import sys
                print(str(e), file=sys.stderr)
                return deepcopy(CATEGORIES_TEMPLATE), None

    return deepcopy(CATEGORIES_TEMPLATE), None