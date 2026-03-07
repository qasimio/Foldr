"""
foldr.cli
~~~~~~~~~
FOLDR v4 — Clean CLI.

No Rich, no pyfiglet, no curses.
Uses foldr.tui for interactive screens, foldr.term for plain output.

Subcommand routing is done BEFORE argparse so 'watch', 'undo', 'history'
are never swallowed as the positional <path> argument.
"""
from __future__ import annotations
import argparse, os, sys, time, threading
from pathlib import Path

from foldr.term import (
    is_tty, term_wh, cat_fg, cat_icon, fmt_size, strip, vlen, pad_to,
    pbar, SPINNER, RESET, BOLD, DIM, MUTED,
    BCYN, CYN, BGRN, BYLW, BRED, BWHT, WHT, BBLK,
    bg256, rgb_bg, rgb_fg,
)
from foldr.config_loader  import load_template
from foldr.dedup          import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs     import remove_empty_dirs, scan_empty_dirs
from foldr.history        import (get_history_entry, get_latest_history,
                                   list_history, save_history, undo_operation)
from foldr.models         import DedupeStrategy
from foldr.organizer      import organize_folder

# ── Global flags (set in main) ────────────────────────────────────────────────
_QUIET        = False
_NO_INTER     = False
_TUI_ALLOWED  = False      # True only when TTY + not --no-interactive

# ── Output helpers ─────────────────────────────────────────────────────────────
def _w() -> int: return min(100, term_wh()[0])

