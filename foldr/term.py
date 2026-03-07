"""
foldr.term
~~~~~~~~~~
Zero-dependency terminal rendering primitives.

Provides:
  - ANSI colour constants
  - Double-buffered, flicker-free Screen renderer
  - Raw keypress reader
  - Box-drawing helpers
  - Category colour / icon palette
"""
from __future__ import annotations
import os, re, sys, select, tty, termios, shutil, time, threading
from typing import Optional

# ── ANSI escape codes ─────────────────────────────────────────────────────────
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"

BLK  = "\033[30m"; RED  = "\033[31m"; GRN  = "\033[32m"; YLW  = "\033[33m"
BLU  = "\033[34m"; MAG  = "\033[35m"; CYN  = "\033[36m"; WHT  = "\033[37m"
BBLK = "\033[90m"; BRED = "\033[91m"; BGRN = "\033[92m"; BYLW = "\033[93m"
BBLU = "\033[94m"; BMAG = "\033[95m"; BCYN = "\033[96m"; BWHT = "\033[97m"

def bg256(n: int) -> str:  return f"\033[48;5;{n}m"
def fg256(n: int) -> str:  return f"\033[38;5;{n}m"
def rgb_bg(r,g,b) -> str:  return f"\033[48;2;{r};{g};{b}m"
def rgb_fg(r,g,b) -> str:  return f"\033[38;2;{r};{g};{b}m"

HIDE_CUR = "\033[?25l"; SHOW_CUR = "\033[?25h"
ALT_ON   = "\033[?1049h"; ALT_OFF = "\033[?1049l"
ERASE_L  = "\033[2K"

def _goto(r: int, c: int) -> str: return f"\033[{r+1};{c+1}H"

# Compound
MUTED = BBLK + DIM
ACCENT = BCYN

# ── Category palette ──────────────────────────────────────────────────────────
_CAT_FG = {
    "Documents": BCYN,   "Text & Data": CYN,   "Images": BGRN,
    "Vector Graphics": GRN, "Videos": BYLW,    "Audio": BMAG,
    "Subtitles": MAG,    "Archives": BRED,     "Disk Images": RED,
    "Code": BBLU,        "Scripts": BLU,       "Notebooks": BBLU,
    "Executables": BRED, "Spreadsheets": BCYN, "Presentations": BCYN,
    "Machine_Learning": BMAG, "Databases": BYLW, "Fonts": BWHT,
    "3D_Models": BWHT,   "GIS": BYLW,          "Ebooks": BMAG,
    "Certificates": BYLW,"Logs": BBLK,         "Misc": BBLK,
}
_CAT_ICON = {
    "Documents":"📄","Text & Data":"📝","Images":"🖼 ","Vector Graphics":"✏ ",
    "Videos":"🎬","Audio":"🎵","Subtitles":"💬","Archives":"📦",
    "Disk Images":"💽","Code":"💻","Scripts":"📜","Notebooks":"📓",
    "Executables":"⚙ ","Spreadsheets":"📊","Presentations":"📽",
    "Machine_Learning":"🧠","Databases":"🗄 ","Fonts":"🔤",
    "3D_Models":"🧊","GIS":"🗺 ","Ebooks":"📚","Certificates":"🔐",
    "Logs":"📋","Misc":"🗃 ",
}
def cat_fg(cat: str) -> str:   return _CAT_FG.get(cat, BWHT)
def cat_icon(cat: str) -> str: return _CAT_ICON.get(cat, "📁")
def fmt_size(n: int) -> str:
    for u in ("B","K","M","G"):
        if n < 1024: return f"{n:.0f}{u}"
        n //= 1024
    return f"{n:.0f}T"

# ── Strip ANSI from string (for width calculation) ────────────────────────────
_ESC_RE = re.compile(r"\033\[[0-9;]*[mABCDHJKfsu]")
def strip(s: str) -> str: return _ESC_RE.sub("", s)
def vlen(s: str) -> int:  return len(strip(s))

def truncate(s: str, w: int) -> str:
    """Truncate to visual width w, preserving ANSI codes."""
    if vlen(s) <= w: return s
    out, vis = [], 0
    for m in re.finditer(r"(\033\[[0-9;]*[mABCDHJKfsu])|(.)", s):
        if m.group(1):
            out.append(m.group(1))
        else:
            if vis >= w - 1: out.append("…"); break
            out.append(m.group(2)); vis += 1
    return "".join(out) + RESET

def pad_to(s: str, w: int) -> str:
    """Right-pad to visual width w."""
    v = vlen(s)
    return s + " " * max(0, w - v)

# ── Terminal size ─────────────────────────────────────────────────────────────
def term_wh() -> tuple[int,int]:
    s = shutil.get_terminal_size((80,24))
    return s.columns, s.lines

