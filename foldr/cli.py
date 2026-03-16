"""
foldr.cli
~~~~~~~~~
FOLDR v4 — Main entry point.

Cross-OS notes
--------------
  - term.py handles all OS differences for TUI (ANSI/VT on Windows)
  - watch.py handles OS differences for file events (inotify/kqueue/ReadDirChanges)
  - watches.py handles OS differences for daemon spawn/kill
  - Path operations use pathlib throughout (no os.path strings)
  - No select/tty/termios imports here (isolated in term.py)

New subcommands
---------------
  watch ~/Downloads        start background daemon organizer
  unwatch ~/Downloads      stop it
  watches                  list all active watches + stats
  _watch-daemon ~/path     internal: the actual daemon process (not for users)
"""
from __future__ import annotations
import argparse, os, platform, sys, time, threading
from pathlib import Path

from foldr.term import (
    is_tty, term_wh, cat_fg, cat_icon, op_icon, fmt_size,
    strip, vlen, pad_to, truncate, pbar, SPINNER,
    RESET, BOLD, DIM, FG_BRIGHT, FG_DIM, FG_MUTED,
    ACCENT, ACCENT2, COL_OK, COL_WARN, COL_ERR, COL_BORD,
    BG_BASE, BG_PANEL, bg256, fg256,
)
from foldr.config_loader import load_template
from foldr.dedup         import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs    import remove_empty_dirs, scan_empty_dirs
from foldr.history       import (get_history_entry, get_latest_history,
                                  list_history, save_history, save_dedup_history,
                                  undo_operation)
from foldr.models        import DedupeStrategy
from foldr.organizer     import organize_folder
from foldr.prefs         import get_mode, set_mode, all_prefs

_IS_WIN = platform.system() == "Windows"

# ── Runtime flags ──────────────────────────────────────────────────────────────
_QUIET   = False
_USE_TUI = False

# ── CLI output helpers ─────────────────────────────────────────────────────────
def _w() -> int:
    return min(100, term_wh()[0])

