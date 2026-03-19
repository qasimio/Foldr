"""
foldr.watches
~~~~~~~~~~~~~
Persistent watch registry for FOLDR v2.1.

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
    startup: bool = False,
) -> None:
    data = _load()
    data[str(path.resolve())] = {
        "pid":       pid,
        "started":   datetime.now(timezone.utc).isoformat(),
        "dry_run":   dry_run,
        "recursive": recursive,
        "startup":   startup,
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


# ── Startup registration ───────────────────────────────────────────────────────

def register_startup(target: Path, recursive: bool = False) -> tuple[bool, str]:
    name = "foldr-watch-" + target.name.lower().replace(" ", "_")
    if _IS_WIN:   return _startup_win(target, name, recursive)
    elif _IS_MAC: return _startup_mac(target, name, recursive)
    else:         return _startup_linux(target, name, recursive)


def unregister_startup(target: Path) -> tuple[bool, str]:
    name = "foldr-watch-" + target.name.lower().replace(" ", "_")
    if _IS_WIN:   return _unstartup_win(name)
    elif _IS_MAC: return _unstartup_mac(name)
    else:         return _unstartup_linux(name)


def _startup_win(target: Path, name: str, recursive: bool) -> tuple[bool, str]:
    try:
        import winreg   # type: ignore[import]
        REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
        python  = _get_python()
        cmd     = f'"{python}" -m foldr.cli _watch-daemon "{target.resolve()}"'
        if recursive:
            cmd += " --recursive"
        key = winreg.OpenKey(           # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,   # type: ignore[attr-defined]
            REG_RUN, 0,
            winreg.KEY_SET_VALUE,       # type: ignore[attr-defined]
        )
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)  # type: ignore[attr-defined]
        winreg.CloseKey(key)                                   # type: ignore[attr-defined]
        return True, f"Registered startup (Registry): {name}"
    except Exception as exc:
        return False, f"Windows startup failed: {exc}"


def _unstartup_win(name: str) -> tuple[bool, str]:
    try:
        import winreg   # type: ignore[import]
        REG_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(           # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,   # type: ignore[attr-defined]
            REG_RUN, 0,
            winreg.KEY_SET_VALUE,       # type: ignore[attr-defined]
        )
        winreg.DeleteValue(key, name)   # type: ignore[attr-defined]
        winreg.CloseKey(key)            # type: ignore[attr-defined]
        return True, f"Removed startup entry: {name}"
    except Exception as exc:
        return False, str(exc)


def _startup_mac(target: Path, name: str, recursive: bool) -> tuple[bool, str]:
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist  = agents / f"com.{name}.plist"
    python = _get_python()
    args   = [python, "-m", "foldr.cli", "_watch-daemon", str(target.resolve())]
    if recursive:
        args.append("--recursive")
    log    = Path.home() / ".foldr" / "watch_logs" / f"{target.name}-daemon.log"
    xml    = "\n".join(f"        <string>{a}</string>" for a in args)
    plist.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        f'    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        f'<plist version="1.0"><dict>\n'
        f'    <key>Label</key>           <string>com.{name}</string>\n'
        f'    <key>ProgramArguments</key>\n'
        f'    <array>\n{xml}\n    </array>\n'
        f'    <key>RunAtLoad</key>       <true/>\n'
        f'    <key>KeepAlive</key>       <true/>\n'
        f'    <key>StandardOutPath</key> <string>{log}</string>\n'
        f'    <key>StandardErrorPath</key> <string>{log}</string>\n'
        f'</dict></plist>\n',
        encoding="utf-8",
    )
    try:
        subprocess.run(["launchctl", "load", str(plist)], capture_output=True)
    except Exception:
        pass
    return True, f"Registered LaunchAgent: {plist}"


def _unstartup_mac(name: str) -> tuple[bool, str]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"com.{name}.plist"
    if plist.exists():
        try:
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        except Exception:
            pass
        plist.unlink()
        return True, f"Removed LaunchAgent: {plist}"
    return False, f"No LaunchAgent: {plist}"


def _startup_linux(target: Path, name: str, recursive: bool) -> tuple[bool, str]:
    svc_dir = Path.home() / ".config" / "systemd" / "user"
    svc_dir.mkdir(parents=True, exist_ok=True)
    svc     = svc_dir / f"{name}.service"
    python  = _get_python()
    exec_   = f'"{python}" -m foldr.cli _watch-daemon "{target.resolve()}"'
    if recursive:
        exec_ += " --recursive"
    log = Path.home() / ".foldr" / "watch_logs" / f"{target.name}-daemon.log"
    svc.write_text(
        f"[Unit]\n"
        f"Description=FOLDR watch daemon — {target}\n"
        f"After=graphical-session.target\n\n"
        f"[Service]\n"
        f"Type=simple\n"
        f"ExecStart={exec_}\n"
        f"Restart=always\n"
        f"RestartSec=5\n"
        f"StandardOutput=append:{log}\n"
        f"StandardError=append:{log}\n\n"
        f"[Install]\n"
        f"WantedBy=default.target\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{name}.service"],
            capture_output=True,
        )
        return True, f"Enabled systemd user service: {svc}"
    except Exception:
        return True, (
            f"Created {svc}\n"
            f"  Run: systemctl --user daemon-reload\n"
            f"       systemctl --user enable --now {name}.service"
        )


def _unstartup_linux(name: str) -> tuple[bool, str]:
    svc = Path.home() / ".config" / "systemd" / "user" / f"{name}.service"
    if svc.exists():
        try:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"{name}.service"],
                           capture_output=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        except Exception:
            pass
        svc.unlink()
        return True, f"Removed systemd unit: {name}.service"
    return False, f"No systemd unit: {name}.service"