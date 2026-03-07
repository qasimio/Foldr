"""
config_loader.py — FOLDR v2 custom configuration system

Precedence (highest to lowest):
  1. --config <path>  (CLI-supplied per-run config)
  2. ~/.config/foldr/config.toml  (user global config, Linux/macOS)
     %USERPROFILE%\.foldr\config.toml  (Windows)
  3. Built-in CATEGORIES_TEMPLATE

A config file uses TOML:

  [Images]
  extensions = [".png", ".jpg", ".jpeg"]
  folder = "Images"       # optional, defaults to the section name

  [Datasets]
  extensions = [".csv", ".parquet", ".feather"]
  folder = "Datasets"

  [merge]
  with_builtin = true     # default: false — set true to ADD to built-ins
                          # rather than replacing them entirely
"""

from __future__ import annotations

import sys
from pathlib import Path


# ─── Global config location ───────────────────────────────────────────────────

def global_config_path() -> Path:
    if sys.platform == "win32":
        base = Path.home() / ".foldr"
    else:
        base = Path.home() / ".config" / "foldr"
    return base / "config.toml"


# ─── TOML loader (stdlib tomllib ≥3.11, else tomli fallback) ─────────────────

def _load_toml(path: Path) -> dict:
    try:
        import tomllib                          # Python 3.11+
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        pass
    try:
        import tomli                            # pip install tomli
        with open(path, "rb") as fh:
            return tomli.load(fh)
    except ImportError:
        pass
    # Last-resort pure-python minimal TOML for simple key=value / sections
    return _minimal_toml_parse(path.read_text(encoding="utf-8"))


def _minimal_toml_parse(text: str) -> dict:
    """
    Tiny TOML parser that handles the foldr config subset:
      [SectionName]
      extensions = [".a", ".b"]
      folder = "Folder_Name"
      [merge]
      with_builtin = true
    """
    result: dict = {}
    current_section: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            result.setdefault(current_section, {})
            continue
        if "=" in line and current_section is not None:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # list
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                items = [
                    v.strip().strip('"').strip("'")
                    for v in inner.split(",")
                    if v.strip()
                ]
                result[current_section][key] = items
            # bool
            elif val.lower() in ("true", "false"):
                result[current_section][key] = val.lower() == "true"
            # string
            else:
                result[current_section][key] = val.strip('"').strip("'")

    return result


# ─── Config parsing ───────────────────────────────────────────────────────────

def parse_custom_config(path: Path) -> tuple[dict | None, bool]:
    """
    Load and parse a TOML config file.

    Returns (custom_config_dict, merge_with_builtin).

    custom_config_dict maps category name → {"folder": str, "ext": set[str]}.
    merge_with_builtin=True means the custom config is layered ON TOP of the
    built-in template rather than replacing it.
    """
    if not path.exists():
        return None, False

    raw = _load_toml(path)

    merge = False
    if "merge" in raw:
        merge = bool(raw["merge"].get("with_builtin", False))

    custom: dict = {}
    for section, values in raw.items():
        if section == "merge":
            continue
        if "extensions" not in values:
            continue
        folder = values.get("folder", section)
        exts = {
            e if e.startswith(".") else f".{e}"
            for e in values["extensions"]
        }
        custom[section] = {"folder": folder, "ext": exts}

    return (custom if custom else None), merge


def load_effective_config(cli_config_path: Path | None) -> dict | None:
    """
    Resolve the effective custom config dict.

    1. Try CLI-supplied path.
    2. Fall back to global config path.
    3. If neither exists, return None (use built-in only).

    When merge=true, returns a dict that will be passed as custom_config to
    build_category_map, which merges it on top of the built-in template.
    """
    path = cli_config_path or global_config_path()

    if not path.exists():
        return None

    custom, merge = parse_custom_config(path)

    if not custom:
        return None

    if merge:
        # Pass as-is; build_category_map will layer it on top of CATEGORIES_TEMPLATE
        return custom
    else:
        # Replace entirely: build_category_map receives this as the full template.
        # We achieve this by returning it — build_category_map already handles
        # custom_config overriding CATEGORIES_TEMPLATE on name collision.
        # For a full replace we need to signal differently; we wrap in a sentinel.
        return {"__replace__": True, **custom}


def resolve_custom_config(cli_config_path: Path | None) -> dict | None:
    """
    Public helper. Returns the dict to pass as `custom_config` to
    `organize_folder`, or None to use built-ins only.
    """
    effective = load_effective_config(cli_config_path)
    if effective is None:
        return None

    # strip the internal __replace__ sentinel before passing to organizer
    if "__replace__" in effective:
        clean = {k: v for k, v in effective.items() if k != "__replace__"}
        return clean or None

    return effective