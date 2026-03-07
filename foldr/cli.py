"""
foldr.cli
~~~~~~~~~
FOLDR v4 — World-class CLI with full interactive TUI.

Commands
--------
  foldr                              → organize cwd (interactive prompt)
  foldr <path>                       → organize directory
  foldr <path> --dry-run             → preview only
  foldr <path> --recursive           → recurse into subdirs
  foldr <path> --max-depth N
  foldr <path> --follow-symlinks
  foldr <path> --deduplicate [keep-newest|keep-largest|keep-oldest]
  foldr <path> --ignore "*.log" "tmp/"
  foldr <path> --config foldr.toml
  foldr <path> --verbose / --quiet
  foldr <path> --interactive         → TUI preview before executing (default when TTY)
  foldr watch <path>                 → live file organizer
  foldr undo [--id ID] [--dry-run]
  foldr history [--all]
"""
from __future__ import annotations

import argparse
import curses
import os
import sys
import time
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

try:
    from pyfiglet import Figlet
    _FIGLET = True
except ImportError:
    _FIGLET = False

from foldr.config_loader import load_template
from foldr.dedup import collect_files, find_duplicates, resolve_strategy
from foldr.empty_dirs import remove_empty_dirs, scan_empty_dirs
from foldr.history import (
    get_history_entry, get_latest_history,
    list_history, save_history, undo_operation,
)
from foldr.models import DedupeStrategy
from foldr.organizer import organize_folder
from foldr.watch import run_watch

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Colour / icon helpers
# ─────────────────────────────────────────────────────────────────────────────

_CAT_STYLE: dict[str, str] = {
    "Documents": "bold cyan",
    "Text & Data": "cyan",
    "Images": "bold green",
    "Videos": "bold yellow",
    "Audio": "bold magenta",
    "Archives": "bold red",
    "Code": "bold blue",
    "Scripts": "blue",
    "Notebooks": "blue",
    "Executables": "red",
    "Spreadsheets": "cyan",
    "Presentations": "cyan",
}

_CAT_ICON: dict[str, str] = {
    "Documents": "📄", "Text & Data": "📝", "Images": "🖼 ",
    "Videos": "🎬", "Audio": "🎵", "Archives": "📦",
    "Code": "💻", "Scripts": "📜", "Notebooks": "📓",
    "Executables": "⚙ ", "Spreadsheets": "📊", "Presentations": "📽 ",
    "Fonts": "🔤", "3D_Models": "🧊", "Machine_Learning": "🧠",
    "Databases": "🗄 ", "GIS": "🗺 ", "Ebooks": "📚",
    "Misc": "🗃 ",
}

def _cat_style(cat: str) -> str:
    return _CAT_STYLE.get(cat, "white")

def _cat_icon(cat: str) -> str:
    return _CAT_ICON.get(cat, "📁")


# ─────────────────────────────────────────────────────────────────────────────
# Header / banner
# ─────────────────────────────────────────────────────────────────────────────

