"""
foldr.tui
~~~~~~~~~
FOLDR v4 — World-class TUI screens.

All screens share:
  - Double-buffered, flicker-free rendering via Screen
  - Raw key input via keys.py
  - Consistent header/footer chrome
  - Full approval gates before any destructive action
"""
from __future__ import annotations
import sys, time, threading, signal
from pathlib import Path

from foldr.screen  import Screen
from foldr.keys    import (read_key, UP, DOWN, LEFT, RIGHT,
                            ENTER, ESC, TAB, BTAB, PGUP, PGDN,
                            HOME, END, BS, CTRL_C, CTRL_D)
from foldr.widgets import (
    draw_logo, draw_header, draw_footer, draw_box, draw_toast,
    confirm_dialog, category_bars, progress_bar,
    Spinner, ScrollList, ACCENT, ACCENT2, SUCCESS, WARN, ERROR, MUTED,
    HDR_BG, HDR_FG, SEL_BG, SEL_FG, BOX_COL, TITLE_COL,
    c256, BOLD, DIM, RESET, BCYAN, CYAN, BGREEN, BRED, BYELLOW,
    BBLUE, BWHITE, BMAGENTA, BBLACK, WHITE,
)
from foldr.ansi import (
    HIDE_CURSOR, SHOW_CURSOR, ALT_ENTER, ALT_EXIT, CLEAR,
    cat_col, cat_icon, term_size, strip_ansi, pad, rgb,
)


# ─────────────────────────────────────────────────────────────────────────────
# Splash  (shown for ~0.8s on startup when TTY detected)
# ─────────────────────────────────────────────────────────────────────────────

