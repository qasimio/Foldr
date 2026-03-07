"""
foldr.cli
~~~~~~~~~
FOLDR v4 — Full CLI with world-class TUI.

Subcommand dispatch happens BEFORE argparse so subcommands are never
accidentally eaten as the positional <path> argument.

Commands
--------
  foldr [path]                        organize (interactive TUI on TTY)
  foldr [path] --dry-run              preview only
  foldr [path] --recursive [-d N]
  foldr [path] --deduplicate <strat>
  foldr [path] --ignore "*.log" ...
  foldr [path] --config file.toml
  foldr [path] --verbose / --quiet
  foldr [path] --no-interactive       skip TUI, plain prompts
  foldr watch [path]
  foldr undo [--id ID] [--dry-run]
  foldr history [--all]
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import threading
from pathlib import Path

from foldr import output as out
from foldr.ansi import term_size, BCYAN, BGREEN, BYELLOW, BRED, BWHITE, MUTED, RESET, BOLD
from foldr.config_loader import load_template
from foldr.dedup import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs import remove_empty_dirs, scan_empty_dirs
from foldr.history import (
    get_history_entry, get_latest_history,
    list_history, save_history, undo_operation,
)
from foldr.models import DedupeStrategy
from foldr.organizer import organize_folder


# ─────────────────────────────────────────────────────────────────────────────
# TTY detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_tty() -> bool:
    return (
        sys.stdout.isatty()
        and sys.stdin.isatty()
        and os.environ.get("TERM", "dumb") != "dumb"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="foldr",
        description="FOLDR v4 — Smart File Organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  foldr ~/Downloads\n"
            "  foldr ~/Downloads --dry-run\n"
            "  foldr ~/Downloads --recursive --max-depth 3\n"
            "  foldr ~/Downloads --deduplicate keep-newest\n"
            "  foldr ~/Downloads --ignore '*.tmp' 'node_modules/'\n"
            "  foldr watch ~/Downloads\n"
            "  foldr undo\n"
            "  foldr undo --id a1b2c3\n"
            "  foldr history\n"
            "  foldr history --all\n"
        ),
    )
    p.add_argument("path", nargs="?", help="Directory to organize")
    p.add_argument("--dry-run",    action="store_true",
                   help="Preview — no files are moved")
    p.add_argument("--recursive",  action="store_true",
                   help="Recurse into subdirectories")
    p.add_argument("--max-depth",  type=int, metavar="N",
                   help="Max recursion depth (requires --recursive)")
    p.add_argument("--follow-symlinks", action="store_true",
                   help="Follow symbolic links when recursing")
    p.add_argument("--smart",      action="store_true",
                   help="MIME detection (catches spoofed extensions)")
    p.add_argument("--deduplicate",
                   choices=["keep-newest", "keep-largest", "keep-oldest"],
                   metavar="{keep-newest,keep-largest,keep-oldest}",
                   help="Find and remove duplicate files")
    p.add_argument("--ignore", nargs="+", metavar="PATTERN",
                   help="Ignore patterns  e.g. '*.log' 'tmp/'")
    p.add_argument("--config", metavar="FILE",
                   help="Path to custom TOML config")
    p.add_argument("--verbose",    action="store_true")
    p.add_argument("--quiet",      action="store_true",
                   help="Suppress all non-error output")
    p.add_argument("--no-interactive", action="store_true",
                   help="Disable TUI (plain text output)")
    # undo / history flags
    p.add_argument("--id",  help="History entry ID for undo")
    p.add_argument("--all", action="store_true",
                   help="Show full history (foldr history --all)")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Template loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_template(config_arg: str | None, quiet: bool) -> dict | None:
    if config_arg:
        config_path = Path(config_arg)
        try:
            template, label = load_template(config_path)
            if not quiet:
                out.dim(f"Config: {label}")
            return template
        except FileNotFoundError as e:
            out.error(str(e))
            sys.exit(1)
    else:
        template, label = load_template(None)
        if label and not quiet:
            out.dim(f"Config: {label}")
        return template


# ─────────────────────────────────────────────────────────────────────────────
# watch
# ─────────────────────────────────────────────────────────────────────────────

def cmd_watch(raw_argv: list[str], args: argparse.Namespace) -> None:
    # Extract the watch target directory from raw argv
    try:
        wi = raw_argv.index("watch")
        candidates = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        target_str = candidates[0] if candidates else None
    except (ValueError, IndexError):
        target_str = None

    target = Path(target_str).resolve() if target_str else Path.cwd()
    if not target.is_dir():
        out.error(f"'{target}' is not a valid directory.")
        sys.exit(1)

    template = _load_template(getattr(args, "config", None), args.quiet)

    from foldr.watch import run_watch
    run_watch(
        base=target,
        template=template or {},
        dry_run=args.dry_run,
        extra_ignore=args.ignore or [],
        use_tui=_is_tty() and not args.no_interactive,
    )


# ─────────────────────────────────────────────────────────────────────────────
# undo
# ─────────────────────────────────────────────────────────────────────────────

def cmd_undo(args: argparse.Namespace) -> None:
    if not args.quiet:
        out.rule("Undo")

    log_data = (
        get_history_entry(args.id) if getattr(args, "id", None)
        else get_latest_history()
    )

    if not log_data:
        out.warn("No history found — nothing to undo.")
        return

    ts    = log_data.get("timestamp", "")[:19].replace("T", " ")
    base  = log_data.get("base", "")
    total = log_data.get("total_files", 0)
    eid   = log_data.get("id", "?")

    if not args.quiet:
        out.panel(
            f"  {BCYAN}{BOLD}ID:{RESET}        {eid}\n"
            f"  {BCYAN}{BOLD}Time:{RESET}      {ts}\n"
            f"  {BCYAN}{BOLD}Directory:{RESET} {base}\n"
            f"  {BCYAN}{BOLD}Files:{RESET}     {total}",
            title="Undo Preview",
            col=BYELLOW,
        )

    dry = args.dry_run
    if not dry and not args.quiet:
        if _is_tty() and not args.no_interactive:
            from foldr.tui    import PreviewScreen
            from foldr.screen import Screen
            from foldr.widgets import confirm_dialog
            scr = Screen()
            scr.enter_alt()
            try:
                confirmed = confirm_dialog(
                    scr,
                    title=" ↩ Undo Operation ",
                    body=[
                        f"{BWHITE}Restore {BCYAN}{BOLD}{total}{RESET}{BWHITE} files{RESET}",
                        f"{BWHITE}from operation {BCYAN}{BOLD}{eid}{RESET}",
                        "",
                        f"{MUTED}Files move back to their original locations.{RESET}",
                        f"{MUTED}Use  foldr history  to view all operations.{RESET}",
                    ],
                    yes=" ↩ Undo ",
                    no=" ✗ Cancel ",
                    danger=True,
                )
            finally:
                scr.exit_alt()
        else:
            confirmed = out.confirm_prompt(
                f"Restore {total} files from operation {eid}?",
                default=False,
            )
        if not confirmed:
            out.dim("Cancelled.")
            return

    result = undo_operation(log_data, dry_run=dry)

    prefix = f"  {BYELLOW}[DRY]{RESET}" if dry else ""
    for r in result.restored:
        print(f"{prefix}  {BGREEN}↩{RESET}  {r}")
    for s in result.skipped:
        out.warn(s)
    for e in result.errors:
        out.error(e)

    if not args.quiet:
        print()
        print(
            f"  {BGREEN}{BOLD}{len(result.restored)}{RESET} restored  "
            f"{MUTED}·{RESET}  "
            f"{BYELLOW}{len(result.skipped)}{RESET} skipped  "
            f"{MUTED}·{RESET}  "
            f"{BRED}{len(result.errors)}{RESET} errors"
        )


# ─────────────────────────────────────────────────────────────────────────────
# history
# ─────────────────────────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    limit   = None if getattr(args, "all", False) else 50
    entries = list_history(limit=limit or 50)

    if not entries:
        out.warn("No history found.")
        return

    if _is_tty() and not args.no_interactive and not args.quiet:
        from foldr.tui import HistoryScreen
        scr = HistoryScreen(entries)
        action, eid = scr.run()
        if action == "undo" and eid:
            args.id = eid
            cmd_undo(args)
        return

    # Plain-text fallback
    out.rule("Operation History")
    print()
    from tabulate import tabulate
    rows = []
    for e in entries:
        ts    = e.get("timestamp", "")[:19].replace("T", " ")
        base  = Path(e.get("base", "?")).name
        total = e.get("total_files", 0)
        eid   = e.get("id", "?")[:6]
        rows.append([eid, ts, base, str(total)])
    print(tabulate(rows, headers=["ID", "Time", "Directory", "Files"],
                   tablefmt="rounded_outline"))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# deduplicate
# ─────────────────────────────────────────────────────────────────────────────

def cmd_deduplicate(target: Path, strategy_str: str,
                    recursive: bool, max_depth: int | None,
                    dry_run: bool, quiet: bool,
                    no_interactive: bool) -> None:
    strategy_map = {
        "keep-newest":  DedupeStrategy.KEEP_NEWEST,
        "keep-oldest":  DedupeStrategy.KEEP_OLDEST,
        "keep-largest": DedupeStrategy.KEEP_LARGEST,
    }
    strategy = strategy_map[strategy_str]

    if not quiet:
        out.rule("Duplicate Detection")
        out.info(f"Scanning {target} …")

    files  = collect_files(target, recursive=recursive, max_depth=max_depth)
    groups = find_duplicates(files)

    if not groups:
        out.success("No duplicates found!")
        return

    total_removable = sum(len(g.files) - 1 for g in groups)
    out.warn(
        f"Found {len(groups)} duplicate groups "
        f"({total_removable} files removable)"
    )
    print()

    for g in groups:
        resolve_strategy(g, strategy)

    # Preview table
    from tabulate import tabulate
    rows = []
    for g in groups[:40]:
        keep = g.keep.name if g.keep else "?"
        size = g.keep.stat().st_size if g.keep and g.keep.exists() else 0
        for rem in g.remove:
            rows.append([keep, rem.name, out.fmt_size(size) if hasattr(out, "fmt_size") else str(size)])
    from foldr.ansi import fmt_size
    rows2 = []
    for g in groups[:40]:
        keep = g.keep.name if g.keep else "?"
        size = g.keep.stat().st_size if g.keep and g.keep.exists() else 0
        for rem in g.remove:
            rows2.append([keep, rem.name, fmt_size(size)])
    print(tabulate(rows2, headers=["Keep", "Remove", "Size"],
                   tablefmt="rounded_outline"))
    if total_removable > 40:
        out.dim(f"… and {total_removable - 40} more")
    print()

    if dry_run:
        out.warn(f"DRY RUN — {total_removable} files would be removed.")
        return

    if _is_tty() and not no_interactive:
        from foldr.screen  import Screen
        from foldr.widgets import confirm_dialog
        scr = Screen()
        scr.enter_alt()
        try:
            confirmed = confirm_dialog(
                scr,
                title=" 🗑  Remove Duplicates ",
                body=[
                    f"{BWHITE}Delete {BRED}{BOLD}{total_removable}{RESET}{BWHITE} duplicate files?{RESET}",
                    f"{BWHITE}Strategy: {BCYAN}{strategy_str}{RESET}",
                    "",
                    f"{MUTED}The 'keep' file is NOT deleted.{RESET}",
                    f"{MUTED}This operation cannot be undone via 'foldr undo'.{RESET}",
                ],
                yes=" 🗑 Delete ",
                no=" ✗ Cancel ",
                danger=True,
            )
        finally:
            scr.exit_alt()
    else:
        confirmed = out.confirm_prompt(
            f"Delete {total_removable} duplicate files?", default=False
        )

    if not confirmed:
        out.dim("Cancelled.")
        return

    removed = 0
    for g in groups:
        for path in g.remove:
            try:
                path.unlink()
                removed += 1
            except OSError as e:
                out.error(f"Could not remove {path.name}: {e}")

    out.success(f"Removed {removed} duplicate files.")


# ─────────────────────────────────────────────────────────────────────────────
# main organize flow
# ─────────────────────────────────────────────────────────────────────────────

def cmd_organize(target: Path, args: argparse.Namespace, template: dict | None) -> None:
    use_tui = _is_tty() and not args.no_interactive and not args.quiet
    dry     = args.dry_run
    quiet   = args.quiet

    if not quiet:
        out.rule(f"Scanning  {target.name}")

    # ── Scan phase (always dry-run first to collect planned actions) ────────
    t_scan = time.monotonic()
    spinner_done = threading.Event()

    if not quiet and not use_tui:
        def _spin():
            frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
            i = 0
            while not spinner_done.is_set():
                sys.stdout.write(f"\r  {BCYAN}{frames[i%10]}{RESET}  Scanning…")
                sys.stdout.flush()
                time.sleep(0.08)
                i += 1
            sys.stdout.write("\r" + " " * 30 + "\r")
            sys.stdout.flush()
        threading.Thread(target=_spin, daemon=True).start()

    preview = organize_folder(
        base=target, dry_run=True,
        recursive=args.recursive,
        max_depth=args.max_depth,
        follow_symlinks=args.follow_symlinks,
        extra_ignore=args.ignore or [],
        category_template=template,
        smart=args.smart,
    )
    spinner_done.set()
    t_scan_done = time.monotonic()

    # ── Nothing to do ────────────────────────────────────────────────────────
    if not preview.actions:
        out.panel(
            f"  {BGREEN}{BOLD}✓  Nothing to organize — directory is already tidy!{RESET}",
            col=BGREEN,
        )
        return

    n_moves = len(preview.records)

    # ── TUI Preview (or plain table) ─────────────────────────────────────────
    if use_tui:
        from foldr.tui import PreviewScreen
        pscr = PreviewScreen(preview.records, target, dry)
        confirmed = pscr.run()
    else:
        # Plain-text preview table
        if not quiet:
            _print_plain_preview(preview, dry)
        if dry:
            elapsed = t_scan_done - t_scan
            out.summary_table(
                {k: v for k, v in preview.categories.items() if v > 0},
                n_moves, preview.other_files, preview.ignored_files,
                elapsed, dry_run=True,
            )
            return
        confirmed = out.confirm_prompt(
            f"Execute {n_moves} moves?", default=True
        )

    if not confirmed:
        out.warn("Cancelled — no files were moved.")
        print()
        return

    # ── Dry-run: just show summary, no execution ─────────────────────────────
    if dry:
        elapsed = t_scan_done - t_scan
        out.summary_table(
            {k: v for k, v in preview.categories.items() if v > 0},
            n_moves, preview.other_files, preview.ignored_files,
            elapsed, dry_run=True,
        )
        return

    # ── Execution ────────────────────────────────────────────────────────────
    if not quiet:
        out.rule("Executing")

    t_exec = time.monotonic()

    if use_tui:
        from foldr.tui import ExecutionScreen
        with ExecutionScreen(n_moves, target, dry_run=False) as exec_scr:
            # Run organizer in a thread, update screen from main thread
            result_holder: list = []
            err_holder:    list = []

            def _run():
                try:
                    r = organize_folder(
                        base=target, dry_run=False,
                        recursive=args.recursive,
                        max_depth=args.max_depth,
                        follow_symlinks=args.follow_symlinks,
                        extra_ignore=args.ignore or [],
                        category_template=template,
                        smart=args.smart,
                    )
                    result_holder.append(r)
                except Exception as e:
                    err_holder.append(e)

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            # Poll progress (organizer doesn't have callbacks yet, so we
            # watch record count growing via a second preview approach)
            # For now, animate while waiting
            frame = 0
            frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
            while t.is_alive():
                exec_scr.scr.resize()
                exec_scr._draw()
                time.sleep(0.05)
                frame += 1

            t.join()
            if err_holder:
                raise err_holder[0]
            result = result_holder[0]

            # Final draw with complete count
            exec_scr.done = len(result.records)
            exec_scr._draw()
            time.sleep(0.4)  # let user see 100%
    else:
        # Plain progress bar
        result = organize_folder(
            base=target, dry_run=False,
            recursive=args.recursive,
            max_depth=args.max_depth,
            follow_symlinks=args.follow_symlinks,
            extra_ignore=args.ignore or [],
            category_template=template,
            smart=args.smart,
        )
        if not quiet:
            out.progress_line(len(result.records), n_moves,
                              elapsed=time.monotonic() - t_exec)
            print()

    elapsed = time.monotonic() - t_exec

    # ── Save history ─────────────────────────────────────────────────────────
    log_path = save_history(result.records, target, dry_run=False)
    if log_path and args.verbose:
        out.dim(f"History saved: {log_path}")

    # ── Verbose action log ───────────────────────────────────────────────────
    if args.verbose:
        for r in result.records:
            dest = Path(r.destination).parent.name
            out.print_move(r.filename, dest, r.category)

    # ── Summary ──────────────────────────────────────────────────────────────
    if not quiet:
        out.summary_table(
            {k: v for k, v in result.categories.items() if v > 0},
            len(result.records), result.other_files, result.ignored_files,
            elapsed, dry_run=False,
        )

        # ── Offer empty dir cleanup ───────────────────────────────────────────
        scan = scan_empty_dirs(target)
        if scan.found:
            out.warn(
                f"Found {len(scan.found)} empty "
                f"{'directory' if len(scan.found)==1 else 'directories'}."
            )
            if use_tui:
                from foldr.screen  import Screen
                from foldr.widgets import confirm_dialog
                scr = Screen()
                scr.enter_alt()
                try:
                    do_clean = confirm_dialog(
                        scr,
                        title=" 🗑  Empty Directories ",
                        body=[
                            f"{BWHITE}Remove {BYELLOW}{BOLD}{len(scan.found)}{RESET}{BWHITE} empty directories?{RESET}",
                        ],
                        yes=" 🗑 Remove ",
                        no=" ✗ Skip ",
                        danger=False,
                    )
                finally:
                    scr.exit_alt()
            else:
                do_clean = out.confirm_prompt(
                    "Remove empty directories?", default=False
                )
            if do_clean:
                removed = remove_empty_dirs(scan.found)
                out.success(f"Removed {len(removed.removed)} empty directories.")


def _print_plain_preview(preview, dry: bool) -> None:
    """Fallback plain-text preview table."""
    from tabulate import tabulate
    from foldr.ansi import cat_icon
    rows = []
    for r in preview.records[:80]:
        dest = Path(r.destination).parent.name
        rows.append([r.filename, f"→ {dest}/", r.category])
    print()
    print(tabulate(rows, headers=["File", "Destination", "Category"],
                   tablefmt="rounded_outline", maxcolwidths=[40, 25, 18]))
    total = len(preview.records)
    if total > 80:
        out.dim(f"… and {total - 80} more files")
    print()
    if dry:
        out.warn(
            f"DRY RUN — {BYELLOW}{BOLD}{total}{RESET} files would be moved. "
            f"No changes made."
        )
    else:
        out.info(f"{total} files will be moved.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    raw = sys.argv[1:]

    # ── Subcommand dispatch (before argparse) ─────────────────────────────────
    # Find first non-flag positional
    subcmds = {"watch", "undo", "history"}
    first_pos = next(
        (a for a in raw if not a.startswith("-")), None
    )

    parser = _build_parser()
    args, _ = parser.parse_known_args(raw)

    # ── Banner ────────────────────────────────────────────────────────────────
    if not args.quiet:
        if _is_tty() and not args.no_interactive:
            try:
                from foldr.tui import splash
                splash(duration=0.7)
            except Exception:
                pass
        out.banner()

    # ── Route subcommands ────────────────────────────────────────────────────
    if first_pos == "watch":
        cmd_watch(raw, args)
        return

    if first_pos == "undo":
        cmd_undo(args)
        return

    if first_pos == "history":
        cmd_history(args)
        return

    # ── Resolve target directory ─────────────────────────────────────────────
    if args.path is None or first_pos is None:
        cwd = Path.cwd()
        if not args.quiet:
            out.panel(
                f"  {BWHITE}No directory specified.{RESET}\n\n"
                f"  Target:  {BCYAN}{BOLD}{cwd}{RESET}\n\n"
                f"  {MUTED}Pass a path to organize a specific directory.{RESET}",
                title="FOLDR",
                col=BCYAN,
            )
        if _is_tty() and not args.no_interactive:
            from foldr.screen  import Screen
            from foldr.widgets import confirm_dialog
            scr = Screen()
            scr.enter_alt()
            try:
                confirmed = confirm_dialog(
                    scr,
                    title=" 📁 Organize Current Directory ",
                    body=[
                        f"{BWHITE}Organize: {BCYAN}{BOLD}{cwd.name}/{RESET}",
                        f"{BWHITE}Full path: {MUTED}{cwd}{RESET}",
                    ],
                    yes=" ✓ Organize ",
                    no=" ✗ Cancel ",
                )
            finally:
                scr.exit_alt()
        else:
            confirmed = out.confirm_prompt(
                f"Organize {cwd.name} (current directory)?",
                default=False,
            )
        if not confirmed:
            out.dim("Cancelled.")
            return
        target = cwd
    else:
        target = Path(args.path).resolve()

    if not target.exists() or not target.is_dir():
        out.error(f"'{target}' is not a valid directory.")
        sys.exit(1)

    template = _load_template(args.config, args.quiet)

    if args.deduplicate:
        cmd_deduplicate(
            target=target,
            strategy_str=args.deduplicate,
            recursive=args.recursive,
            max_depth=args.max_depth,
            dry_run=args.dry_run,
            quiet=args.quiet,
            no_interactive=args.no_interactive,
        )
        return

    cmd_organize(target, args, template)


if __name__ == "__main__":
    main()