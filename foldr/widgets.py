"""
foldr.widgets
~~~~~~~~~~~~~
Reusable TUI widgets drawn onto a Screen.
"""
from __future__ import annotations
import time, math
from foldr.screen import Screen
from foldr.ansi import (
    RESET, BOLD, DIM, BLINK, REV,
    BCYAN, CYAN, BGREEN, GREEN, BYELLOW, YELLOW,
    BMAGENTA, MAGENTA, BRED, RED, BBLUE, BLUE,
    BWHITE, WHITE, BBLACK,
    BG_DARK, BG_DARK2, BG_HEADER, BG_SEL,
    c256, rgb, pad, strip_ansi, cat_col, cat_icon,
    CAT_COLOURS, term_size,
)


# ── Palette shortcuts ────────────────────────────────────────────────────────
ACCENT     = BCYAN
ACCENT2    = c256(39)          # bright sky blue
SUCCESS    = BGREEN
WARN       = BYELLOW
ERROR      = BRED
MUTED      = BBLACK + DIM
HDR_BG     = c256(17, bg=True) # dark navy background
HDR_FG     = BWHITE
SEL_BG     = c256(24, bg=True) # selected row
SEL_FG     = BWHITE
BOX_COL    = c256(244)         # box border colour
TITLE_COL  = BCYAN + BOLD


# ── Logo ─────────────────────────────────────────────────────────────────────
LOGO_LINES = [
    f"{BCYAN}{BOLD}  ███████╗ ██████╗ ██╗     ██████╗ ██████╗ {RESET}",
    f"{BCYAN}{BOLD}  ██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗{RESET}",
    f"{CYAN}{BOLD}  █████╗  ██║   ██║██║     ██║  ██║██████╔╝{RESET}",
    f"{CYAN}  ██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗{RESET}",
    f"{c256(39)}  ███████╗╚██████╔╝███████╗██████╔╝██║  ██║{RESET}",
    f"{c256(39)}  ╚══════╝ ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝{RESET}",
]
LOGO_SUB = f"  {MUTED}v4  ·  Smart File Organizer  ·  github.com/qasimio/Foldr{RESET}"


