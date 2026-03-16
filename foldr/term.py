"""
foldr.term
~~~~~~~~~~
Zero-dependency cross-platform terminal rendering.

Platform support
----------------
  Linux   — ANSI/VT100, tty.setraw, select.select
  macOS   — same as Linux
  Windows — Win10+ Virtual Terminal via ctypes; msvcrt for raw key input
             Falls back to plain text (no TUI) on Windows < 10 build 14931

Key design decision: ALL platform-specific code is isolated in three
functions: is_tty(), read_key(), and _enable_vt_windows(). Everything
else (ANSI codes, box drawing, Screen, etc.) is identical across OS.
"""
from __future__ import annotations
import os, re, sys, shutil, time, platform
from typing import Optional

_IS_WIN = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"

# ── Windows VT100 enable ───────────────────────────────────────────────────────
_WIN_VT_ENABLED = False

def _enable_vt_windows() -> bool:
    """
    Enable Virtual Terminal Processing on Windows 10+.
    Required for ANSI escape codes and alternate screen to work.
    Returns True if successfully enabled.
    """
    global _WIN_VT_ENABLED
    if _WIN_VT_ENABLED:
        return True
    if not _IS_WIN:
        _WIN_VT_ENABLED = True
        return True
    try:
        import ctypes, ctypes.wintypes
        kernel32 = ctypes.windll.kernel32
        # Enable VT processing on stdout (handle -11) and stderr (-12)
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_PROCESSED_OUTPUT            = 0x0001
        for handle_id in (-10, -11):  # stdin, stdout
            h = kernel32.GetStdHandle(handle_id)
            mode = ctypes.wintypes.DWORD()
            if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                kernel32.SetConsoleMode(
                    h,
                    mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT,
                )
        # Also set UTF-8 output codepage
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        _WIN_VT_ENABLED = True
        return True
    except Exception:
        return False

# Enable immediately on import for Windows
if _IS_WIN:
    _enable_vt_windows()

# ── ANSI codes ─────────────────────────────────────────────────────────────────
RESET="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"; ITAL="\033[3m"; UNDER="\033[4m"

BLK="\033[30m"; RED="\033[31m"; GRN="\033[32m"; YLW="\033[33m"
BLU="\033[34m"; MAG="\033[35m"; CYN="\033[36m"; WHT="\033[37m"
BBLK="\033[90m"; BRED="\033[91m"; BGRN="\033[92m"; BYLW="\033[93m"
BBLU="\033[94m"; BMAG="\033[95m"; BCYN="\033[96m"; BWHT="\033[97m"

def bg256(n:int)->str: return f"\033[48;5;{n}m"
def fg256(n:int)->str: return f"\033[38;5;{n}m"
def rgb_bg(r,g,b)->str: return f"\033[48;2;{r};{g};{b}m"
def rgb_fg(r,g,b)->str: return f"\033[38;2;{r};{g};{b}m"

HIDE_CUR="\033[?25l"; SHOW_CUR="\033[?25h"
ALT_ON="\033[?1049h"; ALT_OFF="\033[?1049l"
ERASE_L="\033[2K"

def _goto(r:int,c:int)->str: return f"\033[{r+1};{c+1}H"

# ── Neutral palette ─────────────────────────────────────────────────────────────
BG_BASE   = bg256(233)
BG_PANEL  = bg256(234)
BG_HEADER = rgb_bg(12,12,12)
BG_SEL    = bg256(236)
BG_MODAL  = bg256(235)

FG_BRIGHT = BWHT
FG_DIM    = fg256(245)
FG_MUTED  = fg256(239)

ACCENT    = fg256(75)     # steel blue
ACCENT2   = fg256(110)
ACCENT_BG = bg256(17)

COL_OK    = fg256(71)     # muted green
COL_WARN  = fg256(178)    # amber
COL_ERR   = fg256(167)    # muted red
COL_BORD  = fg256(238)    # subtle border
COL_BORD2 = fg256(244)    # active border

MUTED = FG_MUTED
BCYN  = ACCENT

# ── Category colours / icons ───────────────────────────────────────────────────
_CAT_FG: dict[str,str] = {
    "Documents":        fg256(75),  "Text & Data":      fg256(67),
    "Images":           fg256(71),  "Vector Graphics":  fg256(65),
    "Videos":           fg256(172), "Audio":            fg256(133),
    "Subtitles":        fg256(139), "Archives":         fg256(167),
    "Disk Images":      fg256(124), "Executables":      fg256(160),
    "Code":             fg256(74),  "Scripts":          fg256(68),
    "Notebooks":        fg256(111), "Machine_Learning": fg256(133),
    "Databases":        fg256(178), "Spreadsheets":     fg256(72),
    "Presentations":    fg256(109), "Fonts":            fg256(245),
    "3D_Models":        fg256(250), "Ebooks":           fg256(140),
    "Certificates":     fg256(178), "Logs":             fg256(241),
    "Misc":             fg256(238), "duplicate":        fg256(167),
}
_CAT_ICON: dict[str,str] = {
    "Documents":"doc","Text & Data":"txt","Images":"img","Vector Graphics":"vec",
    "Videos":"vid","Audio":"aud","Subtitles":"sub","Archives":"arc",
    "Disk Images":"dsk","Executables":"exe","Code":"cod","Scripts":"sh",
    "Notebooks":"nb","Machine_Learning":"ml","Databases":"db","Spreadsheets":"xls",
    "Presentations":"ppt","Fonts":"fnt","3D_Models":"3d","Ebooks":"ebo",
    "Certificates":"crt","Logs":"log","Misc":"misc","duplicate":"dup",
}

