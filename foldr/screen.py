"""
foldr.screen
~~~~~~~~~~~~
Double-buffered terminal renderer — eliminates all flicker.

Architecture
------------
- Maintains a "back buffer" (list of strings, one per row)
- On flush(), diffs against "front buffer" and only writes changed rows
- All drawing goes to the back buffer; flush() atomically updates terminal
- Result: zero flicker, no full-screen redraws
"""
from __future__ import annotations
import sys, os
from foldr.ansi import (
    goto, CLEAR, HIDE_CURSOR, SHOW_CURSOR,
    ALT_ENTER, ALT_EXIT, RESET, CLEAR_LINE,
    strip_ansi, pad, term_size
)


class Screen:
    def __init__(self):
        self.h, self.w = term_size()
        self._back:  list[str] = [""] * self.h
        self._front: list[str] = ["\x00"] * self.h  # sentinel → force first draw
        self._dirty: set[int] = set()
        self._buf = []  # write buffer

    def resize(self) -> bool:
        h, w = term_size()
        if h != self.h or w != self.w:
            self.h, self.w = h, w
            self._back  = [""] * h
            self._front = ["\x00"] * h
            return True
        return False

    # ── drawing API ───────────────────────────────────────────────────────────

    def put(self, row: int, col: int, text: str, *, clip: bool = True) -> None:
        """Write `text` at (row, col) into back buffer."""
        if row < 0 or row >= self.h:
            return
        cur = self._back[row]
        # Ensure row is long enough
        vis_cur = strip_ansi(cur)
        pad_len = max(0, col - len(vis_cur))
        cur = cur + " " * pad_len

        # Reconstruct row with text inserted at col
        # Simple approach: build char-list of plain chars + escape tracking
        result = _row_insert(cur, col, text, self.w if clip else 99999)
        self._back[row] = result

    def fill_row(self, row: int, text: str) -> None:
        """Replace entire row."""
        if 0 <= row < self.h:
            self._back[row] = text

    def clear_back(self) -> None:
        self._back = [""] * self.h

    def flush(self) -> None:
        """Diff and write only changed rows."""
        out = []
        for r in range(self.h):
            back = self._back[r]
            if back != self._front[r]:
                # Clear row then write
                out.append(goto(r, 0))
                out.append(CLEAR_LINE)
                if back:
                    out.append(back)
                    out.append(RESET)
                self._front[r] = back
        if out:
            sys.stdout.write("".join(out))
            sys.stdout.flush()

    def enter_alt(self) -> None:
        sys.stdout.write(ALT_ENTER + HIDE_CURSOR + CLEAR)
        sys.stdout.flush()

    def exit_alt(self) -> None:
        sys.stdout.write(ALT_EXIT + SHOW_CURSOR)
        sys.stdout.flush()

    # ── box drawing ───────────────────────────────────────────────────────────

    def box(self, row: int, col: int, h: int, w: int,
            color: str = "", title: str = "", title_col: str = "") -> None:
        if h < 2 or w < 2:
            return
        tl,tr,bl,br = "╔","╗","╚","╝"
        hz, vt     = "═", "║"
        inner_w    = w - 2

        top_line = tl + hz * inner_w + tr
        mid_line = " " + " " * inner_w + " "
        bot_line = bl + hz * inner_w + br

        # Embed title in top border
        if title:
            t = f" {title} "
            tlen = len(t)
            if tlen < inner_w - 2:
                pos = (inner_w - tlen) // 2
                top_line = (tl + hz * pos
                            + (title_col or color) + t + (color or RESET)
                            + hz * (inner_w - pos - tlen) + tr)

        c = color
        self.put(row,     col, c + top_line + RESET)
        for r in range(1, h - 1):
            self.put(row + r, col, c + vt + RESET)
            self.put(row + r, col + w - 1, c + vt + RESET)
        self.put(row + h - 1, col, c + bot_line + RESET)

    def hline(self, row: int, col: int, w: int, color: str = "") -> None:
        self.put(row, col, color + "─" * w + RESET)


def _row_insert(row: str, col: int, text: str, max_w: int) -> str:
    """Insert text at visual column `col` in row string, respecting escapes."""
    import re
    ESC_RE = re.compile(r"\033\[[0-9;]*[mABCDHJKfsu]")

    # Decompose row into list of (escape|char)
    tokens = []
    pos = 0
    for m in ESC_RE.finditer(row):
        for ch in row[pos:m.start()]:
            tokens.append(("c", ch))
        tokens.append(("e", m.group()))
        pos = m.end()
    for ch in row[pos:]:
        tokens.append(("c", ch))

    # Insert text tokens at visual col
    vis = 0
    result = []
    inserted = False
    for kind, val in tokens:
        if kind == "e":
            result.append(val)
        else:
            if not inserted and vis == col:
                result.append(text)
                inserted = True
            if vis < max_w:
                result.append(val)
            vis += 1
    if not inserted:
        pad_needed = max(0, col - vis)
        result.append(" " * pad_needed)
        result.append(text)

    return "".join(result)