def _rule(title: str = "") -> None:
    if _QUIET: return
    w = _w()
    if not title:
        print(FG_MUTED + "─"*w + RESET); return
    side = max(1, (w - len(title) - 2) // 2)
    print(FG_MUTED+"─"*side+RESET+" "+BOLD+title+RESET+" "+FG_MUTED+"─"*side+RESET)

def _banner() -> None:
    if _QUIET: return
    print()
    print(f"   {ACCENT+BOLD}███████╗ ██████╗ ██╗     ██████╗ ██████╗{RESET}")
    print(f"   {ACCENT+BOLD}██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗{RESET}")
    print(f"   {ACCENT+BOLD}█████╗  ██║   ██║██║     ██║  ██║██████╔╝{RESET}")
    print(f"   {FG_DIM}██╔══╝  ██║   ██║██║     ██║  ██║██╔══██╗{RESET}")
    print(f"   {FG_DIM}██║     ╚██████╔╝███████╗██████╔╝██║  ██║{RESET}")
    print(f"   {FG_DIM}╚═╝      ╚═════╝ ╚══════╝╚═════╝ ╚═╝  ╚═╝{RESET}")
    print(f"   {FG_MUTED}Smart File Organizer  ·  v4  ·  github.com/qasimio/Foldr{RESET}")
    print()

def _box(body: str, title: str = "", col: str = "") -> None:
    if _QUIET: return
    c = col or COL_BORD; w = _w(); inner = w-4; lines = body.split("\n")
    t = f" {title} " if title else ""; tl = vlen(t)
    if tl and tl < inner-2:
        pl=(inner-tl)//2; pr=inner-tl-pl
        top=c+"╭"+"─"*pl+ACCENT+BOLD+t+RESET+c+"─"*pr+"╮"+RESET
    else:
        top=c+"╭"+"─"*inner+"╮"+RESET
    print(top)
    for line in lines:
        rest=max(0,inner-vlen(line)-2)
        print(c+"│"+RESET+"  "+line+" "*rest+"  "+c+"│"+RESET)
    print(c+"╰"+"─"*inner+"╯"+RESET)

def _ok(msg:str)   -> None:
    if not _QUIET: print(f"  {COL_OK}ok{RESET}  {msg}")
def _warn(msg:str) -> None:
    if not _QUIET: print(f"  {COL_WARN}!{RESET}  {msg}")
def _err(msg:str)  -> None:
    print(f"  {COL_ERR}error{RESET}  {msg}", file=sys.stderr)
def _dim(msg:str)  -> None:
    if not _QUIET: print(f"  {FG_MUTED}{msg}{RESET}")
def _info(msg:str) -> None:
    if not _QUIET: print(f"  {ACCENT}·{RESET}  {msg}")

def _summary(cat_counts:dict, moved:int, other:int, ignored:int, elapsed:float, dry:bool)->None:
    if _QUIET or not cat_counts: return
    w=_w(); bar_w=max(12,w//3); total=max(1,sum(cat_counts.values()))
    _rule("Summary"); print()
    for cat,cnt in sorted(cat_counts.items(), key=lambda x:-x[1]):
        if not cnt: continue
        col=cat_fg(cat); ico=cat_icon(cat); pct=cnt/total
        fill=max(1,int(pct*bar_w))
        bar=col+"█"*fill+FG_MUTED+"░"*(bar_w-fill)+RESET
        print(f"  {col}{ico}{RESET}  {FG_DIM}{pad_to(cat,16)}{RESET}  {bar}  {ACCENT}{cnt:>4}{RESET}  {FG_MUTED}{pct*100:4.1f}%{RESET}")
    print()
    st=f"{COL_WARN+BOLD}preview -- nothing moved{RESET}" if dry else f"{COL_OK+BOLD}done{RESET}"
    _box(
        f"  {st}\n\n"
        f"  {ACCENT+BOLD}{moved}{RESET} moved  {FG_MUTED}|{RESET}  "
        f"{FG_DIM}{other}{RESET} unrecognised  {FG_MUTED}|{RESET}  "
        f"{FG_DIM}{ignored}{RESET} ignored  {FG_MUTED}|{RESET}  {FG_MUTED}{elapsed:.2f}s{RESET}",
        col=COL_WARN if dry else COL_OK,
    )
    print()

def _confirm_plain(prompt:str, default:bool=False)->bool:
    yn=f"[{'Y' if default else 'y'}/{'n' if default else 'N'}]"
    sys.stdout.write(f"\n  {COL_WARN+BOLD}?{RESET}  {BOLD}{prompt}{RESET}  {FG_MUTED}{yn}{RESET}: ")
    sys.stdout.flush()
    try:
        ans=input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); return False
    return (ans in ("y","yes")) if ans else default

def _preview_plain(preview, dry:bool)->None:
    try:
        from tabulate import tabulate
        rows=[[r.filename,"-> "+Path(r.destination).parent.name+"/",r.category]
              for r in preview.records[:60]]
        print()
        print(tabulate(rows, headers=["File","Destination","Category"],
                       tablefmt="rounded_outline", maxcolwidths=[42,24,16]))
    except ImportError:
        for r in preview.records[:30]:
            dest=Path(r.destination).parent.name; col=cat_fg(r.category)
            print(f"  {col}{cat_icon(r.category)}{RESET}  {FG_BRIGHT}{r.filename:<40}{RESET}  {FG_MUTED}->{RESET}  {col}{dest}/{RESET}")
    n=len(preview.records)
    if n>60: _dim(f"... and {n-60} more")
    print()
    if dry: _warn(f"preview -- {ACCENT+BOLD}{n}{RESET} files would move. Nothing changed.")

def _confirm(title:str, body_lines:list[str], yes:str=" Confirm ", no:str=" Cancel  ",
             danger:bool=False, plain_prompt:str="", plain_default:bool=False)->bool:
    if _USE_TUI:
        from foldr.tui import confirm_dialog, Screen as _Scr
        scr=_Scr(); scr.enter()
        try: return confirm_dialog(scr,title,body_lines,yes_label=yes,no_label=no,danger=danger)
        finally: scr.exit()
    return _confirm_plain(plain_prompt or title.strip(), plain_default)

def _load_template(config_arg)->dict|None:
    if config_arg:
        try:
            tmpl,label=load_template(Path(config_arg))
            if not _QUIET: _dim(f"config: {label}")
            return tmpl
        except FileNotFoundError as e:
            _err(str(e)); sys.exit(1)
    tmpl,label=load_template(None)
    if label and not _QUIET: _dim(f"config: {label}")
    return tmpl

# ── Argument parser ────────────────────────────────────────────────────────────
def _build_parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(
        prog="foldr", description="FOLDR v4 - Smart File Organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples\n--------\n"
            "  foldr ~/Downloads                     organize (shows preview first)\n"
            "  foldr ~/Downloads --preview            dry-run, nothing moves\n"
            "  foldr ~/Downloads --recursive\n"
            "  foldr ~/Downloads --dedup keep-newest\n"
            "  foldr ~/Downloads --ignore '*.log'\n"
            "  foldr ~/Downloads --global-ignore      use ~/.foldr/.foldrignore too\n"
            "\n"
            "  foldr watch ~/Downloads                start background auto-organizer\n"
            "  foldr unwatch ~/Downloads              stop it\n"
            "  foldr watches                          list all active watches\n"
            "\n"
            "  foldr undo                             undo last operation\n"
            "  foldr undo --id a1b2c3                 undo by ID\n"
            "  foldr history                          browse all history\n"
            "  foldr config --mode tui|cli            set output mode\n"
        ),
    )
    p.add_argument("path",           nargs="?")
    p.add_argument("--preview",      action="store_true",
                   help="Show what would happen without moving files")
    p.add_argument("--recursive",    action="store_true")
    p.add_argument("--depth",        type=int,  metavar="N")
    p.add_argument("--follow-links", action="store_true")
    p.add_argument("--smart",        action="store_true",
                   help="Detect file type by content, not just extension")
    p.add_argument("--dedup",
                   choices=["keep-newest","keep-largest","keep-oldest"],
                   metavar="STRATEGY")
    p.add_argument("--ignore",       nargs="+", metavar="PATTERN")
    p.add_argument("--global-ignore",action="store_true",
                   help="Also apply ~/.foldr/.foldrignore rules")
    p.add_argument("--config",       metavar="FILE")
    p.add_argument("--verbose",      action="store_true")
    p.add_argument("--quiet",        action="store_true")
    p.add_argument("--plain",        action="store_true",
                   help="Plain CLI output for this run (no TUI)")
    p.add_argument("--id",           metavar="ID")
    p.add_argument("--all",          action="store_true")
    return p


