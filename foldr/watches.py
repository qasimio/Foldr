"""
foldr.watches
~~~~~~~~~~~~~
Persistent watch registry for FOLDR v4.

Watch modes
-----------
  Session watch  (default):
    `foldr watch ~/Downloads`
    Starts a background daemon that runs until:
      - you run `foldr unwatch ~/Downloads`
      - the machine reboots

  Startup watch  (--startup flag):
    `foldr watch ~/Downloads --startup`
    Registers the watch to auto-start on login / boot.
    Uses the OS login mechanism:
      Windows : HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
      macOS   : ~/Library/LaunchAgents/com.foldr.watch.<name>.plist
      Linux   : ~/.config/systemd/user/foldr-watch-<name>.service
                (or ~/.config/autostart/ for desktop environments)

Windows console popup fix
--------------------------
On Windows, `python.exe` always opens a console window. We use
`pythonw.exe` (the windowless Python) when available. If only
`python.exe` exists, we fall back to CREATE_NO_WINDOW | DETACHED_PROCESS.
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
_IS_WIN = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"


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
    """Cross-platform PID liveness check."""
    try:
        if _IS_WIN:
            try:
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
                    return r == 0x102
                return False
            except Exception:
                return False
        else:
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def get_watches() -> dict:
    """Return active watches, auto-removing dead PIDs."""
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


def _get_python() -> str:
    """
    Return the absolute path to the Python executable for daemon spawning.
    Uses sys.executable (absolute path to venv python) so startup entries
    work after reboot without needing to activate the venv.
    On Windows, prefers pythonw.exe to avoid console popups.
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
    Spawn a detached background daemon process.
    Returns the daemon PID.

    Windows : uses pythonw.exe (no console window) + DETACHED_PROCESS
    Unix    : uses start_new_session=True (equivalent to double-fork/setsid)
    """
    cmd = [
        _get_python(),
        "-m", "foldr.cli",
        "_watch-daemon", str(target.resolve()),
    ]
    if dry_run:
        cmd.append("--preview")
    if recursive:
        cmd.append("--recursive")
    if extra_ignore:
        cmd += ["--ignore"] + extra_ignore

    if _IS_WIN:
        DETACHED_PROCESS     = 0x00000008
        CREATE_NO_WINDOW     = 0x08000000
        CREATE_NEW_PROC_GRP  = 0x00000200
        proc = subprocess.Popen(
            cmd,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROC_GRP,
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
    """Stop the watcher for path. Returns (success, message)."""
    watches = _load()
    key     = str(path.resolve())

    if key not in watches:
        return False, f"No active watch for: {path}"

    info = watches[key]
    pid  = info.get("pid", 0)

    if not pid:
        remove_watch(path)
        return False, "No PID recorded — watch entry removed."

    if not _is_alive(pid):
        remove_watch(path)
        return True, f"Watcher was already stopped (PID {pid})"

    try:
        if _IS_WIN:
            import ctypes
            PROCESS_TERMINATE = 1
            handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
                PROCESS_TERMINATE, False, pid
            )
            if handle:
                ctypes.windll.kernel32.TerminateProcess(handle, 0)  # type: ignore[attr-defined]
                ctypes.windll.kernel32.CloseHandle(handle)           # type: ignore[attr-defined]
        else:
            os.kill(pid, signal.SIGTERM)

        remove_watch(path)
        return True, f"Stopped watcher (PID {pid})"
    except Exception as e:
        remove_watch(path)
        return False, f"Error stopping PID {pid}: {e}"


# ── Startup registration ───────────────────────────────────────────────────────

def register_startup(target: Path, recursive: bool = False) -> tuple[bool, str]:
    """
    Register the watcher to start automatically on login/boot.
    Returns (success, message_or_path).
    """
    name = "foldr-watch-" + target.name.replace(" ", "_").lower()

    if _IS_WIN:
        return _register_startup_windows(target, name, recursive)
    elif _IS_MAC:
        return _register_startup_macos(target, name, recursive)
    else:
        return _register_startup_linux(target, name, recursive)


def unregister_startup(target: Path) -> tuple[bool, str]:
    """Remove startup registration for a watched path."""
    name = "foldr-watch-" + target.name.replace(" ", "_").lower()

    if _IS_WIN:
        try:
            import winreg  # type: ignore[import]
            key = winreg.OpenKey(  # type: ignore[attr-defined]
                winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,  # type: ignore[attr-defined]
            )
            winreg.DeleteValue(key, name)  # type: ignore[attr-defined]
            winreg.CloseKey(key)  # type: ignore[attr-defined]
            return True, f"Removed Windows startup entry: {name}"
        except Exception as e:
            return False, str(e)
    elif _IS_MAC:
        plist = Path.home() / "Library" / "LaunchAgents" / f"com.{name}.plist"
        if plist.exists():
            plist.unlink()
            return True, f"Removed LaunchAgent: {plist}"
        return False, f"No LaunchAgent found: {plist}"
    else:
        service = Path.home() / ".config" / "systemd" / "user" / f"{name}.service"
        if service.exists():
            service.unlink()
            try:
                subprocess.run(
                    ["systemctl", "--user", "disable", "--now", f"{name}.service"],
                    capture_output=True,
                )
            except Exception:
                pass
            return True, f"Removed systemd unit: {service}"
        return False, f"No systemd unit found: {service}"


def _register_startup_windows(target: Path, name: str, recursive: bool) -> tuple[bool, str]:
    try:
        import winreg  # type: ignore[import]
        cmd = (
            f'"{_get_python()}" -m foldr.cli _watch-daemon "{target.resolve()}"'
            + (" --recursive" if recursive else "")
        )
        key = winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,  # type: ignore[attr-defined]
        )
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)  # type: ignore[attr-defined]
        winreg.CloseKey(key)  # type: ignore[attr-defined]
        return True, f"Registered Windows startup: HKCU\\...\\Run\\{name}"
    except Exception as e:
        return False, f"Windows startup registration failed: {e}"


def _register_startup_macos(target: Path, name: str, recursive: bool) -> tuple[bool, str]:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / f"com.{name}.plist"
    args = [_get_python(), "-m", "foldr.cli", "_watch-daemon", str(target.resolve())]
    if recursive:
        args.append("--recursive")
    args_xml = "\n".join(f"        <string>{a}</string>" for a in args)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>         <string>com.{name}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>     <true/>
    <key>KeepAlive</key>     <true/>
    <key>StandardOutPath</key>
    <string>{Path.home() / '.foldr' / 'watch_logs' / (target.name + '-startup.log')}</string>
    <key>StandardErrorPath</key>
    <string>{Path.home() / '.foldr' / 'watch_logs' / (target.name + '-startup.log')}</string>
</dict>
</plist>"""
    plist_path.write_text(plist, encoding="utf-8")
    try:
        subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
    except Exception:
        pass
    return True, f"Registered macOS LaunchAgent: {plist_path}"


def _register_startup_linux(target: Path, name: str, recursive: bool) -> tuple[bool, str]:
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    service_path = systemd_dir / f"{name}.service"
    cmd = f'"{_get_python()}" -m foldr.cli _watch-daemon "{target.resolve()}"'
    if recursive:
        cmd += " --recursive"
    unit = f"""[Unit]
Description=FOLDR watch daemon for {target}
After=network.target

[Service]
Type=simple
ExecStart={cmd}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    service_path.write_text(unit, encoding="utf-8")
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{name}.service"],
            capture_output=True,
        )
        return True, f"Enabled systemd user service: {service_path}"
    except Exception:
        return True, f"Created service file: {service_path}\n  Run: systemctl --user enable --now {name}.service"