def _rule(title: str = "", col: str = BCYN) -> None:
    if _QUIET: return
    w = _w()
    if not title:
        print(col + "─"*w + RESET); return
    side = max(1,(w-len(title)-2)//2)
    print(col+"─"*side+RESET+f" {BOLD}{title}{RESET} "+col+"─"*side+RESET)

def _banner() -> None:
    if _QUIET: return
    cols = [BCYN+BOLD, BCYN+BOLD, CYN+BOLD, CYN, BCYN, BCYN]
    rows = [
        " ███████╗ ██████╗ ██╗     ██████╗ ██████╗ ",
        " ██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗",
        " █████╗  ██║   ██║██║     ██║  ██║██████╔╝",
        " ██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗",
        " ██║     ╚██████╔╝███████╗██████╔╝██║  ██║",
        " ╚═╝      ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝",
    ]
    print()
    for c, r in zip(cols, rows): print(f"  {c}{r}{RESET}")
    print(f"\n  {MUTED}v4  ·  Smart File Organizer  ·  github.com/qasimio/Foldr{RESET}\n")

def _panel(body: str, title: str = "", col: str = BCYN) -> None:
    if _QUIET: return
    w     = _w()
    inner = w - 4
    lines = body.split("\n")
    t = f" {title} " if title else ""
    tl= len(t)
    if tl and tl < inner-2:
        pad_l = (inner-tl)//2
        pad_r = inner-tl-pad_l
        top = col+"╭"+"─"*pad_l+BOLD+t+RESET+col+"─"*pad_r+"╮"+RESET
    else:
        top = col+"╭"+"─"*inner+"╮"+RESET
    print(top)
    for line in lines:
        lv   = vlen(line)
        rest = max(0, inner-lv-2)
        print(col+"│"+RESET+"  "+line+" "*rest+"  "+col+"│"+RESET)
    print(col+"╰"+"─"*inner+"╯"+RESET)

def _ok(msg: str)   -> None:
    if not _QUIET: print(f"  {BGRN}✓{RESET}  {msg}")
def _warn(msg: str) -> None:
    if not _QUIET: print(f"  {BYLW+BOLD}⚠{RESET}  {msg}")
def _err(msg: str)  -> None:
    print(f"  {BRED+BOLD}✗  Error:{RESET}  {msg}", file=sys.stderr)
def _dim(msg: str)  -> None:
    if not _QUIET: print(f"  {MUTED}{msg}{RESET}")
def _info(msg: str) -> None:
    if not _QUIET: print(f"  {BCYN}ℹ{RESET}  {msg}")

def _summary(cat_counts: dict, moved: int, other: int, ignored: int,
             elapsed: float, dry_run: bool) -> None:
    if _QUIET: return
    if not cat_counts: return
    w      = _w()
    bar_w  = max(12, w//4)
    total  = max(1, sum(cat_counts.values()))
    _rule("Summary")
    print()
    for cat, cnt in sorted(cat_counts.items(), key=lambda x:-x[1]):
        if cnt == 0: continue
        col  = cat_fg(cat)
        icon = cat_icon(cat)
        pct  = cnt/total
        fill = max(1, int(pct*bar_w))
        bar  = col+"█"*fill+MUTED+"░"*(bar_w-fill)+RESET
        print(f"  {col}{icon} {pad_to(cat,18)}{RESET}  {bar}  {col+BOLD}{cnt:>4}{RESET}  {MUTED}{pct*100:4.1f}%{RESET}")
    print()
    status = f"{BYLW+BOLD}● DRY RUN — no files were moved{RESET}" if dry_run else f"{BGRN+BOLD}✓ Files organized successfully{RESET}"
    _panel(
        f"  {status}\n\n"
        f"  {BCYN+BOLD}{moved}{RESET} moved  {MUTED}·{RESET}  "
        f"{BWHT}{other}{RESET} unrecognised  {MUTED}·{RESET}  "
        f"{BWHT}{ignored}{RESET} ignored  {MUTED}·{RESET}  {MUTED}{elapsed:.2f}s{RESET}",
        col=BYLW if dry_run else BGRN,
    )
    print()

def _confirm_plain(prompt: str, default: bool = False) -> bool:
    yn = f"[{'Y' if default else 'y'}/{'n' if default else 'N'}]"
    sys.stdout.write(f"\n  {BYLW+BOLD}?{RESET}  {BOLD}{prompt}{RESET}  {MUTED}{yn}{RESET}: ")
    sys.stdout.flush()
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); return False
    return (ans in ("y","yes")) if ans else default

def _plain_preview(preview, dry: bool) -> None:
    """Fallback plain-text preview when TUI unavailable."""
    try:
        from tabulate import tabulate
        rows = [[r.filename, f"→ {Path(r.destination).parent.name}/", r.category]
                for r in preview.records[:60]]
        print()
        print(tabulate(rows, headers=["File","Destination","Category"],
                       tablefmt="rounded_outline", maxcolwidths=[40,25,18]))
        n = len(preview.records)
        if n > 60: _dim(f"… and {n-60} more files")
    except ImportError:
        for r in preview.records[:30]:
            dest = Path(r.destination).parent.name
            col  = cat_fg(r.category)
            icon = cat_icon(r.category)
            print(f"  {col}{icon}{RESET}  {col+BOLD}{r.filename:<40}{RESET}  {MUTED}→{RESET}  {col}{dest}/{RESET}")
    print()
    n = len(preview.records)
    if dry:
        _warn(f"DRY RUN — {BYLW+BOLD}{n}{RESET} files would be moved. Nothing changed.")
    else:
        _info(f"{n} files will be moved.")

# ── Argument parser ────────────────────────────────────────────────────────────
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
            "  foldr watch ~/Downloads\n"
            "  foldr undo\n"
            "  foldr history\n"
        ),
    )
    p.add_argument("path",  nargs="?")
    p.add_argument("--dry-run",         action="store_true")
    p.add_argument("--recursive",       action="store_true")
    p.add_argument("--max-depth",       type=int, metavar="N")
    p.add_argument("--follow-symlinks", action="store_true")
    p.add_argument("--smart",           action="store_true")
    p.add_argument("--deduplicate",
                   choices=["keep-newest","keep-largest","keep-oldest"],
                   metavar="{keep-newest,keep-largest,keep-oldest}")
    p.add_argument("--ignore", nargs="+", metavar="PATTERN")
    p.add_argument("--config", metavar="FILE")
    p.add_argument("--verbose",          action="store_true")
    p.add_argument("--quiet",            action="store_true")
    p.add_argument("--no-interactive",   action="store_true")
    p.add_argument("--id",               help="History entry ID for undo")
    p.add_argument("--all",              action="store_true")
    return p

