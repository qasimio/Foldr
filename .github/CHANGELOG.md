# Changelog

All notable changes to FOLDR are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.1.0] — 2026

### Fixed
- **Linux watch mode** — watch mode now works on Linux. Root cause: `_organize_one`
  imported a private symbol (`_matches_any`) from `organizer.py` at function scope
  without a try/except. On systems where that symbol doesn't exist, the import
  raised `ImportError` which killed the processor thread silently on the first file
  event. The thread died; the observer kept running; nothing moved. Fixed by
  implementing self-contained ignore matching using stdlib `fnmatch`.
- **Processor thread resilience** — `_processor` now wraps every `_organize_one`
  call in try/except with full traceback logging. A single bad file can no longer
  kill the thread.
- **Daemon errors now visible** — background daemon stderr/stdout redirect to the
  watch log file instead of `/dev/null`. Check `~/.foldr/watch_logs/<dir>.log`.
- **PID registered before initial scan** — `foldr watches` now shows entries
  immediately when a daemon starts, even during a slow first organize pass.
- **Files re-organized after being moved back** — removed the `_seen_in_session`
  set that prevented a file from being organized more than once per session.
  Loop prevention is now purely positional: files already inside a FOLDR category
  folder are skipped; files in the root are always eligible.

### Removed
- `--startup` flag and all startup/boot registration code (systemd units,
  LaunchAgent plists, Windows Registry entries). Watch mode runs until the
  machine shuts down; restart it manually with `foldr watch` after reboot.

### Added
- `on_moved` event handler in watch mode — catches files dragged or moved
  into the watched directory from another location.
- User approval prompt before watch mode starts.
- Self-contained `_matches_ignore()` in `watch.py` (stdlib only, no private imports).

---

## [2.0.0] — 2025

### Added
- Background watch mode (`foldr watch`, `foldr unwatch`, `foldr watches`)
- Undo system with JSON history (`foldr undo`, `foldr history`)
- Duplicate removal (`--dedup keep-newest|keep-largest|keep-oldest`)
- Recursive organization (`--recursive`, `--depth N`)
- Custom categories via TOML config (`foldr config --edit`)
- Per-directory and global `.foldrignore` support
- Cross-platform ANSI output (no rich/pyfiglet dependency)
- Empty directory cleanup after organize

### Removed
- `rich` and `pyfiglet` dependencies

---

## [1.0.0] — 2024

### Added
- Initial release
- Organize files by extension into category folders
- Preview mode (`--dry-run`)
- Conflict-safe filename resolution
- Cross-platform support (Windows, macOS, Linux)