"""
foldr.watches
~~~~~~~~~~~~~
Persistent watch registry for FOLDR v0.2.1.

How startup-on-reboot works
----------------------------
The startup entry stores the ABSOLUTE PATH to the Python interpreter
(sys.executable resolved). After reboot, the venv is not activated,
but the absolute path still works because it's a real filesystem path.

The daemon re-registers its new PID in watches.json when it starts,
so `foldr watches` shows accurate info even after a reboot.

Pylance / cross-platform note
------------------------------
All winreg accesses use  # type: ignore[attr-defined]  so Pylance on
Linux/macOS does not flag them. The code is only reached at runtime
when _IS_WIN is True.
"""
from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_WATCHES_FILE = Path.home() / ".foldr" / "watches.json"
_SYSTEM       = platform.system()
_IS_WIN       = _SYSTEM == "Windows"
_IS_MAC       = _SYSTEM == "Darwin"


# ── Registry I/O ──────────────────────────────────────────────────────────────

def _load() -> dict:
    if _WATCHES_FILE.exists():
        try:
            return json.loads(_WATCHES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    _WATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WATCHES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── PID liveness ──────────────────────────────────────────────────────────────

def _is_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        if _IS_WIN:
            import ctypes
            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return False
            k32    = windll.kernel32
            SYNC   = 0x100000
            h      = k32.OpenProcess(SYNC, False, pid)
            if h:
                r = k32.WaitForSingleObject(h, 0)
                k32.CloseHandle(h)
                return r == 0x102      # WAIT_TIMEOUT → still running
            return False
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        return False


# ── Public registry API ────────────────────────────────────────────────────────

def get_watches() -> dict:
    """Return active watches; auto-remove dead PIDs."""
    data    = _load()
    cleaned = {p: info for p, info in data.items()
               if _is_alive(info.get("pid", 0))}
    if len(cleaned) != len(data):
        _save(cleaned)
    return cleaned


def add_watch(
    path: Path,
    pid: int,
    dry_run: bool = False,
    recursive: bool = False,
    config: str | None = None,
    no_ignore: bool = False,
) -> None:
    data = _load()
    data[str(path.resolve())] = {
        "pid":       pid,
        "started":   datetime.now(timezone.utc).isoformat(),
        "dry_run":   dry_run,
        "recursive": recursive,
        "config":    config,
        "no_ignore": no_ignore,
        "total":     0,
    }
    _save(data)


def remove_watch(path: Path) -> bool:
    data = _load()
    key  = str(path.resolve())
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def increment_count(path: Path, n: int = 1) -> None:
    data = _load()
    key  = str(path.resolve())
    if key in data:
        data[key]["total"] = data[key].get("total", 0) + n
        _save(data)


# ── Python executable (absolute, works without venv activation) ───────────────

def _get_python() -> str:
    """
    Return the absolute path to the current Python interpreter.
    Uses sys.executable resolved to an absolute path so startup entries
    (systemd / LaunchAgent / Registry) work after reboot without venv.
    On Windows, prefers pythonw.exe (no console popup).
    """
    exe = Path(sys.executable).resolve()
    if _IS_WIN:
        for cand in [exe.parent / "pythonw.exe",
                     exe.parent / "Scripts" / "pythonw.exe"]:
            if cand.exists():
                return str(cand)
    return str(exe)


# ── Daemon spawn ───────────────────────────────────────────────────────────────

def _project_root() -> str:
    """
    Return the directory that CONTAINS the foldr/ package folder.

    Works for:
    - pip install foldr      → site-packages dir (foldr is on sys.path already)
    - pip install -e .       → the source checkout root
    - python -m foldr.cli    → whatever directory has foldr/ as a child

    This path is passed as cwd AND prepended to PYTHONPATH when spawning
    the daemon subprocess, so the daemon can always import foldr.
    """
    try:
        # __file__ of this module = <root>/foldr/watches.py
        # .parent = <root>/foldr/
        # .parent.parent = <root>/   <- the directory that has foldr/ in it
        return str(Path(__file__).resolve().parent.parent)
    except Exception:
        return os.getcwd()


def spawn_daemon(
    target: Path,
    dry_run: bool = False,
    recursive: bool = False,
    extra_ignore: list[str] | None = None,
    config: str | None = None,
    no_ignore: bool = False,
) -> int:
    """
    Spawn a detached background daemon. Returns its PID.

    Cross-platform:
      Windows : pythonw.exe + DETACHED_PROCESS | CREATE_NO_WINDOW (no console popup)
      Linux   : start_new_session=True  +  cwd set to project root
      macOS   : same as Linux

    Linux note: the daemon subprocess must be able to import foldr. We pass
    the project root as cwd AND prepend it to PYTHONPATH so that
    `python -m foldr.cli` works whether foldr is pip-installed or just a folder.
    """
    python = _get_python()
    root   = _project_root()

    cmd = [python, "-m", "foldr.cli", "_watch-daemon", str(target.resolve())]
    if dry_run:
        cmd.append("--preview")
    if recursive:
        cmd.append("--recursive")
    if config:
        cmd += ["--config", str(Path(config).expanduser().resolve())]
    if no_ignore:
        cmd.append("--no-ignore")
    if extra_ignore:
        cmd += ["--ignore"] + extra_ignore

    # Build environment: prepend project root to PYTHONPATH
    env = os.environ.copy()
    sep = ";" if _IS_WIN else ":"
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (sep + old_pp if old_pp else "")

    # Redirect daemon output to log file so errors are visible
    _LOG_DIR = Path.home() / ".foldr" / "watch_logs"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe     = target.name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    log_file = _LOG_DIR / f"{safe}.log"

    with open(log_file, "a", encoding="utf-8") as lf:
        if _IS_WIN:
            DETACHED    = 0x00000008
            NO_WINDOW   = 0x08000000
            NEW_GROUP   = 0x00000200
            proc = subprocess.Popen(
                cmd,
                creationflags=DETACHED | NO_WINDOW | NEW_GROUP,
                close_fds=True,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=lf,
                stderr=lf,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                start_new_session=True,
                close_fds=True,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=lf,
                stderr=lf,
            )
    return proc.pid


# ── Kill ───────────────────────────────────────────────────────────────────────

def kill_watch(path: Path) -> tuple[bool, str]:
    watches = _load()
    key     = str(path.resolve())
    if key not in watches:
        return False, f"No active watch for: {path}"
    info = watches[key]
    pid  = info.get("pid", 0)
    if not pid:
        remove_watch(path)
        return False, "No PID recorded."
    if not _is_alive(pid):
        remove_watch(path)
        return True, f"Watcher was already stopped (PID {pid})"
    try:
        if _IS_WIN:
            import ctypes
            windll = getattr(ctypes, "windll", None)
            if windll:
                h = windll.kernel32.OpenProcess(1, False, pid)
                if h:
                    windll.kernel32.TerminateProcess(h, 0)
                    windll.kernel32.CloseHandle(h)
        else:
            os.kill(pid, signal.SIGTERM)
        remove_watch(path)
        return True, f"Stopped watcher (PID {pid})"
    except Exception as exc:
        remove_watch(path)
        return False, f"Error stopping PID {pid}: {exc}"