# ── cmd_watch (interactive foreground) ────────────────────────────────────────
def cmd_watch(raw_argv:list[str], args)->None:
    # Extract target directory (first non-flag after 'watch')
    try:
        wi    = next(i for i,a in enumerate(raw_argv) if a in ("watch","unwatch","watches"))
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except (StopIteration, IndexError):
        ts = None
    target = Path(ts).resolve() if ts else Path.cwd()
    if not target.is_dir():
        _err(f"'{target}' is not a valid directory"); sys.exit(1)

    tmpl   = _load_template(getattr(args,"config",None))
    ignore = list(args.ignore or [])
    if getattr(args,"global_ignore",False):
        from foldr.organizer import _load_global_foldrignore
        ignore = _load_global_foldrignore() + ignore

    from foldr.watches import spawn_daemon, add_watch, get_watches

    # Check if already watching
    watches = get_watches()
    if str(target) in watches:
        _warn(f"Already watching {ACCENT+BOLD}{target}{RESET}")
        _dim("Run 'foldr unwatch <path>' to stop it first.")
        return

    _info(f"Starting background watcher for {ACCENT+BOLD}{target.name}/{RESET}")
    _dim("This runs in the background. New files will be organized automatically.")
    _dim("No approval needed per-file — you already approved by starting watch mode.")
    print()

    pid = spawn_daemon(target, dry_run=args.preview, extra_ignore=ignore)
    add_watch(target, pid, dry_run=args.preview)

    _ok(f"Watcher started  {FG_MUTED}(PID {pid}){RESET}")
    _dim(f"Log: ~/.foldr/watch_logs/{target.name}.log")
    _dim(f"Stop: foldr unwatch \"{target}\"")
    _dim(f"Status: foldr watches")


