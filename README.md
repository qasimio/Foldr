# FOLDR

[![PyPI Version](https://img.shields.io/pypi/v/foldr?cacheSeconds=300)](https://pypi.org/project/foldr/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/qasimio/foldr/blob/main/LICENSE)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/foldr?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLUE&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/foldr)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)](#)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-pink?logo=github)](https://github.com/sponsors/qasimio)

### Safe, fast, and predictable CLI file organizer.

**FOLDR** cleans messy directories by organizing files into categorized folders  
without modifying existing folder structures.

Preview everything safely using `--dry-run` before any file is moved.

---

## Quick Example

```bash
foldr ~/Downloads --dry-run
```

---

### Features

- Organizes files by extension into clear categories
- Never modifies or moves existing folders
- Dry-run mode to preview actions safely
- Handles filename conflicts automatically
- Cross-platform (Windows, macOS, Linux)

---

## Support

If **FOLDR** saves you time or is useful in your workflow,
consider supporting continued development:

❤️ https://github.com/sponsors/qasimio

---

### Installation

```bash
pip install foldr
```

Requires Python 3.9+.

---

### Usage

Organize a directory:

```bash
foldr <directory>
```

Preview actions without moving files:

```bash
foldr <directory> --dry-run
```

Example:

```bash
foldr ~/Downloads --dry-run
```

> **Note (paths with spaces):**
>
> Wrap paths containing spaces in quotes.
>
> ```
> foldr "D:\My Downloads" --dry-run
> ```

---

### How It Works

- Files are grouped into predefined categories based on extension
- Category folders are created only when needed
- Existing filenames are safely renamed if conflicts occur
- Directories are detected, counted, and left untouched

---

### Safety First

- Folders are never modified
- Use `--dry-run` to preview changes
- No recursive behavior (by design)

Future versions may introduce optional recursive mode.

---

### Example Output

```
Mode: DRY RUN

report.pdf -> Documents
song.mp3 -> Audio
script.py -> Code

Total items: 24
Skipped directories: 6
Documents: 3
Audio: 1
Code: 1
Other files: 2
```

---

### Roadmap

- Optional `--recursive` flag
- User-defined category configuration
- Exclusion rules

---

### Author

**Muhammad Qasim**

GitHub: https://github.com/qasimio  
LinkedIn: https://www.linkedin.com/in/qasimio/

---

### License

MIT License
