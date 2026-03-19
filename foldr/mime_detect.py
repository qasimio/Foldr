"""
foldr.mime_detect
~~~~~~~~~~~~~~~~~
MIME-type detection for FOLDR v0.2.1.

Used by --smart mode to catch spoofed extensions (e.g. image.png.exe).

Strategy
--------
1. Try python-magic (libmagic) — most accurate
2. Fall back to mimetypes (stdlib) — extension-based, always available

The result is used to override the extension-based category when the
detected MIME type strongly disagrees with the file extension.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

# Attempt to import python-magic
try:
    import magic as _magic
    _MAGIC_AVAILABLE = True
except ImportError:
    _MAGIC_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# MIME → category mapping (covers the most important override cases)
# ──────────────────────────────────────────────────────────────────────────────

_MIME_TO_CATEGORY: dict[str, str] = {
    # Executables / binaries
    "application/x-executable":      "Executables",
    "application/x-dosexec":         "Executables",
    "application/x-elf":             "Executables",
    "application/x-mach-binary":     "Executables",
    "application/x-msdownload":      "Executables",
    # Archives
    "application/zip":               "Archives",
    "application/x-tar":             "Archives",
    "application/x-7z-compressed":   "Archives",
    "application/gzip":              "Archives",
    "application/x-rar-compressed":  "Archives",
    # Images
    "image/png":                     "Images",
    "image/jpeg":                    "Images",
    "image/gif":                     "Images",
    "image/webp":                    "Images",
    "image/bmp":                     "Images",
    # Video
    "video/mp4":                     "Videos",
    "video/x-matroska":              "Videos",
    "video/quicktime":               "Videos",
    "video/x-msvideo":               "Videos",
    # Audio
    "audio/mpeg":                    "Audio",
    "audio/wav":                     "Audio",
    "audio/flac":                    "Audio",
    "audio/ogg":                     "Audio",
    # Documents
    "application/pdf":               "Documents",
    "application/msword":            "Documents",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Documents",
    # Spreadsheets
    "application/vnd.ms-excel":      "Spreadsheets",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Spreadsheets",
    # Code / text
    "text/x-python":                 "Code",
    "text/x-java-source":            "Code",
    "text/x-csrc":                   "Code",
    "text/html":                     "Code",
    "text/css":                      "Code",
    "text/javascript":               "Code",
    "application/javascript":        "Code",
    "text/plain":                    "Text & Data",
    "text/csv":                      "Text & Data",
    "application/json":              "Text & Data",
}


def detect_mime(path: Path) -> str | None:
    """
    Return MIME type string for `path`, or None if detection fails.
    Prefers python-magic; falls back to mimetypes.
    """
    if _MAGIC_AVAILABLE:
        try:
            mime = _magic.from_file(str(path), mime=True)
            return mime
        except Exception:
            pass

    # stdlib fallback (extension-based)
    mime, _ = mimetypes.guess_type(str(path))
    return mime


def category_from_mime(path: Path) -> str | None:
    """
    Return the category name inferred from MIME type, or None if unknown.
    Only returns a value when python-magic is available and confident.
    """
    mime = detect_mime(path)
    if not mime:
        return None
    return _MIME_TO_CATEGORY.get(mime)


def is_magic_available() -> bool:
    return _MAGIC_AVAILABLE