# ── cmd_unwatch ────────────────────────────────────────────────────────────────
def cmd_unwatch(raw_argv:list[str], args)->None:
    try:
        wi    = next(i for i,a in enumerate(raw_argv) if a=="unwatch")
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except (StopIteration, IndexError):
        ts = None

    if not ts:
        # List active watches and ask which to stop
        from foldr.watches import get_watches
        watches = get_watches()
        if not watches:
            _warn("No active watches."); return
        _rule("Active Watches")
        paths = list(watches.keys())
        for i, p in enumerate(paths, 1):
            info = watches[p]
            print(f"  {ACCENT}{i}{RESET}  {FG_BRIGHT}{p}{RESET}  {FG_MUTED}PID {info.get('pid')}{RESET}")
        print()
        sys.stdout.write(f"  {FG_MUTED}Enter number to stop (or Enter to cancel): {RESET}")
        sys.stdout.flush()
        try:
            ans = input().strip()
            if ans.isdigit() and 1 <= int(ans) <= len(paths):
                ts = paths[int(ans)-1]
            else:
                _dim("Cancelled."); return
        except (EOFError, KeyboardInterrupt):
            print(); return

    target = Path(ts).resolve()
    from foldr.watches import kill_watch
    ok, msg = kill_watch(target)
    if ok:
        _ok(msg)
    else:
        _warn(msg)


# ── cmd_watches (list active) ──────────────────────────────────────────────────
def cmd_watches()->None:
    from foldr.watches import get_watches
    watches = get_watches()
    if not watches:
        _box(
            f"  {FG_DIM}No active watches.{RESET}\n\n"
            f"  Start one with:  {ACCENT}foldr watch ~/Downloads{RESET}",
            col=COL_BORD,
        )
        return

    _rule("Active Watches"); print()
    try:
        from tabulate import tabulate
        rows = []
        for p, info in watches.items():
            started = info.get("started","")[:16].replace("T"," ")
            mode    = "preview" if info.get("dry_run") else "live"
            total   = info.get("total",0)
            rows.append([Path(p).name, started, mode, str(total), str(info.get("pid","?"))])
        print(tabulate(rows, headers=["Directory","Started","Mode","Files","PID"],
                       tablefmt="rounded_outline"))
    except ImportError:
        for p, info in watches.items():
            started = info.get("started","")[:16].replace("T"," ")
            mode    = "preview" if info.get("dry_run") else "live"
            total   = info.get("total",0)
            pid     = info.get("pid","?")
            print(f"  {ACCENT+BOLD}{Path(p).name:<24}{RESET}  {FG_DIM}{started}{RESET}  {COL_OK if mode=='live' else COL_WARN}{mode}{RESET}  {FG_DIM}{total} files  PID {pid}{RESET}")
    print()
    _dim("Stop a watch: foldr unwatch <directory>")
    _dim("Logs: ~/.foldr/watch_logs/")


# ── cmd_watch_daemon (internal) ───────────────────────────────────────────────
def cmd_watch_daemon(raw_argv:list[str], args)->None:
    """Internal: the actual daemon process. Not for direct user invocation."""
    try:
        wi    = raw_argv.index("_watch-daemon")
        cands = [a for a in raw_argv[wi+1:] if not a.startswith("-")]
        ts    = cands[0] if cands else None
    except (ValueError, IndexError):
        ts = None
    if not ts:
        sys.exit(1)
    target = Path(ts).resolve()
    tmpl   = _load_template(getattr(args,"config",None))
    ignore = list(args.ignore or [])

    from foldr.watch import run_watch
    run_watch(
        base=target, template=tmpl or {},
        dry_run=getattr(args,"preview",False),
        extra_ignore=ignore, use_tui=False, daemon_mode=True,
    )


