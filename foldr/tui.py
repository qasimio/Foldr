"""
foldr.tui
~~~~~~~~~
All interactive screens for FOLDR v4.

Screens
-------
  splash()              0.7s animated logo on startup
  PreviewScreen.run()   scrollable move-list + approval dialog → bool
  ExecutionScreen ctx   live progress during file moves
  HistoryScreen.run()   browse/undo history
  WatchScreen           live watch-mode display (runs in thread)
  confirm_dialog()      standalone yes/no modal → bool

Architecture
------------
  Every screen uses term.Screen (double-buffered, row-diff renderer).
  Only changed rows are written to stdout → zero flicker, no full clears.
  Raw keys via term.read_key (no curses).
"""
from __future__ import annotations
import sys, time, threading
from pathlib import Path

from foldr.term import (
    Screen, read_key, term_wh, strip, vlen, truncate, pad_to,
    box_top, box_mid, box_bot, box_row, box_sep, pbar, SPINNER,
    cat_fg, cat_icon, fmt_size,
    RESET, BOLD, DIM, MUTED, ACCENT,
    BCYN, CYN, BGRN, GRN, BYLW, YLW,
    BMAG, BRED, RED, BBLU, BLU, BWHT, WHT, BBLK,
    bg256, fg256, rgb_bg, rgb_fg,
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_ENTER, K_ESC,
    K_PGUP, K_PGDN, K_HOME, K_END, K_TAB, K_CC,
)

# ── Colours / theme ────────────────────────────────────────────────────────────
HDR_BG   = rgb_bg(0, 18, 55)
HDR_FG   = BWHT
BG_DARK  = bg256(233)
BG_PANEL = bg256(234)
BG_SEL   = bg256(24)
BG_DRY   = rgb_bg(60, 45, 0)
COL_BORD = fg256(60)
COL_ACC2 = rgb_fg(0,190,255)
SEL_FG   = BWHT + BOLD

# ── ASCII logo (7 rows) ────────────────────────────────────────────────────────
_LOGO = [
    (BCYN+BOLD, "███████╗ ██████╗ ██╗     ██████╗ ██████╗ "),
    (BCYN+BOLD, "██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗"),
    (CYN +BOLD, "█████╗  ██║   ██║██║     ██║  ██║██████╔╝"),
    (CYN,       "██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗"),
    (BCYN,      "██║     ╚██████╔╝███████╗██████╔╝██║  ██║"),
    (BCYN,      "╚═╝      ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝"),
]

def _render_screen_bg(scr: Screen, w: int, h: int) -> None:
    """Fill entire screen with dark background."""
    bg = BG_DARK + " "*w + RESET
    for r in range(h): scr.fill(r, bg)

def _render_header(scr: Screen, w: int, title: str,
                   tag: str, tag_col: str, path_str: str = "") -> None:
    """Row 0: full-width header bar."""
    path_part = f"  {MUTED}📁 {path_str}{RESET}" if path_str else ""
    left  = f"{HDR_BG}{HDR_FG}{BOLD}  ◈  FOLDR   {RESET}{HDR_BG}{WHT}{title}{RESET}{HDR_BG}{path_part}{RESET}"
    right = f"{HDR_BG}  {tag_col}{BOLD}{RESET}{HDR_BG}{tag_col} {tag} {RESET}"
    # Fill row with header bg
    scr.fill(0, HDR_BG + " "*w + RESET)
    # Left side
    scr.fill(0, left + HDR_BG + " "*(w - vlen(strip(left)) - vlen(strip(right))) + right + RESET)

def _render_footer(scr: Screen, w: int, row: int,
                   hints: list[tuple[str,str]]) -> None:
    """Single-row hint bar at the bottom."""
    BG = bg256(235)
    parts = []
    for key, desc in hints:
        parts.append(f"{BG}{BYLW+BOLD} {key} {RESET}{BG}{WHT} {desc} {RESET}{BG}{MUTED}│{RESET}")
    line = "".join(parts)
    scr.fill(row, BG + " "*w + RESET)
    scr.fill(row, " " + line)