def draw_logo(scr: Screen, row: int = 1) -> int:
    """Draw ASCII logo, return next row."""
    _, w = term_size()
    for i, line in enumerate(LOGO_LINES):
        vis = strip_ansi(line)
        col = max(0, (w - len(vis)) // 2)
        scr.put(row + i, col, line)
    sub_vis = strip_ansi(LOGO_SUB)
    scr.put(row + len(LOGO_LINES) + 1, max(0, (w - sub_vis.__len__()) // 2), LOGO_SUB)
    return row + len(LOGO_LINES) + 3


# ── Header bar ───────────────────────────────────────────────────────────────

def draw_header(scr: Screen, title: str, mode_tag: str, mode_col: str,
                path: str = "") -> None:
    _, w = term_size()
    bar = HDR_BG + HDR_FG + BOLD + " " * w + RESET
    scr.fill_row(0, bar)
    left  = f"  {BCYAN}◈{RESET} {HDR_BG}{HDR_FG}{BOLD} FOLDR {RESET}{HDR_BG}{HDR_FG}  {title}{RESET}"
    right = f"  {mode_col}{BOLD} {mode_tag} {RESET}  "
    scr.put(0, 0, HDR_BG + " " * w + RESET)
    scr.put(0, 2, left)
    scr.put(0, w - len(strip_ansi(right)) - 1, right)
    if path:
        scr.put(1, 2, f"  {MUTED}📁  {path}{RESET}")


# ── Status / footer bar ──────────────────────────────────────────────────────

def draw_footer(scr: Screen, row: int, keys: list[tuple[str, str]]) -> None:
    _, w = term_size()
    scr.put(row, 0, c256(236, bg=True) + " " * w + RESET)
    x = 2
    parts = []
    for key, desc in keys:
        parts.append(
            f"{c256(236, bg=True)}{BYELLOW}{BOLD} {key} {RESET}"
            f"{c256(236, bg=True)}{WHITE} {desc} {RESET}"
            f"{c256(236, bg=True)}{MUTED}│{RESET}"
        )
    scr.put(row, 2, " ".join(parts))


# ── Spinner ──────────────────────────────────────────────────────────────────
SPINNER_FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

class Spinner:
    def __init__(self, label: str = ""):
        self.label = label
        self._frame = 0
        self._t = time.time()

    def tick(self) -> str:
        if time.time() - self._t > 0.1:
            self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
            self._t = time.time()
        return f"{BCYAN}{SPINNER_FRAMES[self._frame]}{RESET}  {self.label}"


# ── Progress bar ─────────────────────────────────────────────────────────────

def progress_bar(pct: float, width: int = 30,
                 col_fill: str = BGREEN, col_empty: str = MUTED) -> str:
    filled = max(0, min(width, int(pct * width)))
    empty  = width - filled
    # Gradient fill
    bar = col_fill + "█" * filled + col_empty + "░" * empty + RESET
    return f"[{bar}]"


# ── Category bar chart ───────────────────────────────────────────────────────

def category_bars(counts: dict[str, int], bar_w: int = 20) -> list[str]:
    """Return list of rendered bar chart rows."""
    total = max(1, sum(counts.values()))
    rows  = []
    for cat, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        if cnt == 0:
            continue
        icon  = cat_icon(cat)
        col   = cat_col(cat)
        pct   = cnt / total
        filled= max(1, int(pct * bar_w))
        bar   = col + "█" * filled + MUTED + "░" * (bar_w - filled) + RESET
        label = f"{col}{BOLD}{icon} {cat:<18}{RESET}"
        count = f"{col}{cnt:>4}{RESET}"
        pct_s = f"  {MUTED}{pct*100:4.1f}%{RESET}"
        rows.append(f"  {label}  {bar}  {count}{pct_s}")
    return rows


# ── Table ────────────────────────────────────────────────────────────────────

def table_row(cols: list[str], widths: list[int],
              row_col: str = "", sep: str = "  ") -> str:
    parts = []
    for i, (col, w) in enumerate(zip(cols, widths)):
        parts.append(pad(col_col(col if row_col else col, ""), w))
    return row_col + sep.join(parts) + RESET

def col_col(s: str, _) -> str:
    return s


# ── Box with shadow ──────────────────────────────────────────────────────────

def draw_box(scr: Screen, row: int, col: int, h: int, w: int,
             title: str = "", border_col: str = BOX_COL,
             title_col: str = TITLE_COL, bg: str = "") -> None:
    """Draw a rounded box with optional title and background fill."""
    inner_w = w - 2

    # Fill background
    if bg:
        for r in range(h):
            scr.put(row + r, col, bg + " " * w + RESET)

    # Top border with title
    if title:
        t      = f" {title} "
        tlen   = len(t)
        pad_l  = max(1, (inner_w - tlen) // 2)
        pad_r  = max(1, inner_w - tlen - pad_l)
        top    = (border_col + "╔" + "═" * pad_l
                  + title_col + t + border_col
                  + "═" * pad_r + "╗" + RESET)
    else:
        top = border_col + "╔" + "═" * inner_w + "╗" + RESET

    scr.put(row,          col, top)
    scr.put(row + h - 1,  col, border_col + "╚" + "═" * inner_w + "╝" + RESET)

    for r in range(1, h - 1):
        scr.put(row + r, col,           border_col + "║" + RESET)
        scr.put(row + r, col + w - 1,   border_col + "║" + RESET)


# ── Notification / toast ─────────────────────────────────────────────────────

def draw_toast(scr: Screen, msg: str, kind: str = "info") -> None:
    """Draw a centred notification overlay."""
    h, w = term_size()
    col_map = {
        "info":    (BCYAN,   "╔", "╗", "╚", "╝"),
        "success": (BGREEN,  "╔", "╗", "╚", "╝"),
        "warn":    (BYELLOW, "╔", "╗", "╚", "╝"),
        "error":   (BRED,    "╔", "╗", "╚", "╝"),
    }
    col, *_ = col_map.get(kind, col_map["info"])
    lines  = msg.split("\n")
    box_w  = min(w - 4, max(40, max(len(l) for l in lines) + 6))
    box_h  = len(lines) + 4
    top    = (h - box_h) // 2
    left   = (w - box_w) // 2

    draw_box(scr, top, left, box_h, box_w,
             border_col=col, bg=c256(235, bg=True))

    for i, line in enumerate(lines):
        vis = strip_ansi(line)
        x   = left + (box_w - len(vis)) // 2
        scr.put(top + 2 + i, x, col + BOLD + line + RESET)


# ── Confirm dialog ───────────────────────────────────────────────────────────

def confirm_dialog(scr: Screen, title: str, body: list[str],
                   yes: str = "  ✓ Yes, proceed  ",
                   no:  str = "  ✗ No, cancel    ",
                   danger: bool = False) -> bool:
    """
    Blocking confirm dialog.
    Returns True = confirmed, False = cancelled.
    """
    from foldr.keys import read_key, ENTER, ESC, LEFT, RIGHT, UP, DOWN, TAB, CTRL_C
    h, w = term_size()

    max_body = max((len(strip_ansi(l)) for l in body), default=20)
    box_w    = min(w - 4, max(50, max_body + 8, len(yes) + len(no) + 12))
    box_h    = len(body) + 7
    top      = max(2, (h - box_h) // 2)
    left     = max(0, (w - box_w) // 2)

    border   = BRED if danger else BCYAN
    sel      = 0  # 0 = no (safe default), 1 = yes

    while True:
        # Draw dialog over current screen
        draw_box(scr, top, left, box_h, box_w,
                 title=title, border_col=border,
                 bg=c256(234, bg=True))

        for i, line in enumerate(body):
            vis_col = left + max(1, (box_w - len(strip_ansi(line))) // 2)
            scr.put(top + 2 + i, vis_col, line)

        # Divider
        scr.put(top + 2 + len(body) + 1, left + 1,
                border + "─" * (box_w - 2) + RESET)

        # Buttons
        btn_row = top + box_h - 2
        yes_col = c256(234, bg=True) + (BGREEN + BOLD + c256(22, bg=True) if sel == 1 else MUTED)
        no_col  = c256(234, bg=True) + (BRED + BOLD  + c256(52, bg=True) if sel == 0 else MUTED)

        btn_total = len(yes) + len(no) + 4
        bx = left + max(1, (box_w - btn_total) // 2)
        scr.put(btn_row, bx,
                no_col  + no  + RESET + "    " +
                yes_col + yes + RESET)

        hint = f"  {MUTED}← →  navigate   Enter  confirm   Esc  cancel{RESET}"
        scr.put(top + box_h - 1, left + 2, hint)
        scr.flush()

        k = read_key()
        if k in (LEFT, "h", TAB):
            sel = 1 - sel
        elif k in (RIGHT, "l"):
            sel = 1 - sel
        elif k == ENTER:
            return sel == 1
        elif k in (ESC, CTRL_C, "q", "n", "N"):
            return False
        elif k in ("y", "Y"):
            return True


# ── Scrollable list ──────────────────────────────────────────────────────────

class ScrollList:
    """Scrollable selectable list widget."""

    def __init__(self, items: list[str], row: int, col: int,
                 height: int, width: int,
                 border_col: str = BOX_COL,
                 title: str = ""):
        self.items      = items
        self.row        = row
        self.col        = col
        self.height     = height
        self.width      = width
        self.border_col = border_col
        self.title      = title
        self.scroll     = 0
        self.cursor     = 0
        self._inner_h   = height - 2

    @property
    def selected(self) -> int:
        return self.cursor

    def move(self, delta: int) -> None:
        self.cursor = max(0, min(len(self.items) - 1, self.cursor + delta))
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + self._inner_h:
            self.scroll = self.cursor - self._inner_h + 1

    def page(self, direction: int) -> None:
        self.move(direction * self._inner_h)

    def draw(self, scr: Screen) -> None:
        draw_box(scr, self.row, self.col, self.height, self.width,
                 title=self.title, border_col=self.border_col)

        inner_w = self.width - 2
        visible = self.items[self.scroll: self.scroll + self._inner_h]

        for i, item in enumerate(visible):
            abs_i  = self.scroll + i
            is_sel = abs_i == self.cursor
            r      = self.row + 1 + i

            if is_sel:
                bg  = SEL_BG
                fg  = SEL_FG + BOLD
                bar = "▶ "
            else:
                bg  = ""
                fg  = ""
                bar = "  "

            vis   = strip_ansi(item)
            trunc = vis[:inner_w - 3] + ("…" if len(vis) > inner_w - 3 else "")
            line  = bar + trunc
            line  = line + " " * max(0, inner_w - len(line))
            scr.put(r, self.col + 1, bg + fg + line + RESET)

        # Scrollbar
        total = len(self.items)
        if total > self._inner_h:
            sb_h    = max(1, self._inner_h * self._inner_h // total)
            sb_pos  = int(self.scroll / max(1, total - self._inner_h)
                          * (self._inner_h - sb_h))
            for r in range(self._inner_h):
                ch = "█" if sb_pos <= r < sb_pos + sb_h else "░"
                scr.put(self.row + 1 + r, self.col + self.width - 1,
                        MUTED + ch + RESET)