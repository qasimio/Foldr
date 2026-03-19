# FOLDR 2.1 — User Manual

**GitHub:** https://github.com/qasimio/Foldr  
**Install:** `pip install foldr`

---

## Platform Support

| Platform | TUI | CLI | Watch |
|----------|-----|-----|-------|
| Linux    | yes | yes | yes   |
| macOS    | yes | yes | yes   |
| Windows 10+ (build 14931+) | yes | yes | yes |
| Windows (older) | auto-fallback to CLI | yes | yes |

FOLDR detects its environment. On terminals that can't do TUI, it falls back to plain text automatically — no crashes, no config needed.

---

## Install

```bash
pip install foldr           # basic (works everywhere)
pip install foldr[all]      # with TOML config + smart mode

# --smart mode also needs a system lib:
# macOS:  brew install libmagic
# Linux:  sudo apt install libmagic1
# Windows: pip install python-magic-bin  (includes the DLL)
```

---

## Quick Start

```bash
foldr ~/Downloads              # organize (preview first, confirm to execute)
foldr ~/Downloads --preview    # dry run, nothing moves
foldr undo                     # undo the last operation
foldr history                  # browse all past operations

foldr watch ~/Downloads        # start background auto-organizer
foldr watches                  # see all active watchers + stats
foldr unwatch ~/Downloads      # stop a watcher
```

---

## All Commands

### `foldr [directory]` — Organize files

```bash
foldr ~/Downloads
foldr ~/Downloads --preview              # show moves, nothing changes
foldr ~/Downloads --recursive            # include subfolders
foldr ~/Downloads --recursive --depth 3  # limit depth
foldr ~/Downloads --smart                # detect by content, not just extension
foldr ~/Downloads --dedup keep-newest    # remove duplicates
foldr ~/Downloads --ignore '*.log' 'tmp/'
foldr ~/Downloads --global-ignore        # also use ~/.foldr/.foldrignore
foldr ~/Downloads --config ~/my.toml    # custom categories
foldr ~/Downloads --verbose
foldr ~/Downloads --plain                # CLI output this run (no TUI)
foldr ~/Downloads --quiet                # no output (for scripts)
```

**How confirmation works:**
1. FOLDR scans and shows you every planned move (preview)
2. You press `Y` / `Enter` to open a confirm dialog
3. Default selection is **Cancel** — you must explicitly choose "Move Files"
4. Only then do files actually move

---

### `foldr watch` — Background auto-organizer

```bash
foldr watch ~/Downloads          # start background watcher (no approval per file)
foldr watch ~/Downloads --preview   # log what would move, don't move
foldr watches                    # list all active watches with stats
foldr unwatch ~/Downloads        # stop the watcher for ~/Downloads
foldr unwatch                    # interactive picker (choose which to stop)
```

**How watch mode works:**

`foldr watch` spawns a detached background process that runs forever. You approved organizing that folder when you started it — no further prompts, every new file is handled silently.

- Uses OS-native file events (Linux: inotify, macOS: kqueue, Windows: ReadDirectoryChangesW)
- 500ms debounce prevents processing files mid-download
- In-progress downloads are skipped: `.crdownload .part .tmp .download .partial .!ut .ytdl .aria2`
- Every move is recorded in history (undoable with `foldr undo`)
- Stats accumulate in `~/.foldr/watches.json`
- Logs go to `~/.foldr/watch_logs/<dirname>.log`

**Auto-cleanup:** When you run `foldr watches`, dead processes are automatically removed from the registry.

---

### `foldr undo` — Undo any operation

```bash
foldr undo                   # undo the most recent operation
foldr undo --id a1b2c3       # undo a specific operation by ID
foldr undo --preview         # show what would be restored, nothing moves
```

**Git-style non-sequential undo:** Any operation can be undone independently. Undoing Monday's organize does not affect Tuesday's. Each file is checked individually — if it was moved again since, it's skipped with a warning rather than blindly overwritten.

**Dedup cannot be undone.** Files deleted by `--dedup` are gone. Always `--preview` first.

---

### `foldr history` — Browse all operations

```bash
foldr history          # last 50 operations (TUI browser in TUI mode)
foldr history --all    # everything ever
```

In TUI mode: press `U` on any entry to undo it directly.

Operation types: `-> organize`, `x dedup` (permanent), `<- undo`

---

