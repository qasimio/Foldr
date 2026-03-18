"""
foldr.term
~~~~~~~~~~
Cross-platform terminal colour and string helpers.

No TUI. No raw key reading. No alternate screen. No curses.
Just ANSI colour constants, string helpers, and width detection.

Cross-OS colour support
------------------------
Windows 10+  : enabled via ctypes (SetConsoleMode) on import.
               colorama.init() is called as a safety net if installed.
Linux / macOS: ANSI works natively — nothing special needed.

VSCode / Pylance note
---------------------
All platform-specific stdlib modules (ctypes.windll, etc.) are accessed
with try/except at runtime, NOT as top-level conditional imports.
This means no "module not found" squiggles on any platform.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import platform

_SYSTEM = platform.system()   # "Windows" | "Darwin" | "Linux" | ...


# ── Windows ANSI enable (runtime, not import-time) ────────────────────────────
def _enable_win_ansi() -> None:
    """
    Enable VT100 / ANSI processing on Windows 10 build 14931+.
    Silently does nothing on non-Windows or older Windows.
    Uses try/except so it never crashes and never causes import errors.
    """
    if _SYSTEM != "Windows":
        return
    try:
        import ctypes
        import ctypes.wintypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        ENABLE_VT       = 0x0004
        ENABLE_PROC_OUT = 0x0001
        for hid in (-10, -11):   # stdin=-10, stdout=-11
            h = k32.GetStdHandle(hid)
            mode = ctypes.wintypes.DWORD()
            if k32.GetConsoleMode(h, ctypes.byref(mode)):
                k32.SetConsoleMode(h, mode.value | ENABLE_VT | ENABLE_PROC_OUT)
        k32.SetConsoleOutputCP(65001)   # UTF-8
        k32.SetConsoleCP(65001)
    except Exception:
        pass

    # colorama as a fallback for terminals that don't support ctypes approach
    try:
        import colorama          # type: ignore[import]
        colorama.init(strip=False)
    except ImportError:
        pass


_enable_win_ansi()


# ── ANSI escape codes ──────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
ITAL  = "\033[3m"
UNDER = "\033[4m"

BLK  = "\033[30m";  RED  = "\033[31m";  GRN  = "\033[32m";  YLW  = "\033[33m"
BLU  = "\033[34m";  MAG  = "\033[35m";  CYN  = "\033[36m";  WHT  = "\033[37m"
BBLK = "\033[90m";  BRED = "\033[91m";  BGRN = "\033[92m";  BYLW = "\033[93m"
BBLU = "\033[94m";  BMAG = "\033[95m";  BCYN = "\033[96m";  BWHT = "\033[97m"


def bg256(n: int) -> str:
    return f"\033[48;5;{n}m"

def fg256(n: int) -> str:
    return f"\033[38;5;{n}m"


# ── Colour palette ─────────────────────────────────────────────────────────────
FG_BRIGHT = BWHT
FG_DIM    = fg256(245)
FG_MUTED  = fg256(240)

ACCENT    = fg256(75)    # steel blue
ACCENT2   = fg256(110)

COL_OK    = fg256(71)    # muted green
COL_WARN  = fg256(178)   # amber
COL_ERR   = fg256(167)   # muted red
COL_BORD  = fg256(240)   # subtle border


# ── Category colours and icons ─────────────────────────────────────────────────
_CAT_FG: dict[str, str] = {
    "Documents":        fg256(75),
    "Text & Data":      fg256(67),
    "Images":           fg256(71),
    "Vector Graphics":  fg256(65),
    "Videos":           fg256(172),
    "Audio":            fg256(133),
    "Subtitles":        fg256(139),
    "Archives":         fg256(167),
    "Disk Images":      fg256(124),
    "Executables":      fg256(160),
    "Code":             fg256(74),
    "Scripts":          fg256(68),
    "Notebooks":        fg256(111),
    "Machine_Learning": fg256(133),
    "Databases":        fg256(178),
    "Spreadsheets":     fg256(72),
    "Presentations":    fg256(109),
    "Fonts":            fg256(245),
    "3D_Models":        fg256(250),
    "Ebooks":           fg256(140),
    "Certificates":     fg256(178),
    "Logs":             fg256(241),
    "Misc":             fg256(238),
    "duplicate":        fg256(167),
}

_CAT_ICON: dict[str, str] = {
    "Documents":        "doc",
    "Text & Data":      "txt",
    "Images":           "img",
    "Vector Graphics":  "vec",
    "Videos":           "vid",
    "Audio":            "aud",
    "Subtitles":        "sub",
    "Archives":         "arc",
    "Disk Images":      "dsk",
    "Executables":      "exe",
    "Code":             "cod",
    "Scripts":          "sh ",
    "Notebooks":        "nb ",
    "Machine_Learning": "ml ",
    "Databases":        "db ",
    "Spreadsheets":     "xls",
    "Presentations":    "ppt",
    "Fonts":            "fnt",
    "3D_Models":        "3d ",
    "Ebooks":           "ebo",
    "Certificates":     "crt",
    "Logs":             "log",
    "Misc":             "...",
    "duplicate":        "dup",
}


def cat_fg(cat: str) -> str:
    """Return ANSI colour code for a category name."""
    return _CAT_FG.get(cat, FG_DIM)


def cat_icon(cat: str) -> str:
    """Return a short 3-char icon for a category name."""
    return _CAT_ICON.get(cat, "   ")


def op_icon(t: str) -> str:
    """Return a short icon for an operation type."""
    return {"organize": "->", "dedup": "xx", "undo": "<-"}.get(t, " ?")


def fmt_size(n: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n //= 1024
    return f"{n:.0f}T"


# ── String utilities ───────────────────────────────────────────────────────────
_ESC_RE = re.compile(r"\033\[[0-9;?]*[mABCDHJKfsuhl]")


def strip(s: str) -> str:
    """Remove all ANSI escape codes from a string."""
    return _ESC_RE.sub("", s)


def vlen(s: str) -> int:
    """Visual length of a string (ANSI codes have zero width)."""
    return len(strip(s))


def pad_to(s: str, w: int, fill: str = " ") -> str:
    """Right-pad string to visual width w."""
    return s + fill * max(0, w - vlen(s))


def ljust(s: str, w: int) -> str:
    """Plain left-justify (no ANSI codes in s)."""
    return s + " " * max(0, w - len(s))


def truncate(s: str, w: int) -> str:
    """Truncate a plain string (no ANSI) to at most w chars, adding ~ if cut."""
    if len(s) <= w:
        return s
    return s[: w - 1] + "~"


# ── Terminal detection ─────────────────────────────────────────────────────────
def term_wh() -> tuple[int, int]:
    """Return (columns, lines) of the current terminal."""
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


def is_tty() -> bool:
    """
    True when stdout is a real interactive terminal — not a pipe, redirect,
    or CI/CD environment.
    """
    if not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        return False
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return True


def supports_colour() -> bool:
    """True when the terminal can render ANSI colour codes."""
    if not sys.stdout.isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if _SYSTEM == "Windows":
        # Windows 10 build 14931+ supports VT; we attempted to enable it above
        try:
            v = sys.getwindowsversion()  # type: ignore[attr-defined]
            return (v.major, v.minor, v.build) >= (10, 0, 14931)
        except AttributeError:
            return False
    return True


# ── Progress bar ───────────────────────────────────────────────────────────────
SPINNER = ["|", "/", "-", "\\"]    # ASCII — works in every terminal on every OS


def pbar(pct: float, width: int = 30, col: str = "") -> str:
    """Render a simple ASCII progress bar."""
    fill  = max(0, min(width, int(pct * width)))
    empty = width - fill
    c     = col or COL_OK
    return c + "#" * fill + FG_MUTED + "-" * empty + RESET