def splash(duration: float = 0.9) -> None:
    scr = Screen()
    scr.enter_alt()
    try:
        h, w = term_size()
        scr.clear_back()

        # Animate logo fade-in
        from foldr.widgets import LOGO_LINES, LOGO_SUB
        from foldr.ansi    import c256

        logo_h    = len(LOGO_LINES) + 4
        logo_top  = max(1, (h - logo_h - 3) // 2)

        for frame in range(8):
            scr.clear_back()
            # Background gradient row
            for r in range(h):
                intensity = max(0, 232 + int(r / h * 4))
                scr.put(r, 0, c256(intensity, bg=True) + " " * w + RESET)

            # Logo lines with staggered reveal
            from foldr.widgets import LOGO_LINES
            for i, line in enumerate(LOGO_LINES):
                if i <= frame:
                    vis = strip_ansi(line)
                    col = max(0, (w - len(vis)) // 2)
                    scr.put(logo_top + i, col, line)

            # Tagline
            if frame >= 5:
                sub = f"  {MUTED}v4  ·  Smart File Organizer{RESET}"
                sv  = strip_ansi(sub)
                scr.put(logo_top + len(LOGO_LINES) + 1,
                        max(0, (w - len(sv)) // 2), sub)

            # Loading dots
            dots = "●" * (frame % 4 + 1) + "○" * (3 - frame % 4)
            ld   = f"{BCYAN}{dots}{RESET}"
            scr.put(logo_top + logo_h, max(0, (w - 3) // 2), ld)

            scr.flush()
            time.sleep(duration / 8)

        time.sleep(0.15)
    finally:
        scr.exit_alt()


# ─────────────────────────────────────────────────────────────────────────────
# Preview & Approval Screen
# ─────────────────────────────────────────────────────────────────────────────

class PreviewScreen:
    """
    Interactive full-screen preview of planned file moves.
    User MUST explicitly confirm before anything runs.

    Layout
    ──────
    ┌─ Header bar ─────────────────────────────────────────────────────┐
    │ path info + mode tag                                              │
    ├─ Move list (scrollable) ─────────────────────────────────────────┤
    │ filename → dest/  [category colour]                              │
    ├─ Stats panel ────────────────────────────────────────────────────┤
    │ category bar chart + summary numbers                              │
    ├─ Approval prompt ────────────────────────────────────────────────┤
    │ [Y] Execute  [N] Cancel  [↑↓] Scroll  [?] Help                  │
    └──────────────────────────────────────────────────────────────────┘
    """

    def __init__(self, records: list, base: Path, dry_run: bool):
        self.records  = records
        self.base     = base
        self.dry_run  = dry_run
        self.scr      = Screen()

        # Build display items
        self.items: list[tuple[str, str, str]] = []  # (filename, dest_folder, category)
        self.cat_counts: dict[str, int] = {}
        for r in records:
            dest_folder = Path(r.destination).parent.name
            self.items.append((r.filename, dest_folder, r.category))
            self.cat_counts[r.category] = self.cat_counts.get(r.category, 0) + 1

        # Formatted display strings
        self._fmt_items = self._format_items()

    def _format_items(self) -> list[str]:
        out = []
        for fname, dest, cat in self.items:
            col  = cat_col(cat)
            icon = cat_icon(cat)
            out.append(
                f"{col}{BOLD}{fname:<38}{RESET}"
                f"  {MUTED}→{RESET}  "
                f"{col}{icon} {dest}/{RESET}"
                f"  {MUTED}{cat}{RESET}"
            )
        return out

    def run(self) -> bool:
        """Enter alt screen, show preview, return True if confirmed."""
        self.scr.enter_alt()
        try:
            return self._event_loop()
        finally:
            self.scr.exit_alt()

    def _layout(self) -> dict:
        h, w = term_size()
        stats_h  = min(len(self.cat_counts) + 4, 12)
        footer_h = 3
        header_h = 3
        list_h   = max(5, h - header_h - stats_h - footer_h - 2)
        return dict(h=h, w=w, header_h=header_h,
                    list_top=header_h + 1,
                    list_h=list_h,
                    stats_top=header_h + 1 + list_h + 1,
                    stats_h=stats_h,
                    footer_row=h - footer_h)

    def _draw(self, lst: ScrollList) -> None:
        L = self._layout()
        h, w = L["h"], L["w"]
        self.scr.clear_back()

        # ── background ──────────────────────────────────────────────────────
        for r in range(h):
            self.scr.put(r, 0, c256(233, bg=True) + " " * w + RESET)

        # ── header ──────────────────────────────────────────────────────────
        mode_tag = "DRY-RUN — NO FILES WILL MOVE" if self.dry_run else "PREVIEW — APPROVAL REQUIRED"
        mode_col = BYELLOW if self.dry_run else BCYAN
        draw_header(self.scr, "Interactive Preview", mode_tag, mode_col,
                    path=str(self.base))

        # ── move list ───────────────────────────────────────────────────────
        title = f"Planned Moves  ({len(self.items)} files)"
        lst.row    = L["list_top"]
        lst.height = L["list_h"]
        lst.width  = w
        lst.title  = title
        lst.draw(self.scr)

        # ── selected item detail ─────────────────────────────────────────────
        if self.items:
            idx = lst.cursor
            fname, dest, cat = self.items[idx]
            col  = cat_col(cat)
            icon = cat_icon(cat)
            detail = (
                f"  {MUTED}Selected:{RESET}  "
                f"{col}{BOLD}{icon} {fname}{RESET}"
                f"  {MUTED}→{RESET}  "
                f"{col}{dest}/{RESET}"
                f"  {MUTED}[{cat}]{RESET}"
            )
            self.scr.put(L["list_top"] + L["list_h"], 0,
                         c256(234, bg=True) + " " * w + RESET)
            self.scr.put(L["list_top"] + L["list_h"], 0, detail)

        # ── stats panel ─────────────────────────────────────────────────────
        draw_box(self.scr, L["stats_top"], 0, L["stats_h"], w,
                 title=" Category Breakdown ",
                 border_col=BOX_COL, bg=c256(234, bg=True))

        bars = category_bars(self.cat_counts, bar_w=max(10, w // 3))
        for i, bar_line in enumerate(bars[:L["stats_h"] - 2]):
            self.scr.put(L["stats_top"] + 1 + i, 2, bar_line)

        # Summary numbers (right side of stats)
        total   = len(self.items)
        n_cats  = len(self.cat_counts)
        summary = (
            f"  {BCYAN}{BOLD}{total}{RESET} files  "
            f"{MUTED}·{RESET}  "
            f"{BCYAN}{BOLD}{n_cats}{RESET} categories"
        )
        self.scr.put(L["stats_top"] + 1, w - len(strip_ansi(summary)) - 4, summary)

        # ── footer ──────────────────────────────────────────────────────────
        if self.dry_run:
            keys = [("↑↓", "scroll"), ("PgUp/Dn", "fast scroll"),
                    ("Q/Esc", "exit preview")]
        else:
            keys = [("Y", "EXECUTE"), ("N/Esc", "cancel"),
                    ("↑↓", "scroll"), ("PgUp/Dn", "fast"), ("?", "help")]
        draw_footer(self.scr, L["footer_row"], keys)

        # ── dry run reminder banner ──────────────────────────────────────────
        if self.dry_run:
            banner = (
                f"  {BYELLOW}{BOLD}● DRY RUN{RESET}  "
                f"{BYELLOW}No files will be moved. "
                f"This is a preview only.{RESET}"
            )
            br = L["footer_row"] - 1
            self.scr.put(br, 0, c256(58, bg=True) + " " * w + RESET)
            self.scr.put(br, 2, banner)

        self.scr.flush()

    def _event_loop(self) -> bool:
        L     = self._layout()
        lst   = ScrollList(self._fmt_items, L["list_top"], 0,
                           L["list_h"], L["list_top"],
                           border_col=BOX_COL)

        while True:
            # Handle resize
            if self.scr.resize():
                L   = self._layout()
                lst = ScrollList(self._fmt_items, L["list_top"], 0,
                                 L["list_h"], L["list_top"],
                                 border_col=BOX_COL)

            self._draw(lst)

            k = read_key()

            if k in (UP, "k"):      lst.move(-1)
            elif k in (DOWN, "j"):  lst.move(1)
            elif k == PGUP:         lst.page(-1)
            elif k == PGDN:         lst.page(1)
            elif k == HOME:         lst.cursor = 0; lst.scroll = 0
            elif k == END:
                lst.cursor = max(0, len(self._fmt_items) - 1)
                lst.scroll = max(0, len(self._fmt_items) - lst._inner_h)

            elif k in ("y", "Y") and not self.dry_run:
                # Show confirmation dialog
                confirmed = confirm_dialog(
                    self.scr,
                    title=" ⚡ Execute File Moves ",
                    body=[
                        f"{BWHITE}This will move {BCYAN}{BOLD}{len(self.items)}{RESET}{BWHITE} files{RESET}",
                        f"{BWHITE}from  {BCYAN}{self.base.name}/{RESET}",
                        f"{BWHITE}into  {len(self.cat_counts)} category folders.{RESET}",
                        "",
                        f"{MUTED}This operation can be undone with:{RESET}",
                        f"  {BCYAN}foldr undo{RESET}",
                    ],
                    yes=" ✓ Execute ",
                    no=" ✗ Cancel ",
                    danger=False,
                )
                return confirmed

            elif k in ("n", "N", ESC, CTRL_C, "q", "Q"):
                return False

            elif k == "?" and not self.dry_run:
                self._show_help()

    def _show_help(self) -> None:
        h, w = term_size()
        box_w = min(60, w - 4)
        box_h = 18
        top   = (h - box_h) // 2
        left  = (w - box_w) // 2

        lines = [
            f"  {BCYAN}{BOLD}Keyboard Shortcuts{RESET}",
            "",
            f"  {BYELLOW}↑ / k{RESET}        Scroll up one file",
            f"  {BYELLOW}↓ / j{RESET}        Scroll down one file",
            f"  {BYELLOW}PgUp / PgDn{RESET}  Fast scroll (page)",
            f"  {BYELLOW}Home / End{RESET}   Jump to top / bottom",
            "",
            f"  {BGREEN}Y{RESET}            Execute all moves (shows confirm dialog)",
            f"  {BRED}N / Esc{RESET}      Cancel — no files touched",
            "",
            f"  {MUTED}Colours indicate file category:{RESET}",
            f"  {BCYAN}■{RESET} Cyan=Docs  {BGREEN}■{RESET} Green=Images  {BYELLOW}■{RESET} Yellow=Video",
            f"  {BMAGENTA}■{RESET} Magenta=Audio  {BRED}■{RESET} Red=Archives  {BBLUE}■{RESET} Blue=Code",
            "",
            f"  {MUTED}Press any key to close{RESET}",
        ]

        draw_box(self.scr, top, left, box_h, box_w,
                 title=" Help ", border_col=BCYAN,
                 bg=c256(234, bg=True))
        for i, line in enumerate(lines[:box_h - 2]):
            self.scr.put(top + 1 + i, left + 2, line)
        self.scr.flush()
        read_key()


# ─────────────────────────────────────────────────────────────────────────────
# Execution progress screen
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionScreen:
    """Live progress display during actual file moves."""

    def __init__(self, total: int, base: Path, dry_run: bool):
        self.total   = total
        self.base    = base
        self.dry_run = dry_run
        self.done    = 0
        self.current = ""
        self.log: list[tuple[str, str, str]] = []  # (cat, fname, dest)
        self.scr     = Screen()
        self._lock   = threading.Lock()
        self._start  = time.monotonic()
        self._active = False

    def __enter__(self):
        self.scr.enter_alt()
        self._active = True
        self._draw()
        return self

    def __exit__(self, *_):
        self._active = False
        self.scr.exit_alt()

    def update(self, filename: str, dest: str, category: str) -> None:
        with self._lock:
            self.done    += 1
            self.current  = filename
            self.log.append((category, filename, dest))
        self._draw()

    def _draw(self) -> None:
        h, w = term_size()
        elapsed = time.monotonic() - self._start
        pct     = self.done / max(1, self.total)

        self.scr.clear_back()

        # Background
        for r in range(h):
            self.scr.put(r, 0, c256(233, bg=True) + " " * w + RESET)

        # Header
        mode_tag = "EXECUTING — MOVING FILES"
        draw_header(self.scr, "File Organizer", mode_tag, BGREEN,
                    path=str(self.base))

        # Big progress section
        box_top = 4
        draw_box(self.scr, box_top, 2, 7, w - 4,
                 title=" Progress ", border_col=BGREEN,
                 bg=c256(234, bg=True))

        # Progress bar
        bar_w  = w - 16
        pbar   = progress_bar(pct, width=bar_w, col_fill=BGREEN)
        self.scr.put(box_top + 2, 4, pbar)

        # Stats line
        rate   = self.done / max(0.01, elapsed)
        remain = max(0, (self.total - self.done) / max(0.01, rate))
        stats  = (
            f"  {BCYAN}{BOLD}{self.done}{RESET}/{BCYAN}{self.total}{RESET}  files  "
            f"{MUTED}·{RESET}  "
            f"{BGREEN}{BOLD}{pct*100:.0f}%{RESET}  "
            f"{MUTED}·{RESET}  "
            f"{BYELLOW}{elapsed:.1f}s{RESET} elapsed  "
            f"{MUTED}·{RESET}  "
            f"{MUTED}~{remain:.0f}s remaining{RESET}"
        )
        self.scr.put(box_top + 4, 4, stats)

        # Current file
        if self.current:
            cur = f"  {MUTED}▸{RESET}  {BCYAN}{self.current}{RESET}"
            self.scr.put(box_top + 5, 4, cur)

        # Live log (recent moves)
        log_top = box_top + 9
        log_h   = h - log_top - 2
        draw_box(self.scr, log_top - 1, 2, log_h + 2, w - 4,
                 title=" Recent Moves ", border_col=BOX_COL,
                 bg=c256(233, bg=True))

        visible = self.log[-(log_h):]
        for i, (cat, fname, dest) in enumerate(visible):
            col  = cat_col(cat)
            icon = cat_icon(cat)
            line = (
                f"  {col}{icon}{RESET}  "
                f"{col}{BOLD}{fname:<38}{RESET}  "
                f"{MUTED}→{RESET}  {col}{dest}/{RESET}"
            )
            self.scr.put(log_top + i, 4, line)

        self.scr.flush()


# ─────────────────────────────────────────────────────────────────────────────
# History browser
# ─────────────────────────────────────────────────────────────────────────────

class HistoryScreen:
    """Browse and manage operation history."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.scr     = Screen()

    def run(self) -> tuple[str | None, str | None]:
        """Returns (action, entry_id).  action = 'undo' or None."""
        self.scr.enter_alt()
        try:
            return self._event_loop()
        finally:
            self.scr.exit_alt()

    def _fmt_entries(self) -> list[str]:
        rows = []
        for e in self.entries:
            ts    = e.get("timestamp", "")[:19].replace("T", " ")
            base  = Path(e.get("base", "?")).name
            total = e.get("total_files", 0)
            eid   = e.get("id", "?")[:6]
            rows.append(
                f"{MUTED}{ts}{RESET}  "
                f"{BCYAN}{BOLD}{base:<25}{RESET}  "
                f"{BGREEN}{total:>4}{RESET} files  "
                f"{MUTED}id:{eid}{RESET}"
            )
        return rows

    def _event_loop(self) -> tuple[str | None, str | None]:
        fmt   = self._fmt_entries()
        h, w  = term_size()
        lst   = ScrollList(fmt, 3, 0, h - 6, w,
                           border_col=BOX_COL,
                           title=f" Operation History  ({len(self.entries)} entries) ")

        while True:
            if self.scr.resize():
                h, w = term_size()
                lst  = ScrollList(fmt, 3, 0, h - 6, w,
                                  border_col=BOX_COL,
                                  title=f" Operation History  ({len(self.entries)} entries) ")

            self._draw(lst)

            k = read_key()
            if k in (UP, "k"):       lst.move(-1)
            elif k in (DOWN, "j"):   lst.move(1)
            elif k == PGUP:          lst.page(-1)
            elif k == PGDN:          lst.page(1)
            elif k in (ESC, CTRL_C, "q", "Q"):
                return None, None
            elif k in (ENTER, "d", "D") and self.entries:
                self._detail(self.entries[lst.cursor])
            elif k in ("u", "U") and self.entries:
                eid = self.entries[lst.cursor].get("id")
                confirmed = confirm_dialog(
                    self.scr,
                    title=" ↩ Undo Operation ",
                    body=[
                        f"{BWHITE}Restore {BCYAN}{BOLD}{self.entries[lst.cursor].get('total_files',0)}{RESET}{BWHITE} files{RESET}",
                        f"{BWHITE}from operation {BCYAN}{eid}{RESET}",
                        "",
                        f"{MUTED}Files will be moved back to their original locations.{RESET}",
                    ],
                    yes=" ↩ Undo ",
                    no=" ✗ Cancel ",
                    danger=True,
                )
                if confirmed:
                    return "undo", eid

        return None, None

    def _draw(self, lst: ScrollList) -> None:
        h, w = term_size()
        self.scr.clear_back()
        for r in range(h):
            self.scr.put(r, 0, c256(233, bg=True) + " " * w + RESET)

        draw_header(self.scr, "History", "OPERATION LOG", BCYAN)

        lst.height = h - 6
        lst.width  = w
        lst.draw(self.scr)

        draw_footer(self.scr, h - 3, [
            ("↑↓", "navigate"), ("Enter/D", "detail"),
            ("U", "undo selected"), ("Q/Esc", "back"),
        ])
        self.scr.flush()

    def _detail(self, entry: dict) -> None:
        records = entry.get("records", [])
        fmt = []
        for r in records:
            cat   = r.get("category", "")
            fname = r.get("filename", "")
            dest  = Path(r.get("destination", "")).parent.name
            col   = cat_col(cat)
            icon  = cat_icon(cat)
            fmt.append(
                f"  {col}{icon}{RESET}  {col}{BOLD}{fname:<38}{RESET}  "
                f"{MUTED}→{RESET}  {col}{dest}/{RESET}"
            )

        h, w = term_size()
        lst  = ScrollList(fmt, 4, 2, h - 8, w - 4,
                          border_col=BCYAN,
                          title=f" Detail: {entry.get('id','')}  ·  {len(records)} files ")

        while True:
            if self.scr.resize():
                h, w = term_size()
                lst  = ScrollList(fmt, 4, 2, h - 8, w - 4,
                                  border_col=BCYAN,
                                  title=f" Detail: {entry.get('id','')}  ·  {len(records)} files ")

            self.scr.clear_back()
            h, w = term_size()
            for r in range(h):
                self.scr.put(r, 0, c256(232, bg=True) + " " * w + RESET)

            ts   = entry.get("timestamp", "")[:19].replace("T", " ")
            base = entry.get("base", "")
            hdr  = f"  {BCYAN}{BOLD}Time:{RESET} {ts}   {BCYAN}{BOLD}Dir:{RESET} {base}"
            self.scr.put(2, 0, hdr)
            lst.draw(self.scr)
            draw_footer(self.scr, h - 4, [("↑↓", "scroll"), ("Q/Esc", "back")])
            self.scr.flush()

            k = read_key()
            if k in (UP, "k"):     lst.move(-1)
            elif k in (DOWN, "j"): lst.move(1)
            elif k == PGUP:        lst.page(-1)
            elif k == PGDN:        lst.page(1)
            elif k in (ESC, CTRL_C, "q", "Q", ENTER):
                break


# ─────────────────────────────────────────────────────────────────────────────
# Watch screen
# ─────────────────────────────────────────────────────────────────────────────

class WatchScreen:
    """Live watch mode display — runs in a thread, updated by watch.py."""

    def __init__(self, base: Path, dry_run: bool):
        self.base    = base
        self.dry_run = dry_run
        self.scr     = Screen()
        self.log: list[tuple[str, str, str, str]] = []  # (ts, cat, fname, dest)
        self._lock   = threading.Lock()
        self._start  = time.monotonic()
        self._stop   = threading.Event()

    def add_event(self, filename: str, dest: str, category: str) -> None:
        with self._lock:
            ts = time.strftime("%H:%M:%S")
            self.log.append((ts, category, filename, dest))
            if len(self.log) > 1000:
                self.log = self.log[-1000:]

    def run_blocking(self) -> None:
        """Enter alt screen and refresh in loop until Ctrl+C."""
        self.scr.enter_alt()
        try:
            while not self._stop.is_set():
                self._draw()
                time.sleep(0.25)
        finally:
            self.scr.exit_alt()

    def stop(self) -> None:
        self._stop.set()

    def _draw(self) -> None:
        h, w = term_size()
        self.scr.resize()
        self.scr.clear_back()

        for r in range(h):
            self.scr.put(r, 0, c256(233, bg=True) + " " * w + RESET)

        mode_col = BYELLOW if self.dry_run else BGREEN
        mode_tag = "WATCH — DRY RUN" if self.dry_run else "WATCH — LIVE"
        draw_header(self.scr, "Watch Mode", mode_tag, mode_col, path=str(self.base))

        elapsed = int(time.monotonic() - self._start)
        count   = len(self.log)
        info    = (
            f"  {MUTED}Uptime: {elapsed}s{RESET}  "
            f"{MUTED}·{RESET}  "
            f"{BCYAN}{BOLD}{count}{RESET} files processed  "
            f"{MUTED}·{RESET}  "
            f"{MUTED}Ctrl+C to stop{RESET}"
        )
        self.scr.put(2, 2, info)

        # Column headers
        hdr = (
            f"  {MUTED}{'TIME':<10}{'CATEGORY':<18}{'FILE':<40}DESTINATION{RESET}"
        )
        self.scr.put(4, 0, c256(235, bg=True) + " " * w + RESET)
        self.scr.put(4, 0, hdr)

        # Log rows (newest at bottom)
        log_h = h - 8
        draw_box(self.scr, 5, 0, log_h + 2, w,
                 border_col=BOX_COL, bg=c256(233, bg=True))

        with self._lock:
            visible = self.log[-(log_h):]

        for i, (ts, cat, fname, dest) in enumerate(visible):
            col  = cat_col(cat)
            icon = cat_icon(cat)
            line = (
                f"  {MUTED}{ts:<10}{RESET}"
                f"{col}{icon} {cat:<16}{RESET}"
                f"  {col}{BOLD}{fname:<38}{RESET}"
                f"  {MUTED}→{RESET}  {col}{dest}/{RESET}"
            )
            self.scr.put(6 + i, 0, line)

        draw_footer(self.scr, h - 1, [("Ctrl+C", "stop watching")])
        self.scr.flush()