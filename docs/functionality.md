# FOLDR — Complete Functionality Reference

> Version 4 · Built by Muhammad Qasim (@qasimio)

---

## Installation

```bash
pip install foldr
```

Requires Python 3.9+. Optional extras:

```bash
pip install python-magic   # --smart MIME detection
pip install watchdog       # watch mode (already bundled as dependency)
pip install tomli          # --config TOML support on Python < 3.11
```

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `foldr` | Organize current directory (prompts for confirmation) |
| `foldr <dir>` | Organize a specific directory |
| `foldr <dir> --dry-run` | Preview only — nothing moves |
| `foldr <dir> --interactive` | TUI preview → approve before executing |
| `foldr <dir> --recursive` | Organize all subdirectories too |
| `foldr <dir> --recursive --max-depth 2` | Limit recursion to 2 levels |
| `foldr <dir> --smart` | MIME-type content detection |
| `foldr <dir> --deduplicate` | Find and remove duplicate files |
| `foldr <dir> --ignore "*.log"` | Skip matching files |
| `foldr <dir> --config foldr.toml` | Custom category config |
| `foldr watch <dir>` | Live auto-organizer (runs forever) |
| `foldr undo` | Undo the last operation |
| `foldr undo --id <ID>` | Undo a specific past operation |
| `foldr history` | See recent operations |

---

## 1. Basic Organization

### Organize a directory

```bash
foldr ~/Downloads
```

Files are grouped by extension into category subfolders:
- `Documents/` — `.pdf`, `.docx`, `.tex`, etc.
- `Images/` — `.png`, `.jpg`, `.webp`, etc.
- `Videos/` — `.mp4`, `.mkv`, `.mov`, etc.
- `Audio/` — `.mp3`, `.wav`, `.flac`, etc.
- `Code/` — `.py`, `.js`, `.ts`, `.html`, etc.
- … (30+ categories total — see `config.py` for the full list)

Existing folders in the directory are **never touched or moved**.

### Preview first (dry-run)

```bash
foldr ~/Downloads --dry-run
```

Shows exactly what would happen. Zero files are moved. Safe to run at any time.

### Organize current directory

```bash
cd ~/Downloads
foldr
```

FOLDR detects no path was given, shows the target, and asks for confirmation before proceeding.

### Paths with spaces

Always quote paths that contain spaces:

```bash
foldr "D:\My Downloads"
foldr "/home/user/My Files" --dry-run
```

---

## 2. Recursive Mode

### Organize all nested subdirectories

```bash
foldr ~/Downloads --recursive
```

**Key behavior:** All files — regardless of how deep they are in the tree — move to the **root-level** category folders. Sub-directories do not grow their own `Code/`, `Documents/` etc. trees.

Example:
```
Before:
  Downloads/
    report.pdf
    projects/webapp/index.html
    projects/webapp/style.css

After:
  Downloads/
    Documents/report.pdf
    Code/index.html
    Code/style.css
    projects/webapp/           ← folder left in place
```

### Limit recursion depth

```bash
foldr ~/Downloads --recursive --max-depth 2
```

- `--max-depth 1` — only immediate subdirectories
- `--max-depth 2` — two levels deep
- Omit for unlimited depth

### Follow symbolic links

```bash
foldr ~/Downloads --recursive --follow-symlinks
```

By default, symlinked directories are **skipped** to prevent infinite loops. Enable with this flag. Circular symlinks are still detected and halted automatically.

### Safety confirmation

Running `--recursive` without `--dry-run` always shows a confirmation prompt before any files are moved.

---

## 3. Interactive Mode (TUI Preview)

```bash
foldr ~/Downloads --interactive
```

Shows a full terminal preview before executing:
- Category overview table with file counts and bar chart
- Complete file-by-file listing (first 30 shown)
- Stats: total to move, unmatched, ignored
- `y/n` prompt — nothing moves until you confirm

Combine with any other flags:

```bash
foldr ~/Downloads --interactive --recursive --max-depth 2
foldr ~/Downloads --interactive --config ~/my-categories.toml
```

---

## 4. Ignore Rules

### Using .foldrignore

Create a `.foldrignore` file in the directory you're organizing:

