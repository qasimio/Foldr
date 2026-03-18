"""
foldr.watches
~~~~~~~~~~~~~
Persistent watch registry for FOLDR v4.

Design
------
A "watch" is FOLDR running permanently in the background for a specific
directory. The user runs `foldr watch ~/Downloads` once and it keeps
organizing forever — even when they're not looking.

Storage: ~/.foldr/watches.json
  {
    "/home/user/Downloads": {
      "pid":       12345,       # OS process ID of the watcher daemon
      "started":   "2026-03-07T15:20:33",
      "dry_run":   false,
      "total":     42           # files organized so far
    }
  }

Architecture
------------
  foldr watch ~/Downloads
      → spawns a daemon subprocess (foldr _watch-daemon ~/Downloads)
      → records PID in watches.json
      → returns immediately to shell

  foldr unwatch ~/Downloads
      → reads PID from watches.json
      → sends SIGTERM (Unix) or TerminateProcess (Windows)
      → removes entry from watches.json

  foldr watches
      → shows table of all active watches + their stats

Cross-OS daemon strategy
------------------------
  Linux/macOS : subprocess.Popen with os.setsid() (detaches from terminal)
  Windows     : subprocess.Popen with DETACHED_PROCESS flag + CREATE_NO_WINDOW

The daemon process itself uses watchdog (which has OS-native backends:
  inotify on Linux, kqueue on macOS, ReadDirectoryChangesW on Windows).
"""
from __future__ import annotations
import json, os, platform, signal, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

_WATCHES_FILE = Path.home() / ".foldr" / "watches.json"
_IS_WIN = platform.system() == "Windows"


# ── Registry ───────────────────────────────────────────────────────────────────

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


def _is_alive(pid: int) -> bool:
    """Check if a PID is still running cross-platform."""
    try:
        if _IS_WIN:
            import ctypes
            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                import ctypes.wintypes as wt
                result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
                ctypes.windll.kernel32.CloseHandle(handle)
                return result == 0x102  # WAIT_TIMEOUT = still running
            return False
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def get_watches() -> dict:
    """Return current watches, removing dead PIDs automatically."""
    data    = _load()
    cleaned = {}
    changed = False
    for path, info in data.items():
        pid = info.get("pid", 0)
        if pid and _is_alive(pid):
            cleaned[path] = info
        else:
            changed = True  # dead process, drop it
    if changed:
        _save(cleaned)
    return cleaned


def add_watch(path: Path, pid: int, dry_run: bool = False) -> None:
    data = _load()
    data[str(path)] = {
        "pid":     pid,
        "started": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "total":   0,
    }
    _save(data)


def remove_watch(path: Path) -> bool:
    """Remove watch entry. Returns True if it existed."""
    data = _load()
    key  = str(path.resolve())
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def increment_count(path: Path, n: int = 1) -> None:
    """Increment the organized-file counter for a watched path."""
    data = _load()
    key  = str(path.resolve())
    if key in data:
        data[key]["total"] = data[key].get("total", 0) + n
        _save(data)


# ── Spawn daemon ───────────────────────────────────────────────────────────────

def spawn_daemon(target: Path, dry_run: bool = False,
                 extra_ignore: list[str] | None = None) -> int:
    """
    Start a detached background watcher for `target`.
    Returns the daemon PID.

    Cross-OS:
      Unix  : double-fork / setsid to detach from the calling terminal
      Windows: DETACHED_PROCESS | CREATE_NO_WINDOW flags
    """
    cmd = [
        sys.executable, "-m", "foldr.cli",
        "_watch-daemon", str(target),
    ]
    if dry_run:
        cmd.append("--preview")
    if extra_ignore:
        cmd.extend(["--ignore"] + extra_ignore)

    if _IS_WIN:
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        proc = subprocess.Popen(
            cmd,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,   # setsid equivalent
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return proc.pid


def kill_watch(path: Path) -> tuple[bool, str]:
    """
    Stop the watcher for `path`.
    Returns (success, message).
    """
    watches = _load()
    key     = str(path.resolve())
    if key not in watches:
        return False, f"No active watch for {path}"

    info = watches[key]
    pid  = info.get("pid", 0)

    if not pid:
        remove_watch(path)
        return False, "No PID recorded for this watch"

    if not _is_alive(pid):
        remove_watch(path)
        return True, f"Watcher was already stopped (PID {pid} not running)"

    try:
        if _IS_WIN:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE=1
            if handle:
                ctypes.windll.kernel32.TerminateProcess(handle, 0)
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(pid, signal.SIGTERM)

        remove_watch(path)
        return True, f"Stopped watcher (PID {pid})"
    except Exception as e:
        remove_watch(path)
        return False, f"Error stopping PID {pid}: {e}"