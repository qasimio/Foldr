"""
foldr.watches
~~~~~~~~~~~~~
Persistent watch registry for FOLDR v2.1.

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
) -> None:
    data = _load()
    data[str(path.resolve())] = {
        "pid":       pid,
        "started":   datetime.now(timezone.utc).isoformat(),
        "dry_run":   dry_run,
        "recursive": recursive,
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
    Uses sys.executable resolved to an absolute path.
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

def spawn_daemon(
    target: Path,
    dry_run: bool = False,
    recursive: bool = False,
    extra_ignore: list[str] | None = None,
) -> int:
    """
    Spawn a detached background daemon. Returns its PID.
    Windows: pythonw.exe + DETACHED_PROCESS | CREATE_NO_WINDOW (no popup).
    Unix:    start_new_session=True (setsid equivalent).
    """
    python = _get_python()
    cmd    = [python, "-m", "foldr.cli",
              "_watch-daemon", str(target.resolve())]
    if dry_run:
        cmd.append("--preview")
    if recursive:
        cmd.append("--recursive")
    if extra_ignore:
        cmd += ["--ignore"] + extra_ignore

    if _IS_WIN:
        DETACHED    = 0x00000008
        NO_WINDOW   = 0x08000000
        NEW_GROUP   = 0x00000200
        proc = subprocess.Popen(
            cmd,
            creationflags=DETACHED | NO_WINDOW | NEW_GROUP,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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