```
# .foldrignore

node_modules/
.env
*.log
*.tmp
*.cache
build/
dist/
```

Rules:
- Lines starting with `#` are comments
- Trailing `/` means directory-only pattern
- `*` is a wildcard (fnmatch syntax)
- Patterns match both the bare name and relative path

FOLDR automatically reads this file — no flag required.

### CLI ignore patterns

```bash
foldr ~/Downloads --ignore "*.log"
foldr ~/Downloads --ignore "*.log" "*.tmp" "node_modules/"
```

Multiple patterns are accepted. They are merged with `.foldrignore` if it exists.

### What gets reported

```bash
foldr ~/Downloads --ignore "*.log" --verbose
```

In verbose mode, ignored files and directories are listed:

```
IGNORED_FILE  report.log
IGNORED_DIR   node_modules
```

---

## 5. Smart MIME Detection

```bash
foldr ~/Downloads --smart
```

In addition to extension matching, FOLDR reads each file's actual content (magic bytes) to verify or override the category.

Example: a file named `invoice.jpg` that is actually a PDF will be moved to `Documents/` instead of `Images/`.

Requires `python-magic` for the most accurate detection:
```bash
pip install python-magic
```

Falls back to stdlib `mimetypes` (extension-based) if not installed.

Verbose output shows overrides:
```bash
foldr ~/Downloads --smart --verbose
# MIME_OVERRIDE invoice.jpg: Images → Documents
```

---

## 6. Duplicate Detection

### Find and remove duplicates

```bash
foldr ~/Downloads --deduplicate
```

Default strategy: keep the **newest** file (by modification time).

### Choose a strategy

```bash
foldr ~/Downloads --deduplicate keep-newest    # default
foldr ~/Downloads --deduplicate keep-oldest
foldr ~/Downloads --deduplicate keep-largest
```

**How it works:**
1. Groups files by size (fast pre-filter)
2. Computes SHA-256 hash for size-collision groups
3. Files with identical hashes are confirmed duplicates
4. The chosen strategy determines which copy to keep
5. FOLDR shows you the plan and asks for confirmation before deleting

### Preview duplicates

```bash
foldr ~/Downloads --deduplicate --dry-run
```

Shows the duplicate groups and what would be deleted — nothing is removed.

### Combine with organize

```bash
foldr ~/Downloads --deduplicate keep-newest --dry-run
```

Deduplication runs before organization. The deduplicate step and organize step each have their own confirmation.

---

## 7. Custom Configuration

### Create a config file

```toml
# foldr.toml

[Datasets]
extensions = [".csv", ".parquet", ".arrow", ".feather"]
folder = "Datasets"

[ML_Models]
extensions = [".pt", ".pth", ".onnx", ".h5", ".pkl"]
folder = "ML_Models"

[Raw_Photos]
extensions = [".cr2", ".nef", ".orf", ".arw", ".dng"]
folder = "Raw_Photos"

[foldr]
merge = true    # true = add to built-ins (default)
                # false = replace built-ins entirely
```

### Use it

```bash
foldr ~/Downloads --config ~/foldr.toml
foldr ~/Downloads --config ./foldr.toml --dry-run
```

### Global user config (auto-loaded)

Place a config file at:

| OS | Path |
|----|------|
| Linux / macOS | `~/.config/foldr/config.toml` |
| Windows | `%USERPROFILE%\.foldr\config.toml` |

FOLDR loads this automatically on every run — no `--config` flag needed.

The `--config` flag overrides the global config.

---

## 8. Watch Mode (Auto-Organizer)

```bash
foldr watch ~/Downloads
```

FOLDR monitors the directory and automatically organizes any new file that appears. Runs continuously until `Ctrl+C`.

### How it works

- Uses OS-native filesystem events (via watchdog)
- Waits 350ms after file creation (for download completion)
- Skips in-progress files (`.crdownload`, `.part`, `.tmp`)
- Skips files already inside FOLDR category folders (no double-moves)
- Prints a timestamped log of every file it processes

### Preview mode

```bash
foldr watch ~/Downloads --dry-run
```

Shows what would happen for each new file without actually moving anything.

### With custom config

```bash
foldr watch ~/Downloads --config ~/foldr.toml
foldr watch ~/Downloads --ignore "*.tmp"
```

