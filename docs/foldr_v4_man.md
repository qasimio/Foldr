# FOLDR v4 — User Manual

**GitHub:** https://github.com/qasimio/Foldr  
**Install:** `pip install foldr`

---

## Quick Start

```bash
foldr ~/Downloads              # organize (shows preview first, asks to confirm)
foldr ~/Downloads --preview    # show what would happen — nothing moves
foldr undo                     # undo the last operation
foldr history                  # browse all past operations
```

---

## All Commands

### `foldr [directory]` — Organize files

Scans a directory, groups files by type, then asks for confirmation before moving anything.

```bash
foldr ~/Downloads
foldr ~/Downloads --preview              # dry run — nothing moves
foldr ~/Downloads --recursive            # include files in subfolders
foldr ~/Downloads --recursive --depth 3  # limit subfolder depth
foldr ~/Downloads --follow-links         # follow symbolic links
foldr ~/Downloads --smart                # detect by content, not just extension
foldr ~/Downloads --ignore '*.log' 'tmp/' 'secret.txt'
foldr ~/Downloads --global-ignore        # also use ~/.foldr/.foldrignore
foldr ~/Downloads --config ~/my.toml    # use a custom category config
foldr ~/Downloads --verbose              # print each file that moves
foldr ~/Downloads --quiet                # no output (for scripts)
foldr ~/Downloads --plain                # CLI text output (no TUI) this run
```

**How confirmation works:**
1. FOLDR scans and shows you what will move (preview screen or table)
2. You approve — press `Y` / `Enter` in TUI, or `y` in CLI
3. A confirmation dialog appears (TUI) — default is **Cancel** for safety
4. Only after explicitly choosing "Move Files" do files actually move

**`--preview` flag:**
Shows the preview but never asks for confirmation — just exits. Safe to run anytime.

---

### `foldr watch [directory]` — Auto-organize new files

Watches a directory. Every time a new file appears, FOLDR organizes it automatically.

```bash
foldr watch ~/Downloads
foldr watch ~/Downloads --preview    # show what would happen, don't move
foldr watch ~/Downloads --quiet      # silent mode
```

**What watch mode does:**
- Uses OS-native file events (no polling, instant response)
- Waits 300ms after a file appears (lets downloads finish writing)
- Skips in-progress download files (`.crdownload`, `.part`, `.tmp`, etc.)
- Runs forever until you press **Ctrl+C**
- Each file it moves is saved to history (undoable with `foldr undo`)

**Use case — auto-sort Downloads:**
```bash
# Run in background (or in a tmux/screen session)
foldr watch ~/Downloads
# Now anything downloaded automatically lands in the right folder
```

**`--smart` flag (for both `foldr` and `foldr watch`):**
Without `--smart`: FOLDR looks only at the file extension. `document.pdf` → Documents.
With `--smart`: FOLDR reads the first few bytes of each file to detect its actual type.
This catches files like `photo.png.exe` (a Windows executable renamed to look like an image).
Requires `pip install python-magic` for best results (falls back to stdlib mimetypes).

---

### `foldr undo` — Undo any past operation

```bash
foldr undo                   # undo the most recent operation
foldr undo --id a1b2c3       # undo a specific operation by ID
foldr undo --preview         # show what would be restored, don't move
```

**How undo works:**
Each file move is tracked individually. Undo moves each file from its current location
back to where it came from.

**If a file was moved again after the operation you're undoing:**
FOLDR detects this and skips that file with a warning — it never blindly overwrites
another operation's work. You'll see `skip  filename — not found at Documents/` in the output.

**Non-sequential undo:**
You can undo ANY operation, not just the most recent one. If you organized Downloads
on Monday and Documents on Tuesday, you can undo the Monday operation on Wednesday
without touching Tuesday's work. Each operation is completely independent.

```bash
foldr history                 # find the ID of the operation you want to undo
foldr undo --id a1b2c3        # undo it
```

**Dedup cannot be undone:**
Files deleted by `--dedup` are permanently removed. FOLDR records what was deleted
in history so you can see what happened, but restoration is not possible.
Always use `foldr ~/path --dedup keep-newest --preview` first.

---