def _load_template(config_arg, quiet):
    if config_arg:
        try:
            tmpl, label = load_template(Path(config_arg))
            if not quiet: _dim(f"Config: {label}")
            return tmpl
        except FileNotFoundError as e:
            _err(str(e)); sys.exit(1)
    tmpl, label = load_template(None)
    if label and not quiet: _dim(f"Config: {label}")
    return tmpl

# ── watch ──────────────────────────────────────────────────────────────────────
def cmd_watch(raw_argv: list[str], args) -> None:
    try:
        wi = raw_argv.index("watch")
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        target_str = cands[0] if cands else None
    except (ValueError, IndexError):
        target_str = None
    target = Path(target_str).resolve() if target_str else Path.cwd()
    if not target.is_dir():
        _err(f"'{target}' is not a valid directory."); sys.exit(1)
    tmpl = _load_template(getattr(args,"config",None), args.quiet)
    from foldr.watch import run_watch
    run_watch(base=target, template=tmpl or {},
              dry_run=args.dry_run, extra_ignore=args.ignore or [],
              use_tui=_TUI_ALLOWED)

# ── undo ───────────────────────────────────────────────────────────────────────
def cmd_undo(args) -> None:
    _rule("Undo")
    log = (get_history_entry(args.id) if getattr(args,"id",None)
           else get_latest_history())
    if not log:
        _warn("No history found — nothing to undo."); return
    ts    = log.get("timestamp","")[:19].replace("T"," ")
    base  = log.get("base","")
    total = log.get("total_files",0)
    eid   = log.get("id","?")
    _panel(
        f"  {BCYN+BOLD}ID:{RESET}        {eid}\n"
        f"  {BCYN+BOLD}Time:{RESET}      {ts}\n"
        f"  {BCYN+BOLD}Directory:{RESET} {base}\n"
        f"  {BCYN+BOLD}Files:{RESET}     {total}",
        title="Undo Preview", col=BYLW,
    )
    if not args.dry_run:
        if _TUI_ALLOWED:
            from foldr.tui import confirm_dialog, Screen as _Scr
            scr = _Scr(); scr.enter()
            try:
                confirmed = confirm_dialog(scr, " ↩ Undo Operation ",
                    [f"{BWHT}Restore {BCYN+BOLD}{total}{RESET+BWHT} files from op {BCYN+BOLD}{eid}{RESET}",
                     f"{MUTED}Files move back to original locations.{RESET}"],
                    yes_label=" ↩ Undo ", no_label=" ✗ Cancel ", danger=True)
            finally:
                scr.exit()
        else:
            confirmed = _confirm_plain(f"Restore {total} files from op {eid}?", default=False)
        if not confirmed:
            _dim("Cancelled."); return
    result = undo_operation(log, dry_run=args.dry_run)
    pfx = f"  {BYLW}[DRY]{RESET}" if args.dry_run else ""
    for r in result.restored: print(f"{pfx}  {BGRN}↩{RESET}  {r}")
    for s in result.skipped:  _warn(s)
    for e in result.errors:   _err(e)
    print(f"\n  {BGRN+BOLD}{len(result.restored)}{RESET} restored  "
          f"{MUTED}·{RESET}  {BYLW}{len(result.skipped)}{RESET} skipped  "
          f"{MUTED}·{RESET}  {BRED}{len(result.errors)}{RESET} errors")