### Example output

```
  Watching  /home/UserX/Downloads
  Mode  LIVE

  Press Ctrl+C to stop.

  15:42:03  invoice.pdf  ↓ detected
      → invoice.pdf  →  Documents/

  15:43:17  recording.mp3  ↓ detected
      → recording.mp3  →  Audio/
```

---

## 9. Undo System

### Undo the last operation

```bash
foldr undo
```

Shows the operation details (ID, directory, timestamp, file count), previews the first 10 file restores, then asks for `y/n` confirmation.

Files are restored to their **original locations**. If a file already exists there, it's renamed with a `_restored(N)` suffix.

### Preview undo without moving anything

```bash
foldr undo --dry-run
```

Shows exactly what would be restored. No files are moved.

### Undo a specific past operation

```bash
foldr undo --id a1b2c3
```

The ID is the 6-character code shown in `foldr history`.

### After undo

The history entry is archived (renamed `.undone`) — never deleted. The audit trail is always preserved.

---

## 10. History

### View recent operations

```bash
foldr history
```

Output is styled like `git log --oneline`:

```
 a1b2c3  07 Mar 15:20   21 files  → Documents
 d4e5f6  06 Mar 11:45    8 files  → Downloads
```

Each line shows:
- **ID** — 6-char hex, use with `foldr undo --id`
- **Timestamp** — day, month, time
- **File count**
- **Directory name**

### Show undone operations too

```bash
foldr history --all
```

Undone entries are shown with strikethrough and `(undone)` label.

### History storage

History lives at `~/.foldr/history/`. Each operation creates a JSON file:

```
~/.foldr/history/
  2026-03-07_15-20-33_a1b2c3.json       ← active
  2026-03-06_11-45-01_d4e5f6.undone     ← archived after undo
```

---

## 11. Verbosity Control

### Verbose — see everything

```bash
foldr ~/Downloads --verbose
```

Shows:
- All normal actions
- Files ignored by `.foldrignore` / `--ignore`
- Unmatched files (no category)
- MIME overrides (from `--smart`)

### Quiet — minimal output

```bash
foldr ~/Downloads --quiet
```

Suppresses the action list. Only prints the final one-liner:

```
✓ Moved 21 · Unmatched 2 · 0.14s
```

Useful for scripting or cron jobs.

---

## 12. Structured Operation Logs

Every real (non-dry-run) operation writes two files:

**History log** (`~/.foldr/history/*.json`) — used by `undo` and `history`:
```json
{
  "id": "a1b2c3",
  "timestamp": "2026-03-07T15:20:33Z",
  "base": "/home/UserX/Downloads",
  "total_files": 21,
  "records": [...]
}
```

**Operation log** (`~/.foldr/logs/*.json`) — full observability record:
```json
{
  "operation_id": "a1b2c3",
  "base": "/home/UserX/Downloads",
  "dry_run": false,
  "recursive": true,
  "files_moved": [...],
  "files_ignored": 3,
  "mime_overrides": 1,
  "duration_seconds": 0.143,
  "summary": { "Documents": 16, "Code": 3, "Videos": 1 }
}
```

---

## 13. Flag Reference

```
foldr [path] [options]

Positional:
  path                Directory to organize, or: watch | undo | history

Core:
  --dry-run           Preview only, no files moved
  --interactive, -i   TUI preview → confirm before executing

Recursive Engine:
  --recursive         Descend into subdirectories
  --max-depth N       Limit recursion depth (requires --recursive)
  --follow-symlinks   Follow symlinked directories (default: off)

Ignore Rules:
  --ignore PATTERN    Skip matching files/dirs (repeatable)
                      e.g. --ignore "*.log" "node_modules/"

Configuration:
  --config FILE       Path to foldr.toml

Intelligent Detection:
  --smart             MIME-type content detection (needs python-magic)
  --deduplicate [STRATEGY]
                      Find/remove duplicates
                      Strategies: keep-newest | keep-largest | keep-oldest

Output:
  --verbose, -v       Show every file decision
  --quiet, -q         Suppress action list, final counts only

Undo / History:
  --id ID             Operation ID for: foldr undo --id <ID>
  --all               Include undone ops: foldr history --all
```

