"""
foldr.output
~~~~~~~~~~~~
Rich-free ANSI output for non-TTY / piped / --quiet contexts.
Uses colorama + raw ANSI — zero external deps beyond stdlib.
"""
from __future__ import annotations
import sys, time, shutil
from pathlib import Path
from foldr.ansi import (
    RESET, BOLD, DIM, MUTED,
    BCYAN, CYAN, BGREEN, GREEN, BYELLOW, YELLOW,
    BMAGENTA, BRED, RED, BBLUE, BWHITE, BBLACK,
    WHITE, BG_DARK,
    cat_col, cat_icon, fmt_size, strip_ansi, term_size,
    CAT_COLOURS,
)


def _w() -> int:
    return min(100, shutil.get_terminal_size((80, 24)).columns)


def rule(title: str = "", col: str = BCYAN) -> None:
    w     = _w()
    if not title:
        print(col + "─" * w + RESET)
        return
    side  = max(1, (w - len(title) - 2) // 2)
    print(col + "─" * side + RESET + f" {BOLD}{title}{RESET} " + col + "─" * side + RESET)


def banner() -> None:
    """Print FOLDR ASCII banner."""
    lines = [
        f"{BCYAN}{BOLD}  ███████╗ ██████╗ ██╗     ██████╗ ██████╗ {RESET}",
        f"{BCYAN}{BOLD}  ██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗{RESET}",
        f"{CYAN}{BOLD}  █████╗  ██║   ██║██║     ██║  ██║██████╔╝{RESET}",
        f"{CYAN}  ██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗{RESET}",
        f"  ███████╗╚██████╔╝███████╗██████╔╝██║  ██║{RESET}",
        f"  ╚══════╝ ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝{RESET}",
    ]
    print()
    for line in lines:
        print(line)
    print(f"\n  {MUTED}v4  ·  Smart File Organizer  ·  github.com/qasimio/Foldr{RESET}\n")


def panel(body: str, title: str = "", col: str = BCYAN) -> None:
    w     = _w()
    inner = w - 4
    lines = body.split("\n")

    tl = col + "╭"
    if title:
        t   = f" {title} "
        pad = max(0, inner - len(t)) // 2
        top = tl + "─" * pad + BOLD + t + RESET + col + "─" * (inner - pad - len(t)) + "╮" + RESET
    else:
        top = tl + "─" * inner + "╮" + RESET
    print(top)
    for line in lines:
        vlen = len(strip_ansi(line))
        pad  = max(0, inner - vlen)
        print(col + "│" + RESET + f"  {line}" + " " * pad + col + "│" + RESET)
    print(col + "╰" + "─" * inner + "╯" + RESET)


def progress_line(done: int, total: int, label: str = "",
                  elapsed: float = 0) -> None:
    """Print a single-line progress bar (overwrites previous)."""
    w    = _w()
    pct  = done / max(1, total)
    bar_w= max(10, w - 50)
    fill = int(pct * bar_w)
    bar  = BGREEN + "█" * fill + MUTED + "░" * (bar_w - fill) + RESET
    pct_s= f"{pct*100:5.1f}%"
    line = f"  {bar}  {BCYAN}{BOLD}{done}/{total}{RESET}  {pct_s}  {MUTED}{elapsed:.1f}s{RESET}"
    if label:
        line = f"  {MUTED}{label[:30]:<30}{RESET}  " + line
    # Overwrite line
    sys.stdout.write(f"\r{line}")
    sys.stdout.flush()


def summary_table(cat_counts: dict[str, int], total_moved: int,
                  other: int, ignored: int, elapsed: float,
                  dry_run: bool) -> None:
    if not cat_counts:
        return

    w      = _w()
    bar_w  = max(12, w // 4)
    total  = max(1, sum(cat_counts.values()))

    rule("Summary")
    print()

    # Category rows
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        if cnt == 0:
            continue
        col   = cat_col(cat)
        icon  = cat_icon(cat)
        pct   = cnt / total
        fill  = max(1, int(pct * bar_w))
        bar   = col + "█" * fill + MUTED + "░" * (bar_w - fill) + RESET
        label = f"{col}{icon} {cat:<18}{RESET}"
        count = f"{col}{BOLD}{cnt:>4}{RESET}"
        pct_s = f"  {MUTED}{pct*100:4.1f}%{RESET}"
        print(f"  {label}  {bar}  {count}{pct_s}")

    print()

    # Summary panel
    if dry_run:
        status = f"{BYELLOW}{BOLD}● DRY RUN — no files were moved{RESET}"
    else:
        status = f"{BGREEN}{BOLD}✓ Files organized successfully{RESET}"

    stats = (
        f"  {BCYAN}{BOLD}{total_moved}{RESET} moved  "
        f"{MUTED}·{RESET}  "
        f"{BWHITE}{other}{RESET} unrecognised  "
        f"{MUTED}·{RESET}  "
        f"{BWHITE}{ignored}{RESET} ignored  "
        f"{MUTED}·{RESET}  "
        f"{MUTED}{elapsed:.2f}s{RESET}"
    )
    panel(f"  {status}\n\n{stats}",
          col=BYELLOW if dry_run else BGREEN)
    print()


def print_move(filename: str, dest: str, category: str, dry: bool = False) -> None:
    col  = cat_col(category)
    icon = cat_icon(category)
    tag  = f"  {BYELLOW}{DIM}[DRY]{RESET}" if dry else "      "
    print(f"{tag}  {col}{icon}{RESET}  {col}{BOLD}{filename:<40}{RESET}  "
          f"{MUTED}→{RESET}  {col}{dest}/{RESET}")


def confirm_prompt(prompt: str, default: bool = False) -> bool:
    """Plain-text y/n prompt."""
    yn   = f"[{'Y' if default else 'y'}/{'n' if default else 'N'}]"
    col  = BYELLOW
    sys.stdout.write(f"\n  {col}{BOLD}?{RESET}  {BOLD}{prompt}{RESET}  {MUTED}{yn}{RESET}: ")
    sys.stdout.flush()
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def error(msg: str) -> None:
    print(f"  {BRED}{BOLD}✗  Error:{RESET}  {msg}", file=sys.stderr)

def warn(msg: str) -> None:
    print(f"  {BYELLOW}{BOLD}⚠{RESET}  {msg}")

def info(msg: str) -> None:
    print(f"  {BCYAN}ℹ{RESET}  {msg}")

def success(msg: str) -> None:
    print(f"  {BGREEN}✓{RESET}  {msg}")

def dim(msg: str) -> None:
    print(f"  {MUTED}{msg}{RESET}")