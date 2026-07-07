<div align="center">

# FOLDR

[![PyPI Version](https://img.shields.io/pypi/v/foldr?cacheSeconds=300)](https://pypi.org/project/foldr/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-online-blue?logo=gitbook)](https://docs.qasimio.me/docs/foldr/start-here)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/foldr?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/foldr)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)](#)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/qasimio/Foldr)
[![Support on Patreon](https://img.shields.io/badge/Patreon-Support-orange)](https://patreon.com/qasimio)

**Never organize your files like a caveman.**

📖 Documentation: https://docs.qasimio.me/docs/foldr/start-here

FOLDR cleans messy directories by sorting files into category folders — instantly, predictably, and safely. Preview every action before anything moves. Undo anything. Watch a folder and keep it tidy automatically.

</div>

---

<h2 align="center">Preview</h2>

<p align="center">
  <img src="assets/foldr-preview.png" width="800"/>
</p>

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
```
Done?

Continue with the complete documentation:
https://docs.qasimio.me/docs/foldr/start-here
```
---

## Documentation

Looking for detailed guides, advanced usage, and examples?

📖 https://docs.qasimio.me/docs/foldr/start-here

---

## Safety

- **Preview by default** — FOLDR shows you what it will do and asks before moving anything.
- **Folders are never touched** — only files are moved; directories stay where they are.
- **Conflict-safe** — if a file with the same name already exists at the destination, FOLDR renames the incoming file (`photo_(1).jpg`, etc.) rather than overwriting.
- **Undo anything** — every operation is reversible via `foldr undo`.
- **Dedup is the only irreversible action** — always use `--preview` before `--dedup`.

---

## Star History

<a href="https://www.star-history.com/?repos=qasimio%2FFOLDR&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=qasimio/FOLDR&type=date&theme=dark&legend=top-left&sealed_token=nRvWhSFeLGr0geFLPrNTsGQ4Z-SGfTeO5_g56Vm1QCMzt33eD8o-BTaTJU12u3HJSN-7Rr-7mPjy5dCL0n5zCDaLw2BxUjcU_oIjtUO8M1fKPiKWD4BsvA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=qasimio/FOLDR&type=date&legend=top-left&sealed_token=nRvWhSFeLGr0geFLPrNTsGQ4Z-SGfTeO5_g56Vm1QCMzt33eD8o-BTaTJU12u3HJSN-7Rr-7mPjy5dCL0n5zCDaLw2BxUjcU_oIjtUO8M1fKPiKWD4BsvA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=qasimio/FOLDR&type=date&legend=top-left&sealed_token=nRvWhSFeLGr0geFLPrNTsGQ4Z-SGfTeO5_g56Vm1QCMzt33eD8o-BTaTJU12u3HJSN-7Rr-7mPjy5dCL0n5zCDaLw2BxUjcU_oIjtUO8M1fKPiKWD4BsvA" />
 </picture>
</a>

---

## 💖 Support

If FOLDR saves you time or improves your workflow, consider supporting its continued development and maintenance:

[![Support on Patreon](https://img.shields.io/badge/Patreon-qasimio-F96854?style=for-the-badge&logo=patreon&logoColor=white)](https://patreon.com/qasimio)

---

## Author

**Muhammad Qasim**
[qasimio.me](https://qasimio.me)
<br>
LinkedIn: [linkedin.com/in/qasimio](https://www.linkedin.com/in/qasimio/)

---

## License

[MIT](LICENSE)