### `foldr config` — Set preferences

```bash
foldr config                  # show current settings
foldr config --mode tui       # always use TUI (saved)
foldr config --mode cli       # always use plain CLI (saved)
```

On first run FOLDR asks you to choose. Saved to `~/.foldr/prefs.json`.

---

### `foldr --dedup` — Remove duplicate files

```bash
foldr ~/Downloads --dedup keep-newest    # keep most recently modified
foldr ~/Downloads --dedup keep-largest   # keep largest file
foldr ~/Downloads --dedup keep-oldest    # keep oldest (original)
foldr ~/Downloads --dedup keep-newest --preview   # ALWAYS preview first
```

Groups files by SHA-256 hash. Dedup history is recorded but **cannot be reversed**.

---

## Ignore Rules

### `.foldrignore` in the target directory

```
# comment
*.py
*.log
tmp/
build/
.env
secret.txt
*_backup.*
```

First line works correctly even if your editor adds a UTF-8 BOM.

### Global `~/.foldr/.foldrignore`

```bash
foldr ~/Downloads --global-ignore   # apply on top of local .foldrignore
```

### Inline

```bash
foldr ~/Downloads --ignore '*.log' '*.tmp' 'build/'
```

---

## Custom Config (`~/.foldr/config.toml`)

```toml
[foldr]
merge = true    # extend built-ins (false = replace entirely)

[RAW Photos]
extensions = [".raw", ".cr2", ".nef", ".arw", ".dng"]
folder     = "RAW_Photos"

[Documents]
extensions = [".pages", ".numbers", ".key"]   # extend built-in Documents
```

---

## File Layout

```
~/.foldr/
├── prefs.json          mode preference (tui|cli)
├── config.toml         custom categories (optional)
├── .foldrignore        global ignore rules (optional)
├── watches.json        active background watchers (PID, stats)
├── watch_logs/
│   └── Downloads.log   one log file per watched directory
└── history/
    ├── 2026-03-07_15-20-33_a1b2c3.json
    └── archive/        entries moved here after undo
```

---

## TUI Keys

### Preview Screen

| Key | Action |
|-----|--------|
| `Up` / `Down` (or j/k) | Scroll |
| `PgUp` / `PgDn` | Fast scroll |
| `Home` / `End` | First / last file |
| `Enter` / `Y` | Open confirm dialog |
| `N` / `Esc` | Cancel — nothing moves |
| `?` | Keyboard help |

### Confirm Dialog

| Key | Action |
|-----|--------|
| `Left` / `Right` (or Tab) | Switch Cancel <-> Confirm |
| `Enter` | Execute selected button |
| `Y` | Confirm immediately |
| `N` / `Esc` | Cancel immediately |

Default is always **Cancel**.

### History Browser

| Key | Action |
|-----|--------|
| `Up` / `Down` | Navigate |
| `Enter` / `D` | View files in this operation |
| `U` | Undo selected |
| `Q` / `Esc` | Quit |

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
| Text & Data | .txt .json .xml .yaml .toml .log |

Unrecognised extensions are never moved.

---

## Windows

**Colours + TUI:** enabled automatically via `ctypes.windll.kernel32.SetConsoleMode`. Works in Windows Terminal and PowerShell on Win10 build 14931+. Older builds auto-fall back to plain text.

**Paths:** `C:\Users\Name\Downloads` works identically to `~/Downloads` on Linux.

**Watch mode:** Uses `ReadDirectoryChangesW` via watchdog — same API as Windows Explorer, fast and native.

**`--smart` on Windows:** `pip install python-magic-bin` (ships its own DLL, no separate install).

---

## Troubleshooting

**TUI not appearing** — run in Windows Terminal or a real terminal emulator. Pipes disable TUI automatically (correct behaviour for scripts). Force CLI permanently: `foldr config --mode cli`.

**`undo --id abc` not found** — run `foldr history` for valid IDs. Partial match works (4+ chars).

**`.foldrignore` first line not matching** — save as UTF-8 (without BOM) if possible. FOLDR strips BOM automatically in 2.1+.

**`config.toml` not loading** — must be at `~/.foldr/config.toml` (not `~/.config/foldr/`).

**`watchdog not installed`** — `pip install watchdog`.

**Watch mode moving already-organized files** — won't happen. Watch only processes files directly in the root of the watched directory, not files already in category subfolders.