def _print_banner(quiet: bool = False) -> None:
    if quiet:
        return
    if _FIGLET:
        fig = Figlet(font="slant")
        title = fig.renderText("FOLDR")
        console.print(f"[bold cyan]{title}[/bold cyan]")
    else:
        console.print("\n[bold cyan]  ╔═══════════════════╗")
        console.print("[bold cyan]  ║   F O L D R  v4   ║")
        console.print("[bold cyan]  ╚═══════════════════╝[/bold cyan]\n")

    console.print(
        "[dim]  Smart File Organizer  ·  "
        "https://github.com/qasimio/Foldr[/dim]\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rich summary table
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(result, base: Path, elapsed: float, dry_run: bool, quiet: bool) -> None:
    if quiet:
        moved = len(result.records)
        tag = "[dim](dry)[/dim] " if dry_run else ""
        console.print(f"{tag}[green]{moved} files organized[/green]")
        return

    moved_cats = {k: v for k, v in result.categories.items() if v > 0}

    console.print()
    console.print(Rule("Summary", style="cyan"))
    console.print()

    # Category breakdown table
    if moved_cats:
        table = Table(
            show_header=True,
            header_style="bold cyan",
            box=box.ROUNDED,
            border_style="dim",
            expand=False,
        )
        table.add_column("  Category", style="bold", min_width=20)
        table.add_column("Files", justify="right", style="cyan")
        table.add_column("Bar", min_width=20)

        total_moved = sum(moved_cats.values())
        for cat, cnt in sorted(moved_cats.items(), key=lambda x: -x[1]):
            icon  = _cat_icon(cat)
            style = _cat_style(cat)
            bar_w = 20
            filled = max(1, int(cnt / total_moved * bar_w))
            bar = f"[{style}]{'█' * filled}[/{style}][dim]{'░' * (bar_w - filled)}[/dim]"
            table.add_row(
                f"  {icon} {cat}",
                f"[{style}]{cnt}[/{style}]",
                bar,
            )

        console.print(table)
        console.print()

    # Stats row
    mode_tag = (
        "[bold yellow]  DRY RUN — no files were moved  [/bold yellow]"
        if dry_run else
        "[bold green]  ✓ Files organized successfully  [/bold green]"
    )
    console.print(
        Panel.fit(
            f"{mode_tag}\n\n"
            f"  [bold]{len(result.records)}[/bold] files moved   "
            f"[dim]·[/dim]   "
            f"[bold]{result.other_files}[/bold] unrecognised   "
            f"[dim]·[/dim]   "
            f"[bold]{result.ignored_files}[/bold] ignored   "
            f"[dim]·[/dim]   "
            f"[dim]{elapsed:.2f}s[/dim]",
            border_style="cyan" if not dry_run else "yellow",
        )
    )
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# TUI interactive preview (wraps curses)
# ─────────────────────────────────────────────────────────────────────────────

def _run_tui_preview(actions: list[str], records: list, base: Path,
                     dry_run: bool) -> bool:
    """Launch interactive TUI. Returns True if user confirmed."""
    def _inner(stdscr):
        from foldr.tui import init_colors, show_splash, PreviewTUI
        init_colors()
        show_splash(stdscr)
        tui = PreviewTUI(stdscr, actions, records, base, dry_run)
        return tui.run()

    try:
        return curses.wrapper(_inner)
    except Exception as e:
        # Fallback if terminal doesn't support curses
        console.print(f"[dim]TUI unavailable ({e}), falling back to plain prompt.[/dim]")
        return Confirm.ask(
            f"  Execute [bold]{len(actions)}[/bold] moves?",
            default=False,
            console=console,
        )


def _run_tui_history(entries: list[dict]) -> tuple[str | None, str | None]:
    def _inner(stdscr):
        from foldr.tui import init_colors, HistoryTUI
        init_colors()
        tui = HistoryTUI(stdscr, entries)
        return tui.run()

    try:
        return curses.wrapper(_inner)
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# watch subcommand
# ─────────────────────────────────────────────────────────────────────────────

def cmd_watch(target: str | None, args: argparse.Namespace) -> None:
    target_path = Path(target).resolve() if target else Path.cwd()

    if not target_path.exists() or not target_path.is_dir():
        console.print(
            f"[bold red]Error:[/bold red] "
            f"Watch target '{target_path}' is not a valid directory."
        )
        sys.exit(1)

    template_result = load_template(Path(args.config)) if getattr(args, "config", None) else {}
    template = template_result[0] if isinstance(template_result, tuple) else template_result

    run_watch(
        base=target_path,
        template=template,
        dry_run=args.dry_run,
        extra_ignore=args.ignore,
    )


# ─────────────────────────────────────────────────────────────────────────────
# undo subcommand
# ─────────────────────────────────────────────────────────────────────────────

def cmd_undo(args: argparse.Namespace) -> None:
    # Load history entry
    if getattr(args, "id", None):
        log_data = get_history_entry(args.id)
        if not log_data:
            console.print(f"[red]No history entry found with id: {args.id}[/red]")
            sys.exit(1)
    else:
        log_data = get_latest_history()
        if not log_data:
            console.print("[yellow]No history found. Nothing to undo.[/yellow]")
            return

    ts    = log_data.get("timestamp", "")[:19].replace("T", " ")
    base  = log_data.get("base", "")
    total = log_data.get("total_files", 0)
    eid   = log_data.get("id", "?")

    console.print()
    console.print(
        Panel.fit(
            f"[bold]Undo Operation[/bold]\n\n"
            f"  ID        : [cyan]{eid}[/cyan]\n"
            f"  Time      : [dim]{ts}[/dim]\n"
            f"  Directory : [cyan]{base}[/cyan]\n"
            f"  Files     : [bold]{total}[/bold]",
            border_style="yellow",
            title=" Undo Preview ",
        )
    )
    console.print()

    dry_run = args.dry_run

    if not dry_run:
        confirmed = Confirm.ask(
            "  [bold yellow]⚠[/bold yellow]  "
            "This will move all files back. Continue?",
            default=False,
            console=console,
        )
        if not confirmed:
            console.print("  [dim]Cancelled.[/dim]")
            return

    result = undo_operation(log_data, dry_run=dry_run)

    prefix = "[dim](dry)[/dim] " if dry_run else ""
    for r in result.restored:
        console.print(f"  {prefix}[green]↩[/green]  {r}")
    for s in result.skipped:
        console.print(f"  [yellow]⚠[/yellow]  [dim]{s}[/dim]")
    for e in result.errors:
        console.print(f"  [red]✗[/red]  {e}")

    console.print()
    console.print(
        f"  [bold green]{len(result.restored)}[/bold green] restored  "
        f"[dim]·[/dim]  "
        f"[yellow]{len(result.skipped)}[/yellow] skipped  "
        f"[dim]·[/dim]  "
        f"[red]{len(result.errors)}[/red] errors"
    )


# ─────────────────────────────────────────────────────────────────────────────
# history subcommand
# ─────────────────────────────────────────────────────────────────────────────

def cmd_history(args: argparse.Namespace) -> None:
    limit = None if getattr(args, "all", False) else 20
    entries = list_history(limit=limit or 20)

    if not entries:
        console.print("[yellow]No history found.[/yellow]")
        return

    # If we have a real TTY, launch the TUI history viewer
    if sys.stdout.isatty():
        action, eid = _run_tui_history(entries)
        if action == "undo" and eid:
            # Delegate to undo
            fake_args = argparse.Namespace(id=eid, dry_run=False)
            cmd_undo(fake_args)
        return

    # Plain-text fallback
    console.print()
    console.print(Rule("Operation History", style="cyan"))
    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=box.SIMPLE_HEAD,
    )
    table.add_column("ID", style="dim", width=8)
    table.add_column("Time", width=20)
    table.add_column("Directory", style="cyan")
    table.add_column("Files", justify="right")

    for e in entries:
        ts = e.get("timestamp", "")[:19].replace("T", " ")
        table.add_row(
            e.get("id", "?")[:6],
            ts,
            Path(e.get("base", "?")).name,
            str(e.get("total_files", 0)),
        )
    console.print(table)