def cat_fg(cat:str)->str:   return _CAT_FG.get(cat, FG_DIM)
def cat_icon(cat:str)->str: return _CAT_ICON.get(cat, "·")
def op_icon(t:str)->str:    return {"organize":"->","dedup":"x","undo":"<-"}.get(t,"·")

def fmt_size(n:int)->str:
    for u in ("B","K","M","G"):
        if n<1024: return f"{n:.0f}{u}"
        n//=1024
    return f"{n:.0f}T"

# ── String / display utilities ─────────────────────────────────────────────────
_ESC_RE = re.compile(r"\033\[[0-9;?]*[mABCDHJKfsuhl]")

def strip(s:str)->str:  return _ESC_RE.sub("", s)
def vlen(s:str)->int:   return len(strip(s))

def truncate(s:str, w:int)->str:
    if vlen(s)<=w: return s
    out, vis = [], 0
    for m in re.finditer(r"(\033\[[0-9;?]*[mABCDHJKfsuhl])|(.)", s):
        if m.group(1):
            out.append(m.group(1))
        else:
            if vis >= w-1:
                out.append("~"); break
            out.append(m.group(2)); vis+=1
    return "".join(out)+RESET

def pad_to(s:str, w:int, fill:str=" ")->str:
    return s + fill * max(0, w - vlen(s))

def centre(s:str, w:int, fill:str=" ")->str:
    v=vlen(s); pad=max(0,w-v)
    return fill*(pad//2)+s+fill*(pad-pad//2)

# ── Terminal detection ─────────────────────────────────────────────────────────
def term_wh()->tuple[int,int]:
    s = shutil.get_terminal_size((80, 24))
    return s.columns, s.lines

def is_tty()->bool:
    """
    True only in an interactive terminal with colour support.
    Windows: also requires VT mode to be successfully enabled.
    """
    if not (hasattr(sys.stdout,"isatty") and sys.stdout.isatty()): return False
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):  return False
    if os.environ.get("NO_COLOR"):     return False
    if os.environ.get("TERM","")=="dumb": return False
    if _IS_WIN:
        return _WIN_VT_ENABLED
    return True

# ── Double-buffered Screen ─────────────────────────────────────────────────────
class Screen:
    """
    Flicker-free double-buffered renderer.
    Identical across all platforms — ANSI codes work everywhere
    once VT processing is enabled (handled in term init above).
    """
    def __init__(self):
        w,h = term_wh()
        self.w=w; self.h=h
        self._back  = [""]*h
        self._front = ["\x00"]*h

    def resize(self)->bool:
        w,h = term_wh()
        if w!=self.w or h!=self.h:
            self.w,self.h=w,h
            self._back=[""]*h; self._front=["\x00"]*h
            return True
        return False

    def fill(self, row:int, text:str)->None:
        if 0<=row<self.h: self._back[row]=text

    def clear_back(self)->None:
        self._back=[""]*self.h

    def flush(self)->None:
        out=[]
        for r in range(self.h):
            b=self._back[r]
            if b!=self._front[r]:
                out.append(_goto(r,0)); out.append(ERASE_L)
                if b: out.append(b); out.append(RESET)
                self._front[r]=b
        if out:
            sys.stdout.write("".join(out)); sys.stdout.flush()

    def enter(self)->None:
        sys.stdout.write(ALT_ON+HIDE_CUR+"\033[2J"); sys.stdout.flush()

    def exit(self)->None:
        sys.stdout.write(ALT_OFF+SHOW_CUR+RESET); sys.stdout.flush()


# ── Key names ──────────────────────────────────────────────────────────────────
K_UP="UP"; K_DOWN="DOWN"; K_LEFT="LEFT"; K_RIGHT="RIGHT"
K_ENTER="ENTER"; K_ESC="ESC"; K_PGUP="PGUP"; K_PGDN="PGDN"
K_HOME="HOME"; K_END="END"; K_TAB="TAB"; K_BS="BS"
K_CC="CTRL_C"; K_CD="CTRL_D"