# ── cmd_undo ──────────────────────────────────────────────────────────────────
def cmd_undo(args)->None:
    _rule("Undo")
    target_id = getattr(args,"id",None)
    log = get_history_entry(target_id) if target_id else get_latest_history()
    if not log:
        _warn("No history found." + (" Run 'foldr history' to see IDs." if target_id else "")); return

    ts=log.get("timestamp","")[:19].replace("T"," ")
    base=log.get("base",""); total=log.get("total_files",0)
    eid=log.get("id","?"); otype=log.get("op_type","organize")

    _box(
        f"  ID:          {ACCENT+BOLD}{eid}{RESET}\n"
        f"  Operation:   {FG_DIM}{otype}{RESET}\n"
        f"  Time:        {FG_DIM}{ts}{RESET}\n"
        f"  Directory:   {FG_DIM}{base}{RESET}\n"
        f"  Files:       {ACCENT+BOLD}{total}{RESET}",
        title=" Undo Preview ",col=COL_WARN,
    )
    if otype=="dedup":
        _warn("Dedup permanently deletes files -- cannot be undone."); return

    dry=getattr(args,"preview",False)
    if not dry:
        ok=_confirm(
            " Undo Operation ",
            body_lines=["",f"  Restore {ACCENT+BOLD}{total}{RESET} files",
                        f"  from operation {ACCENT}{eid}{RESET}",
                        f"  in {FG_DIM}{Path(base).name}/{RESET}","",
                        f"  {FG_MUTED}Files moved elsewhere will be skipped.{RESET}",""],
            yes=" Undo ",no=" Cancel ",danger=True,
            plain_prompt=f"Restore {total} files from op {eid}?",
        )
        if not ok: _dim("Cancelled."); return

    result=undo_operation(log, dry_run=dry)
    print(); _rule("Restored" if not dry else "Preview"); print()
    for r in result.restored:
        pfx=f"  {COL_WARN}preview{RESET}" if dry else f"  {COL_OK}<-{RESET}"
        print(f"{pfx}  {FG_DIM}{r}{RESET}")
    for s in result.skipped:
        print(f"  {COL_WARN}skip{RESET}  {FG_MUTED}{s}{RESET}")
    for e in result.errors: _err(e)
    print()
    _box(
        f"  {COL_OK+BOLD}{len(result.restored)}{RESET} restored  {FG_MUTED}|{RESET}  "
        f"{COL_WARN}{len(result.skipped)}{RESET} skipped  {FG_MUTED}|{RESET}  "
        f"{COL_ERR}{len(result.errors)}{RESET} errors",
        col=COL_OK if not result.errors else COL_ERR,
    )


# ── cmd_history ───────────────────────────────────────────────────────────────
def cmd_history(args)->None:
    entries=list_history(limit=None if getattr(args,"all",False) else 50)
    if not entries: _warn("No history found."); return
    if _USE_TUI:
        from foldr.tui import HistoryScreen
        action,eid=HistoryScreen(entries).run()
        if action=="undo" and eid: args.id=eid; cmd_undo(args)
        return
    _rule("Operation History"); print()
    try:
        from tabulate import tabulate
        rows=[[e.get("id","?"),e.get("op_type","organize"),
               e.get("timestamp","")[:16].replace("T"," "),
               Path(e.get("base","?")).name,str(e.get("total_files",0))]
              for e in entries]
        print(tabulate(rows,headers=["ID","Type","Time","Directory","Files"],
                       tablefmt="rounded_outline"))
    except ImportError:
        for e in entries:
            ts=e.get("timestamp","")[:16].replace("T"," "); ot=e.get("op_type","organize")
            print(f"  {ACCENT}{e.get('id','?')}{RESET}  {FG_MUTED}{op_icon(ot)} {ot:<10}{RESET}"
                  f"  {ts}  {Path(e.get('base','?')).name}  {FG_DIM}{e.get('total_files',0)} files{RESET}")
    print(); _dim("To undo: foldr undo --id <ID>")


