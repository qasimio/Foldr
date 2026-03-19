"""
foldr.cli
~~~~~~~~~
FOLDR 2.1 — Smart File Organizer by Muhammad Qasim
     github.com/qasimio/Foldr

Usage
-----
  foldr <path>                         organize a directory
  foldr <path> --preview               dry-run, nothing moves
  foldr <path> --recursive             include subdirectories
  foldr <path> --recursive --depth 2   limit recursion depth
  foldr <path> --dedup keep-newest     remove duplicate files
  foldr <path> --ignore '*.log'        skip matching files this run
  foldr <path> --no-ignore             disable ALL ignore rules this run
  foldr <path> --show-ignored          list which files were ignored and why
  foldr <path> --smart                 detect type by content (needs python-magic)
  foldr <path> --verbose               print every file moved
  foldr <path> --quiet                 no output (for scripts / CI)
  foldr <path> --config file.toml      use a custom category config

  foldr watch <path>                   start background auto-organizer
  foldr watch <path> --recursive       watch subdirectories too
  foldr watch <path> --startup         also start on login / reboot
  foldr unwatch <path>                 stop a watcher
  foldr watches                        list all active watchers

  foldr undo                           undo the last operation
  foldr undo --id a1b2c3               undo a specific operation by ID
  foldr undo --preview                 show what would be restored
  foldr history                        list past operations
  foldr history --all                  list all (no 50-entry limit)

  foldr config                         show config file paths and status
  foldr config --edit                  open config.toml in your editor
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import threading
import time
from pathlib import Path

from foldr.term import (
    ACCENT, BOLD, COL_BORD, COL_ERR, COL_OK, COL_WARN,
    FG_BRIGHT, FG_DIM, FG_MUTED, RESET, SPINNER,
    cat_fg, cat_icon, fmt_size, is_tty, ljust,
    op_icon, pad_to, pbar, strip, term_wh, truncate, vlen,
)
from foldr.config_loader import (
    default_config_path, ensure_config_exists, load_template,
)
from foldr.dedup import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs import remove_empty_dirs, scan_empty_dirs
from foldr.history import (
    get_history_entry, get_latest_history, list_history,
    save_dedup_history, save_history, undo_operation,
)
from foldr.models import DedupeStrategy
from foldr.organizer import organize_folder

_IS_WIN = platform.system() == "Windows"

# ── Runtime flags ──────────────────────────────────────────────────────────────
_QUIET   = False
_NOCOLOR = False


# ── Output helpers ─────────────────────────────────────────────────────────────

def _w() -> int:
    return min(100, term_wh()[0])

def _c(code: str) -> str:
    return "" if _NOCOLOR else code

def _print(*args: object, sep: str | None = " ", end: str | None = "\n", file=None, flush: bool = False) -> None:
    if not _QUIET:
        print(*args, sep=sep, end=end, file=file, flush=flush)

def _ok(msg: str)   -> None: _print(f"  {_c(COL_OK)}ok{_c(RESET)}  {msg}")
def _warn(msg: str) -> None: _print(f"  {_c(COL_WARN)}!{_c(RESET)}   {msg}")
def _err(msg: str)  -> None: print(f"  {_c(COL_ERR)}err{_c(RESET)} {msg}", file=sys.stderr)
def _dim(msg: str)  -> None: _print(f"  {_c(FG_MUTED)}{msg}{_c(RESET)}")
def _info(msg: str) -> None: _print(f"  {_c(ACCENT)}>{_c(RESET)} {msg}")

def _rule(title: str = "") -> None:
    if _QUIET:
        return
    w = _w()
    m, r, b = _c(FG_MUTED), _c(RESET), _c(BOLD)
    if not title:
        print(f"{m}{'─' * w}{r}")
        return
    side = max(1, (w - len(title) - 2) // 2)
    print(f"{m}{'─'*side}{r} {b}{title}{r} {m}{'─'*side}{r}")

def _banner() -> None:
    if _QUIET:
        return
    a, d, m, r = _c(ACCENT+BOLD), _c(FG_DIM), _c(FG_MUTED), _c(RESET)
    print()
    print(f"   {a}███████╗ ██████╗ ██╗     ██████╗ ██████╗{r}")
    print(f"   {a}██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗{r}")
    print(f"   {a}█████╗  ██║   ██║██║     ██║  ██║██████╔╝{r}")
    print(f"   {d}██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗{r}")
    print(f"   {d}██║     ╚██████╔╝███████╗██████╔╝██║  ██║{r}")
    print(f"   {d}╚═╝      ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝{r}")
    print(f"   {m}Smart File Organizer  ·  2.1{r}")
    print(f"   {m}by Muhammad Qasim  ·  github.com/qasimio/Foldr{r}")
    print()

def _box(body: str, title: str = "", col: str = "") -> None:
    """
    Rounded box. body may contain \\n.
    FIX: rest = inner - vlen(line) - 4  (was - 2, causing off-by-2 alignment).
    The content row is: │ + 2sp + line + rest_sp + 2sp + │
    Visual total = 1 + 2 + vlen + rest + 2 + 1 = 6 + vlen + rest
    For total = w = inner + 4:  rest = inner - 2 - vlen... but wait,
    the two │ chars are NOT inside inner, so content between │ must = inner.
    Content visual = 2 + vlen + rest + 2 = inner  →  rest = inner - vlen - 4.
    """
    if _QUIET:
        return
    c     = _c(col or COL_BORD)
    ac    = _c(ACCENT + BOLD)
    r     = _c(RESET)
    w     = _w()
    inner = w - 2      # width between the two │ chars
    lines = body.split("\n")

    if title:
        t  = f" {title} "
        tl = len(t)    # plain text, no ANSI in title
        pl = max(1, (inner - 2 - tl) // 2)
        pr = max(0, inner - 2 - tl - pl)
        print(f"{c}╭{'─'*pl}{r}{ac}{t}{r}{c}{'─'*pr}╮{r}")
    else:
        print(f"{c}╭{'─'*(inner-2)}╮{r}")

    for line in lines:
        rest = max(0, inner - vlen(line) - 4)
        # Apply RESET before padding so colour from body doesn't bleed into spaces
        print(f"{c}│{r}  {line}{_c(RESET)}{' ' * rest}  {c}│{r}")

    print(f"{c}╰{'─'*(inner-2)}╯{r}")

def _confirm(prompt: str, default: bool = False) -> bool:
    yn = f"[{'Y' if default else 'y'}/{'n' if default else 'N'}]"
    sys.stdout.write(
        f"\n  {_c(COL_WARN+BOLD)}?{_c(RESET)}  {_c(BOLD)}{prompt}{_c(RESET)}"
        f"  {_c(FG_MUTED)}{yn}{_c(RESET)}: "
    )
    sys.stdout.flush()
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return (ans in ("y", "yes")) if ans else default


# ── Summary ────────────────────────────────────────────────────────────────────

def _print_summary(
    cat_counts: dict[str, int],
    moved: int,
    other: int,
    ignored: int,
    elapsed: float,
    dry: bool,
) -> None:
    if _QUIET or not cat_counts:
        return
    w     = _w()
    bar_w = max(12, w // 3)
    total = max(1, sum(cat_counts.values()))
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
            f"{_c(FG_MUTED)}{pct*100:4.1f}%{rst}"
        )
    print()
    status = (
        f"{_c(COL_WARN+BOLD)}preview — nothing moved{_c(RESET)}"
        if dry else
        f"{_c(COL_OK+BOLD)}done{_c(RESET)}"
    )
    _box(
        f"  {status}\n\n"
        f"  {_c(ACCENT+BOLD)}{moved}{_c(RESET)} moved  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(FG_DIM)}{other}{_c(RESET)} unrecognised  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(FG_DIM)}{ignored}{_c(RESET)} ignored  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(FG_MUTED)}{elapsed:.2f}s{_c(RESET)}",
        col=COL_WARN if dry else COL_OK,
    )
    print()


# ── Preview table ──────────────────────────────────────────────────────────────

def _print_preview(result: object, dry: bool) -> None:
    records = getattr(result, "records", [])
    n = len(records)
    if not n:
        return
    print()
    try:
        from tabulate import tabulate  # type: ignore[import]
        rows = [
            [truncate(r.filename, 42),
             Path(r.destination).parent.name + "/",
             r.category]
            for r in records[:80]
        ]
        print(tabulate(rows, headers=["File", "Destination", "Category"],
                       tablefmt="rounded_outline"))
    except ImportError:
        for r in records[:50]:
            dest = Path(r.destination).parent.name
            col  = _c(cat_fg(r.category))
            rst  = _c(RESET)
            print(
                f"  {col}{cat_icon(r.category)}{rst}  "
                f"{_c(FG_BRIGHT)}{truncate(r.filename, 40):<40}{rst}  "
                f"{_c(FG_MUTED)}->{rst}  {col}{dest}/{rst}"
            )
    if n > 80:
        _dim(f"... and {n-80} more files")
    print()
    if dry:
        _warn(
            f"preview — {_c(ACCENT+BOLD)}{n}{_c(RESET)} files would move. "
            "Nothing changed."
        )


# ── Ignore helpers ─────────────────────────────────────────────────────────────

def _build_ignore(args: argparse.Namespace) -> list[str]:
    """
    Build the final ignore pattern list.

    Default behaviour:
      ~/.foldr/.foldrignore is loaded automatically (no flag needed).
      Local .foldrignore in the target dir is always loaded by organizer.py.

    --ignore PATTERN   add extra patterns for this run
    --no-ignore        disable ALL ignore rules (local + global + CLI)
    """
    if getattr(args, "no_ignore", False):
        return []   # user wants to ignore nothing

    patterns: list[str] = list(args.ignore or [])
    # Global ignore applied by default (organizer handles local .foldrignore)
    return patterns


def _load_template(config_arg: str | None) -> dict | None:
    if config_arg:
        try:
            tmpl, label = load_template(Path(config_arg))
            if not _QUIET:
                _dim(f"config: {label}")
            return tmpl
        except (FileNotFoundError, RuntimeError) as e:
            _err(str(e))
            sys.exit(1)
    tmpl, label = load_template(None)
    if label and not _QUIET:
        _dim(f"config: {label}")
    return tmpl


# ── Argument parser ────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="foldr",
        description=(
            "FOLDR 2.1 — Smart File Organizer\n"
            "by Muhammad Qasim  ·  github.com/qasimio/Foldr"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "────────────────────────────────────────────────────────────\n"
            "EXAMPLES\n"
            "────────────────────────────────────────────────────────────\n"
            '  foldr "D:\\Downloads"                  organize (preview first)\n'
            '  foldr "D:\\Downloads" --preview         dry-run, nothing moves\n'
            '  foldr "D:\\Downloads" --recursive       include subdirectories\n'
            '  foldr "D:\\Downloads" --recursive --depth 2\n'
            '  foldr "D:\\Downloads" --dedup keep-newest\n'
            '  foldr "D:\\Downloads" --ignore "*.log" "tmp/"\n'
            '  foldr "D:\\Downloads" --no-ignore        skip all ignore rules\n'
            '  foldr "D:\\Downloads" --show-ignored     show ignored files\n'
            "  foldr watch ~/Downloads\n"
            "  foldr watch ~/Downloads --recursive --startup\n"
            "  foldr unwatch ~/Downloads\n"
            "  foldr watches\n"
            "  foldr undo\n"
            "  foldr undo --id a1b2c3\n"
            "  foldr history\n"
            "  foldr config\n"
            "\n"
            "────────────────────────────────────────────────────────────\n"
            "WARNINGS\n"
            "────────────────────────────────────────────────────────────\n"
            "  • Paths with spaces must be quoted:  foldr \"My Downloads\"\n"
            "  • --dedup permanently deletes files and CANNOT be undone.\n"
            "    Always run with --preview first.\n"
            "  • Watch mode organizes files silently — no confirmation per file.\n"
        ),
    )
    p.add_argument("path",           nargs="?", help="Directory to organize")
    p.add_argument("--preview",      action="store_true",
                   help="Show what would happen without moving files")
    p.add_argument("--recursive",    action="store_true",
                   help="Organize files in subdirectories too")
    p.add_argument("--depth",        type=int, metavar="N",
                   help="Max recursion depth (use with --recursive)")
    p.add_argument("--follow-links", action="store_true",
                   help="Follow symbolic links")
    p.add_argument("--smart",        action="store_true",
                   help="Detect file type by content not extension (needs: pip install python-magic)")
    p.add_argument("--dedup",
                   choices=["keep-newest", "keep-largest", "keep-oldest"],
                   metavar="STRATEGY",
                   help="⚠ Remove duplicates — IRREVERSIBLE. Strategies: keep-newest | keep-largest | keep-oldest")
    p.add_argument("--ignore",       nargs="+", metavar="PATTERN",
                   help="Skip files matching patterns this run, e.g. '*.log' 'tmp/'")
    p.add_argument("--no-ignore",    action="store_true",
                   help="Disable ALL ignore rules (local .foldrignore, global, and --ignore)")
    p.add_argument("--show-ignored", action="store_true",
                   help="Show which files were skipped and why")
    p.add_argument("--global-ignore",action="store_true",
                   help="(Deprecated — global ignore is now always applied. Use --no-ignore to disable.)")
    p.add_argument("--config",       metavar="FILE",
                   help="Path to a custom category config (.toml)")
    p.add_argument("--verbose",      action="store_true",
                   help="Print every file that is moved (implies progress details)")
    p.add_argument("--quiet",        action="store_true",
                   help="Suppress all output — useful in scripts, cron jobs, CI")
    p.add_argument("--startup",      action="store_true",
                   help="(watch) also register to start on login/reboot")
    p.add_argument("--id",           metavar="ID",
                   help="History operation ID (for: foldr undo --id <ID>)")
    p.add_argument("--all",          action="store_true",
                   help="Show all history entries (removes 50-entry limit)")
    p.add_argument("--edit",         action="store_true",
                   help="(config) open config.toml in your editor")
    p.add_argument("--ignore-file",  action="store_true", dest="ignore_file",
                   help="(config --edit) open .foldrignore instead of config.toml")
    return p


# ── watch ──────────────────────────────────────────────────────────────────────

def cmd_watch(raw_argv: list[str], args: argparse.Namespace) -> None:
    try:
        wi    = next(i for i, a in enumerate(raw_argv) if a == "watch")
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except StopIteration:
        ts = None

    target = Path(ts).resolve() if ts else Path.cwd()
    if not target.is_dir():
        _err(f"Not a valid directory: {target}")
        _dim("Tip: if the path has spaces, wrap it in quotes.")
        sys.exit(1)

    from foldr.watches import add_watch, get_watches, spawn_daemon, register_startup

    if str(target.resolve()) in get_watches():
        _warn(f"Already watching: {target}")
        _dim("Run 'foldr unwatch <path>' to stop it first.")
        return

    ignore    = _build_ignore(args)
    recursive = args.recursive
    startup   = getattr(args, "startup", False)

    pid = spawn_daemon(
        target, dry_run=args.preview,
        recursive=recursive, extra_ignore=ignore,
    )
    add_watch(target, pid, dry_run=args.preview, recursive=recursive, startup=startup)

    _info(f"Watcher started for: {_c(ACCENT+BOLD)}{target}{_c(RESET)}")
    _dim(f"PID:       {pid}")
    _dim(f"Mode:      {'preview (no moves)' if args.preview else 'live'}")
    _dim(f"Recursive: {'yes' if recursive else 'no'}")
    _dim(f"Log:       {Path.home() / '.foldr' / 'watch_logs' / (target.name + '.log')}")
    _dim(f"Stop:      foldr unwatch \"{target}\"")
    _dim(f"Status:    foldr watches")

    if startup:
        ok, msg = register_startup(target, recursive=recursive)
        (_ok if ok else _warn)(msg)
    else:
        _dim("Tip: add --startup to also start on login/reboot")


# ── unwatch ────────────────────────────────────────────────────────────────────

def cmd_unwatch(raw_argv: list[str]) -> None:
    try:
        wi    = next(i for i, a in enumerate(raw_argv) if a == "unwatch")
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except StopIteration:
        ts = None

    if not ts:
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
        sys.stdout.write(f"  {_c(FG_MUTED)}Number to stop (Enter = cancel): {_c(RESET)}")
        sys.stdout.flush()
        try:
            ans = input().strip()
        except (EOFError, KeyboardInterrupt):
            print(); return
        if ans.isdigit() and 1 <= int(ans) <= len(paths):
            ts = paths[int(ans)-1]
        else:
            _dim("Cancelled."); return

    target = Path(ts).resolve()
    from foldr.watches import kill_watch, unregister_startup
    ok, msg = kill_watch(target)
    (_ok if ok else _warn)(msg)
    # Also remove startup entry if one exists
    unregister_startup(target)


# ── watches ────────────────────────────────────────────────────────────────────

def cmd_watches() -> None:
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
            started   = info.get("started", "")[:16].replace("T", " ")
            mode      = "preview" if info.get("dry_run") else "live"
            recursive = "yes" if info.get("recursive") else "no"
            startup   = "yes" if info.get("startup") else "no"
            total     = info.get("total", 0)
            rows.append([
                Path(p).name, started, mode,
                recursive, startup, f"{total} files",
                str(info.get("pid", "?")),
            ])
        print(tabulate(rows,
                       headers=["Directory", "Started", "Mode", "Recursive", "Startup", "Organized", "PID"],
                       tablefmt="rounded_outline"))
    except ImportError:
        for p, info in watches.items():
            started   = info.get("started", "")[:16].replace("T", " ")
            mode      = "preview" if info.get("dry_run") else "live"
            total     = info.get("total", 0)
            pid       = info.get("pid", "?")
            col       = _c(COL_OK) if mode == "live" else _c(COL_WARN)
            print(
                f"  {_c(ACCENT+BOLD)}{ljust(Path(p).name, 22)}{_c(RESET)}  "
                f"{_c(FG_DIM)}{started}{_c(RESET)}  "
                f"{col}{mode}{_c(RESET)}  "
                f"{_c(FG_DIM)}{total} files  PID {pid}{_c(RESET)}"
            )
    print()
    _dim(f"Logs:  {Path.home() / '.foldr' / 'watch_logs'}")
    _dim("Stop:  foldr unwatch <directory>")


# ── _watch-daemon (internal) ───────────────────────────────────────────────────

def cmd_watch_daemon(raw_argv: list[str], args: argparse.Namespace) -> None:
    try:
        wi    = raw_argv.index("_watch-daemon")
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
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
        recursive=getattr(args, "recursive", False),
        extra_ignore=ignore,
        daemon_mode=True,
    )


# ── undo ───────────────────────────────────────────────────────────────────────

def cmd_undo(args: argparse.Namespace) -> None:
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
        f"  ID:          {_c(ACCENT+BOLD)}{eid}{_c(RESET)}\n"
        f"  Operation:   {_c(FG_DIM)}{otype}{_c(RESET)}\n"
        f"  Time:        {_c(FG_DIM)}{ts}{_c(RESET)}\n"
        f"  Directory:   {_c(FG_DIM)}{base}{_c(RESET)}\n"
        f"  Files:       {_c(ACCENT+BOLD)}{total}{_c(RESET)}",
        title=" Undo Preview ", col=COL_WARN,
    )

    if otype == "dedup":
        _warn("Dedup permanently deletes files — cannot be undone.")
        _dim("Always run 'foldr --dedup ... --preview' before deduping.")
        return

    dry = getattr(args, "preview", False)
    if not dry:
        ok = _confirm(f"Restore {total} files from operation {eid}?", default=False)
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
        f"  {_c(COL_OK+BOLD)}{len(result.restored)}{_c(RESET)} restored  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(COL_WARN)}{len(result.skipped)}{_c(RESET)} skipped  "
        f"{_c(FG_MUTED)}|{_c(RESET)}  "
        f"{_c(COL_ERR)}{len(result.errors)}{_c(RESET)} errors",
        col=COL_OK if not result.errors else COL_ERR,
    )


# ── history ────────────────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    entries = list_history(limit=9999 if getattr(args, "all", False) else 50)
    if not entries:
        _warn("No history found. Run 'foldr <path>' to start.")
        return

    _rule("Operation History")
    print()
    try:
        from tabulate import tabulate  # type: ignore[import]
        rows = [
            [e.get("id","?"), e.get("op_type","organize"),
             e.get("timestamp","")[:16].replace("T"," "),
             Path(e.get("base","?")).name, str(e.get("total_files",0))]
            for e in entries
        ]
        print(tabulate(rows, headers=["ID","Type","Time","Directory","Files"],
                       tablefmt="rounded_outline"))
    except ImportError:
        for e in entries:
            ts = e.get("timestamp","")[:16].replace("T"," ")
            ot = e.get("op_type","organize")
            print(
                f"  {_c(ACCENT)}{e.get('id','?')}{_c(RESET)}"
                f"  {_c(FG_MUTED)}{op_icon(ot)} {ljust(ot,10)}{_c(RESET)}"
                f"  {ts}  {Path(e.get('base','?')).name}"
                f"  {_c(FG_DIM)}{e.get('total_files',0)} files{_c(RESET)}"
            )
    print()
    _dim("To undo any operation: foldr undo --id <ID>")


# ── config ─────────────────────────────────────────────────────────────────────

def cmd_config(args: argparse.Namespace) -> None:
    foldr_dir = Path.home() / ".foldr"
    cfg_path  = default_config_path()

    if getattr(args, "edit", False):
        # Decide which file to edit: config.toml or .foldrignore
        edit_ignore = getattr(args, "ignore_file", False)
        target_file = (foldr_dir / ".foldrignore") if edit_ignore else cfg_path
        # Ensure the file exists before opening
        if not target_file.exists():
            target_file.parent.mkdir(parents=True, exist_ok=True)
            if edit_ignore:
                target_file.write_text(
                    "# FOLDR global ignore rules\n"
                    "# One pattern per line. Applied to every foldr run.\n"
                    "# Disable for one run with: foldr <path> --no-ignore\n"
                    "#\n# Examples:\n# *.tmp\n# *.bak\n# desktop.ini\n",
                    encoding="utf-8",
                )
        import shutil as sh
        editor = (
            os.environ.get("VISUAL")
            or os.environ.get("EDITOR")
            or ("notepad" if _IS_WIN else "nano")
        )
        if sh.which(editor):
            os.execvp(editor, [editor, str(target_file)])
        else:
            _err(f"Editor not found: {editor}")
            _dim(f"Edit manually: {target_file}")
        return

    _rule("FOLDR Config")
    print()

    def _show(label: str, path: Path) -> None:
        exists = f"{_c(COL_OK)}(exists){_c(RESET)}" if path.exists() else f"{_c(FG_MUTED)}(not set){_c(RESET)}"
        _print(f"  {_c(FG_DIM)}{label:<24}{_c(RESET)}  {path}  {exists}")

    _show("Config directory",   foldr_dir)
    _show("Category config",    cfg_path)
    _show("Global ignore",      foldr_dir / ".foldrignore")
    _show("History",            foldr_dir / "history")
    _show("Watch logs",         foldr_dir / "watch_logs")
    _show("Active watchers",    foldr_dir / "watches.json")
    print()
    _dim("Edit config:    foldr config --edit")
    _dim("Category docs:  see FOLDR_MANUAL.md  or  foldr --help")


# ── dedup ───────────────────────────────────────────────────────────────────────

def cmd_dedup(
    target: Path, strat_str: str, recursive: bool,
    max_depth: int | None, preview: bool, verbose: bool,
) -> None:
    stmap = {
        "keep-newest":  DedupeStrategy.KEEP_NEWEST,
        "keep-oldest":  DedupeStrategy.KEEP_OLDEST,
        "keep-largest": DedupeStrategy.KEEP_LARGEST,
    }
    _rule("Duplicate Detection")
    _warn("Dedup permanently deletes files. This CANNOT be undone via 'foldr undo'.")
    print()
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
            [truncate(g.keep.name, 34) if g.keep else "?",
             truncate(rem.name, 34),
             fmt_size(g.keep.stat().st_size if g.keep and g.keep.exists() else 0)]
            for g in groups[:60]
            for rem in g.remove
        ]
        print(tabulate(rows, headers=["Keep","Remove","Size"], tablefmt="rounded_outline"))
    except ImportError:
        for g in groups[:30]:
            for rem in g.remove:
                print(f"  {_c(COL_OK)}keep{_c(RESET)} {g.keep.name if g.keep else '?'}"
                      f"  {_c(COL_ERR)}del{_c(RESET)}  {rem.name}")

    if total_rem > 60:
        _dim(f"... and {total_rem-60} more")
    print()

    if preview:
        _warn(f"preview — {total_rem} files would be removed. Nothing changed.")
        return

    ok = _confirm(
        f"⚠  Permanently delete {total_rem} duplicate files? (strategy: {strat_str})",
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
    _dim("Recorded in history, but files cannot be restored via 'foldr undo'.")


# ── organize ───────────────────────────────────────────────────────────────────

def cmd_organize(
    target: Path, args: argparse.Namespace, template: dict | None,
) -> None:
    preview    = args.preview
    ignore     = _build_ignore(args)
    no_ignore  = getattr(args, "no_ignore", False)
    show_ign   = getattr(args, "show_ignored", False)
    verbose    = args.verbose

    _rule(f"Scanning  {target.name}/")

    # Spinner when not in TTY
    spinner_done = threading.Event()
    if not _QUIET and not is_tty():
        def _spin() -> None:
            i = 0
            while not spinner_done.is_set():
                sys.stdout.write(f"\r  {SPINNER[i%4]}  Scanning...")
                sys.stdout.flush()
                time.sleep(0.1); i += 1
            sys.stdout.write("\r" + " "*30 + "\r")
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
        global_ignore=not no_ignore,   # global ignore ON by default, OFF with --no-ignore
    )
    spinner_done.set()

    # --show-ignored: list everything that got skipped
    if show_ign and not _QUIET:
        ig_files  = getattr(prev, "_ignored_list", [])
        ig_count  = getattr(prev, "ignored_files", 0)
        print()
        _rule("Ignored files")
        if ig_files:
            for fname, reason in ig_files[:50]:
                print(f"  {_c(FG_MUTED)}{fname:<40}{_c(RESET)}  {_c(FG_DIM)}{reason}{_c(RESET)}")
            if len(ig_files) > 50:
                _dim(f"... and {len(ig_files)-50} more")
        else:
            _dim(f"{ig_count} files ignored (pattern details unavailable — upgrade organizer)")
        print()

    if not prev.actions:
        _box(
            f"  {_c(COL_OK+BOLD)}Nothing to organize — directory is already tidy!{_c(RESET)}",
            col=COL_OK,
        )
        return

    n = len(prev.records)

    # Show preview table
    _print_preview(prev, preview)

    if preview:
        _print_summary(
            {k: v for k, v in prev.categories.items() if v},
            n, prev.other_files, getattr(prev, "ignored_files", 0),
            time.monotonic()-t0, dry=True,
        )
        return

    confirmed = _confirm(f"Move {n} files?", default=True)
    if not confirmed:
        _warn("Cancelled — nothing was moved.")
        print(); return

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
        global_ignore=not no_ignore,
    )
    elapsed = time.monotonic() - t_exec

    moved_n = len(result.records)

    if not _QUIET:
        bar = pbar(1.0, 30)
        print(f"  {bar}  {_c(ACCENT+BOLD)}{moved_n}{_c(RESET)} files moved")

    if verbose and not _QUIET:
        print()
        for r in result.records:
            dest = Path(r.destination).parent.name
            col  = _c(cat_fg(r.category))
            rst  = _c(RESET)
            print(
                f"  {col}{cat_icon(r.category)}{rst}  "
                f"{_c(FG_BRIGHT)}{truncate(r.filename, 40):<40}{rst}  "
                f"{_c(FG_MUTED)}->{rst}  {col}{dest}/{rst}"
            )

    log_path = save_history(result.records, target, dry_run=False, op_type="organize")
    if log_path and verbose:
        _dim(f"History: {log_path.name}")

    _print_summary(
        {k: v for k, v in result.categories.items() if v},
        moved_n, result.other_files,
        getattr(result, "ignored_files", 0),
        elapsed, dry=False,
    )

    # Offer to clean empty dirs
    scan = scan_empty_dirs(target)
    if scan.found and not _QUIET:
        n_empty = len(scan.found)
        _warn(f"Found {n_empty} empty {'directory' if n_empty==1 else 'directories'}.")
        if _confirm(f"Remove {n_empty} empty directories?", default=False):
            removed = remove_empty_dirs(scan.found)
            _ok(f"Removed {len(removed.removed)} empty directories.")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    global _QUIET, _NOCOLOR

    raw = sys.argv[1:]

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
    _NOCOLOR = not is_tty() or bool(os.environ.get("NO_COLOR"))

    # Auto-create config.toml with boilerplate if first run
    if not _QUIET and sub != "_watch-daemon":
        try:
            created = not default_config_path().exists()
            ensure_config_exists()
            if created:
                _dim(f"Created config: {default_config_path()}")
        except Exception:
            pass

    if not _QUIET and sub != "_watch-daemon":
        _banner()

    # Dispatch
    if sub == "config":        cmd_config(args);               return
    if sub == "watch":         cmd_watch(raw, args);            return
    if sub == "unwatch":       cmd_unwatch(raw);                return
    if sub == "watches":       cmd_watches();                   return
    if sub == "_watch-daemon": cmd_watch_daemon(raw, args);     return
    if sub == "undo":          cmd_undo(args);                  return
    if sub == "history":       cmd_history(args);               return

    # Resolve target directory
    path_candidates = [a for a in raw if not a.startswith("-") and a not in _SUBCMDS]
    raw_path = path_candidates[0] if path_candidates else None

    if not raw_path:
        cwd = Path.cwd()
        _box(
            f"  No path given.\n\n"
            f"  Target:  {_c(ACCENT+BOLD)}{cwd}{_c(RESET)}\n\n"
            f"  {_c(FG_MUTED)}Tip: foldr ~/Downloads{_c(RESET)}\n"
            f"  {_c(FG_MUTED)}     Paths with spaces: foldr \"My Downloads\"{_c(RESET)}",
        )
        if not _confirm(f"Organize current directory ({cwd.name})?", default=False):
            _dim("Cancelled.")
            return
        target = cwd
    else:
        target = Path(raw_path).resolve()

    if not target.exists() or not target.is_dir():
        _err(f"Not a valid directory: {target}")
        _dim("Tip: paths with spaces must be quoted — e.g.  foldr \"My Downloads\"")
        sys.exit(1)

    template = _load_template(args.config)

    if args.dedup:
        cmd_dedup(
            target, args.dedup, args.recursive,
            getattr(args, "depth", None), args.preview, args.verbose,
        )
        return

    cmd_organize(target, args, template)


if __name__ == "__main__":
    main()