# ── Platform-specific raw key reader ──────────────────────────────────────────
if _IS_WIN:
    # ── Windows: msvcrt ───────────────────────────────────────────────────────
    import msvcrt, threading as _threading

    # Windows VK → key name mapping
    _WIN_VK: dict[int,str] = {
        0x48: K_UP,   0x50: K_DOWN, 0x4B: K_LEFT,  0x4D: K_RIGHT,
        0x49: K_PGUP, 0x51: K_PGDN, 0x47: K_HOME,  0x4F: K_END,
    }

    def read_key(timeout:float=5.0)->str:
        """
        Windows raw keypress reader using msvcrt.
        Polls at 50ms intervals up to timeout seconds.
        Returns "" on timeout (not ESC, so loops don't exit prematurely).
        """
        elapsed = 0.0
        interval = 0.05
        while elapsed < timeout:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                # Special keys are preceded by \x00 or \xe0
                if ch in ("\x00", "\xe0"):
                    ch2 = msvcrt.getwch()
                    vk = ord(ch2)
                    return _WIN_VK.get(vk, "")
                oc = ord(ch)
                if oc == 13:  return K_ENTER  # Enter
                if oc == 27:  return K_ESC    # Esc
                if oc == 9:   return K_TAB    # Tab
                if oc == 8:   return K_BS     # Backspace
                if oc == 3:   return K_CC     # Ctrl+C
                if oc == 4:   return K_CD     # Ctrl+D
                try:
                    return ch
                except Exception:
                    return ""
            time.sleep(interval)
            elapsed += interval
        return ""  # timeout

else:
    # ── POSIX (Linux / macOS): tty + select ───────────────────────────────────
    import select as _select, tty as _tty, termios as _termios

    _POSIX_SEQ: dict[bytes,str] = {
        b"[A":K_UP,   b"[B":K_DOWN,  b"[C":K_RIGHT, b"[D":K_LEFT,
        b"[H":K_HOME, b"[F":K_END,   b"[5~":K_PGUP, b"[6~":K_PGDN,
        b"OA":K_UP,   b"OB":K_DOWN,  b"OC":K_RIGHT, b"OD":K_LEFT,
        b"[1~":K_HOME,b"[4~":K_END,
    }

    def read_key(timeout:float=5.0)->str:
        """
        POSIX raw keypress reader.
        Returns "" on timeout — callers loop and call again.
        """
        fd  = sys.stdin.fileno()
        old = _termios.tcgetattr(fd)
        try:
            _tty.setraw(fd)
            ready = _select.select([fd],[],[],timeout)[0]
            if not ready: return ""
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                rest = b""
                while _select.select([fd],[],[],0.04)[0]:
                    part = os.read(fd, 16); rest += part
                    if rest and rest[-1:] not in (b"\x1b",): break
                # Discard mouse events
                if rest.startswith((b"[M", b"[<", b"[?")): return ""
                return _POSIX_SEQ.get(rest, K_ESC) if rest else K_ESC
            if ch in (b"\r", b"\n"): return K_ENTER
            if ch == b"\t":          return K_TAB
            if ch == b"\x7f":        return K_BS
            if ch == b"\x03":        return K_CC
            if ch == b"\x04":        return K_CD
            if not ch:               return ""
            return ch.decode("utf-8", "replace")
        except Exception:
            return K_ESC
        finally:
            _termios.tcsetattr(fd, _termios.TCSADRAIN, old)


# ── Box drawing ────────────────────────────────────────────────────────────────
def box_top(w:int, title:str="", col:str=COL_BORD, tcol:str="")->str:
    inner = w-2
    if title:
        t=f" {title} "; tl=vlen(t)
        pad=max(1,(inner-tl)//2); rest=max(0,inner-tl-pad)
        tc = tcol or (ACCENT2+BOLD)
        return col+"╔"+"─"*pad+RESET+tc+t+RESET+col+"─"*rest+"╗"+RESET
    return col+"╔"+"─"*inner+"╗"+RESET

def box_bot(w:int, col:str=COL_BORD)->str:
    return col+"╚"+"─"*(w-2)+"╝"+RESET

def box_sep(w:int, col:str=COL_BORD)->str:
    return col+"╟"+"─"*(w-2)+"╢"+RESET

def box_row(content:str, w:int, col:str=COL_BORD, bg:str="")->str:
    inner  = w-4
    padded = pad_to(truncate(content, inner), inner)
    return col+"║"+RESET+bg+"  "+padded+"  "+RESET+col+"║"+RESET

SPINNER = ["|","/","-","\\"]  # ASCII fallback (works everywhere, even Windows cmd)

def pbar(pct:float, width:int=28, col:str="")->str:
    fill  = max(0, min(width, int(pct*width)))
    empty = width-fill
    c = col or COL_OK
    return c+"█"*fill+COL_BORD+"░"*empty+RESET
