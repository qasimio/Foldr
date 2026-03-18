"""
foldr.cli
~~~~~~~~~
FOLDR v4 — CLI entry point.

Works identically on Linux, macOS, and Windows.
No TUI. No Rich. No pyfiglet. No platform-specific imports at module level.

All features:
  foldr <path>                         organize
  foldr <path> --preview               dry-run, nothing moves
  foldr <path> --recursive             include subdirectories
  foldr <path> --recursive --depth 2   limit depth
  foldr <path> --dedup keep-newest     remove duplicates
  foldr <path> --ignore '*.log'        skip patterns
  foldr <path> --global-ignore         use ~/.foldr/.foldrignore too
  foldr <path> --smart                 detect by content not extension
  foldr <path> --verbose               print each file moved
  foldr <path> --quiet                 no output (for scripts/pipes)
  foldr <path> --config file.toml      custom category config

  foldr watch <path>                   start background auto-organizer
  foldr unwatch <path>                 stop it
  foldr watches                        list all active watchers

  foldr undo                           undo last operation
  foldr undo --id a1b2c3               undo specific operation by ID
  foldr undo --preview                 show what would be restored
  foldr history                        list past operations
  foldr history --all                  list all (no 50-entry limit)

  foldr config                         show config paths and settings
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from foldr.term import (
    ACCENT,
    BOLD,
    COL_BORD,
    COL_ERR,
    COL_OK,
    COL_WARN,
    FG_BRIGHT,
    FG_DIM,
    FG_MUTED,
    RESET,
    SPINNER,
    cat_fg,
    cat_icon,
    fmt_size,
    is_tty,
    ljust,
    op_icon,
    pad_to,
    pbar,
    strip,
    term_wh,
    truncate,
    vlen,
)
from foldr.config_loader import load_template
from foldr.dedup import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs import remove_empty_dirs, scan_empty_dirs
from foldr.history import (
    get_history_entry,
    get_latest_history,
    list_history,
    save_dedup_history,
    save_history,
    undo_operation,
)
from foldr.models import DedupeStrategy
from foldr.organizer import organize_folder

# ── Global flags (set in main) ─────────────────────────────────────────────────
_QUIET   = False    # suppress all stdout output
_NOCOLOR = False    # strip ANSI when piped / NO_COLOR set


# ── Output helpers ─────────────────────────────────────────────────────────────

def _w() -> int:
    """Current terminal width, capped at 100."""
    return min(100, term_wh()[0])


def _c(code: str) -> str:
    """Return ANSI code, or empty string when colour is disabled."""
    return "" if _NOCOLOR else code


def _print(*args: object, sep: str | None = " ", end: str | None = "\n", file = None, flush: bool = False) -> None:
    if not _QUIET:
        print(*args, sep=sep, end=end, file=file, flush=flush)


def _ok(msg: str) -> None:
    _print(f"  {_c(COL_OK)}ok{_c(RESET)}  {msg}")


def _warn(msg: str) -> None:
    _print(f"  {_c(COL_WARN)}!{_c(RESET)}   {msg}")


def _err(msg: str) -> None:
    # Errors always print, even in --quiet mode
    print(f"  {_c(COL_ERR)}err{_c(RESET)} {msg}", file=sys.stderr)


def _dim(msg: str) -> None:
    _print(f"  {_c(FG_MUTED)}{msg}{_c(RESET)}")


def _info(msg: str) -> None:
    _print(f"  {_c(ACCENT)}>{_c(RESET)} {msg}")


def _rule(title: str = "") -> None:
    if _QUIET:
        return
    w    = _w()
    muted = _c(FG_MUTED)
    rst   = _c(RESET)
    bold  = _c(BOLD)
    if not title:
        print(f"{muted}{'─' * w}{rst}")
        return
    side = max(1, (w - len(title) - 2) // 2)
    print(f"{muted}{'─' * side}{rst} {bold}{title}{rst} {muted}{'─' * side}{rst}")


def _banner() -> None:
    if _QUIET:
        return
    a = _c(ACCENT + BOLD)
    d = _c(FG_DIM)
    m = _c(FG_MUTED)
    r = _c(RESET)
    print()
    print(f"   {a}███████╗ ██████╗ ██╗     ██████╗ ██████╗{r}")
    print(f"   {a}██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗{r}")
    print(f"   {a}█████╗  ██║   ██║██║     ██║  ██║██████╔╝{r}")
    print(f"   {d}██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗{r}")
    print(f"   {d}██║     ╚██████╔╝███████╗██████╔╝██║  ██║{r}")
    print(f"   {d}╚═╝      ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝{r}")
    print(f"   {m}Smart File Organizer · v4.1 · github.com/qasimio/Foldr{r}")
    print()


def _box(body: str, title: str = "", col: str = "") -> None:
    """Rounded box around body. body may contain \\n for multiple lines."""
    if _QUIET:
        return
    c     = _c(col or COL_BORD)
    ac    = _c(ACCENT + BOLD)
    r     = _c(RESET)
    w     = _w()
    inner = w - 4
    lines = body.split("\n")

    if title:
        t  = f" {title} "
        tl = len(t)
        pl = max(1, (inner - tl) // 2)
        pr = max(0, inner - tl - pl)
        print(f"{c}╭{'─'*pl}{r}{ac}{t}{r}{c}{'─'*pr}╮{r}")
    else:
        print(f"{c}╭{'─'*inner}╮{r}")

    for line in lines:
        rest = max(0, inner - vlen(line) - 2)
        print(f"{c}│{r}  {line}{' ' * rest}  {c}│{r}")

    print(f"{c}╰{'─'*inner}╯{r}")


def _confirm(prompt: str, default: bool = False) -> bool:
    """
    Simple y/n confirmation prompt. Cross-platform, works in pipes.
    Returns `default` on EOF (non-interactive) or Ctrl+C.
    """
    yn = f"[{'Y' if default else 'y'}/{'n' if default else 'N'}]"
    sys.stdout.write(
        f"\n  {_c(COL_WARN + BOLD)}?{_c(RESET)}  {_c(BOLD)}{prompt}{_c(RESET)}"
        f"  {_c(FG_MUTED)}{yn}{_c(RESET)}: "
    )
    sys.stdout.flush()
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def _print_summary(
    cat_counts: dict[str, int],
    moved: int,
    other: int,
    ignored: int,
    elapsed: float,
    dry: bool,
) -> None:
    """Print per-category bar chart + totals."""
    if _QUIET or not cat_counts:
        return

    w      = _w()
    bar_w  = max(12, w // 3)
    total  = max(1, sum(cat_counts.values()))

    _rule("Summary")
    print()
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        if not cnt:
            continue
        col  = _c(cat_fg(cat))
        ico  = cat_icon(cat)
        rst  = _c(RESET)
        pct  = cnt / total
        fill = max(1, int(pct * bar_w))
        bar  = _c(cat_fg(cat)) + "#" * fill + _c(FG_MUTED) + "-" * (bar_w - fill) + _c(RESET)
        print(
            f"  {col}{ico}{rst}  "
            f"{_c(FG_DIM)}{ljust(cat, 16)}{rst}  "
            f"{bar}  "
            f"{_c(ACCENT)}{cnt:>4}{rst}  "
            f"{_c(FG_MUTED)}{pct * 100:4.1f}%{rst}"
        )
    print()

    status = (
        f"{_c(COL_WARN + BOLD)}preview — nothing moved{_c(RESET)}"
        if dry
        else f"{_c(COL_OK + BOLD)}done{_c(RESET)}"
    )
    _box(
        f"  {status}\n\n"
        f"  {_c(ACCENT + BOLD)}{moved}{_c(RESET)} moved  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(FG_DIM)}{other}{_c(RESET)} unrecognised  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(FG_DIM)}{ignored}{_c(RESET)} ignored  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(FG_MUTED)}{elapsed:.2f}s{_c(RESET)}",
        col=COL_WARN if dry else COL_OK,
    )
    print()


def _print_preview(result: object, dry: bool) -> None:
    """Print planned file moves as a table (or plain list if tabulate absent)."""
    records = getattr(result, "records", [])
    n = len(records)
    if not n:
        return

    print()
    try:
        from tabulate import tabulate  # type: ignore[import]
        rows = [
            [
                truncate(r.filename, 42),
                Path(r.destination).parent.name + "/",
                r.category,
            ]
            for r in records[:80]
        ]
        print(
            tabulate(
                rows,
                headers=["File", "Destination", "Category"],
                tablefmt="rounded_outline",
            )
        )
    except ImportError:
        for r in records[:50]:
            dest = Path(r.destination).parent.name
            col  = _c(cat_fg(r.category))
            rst  = _c(RESET)
            print(
                f"  {col}{cat_icon(r.category)}{rst}  "
                f"{_c(FG_BRIGHT)}{truncate(r.filename, 40):<40}{rst}  "
                f"{_c(FG_MUTED)}->{rst}  "
                f"{col}{dest}/{rst}"
            )

    if n > 80:
        _dim(f"... and {n - 80} more files")
    print()
    if dry:
        _warn(
            f"preview — {_c(ACCENT + BOLD)}{n}{_c(RESET)} files would move. "
            "Nothing changed."
        )


def _load_template(config_arg: str | None) -> dict | None:
    """Load category template from --config path or auto-discovered config."""
    if config_arg:
        try:
            tmpl, label = load_template(Path(config_arg))
            if not _QUIET:
                _dim(f"config: {label}")
            return tmpl
        except FileNotFoundError as e:
            _err(str(e))
            sys.exit(1)
    tmpl, label = load_template(None)
    if label and not _QUIET:
        _dim(f"config: {label}")
    return tmpl


def _build_ignore(args: argparse.Namespace) -> list[str]:
    """Merge CLI --ignore patterns with optional global ignore file."""
    patterns: list[str] = list(args.ignore or [])
    if getattr(args, "global_ignore", False):
        from foldr.organizer import _load_global_foldrignore
        patterns = _load_global_foldrignore() + patterns
    return patterns


# ── Argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="foldr",
        description="FOLDR v4.1 — Smart File Organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples\n"
            "--------\n"
            "  foldr ~/Downloads                     organize (preview first)\n"
            "  foldr ~/Downloads --preview            dry-run, nothing moves\n"
            "  foldr ~/Downloads --recursive          include subfolders\n"
            "  foldr ~/Downloads --recursive --depth 2\n"
            "  foldr ~/Downloads --dedup keep-newest  remove duplicates\n"
            "  foldr ~/Downloads --ignore '*.log' 'tmp/'\n"
            "  foldr ~/Downloads --global-ignore      use ~/.foldr/.foldrignore too\n"
            "  foldr ~/Downloads --smart              detect by content not extension\n"
            "  foldr ~/Downloads --verbose            print each file moved\n"
            "\n"
            "  foldr watch ~/Downloads                start background auto-organizer\n"
            "  foldr unwatch ~/Downloads              stop it\n"
            "  foldr watches                          list active watchers\n"
            "\n"
            "  foldr undo                             undo last operation\n"
            "  foldr undo --id a1b2c3                 undo specific operation\n"
            "  foldr undo --preview                   preview undo without restoring\n"
            "  foldr history                          list past operations\n"
            "  foldr history --all                    list all (no 50-entry limit)\n"
            "\n"
            "  foldr config                           show config paths\n"
        ),
    )
    p.add_argument(
        "path", nargs="?",
        help="Directory to organize",
    )
    p.add_argument(
        "--preview", action="store_true",
        help="Show what would happen without moving any files",
    )
    p.add_argument(
        "--recursive", action="store_true",
        help="Organize files in subdirectories too",
    )
    p.add_argument(
        "--depth", type=int, metavar="N",
        help="Maximum recursion depth (use with --recursive)",
    )
    p.add_argument(
        "--follow-links", action="store_true",
        help="Follow symbolic links when scanning",
    )
    p.add_argument(
        "--smart", action="store_true",
        help="Detect file type by content, not just extension (requires python-magic)",
    )
    p.add_argument(
        "--dedup",
        choices=["keep-newest", "keep-largest", "keep-oldest"],
        metavar="STRATEGY",
        help="Remove duplicates: keep-newest | keep-largest | keep-oldest",
    )
    p.add_argument(
        "--ignore", nargs="+", metavar="PATTERN",
        help="Skip files matching patterns, e.g. '*.log' 'tmp/'",
    )
    p.add_argument(
        "--global-ignore", action="store_true",
        help="Also apply rules from ~/.foldr/.foldrignore",
    )
    p.add_argument(
        "--config", metavar="FILE",
        help="Path to a custom category config (.toml)",
    )
    p.add_argument(
        "--verbose", action="store_true",
        help="Print every file that is moved",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Suppress all output (useful in scripts)",
    )
    p.add_argument(
        "--id", metavar="ID",
        help="History operation ID (for undo)",
    )
    p.add_argument(
        "--all", action="store_true",
        help="Show all history entries (removes 50-entry limit)",
    )
    return p


# ── Subcommand: watch ──────────────────────────────────────────────────────────

def cmd_watch(raw_argv: list[str], args: argparse.Namespace) -> None:
    """Start a persistent background watcher for a directory."""
    # Extract the target directory: first non-flag token after 'watch'
    try:
        wi    = next(i for i, a in enumerate(raw_argv) if a == "watch")
        cands = [a for a in raw_argv[wi + 1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except StopIteration:
        ts = None

    target = Path(ts).resolve() if ts else Path.cwd()
    if not target.is_dir():
        _err(f"'{target}' is not a valid directory")
        sys.exit(1)

    from foldr.watches import add_watch, get_watches, spawn_daemon

    watches = get_watches()
    if str(target) in watches:
        _warn(f"Already watching: {target}")
        _dim("Run 'foldr unwatch <path>' to stop it first.")
        return

    ignore = _build_ignore(args)
    pid    = spawn_daemon(target, dry_run=args.preview, extra_ignore=ignore)
    add_watch(target, pid, dry_run=args.preview)

    _info(f"Watcher started for: {_c(ACCENT + BOLD)}{target}{_c(RESET)}")
    _dim(f"PID:    {pid}")
    _dim(f"Mode:   {'preview (no moves)' if args.preview else 'live'}")
    _dim(f"Log:    {Path.home() / '.foldr' / 'watch_logs' / (target.name + '.log')}")
    _dim(f"Stop:   foldr unwatch \"{target}\"")
    _dim("Status: foldr watches")


# ── Subcommand: unwatch ────────────────────────────────────────────────────────

def cmd_unwatch(raw_argv: list[str]) -> None:
    """Stop a background watcher."""
    try:
        wi    = next(i for i, a in enumerate(raw_argv) if a == "unwatch")
        cands = [a for a in raw_argv[wi + 1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except StopIteration:
        ts = None

    if not ts:
        # Interactive picker
        from foldr.watches import get_watches
        watches = get_watches()
        if not watches:
            _warn("No active watchers.")
            return
        _rule("Active Watchers")
        paths = list(watches.keys())
        for i, p in enumerate(paths, 1):
            pid = watches[p].get("pid", "?")
            print(
                f"  {_c(ACCENT)}{i}{_c(RESET)}  "
                f"{_c(FG_BRIGHT)}{p}{_c(RESET)}  "
                f"{_c(FG_MUTED)}PID {pid}{_c(RESET)}"
            )
        print()
        sys.stdout.write(
            f"  {_c(FG_MUTED)}Enter number to stop (or Enter to cancel): {_c(RESET)}"
        )
        sys.stdout.flush()
        try:
            ans = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if ans.isdigit() and 1 <= int(ans) <= len(paths):
            ts = paths[int(ans) - 1]
        else:
            _dim("Cancelled.")
            return

    target = Path(ts).resolve()
    from foldr.watches import kill_watch
    ok, msg = kill_watch(target)
    (_ok if ok else _warn)(msg)


# ── Subcommand: watches ────────────────────────────────────────────────────────

def cmd_watches() -> None:
    """List all active background watchers."""
    from foldr.watches import get_watches
    watches = get_watches()

    if not watches:
        _box(
            f"  {_c(FG_DIM)}No active watchers.{_c(RESET)}\n\n"
            f"  Start one:  {_c(ACCENT)}foldr watch ~/Downloads{_c(RESET)}",
        )
        return

    _rule("Active Watchers")
    print()
    try:
        from tabulate import tabulate  # type: ignore[import]
        rows = []
        for p, info in watches.items():
            started = info.get("started", "")[:16].replace("T", " ")
            mode    = "preview" if info.get("dry_run") else "live"
            total   = info.get("total", 0)
            rows.append([
                Path(p).name,
                started,
                mode,
                f"{total} files",
                str(info.get("pid", "?")),
            ])
        print(tabulate(
            rows,
            headers=["Directory", "Started", "Mode", "Organized", "PID"],
            tablefmt="rounded_outline",
        ))
    except ImportError:
        for p, info in watches.items():
            started = info.get("started", "")[:16].replace("T", " ")
            mode    = "preview" if info.get("dry_run") else "live"
            total   = info.get("total", 0)
            pid     = info.get("pid", "?")
            col     = _c(COL_OK) if mode == "live" else _c(COL_WARN)
            print(
                f"  {_c(ACCENT + BOLD)}{ljust(Path(p).name, 24)}{_c(RESET)}"
                f"  {_c(FG_DIM)}{started}{_c(RESET)}"
                f"  {col}{mode}{_c(RESET)}"
                f"  {_c(FG_DIM)}{total} files  PID {pid}{_c(RESET)}"
            )
    print()
    _dim(f"Logs:  {Path.home() / '.foldr' / 'watch_logs'}")
    _dim("Stop:  foldr unwatch <directory>")


# ── Subcommand: _watch-daemon (internal, not for users) ───────────────────────

def cmd_watch_daemon(raw_argv: list[str], args: argparse.Namespace) -> None:
    """
    Internal daemon process spawned by 'foldr watch'.
    Not meant for direct user invocation.
    """
    try:
        wi    = raw_argv.index("_watch-daemon")
        cands = [a for a in raw_argv[wi + 1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except (ValueError, IndexError):
        ts = None
    if not ts:
        sys.exit(1)

    target = Path(ts).resolve()
    tmpl   = _load_template(getattr(args, "config", None))
    ignore = _build_ignore(args)

    from foldr.watch import run_watch
    run_watch(
        base=target,
        template=tmpl or {},
        dry_run=getattr(args, "preview", False),
        extra_ignore=ignore,
        daemon_mode=True,
    )


# ── Subcommand: undo ───────────────────────────────────────────────────────────

def cmd_undo(args: argparse.Namespace) -> None:
    """Restore files from a past organize operation."""
    _rule("Undo")

    target_id = getattr(args, "id", None)
    if target_id:
        log = get_history_entry(target_id)
        if not log:
            _err(f"No history entry found for ID: {target_id!r}")
            _dim("Run 'foldr history' to see valid IDs.")
            return
    else:
        log = get_latest_history()
        if not log:
            _warn("No history found. Run 'foldr <path>' first.")
            return

    ts    = log.get("timestamp", "")[:19].replace("T", " ")
    base  = log.get("base", "")
    total = log.get("total_files", 0)
    eid   = log.get("id", "?")
    otype = log.get("op_type", "organize")

    _box(
        f"  ID:          {_c(ACCENT + BOLD)}{eid}{_c(RESET)}\n"
        f"  Operation:   {_c(FG_DIM)}{otype}{_c(RESET)}\n"
        f"  Time:        {_c(FG_DIM)}{ts}{_c(RESET)}\n"
        f"  Directory:   {_c(FG_DIM)}{base}{_c(RESET)}\n"
        f"  Files:       {_c(ACCENT + BOLD)}{total}{_c(RESET)}",
        title=" Undo Preview ",
        col=COL_WARN,
    )

    if otype == "dedup":
        _warn("Dedup permanently deletes files — cannot be undone.")
        _dim("Tip: always run '--dedup ... --preview' before deduping.")
        return

    dry = getattr(args, "preview", False)
    if not dry:
        ok = _confirm(
            f"Restore {total} files from operation {eid}?",
            default=False,
        )
        if not ok:
            _dim("Cancelled.")
            return

    result = undo_operation(log, dry_run=dry)

    print()
    _rule("Preview" if dry else "Restored")
    print()
    for r in result.restored:
        pfx = f"  {_c(COL_WARN)}preview{_c(RESET)}" if dry else f"  {_c(COL_OK)}<-{_c(RESET)}"
        print(f"{pfx}  {_c(FG_DIM)}{r}{_c(RESET)}")
    for s in result.skipped:
        print(f"  {_c(COL_WARN)}skip{_c(RESET)}  {_c(FG_MUTED)}{s}{_c(RESET)}")
    for e in result.errors:
        _err(e)
    print()
    _box(
        f"  {_c(COL_OK + BOLD)}{len(result.restored)}{_c(RESET)} restored  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(COL_WARN)}{len(result.skipped)}{_c(RESET)} skipped  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(COL_ERR)}{len(result.errors)}{_c(RESET)} errors",
        col=COL_OK if not result.errors else COL_ERR,
    )


# ── Subcommand: history ────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    """List all past organize/dedup/undo operations."""
    limit   = None if getattr(args, "all", False) else 50
    entries = list_history(limit=limit or 50)

    if not entries:
        _warn("No history found. Run 'foldr <path>' to start.")
        return

    _rule("Operation History")
    print()
    try:
        from tabulate import tabulate  # type: ignore[import]
        rows = [
            [
                e.get("id", "?"),
                e.get("op_type", "organize"),
                e.get("timestamp", "")[:16].replace("T", " "),
                Path(e.get("base", "?")).name,
                str(e.get("total_files", 0)),
            ]
            for e in entries
        ]
        print(tabulate(
            rows,
            headers=["ID", "Type", "Time", "Directory", "Files"],
            tablefmt="rounded_outline",
        ))
    except ImportError:
        for e in entries:
            ts  = e.get("timestamp", "")[:16].replace("T", " ")
            ot  = e.get("op_type", "organize")
            oi  = op_icon(ot)
            print(
                f"  {_c(ACCENT)}{e.get('id', '?')}{_c(RESET)}"
                f"  {_c(FG_MUTED)}{oi} {ljust(ot, 10)}{_c(RESET)}"
                f"  {ts}"
                f"  {Path(e.get('base', '?')).name}"
                f"  {_c(FG_DIM)}{e.get('total_files', 0)} files{_c(RESET)}"
            )

    print()
    _dim("To undo any operation: foldr undo --id <ID>")


# ── Subcommand: config ─────────────────────────────────────────────────────────

def cmd_config() -> None:
    """Show config paths and current status."""
    foldr_dir = Path.home() / ".foldr"
    _rule("FOLDR Config")
    print()

    def _show(label: str, path: Path, note: str = "") -> None:
        exists = "(exists)" if path.exists() else "(not set)"
        suffix = f"  {_c(FG_MUTED)}{note or exists}{_c(RESET)}"
        _print(f"  {_c(FG_DIM)}{label:<22}{_c(RESET)}  {path}{suffix}")

    _show("Config dir",      foldr_dir)
    _show("Category config", foldr_dir / "config.toml")
    _show("Global ignore",   foldr_dir / ".foldrignore")
    _show("History",         foldr_dir / "history")
    _show("Watch logs",      foldr_dir / "watch_logs")
    _show("Watchers",        foldr_dir / "watches.json")
    print()
    _dim("Category config format: see FOLDR_MANUAL.md")
    _dim("Create config:  touch ~/.foldr/config.toml")


# ── Subcommand: dedup ──────────────────────────────────────────────────────────

def cmd_dedup(
    target: Path,
    strat_str: str,
    recursive: bool,
    max_depth: int | None,
    preview: bool,
    verbose: bool,
) -> None:
    """Find and remove duplicate files."""
    stmap = {
        "keep-newest":  DedupeStrategy.KEEP_NEWEST,
        "keep-oldest":  DedupeStrategy.KEEP_OLDEST,
        "keep-largest": DedupeStrategy.KEEP_LARGEST,
    }

    _rule("Duplicate Detection")
    _info(f"Scanning {target} ...")

    files  = collect_files(target, recursive=recursive, max_depth=max_depth)
    groups = find_duplicates(files)

    if not groups:
        _ok("No duplicates found.")
        return

    total_rem = sum(len(g.files) - 1 for g in groups)
    _warn(f"Found {len(groups)} duplicate groups — {total_rem} files can be removed")

    for g in groups:
        resolve_strategy(g, stmap[strat_str])

    print()
    try:
        from tabulate import tabulate  # type: ignore[import]
        rows = [
            [
                truncate(g.keep.name, 36) if g.keep else "?",
                truncate(rem.name, 36),
                fmt_size(g.keep.stat().st_size if g.keep and g.keep.exists() else 0),
            ]
            for g in groups[:60]
            for rem in g.remove
        ]
        print(tabulate(rows, headers=["Keep", "Remove", "Size"], tablefmt="rounded_outline"))
    except ImportError:
        for g in groups[:30]:
            for rem in g.remove:
                kname = g.keep.name if g.keep else "?"
                print(
                    f"  {_c(COL_OK)}keep{_c(RESET)} {kname}  "
                    f"{_c(COL_ERR)}del{_c(RESET)}  {rem.name}"
                )

    if total_rem > 60:
        _dim(f"... and {total_rem - 60} more")
    print()

    if preview:
        _warn(f"preview — {total_rem} files would be removed. Nothing changed.")
        return

    ok = _confirm(
        f"Permanently delete {total_rem} duplicate files? (strategy: {strat_str})",
        default=False,
    )
    if not ok:
        _dim("Cancelled.")
        return

    removed: list[Path] = []
    for g in groups:
        for p in g.remove:
            try:
                p.unlink()
                removed.append(p)
                if verbose:
                    _dim(f"deleted  {p}")
            except OSError as e:
                _err(f"Could not remove {p.name}: {e}")

    save_dedup_history(removed, target, strat_str)
    _ok(f"Removed {len(removed)} duplicate files.")
    _dim("Dedup history is recorded, but files cannot be restored via 'foldr undo'.")


# ── Subcommand: organize (core feature) ───────────────────────────────────────

def cmd_organize(
    target: Path,
    args: argparse.Namespace,
    template: dict | None,
) -> None:
    """Scan target and organize files into category folders."""
    preview = args.preview
    ignore  = _build_ignore(args)

    _rule(f"Scanning  {target.name}/")

    # Spinner for slow scans in non-interactive environments
    spinner_done = threading.Event()
    if not _QUIET and not is_tty():
        def _spin() -> None:
            i = 0
            while not spinner_done.is_set():
                sys.stdout.write(f"\r  {SPINNER[i % 4]}  Scanning...")
                sys.stdout.flush()
                time.sleep(0.1)
                i += 1
            sys.stdout.write("\r" + " " * 30 + "\r")
            sys.stdout.flush()
        threading.Thread(target=_spin, daemon=True).start()

    t0 = time.monotonic()
    prev = organize_folder(
        base=target,
        dry_run=True,
        recursive=args.recursive,
        max_depth=getattr(args, "depth", None),
        follow_symlinks=getattr(args, "follow_links", False),
        extra_ignore=ignore,
        category_template=template,
        global_ignore=getattr(args, "global_ignore", False),
    )
    spinner_done.set()

    if not prev.actions:
        _box(
            f"  {_c(COL_OK + BOLD)}Nothing to organize — directory is already tidy!{_c(RESET)}",
            col=COL_OK,
        )
        return

    n = len(prev.records)

    # Show preview table
    _print_preview(prev, preview)

    if preview:
        _print_summary(
            {k: v for k, v in prev.categories.items() if v},
            n,
            prev.other_files,
            getattr(prev, "ignored_files", 0),
            time.monotonic() - t0,
            dry=True,
        )
        return

    # Confirm before executing
    confirmed = _confirm(f"Move {n} files?", default=True)
    if not confirmed:
        _warn("Cancelled — nothing was moved.")
        print()
        return

    # Execute
    _rule("Moving files")
    t_exec = time.monotonic()

    result = organize_folder(
        base=target,
        dry_run=False,
        recursive=args.recursive,
        max_depth=getattr(args, "depth", None),
        follow_symlinks=getattr(args, "follow_links", False),
        extra_ignore=ignore,
        category_template=template,
        global_ignore=getattr(args, "global_ignore", False),
    )

    elapsed = time.monotonic() - t_exec

    if not _QUIET:
        bar = pbar(1.0, 30)
        print(
            f"  {bar}  "
            f"{_c(ACCENT + BOLD)}{len(result.records)}{_c(RESET)} files moved"
        )

    # Save history
    log_path = save_history(
        result.records, target, dry_run=False, op_type="organize"
    )
    if log_path and args.verbose:
        _dim(f"History: {log_path.name}")

    # Verbose per-file list
    if args.verbose:
        print()
        for r in result.records:
            dest = Path(r.destination).parent.name
            col  = _c(cat_fg(r.category))
            rst  = _c(RESET)
            print(
                f"  {col}{cat_icon(r.category)}{rst}  "
                f"{_c(FG_BRIGHT)}{truncate(r.filename, 40):<40}{rst}  "
                f"{_c(FG_MUTED)}->{rst}  "
                f"{col}{dest}/{rst}"
            )

    _print_summary(
        {k: v for k, v in result.categories.items() if v},
        len(result.records),
        result.other_files,
        getattr(result, "ignored_files", 0),
        elapsed,
        dry=False,
    )

    # Offer to remove empty directories
    scan = scan_empty_dirs(target)
    if scan.found and not _QUIET:
        n_empty = len(scan.found)
        _warn(f"Found {n_empty} empty {'directory' if n_empty == 1 else 'directories'}.")
        if _confirm(f"Remove {n_empty} empty directories?", default=False):
            removed = remove_empty_dirs(scan.found)
            _ok(f"Removed {len(removed.removed)} empty directories.")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global _QUIET, _NOCOLOR

    raw = sys.argv[1:]

    # ── Subcommand detection ───────────────────────────────────────────────────
    # Scan ALL positional args, not just the first, so that:
    #   foldr ~/Downloads/path undo --id X
    # correctly dispatches to undo even though a path comes first.
    _SUBCMDS = {
        "watch", "unwatch", "watches",
        "undo", "history", "config",
        "_watch-daemon",
    }
    sub = next(
        (a for a in raw if not a.startswith("-") and a in _SUBCMDS),
        None,
    )

    parser = _build_parser()
    args, _ = parser.parse_known_args(raw)

    _QUIET   = args.quiet
    # Disable colour when output is piped, redirected, or NO_COLOR is set
    _NOCOLOR = not is_tty() or bool(os.environ.get("NO_COLOR"))

    # ── Banner ─────────────────────────────────────────────────────────────────
    if not _QUIET and sub != "_watch-daemon":
        _banner()

    # ── Dispatch ───────────────────────────────────────────────────────────────
    if sub == "config":         cmd_config();                  return
    if sub == "watch":          cmd_watch(raw, args);          return
    if sub == "unwatch":        cmd_unwatch(raw);              return
    if sub == "watches":        cmd_watches();                 return
    if sub == "_watch-daemon":  cmd_watch_daemon(raw, args);   return
    if sub == "undo":           cmd_undo(args);                return
    if sub == "history":        cmd_history(args);             return

    # ── Resolve target directory ───────────────────────────────────────────────
    path_candidates = [
        a for a in raw
        if not a.startswith("-") and a not in _SUBCMDS
    ]
    raw_path = path_candidates[0] if path_candidates else None

    if not raw_path:
        # No path given — offer to organize cwd
        cwd = Path.cwd()
        _box(
            f"  No path given.\n\n"
            f"  Target:  {_c(ACCENT + BOLD)}{cwd}{_c(RESET)}\n\n"
            f"  {_c(FG_MUTED)}Tip: foldr ~/Downloads{_c(RESET)}",
        )
        if not _confirm(f"Organize current directory ({cwd.name})?", default=False):
            _dim("Cancelled.")
            return
        target = cwd
    else:
        target = Path(raw_path).resolve()

    if not target.exists() or not target.is_dir():
        _err(f"'{target}' is not a valid directory")
        sys.exit(1)

    template = _load_template(args.config)

    if args.dedup:
        cmd_dedup(
            target,
            args.dedup,
            args.recursive,
            getattr(args, "depth", None),
            args.preview,
            args.verbose,
        )
        return

    cmd_organize(target, args, template)


if __name__ == "__main__":
    main()