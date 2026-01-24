from pathlib import Path

CATEGORIES_TEMPLATE = {
    "Documents": {
        "folder": "Documents",
        "ext": {
            ".pdf", ".doc", ".docx", ".odt",
            ".xls", ".xlsx", ".ppt", ".pptx",
            ".rtf"
        },
    },
    "Text & Data": {
        "folder": "Text_Data",
        "ext": {
            ".txt", ".md", ".csv", ".json",
            ".xml", ".yaml", ".yml", ".log", "toml"
        },
    },
    "Images": {
        "folder": "Images",
        "ext": {
            ".png", ".jpg", ".jpeg", ".gif",
            ".bmp", ".tiff", ".ico", ".webp"
        },
    },
    "Videos": {
        "folder": "Videos",
        "ext": {
            ".mp4", ".mkv", ".mov",
            ".avi", ".wmv", ".flv"
        },
    },
    "Audio": {
        "folder": "Audio",
        "ext": {
            ".mp3", ".wav", ".aac",
            ".flac", ".ogg", ".m4a"
        },
    },
    "Archives": {
        "folder": "Archives",
        "ext": {
            ".zip", ".rar", ".7z",
            ".tar", ".gz", ".bz2"
        },
    },
    "Executables": {
        "folder": "Executables",
        "ext": {
            ".exe", ".msi", ".sh", ".bat", ".app"
        },
    },
    "Code": {
        "folder": "Code",
        "ext": {
            ".py", ".ipynb", ".java", ".cpp", ".c",
            ".js", ".ts", ".html", ".css",
            ".go", ".rs", ".php", ".sql"
        },
    },
    "Fonts": {
        "folder": "Fonts",
        "ext": {
            ".ttf", ".otf", ".woff", ".woff2"
        },
    }
}