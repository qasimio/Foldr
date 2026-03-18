# FOLDR — Complete Functionality Guide

**Author:** Muhammad Qasim  
**GitHub:** https://github.com/qasimio/Foldr  
**Version:** 4.1

---

## Table of Contents

1. [Install](#install)
2. [pip install foldr vs pip install foldr\[all\]](#pip-extras-explained)
3. [Quick Start](#quick-start)
4. [All Commands](#all-commands)
5. [Ignore Rules](#ignore-rules)
6. [Custom Categories (config.toml)](#custom-categories)
7. [Watch Mode](#watch-mode)
8. [History & Undo](#history--undo)
9. [Dedup](#dedup)
10. [Per-OS File Locations](#per-os-file-locations)
11. [Config File Locations](#config-file-locations)
12. [Windows-Specific Notes](#windows-specific-notes)
13. [macOS-Specific Notes](#macos-specific-notes)
14. [Linux-Specific Notes](#linux-specific-notes)

---

## Install

```bash
pip install foldr
```

That's it. FOLDR works immediately on Linux, macOS, and Windows with no additional setup.

---

## pip install foldr vs pip install foldr\[all\]

When you run `pip install foldr` you get the **core** package.  
When you run `pip install foldr[all]` you get **extra optional features**.

Think of it like buying a car (base) vs. buying it with optional extras (sunroof, leather seats).

| Feature | `pip install foldr` | `pip install foldr[all]` |
|---------|--------------------|-----------------------|
| Organize files by type | ✓ | ✓ |
| Undo operations | ✓ | ✓ |
| Watch mode | ✓ | ✓ |
| History browser | ✓ | ✓ |
| Pretty tables in output | ✓ | ✓ |
| Windows ANSI colours | ✓ | ✓ |
| TOML config on Python 3.10 | ✗ | ✓ |
| `--smart` content detection | ✗ | ✓ |

**When do you need `foldr[all]`?**

- You use a custom `config.toml` AND you are on Python 3.10 (3.11+ has it built-in).
- You want `--smart` mode to catch misnamed files (e.g. a `.jpg` that is actually a PDF).

**`--smart` also needs a system library:**

```bash
# Linux (Debian/Ubuntu)
sudo apt install libmagic1
pip install "foldr[all]"

# macOS
brew install libmagic
pip install "foldr[all]"

# Windows (DLL included — no system lib needed)
pip install "foldr[all]"
```

---

## Quick Start

```bash
# Show what would happen (nothing moves)
foldr ~/Downloads --preview

# Organize (preview first, then ask to confirm)
foldr ~/Downloads

# Undo the last operation
foldr undo

# See history of all operations
foldr history
```

On **Windows**, always quote paths that may have spaces:

```powershell
foldr "D:\My Downloads" --preview
foldr "D:\My Downloads"
```

---

## All Commands

### Organize

```bash
foldr <path>                          # organize (shows preview, asks to confirm)
foldr <path> --preview                # dry-run — shows plan, nothing moves
foldr <path> --recursive              # also organize files in subdirectories
foldr <path> --recursive --depth 2    # limit to 2 levels of subdirectories
foldr <path> --follow-links           # follow symbolic links
foldr <path> --smart                  # detect file type by content, not extension
foldr <path> --verbose                # print every file as it moves
foldr <path> --quiet                  # no output (for scripts, CI, cron)
foldr <path> --config ~/custom.toml   # use a different category config
```

### Ignore

```bash
foldr <path> --ignore "*.log" "tmp/"  # skip these patterns this run
foldr <path> --no-ignore              # disable ALL ignore rules for this run
foldr <path> --show-ignored           # list which files were skipped and why
```

### Duplicates

```bash
# ⚠ IRREVERSIBLE — always preview first
foldr <path> --dedup keep-newest --preview
foldr <path> --dedup keep-newest      # delete older duplicates
foldr <path> --dedup keep-largest     # delete smaller duplicates
foldr <path> --dedup keep-oldest      # delete newer copies, keep originals
foldr <path> --recursive --dedup keep-newest   # dedup across subdirectories too
```

### Watch mode (background auto-organizer)

```bash
foldr watch <path>                    # start background watcher
foldr watch <path> --recursive        # watch subdirectories too
foldr watch <path> --startup          # also start on login/reboot
foldr watch <path> --preview          # watch but don't move (log only)
foldr watches                         # list all active watchers
foldr unwatch <path>                  # stop a specific watcher
foldr unwatch                         # interactive picker
```

### Undo & History

```bash
foldr undo                            # undo the most recent operation
foldr undo --id a1b2c3                # undo a specific operation by ID
foldr undo --preview                  # show what would be restored, don't move
foldr history                         # list last 50 operations
foldr history --all                   # list everything ever
```

### Config

```bash
foldr config                          # show all config file paths and status
foldr config --edit                   # open config.toml in your editor
```

---

## Ignore Rules

FOLDR has three layers of ignore rules, applied in this order:

### 1. Always-ignored (built-in, cannot be disabled)

```
.git/    .svn/    .hg/    __pycache__/    node_modules/
.venv/   venv/    .DS_Store    Thumbs.db    desktop.ini
```

### 2. Global ignore — `~/.foldr/.foldrignore` (default: ON)

This file applies to every `foldr` run automatically. Create it to permanently skip certain file types or names everywhere.

```
# ~/.foldr/.foldrignore
*.tmp
*.bak
*.log
desktop.ini
~$*
```

The global ignore is **always active by default**. Disable it for one run with `--no-ignore`.

### 3. Local `.foldrignore` — in the target directory

Create a `.foldrignore` in the folder you're organizing:

```
# .foldrignore in ~/Downloads
*.log
tmp/
build/
secret.txt
*_backup.*
```

### 4. CLI `--ignore` patterns

Add extra patterns for just one run:

```bash
foldr ~/Downloads --ignore "*.log" "temp/" "DO_NOT_MOVE*"
```

### Pattern syntax

```
*.py           match all .py files
*.log          match all .log files
tmp/           match a directory named "tmp"
build/         match a directory named "build"
secret.txt     exact filename match
*_backup.*     wildcard on both sides
```

### Disabling ignores

```bash
foldr ~/Downloads --no-ignore          # disable ALL rules (built-in exceptions still apply)
foldr ~/Downloads --show-ignored       # see what was skipped and why
```

---

## Custom Categories

FOLDR auto-creates `~/.foldr/config.toml` with commented-out examples on first run.

### Simple examples

**Add file extensions to an existing category:**

```toml
[Documents]
extensions = [".pages", ".numbers", ".key"]
```

**Create a brand new category:**

```toml
[RAW Photos]
folder     = "RAW_Photos"
extensions = [".raw", ".cr2", ".nef", ".arw", ".dng", ".orf"]
```

**Rename the folder a category uses:**

```toml
[Code]
folder = "Source_Code"
```

**Replace all built-in categories (use only yours):**

```toml
[foldr]
merge = false

[My Documents]
folder     = "Documents"
extensions = [".pdf", ".doc", ".docx", ".txt"]

[My Media]
folder     = "Media"
extensions = [".jpg", ".png", ".mp4", ".mp3"]
```

### Edit your config

```bash
foldr config --edit       # opens in your default editor
```

Or just open `~/.foldr/config.toml` in any text editor.

### Test your config

```bash
foldr ~/Downloads --preview --config ~/.foldr/config.toml
```

---

## Watch Mode

Watch mode runs FOLDR permanently in the background. Drop a file into the watched directory — it gets organized automatically within 1 second, no prompts.

### Start watching

```bash
foldr watch ~/Downloads
```

FOLDR spawns a background process, registers its PID, and returns you to the shell immediately. The watcher keeps running even after you close the terminal.

### Watch subdirectories too

```bash
foldr watch ~/Downloads --recursive
```

Files dropped anywhere inside `~/Downloads` (including subdirectories) will be organized.

### Watch runs forever — even after reboot

```bash
foldr watch ~/Downloads --startup
```

This registers the watcher with your OS so it starts automatically on login:
- **Windows**: adds a registry entry under `HKCU\...\Run`
- **macOS**: creates a LaunchAgent plist in `~/Library/LaunchAgents/`
- **Linux**: creates a systemd user service in `~/.config/systemd/user/`

### Check active watchers

```bash
foldr watches
```

Shows: directory, start time, mode (live/preview), whether recursive, startup registration, files organized, PID.

### Stop watching

```bash
foldr unwatch ~/Downloads       # stop specific watcher
foldr unwatch                   # pick from list interactively
```

### Watch logs

Every file move is logged to: `~/.foldr/watch_logs/<dirname>.log`

View the log:
```bash
cat ~/.foldr/watch_logs/Downloads.log    # Linux / macOS
type %USERPROFILE%\.foldr\watch_logs\Downloads.log    # Windows
```

### Is watch mode safe?

Yes. It uses the OS-native file event API (no polling, no CPU spinning):
- **Linux**: inotify — 0% CPU when idle
- **macOS**: kqueue / FSEvents — 0% CPU when idle
- **Windows**: ReadDirectoryChangesW — 0% CPU when idle

Memory use: ~15–20 MB per watched directory.

### What watch mode will NOT touch

- Files with in-progress download extensions: `.crdownload` `.part` `.tmp` `.!ut` `.aria2`
- Files already inside category subfolders
- Files matching your ignore rules

---

## History & Undo

Every `foldr` operation that moves files is saved as a JSON entry in `~/.foldr/history/`.

### View history

```bash
foldr history           # last 50 operations
foldr history --all     # everything
```

### Undo

```bash
foldr undo                    # undo the most recent operation
foldr undo --id a1b2c3        # undo a specific operation (get ID from 'foldr history')
foldr undo --preview          # see what would be restored without actually restoring
```

### How undo works (git revert, not git reset)

Each file is tracked individually. Undoing operation #1 does not require undoing operation #2 first. They are independent.

If a file was moved again after the operation you're undoing, FOLDR skips that file and tells you — it never blindly overwrites a later operation's result.

### What cannot be undone

`foldr --dedup` permanently deletes files. FOLDR records what was deleted in history so you can see what happened, but the files are gone. **Always `--preview` before deduping.**

---

## Dedup

Finds files with identical content (by SHA-256 hash) and removes duplicates.

```bash
# Always preview first — dedup is PERMANENT
foldr ~/Downloads --dedup keep-newest --preview

# Then execute
foldr ~/Downloads --dedup keep-newest
```

**Strategies:**
- `keep-newest` — keep the most recently modified file, delete older ones
- `keep-largest` — keep the biggest file (safest: maximises data if one copy is corrupted)
- `keep-oldest` — keep the original; delete newer copies

---

## Per-OS File Locations

### Linux

| File | Path |
|------|------|
| Config directory | `~/.foldr/` |
| Category config | `~/.foldr/config.toml` |
| Global ignore | `~/.foldr/.foldrignore` |
| History | `~/.foldr/history/` |
| Watch logs | `~/.foldr/watch_logs/` |
| Active watchers | `~/.foldr/watches.json` |
| Startup service | `~/.config/systemd/user/foldr-watch-<name>.service` |

### macOS

| File | Path |
|------|------|
| Config directory | `~/.foldr/` |
| Category config | `~/.foldr/config.toml` |
| Global ignore | `~/.foldr/.foldrignore` |
| History | `~/.foldr/history/` |
| Watch logs | `~/.foldr/watch_logs/` |
| Active watchers | `~/.foldr/watches.json` |
| Startup agent | `~/Library/LaunchAgents/com.foldr-watch-<name>.plist` |

### Windows

| File | Path |
|------|------|
| Config directory | `C:\Users\<you>\.foldr\` |
| Category config | `C:\Users\<you>\.foldr\config.toml` |
| Global ignore | `C:\Users\<you>\.foldr\.foldrignore` |
| History | `C:\Users\<you>\.foldr\history\` |
| Watch logs | `C:\Users\<you>\.foldr\watch_logs\` |
| Active watchers | `C:\Users\<you>\.foldr\watches.json` |
| Startup entry | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\foldr-watch-<name>` |

---

## Config File Locations

### `config.toml` — category configuration

FOLDR auto-creates this on first run with commented-out examples.

| OS | Path |
|----|------|
| All | `~/.foldr/config.toml` |

Edit with: `foldr config --edit`

### `.foldrignore` — global ignore rules

Create this file manually to permanently skip file types everywhere.

| OS | Path |
|----|------|
| All | `~/.foldr/.foldrignore` |

---

## Windows-Specific Notes

### Paths with spaces

Always wrap Windows paths in quotes:

```powershell
foldr "D:\My Downloads"
foldr "D:\My Downloads" --preview
foldr watch "D:\My Documents"
```

### Colours in the terminal

FOLDR automatically enables ANSI colour support in:
- **Windows Terminal** — full colour, works perfectly
- **PowerShell** — full colour on Windows 10+
- **cmd.exe** — full colour on Windows 10 build 14931+
- **Older Windows** — graceful plain-text fallback

### Watch mode and console windows

When you run `foldr watch`, FOLDR uses `pythonw.exe` (the windowless Python interpreter) to spawn the background daemon so no console window appears.

### Startup on login

```powershell
foldr watch "D:\Downloads" --startup
```

This adds a registry entry:  
`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`

To remove it:
```powershell
foldr unwatch "D:\Downloads"
```

---

## macOS-Specific Notes

### Installation

```bash
pip install foldr
# For --smart mode:
brew install libmagic
pip install "foldr[all]"
```

### Startup on login

```bash
foldr watch ~/Downloads --startup
```

Creates a LaunchAgent plist: `~/Library/LaunchAgents/com.foldr-watch-downloads.plist`

To remove: `foldr unwatch ~/Downloads`

### Spaces in paths

macOS paths with spaces work fine in Terminal:

```bash
foldr ~/Desktop/My\ Downloads
# or:
foldr "~/Desktop/My Downloads"
```

---

## Linux-Specific Notes

### Installation

```bash
pip install foldr
# For --smart mode:
sudo apt install libmagic1      # Debian/Ubuntu
sudo dnf install file-libs      # Fedora/RHEL
sudo pacman -S file             # Arch
pip install "foldr[all]"
```

### Startup with systemd (recommended)

```bash
foldr watch ~/Downloads --startup
```

Creates: `~/.config/systemd/user/foldr-watch-downloads.service`

Manage it:
```bash
systemctl --user status foldr-watch-downloads
systemctl --user stop foldr-watch-downloads
systemctl --user disable foldr-watch-downloads
```

### Config file in XDG locations

FOLDR primarily uses `~/.foldr/config.toml`. It also checks `~/.config/foldr/config.toml` as a fallback for XDG-compliant setups.

---

## Default Categories

| Category | Folder | Common Extensions |
|----------|--------|-------------------|
| Documents | Documents/ | .pdf .doc .docx .odt .rtf .tex .md .pages |
| Images | Images/ | .png .jpg .jpeg .gif .bmp .tiff .webp .heic .raw |
| Videos | Videos/ | .mp4 .mkv .mov .avi .wmv .flv .webm |
| Audio | Audio/ | .mp3 .wav .aac .flac .ogg .m4a .wma |
| Archives | Archives/ | .zip .rar .7z .tar .gz .bz2 .xz |
| Code | Code/ | .py .js .ts .html .css .java .cpp .c .rs .go |
| Scripts | Scripts/ | .sh .bash .zsh .fish .ps1 .bat .cmd |
| Spreadsheets | Spreadsheets/ | .xlsx .xls .csv .ods |
| Presentations | Presentations/ | .pptx .ppt .odp |
| Databases | Databases/ | .db .sqlite .sqlite3 |
| Executables | Executables/ | .exe .msi .deb .rpm .apk .dmg |
| Fonts | Fonts/ | .ttf .otf .woff .woff2 |
| Ebooks | Ebooks/ | .epub .mobi .azw |
| Text & Data | Text_Data/ | .txt .json .xml .yaml .toml .log |
| Notebooks | Notebooks/ | .ipynb |
| Machine_Learning | Machine_Learning/ | .pkl .h5 .onnx .pt .pth |

Files with unrecognised extensions are **never moved** — they stay in place.

---

## Troubleshooting

**"Not a valid directory" / path error on Windows**  
Wrap the path in quotes: `foldr "D:\My Downloads"`

**config.toml error on startup**  
Open `~/.foldr/config.toml` and check for TOML syntax errors. The error message tells you the exact line. Or delete the file and let FOLDR regenerate it:

```bash
del %USERPROFILE%\.foldr\config.toml   # Windows
rm ~/.foldr/config.toml                 # Linux / macOS
foldr                                   # re-generates automatically
```

**Watch mode not picking up new files**  
Check the log: `~/.foldr/watch_logs/<dirname>.log`  
Check the watcher is alive: `foldr watches`

**`--dedup` didn't delete anything**  
Check you used `--preview` — in preview mode nothing is deleted. Run without `--preview` to execute.

**`foldr undo` says "already restored"**  
The file was moved again after the operation you're undoing. Check `foldr history` to find the more recent operation and undo that one instead.