"""
foldr.watch
~~~~~~~~~~~
Background directory watcher for FOLDR 2.1.

Key fixes
---------
1. Removed _seen_in_session — files can be re-organized if moved back to root.
   Loop prevention: _organize_one checks if file is already in a category folder.

2. Initial scan on startup — organizes existing unorganized files immediately.

3. on_moved handler — catches files moved INTO the watched directory (not just created).

4. Daemon re-registers its PID in watches.json on startup — so 'foldr watches'
   shows accurate info after a reboot.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from foldr.term import (
    ACCENT, BOLD, COL_OK, COL_WARN, FG_MUTED, RESET, cat_fg, cat_icon,
)
from foldr.history import save_history
from foldr.organizer import _classify_file, _matches_any

_IN_PROGRESS: frozenset[str] = frozenset({
    ".crdownload", ".part", ".tmp", ".download",
    ".partial", ".!ut", ".ytdl", ".aria2", ".opdownload",
})

_LOG_DIR = Path.home() / ".foldr" / "watch_logs"


def _normalize_path(src: object) -> Path:
    if isinstance(src, memoryview):
        src = bytes(src)
    if isinstance(src, (bytes, bytearray)):
        return Path(src.decode(errors="replace"))
    return Path(str(src))


def _file_stable(p: Path) -> bool:
    try:
        before = p.stat().st_size
    except OSError:
        return False
    time.sleep(0.4)
    try:
        return p.stat().st_size == before
    except OSError:
        return False


def _get_logger(base: Path) -> logging.Logger:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe     = base.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    log_file = _LOG_DIR / f"{safe}.log"
    name     = f"foldr.watch.{safe}"
    logger   = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def _get_category_folders(base: Path, template: dict | None) -> set[str]:
    """Return the set of folder names FOLDR creates inside base."""
    from foldr.config import CATEGORIES_TEMPLATE
    tmpl = template or CATEGORIES_TEMPLATE
    return {v["folder"] for v in tmpl.values()}


def _organize_one(
    file_path: Path,
    base: Path,
    template: dict | None,
    dry_run: bool,
    ignore_patterns: list[str],
    logger: logging.Logger,
    category_folders: set[str],
) -> tuple[str, str] | None:
    """
    Organize exactly one file.

    Loop prevention (no _seen_in_session):
    Files that are already inside a FOLDR category folder are skipped.
    Files that have been moved back to root can be organized again.
    """
    from foldr.config import CATEGORIES_TEMPLATE
    tmpl = template or CATEGORIES_TEMPLATE

    if not file_path.exists() or not file_path.is_file():
        return None

    try:
        file_parent   = file_path.parent.resolve()
        base_resolved = base.resolve()

        if file_parent != base_resolved:
            # File is in a subdirectory — check if it's already in a category folder
            try:
                rel_parts = file_parent.relative_to(base_resolved).parts
            except ValueError:
                return None  # outside base entirely

            if rel_parts and rel_parts[0] in category_folders:
                return None  # already organized — do not re-move
    except OSError:
        return None

    if _matches_any(file_path.name, str(file_path), ignore_patterns):
        logger.info("SKIP (ignored)      %s", file_path.name)
        return None

    cat, dest_folder = _classify_file(file_path, tmpl)
    if not cat or not dest_folder:
        logger.info("SKIP (unknown ext)  %s", file_path.name)
        return None

    dest_dir  = base / dest_folder
    dest_path = dest_dir / file_path.name

    try:
        if file_path.resolve() == dest_path.resolve():
            logger.info("SKIP (already here) %s", file_path.name)
            return None
    except OSError:
        pass

    if dry_run:
        logger.info("PREVIEW  %s  ->  %s/", file_path.name, dest_folder)
        return cat, dest_folder

    dest_dir.mkdir(parents=True, exist_ok=True)

    if dest_path.exists():
        stem, suf, n = file_path.stem, file_path.suffix, 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_({n}){suf}"
            n += 1

    shutil.move(str(file_path), str(dest_path))
    logger.info("MOVED  %s  ->  %s/", file_path.name, dest_folder)
    return cat, dest_folder


def run_watch(
    base: Path,
    template: dict | None = None,
    dry_run: bool = False,
    recursive: bool = False,
    extra_ignore: list[str] | None = None,
    daemon_mode: bool = False,
) -> None:
    """
    1. Immediately organize all existing files in base (initial scan).
    2. Then watch for new/modified/moved files forever.

    After reboot: the daemon restarts via systemd/registry, runs the initial
    scan to catch anything that arrived while it was down, then resumes watching.
    """
    try:
        from watchdog.observers import Observer               # type: ignore[import]
        from watchdog.events import FileSystemEventHandler   # type: ignore[import]
    except ImportError:
        msg = "\n  watchdog not installed.\n  Run: pip install watchdog\n"
        (_get_logger(base).error if daemon_mode else
         lambda m: print(m, file=sys.stderr))("watchdog not installed")
        sys.exit(1)

    logger           = _get_logger(base)
    ignore_patterns  = list(extra_ignore or [])
    category_folders = _get_category_folders(base, template)

    def _log_event(filename: str, dest: str, category: str) -> None:
        logger.info("-> %s  =>  %s/", filename, dest)
        if not daemon_mode:
            tag = f"  {COL_WARN}preview{RESET}" if dry_run else f"  {COL_OK}->{RESET}"
            ts  = time.strftime("%H:%M:%S")
            col = cat_fg(category)
            ico = cat_icon(category)
            print(
                f"{tag}  {FG_MUTED}{ts}{RESET}  "
                f"{col}{ico} {BOLD}{filename:<38}{RESET}  "
                f"{FG_MUTED}->{RESET}  {col}{dest}/{RESET}"
            )
            sys.stdout.flush()

    # ── Step 1: Initial scan ───────────────────────────────────────────────────
    logger.info("INITIAL SCAN  %s  recursive=%s", base, recursive)
    try:
        from foldr.organizer import organize_folder
        result = organize_folder(
            base=base,
            dry_run=dry_run,
            recursive=recursive,
            extra_ignore=ignore_patterns,
            category_template=template,
            global_ignore=True,
        )
        n = len(result.records)
        logger.info("INITIAL SCAN: %d files organized", n)
        if n > 0 and not dry_run:
            save_history(result.records, base, dry_run=False, op_type="organize")
        for r in result.records:
            _log_event(r.filename, Path(r.destination).parent.name, r.category)
    except Exception as exc:
        logger.warning("INITIAL SCAN ERROR: %s", exc)

    # ── Step 2: Register PID in watches.json (daemon restart fix) ─────────────
    if daemon_mode:
        try:
            from foldr.watches import _load, _save
            data = _load()
            key  = str(base.resolve())
            if key in data:
                data[key]["pid"] = os.getpid()
                _save(data)
            else:
                # Entry was deleted — recreate it
                from foldr.watches import add_watch
                add_watch(base, pid=os.getpid(), dry_run=dry_run, recursive=recursive)
        except Exception as exc:
            logger.warning("PID update failed: %s", exc)

    # ── Step 3: File event watcher ─────────────────────────────────────────────
    _pending: dict[str, float] = {}
    _lock    = threading.Lock()
    _stop    = threading.Event()

    def _enqueue(path_str: str) -> None:
        p = Path(path_str)
        try:
            base_res = base.resolve()
            parent   = p.parent.resolve()
            # Filter events from inside category folders
            try:
                rel = parent.relative_to(base_res)
                if rel.parts and rel.parts[0] in category_folders:
                    return   # already organized
            except ValueError:
                return       # outside base
            if not recursive and parent != base_res:
                return
            if p.suffix.lower() in _IN_PROGRESS:
                return
        except OSError:
            return
        with _lock:
            _pending[str(p)] = time.monotonic()

    class _Handler(FileSystemEventHandler):   # type: ignore[misc]
        def on_created(self, event: object) -> None:    # type: ignore[override]
            if not getattr(event, "is_directory", False):
                _enqueue(str(_normalize_path(getattr(event, "src_path", ""))))

        def on_modified(self, event: object) -> None:   # type: ignore[override]
            if not getattr(event, "is_directory", False):
                _enqueue(str(_normalize_path(getattr(event, "src_path", ""))))

        def on_moved(self, event: object) -> None:      # type: ignore[override]
            # Catches files moved INTO the watched folder from elsewhere
            if not getattr(event, "is_directory", False):
                dest = getattr(event, "dest_path", None)
                if dest:
                    _enqueue(str(_normalize_path(dest)))

    def _processor() -> None:
        while not _stop.is_set():
            time.sleep(0.5)
            now = time.monotonic()
            with _lock:
                due = [ps for ps, t in list(_pending.items()) if now - t >= 0.5]
                for ps in due:
                    del _pending[ps]

            for ps in due:
                p = Path(ps)
                if not p.exists():
                    continue
                if not _file_stable(p):
                    continue

                outcome = _organize_one(
                    p, base, template, dry_run,
                    ignore_patterns, logger, category_folders,
                )
                if outcome is None:
                    continue

                cat, dest = outcome
                _log_event(p.name, dest, cat)

                if not dry_run:
                    from foldr.organizer import OperationRecord
                    rec = OperationRecord(
                        op_id=uuid.uuid4().hex[:8],
                        source=ps,
                        destination=str(base / dest / p.name),
                        filename=p.name,
                        category=cat,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                    save_history([rec], base, dry_run=False, op_type="organize")
                    if daemon_mode:
                        try:
                            from foldr.watches import increment_count
                            increment_count(base)
                        except Exception:
                            pass

    threading.Thread(target=_processor, daemon=True).start()

    observer = Observer()
    observer.schedule(_Handler(), str(base), recursive=recursive)
    observer.start()

    if daemon_mode:
        logger.info("WATCHING  %s", base)
        try:
            while not _stop.is_set():
                time.sleep(2)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            _stop.set()
            observer.stop()
            observer.join()
            logger.info("WATCH STOP  %s", base)
        return

    # Foreground
    mode = f"{COL_WARN}preview{RESET}" if dry_run else f"{COL_OK}live{RESET}"
    print(
        f"\n  Watching  {ACCENT + BOLD}{base}{RESET}  [{mode}]\n"
        f"  {FG_MUTED}New and modified files will be organized automatically.{RESET}\n"
        f"  {FG_MUTED}Files moved back to this folder will be re-organized.{RESET}\n"
        f"  {FG_MUTED}Press Ctrl+C to stop.{RESET}\n"
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n  {FG_MUTED}Stopping...{RESET}")
    finally:
        _stop.set()
        observer.stop()
        observer.join()