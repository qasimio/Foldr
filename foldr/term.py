"""
foldr.term
~~~~~~~~~~
Cross-platform colour and string helpers. Zero dependencies.

Windows: ANSI enabled via ctypes at import time (Win10+).
         colorama used as safety net if installed.
Linux/macOS: ANSI works natively.

Pylance note: all Windows-only ctypes.windll access is inside try/except
with no top-level conditional imports, so Pylance on Linux never complains.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import platform

_SYSTEM = platform.system()


def _enable_win_ansi() -> None:
    """Enable VT100 on Windows 10+ via ctypes. Silent on failure."""
    if _SYSTEM != "Windows":
        return
    try:
        import ctypes
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return
        k32 = windll.kernel32
        ENABLE_VT       = 0x0004
        ENABLE_PROC_OUT = 0x0001
        for hid in (-10, -11):
            h = k32.GetStdHandle(hid)
            import ctypes.wintypes
            mode = ctypes.wintypes.DWORD()
            if k32.GetConsoleMode(h, ctypes.byref(mode)):
                k32.SetConsoleMode(h, mode.value | ENABLE_VT | ENABLE_PROC_OUT)
        k32.SetConsoleOutputCP(65001)
        k32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        import colorama          # type: ignore[import]
        colorama.init(strip=False)
    except ImportError:
        pass


_enable_win_ansi()

# ── ANSI codes ─────────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

BWHT = "\033[97m"
BBLK = "\033[90m"

def fg256(n: int) -> str: return f"\033[38;5;{n}m"
def bg256(n: int) -> str: return f"\033[48;5;{n}m"

FG_BRIGHT = BWHT
FG_DIM    = fg256(245)
FG_MUTED  = fg256(240)

ACCENT    = fg256(75)    # steel blue
ACCENT2   = fg256(110)

COL_OK    = fg256(71)
COL_WARN  = fg256(178)
COL_ERR   = fg256(167)
COL_BORD  = fg256(240)

_CAT_FG: dict[str, str] = {
    "Documents":        fg256(75),   "Text & Data":      fg256(67),
    "Images":           fg256(71),   "Vector Graphics":  fg256(65),
    "Videos":           fg256(172),  "Audio":            fg256(133),
    "Subtitles":        fg256(139),  "Archives":         fg256(167),
    "Disk Images":      fg256(124),  "Executables":      fg256(160),
    "Code":             fg256(74),   "Scripts":          fg256(68),
    "Notebooks":        fg256(111),  "Machine_Learning": fg256(133),
    "Databases":        fg256(178),  "Spreadsheets":     fg256(72),
    "Presentations":    fg256(109),  "Fonts":            fg256(245),
    "3D_Models":        fg256(250),  "Ebooks":           fg256(140),
    "Certificates":     fg256(178),  "Logs":             fg256(241),
    "Misc":             fg256(238),  "duplicate":        fg256(167),
}

_CAT_ICON: dict[str, str] = {
    "Documents": "doc", "Text & Data": "txt", "Images": "img",
    "Vector Graphics": "vec", "Videos": "vid", "Audio": "aud",
    "Subtitles": "sub", "Archives": "arc", "Disk Images": "dsk",
    "Executables": "exe", "Code": "cod", "Scripts": "sh ",
    "Notebooks": "nb ", "Machine_Learning": "ml ", "Databases": "db ",
    "Spreadsheets": "xls", "Presentations": "ppt", "Fonts": "fnt",
    "3D_Models": "3d ", "Ebooks": "ebo", "Certificates": "crt",
    "Logs": "log", "Misc": "...", "duplicate": "dup",
}

def cat_fg(cat: str) -> str:   return _CAT_FG.get(cat, FG_DIM)
def cat_icon(cat: str) -> str: return _CAT_ICON.get(cat, "   ")
def op_icon(t: str) -> str:    return {"organize": "->", "dedup": "xx", "undo": "<-"}.get(t, " ?")

def fmt_size(n: int) -> str:
    for u in ("B", "K", "M", "G"):
        if n < 1024: return f"{n:.0f}{u}"
        n //= 1024
    return f"{n:.0f}T"

_ESC_RE = re.compile(r"\033\[[0-9;?]*[mABCDHJKfsuhl]")

def strip(s: str) -> str:  return _ESC_RE.sub("", s)
def vlen(s: str) -> int:   return len(strip(s))

def pad_to(s: str, w: int, fill: str = " ") -> str:
    return s + fill * max(0, w - vlen(s))

def ljust(s: str, w: int) -> str:
    return s + " " * max(0, w - len(s))

def truncate(s: str, w: int) -> str:
    return s if len(s) <= w else s[:w - 1] + "~"

def term_wh() -> tuple[int, int]:
    s = shutil.get_terminal_size((80, 24))
    return s.columns, s.lines

def is_tty() -> bool:
    return (
        hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        and hasattr(sys.stdin,  "isatty") and sys.stdin.isatty()
        and not os.environ.get("NO_COLOR")
        and os.environ.get("TERM", "") != "dumb"
    )

SPINNER = ["|", "/", "-", "\\"]

def pbar(pct: float, width: int = 30, col: str = "") -> str:
    fill  = max(0, min(width, int(pct * width)))
    empty = width - fill
    c = col or COL_OK
    return c + "#" * fill + FG_MUTED + "-" * empty + RESET