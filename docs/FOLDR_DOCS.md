# FOLDR v4 — Complete Documentation

> **Smart, predictable CLI file organizer with a world-class TUI**  
> Zero config needed. Works on Linux, macOS, and Windows.

---

## Table of Contents

1. [Architecture Decision](#architecture-decision)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Commands & Flags](#commands--flags)
5. [Interactive TUI Guide](#interactive-tui-guide)
6. [Configuration](#configuration)
7. [Ignore Rules (.foldrignore)](#ignore-rules-foldrignore)
8. [History & Undo](#history--undo)
9. [Deduplication](#deduplication)
10. [Watch Mode](#watch-mode)
11. [Recursive Mode](#recursive-mode)
12. [All Examples](#all-examples)
13. [Category Reference](#category-reference)
14. [Exit Codes](#exit-codes)
15. [Architecture Overview](#architecture-overview)

---

## Architecture Decision

### TUI or CLI — which did we choose?

**Both, with the TUI as the primary interface.**

FOLDR v4 uses a **dual-mode design**:

| Mode | When | What you get |
|------|------|-------------|
| **TUI** (default) | Any real terminal (TTY) | Animated splash, full-screen preview, scrollable move list, approval dialog, live progress, history browser |
| **Plain** (fallback) | Piped/CI/`--no-interactive` | Coloured ANSI output, progress bar, tabular preview, `y/n` prompts |

**Why not TUI-only?**  
FOLDR needs to work in CI pipelines, Docker, cron jobs, and shell scripts where there is no interactive terminal. The plain mode (`--no-interactive` or non-TTY) is a first-class citizen, not an afterthought.

**Why not CLI-only?**  
A file organizer that moves potentially hundreds of files deserves a proper approval UX. The TUI shows you *exactly* what will happen — colour-coded by category, scrollable, with an explicit two-step confirmation — before a single file moves.

**Why not Textual/urwid/blessed?**  
Zero extra dependencies. The TUI is built on Python's built-in `curses`-style primitives (raw terminal I/O + ANSI escape codes), giving us:
- **No flicker** — double-buffered renderer diffs only changed rows
- **No external runtime** — works anywhere Python runs
- **Full portability** — tested on xterm, iTerm2, Windows Terminal, tmux

---

## Installation

```bash
pip install foldr
```

**With TOML config support** (Python ≤ 3.10):
```bash
pip install "foldr[toml]"
```

**With MIME/smart detection:**
```bash
pip install "foldr[magic]"
```

---

## Quick Start

```bash
# Organize current directory (prompts for confirmation)
foldr

# Organize a specific directory
foldr ~/Downloads

# Preview only — nothing moves
foldr ~/Downloads --dry-run

# Recursive
foldr ~/Downloads --recursive

# Watch mode — organizes new files as they arrive
foldr watch ~/Downloads
```

On a real terminal, FOLDR shows a full-screen TUI preview after scanning.  
On a pipe or CI, it falls back to a clean plain-text table.

---

## Commands & Flags

### `foldr [path]` — Organize

```
foldr [PATH] [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `PATH` | `cwd` | Directory to organize |
| `--dry-run` | off | Scan and preview; nothing moves |
| `--recursive` | off | Descend into subdirectories |
| `--max-depth N` | unlimited | Max recursion depth (requires `--recursive`) |
| `--follow-symlinks` | off | Follow symlinked directories |
| `--smart` | off | MIME detection (catches spoofed extensions) |
| `--ignore PAT...` | none | Extra ignore patterns, e.g. `'*.log' 'tmp/'` |
| `--config FILE` | auto | Path to custom TOML config |
| `--verbose` | off | Print each file move |
| `--quiet` | off | Suppress all non-error output |
| `--no-interactive` | off | Disable TUI; use plain text + y/n prompts |
| `--deduplicate` | none | Find + remove duplicates (see below) |

---

### `foldr watch [path]` — Live Watch Mode

Monitors a directory and organizes files automatically as they arrive.

```bash
foldr watch ~/Downloads
foldr watch ~/Downloads --dry-run
foldr watch ~/Downloads --ignore '*.tmp'
```

- Uses OS-native filesystem events (via `watchdog`)
- Skips in-progress files: `.crdownload`, `.part`, `.tmp`, `.download`, `.partial`
- Waits 300ms after creation before processing (handles partial writes)
- Press **Ctrl+C** to stop

---

### `foldr undo [--id ID] [--dry-run]` — Undo Last Operation

Restores files moved in the most recent (or specified) operation.

```bash
# Undo the last operation
foldr undo

# Preview what undo would do (nothing restored)
foldr undo --dry-run

# Undo a specific operation by ID
foldr undo --id a1b2c3

# Undo a specific operation, preview first
foldr undo --id a1b2c3 --dry-run
```

- History lives in `~/.foldr/history/`
- Each operation creates a JSON log named `2026-03-07_15-20-33_a1b2c3.json`
- On TTY: shows a TUI confirmation dialog before restoring
- Files that have moved again get a `_restored(N)` suffix to avoid overwriting

---

### `foldr history [--all]` — Browse History

```bash
# Show last 50 operations (TUI browser on TTY)
foldr history

# Show all history
foldr history --all

# Pipe-friendly plain text
foldr history --no-interactive
```

In TUI mode, the History screen lets you:
- Browse operations with **↑↓**
- View detail (which files moved where) with **Enter/D**
- Trigger undo directly with **U**

---

### `foldr [path] --deduplicate` — Deduplication

```bash
# Keep newest copy of each duplicate
foldr ~/Downloads --deduplicate keep-newest

# Keep oldest (original provenance)
foldr ~/Downloads --deduplicate keep-oldest

# Keep largest (safest for partially-written files)
foldr ~/Downloads --deduplicate keep-largest

# Preview duplicates, don't delete
foldr ~/Downloads --deduplicate keep-newest --dry-run

# Combine with recursive
foldr ~/Downloads --deduplicate keep-newest --recursive
```

**Algorithm:**
1. Group files by size (fast pre-filter)
2. SHA-256 hash same-size groups
3. Report groups with 2+ identical hashes
4. Show preview table, then confirmation before any deletion

> ⚠️ Deduplication bypasses `foldr undo` — deleted files are gone.  
> Use `--dry-run` first.

---

## Interactive TUI Guide

When running on a real terminal, FOLDR launches a full-screen TUI.

### Splash screen
A 0.7-second animated splash plays on startup. Skip it with `--quiet`.

### Preview Screen layout

```
╔══ Header bar ════════════════════════════════════════════════════════════╗
║  ◈ FOLDR  Interactive Preview          [ PREVIEW — APPROVAL REQUIRED ]  ║
║    📁 /home/user/Downloads                                                ║
╠══ Move list (scrollable) ════════════════════════════════════════════════╣
║  ▶ report.pdf                    →  Documents/    [Documents]           ║
║    photo_vacation.jpg            →  Images/       [Images]              ║
║    my_script.py                  →  Code/         [Code]                ║
║    … (scroll for more)                                                   ║
╠══ Category breakdown ════════════════════════════════════════════════════╣
║  📄 Documents      ████████░░░░░░░░░░░░    8   44.4%                   ║
║  🖼  Images         ████░░░░░░░░░░░░░░░░    4   22.2%                   ║
╠══ Footer ════════════════════════════════════════════════════════════════╣
║  Y EXECUTE   N/Esc CANCEL   ↑↓ scroll   PgUp/Dn fast   ? help          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### Keyboard map

| Key | Action |
|-----|--------|
| `↑` / `k` | Scroll up |
| `↓` / `j` | Scroll down |
| `PgUp` | Page up |
| `PgDn` | Page down |
| `Home` | Jump to top |
| `End` | Jump to bottom |
| `Y` | Open confirmation dialog |
| `N` / `Esc` / `Q` | Cancel — no files moved |
| `?` | Show help overlay |

### Confirmation dialog

When you press **Y**, a modal dialog appears:

```
╔══ ⚡ Execute File Moves ══════════════╗
║                                      ║
║   This will move 18 files            ║
║   from  Downloads/                   ║
║   into  5 category folders.          ║
║                                      ║
║   This operation can be undone with: ║
║     foldr undo                       ║
║                                      ║
║  ── ──────────────────────────── ──  ║
║    ✗ Cancel         ✓ Execute        ║
╚══════════════════════════════════════╝
```

Use `←` `→` to navigate buttons, `Enter` to confirm.  
**Safe default is always "Cancel".**

---

## Configuration

### Auto-detected user config

FOLDR automatically loads:
- **Linux/macOS:** `~/.config/foldr/config.toml`
- **Windows:** `%USERPROFILE%\.foldr\config.toml`

### Custom config via flag

```bash
foldr ~/Downloads --config my_rules.toml
```

### Config file format

```toml
# Optional: control merge behaviour
[foldr]
merge = true   # true = extend built-in categories; false = replace entirely

# Add or extend a built-in category
[Images]
extensions = [".png", ".jpg", ".jpeg", ".webp", ".heic", ".raw"]
folder = "Images"

# Add a brand-new category
[DesignFiles]
extensions = [".sketch", ".fig", ".xd", ".psd", ".ai"]
folder = "Design"

[WorkDocuments]
extensions = [".pdf", ".docx", ".pages"]
folder = "Work_Docs"
```

**Merge rules:**
- `merge = true` (default): your categories are added to / override built-ins
- `merge = false`: only your categories are used (replaces everything)

---

## Ignore Rules (.foldrignore)

Create a `.foldrignore` file in the directory you're organizing:

```gitignore
# Comments are supported

# Skip specific files
secrets.env
*.key

# Skip all .log files
*.log

# Skip directories (trailing slash)
node_modules/
.git/
__pycache__/
tmp/
build/

# Skip by pattern
draft_*
~*
```

### CLI ignore (one-off)

```bash
foldr ~/Downloads --ignore '*.log' '*.tmp' 'node_modules/'
```

**Always-ignored** (hardcoded, cannot be overridden):
- Dirs: `.git`, `.svn`, `.hg`, `__pycache__`, `node_modules`, `.venv`, `venv`
- Files: `.DS_Store`, `Thumbs.db`, `desktop.ini`

---

## History & Undo

Every successful `foldr` run writes a JSON log to `~/.foldr/history/`.

### Log filename format
```
2026-03-07_15-20-33_a1b2c3.json
```

### Log schema
```json
{
  "id": "a1b2c3",
  "timestamp": "2026-03-07T15:20:33Z",
  "base": "/home/user/Downloads",
  "total_files": 18,
  "records": [
    {
      "op_id": "uuid4",
      "source": "/home/user/Downloads/report.pdf",
      "destination": "/home/user/Downloads/Documents/report.pdf",
      "filename": "report.pdf",
      "category": "Documents",
      "timestamp": "..."
    }
  ]
}
```

### Undo behaviour
- Reverses records in reverse order (most recent move first)
- If the destination file has moved again, the restore gets a `_restored(N)` suffix
- After successful undo, the log file is deleted
- Dry-run undo doesn't delete the log

---

## Deduplication

### How it works

```
1. Collect all files under target (optionally recursive)
2. Group by file size  →  quick pre-filter (different sizes ≠ duplicate)
3. SHA-256 hash files in same-size groups
4. Files sharing a hash are duplicates
5. Apply strategy to decide which to KEEP
6. Preview table → confirmation → delete
```

### Strategies

| Strategy | Keeps | Use when |
|----------|-------|----------|
| `keep-newest` | Most recently modified | You want the latest version |
| `keep-oldest` | Oldest modified | You want the original |
| `keep-largest` | Largest file size | Files are identical — largest = safest |

---

## Watch Mode

```bash
foldr watch ~/Downloads
```

Watch mode uses OS-native filesystem events:
- **Linux:** inotify
- **macOS:** FSEvents
- **Windows:** ReadDirectoryChangesW

### What gets skipped automatically
Files with these extensions are ignored until stable:
`.crdownload`, `.part`, `.tmp`, `.download`, `.partial`

### Combine with other flags
```bash
# Watch with dry-run (see what would be organized, nothing moves)
foldr watch ~/Desktop --dry-run

# Watch with custom ignore
foldr watch ~/Downloads --ignore '*.iso' 'Torrents/'

# Watch with custom config
foldr watch ~/Downloads --config ~/my_foldr.toml
```

---

## Recursive Mode

```bash
# Recurse all subdirectories
foldr ~/Projects --recursive

# Limit depth to 2 levels
foldr ~/Projects --recursive --max-depth 2

# Follow symlinks too
foldr ~/Projects --recursive --follow-symlinks
```

**Key design rule:** All files from subdirectories are moved to the *root-level* category folders. FOLDR never creates `Code/Code/Code/…` nesting.

```
Before:                    After:
~/Downloads/               ~/Downloads/
├── notes.txt              ├── Documents/
├── work/                  │   └── notes.txt
│   ├── report.pdf         │   └── report.pdf
│   └── budget.xlsx        ├── Spreadsheets/
└── code/                  │   └── budget.xlsx
    └── app.py             └── Code/
                               └── app.py
```

---

## All Examples

```bash
# ── Organize ──────────────────────────────────────────────────────
foldr                                      # Organize cwd (prompts)
foldr ~/Downloads                          # Organize Downloads
foldr ~/Downloads --dry-run                # Preview only
foldr ~/Downloads --quiet                  # Silent output
foldr ~/Downloads --verbose                # Print every move
foldr ~/Downloads --no-interactive         # Plain text, no TUI

# ── Recursive ─────────────────────────────────────────────────────
foldr ~/Projects --recursive
foldr ~/Projects --recursive --max-depth 3
foldr ~/Projects --recursive --follow-symlinks

# ── Ignore ────────────────────────────────────────────────────────
foldr ~/Downloads --ignore '*.log' '*.tmp'
foldr ~/Downloads --ignore 'node_modules/' 'build/'
# Also: create .foldrignore in the target directory

# ── Custom config ─────────────────────────────────────────────────
foldr ~/Downloads --config ~/.config/foldr/config.toml
foldr ~/Downloads --config ./my_rules.toml

# ── Deduplication ─────────────────────────────────────────────────
foldr ~/Downloads --deduplicate keep-newest
foldr ~/Downloads --deduplicate keep-oldest  --dry-run
foldr ~/Downloads --deduplicate keep-largest --recursive

# ── Watch ─────────────────────────────────────────────────────────
foldr watch ~/Downloads
foldr watch ~/Desktop --dry-run
foldr watch ~/Downloads --ignore '*.torrent'
foldr watch ~/Downloads --config ~/my_rules.toml

# ── Undo ──────────────────────────────────────────────────────────
foldr undo                                 # Undo last operation
foldr undo --dry-run                       # Preview undo
foldr undo --id a1b2c3                     # Undo specific operation

# ── History ───────────────────────────────────────────────────────
foldr history                              # TUI browser (on TTY)
foldr history --all                        # Show all (not just 50)
foldr history --no-interactive             # Plain text table

# ── Combine flags ─────────────────────────────────────────────────
foldr ~/Downloads --dry-run --recursive --max-depth 2 --verbose
foldr ~/Downloads --recursive --ignore '*.tmp' --config rules.toml
```

---

## Category Reference

| Category | Folder | Example Extensions |
|----------|--------|--------------------|
| Documents | `Documents/` | `.pdf` `.docx` `.odt` `.rtf` `.pages` |
| Text & Data | `Text_Data/` | `.txt` `.csv` `.json` `.yaml` `.toml` `.log` |
| Images | `Images/` | `.png` `.jpg` `.gif` `.webp` `.heic` `.raw` |
| Vector Graphics | `Vector_Graphics/` | `.svg` `.eps` `.ai` |
| Videos | `Videos/` | `.mp4` `.mkv` `.mov` `.avi` `.webm` |
| Audio | `Audio/` | `.mp3` `.wav` `.flac` `.ogg` `.m4a` |
| Subtitles | `Subtitles/` | `.srt` `.vtt` `.ass` `.sub` |
| Archives | `Archives/` | `.zip` `.rar` `.7z` `.tar.gz` `.tgz` |
| Disk Images | `Disk_Images/` | `.iso` `.img` `.dmg` `.vmdk` |
| Executables | `Executables/` | `.exe` `.msi` `.deb` `.rpm` `.app` |
| Code | `Code/` | `.py` `.js` `.ts` `.go` `.rs` `.cpp` `.java` |
| Scripts | `Scripts/` | `.sh` `.bash` `.ps1` `.fish` `.zsh` |
| Notebooks | `Notebooks/` | `.ipynb` `.rmd` |
| Machine Learning | `Machine_Learning/` | `.h5` `.pt` `.pth` `.onnx` `.pkl` |
| Spreadsheets | `Spreadsheets/` | `.xlsx` `.xls` `.ods` `.csv` |
| Presentations | `Presentations/` | `.pptx` `.ppt` `.key` `.odp` |
| Databases | `Databases/` | `.db` `.sqlite` `.sql` `.mdb` |
| Fonts | `Fonts/` | `.ttf` `.otf` `.woff` `.woff2` |
| 3D Models | `3D_Models/` | `.stl` `.obj` `.fbx` `.blend` `.gltf` |
| CAD | `CAD/` | `.dwg` `.dxf` `.step` `.iges` |
| GIS | `GIS/` | `.shp` `.geojson` `.kml` `.gpx` |
| Ebooks | `Ebooks/` | `.epub` `.mobi` `.azw3` `.fb2` |
| Certificates | `Certificates/` | `.crt` `.pem` `.key` `.p12` |
| Logs | `Logs/` | `.log` `.trace` `.out` `.err` |
| Misc | `Misc/` | `.part` `.crdownload` `.bak` `.tmp` |

Custom categories can be added via [config file](#configuration).

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (or user cancelled cleanly) |
| `1` | Fatal error (bad path, config error, etc.) |

---

## Architecture Overview

```
foldr/
├── cli.py          ← Entry point, subcommand routing, orchestration
├── tui.py          ← Full-screen TUI screens (PreviewScreen, ExecutionScreen,
│                      HistoryScreen, WatchScreen, splash)
├── screen.py       ← Double-buffered flicker-free terminal renderer
├── widgets.py      ← Reusable TUI widgets (boxes, bars, dialogs, lists)
├── keys.py         ← Raw keypress reader (no curses required)
├── ansi.py         ← ANSI escape constants and primitives
├── output.py       ← Plain-text ANSI output for non-TTY/piped contexts
├── organizer.py    ← Core file-move engine (pure, no I/O side effects)
├── models.py       ← All dataclasses (single source of truth)
├── config.py       ← Default CATEGORIES_TEMPLATE
├── config_loader.py← TOML config loading + merge logic
├── dedup.py        ← SHA-256 duplicate detection + strategy resolution
├── empty_dirs.py   ← Empty directory scanner + remover
├── history.py      ← JSON operation log + undo engine
├── ignore.py       ← .foldrignore parsing + pattern matching
├── logger.py       ← Structured operation JSON logger
├── mime_detect.py  ← MIME type detection (--smart mode)
└── watch.py        ← watchdog integration + live TUI bridge
```

### TUI rendering pipeline

```
User action (keypress)
    ↓
Event loop (tui.py)
    ↓
Widget draw calls → Screen.put(row, col, text)
    ↓
Screen.flush() → diff back/front buffer
    ↓
Only changed rows written to stdout
    ↓
Zero flicker ✓
```

---

## Ratatui vs our approach

You mentioned Ratatui — that's a Rust TUI library. FOLDR is Python, so the equivalent would be **Textual** (by the makers of Rich).

Textual is excellent, but requires a ~5MB runtime install and uses an async event model that adds significant complexity for a tool this focused.

Our approach (hand-rolled double-buffer + raw ANSI) gives us:
- **Identical visual quality** to Textual for our use case
- **Zero extra dependencies** (just stdlib + watchdog)
- **Faster startup** (no async framework to spin up)
- **Full portability** (works in any terminal that supports ANSI)
- **No version conflicts** in user environments

The trade-off: more code to maintain. For FOLDR's scope, that's the right call.
