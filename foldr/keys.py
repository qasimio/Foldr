"""
foldr.keys
~~~~~~~~~~
Raw keypress reader — works on Linux/macOS without curses.
Returns semantic key names.
"""
from __future__ import annotations
import sys, tty, termios, os

# Key name constants
UP    = "UP";    DOWN  = "DOWN"
LEFT  = "LEFT";  RIGHT = "RIGHT"
ENTER = "ENTER"; ESC   = "ESC"
TAB   = "TAB";   BTAB  = "BTAB"
PGUP  = "PGUP";  PGDN  = "PGDN"
HOME  = "HOME";  END   = "END"
DEL   = "DEL";   BS    = "BS"
F1    = "F1";    F5    = "F5"; F10 = "F10"
CTRL_C = "CTRL_C"; CTRL_D = "CTRL_D"
CTRL_Z = "CTRL_Z"; CTRL_R = "CTRL_R"

_ESC_MAP = {
    b"[A": UP,    b"[B": DOWN,  b"[C": RIGHT, b"[D": LEFT,
    b"[H": HOME,  b"[F": END,
    b"[5~": PGUP, b"[6~": PGDN,
    b"[3~": DEL,
    b"[Z": BTAB,
    b"OP": F1, b"[15~": F5, b"[21~": F10,
    b"OA": UP, b"OB": DOWN, b"OC": RIGHT, b"OD": LEFT,
}


def read_key() -> str:
    """Block until a keypress; return semantic name or char."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            # Escape sequence
            rest = b""
            import select
            while True:
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    break
                rest += os.read(fd, 8)
            if rest:
                return _ESC_MAP.get(rest, "ESC")
            return ESC
        if ch == b"\r" or ch == b"\n":  return ENTER
        if ch == b"\t":                  return TAB
        if ch == b"\x7f":                return BS
        if ch == b"\x03":                return CTRL_C
        if ch == b"\x04":                return CTRL_D
        if ch == b"\x1a":                return CTRL_Z
        if ch == b"\x12":                return CTRL_R
        return ch.decode("utf-8", errors="replace")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_line(prompt: str = "", default: str = "",
              echo: bool = True) -> str:
    """Simple line editor (no history). Returns the string entered."""
    import sys
    sys.stdout.write(prompt + default)
    sys.stdout.flush()
    buf = list(default)
    while True:
        k = read_key()
        if k == ENTER:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf)
        elif k in (BS, DEL):
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif k == CTRL_C:
            raise KeyboardInterrupt
        elif k == ESC:
            return ""
        elif len(k) == 1:
            buf.append(k)
            if echo:
                sys.stdout.write(k)
                sys.stdout.flush()