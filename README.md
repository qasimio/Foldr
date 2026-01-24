# FOLDR

##### A safe, fast, and predictable CLI tool to organize files in a directory by file extension.

**FOLDR** is designed to clean up messy folders without touching your existing folder structure. It focuses on files only, with a built-in --dry-run mode so you can see exactly what will happen before anything moves.

--- 

### Features
<br>

- Organizes files by extension into clear categories
- Never modifies or moves existing folders
- Dry-run mode to preview actions safely
- Handles filename conflicts automatically
- Cross-platform (Windows, macOS, Linux)

---

### Installation
<br>

```
pip install foldr
```

Requires Python 3.9+.

---
### Usage
<br>

Organize a directory:
```
foldr <directory>
```
Preview actions without moving files:
```
foldr <directory> --dry-run
```
Example:
```
foldr ~/Downloads --dry-run
```

---

### How It Works
<br>

- Files are grouped into predefined categories based on extension
- Category folders are created only if needed
- If a filename already exists, FOLDR safely renames the file
- Directories are detected, counted, and left untouched

---

### Safety First
<br>

Folders are never modified

- Use ```--dry-run``` to preview changes

- No recursive behavior (by design)

Future versions may introduce optional recursive mode.

---

### Example Output
<br>

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
<br>

- Optional ```--recursive``` flag

- User-defined category configuration

- Exclusion rules

---

### Author

**Muhammad Qasim** 

GitHub: https://github.com/Kas-sim

---

#### License

**MIT License**