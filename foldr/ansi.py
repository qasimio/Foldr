"""
foldr.ansi
~~~~~~~~~~
Terminal ANSI primitives — colours, cursor, drawing.
Used by both the TUI engine and the plain-text fallback.
"""
from __future__ import annotations
import os, sys, shutil

# ── Colour constants ─────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
ITALIC  = "\033[3m"
UNDER   = "\033[4m"
BLINK   = "\033[5m"
REV     = "\033[7m"

# Foreground
BLACK   = "\033[30m"; RED     = "\033[31m"; GREEN   = "\033[32m"
YELLOW  = "\033[33m"; BLUE    = "\033[34m"; MAGENTA = "\033[35m"
CYAN    = "\033[36m"; WHITE   = "\033[37m"
BBLACK  = "\033[90m"; BRED    = "\033[91m"; BGREEN  = "\033[92m"
BYELLOW = "\033[93m"; BBLUE   = "\033[94m"; BMAGENTA= "\033[95m"
BCYAN   = "\033[96m"; BWHITE  = "\033[97m"

# Background
BG_BLACK  = "\033[40m";  BG_RED    = "\033[41m";  BG_GREEN  = "\033[42m"
BG_YELLOW = "\033[43m";  BG_BLUE   = "\033[44m";  BG_MAGENTA= "\033[45m"
BG_CYAN   = "\033[46m";  BG_WHITE  = "\033[47m"
BG_DARK   = "\033[48;5;235m"; BG_DARK2 = "\033[48;5;237m"
BG_HEADER = "\033[48;5;17m";  BG_SEL   = "\033[48;5;24m"

def rgb(r: int, g: int, b: int, bg: bool = False) -> str:
    return f"\033[{'48' if bg else '38'};2;{r};{g};{b}m"

def c256(n: int, bg: bool = False) -> str:
    return f"\033[{'48' if bg else '38'};5;{n}m"

# Cursor
HIDE_CURSOR = "\033[?25l"; SHOW_CURSOR = "\033[?25h"
CLEAR       = "\033[2J\033[H"
CLEAR_LINE  = "\033[2K"
ALT_ENTER   = "\033[?1049h"; ALT_EXIT = "\033[?1049l"

def goto(row: int, col: int) -> str:
    return f"\033[{row+1};{col+1}H"

def up(n: int = 1) -> str:   return f"\033[{n}A"
def down(n: int = 1) -> str: return f"\033[{n}B"

# ── Category palette ─────────────────────────────────────────────────────────
CAT_COLOURS = {
    "Documents":    BCYAN,
    "Text & Data":  CYAN,
    "Images":       BGREEN,
    "Vector Graphics": GREEN,
    "Videos":       BYELLOW,
    "Audio":        BMAGENTA,
    "Subtitles":    MAGENTA,
    "Archives":     BRED,
    "Disk Images":  RED,
    "Code":         BBLUE,
    "Scripts":      BLUE,
    "Notebooks":    BBLUE,
    "Executables":  BRED,
    "Spreadsheets": BCYAN,
    "Presentations":BCYAN,
    "Fonts":        BWHITE,
    "3D_Models":    BWHITE,
    "Machine_Learning": BMAGENTA,
    "Databases":    BYELLOW,
    "Misc":         BBLACK,
}
CAT_ICONS = {
    "Documents": "📄", "Text & Data": "📝", "Images": "🖼 ",
    "Videos": "🎬", "Audio": "🎵", "Archives": "📦",
    "Code": "💻", "Scripts": "📜", "Notebooks": "📓",
    "Executables": "⚙ ", "Spreadsheets": "📊", "Presentations": "📽 ",
    "Fonts": "🔤", "3D_Models": "🧊", "Machine_Learning": "🧠",
    "Databases": "🗄 ", "GIS": "🗺 ", "Ebooks": "📚", "Misc": "🗃 ",
    "Vector Graphics": "✏ ", "Subtitles": "💬", "Disk Images": "💽",
}
def cat_col(cat: str) -> str:
    return CAT_COLOURS.get(cat, BWHITE)
def cat_icon(cat: str) -> str:
    return CAT_ICONS.get(cat, "📁")

# ── Sizing ───────────────────────────────────────────────────────────────────
def term_size() -> tuple[int, int]:
    s = shutil.get_terminal_size((80, 24))
    return s.lines, s.columns

def supports_ansi() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and os.name != "nt"

# ── Rendering helpers ────────────────────────────────────────────────────────
def pad(s: str, width: int, align: str = "left") -> str:
    """Pad/truncate to exact visual width (ignores escape codes)."""
    vis = strip_ansi(s)
    vlen = len(vis)
    if vlen >= width:
        return s[:width] if not s.startswith("\033") else _trunc_ansi(s, width)
    pad_str = " " * (width - vlen)
    return (pad_str + s + pad_str[:0]) if align == "right" else (s + pad_str)

def strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*[mABCDHJKfsu]", "", s)

def _trunc_ansi(s: str, w: int) -> str:
    import re
    out, vis = [], 0
    for m in re.finditer(r"(\033\[[0-9;]*[mABCDHJKfsu])|(.)", s):
        if m.group(1):
            out.append(m.group(1))
        else:
            if vis >= w:
                break
            out.append(m.group(2))
            vis += 1
    out.append(RESET)
    return "".join(out)

def fmt_size(size: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size //= 1024
    return f"{size:.0f}T"


# Compound styles (frequently used)
MUTED = BBLACK + DIM