# ── cmd_config ────────────────────────────────────────────────────────────────
def cmd_config(raw_argv:list[str])->None:
    mode=None
    for i,a in enumerate(raw_argv):
        if a=="--mode" and i+1<len(raw_argv): mode=raw_argv[i+1]; break
        if a.startswith("--mode="): mode=a.split("=",1)[1]; break
    if mode:
        if mode not in ("tui","cli"): _err(f"Unknown mode '{mode}'. Use: tui or cli"); sys.exit(1)
        set_mode(mode); _ok(f"Mode set to {ACCENT+BOLD}{mode}{RESET}"); _dim("Saved to ~/.foldr/prefs.json")
    else:
        _rule("Current Preferences")
        for k,v in all_prefs().items():
            print(f"  {FG_DIM}{k:<20}{RESET}  {ACCENT}{v}{RESET}")
        print(); _dim("Change: foldr config --mode tui|cli")


# ── cmd_dedup ─────────────────────────────────────────────────────────────────
def cmd_dedup(target:Path, strat_str:str, recursive:bool,
              max_depth:int|None, preview:bool, verbose:bool)->None:
    stmap={"keep-newest":DedupeStrategy.KEEP_NEWEST,"keep-oldest":DedupeStrategy.KEEP_OLDEST,
           "keep-largest":DedupeStrategy.KEEP_LARGEST}
    _rule("Duplicate Detection"); _info(f"Scanning {target} ...")
    files=collect_files(target,recursive=recursive,max_depth=max_depth)
    groups=find_duplicates(files)
    if not groups: _ok("No duplicates found!"); return
    total_rem=sum(len(g.files)-1 for g in groups)
    _warn(f"Found {len(groups)} groups -- {total_rem} removable files")
    for g in groups: resolve_strategy(g,stmap[strat_str])
    try:
        from tabulate import tabulate
        rows=[[g.keep.name if g.keep else "?",rem.name,
               fmt_size(g.keep.stat().st_size if g.keep and g.keep.exists() else 0)]
              for g in groups[:40] for rem in g.remove]
        print("\n"+tabulate(rows,headers=["Keep","Remove","Size"],tablefmt="rounded_outline"))
    except ImportError:
        for g in groups[:20]:
            for rem in g.remove:
                print(f"  {COL_OK}keep:{RESET} {g.keep.name if g.keep else '?'}  {COL_ERR}del:{RESET} {rem.name}")
    if total_rem>40: _dim(f"... and {total_rem-40} more")
    print()
    if preview: _warn(f"preview -- {total_rem} files would be removed."); return
    ok=_confirm(" Remove Duplicates ",
                body_lines=["",f"  Delete {COL_ERR+BOLD}{total_rem}{RESET} duplicate files?",
                            f"  Strategy: {ACCENT}{strat_str}{RESET}","",
                            f"  {COL_WARN}Dedup cannot be reversed via 'foldr undo'.{RESET}",""],
                yes=" Delete ",no=" Cancel ",danger=True,
                plain_prompt=f"Delete {total_rem} duplicate files?")
    if not ok: _dim("Cancelled."); return
    removed=[]
    for g in groups:
        for p in g.remove:
            try: p.unlink(); removed.append(p)
            except OSError as e: _err(f"Could not remove {p.name}: {e}")
    save_dedup_history(removed,target,strat_str)
    _ok(f"Removed {len(removed)} duplicate files.")
    _dim("Note: dedup cannot be reversed with 'foldr undo'.")