# ── Splash ─────────────────────────────────────────────────────────────────────
def splash(duration: float = 0.7) -> None:
    scr = Screen()
    scr.enter()
    try:
        w, h = scr.w, scr.h
        frames = 7
        logo_h = len(_LOGO) + 3
        top    = max(1, (h - logo_h) // 2)
        for f in range(frames):
            scr.clear_back()
            # Gradient background
            for r in range(h):
                d = min(3, int(r/h * 4))
                scr.fill(r, bg256(232+d) + " "*w + RESET)
            # Logo lines (staggered reveal)
            for i, (col, txt) in enumerate(_LOGO):
                if i <= f:
                    lw   = vlen(txt)
                    lcol = max(0, (w - lw) // 2)
                    scr.fill(top+i, " "*lcol + col + txt + RESET)
            # Tagline
            if f >= 4:
                sub  = f"  {MUTED}v4 · Smart File Organizer · github.com/qasimio/Foldr{RESET}"
                scol = max(0, (w - vlen(strip(sub))) // 2)
                scr.fill(top + len(_LOGO) + 1, " "*scol + sub)
            # Loading dots
            dot_s = BCYN + "●"*(f%4+1) + fg256(236) + "●"*(3-f%4) + RESET
            scr.fill(top + len(_LOGO) + 2, " "*((w-3)//2) + dot_s)
            scr.flush()
            time.sleep(duration / frames)
        time.sleep(0.1)
    finally:
        scr.exit()


# ── confirm_dialog ─────────────────────────────────────────────────────────────
def confirm_dialog(scr: Screen, title: str, body_lines: list[str],
                   yes_label: str = " ✓ Yes ", no_label: str = " ✗ Cancel ",
                   danger: bool = False) -> bool:
    """
    Blocking modal dialog drawn onto `scr`.
    Returns True = confirmed, False = cancelled.
    Default selection is CANCEL (safe default).
    """
    w, h = scr.w, scr.h
    border_col = BRED if danger else BCYN

    body_vlen = max((vlen(l) for l in body_lines), default=20)
    box_w = min(w - 6, max(52, body_vlen + 8))
    box_h = len(body_lines) + 7
    box_r = max(1, (h - box_h) // 2)
    box_c = max(0, (w - box_w) // 2)

    sel = 0  # 0 = cancel (safe default)

    while True:
        # We only redraw the dialog area to avoid flickering
        scr.fill(box_r, box_top(box_w, title, col=border_col, tcol=BYLW+BOLD) if not danger
                        else box_top(box_w, title, col=BRED, tcol=BYLW+BOLD))
        # Offset for box start column
        def put(row: int, content: str) -> None:
            # Pad content to full terminal width so right side is cleared
            left_pad  = " " * box_c
            right_pad = " " * max(0, w - box_c - vlen(strip(content)))
            scr.fill(row, BG_DARK + left_pad + content + right_pad + RESET)

        put(box_r, box_top(box_w, title, col=border_col, tcol=BYLW+BOLD))
        put(box_r+1, box_mid(box_w, col=border_col))

        for i, bl in enumerate(body_lines):
            bw = box_w - 4
            line = pad_to(truncate(bl, bw), bw)
            put(box_r+2+i, border_col + "║" + RESET + "  " + line + "  " + border_col + "║" + RESET)

        sep_r = box_r + 2 + len(body_lines)
        put(sep_r,   box_sep(box_w, col=border_col))
        put(sep_r+1, box_mid(box_w, col=border_col))

        # Buttons row
        no_s  = (BG_SEL + SEL_FG if sel==0 else MUTED) + f" ◀ {no_label} ▶ " + RESET
        yes_s = (bg256(22)+BGRN+BOLD if sel==1 else MUTED) + f" ◀ {yes_label} ▶ " + RESET
        btn_gap = box_w - 4 - vlen(strip(no_s)) - vlen(strip(yes_s))
        gap = " " * max(2, btn_gap // 2)
        put(sep_r+2, border_col + "║" + RESET + "  " + no_s + gap + yes_s + "  " + border_col + "║" + RESET)

        hint = f"  {MUTED}← →  navigate    Enter  confirm    Esc  cancel{RESET}"
        hint_pad = pad_to(truncate(hint, box_w-4), box_w-4)
        put(sep_r+3, border_col + "║" + RESET + "  " + hint_pad + "  " + border_col + "║" + RESET)
        put(sep_r+4, box_bot(box_w, col=border_col))

        scr.flush()
        k = read_key()

        if k in (K_LEFT, K_RIGHT, K_TAB, "h", "l"):
            sel = 1 - sel
        elif k == K_ENTER:
            return sel == 1
        elif k in (K_ESC, K_CC, "q", "Q", "n", "N"):
            return False
        elif k in ("y", "Y"):
            return True


# ── PreviewScreen ──────────────────────────────────────────────────────────────
class PreviewScreen:
    """
    Full-screen preview: scrollable move list + approval gate.

    Layout (top to bottom)
    ──────────────────────
     0        header bar
     1        blank (spacer)
     2..L+1   move list (scrollable, boxed)
     L+2      selected-item detail strip
     L+3..S   category bar chart (boxed)
     S+1      dry-run banner  (only when --dry-run)
     S+2/-1   footer hints
    """
    def __init__(self, records: list, base: Path, dry_run: bool):
        self.records  = records
        self.base     = base
        self.dry_run  = dry_run
        # Build category counts
        self.cat_counts: dict[str,int] = {}
        for r in records:
            self.cat_counts[r.category] = self.cat_counts.get(r.category, 0) + 1
        self.sorted_cats = sorted(self.cat_counts.items(), key=lambda x: -x[1])
        # Format display lines for the list
        self._lines = self._fmt_lines()
        # Scroll state
        self.cursor = 0
        self.scroll = 0

    def _fmt_lines(self) -> list[str]:
        out = []
        for r in self.records:
            dest = Path(r.destination).parent.name
            col  = cat_fg(r.category)
            icon = cat_icon(r.category)
            out.append(
                f"{col}{BOLD}{r.filename}{RESET}"
                f"  {MUTED}→{RESET}  "
                f"{col}{icon} {dest}/{RESET}"
                f"  {MUTED}{r.category}{RESET}"
            )
        return out

    def run(self) -> bool:
        scr = Screen()
        scr.enter()
        try:
            return self._loop(scr)
        finally:
            scr.exit()

    # ── layout math (called every frame to handle resize) ──────────────────────
    def _layout(self, w: int, h: int) -> dict:
        n_cats   = len(self.sorted_cats)
        stats_h  = min(n_cats + 2, 10)          # box: border + rows
        footer_h = 1
        dry_h    = 1 if self.dry_run else 0
        header_h = 1
        spacer   = 1
        detail_h = 1
        # Remaining rows for the list box (minimum 5)
        list_h = max(5, h - header_h - spacer - detail_h - stats_h - dry_h - footer_h - 2)
        list_inner = list_h - 2        # rows inside the box borders

        return dict(
            header=0,
            spacer=1,
            list_top=2,
            list_h=list_h,
            list_inner=list_inner,
            detail=2 + list_h,
            stats_top=2 + list_h + 1,
            stats_h=stats_h,
            dry_row=2 + list_h + 1 + stats_h + (1 if dry_h else -99),
            footer=h - 1,
        )

    def _loop(self, scr: Screen) -> bool:
        while True:
            scr.resize()
            w, h = scr.w, scr.h
            L = self._layout(w, h)
            self._draw(scr, w, h, L)
            k = read_key()
            # Navigation
            if k in (K_UP, "k"):     self._move(-1, L["list_inner"])
            elif k in (K_DOWN,"j"):  self._move(+1, L["list_inner"])
            elif k == K_PGUP:        self._move(-L["list_inner"], L["list_inner"])
            elif k == K_PGDN:        self._move(+L["list_inner"], L["list_inner"])
            elif k == K_HOME:        self.cursor=0; self.scroll=0
            elif k == K_END:
                self.cursor=max(0,len(self._lines)-1)
                self.scroll=max(0,len(self._lines)-L["list_inner"])
            # Action
            elif k in ("y","Y") and not self.dry_run:
                confirmed = confirm_dialog(
                    scr,
                    title=" ⚡ Execute File Moves ",
                    body_lines=[
                        f"{BWHT}Move {BCYN+BOLD}{len(self.records)}{RESET+BWHT} files from {BCYN}{self.base.name}/{RESET}",
                        f"{BWHT}into {BCYN+BOLD}{len(self.cat_counts)}{RESET+BWHT} category folders.{RESET}",
                        "",
                        f"{MUTED}Reversible with:  {BCYN}foldr undo{RESET}",
                    ],
                    yes_label=" ✓ Execute ",
                    no_label=" ✗ Cancel  ",
                )
                return confirmed
            elif k in ("n","N",K_ESC,K_CC,"q","Q"):
                return False
            elif k == "?":
                self._help(scr, w, h)

    def _move(self, delta: int, inner: int) -> None:
        n = len(self._lines)
        self.cursor = max(0, min(n-1, self.cursor + delta))
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + inner:
            self.scroll = self.cursor - inner + 1

    def _draw(self, scr: Screen, w: int, h: int, L: dict) -> None:
        # Background
        _render_screen_bg(scr, w, h)

        # Header
        tag     = "DRY-RUN ─ NO FILES MOVE" if self.dry_run else "PREVIEW ─ APPROVAL REQUIRED"
        tag_col = BYLW if self.dry_run else BCYN
        _render_header(scr, w, "Interactive Preview", tag, tag_col, str(self.base))

        # Move list box
        n        = len(self._lines)
        inner    = L["list_inner"]
        list_top = L["list_top"]
        title_str = f"Planned Moves  ({n} files)"

        scr.fill(list_top, BG_PANEL + box_top(w, title_str, col=COL_BORD, tcol=COL_ACC2+BOLD) + RESET)
        for i in range(inner):
            abs_i = self.scroll + i
            row_r = list_top + 1 + i
            if abs_i < n:
                is_sel = (abs_i == self.cursor)
                raw = self._lines[abs_i]
                # Build content
                prefix = f"{BGRN+BOLD}▶ {RESET}" if is_sel else "  "
                content = truncate(raw, w - 6)
                inner_w = w - 4   # 2 border ║ + 2 padding
                if is_sel:
                    body = pad_to(strip(prefix) + strip(content), inner_w)
                    line = (COL_BORD + "║" + RESET + BG_SEL + SEL_FG + " " + body + " " + RESET + COL_BORD + "║" + RESET)
                else:
                    body = truncate(prefix + content, inner_w - 1)
                    line = (COL_BORD + "║" + RESET + BG_PANEL + " " + body + " "*(inner_w - vlen(strip(body)) - 1) + " " + RESET + COL_BORD + "║" + RESET)
                scr.fill(row_r, line)
            else:
                scr.fill(row_r, COL_BORD + "║" + RESET + BG_PANEL + " "*(w-2) + RESET + COL_BORD + "║" + RESET)
        # Scrollbar — insert before right border ║
        if n > inner:
            sb_h   = max(1, inner * inner // n)
            sb_pos = int(self.scroll / max(1, n-inner) * (inner - sb_h))
            for i in range(inner):
                ch    = ("█" if sb_pos <= i < sb_pos+sb_h else fg256(236)+"░")
                row_r = list_top + 1 + i
                # Row is: ║ body ║ — insert scrollbar char before last ║
                row   = scr._back[row_r]
                # Strip the trailing ║+RESET and replace with sb+║+RESET
                suffix = COL_BORD + "║" + RESET
                if row.endswith(suffix):
                    row = row[:-len(suffix)] + MUTED + ch + RESET + suffix
                    scr.fill(row_r, row)
        scr.fill(list_top + inner + 1,
                 BG_PANEL + box_bot(w, col=COL_BORD) + RESET)

        # Detail strip
        if self._lines:
            r  = self.records[self.cursor]
            dest = Path(r.destination).parent.name
            col  = cat_fg(r.category)
            icon = cat_icon(r.category)
            detail = (f"  {MUTED}▸  Selected:{RESET}  "
                      f"{col+BOLD}{icon} {r.filename}{RESET}"
                      f"  {MUTED}→{RESET}  {col}{dest}/{RESET}"
                      f"  {MUTED}[{r.category}]{RESET}")
            scr.fill(L["detail"], bg256(234) + pad_to(detail, w) + RESET)

        # Category bar chart (stats box)
        st      = L["stats_top"]
        bar_w   = max(12, w // 3)
        total_f = max(1, len(self.records))
        scr.fill(st, BG_PANEL + box_top(w, " Category Breakdown ", col=COL_BORD, tcol=COL_ACC2+BOLD) + RESET)
        max_rows = L["stats_h"] - 2
        for i, (cat, cnt) in enumerate(self.sorted_cats[:max_rows]):
            col  = cat_fg(cat)
            icon = cat_icon(cat)
            pct  = cnt / total_f
            fill = max(1, int(pct * bar_w))
            bar  = col + "█"*fill + MUTED + "░"*(bar_w-fill) + RESET
            pcts = f"{pct*100:4.1f}%"
            row  = (f"  {col+BOLD}{icon} {pad_to(cat,18)}{RESET}"
                    f"  {bar}  {col+BOLD}{cnt:>4}{RESET}  {MUTED}{pcts}{RESET}")
            scr.fill(st+1+i, BG_PANEL + row + RESET)
        # Summary count in top-right of stats box
        summary = (f"  {BCYN+BOLD}{len(self.records)}{RESET} files"
                   f"  {MUTED}·{RESET}  {BCYN+BOLD}{len(self.cat_counts)}{RESET} categories  ")
        sr = st + 1
        # Right-align summary
        cur = scr._back[sr]
        sv  = vlen(strip(summary))
        if sv < w - 4:
            scr.fill(sr, cur.rstrip(RESET) + " "*(w - len(strip(cur)) - sv - 2) + summary + RESET)
        scr.fill(st + L["stats_h"] - 1, BG_PANEL + box_bot(w, col=COL_BORD) + RESET)

        # Dry-run banner
        if self.dry_run:
            banner = (BG_DRY + BYLW+BOLD
                      + "  ● DRY RUN — NO FILES WILL BE MOVED — THIS IS A PREVIEW ONLY  "
                      + RESET)
            bv  = vlen(strip(banner))
            pad = " "*max(0,(w-bv)//2)
            scr.fill(L["dry_row"], BG_DRY + " "*w + RESET)
            scr.fill(L["dry_row"], pad + banner)

        # Footer
        if self.dry_run:
            hints = [("↑↓","scroll"),("PgUp/Dn","fast"),("Q/Esc","exit")]
        else:
            hints = [("Y","EXECUTE"),("N/Esc","cancel"),("↑↓","scroll"),("PgUp/Dn","fast"),("?","help")]
        _render_footer(scr, w, L["footer"], hints)

        scr.flush()

    def _help(self, scr: Screen, w: int, h: int) -> None:
        lines = [
            f"  {BCYN+BOLD}Keyboard Shortcuts{RESET}",
            "",
            f"  {BYLW}↑ / k{RESET}         Scroll up",
            f"  {BYLW}↓ / j{RESET}         Scroll down",
            f"  {BYLW}PgUp / PgDn{RESET}   Fast scroll",
            f"  {BYLW}Home / End{RESET}    Jump to top / bottom",
            "",
            f"  {BGRN}Y{RESET}             Open confirmation dialog",
            f"  {BRED}N / Esc{RESET}       Cancel — nothing moves",
            "",
            f"  {MUTED}Colour key:{RESET}",
            f"  {BCYN}■{RESET} Docs  {BGRN}■{RESET} Images  {BYLW}■{RESET} Video  {BMAG}■{RESET} Audio  {BRED}■{RESET} Archives  {BBLU}■{RESET} Code",
            "",
            f"  {MUTED}Press any key to close{RESET}",
        ]
        bw = min(58, w-4)
        bh = len(lines)+4
        br = max(1,(h-bh)//2)
        bc = max(0,(w-bw)//2)
        pad = " "*bc
        scr.fill(br, pad + box_top(bw," Help ", col=BCYN, tcol=BCYN+BOLD))
        for i,l in enumerate(lines[:bh-2]):
            inner_w = bw-4
            scr.fill(br+1+i, pad + BCYN+"║"+RESET+"  " + pad_to(truncate(l,inner_w),inner_w) + "  "+BCYN+"║"+RESET)
        scr.fill(br+len(lines)+1, pad + box_bot(bw, col=BCYN))
        scr.flush()
        read_key()


# ── ExecutionScreen ────────────────────────────────────────────────────────────
class ExecutionScreen:
    """Context manager: live progress display during file moves."""
    def __init__(self, total: int, base: Path):
        self.total   = total
        self.base    = base
        self.done    = 0
        self.current = ""
        self.log: list[tuple[str,str,str]] = []  # (cat, fname, dest)
        self._scr    = Screen()
        self._lock   = threading.Lock()
        self._start  = time.monotonic()

    def __enter__(self):
        self._scr.enter()
        return self

    def __exit__(self, *_):
        self._scr.exit()

    def update(self, filename: str, dest: str, category: str) -> None:
        with self._lock:
            self.done += 1
            self.current = filename
            self.log.append((category, filename, dest))
        self._draw()

    def _draw(self) -> None:
        scr = self._scr
        scr.resize()
        w, h = scr.w, scr.h
        elapsed = time.monotonic() - self._start
        pct     = self.done / max(1, self.total)

        _render_screen_bg(scr, w, h)
        _render_header(scr, w, "Executing", "MOVING FILES", BGRN, str(self.base))

        # Progress box
        pb_row = 3
        scr.fill(pb_row, BG_PANEL + box_top(w," Progress ", col=COL_BORD, tcol=BGRN+BOLD))
        bar_w = max(10, w-20)
        bar   = pbar(pct, bar_w)
        scr.fill(pb_row+1, BG_PANEL + f"  {bar}  " + RESET)
        rate   = self.done / max(0.01, elapsed)
        remain = max(0,(self.total-self.done)/max(0.01,rate))
        stats  = (f"  {BCYN+BOLD}{self.done}{RESET}/{BCYN}{self.total}{RESET} files"
                  f"  {MUTED}·{RESET}  {BGRN+BOLD}{pct*100:.0f}%{RESET}"
                  f"  {MUTED}·{RESET}  {BYLW}{elapsed:.1f}s{RESET} elapsed"
                  f"  {MUTED}· ~{remain:.0f}s left{RESET}")
        scr.fill(pb_row+2, BG_PANEL + stats + RESET)
        if self.current:
            scr.fill(pb_row+3, BG_PANEL + f"  {MUTED}▸  {BCYN}{self.current}{RESET}")
        scr.fill(pb_row+4, BG_PANEL + box_bot(w, col=COL_BORD))

        # Live log
        log_top = pb_row + 6
        log_h   = h - log_top - 2
        scr.fill(log_top-1, BG_PANEL + box_top(w," Recent Moves ", col=COL_BORD, tcol=COL_ACC2+BOLD))
        with self._lock:
            visible = self.log[-(log_h):]
        for i,(cat,fname,dest) in enumerate(visible):
            col  = cat_fg(cat)
            icon = cat_icon(cat)
            line = (f"  {col}{icon}{RESET}  {col+BOLD}{truncate(fname,40)}{RESET}"
                    f"  {MUTED}→{RESET}  {col}{dest}/{RESET}")
            scr.fill(log_top+i, BG_PANEL + line + RESET)
        scr.fill(log_top + log_h, BG_PANEL + box_bot(w, col=COL_BORD))
        scr.flush()


# ── HistoryScreen ──────────────────────────────────────────────────────────────
class HistoryScreen:
    def __init__(self, entries: list[dict]):
        self.entries = entries
        self._cursor = 0
        self._scroll = 0

    def run(self) -> tuple[str|None, str|None]:
        scr = Screen()
        scr.enter()
        try:
            return self._loop(scr)
        finally:
            scr.exit()

    def _loop(self, scr: Screen) -> tuple[str|None, str|None]:
        n = len(self.entries)
        while True:
            scr.resize()
            w, h = scr.w, scr.h
            inner = h - 4
            self._draw(scr, w, h, inner)
            k = read_key()
            if k in (K_UP,"k"):     self._mv(-1, inner)
            elif k in (K_DOWN,"j"): self._mv(+1, inner)
            elif k == K_PGUP:       self._mv(-inner, inner)
            elif k == K_PGDN:       self._mv(+inner, inner)
            elif k in (K_ENTER,"d","D") and n:
                self._detail(scr, self.entries[self._cursor])
            elif k in ("u","U") and n:
                eid = self.entries[self._cursor].get("id")
                confirmed = confirm_dialog(
                    scr,
                    title=" ↩ Undo Operation ",
                    body_lines=[
                        f"{BWHT}Restore {BCYN+BOLD}{self.entries[self._cursor].get('total_files',0)}{RESET+BWHT} files{RESET}",
                        f"{BWHT}from operation {BCYN+BOLD}{eid}{RESET}",
                        f"{MUTED}Files return to their original locations.{RESET}",
                    ],
                    yes_label=" ↩ Undo ",
                    no_label=" ✗ Cancel ",
                    danger=True,
                )
                if confirmed:
                    return "undo", eid
            elif k in (K_ESC,K_CC,"q","Q"):
                return None, None

    def _mv(self, d: int, inner: int) -> None:
        n = len(self.entries)
        self._cursor = max(0, min(n-1, self._cursor+d))
        if self._cursor < self._scroll:
            self._scroll = self._cursor
        elif self._cursor >= self._scroll + inner:
            self._scroll = self._cursor - inner + 1

    def _draw(self, scr: Screen, w: int, h: int, inner: int) -> None:
        _render_screen_bg(scr, w, h)
        _render_header(scr, w, "History", "OPERATION LOG", BCYN)
        n = len(self.entries)
        scr.fill(1, BG_PANEL + box_top(w, f" Operations  ({n} entries) ",
                                       col=COL_BORD, tcol=COL_ACC2+BOLD) + RESET)
        for i in range(inner):
            abs_i = self._scroll + i
            rr    = 2 + i
            if abs_i < n:
                e    = self.entries[abs_i]
                ts   = e.get("timestamp","")[:19].replace("T"," ")
                base = Path(e.get("base","?")).name
                tot  = e.get("total_files",0)
                eid  = e.get("id","?")[:6]
                is_sel = (abs_i == self._cursor)
                line = (f"  {MUTED}{ts:<12}{RESET}"
                        f"  {BCYN+BOLD}{base:<25}{RESET}"
                        f"  {BGRN+BOLD}{tot:>4}{RESET} files"
                        f"  {MUTED}id:{eid}{RESET}")
                if is_sel:
                    scr.fill(rr, BG_SEL + SEL_FG + "▶ " + pad_to(strip(line), w-3) + RESET)
                else:
                    scr.fill(rr, BG_PANEL + line + RESET)
            else:
                scr.fill(rr, BG_PANEL + " "*w + RESET)
        scr.fill(2+inner, BG_PANEL + box_bot(w, col=COL_BORD) + RESET)
        _render_footer(scr, w, h-1, [("↑↓","navigate"),("Enter/D","detail"),("U","undo selected"),("Q/Esc","quit")])
        scr.flush()

    def _detail(self, scr: Screen, entry: dict) -> None:
        records = entry.get("records",[])
        lines = []
        for r in records:
            col  = cat_fg(r.get("category",""))
            icon = cat_icon(r.get("category",""))
            dest = Path(r.get("destination","")).parent.name
            lines.append(f"  {col}{icon}{RESET}  {col+BOLD}{r.get('filename',''):<38}{RESET}  {MUTED}→{RESET}  {col}{dest}/{RESET}")
        scroll = 0
        while True:
            scr.resize()
            w, h = scr.w, scr.h
            inner = h - 5
            _render_screen_bg(scr, w, h)
            title = f" Detail: {entry.get('id','')} · {len(records)} files "
            scr.fill(1, BG_PANEL + box_top(w, title, col=BCYN, tcol=BCYN+BOLD) + RESET)
            for i in range(inner):
                idx = scroll + i
                scr.fill(2+i, BG_PANEL + (lines[idx] if idx < len(lines) else " "*w) + RESET)
            scr.fill(2+inner, BG_PANEL + box_bot(w, col=BCYN) + RESET)
            _render_footer(scr, w, h-1, [("↑↓","scroll"),("Q/Esc","back")])
            scr.flush()
            k = read_key()
            if k in (K_UP,"k"):     scroll = max(0, scroll-1)
            elif k in (K_DOWN,"j"): scroll = min(max(0,len(lines)-inner), scroll+1)
            elif k == K_PGUP:       scroll = max(0, scroll-inner)
            elif k == K_PGDN:       scroll = min(max(0,len(lines)-inner), scroll+inner)
            elif k in (K_ESC,K_CC,"q","Q",K_ENTER): break


# ── WatchScreen ────────────────────────────────────────────────────────────────
class WatchScreen:
    def __init__(self, base: Path, dry_run: bool):
        self.base    = base
        self.dry_run = dry_run
        self._log: list[tuple[str,str,str,str]] = []  # (ts, cat, fname, dest)
        self._lock  = threading.Lock()
        self._start = time.monotonic()
        self._stop  = threading.Event()
        self._scr   = Screen()

    def add_event(self, filename: str, dest: str, category: str) -> None:
        with self._lock:
            ts = time.strftime("%H:%M:%S")
            self._log.append((ts, category, filename, dest))
            if len(self._log) > 1000:
                self._log = self._log[-1000:]

    def run_blocking(self) -> None:
        self._scr.enter()
        try:
            while not self._stop.is_set():
                self._draw()
                time.sleep(0.2)
        finally:
            self._scr.exit()

    def stop(self) -> None:
        self._stop.set()

    def _draw(self) -> None:
        scr = self._scr
        scr.resize()
        w, h = scr.w, scr.h
        _render_screen_bg(scr, w, h)

        tag = "WATCH · DRY RUN" if self.dry_run else "WATCH · LIVE"
        col = BYLW if self.dry_run else BGRN
        _render_header(scr, w, "Watch Mode", tag, col, str(self.base))

        elapsed = int(time.monotonic() - self._start)
        count   = len(self._log)
        scr.fill(1, f"  {MUTED}Uptime: {elapsed}s{RESET}  {MUTED}·{RESET}  "
                    f"{BCYN+BOLD}{count}{RESET} files processed  {MUTED}·  Ctrl+C to stop{RESET}")

        # Column header
        hdr = (f"  {MUTED+BOLD}{'TIME':<10}  {'CATEGORY':<18}  {'FILE':<40}  DESTINATION{RESET}")
        scr.fill(2, bg256(235) + pad_to(hdr, w) + RESET)

        log_h = h - 5
        scr.fill(3, BG_PANEL + box_top(w," Live Events ", col=COL_BORD, tcol=COL_ACC2+BOLD) + RESET)
        with self._lock:
            visible = self._log[-(log_h):]
        for i,(ts,cat,fname,dest) in enumerate(visible):
            col  = cat_fg(cat)
            icon = cat_icon(cat)
            line = (f"  {MUTED}{ts:<10}{RESET}  {col}{icon} {cat:<16}{RESET}"
                    f"  {col+BOLD}{truncate(fname,40)}{RESET}"
                    f"  {MUTED}→{RESET}  {col}{dest}/{RESET}")
            scr.fill(4+i, BG_PANEL + line + RESET)
        scr.fill(4+log_h, BG_PANEL + box_bot(w, col=COL_BORD) + RESET)
        _render_footer(scr, w, h-1, [("Ctrl+C","stop watching")])
        scr.flush()
