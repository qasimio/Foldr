"""
foldr.tui
~~~~~~~~~
World-class curses TUI for FOLDR v4.
Interactive preview, approval workflow, live stats.
"""
from __future__ import annotations

import curses
import curses.textpad
import os
import sys
import time
from pathlib import Path
from typing import Callable


# ── Category colour palette ───────────────────────────────────────────────────
_CAT_COLORS = [
    # (fg, bg) — will be mapped to curses colour pairs
    (curses.COLOR_CYAN,    -1),   # 1  Documents
    (curses.COLOR_GREEN,   -1),   # 2  Images
    (curses.COLOR_YELLOW,  -1),   # 3  Videos
    (curses.COLOR_MAGENTA, -1),   # 4  Audio
    (curses.COLOR_RED,     -1),   # 5  Archives
    (curses.COLOR_BLUE,    -1),   # 6  Code
    (curses.COLOR_WHITE,   -1),   # 7  Other
]

_CAT_COLOR_MAP: dict[str, int] = {
    "Documents": 1, "Text & Data": 1,
    "Images": 2, "Vector Graphics": 2,
    "Videos": 3,
    "Audio": 4, "Subtitles": 4,
    "Archives": 5, "Disk Images": 5,
    "Code": 6, "Scripts": 6, "Notebooks": 6,
    "Executables": 5,
    "Spreadsheets": 1, "Presentations": 1,
}


def _cat_color(cat: str) -> int:
    return _CAT_COLOR_MAP.get(cat, 7)