### `foldr history` — Browse all past operations

```bash
foldr history                 # show last 50 operations (TUI browser in TUI mode)
foldr history --all           # show everything
```

**TUI History browser keys:**
| Key | Action |
|-----|--------|
| `↑↓` | Navigate entries |
| `Enter` or `D` | View detail (all files in this operation) |
| `U` | Undo the selected operation |
| `Q` / `Esc` | Quit |

**Operation types in history:**
- `↗ organize` — files were moved into category folders
- `✕ dedup` — duplicate files were deleted (cannot undo)
- `↩ undo` — a previous operation was reversed

---

### `foldr config` — Preferences

```bash
foldr config                  # show current preferences
foldr config --mode tui       # switch to TUI mode (saved permanently)
foldr config --mode cli       # switch to CLI mode (saved permanently)
```

**First run:**
On first launch, FOLDR asks you to choose a mode. This is saved to
`~/.foldr/prefs.json` and applied every run. Change it anytime with `foldr config --mode`.

**Override per-run:**
```bash
foldr ~/Downloads --plain     # CLI output just this run (doesn't change saved mode)
```

---

### `foldr --dedup` — Remove duplicate files

```bash
foldr ~/Downloads --dedup keep-newest    # keep the most recently modified copy
foldr ~/Downloads --dedup keep-largest   # keep the largest file
foldr ~/Downloads --dedup keep-oldest    # keep the original (oldest) copy
foldr ~/Downloads --dedup keep-newest --preview   # show what would be deleted
```

