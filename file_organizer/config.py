from pathlib import Path

CATEGORIES_TEMPLATE = {
    "PDFs": {
        "folder": "PDFs",
        "ext": {".pdf"},
    },
    "Office files": {
        "folder": "Office files",
        "ext": {".docx", ".xlsx", ".pptx", ".accdb"},
    },
    "Text files": {
        "folder": "Text files",
        "ext": {".csv", ".json", ".txt", ".md"},
    },
    "Images": {
        "folder": "Images",
        "ext": {".png", ".jpg", ".jpeg", ".ico"},
    },
    "Videos": {
        "folder": "Videos",
        "ext": {".mp4", ".mov", ".mkv", ".avi"},
    },
    "Audio files": {
        "folder": "Audio files",
        "ext": {".mp3", ".wav", ".m4a", ".aac"},
    },
    "Coding Files": {
        "folder": "Coding Files",
        "ext": {".py", ".ipynb", ".java", ".html", ".cpp"},
    },
    "Setups": {
        "folder": "Setups",
        "ext": {".exe"},
    }
}