# ─────────────────────────────────────────────────────────────────────────────
# deduplicate helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_deduplicate(target_dir: Path, strategy_str: str,
                     recursive: bool, max_depth: int | None,
                     dry_run: bool, quiet: bool) -> None:
    strategy_map = {
        "keep-newest": DedupeStrategy.KEEP_NEWEST,
        "keep-oldest": DedupeStrategy.KEEP_OLDEST,
        "keep-largest": DedupeStrategy.KEEP_LARGEST,
    }
    strategy = strategy_map.get(strategy_str, DedupeStrategy.KEEP_NEWEST)

    if not quiet:
        console.print(Rule("Duplicate Detection", style="yellow"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning files…", total=None)
        files = collect_files(target_dir, recursive=recursive, max_depth=max_depth)
        progress.update(task, description=f"Hashing {len(files)} files…", total=len(files))
        groups = find_duplicates(files)
        progress.update(task, completed=len(files))

    if not groups:
        console.print("[green]No duplicates found![/green]")
        return

    total_removable = sum(len(g.files) - 1 for g in groups)
    console.print(
        f"\n  Found [bold yellow]{len(groups)}[/bold yellow] duplicate groups "
        f"([bold]{total_removable}[/bold] files removable)\n"
    )

    # Resolve which to keep
    for g in groups:
        resolve_strategy(g, strategy)

    # Show preview table
    table = Table(
        show_header=True, header_style="bold yellow",
        box=box.ROUNDED, border_style="dim",
    )
    table.add_column("Keep", style="green", min_width=30)
    table.add_column("Remove", style="red", min_width=30)
    table.add_column("Size", justify="right", style="dim")

    shown = 0
    for g in groups:
        size = g.keep.stat().st_size if g.keep and g.keep.exists() else 0
        size_str = _fmt_size(size)
        keep_name = g.keep.name if g.keep else "?"
        for rem in g.remove:
            table.add_row(keep_name, rem.name, size_str)
            shown += 1
            if shown >= 50:
                break
        if shown >= 50:
            break

    console.print(table)
    if total_removable > 50:
        console.print(f"  [dim]… and {total_removable - 50} more[/dim]")
    console.print()

    if not dry_run:
        confirmed = Confirm.ask(
            f"  Delete [bold red]{total_removable}[/bold red] duplicate files?",
            default=False,
            console=console,
        )
        if not confirmed:
            console.print("  [dim]Cancelled.[/dim]")
            return

        removed = 0
        for g in groups:
            for path in g.remove:
                try:
                    path.unlink()
                    removed += 1
                except OSError as e:
                    console.print(f"  [red]Could not remove {path.name}: {e}[/red]")

        console.print(
            f"\n  [bold green]✓[/bold green] "
            f"Removed [bold]{removed}[/bold] duplicate files."
        )
    else:
        console.print(
            f"  [bold yellow]DRY RUN[/bold yellow] — "
            f"{total_removable} files would be removed."
        )


def _fmt_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size //= 1024
    return f"{size:.1f} TB"


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FOLDR v4 — Smart File Organizer",
        formatter_class=argparse.RawTextHelpFormatter,
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

    parser.add_argument(
        "path", nargs="?",
        help="Directory to organize, or subcommand (watch / undo / history)",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without executing")
    parser.add_argument("--recursive", action="store_true",
                        help="Organize subdirectories recursively")
    parser.add_argument("--max-depth", type=int, default=None,
                        help="Maximum recursion depth (requires --recursive)")
    parser.add_argument("--follow-symlinks", action="store_true",
                        help="Follow symbolic links when recursing")
    parser.add_argument("--smart", action="store_true",
                        help="Use MIME detection to catch spoofed extensions")
    parser.add_argument(
        "--deduplicate",
        choices=["keep-newest", "keep-largest", "keep-oldest"],
        metavar="{keep-newest,keep-largest,keep-oldest}",
        help="Find and remove duplicate files",
    )
    parser.add_argument("--ignore", nargs="+", metavar="PATTERN",
                        help="Ignore patterns, e.g. '*.log' 'tmp/'")
    parser.add_argument("--config", metavar="FILE",
                        help="Path to custom TOML config file")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress all non-error output")
    parser.add_argument("--interactive", action="store_true", default=None,
                        help="Force TUI preview before executing")
    parser.add_argument("--no-interactive", action="store_true",
                        help="Skip TUI preview")
    # Undo / History flags
    parser.add_argument("--id", help="History entry ID for undo")
    parser.add_argument("--all", action="store_true",
                        help="Show full history (foldr history --all)")

    args, remaining = parser.parse_known_args()

    # ── Banner ────────────────────────────────────────────────────────────────
    _print_banner(quiet=args.quiet)

    # ── Subcommand routing ───────────────────────────────────────────────────
    if args.path == "undo":
        cmd_undo(args)
        return

    if args.path == "history":
        cmd_history(args)
        return

    if args.path == "watch":
        # Extract the actual watch target from raw argv
        raw = sys.argv[1:]
        try:
            watch_idx = raw.index("watch")
            candidates = [a for a in raw[watch_idx + 1:] if not a.startswith("-")]
            watch_target = candidates[0] if candidates else None
        except (ValueError, IndexError):
            watch_target = None
        cmd_watch(watch_target, args)
        return

    # ── Resolve target directory ──────────────────────────────────────────────
    if args.path is None:
        cwd = Path.cwd()
        if not args.quiet:
            console.print(
                Panel.fit(
                    f"[bold]No directory specified.[/bold]\n\n"
                    f"  Target : [cyan]{cwd}[/cyan]\n\n"
                    "[dim]  Pass a path to organize a different directory.[/dim]",
                    border_style="cyan",
                )
            )
        confirmed = Confirm.ask(
            f"  Organize [bold]{cwd.name}[/bold] (current directory)?",
            default=False,
            console=console,
        )
        if not confirmed:
            console.print("  [dim]Cancelled.[/dim]\n")
            raise SystemExit(0)
        target_dir = cwd
    else:
        target_dir = Path(args.path).resolve()

    if not target_dir.exists() or not target_dir.is_dir():
        console.print(
            f"[bold red]Error:[/bold red] "
            f"'{target_dir}' is not a valid directory."
        )
        sys.exit(1)

    # ── Load template ─────────────────────────────────────────────────────────
    template: dict = {}
    config_label: str | None = None
    if args.config:
        config_path = Path(args.config)
        try:
            result_t = load_template(config_path)
            template, config_label = result_t
        except FileNotFoundError as e:
            console.print(f"[red]Config error: {e}[/red]")
            sys.exit(1)
    else:
        result_t = load_template(None)
        template, config_label = result_t

    if config_label and not args.quiet:
        console.print(f"  [dim]Config: {config_label}[/dim]")

    # ── Deduplicate mode ──────────────────────────────────────────────────────
    if args.deduplicate:
        _run_deduplicate(
            target_dir=target_dir,
            strategy_str=args.deduplicate,
            recursive=args.recursive,
            max_depth=args.max_depth,
            dry_run=args.dry_run,
            quiet=args.quiet,
        )
        return

    # ── Determine interactive mode ────────────────────────────────────────────
    # Default: interactive when stdout is a real TTY, unless --no-interactive
    use_tui = (
        sys.stdout.isatty()
        and not args.no_interactive
        and not args.quiet
    )
    if args.interactive:
        use_tui = True

    # ── Run organizer (dry-run first if TUI preview) ──────────────────────────
    if not args.quiet:
        console.print(Rule(f"Scanning  {target_dir.name}", style="cyan"))

    t_start = time.monotonic()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning files…", total=None)
        # Always do a dry-run scan first to collect planned actions
        preview_result = organize_folder(
            base=target_dir,
            dry_run=True,
            recursive=args.recursive,
            max_depth=args.max_depth,
            follow_symlinks=args.follow_symlinks,
            extra_ignore=args.ignore,
            category_template=template or None,
            smart=args.smart,
        )
        progress.update(task, description="Scan complete.")

    if not preview_result.actions:
        console.print(
            Panel.fit(
                "[bold green]✓[/bold green]  Nothing to organize — "
                "directory is already tidy!",
                border_style="green",
            )
        )
        return

    # ── TUI preview / approval ────────────────────────────────────────────────
    if use_tui and not args.dry_run:
        confirmed = _run_tui_preview(
            actions=preview_result.actions,
            records=preview_result.records,
            base=target_dir,
            dry_run=False,
        )
        if not confirmed:
            console.print("\n  [bold yellow]Cancelled.[/bold yellow] No files were moved.\n")
            return
    elif args.dry_run:
        # Just show the TUI preview but don't ask for confirmation
        if use_tui:
            _run_tui_preview(
                actions=preview_result.actions,
                records=preview_result.records,
                base=target_dir,
                dry_run=True,
            )
        else:
            _print_dry_run_table(preview_result, args.quiet)

        elapsed = time.monotonic() - t_start
        _print_summary(preview_result, target_dir, elapsed, dry_run=True, quiet=args.quiet)
        return
    else:
        # No TUI — plain-text confirmation
        _print_dry_run_table(preview_result, args.quiet)
        if not args.quiet:
            confirmed = Confirm.ask(
                f"\n  Execute [bold]{len(preview_result.actions)}[/bold] moves?",
                default=True,
                console=console,
            )
            if not confirmed:
                console.print("  [dim]Cancelled.[/dim]")
                return

    # ── Execute ───────────────────────────────────────────────────────────────
    if not args.quiet:
        console.print(Rule("Executing", style="green"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "Moving files…", total=len(preview_result.actions)
        )
        result = organize_folder(
            base=target_dir,
            dry_run=False,
            recursive=args.recursive,
            max_depth=args.max_depth,
            follow_symlinks=args.follow_symlinks,
            extra_ignore=args.ignore,
            category_template=template or None,
            smart=args.smart,
        )
        progress.update(task, completed=len(result.actions))

    elapsed = time.monotonic() - t_start

    # Save history
    log_path = save_history(result.records, target_dir, dry_run=False)
    if log_path and args.verbose:
        console.print(f"  [dim]History saved: {log_path}[/dim]")

    # Verbose action log
    if args.verbose:
        for action in result.actions:
            console.print(f"  [dim]→ {action}[/dim]")

    _print_summary(result, target_dir, elapsed, dry_run=False, quiet=args.quiet)

    # Offer empty dir cleanup
    if not args.quiet and not args.dry_run:
        scan = scan_empty_dirs(target_dir)
        if scan.found:
            console.print(
                f"\n  [yellow]⚠[/yellow]  "
                f"Found [bold]{len(scan.found)}[/bold] empty "
                f"director{'y' if len(scan.found) == 1 else 'ies'}."
            )
            if Confirm.ask("  Remove empty directories?", default=False, console=console):
                removed = remove_empty_dirs(scan.found, dry_run=False)
                console.print(
                    f"  [green]Removed {len(removed.removed)} empty directories.[/green]"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Plain-text dry-run preview (non-TUI fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _print_dry_run_table(result, quiet: bool) -> None:
    if quiet:
        return

    # Group by category
    by_cat: dict[str, list] = {}
    for r in result.records:
        by_cat.setdefault(r.category, []).append(r)

    table = Table(
        title="Planned Moves",
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
        border_style="dim",
        expand=False,
    )
    table.add_column("File", min_width=30)
    table.add_column("→ Destination", style="dim", min_width=20)
    table.add_column("Category", min_width=16)

    shown = 0
    for cat, records in sorted(by_cat.items(), key=lambda x: -len(x[1])):
        style = _cat_style(cat)
        icon  = _cat_icon(cat)
        for r in records[:10]:  # cap per category to avoid flooding
            dest_folder = Path(r.destination).parent.name
            table.add_row(
                r.filename,
                dest_folder + "/",
                f"[{style}]{icon} {cat}[/{style}]",
            )
            shown += 1

    console.print(table)
    total = len(result.records)
    if total > shown:
        console.print(f"  [dim]… and {total - shown} more files[/dim]")
    console.print()


if __name__ == "__main__":
    main()