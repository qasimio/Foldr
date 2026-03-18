"""
foldr.config_loader
~~~~~~~~~~~~~~~~~~~~
Loads and merges category configuration for FOLDR v4.

Config search order (highest → lowest priority)
------------------------------------------------
1. --config <path>              explicit CLI flag
2. ~/.foldr/config.toml         primary (same dir as history)
3. ~/.config/foldr/config.toml  XDG fallback (Linux)
4. Built-in CATEGORIES_TEMPLATE
"""
from __future__ import annotations
import platform
from pathlib import Path
from copy import deepcopy

from foldr.config import CATEGORIES_TEMPLATE

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore


def _default_config_paths() -> list[Path]:
    """Candidate paths in priority order."""
    paths = [Path.home() / ".foldr" / "config.toml"]
    if platform.system() != "Windows":
        paths.append(Path.home() / ".config" / "foldr" / "config.toml")
    return paths


def _parse_toml(path: Path) -> dict:
    if tomllib is None:
        raise RuntimeError("TOML config requires Python 3.11+ or: pip install tomli")
    with open(path, "rb") as f:
        return tomllib.load(f)


def _toml_to_template(data: dict) -> dict:
    template: dict = {}
    for section, value in data.items():
        if section == "foldr" or not isinstance(value, dict):
            continue
        exts   = value.get("extensions") or value.get("ext") or []
        folder = value.get("folder", section)
        template[section] = {"folder": folder, "ext": set(e.lower() for e in exts)}
    return template


def _load_and_merge(path: Path) -> dict:
    raw          = _parse_toml(path)
    user_t       = _toml_to_template(raw)
    should_merge = raw.get("foldr", {}).get("merge", True)
    if should_merge:
        merged = deepcopy(CATEGORIES_TEMPLATE)
        for name, data in user_t.items():
            if name in merged:
                merged[name]["ext"] = merged[name]["ext"] | data["ext"]
            else:
                merged[name] = data
        return merged
    return user_t


def load_template(config_path: Path | None = None) -> tuple[dict, str | None]:
    """Return (template_dict, source_label_or_None)."""
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config not found: {config_path}\n"
                f"  Tip: place your config at {Path.home() / '.foldr' / 'config.toml'}"
            )
        return _load_and_merge(config_path), str(config_path)

    for candidate in _default_config_paths():
        if candidate.exists():
            return _load_and_merge(candidate), str(candidate)

    return deepcopy(CATEGORIES_TEMPLATE), None