---

## 14. Example Workflows

### Daily Downloads cleanup

```bash
# Preview first
foldr ~/Downloads --dry-run

# Run it
foldr ~/Downloads
```

### Deep project folder cleanup

```bash
# Preview recursive cleanup, 3 levels deep
foldr ~/projects/old-repo --recursive --max-depth 3 --dry-run

# Run interactively
foldr ~/projects/old-repo --recursive --max-depth 3 --interactive
```

### Downloads auto-organizer (background)

```bash
# Start the watcher
foldr watch ~/Downloads

# Or as a nohup background process
nohup foldr watch ~/Downloads &
```

### Research data with custom categories

```toml
# ~/research.toml
[Datasets]
extensions = [".csv", ".parquet", ".json", ".jsonl"]

[Models]
extensions = [".pt", ".pth", ".onnx", ".pkl", ".joblib"]

[Papers]
extensions = [".pdf"]
folder = "Papers"

[foldr]
merge = false   # only use these categories
```

```bash
foldr ~/research --config ~/research.toml --recursive --dry-run
```

### Clean up and deduplicate at once

```bash
foldr ~/Downloads --deduplicate keep-newest --recursive --dry-run
# Review output
foldr ~/Downloads --deduplicate keep-newest --recursive
```

### Oops — undo it

```bash
# See what happened
foldr history

# Undo the last one
foldr undo

# Or undo a specific operation
foldr undo --id a1b2c3
```

---

## 15. Safety Guarantees

1. **Existing folders are never moved** — FOLDR only moves files. Directories already in the target are counted as "skipped directories" and left alone.
2. **Recursive mode always asks for confirmation** — unless `--dry-run` or `--interactive`.
3. **No infinite loops** — FOLDR's output folders are tracked and never re-entered during recursive walks.
4. **Symlink protection** — symlinked directories are skipped by default; circular symlinks are detected even when `--follow-symlinks` is used.
5. **Name conflict resolution** — if a destination file already exists, the source is renamed `filename(1).ext`, `filename(2).ext`, etc.
6. **Full undo** — every real run is logged. `foldr undo` restores all files.
7. **Permission errors** — restricted directories are silently skipped, not crashed on.

---

## 16. Built-in Categories

FOLDR ships with 30+ built-in categories. A selection:

| Category | Extensions |
|----------|-----------|
| Documents | `.pdf` `.docx` `.odt` `.tex` `.md` |
| Images | `.png` `.jpg` `.gif` `.webp` `.heic` `.raw` |
| Videos | `.mp4` `.mkv` `.mov` `.avi` `.webm` |
| Audio | `.mp3` `.wav` `.flac` `.aac` `.ogg` |
| Code | `.py` `.js` `.ts` `.go` `.rs` `.cpp` `.java` … |
| Spreadsheets | `.xlsx` `.csv` `.ods` |
| Archives | `.zip` `.tar.gz` `.7z` `.rar` |
| Machine Learning | `.pt` `.onnx` `.h5` `.pkl` `.npz` |
| Ebooks | `.epub` `.mobi` `.azw3` |
| Databases | `.sqlite` `.db` `.sql` |
| Fonts | `.ttf` `.otf` `.woff2` |
| 3D Models | `.stl` `.obj` `.fbx` `.blend` |
| GIS | `.geojson` `.kml` `.shp` |

Full list: see `foldr/config.py` in the package.

---

## 17. Project Layout

```
foldr/
├── __init__.py          public API
├── config.py            built-in category/extension map
├── config_loader.py     TOML config loading + merge
├── organizer.py         core engine (move files, recursive walk)
├── cli.py               all commands + Rich UI
├── watch.py             watch mode (watchdog integration)
├── history.py           operation log + undo
├── logger.py            structured JSON operation logs
├── models.py            shared dataclasses
├── dedup.py             SHA-256 duplicate detection
├── empty_dirs.py        empty directory scanner/remover
├── ignore.py            .foldrignore + --ignore pattern matching
└── mime_detect.py       MIME-type detection (python-magic / mimetypes)
```

---

*FOLDR is MIT licensed. Source: https://github.com/qasimio/Foldr*