# ── cmd_organize ──────────────────────────────────────────────────────────────
def cmd_organize(target:Path, args, template)->None:
    preview=getattr(args,"preview",False)
    ignore=list(args.ignore or [])
    if getattr(args,"global_ignore",False):
        from foldr.organizer import _load_global_foldrignore
        ignore=_load_global_foldrignore()+ignore

    _rule(f"Scanning  {target.name}")
    spinner_done=threading.Event()
    if not _QUIET and not _USE_TUI and not is_tty():
        def _spin():
            i=0
            while not spinner_done.is_set():
                sys.stdout.write(f"\r  {ACCENT}{SPINNER[i%4]}{RESET}  Scanning..."); sys.stdout.flush()
                time.sleep(0.1); i+=1
            sys.stdout.write("\r"+" "*30+"\r"); sys.stdout.flush()
        threading.Thread(target=_spin,daemon=True).start()

    t0=time.monotonic()
    prev=organize_folder(
        base=target,dry_run=True,recursive=args.recursive,
        max_depth=getattr(args,"depth",None),
        follow_symlinks=getattr(args,"follow_links",False),
        extra_ignore=ignore,category_template=template,
        global_ignore=getattr(args,"global_ignore",False),
    )
    spinner_done.set()

    if not prev.actions:
        _box(f"  {COL_OK+BOLD}Nothing to organize -- directory is already tidy!{RESET}",col=COL_OK); return

    n=len(prev.records)

    if _USE_TUI:
        from foldr.tui import PreviewScreen
        confirmed=PreviewScreen(prev.records,target,preview).run()
    else:
        _preview_plain(prev,preview)
        if preview:
            _summary({k:v for k,v in prev.categories.items() if v},n,prev.other_files,prev.ignored_files,time.monotonic()-t0,dry_run=True); return
        confirmed=_confirm_plain(f"Move {n} files?",default=True)

    if not confirmed: _warn("Cancelled -- nothing was moved."); print(); return
    if preview:
        _summary({k:v for k,v in prev.categories.items() if v},n,prev.other_files,prev.ignored_files,time.monotonic()-t0,dry_run=True); return

    _rule("Executing"); t_exec=time.monotonic()

    if _USE_TUI:
        from foldr.tui import ExecutionScreen
        result_box:list=[]; err_box:list=[]; done_evt=threading.Event()
        def _run():
            try:
                r=organize_folder(base=target,dry_run=False,recursive=args.recursive,
                                  max_depth=getattr(args,"depth",None),
                                  follow_symlinks=getattr(args,"follow_links",False),
                                  extra_ignore=ignore,category_template=template,
                                  global_ignore=getattr(args,"global_ignore",False))
                result_box.append(r)
            except Exception as e: err_box.append(e)
            finally: done_evt.set()
        with ExecutionScreen(n,target) as xs:
            t=threading.Thread(target=_run,daemon=True); t.start()
            while not done_evt.wait(timeout=0.05): xs._draw()
            t.join()
            if err_box: raise err_box[0]
            result=result_box[0]
            xs.done=len(result.records)
            for r in result.records: xs.log.append((r.category,r.filename,Path(r.destination).parent.name))
            xs._draw(); time.sleep(0.5)
    else:
        result=organize_folder(base=target,dry_run=False,recursive=args.recursive,
                               max_depth=getattr(args,"depth",None),
                               follow_symlinks=getattr(args,"follow_links",False),
                               extra_ignore=ignore,category_template=template,
                               global_ignore=getattr(args,"global_ignore",False))
        if not _QUIET:
            print(f"  {pbar(1.0,30)}  {ACCENT+BOLD}{len(result.records)}{RESET} files moved")

    elapsed=time.monotonic()-t_exec
    log_path=save_history(result.records,target,dry_run=False,op_type="organize")
    if log_path and getattr(args,"verbose",False): _dim(f"History saved: {log_path.name}")
    if getattr(args,"verbose",False):
        for r in result.records:
            dest=Path(r.destination).parent.name; col=cat_fg(r.category)
            print(f"  {col}{cat_icon(r.category)}{RESET}  {FG_BRIGHT}{r.filename:<40}{RESET}  {FG_MUTED}->{RESET}  {col}{dest}/{RESET}")
    _summary({k:v for k,v in result.categories.items() if v},len(result.records),
             result.other_files,result.ignored_files,elapsed,dry_run=False)

    scan=scan_empty_dirs(target)
    if scan.found and not _QUIET:
        n_empty=len(scan.found); _warn(f"Found {n_empty} empty director{'y' if n_empty==1 else 'ies'}.")
        ok=_confirm(" Empty Directories ",body_lines=["",f"  Remove {n_empty} empty directories?",""],
                    yes=" Remove ",no=" Skip   ",plain_prompt=f"Remove {n_empty} empty directories?")
        if ok:
            removed=remove_empty_dirs(scan.found); _ok(f"Removed {len(removed.removed)} empty directories.")