# ─────────────────────────────────────────────────────────────────────────────
# Box-drawing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _box(win, title: str = "", style: int = 0) -> None:
    win.box()
    if title:
        h, w = win.getmaxyx()
        t = f" {title} "
        x = max(2, (w - len(t)) // 2)
        try:
            win.addstr(0, x, t, curses.A_BOLD | style)
        except curses.error:
            pass


def _centre(win, row: int, text: str, attr: int = 0) -> None:
    h, w = win.getmaxyx()
    x = max(0, (w - len(text)) // 2)
    try:
        win.addstr(row, x, text, attr)
    except curses.error:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Splash screen
# ─────────────────────────────────────────────────────────────────────────────

LOGO = [
    r" _____ ___  _    ____  ____  ",
    r"|  ___|/ _ \| |  |  _ \|  _ \ ",
    r"| |_  | | | | |  | | | | |_) |",
    r"|  _| | |_| | |__| |_| |  _ < ",
    r"|_|    \___/|____|____/|_| \_\\",
]

def show_splash(stdscr) -> None:
    curses.curs_set(0)
    h, w = stdscr.getmaxyx()
    stdscr.clear()

    logo_top = max(1, h // 2 - 5)
    for i, line in enumerate(LOGO):
        x = max(0, (w - len(line)) // 2)
        try:
            stdscr.addstr(logo_top + i, x, line,
                          curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

    sub = "v4  ·  Smart File Organizer"
    _centre(stdscr, logo_top + len(LOGO) + 1, sub,
            curses.color_pair(7) | curses.A_DIM)
    _centre(stdscr, logo_top + len(LOGO) + 3, "Loading…",
            curses.color_pair(7) | curses.A_DIM)
    stdscr.refresh()
    time.sleep(0.6)


# ─────────────────────────────────────────────────────────────────────────────
# Preview TUI  (the main interactive screen)
# ─────────────────────────────────────────────────────────────────────────────

class PreviewTUI:
    """
    Full-screen interactive preview before executing file moves.

    Layout:
    ┌────────────── FOLDR ──────────────┐
    │ Header: path, mode flags          │
    ├─ Preview ────────────────────────┤
    │ Scrollable list of planned moves  │
    ├─ Stats ───────────────────────────┤
    │ Category bar chart                │
    ├─ Controls ────────────────────────┤
    │ [Y] Confirm  [N] Cancel  [?] Help │
    └───────────────────────────────────┘
    """

    def __init__(self, stdscr, actions: list[str], records: list,
                 base: Path, dry_run: bool):
        self.stdscr   = stdscr
        self.actions  = actions
        self.records  = records
        self.base     = base
        self.dry_run  = dry_run
        self.scroll   = 0
        self.selected = 0
        self.confirmed: bool | None = None

        # Build category counts from records
        self.cat_counts: dict[str, int] = {}
        for r in records:
            self.cat_counts[r.category] = self.cat_counts.get(r.category, 0) + 1

    # ── rendering ─────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        # Zones
        header_h = 3
        footer_h = 3
        stats_h  = min(8, max(4, len(self.cat_counts) + 2))
        list_h   = max(4, h - header_h - stats_h - footer_h)

        self._draw_header(0, w, header_h)
        self._draw_list(header_h, w, list_h)
        self._draw_stats(header_h + list_h, w, stats_h)
        self._draw_footer(h - footer_h, w, footer_h)

        self.stdscr.refresh()

    def _draw_header(self, top: int, w: int, h: int) -> None:
        win = curses.newwin(h, w, top, 0)
        win.bkgd(" ", curses.color_pair(1))
        mode_tag = " DRY-RUN " if self.dry_run else " LIVE "
        mode_col = curses.color_pair(3) if self.dry_run else curses.color_pair(2)

        title = "  FOLDR  —  Interactive Preview"
        try:
            win.addstr(0, 0, " " * w, curses.color_pair(1) | curses.A_REVERSE)
            win.addstr(0, 2, title, curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
            win.addstr(0, w - len(mode_tag) - 2, mode_tag,
                       mode_col | curses.A_BOLD | curses.A_REVERSE)
            path_str = f"  📁  {self.base}"[:w - 2]
            win.addstr(1, 0, path_str, curses.color_pair(7))
            count_str = f"  {len(self.actions)} moves planned  ·  {len(self.cat_counts)} categories"
            win.addstr(2, 0, count_str, curses.color_pair(7) | curses.A_DIM)
        except curses.error:
            pass
        win.noutrefresh()

    def _draw_list(self, top: int, w: int, h: int) -> None:
        inner_h = h - 2
        inner_w = w - 2
        win = curses.newwin(h, w, top, 0)
        _box(win, "Planned Moves  ↑↓ scroll", curses.color_pair(1))

        visible = self.actions[self.scroll: self.scroll + inner_h]

        for i, action in enumerate(visible):
            abs_i = self.scroll + i
            row = i + 1

            # Parse: "filename → dest_folder/"
            if " → " in action:
                parts = action.split(" → ", 1)
                fname = parts[0].strip()
                dest  = parts[1].strip()
            else:
                fname = action
                dest  = ""

            # Find category for colour
            cat = "Other"
            for r in self.records:
                if r.filename in fname:
                    cat = r.category
                    break

            is_sel = (abs_i == self.selected)
            attr = curses.A_REVERSE if is_sel else 0
            col  = curses.color_pair(_cat_color(cat))

            line = f"  {fname:<35}  →  {dest}"
            line = line[:inner_w]

            try:
                if is_sel:
                    win.addstr(row, 1, " " * inner_w, attr)
                win.addstr(row, 1, f"  ", col | attr)
                win.addstr(row, 3, fname[:30], col | curses.A_BOLD | attr)
                arrow_x = 35
                win.addstr(row, arrow_x, "  →  ", curses.color_pair(7) | attr)
                win.addstr(row, arrow_x + 5, dest[:inner_w - arrow_x - 6],
                           curses.color_pair(7) | curses.A_DIM | attr)
            except curses.error:
                pass

        # Scroll indicator
        total = len(self.actions)
        if total > inner_h:
            pct = int(self.scroll / max(1, total - inner_h) * (inner_h - 1))
            try:
                win.addstr(1 + pct, w - 1, "█", curses.color_pair(1))
            except curses.error:
                pass

        win.noutrefresh()

    def _draw_stats(self, top: int, w: int, h: int) -> None:
        win = curses.newwin(h, w, top, 0)
        _box(win, "Category Summary", curses.color_pair(1))

        inner_w = w - 4
        total = max(1, sum(self.cat_counts.values()))
        sorted_cats = sorted(self.cat_counts.items(), key=lambda x: -x[1])

        bar_area = max(10, inner_w - 25)
        row = 1
        for cat, cnt in sorted_cats[:h - 2]:
            bar_len = int(cnt / total * bar_area)
            bar = "█" * bar_len + "░" * (bar_area - bar_len)
            col = curses.color_pair(_cat_color(cat))
            label = f"{cat:<18}"[:18]
            count = f"{cnt:>4}"
            pct   = f" {cnt/total*100:4.1f}%"
            try:
                win.addstr(row, 2, label, col | curses.A_BOLD)
                win.addstr(row, 21, bar[:bar_area], col)
                win.addstr(row, 21 + bar_area + 1, count + pct,
                           curses.color_pair(7) | curses.A_DIM)
            except curses.error:
                pass
            row += 1
            if row >= h - 1:
                break

        win.noutrefresh()

    def _draw_footer(self, top: int, w: int, h: int) -> None:
        win = curses.newwin(h, w, top, 0)
        win.bkgd(" ", curses.color_pair(1))
        _box(win)

        keys = [
            ("[Y] Confirm", curses.color_pair(2) | curses.A_BOLD),
            ("  [N] Cancel", curses.color_pair(5) | curses.A_BOLD),
            ("  [↑↓] Scroll", curses.color_pair(7)),
            ("  [↵] Select", curses.color_pair(7)),
            ("  [?] Help", curses.color_pair(4)),
        ]
        x = 2
        for text, attr in keys:
            try:
                win.addstr(1, x, text, attr)
                x += len(text)
            except curses.error:
                break

        win.noutrefresh()

    # ── input loop ────────────────────────────────────────────────────────────

    def run(self) -> bool:
        """Returns True if user confirmed, False if cancelled."""
        curses.curs_set(0)
        while True:
            self._draw()
            curses.doupdate()

            key = self.stdscr.getch()

            if key in (ord("y"), ord("Y")):
                self.confirmed = True
                return True
            elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):  # 27=ESC
                self.confirmed = False
                return False
            elif key == curses.KEY_UP:
                if self.selected > 0:
                    self.selected -= 1
                    h, w = self.stdscr.getmaxyx()
                    list_h = max(4, h - 3 - min(8, max(4, len(self.cat_counts) + 2)) - 3)
                    inner_h = list_h - 2
                    if self.selected < self.scroll:
                        self.scroll = self.selected
            elif key == curses.KEY_DOWN:
                if self.selected < len(self.actions) - 1:
                    self.selected += 1
                    h, w = self.stdscr.getmaxyx()
                    list_h = max(4, h - 3 - min(8, max(4, len(self.cat_counts) + 2)) - 3)
                    inner_h = list_h - 2
                    if self.selected >= self.scroll + inner_h:
                        self.scroll = self.selected - inner_h + 1
            elif key == curses.KEY_PPAGE:
                h, w = self.stdscr.getmaxyx()
                list_h = max(4, h - 3 - min(8, max(4, len(self.cat_counts) + 2)) - 3)
                inner_h = list_h - 2
                self.scroll = max(0, self.scroll - inner_h)
                self.selected = max(0, self.selected - inner_h)
            elif key == curses.KEY_NPAGE:
                h, w = self.stdscr.getmaxyx()
                list_h = max(4, h - 3 - min(8, max(4, len(self.cat_counts) + 2)) - 3)
                inner_h = list_h - 2
                self.scroll = min(max(0, len(self.actions) - inner_h),
                                  self.scroll + inner_h)
                self.selected = min(len(self.actions) - 1, self.selected + inner_h)
            elif key == ord("?"):
                self._show_help()

    def _show_help(self) -> None:
        h, w = self.stdscr.getmaxyx()
        hh, hw = min(20, h - 4), min(60, w - 4)
        hy, hx = (h - hh) // 2, (w - hw) // 2
        popup = curses.newwin(hh, hw, hy, hx)
        _box(popup, " Help ", curses.color_pair(4) | curses.A_BOLD)

        lines = [
            "",
            "  ↑ / ↓       Scroll move list",
            "  PgUp/PgDn   Fast scroll",
            "",
            "  Y           Confirm and execute moves",
            "  N / ESC     Cancel — no files touched",
            "",
            "  Colours:",
            "  ■ Cyan   = Documents / Text",
            "  ■ Green  = Images",
            "  ■ Yellow = Videos",
            "  ■ Magenta= Audio",
            "  ■ Red    = Archives / Exec",
            "  ■ Blue   = Code / Scripts",
            "",
            "  Press any key to close",
        ]
        for i, line in enumerate(lines[:hh - 2]):
            try:
                popup.addstr(i + 1, 1, line[:hw - 2], curses.color_pair(7))
            except curses.error:
                pass
        popup.refresh()
        self.stdscr.getch()


# ─────────────────────────────────────────────────────────────────────────────
# History viewer
# ─────────────────────────────────────────────────────────────────────────────

class HistoryTUI:
    def __init__(self, stdscr, entries: list[dict]):
        self.stdscr  = stdscr
        self.entries = entries
        self.scroll  = 0
        self.sel     = 0

    def _draw(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        # Header
        hdr = curses.newwin(2, w, 0, 0)
        hdr.bkgd(" ", curses.color_pair(1) | curses.A_REVERSE)
        try:
            hdr.addstr(0, 2, "  FOLDR  —  History", curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
            hdr.addstr(1, 2, f"{len(self.entries)} operations logged", curses.color_pair(7))
        except curses.error:
            pass
        hdr.noutrefresh()

        # List
        list_win = curses.newwin(h - 4, w, 2, 0)
        _box(list_win, "Operations  (newest first)", curses.color_pair(1))

        inner_h = h - 6
        inner_w = w - 4
        visible = self.entries[self.scroll: self.scroll + inner_h]

        for i, entry in enumerate(visible):
            abs_i = self.scroll + i
            is_sel = abs_i == self.sel
            attr = curses.A_REVERSE if is_sel else 0

            ts = entry.get("timestamp", "")[:19].replace("T", " ")
            base_name = Path(entry.get("base", "?")).name
            total = entry.get("total_files", 0)
            eid   = entry.get("id", "?")[:6]

            line = f"  {ts}   {base_name:<20}  {total:>4} files   id:{eid}"
            line = line[:inner_w]
            try:
                list_win.addstr(i + 1, 1, " " * inner_w, attr)
                list_win.addstr(i + 1, 1, line, curses.color_pair(1) | attr)
            except curses.error:
                pass

        list_win.noutrefresh()

        # Footer
        ftr = curses.newwin(2, w, h - 2, 0)
        _box(ftr)
        try:
            ftr.addstr(0, 2,
                       "[↑↓] Navigate   [↵] View detail   [U] Undo selected   [Q] Back",
                       curses.color_pair(7))
        except curses.error:
            pass
        ftr.noutrefresh()

        curses.doupdate()

    def run(self) -> tuple[str | None, str | None]:
        """Return (action, entry_id)  action in {'undo', None}"""
        curses.curs_set(0)
        while True:
            self._draw()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return None, None
            elif key == curses.KEY_UP and self.sel > 0:
                self.sel -= 1
                if self.sel < self.scroll:
                    self.scroll = self.sel
            elif key == curses.KEY_DOWN and self.sel < len(self.entries) - 1:
                self.sel += 1
                h, _ = self.stdscr.getmaxyx()
                inner_h = h - 6
                if self.sel >= self.scroll + inner_h:
                    self.scroll = self.sel - inner_h + 1
            elif key in (ord("u"), ord("U")) and self.entries:
                eid = self.entries[self.sel].get("id")
                return "undo", eid
            elif key in (10, 13) and self.entries:
                self._detail_view(self.entries[self.sel])
        return None, None

    def _detail_view(self, entry: dict) -> None:
        h, w = self.stdscr.getmaxyx()
        win = curses.newwin(h - 4, w - 4, 2, 2)
        _box(win, f" Operation {entry.get('id', '')} ", curses.color_pair(4) | curses.A_BOLD)

        inner_h = h - 8
        records = entry.get("records", [])
        scroll = 0

        while True:
            win.erase()
            _box(win, f" Operation {entry.get('id', '')}  —  {len(records)} files ", curses.color_pair(4) | curses.A_BOLD)

            ts   = entry.get("timestamp", "")[:19].replace("T", " ")
            base = entry.get("base", "")
            try:
                win.addstr(1, 2, f"Time: {ts}   Base: {base}"[:w - 8], curses.color_pair(7))
            except curses.error:
                pass

            visible = records[scroll: scroll + inner_h - 2]
            for i, r in enumerate(visible):
                src  = Path(r.get("source", "")).name
                dest = Path(r.get("destination", "")).parent.name
                cat  = r.get("category", "")
                col  = curses.color_pair(_cat_color(cat))
                line = f"  {src:<35}  →  {dest}/"
                try:
                    win.addstr(i + 3, 2, line[:w - 8], col)
                except curses.error:
                    pass

            try:
                win.addstr(h - 7, 2, "[↑↓] Scroll  [Q/ESC] Close", curses.color_pair(7) | curses.A_DIM)
            except curses.error:
                pass
            win.refresh()

            key = win.getch()
            if key in (ord("q"), ord("Q"), 27, 10, 13):
                break
            elif key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max(0, len(records) - inner_h + 2), scroll + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Confirmation dialog  (simple y/n)
# ─────────────────────────────────────────────────────────────────────────────

def confirm_dialog(stdscr, title: str, body: str,
                   yes_label: str = "Yes", no_label: str = "No") -> bool:
    h, w = stdscr.getmaxyx()
    lines = body.split("\n")
    dh = len(lines) + 6
    dw = min(w - 4, max(50, max(len(l) for l in lines) + 6))
    dy = (h - dh) // 2
    dx = (w - dw) // 2

    win = curses.newwin(dh, dw, dy, dx)
    _box(win, title, curses.color_pair(4) | curses.A_BOLD)

    for i, line in enumerate(lines):
        try:
            win.addstr(i + 2, 3, line[:dw - 6], curses.color_pair(7))
        except curses.error:
            pass

    sel = 0  # 0=yes, 1=no
    while True:
        y_attr = curses.color_pair(2) | curses.A_BOLD | (curses.A_REVERSE if sel == 0 else 0)
        n_attr = curses.color_pair(5) | curses.A_BOLD | (curses.A_REVERSE if sel == 1 else 0)
        btn_y = dh - 2
        try:
            win.addstr(btn_y, 4,  f" {yes_label} ", y_attr)
            win.addstr(btn_y, 4 + len(yes_label) + 4, f" {no_label} ", n_attr)
        except curses.error:
            pass
        win.refresh()

        key = win.getch()
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("\t")):
            sel ^= 1
        elif key in (10, 13):
            return sel == 0
        elif key in (ord("y"), ord("Y")):
            return True
        elif key in (ord("n"), ord("N"), 27):
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Progress display (used during actual execution)
# ─────────────────────────────────────────────────────────────────────────────

class ProgressDisplay:
    def __init__(self, stdscr, total: int, base: Path, dry_run: bool):
        self.stdscr  = stdscr
        self.total   = total
        self.base    = base
        self.dry_run = dry_run
        self.done    = 0
        self.log: list[str] = []
        self._start  = time.time()

    def update(self, filename: str, dest: str, category: str) -> None:
        self.done += 1
        self.log.append(f"{filename}  →  {dest}")
        self._draw()

    def _draw(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        # Title bar
        try:
            tag = " DRY-RUN " if self.dry_run else " RUNNING "
            col = curses.color_pair(3) if self.dry_run else curses.color_pair(2)
            self.stdscr.addstr(0, 0, " " * w, curses.A_REVERSE)
            self.stdscr.addstr(0, 2, "  FOLDR  —  Organizing", curses.A_BOLD | curses.A_REVERSE)
            self.stdscr.addstr(0, w - len(tag) - 2, tag, col | curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass

        # Progress bar
        pct = self.done / max(1, self.total)
        bar_w = w - 14
        filled = int(pct * bar_w)
        bar = "█" * filled + "░" * (bar_w - filled)
        elapsed = time.time() - self._start
        try:
            self.stdscr.addstr(2, 2, f"Progress: {self.done}/{self.total}  ({pct*100:.0f}%)  {elapsed:.1f}s",
                               curses.color_pair(7))
            self.stdscr.addstr(3, 2, f"[{bar}]", curses.color_pair(2))
        except curses.error:
            pass

        # Scrolling log
        log_top = 5
        log_h   = h - log_top - 2
        visible = self.log[-(log_h):]
        for i, entry in enumerate(visible):
            try:
                self.stdscr.addstr(log_top + i, 4, entry[:w - 6],
                                   curses.color_pair(7) | curses.A_DIM)
            except curses.error:
                pass

        self.stdscr.refresh()

    def finish(self) -> None:
        self._draw()
        time.sleep(0.3)


# ─────────────────────────────────────────────────────────────────────────────
# Public init helper (called once before any TUI window)
# ─────────────────────────────────────────────────────────────────────────────

def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    for pair_id, (fg, bg) in enumerate(_CAT_COLORS, start=1):
        try:
            curses.init_pair(pair_id, fg, bg)
        except curses.error:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Watch mode live display
# ─────────────────────────────────────────────────────────────────────────────

class WatchDisplay:
    def __init__(self, stdscr, base: Path, dry_run: bool):
        self.stdscr  = stdscr
        self.base    = base
        self.dry_run = dry_run
        self.log: list[tuple[str, str, str]] = []  # (time, file, dest)
        self._start  = time.time()

    def add_event(self, filename: str, dest: str, category: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log.append((ts, filename, dest))
        if len(self.log) > 500:
            self.log = self.log[-500:]
        self.draw()

    def draw(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        # Header
        mode = " DRY-RUN " if self.dry_run else "  LIVE   "
        col  = curses.color_pair(3) if self.dry_run else curses.color_pair(2)
        try:
            self.stdscr.addstr(0, 0, " " * w, curses.A_REVERSE)
            self.stdscr.addstr(0, 2, "  FOLDR WATCH  ", curses.A_BOLD | curses.A_REVERSE)
            self.stdscr.addstr(0, w - len(mode) - 2, mode, col | curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass

        path_str = f"  Watching: {self.base}"[:w - 2]
        elapsed  = f"  Uptime: {int(time.time() - self._start)}s"
        try:
            self.stdscr.addstr(1, 0, path_str, curses.color_pair(1))
            self.stdscr.addstr(2, 0, elapsed, curses.color_pair(7) | curses.A_DIM)
        except curses.error:
            pass

        # Log area
        log_top = 4
        log_h   = h - log_top - 3
        visible = self.log[-(log_h):]

        hdr = f"  {'TIME':<10}{'FILE':<35}DESTINATION"
        try:
            self.stdscr.addstr(log_top - 1, 0, hdr[:w], curses.color_pair(1) | curses.A_BOLD)
        except curses.error:
            pass

        for i, (ts, fname, dest) in enumerate(visible):
            row = log_top + i
            line = f"  {ts:<10}{fname:<35}{dest}"
            try:
                self.stdscr.addstr(row, 0, line[:w], curses.color_pair(7))
            except curses.error:
                pass

        count = len(self.log)
        try:
            self.stdscr.addstr(h - 2, 2, f"{count} file(s) organized  ·  Ctrl+C to stop",
                               curses.color_pair(7) | curses.A_DIM)
        except curses.error:
            pass

        self.stdscr.refresh()