**Algorithm:**
1. Groups files by size (fast — different sizes can't be identical)
2. For same-size files, computes SHA-256 hash
3. Files with matching hashes are duplicates

**Strategies:**
- `keep-newest` — good for "I want the most recently edited version"
- `keep-largest` — safe default (maximizes data retention if corruption occurred)
- `keep-oldest` — good for "I want the original, delete the copies"

**Warning:** Dedup is permanent. History records what was deleted, but files cannot
be restored via `foldr undo`. Always preview first:
```bash
foldr ~/Downloads --dedup keep-newest --preview
```

---

## Ignore Rules

### Local `.foldrignore`

Create a `.foldrignore` file in the directory you're organizing:

```
# Skip Python files
*.py

# Skip log files
*.log

# Skip a specific folder
tmp/
build/

# Skip a specific file
.env
secret.txt

# Skip by partial name
*_backup.*
```

This file works exactly like `.gitignore`. Lines starting with `#` are comments.

**Note:** If your editor adds a BOM (byte-order mark) to the file, FOLDR handles it
correctly — the first pattern will still work.

### Global ignore (`~/.foldr/.foldrignore`)

Create `~/.foldr/.foldrignore` for patterns you always want to skip everywhere:

```
# Always skip these everywhere
*.tmp
*.bak
Thumbs.db
.DS_Store
desktop.ini
```

Enable it per-run:
```bash
foldr ~/Downloads --global-ignore
```

### Inline ignore patterns

```bash
foldr ~/Downloads --ignore '*.log' '*.tmp' 'build/'
```

Patterns support wildcards (`*`, `?`). Add `/` suffix to match directories only.

---

## Configuration File

Place `~/.foldr/config.toml` to customize categories:

```toml
[foldr]
merge = true    # true = extend built-in categories, false = replace entirely

# Add a new category
[RAW Photos]
extensions = [".raw", ".cr2", ".nef", ".arw", ".orf", ".dng"]
folder = "RAW_Photos"

# Extend an existing category with more extensions
[Documents]
extensions = [".pages", ".numbers", ".key"]

# Completely custom setup with merge = false
# [foldr]
# merge = false
# [My Projects]
# extensions = [".py", ".js", ".ts", ".rs"]
# folder = "Projects"
```

**Location:** `~/.foldr/config.toml` (same folder as history)  
**Explicit path:** `foldr ~/Downloads --config ~/custom.toml`

---

## File Locations

```
~/.foldr/
├── prefs.json          user preferences (mode: tui|cli)
├── config.toml         custom category config (optional)
├── .foldrignore        global ignore rules (optional)
└── history/
    ├── 2026-03-07_15-20-33_a1b2c3.json   organize operation
    ├── 2026-03-07_16-00-00_d4e5f6.json   dedup operation
    └── archive/
        └── 2026-03-07_14-00-00_*.json    archived (after undo)
```

---

## TUI Keyboard Reference

### Preview Screen

| Key | Action |
|-----|--------|
| `↑` / `k` | Scroll up |
| `↓` / `j` | Scroll down |
| `PgUp` / `PgDn` | Fast scroll |
| `Home` / `End` | Jump to first/last file |
| `Enter` or `Y` | Open confirmation dialog |
| `N` / `Esc` | Cancel — nothing moves |
| `?` | Help overlay |

### Confirmation Dialog

| Key | Action |
|-----|--------|
| `←` / `→` | Switch between Cancel and Confirm |
| `Tab` | Toggle selection |
| `Enter` | Execute selected button |
| `Y` | Confirm immediately |
| `N` / `Esc` | Cancel immediately |

Default is always **Cancel** — you have to explicitly choose to proceed.

---

## Default Categories

| Category | Extensions |
|----------|-----------|
| Documents | .pdf .doc .docx .odt .rtf .tex .pages .md |
| Images | .png .jpg .jpeg .gif .bmp .tiff .webp .heic .raw .cr2 |
| Videos | .mp4 .mkv .mov .avi .wmv .flv .webm .m4v |
| Audio | .mp3 .wav .aac .flac .ogg .m4a .wma |
| Archives | .zip .rar .7z .tar .gz .bz2 .xz |
| Code | .py .js .ts .html .css .java .cpp .c .rs .go |
| Scripts | .sh .bash .zsh .fish .ps1 .bat .cmd |
| Spreadsheets | .xlsx .xls .csv .ods |
| Presentations | .pptx .ppt .odp |
| Databases | .db .sqlite .sqlite3 |
| Executables | .exe .msi .deb .rpm .apk .dmg |
| Fonts | .ttf .otf .woff .woff2 |
| Ebooks | .epub .mobi .azw |
| Text & Data | .txt .json .xml .yaml .toml .log .csv |

Unrecognised extensions are left in place (never moved to a miscellaneous folder).

---

## Install & Dependencies

```bash
pip install foldr

# Optional but recommended
pip install watchdog    # for 'foldr watch' (auto-organize)
pip install tabulate    # for better CLI tables
pip install tomli       # for TOML config on Python < 3.11

# For --smart mode (detect files by content, not just extension)
pip install python-magic
# macOS: brew install libmagic
# Linux: sudo apt install libmagic1
```

---

## Uninstall / Reset

```bash
pip uninstall foldr
rm -rf ~/.foldr/          # delete all history and preferences
```

---

## Troubleshooting

**TUI doesn't appear / shows plain text output**  
The TUI requires a real terminal. It won't appear in:
- Pipes: `foldr ~/Downloads | tee log.txt`
- Non-interactive shells or CI/CD
- Terminals with `TERM=dumb` or `NO_COLOR=1`

Fix: run in a real terminal, or use `foldr config --mode cli` to switch to CLI permanently.

**`foldr undo --id abc` says "not found"**  
Run `foldr history` to see valid IDs. IDs are 8 hex characters.
You only need the first 4-6 characters — partial match works:
```bash
foldr undo --id a1b2      # matches any ID starting with a1b2
```

**`.foldrignore` first pattern not working**  
Your editor may have saved the file with a BOM (byte-order mark). FOLDR v4 strips
this automatically — upgrade to v4 if you're on v3.

**`config.toml` not being loaded**  
Check the path: it should be `~/.foldr/config.toml`.  
Previous versions looked in `~/.config/foldr/config.toml` — v4 checks both.

**`foldr watch` quits when I press a key**  
Known issue in some terminal emulators where mouse scroll events are sent as
key sequences. v4 discards these events instead of quitting.

**`python-magic` not found for `--smart`**  
```bash
pip install python-magic
# macOS also needs: brew install libmagic
# Ubuntu/Debian: sudo apt install libmagic1
```
Without it, FOLDR falls back to the stdlib `mimetypes` module (extension-based,
less accurate but always available).