# ── main ──────────────────────────────────────────────────────────────────────
def main()->None:
    global _QUIET, _USE_TUI

    raw=sys.argv[1:]

    # ── Subcommand detection ───────────────────────────────────────────────────
    # Scan ALL positionals (not just first) to handle: foldr ~/path undo --id X
    _SUBCMDS={"watch","unwatch","watches","undo","history","config","_watch-daemon"}
    sub=next((a for a in raw if not a.startswith("-") and a in _SUBCMDS), None)

    parser=_build_parser()
    args,_=parser.parse_known_args(raw)
    _QUIET=args.quiet

    # ── Output mode ────────────────────────────────────────────────────────────
    if _QUIET or args.plain or not is_tty():
        _USE_TUI=False
    else:
        saved=get_mode()
        prefs_file=Path.home()/".foldr"/"prefs.json"
        if not prefs_file.exists() and sub not in _SUBCMDS:
            try:
                from foldr.tui import mode_picker
                chosen=mode_picker(); set_mode(chosen); saved=chosen
            except Exception:
                saved="cli"
        _USE_TUI=(saved=="tui") and is_tty()

    # ── Splash + banner ────────────────────────────────────────────────────────
    if not _QUIET and sub not in {"_watch-daemon"}:
        if _USE_TUI and sub not in _SUBCMDS:
            try:
                from foldr.tui import splash
                splash(0.4)
            except Exception: pass
        _banner()

    # ── Dispatch ───────────────────────────────────────────────────────────────
    if sub=="config":        cmd_config(raw);              return
    if sub=="watch":         cmd_watch(raw,args);           return
    if sub=="unwatch":       cmd_unwatch(raw,args);         return
    if sub=="watches":       cmd_watches();                 return
    if sub=="_watch-daemon": cmd_watch_daemon(raw,args);    return
    if sub=="undo":          cmd_undo(args);                return
    if sub=="history":       cmd_history(args);             return

    # ── Organize ───────────────────────────────────────────────────────────────
    path_candidates=[a for a in raw if not a.startswith("-") and a not in _SUBCMDS]
    raw_path=path_candidates[0] if path_candidates else None

    if not raw_path:
        cwd=Path.cwd()
        if not _QUIET:
            _box(f"  No path specified.\n\n  Target:  {ACCENT+BOLD}{cwd}{RESET}\n\n"
                 f"  {FG_MUTED}Tip: foldr ~/Downloads{RESET}",title=" FOLDR ")
        ok=_confirm(" Organize Current Directory ",
                    body_lines=["",f"  Organize: {ACCENT+BOLD}{cwd.name}/{RESET}",f"  {FG_MUTED}{cwd}{RESET}",""],
                    yes=" Organize ",no=" Cancel ",
                    plain_prompt=f"Organize {cwd.name}?")
        if not ok: _dim("Cancelled."); return
        target=cwd
    else:
        target=Path(raw_path).resolve()

    if not target.exists() or not target.is_dir():
        _err(f"'{target}' is not a valid directory"); sys.exit(1)

    template=_load_template(args.config)
    if args.dedup:
        cmd_dedup(target,args.dedup,args.recursive,getattr(args,"depth",None),
                  args.preview,getattr(args,"verbose",False)); return
    cmd_organize(target,args,template)


if __name__=="__main__":
    main()