def is_tty() -> bool:
    return (hasattr(sys.stdout,"isatty") and sys.stdout.isatty()
            and hasattr(sys.stdin,"isatty") and sys.stdin.isatty()
            and os.environ.get("TERM","dumb") != "dumb")

# ── Double-buffered screen ─────────────────────────────────────────────────────
class Screen:
    """
    Flicker-free, double-buffered terminal renderer.

    Draw to the back-buffer with put()/fill(), then call flush()
    to write ONLY the changed rows to stdout.  No full clears, no flicker.
    """
    def __init__(self):
        w, h = term_wh()
        self.w, self.h = w, h
        self._back  : list[str] = [""] * h
        self._front : list[str] = ["\x00"] * h   # sentinel → force first draw
        self._buf   : list[str] = []

    def resize(self) -> bool:
        w, h = term_wh()
        if w != self.w or h != self.h:
            self.w, self.h = w, h
            self._back  = [""] * h
            self._front = ["\x00"] * h
            return True
        return False

    def fill(self, row: int, text: str) -> None:
        """Replace the entire row string."""
        if 0 <= row < self.h:
            self._back[row] = text

    def clear_back(self) -> None:
        self._back = [""] * self.h

    def flush(self) -> None:
        """Write only changed rows to stdout."""
        out: list[str] = []
        for r in range(self.h):
            b = self._back[r]
            if b != self._front[r]:
                out.append(_goto(r, 0))
                out.append(ERASE_L)
                if b:
                    out.append(b)
                    out.append(RESET)
                self._front[r] = b
        if out:
            sys.stdout.write("".join(out))
            sys.stdout.flush()

    def enter(self) -> None:
        sys.stdout.write(ALT_ON + HIDE_CUR + "\033[2J")
        sys.stdout.flush()

    def exit(self) -> None:
        sys.stdout.write(ALT_OFF + SHOW_CUR)
        sys.stdout.flush()

# ── Raw keypress reader ────────────────────────────────────────────────────────
K_UP="UP"; K_DOWN="DOWN"; K_LEFT="LEFT"; K_RIGHT="RIGHT"
K_ENTER="ENTER"; K_ESC="ESC"; K_PGUP="PGUP"; K_PGDN="PGDN"
K_HOME="HOME"; K_END="END"; K_TAB="TAB"; K_BS="BS"
K_CC="CTRL_C"; K_CD="CTRL_D"

_SEQ = {
    b"[A":K_UP,   b"[B":K_DOWN, b"[C":K_RIGHT,b"[D":K_LEFT,
    b"[H":K_HOME, b"[F":K_END,  b"[5~":K_PGUP,b"[6~":K_PGDN,
    b"OA":K_UP,   b"OB":K_DOWN, b"OC":K_RIGHT,b"OD":K_LEFT,
}

def read_key() -> str:
    fd  = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            rest = b""
            while select.select([fd],[],[],0.05)[0]:
                rest += os.read(fd, 8)
            return _SEQ.get(rest, K_ESC) if rest else K_ESC
        if ch in (b"\r", b"\n"):  return K_ENTER
        if ch == b"\t":            return K_TAB
        if ch == b"\x7f":          return K_BS
        if ch == b"\x03":          return K_CC
        if ch == b"\x04":          return K_CD
        return ch.decode("utf-8", errors="replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

# ── Box drawing helpers ────────────────────────────────────────────────────────
def box_top(w: int, title: str = "", col: str = MUTED, tcol: str = "") -> str:
    inner = w - 2
    if title:
        t    = f" {title} "
        tl   = vlen(t)
        pad  = max(1, (inner - tl) // 2)
        rest = max(1, inner - tl - pad)
        return col + "╔" + "═"*pad + (tcol or BCYN+BOLD) + t + RESET + col + "═"*rest + "╗" + RESET
    return col + "╔" + "═"*inner + "╗" + RESET

def box_mid(w: int, col: str = MUTED) -> str:
    return col + "║" + " "*(w-2) + "║" + RESET

def box_sep(w: int, col: str = MUTED) -> str:
    return col + "╠" + "═"*(w-2) + "╣" + RESET

def box_bot(w: int, col: str = MUTED) -> str:
    return col + "╚" + "═"*(w-2) + "╝" + RESET

def box_row(content: str, w: int, col: str = MUTED) -> str:
    """Content row inside a box, padded to fit."""
    inner = w - 4   # 2 border + 2 padding
    padded = pad_to(truncate(content, inner), inner)
    return col + "║ " + RESET + padded + col + " ║" + RESET

# ── Spinner frames ─────────────────────────────────────────────────────────────
SPINNER = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

# ── Progress bar ───────────────────────────────────────────────────────────────
def pbar(pct: float, width: int = 28) -> str:
    fill  = max(0, min(width, int(pct * width)))
    empty = width - fill
    return BGRN + "█"*fill + MUTED + "░"*empty + RESET