# ── history ────────────────────────────────────────────────────────────────────
def cmd_history(args) -> None:
    limit   = None if getattr(args,"all",False) else 50
    entries = list_history(limit=limit or 50)
    if not entries:
        _warn("No history found."); return
    if _TUI_ALLOWED:
        from foldr.tui import HistoryScreen
        action, eid = HistoryScreen(entries).run()
        if action == "undo" and eid:
            args.id = eid; cmd_undo(args)
        return
    _rule("Operation History"); print()
    try:
        from tabulate import tabulate
        rows = [[e.get("id","?")[:6],
                 e.get("timestamp","")[:19].replace("T"," "),
                 Path(e.get("base","?")).name,
                 str(e.get("total_files",0))] for e in entries]
        print(tabulate(rows, headers=["ID","Time","Directory","Files"], tablefmt="rounded_outline"))
    except ImportError:
        for e in entries:
            print(f"  {BCYN}{e.get('id','?')[:6]}{RESET}  {e.get('timestamp','')[:19]}  {Path(e.get('base','?')).name}  {e.get('total_files',0)} files")
    print()

# ── deduplicate ────────────────────────────────────────────────────────────────
def cmd_dedup(target, strat_str, recursive, max_depth, dry_run, verbose) -> None:
    strategy_map = {"keep-newest": DedupeStrategy.KEEP_NEWEST,
                    "keep-oldest": DedupeStrategy.KEEP_OLDEST,
                    "keep-largest": DedupeStrategy.KEEP_LARGEST}
    strategy = strategy_map[strat_str]
    _rule("Duplicate Detection")
    _info(f"Scanning {target} …")
    files  = collect_files(target, recursive=recursive, max_depth=max_depth)
    groups = find_duplicates(files)
    if not groups:
        _ok("No duplicates found!"); return
    total_rem = sum(len(g.files)-1 for g in groups)
    _warn(f"Found {len(groups)} duplicate groups  ({total_rem} files removable)")
    for g in groups: resolve_strategy(g, strategy)
    try:
        from tabulate import tabulate
        rows = [[g.keep.name if g.keep else "?", rem.name,
                 fmt_size(g.keep.stat().st_size if g.keep and g.keep.exists() else 0)]
                for g in groups[:40] for rem in g.remove]
        print("\n" + tabulate(rows, headers=["Keep","Remove","Size"], tablefmt="rounded_outline"))
    except ImportError:
        for g in groups[:20]:
            for rem in g.remove:
                print(f"  {BGRN}keep:{RESET} {g.keep.name if g.keep else '?'}  {BRED}del:{RESET} {rem.name}")
    if total_rem > 40: _dim(f"… and {total_rem-40} more")
    print()
    if dry_run:
        _warn(f"DRY RUN — {total_rem} files would be removed."); return
    if _TUI_ALLOWED:
        from foldr.tui import confirm_dialog, Screen as _Scr
        scr = _Scr(); scr.enter()
        try:
            confirmed = confirm_dialog(scr, " 🗑 Remove Duplicates ",
                [f"{BWHT}Delete {BRED+BOLD}{total_rem}{RESET+BWHT} duplicate files?{RESET}",
                 f"{BWHT}Strategy: {BCYN}{strat_str}{RESET}",
                 f"{MUTED}⚠ Cannot be undone via 'foldr undo'{RESET}"],
                yes_label=" 🗑 Delete ", no_label=" ✗ Cancel ", danger=True)
        finally:
            scr.exit()
    else:
        confirmed = _confirm_plain(f"Delete {total_rem} duplicate files?", default=False)
    if not confirmed:
        _dim("Cancelled."); return
    removed = 0
    for g in groups:
        for p in g.remove:
            try: p.unlink(); removed += 1
            except OSError as e: _err(f"Could not remove {p.name}: {e}")
    _ok(f"Removed {removed} duplicate files.")

