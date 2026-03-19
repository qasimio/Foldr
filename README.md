<div align="center">

# FOLDR

[![PyPI Version](https://img.shields.io/pypi/v/foldr?cacheSeconds=300)](https://pypi.org/project/foldr/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/foldr?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLUE&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/foldr)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)](#)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/qasimio/Foldr)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-pink?logo=github)](https://github.com/sponsors/qasimio)

**Smart, safe, cross-platform CLI file organizer.**

FOLDR cleans messy directories by sorting files into category folders — instantly, predictably, and safely. Preview every action before anything moves. Undo anything. Watch a folder and keep it tidy automatically.

[Installation](#installation) · [Quick Start](#quick-start) · [All Commands](#all-commands) · [Watch Mode](#watch-mode) · [Undo & History](#undo--history) · [Configuration](#configuration)

</div>

---

## Installation

```bash
pip install foldr
```

Requires Python 3.10+. Works on **Windows**, **Linux**, **macOS**

---

## Quick Start

```bash
# Preview what would happen (nothing moves)
foldr ~/Downloads --preview

# Organize (shows preview, asks to confirm)
foldr ~/Downloads

# Undo the last operation
foldr undo

# Watch a folder — organize now and keep watching
foldr watch ~/Downloads
```

> **Paths with spaces** must be quoted:
> ```bash
> foldr "D:\My Downloads" --preview
> ```

---

## All Commands

### Organize

```bash
foldr <path>                          # organize (preview → confirm → move)
foldr <path> --preview                # dry-run: show plan, nothing moves
foldr <path> --recursive              # also organize subdirectories
foldr <path> --recursive --depth 2    # limit to 2 levels deep
foldr <path> --ignore "*.log" "tmp/"  # skip patterns this run
foldr <path> --no-ignore              # disable all ignore rules
foldr <path> --show-ignored           # list skipped files
foldr <path> --verbose                # print every file moved
foldr <path> --quiet                  # no output (for scripts / cron)
foldr <path> --config myconfig.toml   # use a custom category config
```

### Duplicate removal

```bash
# ⚠ IRREVERSIBLE — always preview first
foldr <path> --dedup keep-newest --preview
foldr <path> --dedup keep-newest      # delete older copies
foldr <path> --dedup keep-largest     # delete smaller copies
foldr <path> --dedup keep-oldest      # delete newer copies
```

### Watch mode

```bash
foldr watch <path>                    # organize now + keep watching
foldr watch <path> --recursive        # watch subdirectories too
foldr watch <path> --preview          # watch mode, log only (no moves)
foldr watches                         # list active watchers
foldr unwatch <path>                  # stop a specific watcher
foldr unwatch                         # interactive picker
```

### Undo & History

```bash
foldr undo                            # undo the last operation
foldr undo --id a1b2c3                # undo a specific operation by ID
foldr undo --preview                  # show what would be restored
foldr history                         # list last 50 operations
foldr history --all                   # list all operations ever
```

### Config

```bash
foldr config                          # show config file locations
foldr config --edit                   # open config.toml in your editor
foldr config --edit --ignore-file     # open .foldrignore in your editor
```

---

## Watch Mode

Watch mode has two jobs: **organize what's already there**, then **keep watching forever**.

```bash
foldr watch ~/Downloads
```

When you run this:
1. FOLDR organizes all existing files in `~/Downloads` immediately (same as running `foldr ~/Downloads`).
2. FOLDR then watches the folder in the background. Any file you drop, copy, or move into it gets organized automatically — within about one second.
3. If you move an already-organized file back to the root, it gets re-organized again. No stale state.

The watcher runs until your machine shuts down or you stop it with `foldr unwatch`.

**See all active watchers:**
```bash
foldr watches
```

**Stop watching:**
```bash
foldr unwatch ~/Downloads
```

**Watch logs** (for debugging) live at:
```
~/.foldr/watch_logs/<dirname>.log
```

---

## How It Works

Files are classified by extension and moved into category folders at the root of the target directory. Existing folders are never touched. Filename conflicts are resolved automatically by appending `_(1)`, `_(2)`, etc.

### Default categories

| Category | Folder | Common extensions |
|----------|--------|-------------------|
| Documents | `Documents/` | `.pdf` `.doc` `.docx` `.odt` `.md` `.tex` |
| Images | `Images/` | `.jpg` `.png` `.gif` `.webp` `.heic` `.raw` |
| Videos | `Videos/` | `.mp4` `.mkv` `.mov` `.avi` `.webm` |
| Audio | `Audio/` | `.mp3` `.wav` `.flac` `.aac` `.ogg` |
| Archives | `Archives/` | `.zip` `.rar` `.7z` `.tar` `.gz` |
| Code | `Code/` | `.py` `.js` `.ts` `.html` `.css` `.java` `.cpp` |
| Scripts | `Scripts/` | `.sh` `.bash` `.ps1` `.bat` `.cmd` |
| Spreadsheets | `Spreadsheets/` | `.xlsx` `.xls` `.csv` `.ods` |
| Presentations | `Presentations/` | `.pptx` `.ppt` `.odp` |
| Databases | `Databases/` | `.db` `.sqlite` `.sqlite3` |
| Executables | `Executables/` | `.exe` `.msi` `.deb` `.rpm` `.apk` `.dmg` |
| Fonts | `Fonts/` | `.ttf` `.otf` `.woff` `.woff2` |
| Ebooks | `Ebooks/` | `.epub` `.mobi` `.azw` |
| Notebooks | `Notebooks/` | `.ipynb` |
| Text & Data | `Text_Data/` | `.txt` `.json` `.xml` `.yaml` `.toml` |

Files with unrecognised extensions are left in place — never moved.

---

## Undo & History

Every organize operation is saved to `~/.foldr/history/`. You can undo any operation independently — no need to undo in order.

```bash
foldr history          # see what's available
foldr undo             # undo the most recent
foldr undo --id a1b2   # undo a specific one
```

If a file was moved again after the operation you're undoing, FOLDR skips it and tells you — it never blindly overwrites later changes.

> **Dedup cannot be undone** — `--dedup` permanently deletes files. Always `--preview` first.

---

## Configuration

### Custom categories

FOLDR auto-creates `~/.foldr/config.toml` on first run. Edit it to add extensions or create your own categories:

```toml
[foldr]
merge = true   # true = extend built-ins | false = replace them

[Images]
extensions = [".heic", ".avif", ".raw"]   # adds to built-in Images

[RAW Photos]
folder     = "RAW_Photos"
extensions = [".cr2", ".nef", ".arw", ".dng", ".orf"]

[Design]
folder     = "Design"
extensions = [".fig", ".sketch", ".xd", ".psd", ".ai"]
```

Open in editor:
```bash
foldr config --edit
```

### Ignore rules

Create `~/.foldr/.foldrignore` (global, applies to all runs):

```
# ~/.foldr/.foldrignore
*.tmp
*.bak
desktop.ini
~$*
Thumbs.db
```

Or pass patterns for one run:
```bash
foldr ~/Downloads --ignore "*.log" "tmp/" "DO_NOT_MOVE*"
```

Disable all rules for one run:
```bash
foldr ~/Downloads --no-ignore
```

### File locations

| Platform | Config | History | Watch logs |
|----------|--------|---------|------------|
| Linux / macOS | `~/.foldr/config.toml` | `~/.foldr/history/` | `~/.foldr/watch_logs/` |
| Windows | `%USERPROFILE%\.foldr\config.toml` | `%USERPROFILE%\.foldr\history\` | `%USERPROFILE%\.foldr\watch_logs\` |

---

## Safety

- **Preview by default** — FOLDR shows you what it will do and asks before moving anything.
- **Folders are never touched** — only files are moved; directories stay where they are.
- **Conflict-safe** — if a file with the same name already exists at the destination, FOLDR renames the incoming file (`photo_(1).jpg`, etc.) rather than overwriting.
- **Undo anything** — every operation is reversible via `foldr undo`.
- **Dedup is the only irreversible action** — always use `--preview` before `--dedup`.

---

## Support

If FOLDR saves you time, consider supporting continued development:

❤️ [github.com/sponsors/qasimio](https://github.com/sponsors/qasimio)

---

## Author

**Muhammad Qasim**
GitHub: [github.com/qasimio](https://github.com/qasimio)
LinkedIn: [linkedin.com/in/qasimio](https://www.linkedin.com/in/qasimio/)

---

## License

[MIT](LICENSE)