# ── main organize ──────────────────────────────────────────────────────────────
def cmd_organize(target: Path, args, template) -> None:
    dry   = args.dry_run

    _rule(f"Scanning  {target.name}")

    # Scan with spinner
    spinner_done = threading.Event()
    if not _QUIET and not is_tty():
        def _spin():
            i = 0
            while not spinner_done.is_set():
                sys.stdout.write(f"\r  {BCYN}{SPINNER[i%10]}{RESET}  Scanning…")
                sys.stdout.flush(); time.sleep(0.08); i += 1
            sys.stdout.write("\r"+" "*30+"\r"); sys.stdout.flush()
        threading.Thread(target=_spin, daemon=True).start()

    t0 = time.monotonic()
    preview = organize_folder(
        base=target, dry_run=True,
        recursive=args.recursive, max_depth=args.max_depth,
        follow_symlinks=args.follow_symlinks,
        extra_ignore=args.ignore or [],
        category_template=template,
    )
    spinner_done.set()

    if not preview.actions:
        _panel(f"  {BGRN+BOLD}✓  Nothing to organize — directory is already tidy!{RESET}", col=BGRN)
        return

    n = len(preview.records)

    # ── Show preview (TUI or plain) ───────────────────────────────────────────
    if _TUI_ALLOWED:
        from foldr.tui import PreviewScreen
        confirmed = PreviewScreen(preview.records, target, dry).run()
    else:
        _plain_preview(preview, dry)
        if dry:
            _summary({k:v for k,v in preview.categories.items() if v},
                     n, preview.other_files, preview.ignored_files,
                     time.monotonic()-t0, dry_run=True)
            return
        confirmed = _confirm_plain(f"Execute {n} moves?", default=True)

    if not confirmed:
        _warn("Cancelled — no files were moved."); print(); return

    # Dry-run: skip execution entirely
    if dry:
        _summary({k:v for k,v in preview.categories.items() if v},
                 n, preview.other_files, preview.ignored_files,
                 time.monotonic()-t0, dry_run=True)
        return

    # ── Execute ────────────────────────────────────────────────────────────────
    _rule("Executing")
    t_exec = time.monotonic()

    if _TUI_ALLOWED:
        from foldr.tui import ExecutionScreen
        with ExecutionScreen(n, target) as xs:
            # Run organizer in background thread, poll for updates
            result_box: list = []
            err_box:    list = []
            done_evt = threading.Event()

            def _run():
                try:
                    r = organize_folder(
                        base=target, dry_run=False,
                        recursive=args.recursive, max_depth=args.max_depth,
                        follow_symlinks=args.follow_symlinks,
                        extra_ignore=args.ignore or [],
                        category_template=template,
                    )
                    result_box.append(r)
                except Exception as e:
                    err_box.append(e)
                finally:
                    done_evt.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            # Keep refreshing the execution screen while organizer runs.
            # We approximate progress by polling done count.
            last_done = 0
            while not done_evt.wait(timeout=0.05):
                # Estimate progress from result_box intermediate state isn't
                # available, so we animate the spinner via repeated redraws.
                xs._draw()

            t.join()
            if err_box: raise err_box[0]
            result = result_box[0]

            # Update done count and do one final draw showing 100%
            xs.done = len(result.records)
            for r in result.records:
                dest = Path(r.destination).parent.name
                xs.log.append((r.category, r.filename, dest))
            xs._draw()
            time.sleep(0.5)   # let user see 100%
    else:
        # Plain execution with progress bar
        result = organize_folder(
            base=target, dry_run=False,
            recursive=args.recursive, max_depth=args.max_depth,
            follow_symlinks=args.follow_symlinks,
            extra_ignore=args.ignore or [],
            category_template=template,
        )
        if not _QUIET:
            bar = pbar(1.0, 30)
            print(f"  Moving files…  {bar}  100%  {BGRN+BOLD}{len(result.records)}{RESET} files")

    elapsed = time.monotonic() - t_exec

    # Save history
    log_path = save_history(result.records, target, dry_run=False)
    if log_path and args.verbose: _dim(f"History saved: {log_path}")

    if args.verbose:
        for r in result.records:
            dest = Path(r.destination).parent.name
            col  = cat_fg(r.category)
            icon = cat_icon(r.category)
            print(f"  {col}{icon}{RESET}  {col+BOLD}{r.filename:<40}{RESET}  {MUTED}→{RESET}  {col}{dest}/{RESET}")

    _summary({k:v for k,v in result.categories.items() if v},
             len(result.records), result.other_files,
             result.ignored_files, elapsed, dry_run=False)

    # Empty dir cleanup offer
    scan = scan_empty_dirs(target)
    if scan.found:
        _warn(f"Found {len(scan.found)} empty {'directory' if len(scan.found)==1 else 'directories'}.")
        if _TUI_ALLOWED:
            from foldr.tui import confirm_dialog, Screen as _Scr
            scr = _Scr(); scr.enter()
            try:
                do_clean = confirm_dialog(scr, " 🗑 Empty Directories ",
                    [f"{BWHT}Remove {BYLW+BOLD}{len(scan.found)}{RESET+BWHT} empty directories?{RESET}"],
                    yes_label=" 🗑 Remove ", no_label=" ✗ Skip ")
            finally:
                scr.exit()
        else:
            do_clean = _confirm_plain("Remove empty directories?", default=False)
        if do_clean:
            removed = remove_empty_dirs(scan.found)
            _ok(f"Removed {len(removed.removed)} empty directories.")

# ── main entry point ───────────────────────────────────────────────────────────
def main() -> None:
    global _QUIET, _NO_INTER, _TUI_ALLOWED

    raw  = sys.argv[1:]

    # Detect subcommand BEFORE argparse (so it's never eaten as 'path')
    _SUBCMDS = {"watch", "undo", "history"}
    first_pos = next((a for a in raw if not a.startswith("-")), None)

    parser = _build_parser()
    args, _ = parser.parse_known_args(raw)

    _QUIET       = args.quiet
    _NO_INTER    = args.no_interactive
    _TUI_ALLOWED = is_tty() and not _NO_INTER and not _QUIET

    # Splash + banner
    if not _QUIET:
        if _TUI_ALLOWED:
            try:
                from foldr.tui import splash
                splash(duration=0.65)
            except Exception:
                pass
        _banner()

    # Subcommand routing
    if first_pos == "watch":   cmd_watch(raw, args); return
    if first_pos == "undo":    cmd_undo(args);        return
    if first_pos == "history": cmd_history(args);     return

    # Resolve target directory
    if args.path is None or first_pos is None:
        cwd = Path.cwd()
        if not _QUIET:
            _panel(
                f"  {BWHT}No directory specified.{RESET}\n\n"
                f"  Target:  {BCYN+BOLD}{cwd}{RESET}\n\n"
                f"  {MUTED}Pass a path to organize a different directory.{RESET}",
                title="FOLDR", col=BCYN,
            )
        if _TUI_ALLOWED:
            from foldr.tui import confirm_dialog, Screen as _Scr
            scr = _Scr(); scr.enter()
            try:
                confirmed = confirm_dialog(scr, " 📁 Organize Current Directory ",
                    [f"{BWHT}Organize: {BCYN+BOLD}{cwd.name}/{RESET}",
                     f"{MUTED}{cwd}{RESET}"],
                    yes_label=" ✓ Organize ", no_label=" ✗ Cancel ")
            finally:
                scr.exit()
        else:
            confirmed = _confirm_plain(f"Organize {cwd.name} (current directory)?", default=False)
        if not confirmed:
            _dim("Cancelled."); return
        target = cwd
    else:
        target = Path(args.path).resolve()

    if not target.exists() or not target.is_dir():
        _err(f"'{target}' is not a valid directory."); sys.exit(1)

    template = _load_template(args.config, args.quiet)

    if args.deduplicate:
        cmd_dedup(target, args.deduplicate, args.recursive,
                  args.max_depth, args.dry_run, args.verbose)
        return

    cmd_organize(target, args, template)


if __name__ == "__main__":
    main()
