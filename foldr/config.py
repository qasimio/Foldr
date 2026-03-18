CATEGORIES_TEMPLATE = {
    "Documents": {
        "folder": "Documents",
        "ext": {
            ".bib", ".doc", ".docx", ".md", ".odt", ".pages", ".pdf", ".rtf", ".tex"
        },
    },
    "Text & Data": {
        "folder": "Text_Data",
        "ext": {
            ".ndjson", ".properties", ".toml", ".xml", ".yaml", ".yml", ".txt", ".env"
        },
    },
    "Images": {
        "folder": "Images",
        "ext": {
            ".bmp", ".cr2", ".gif", ".heic", ".heif", ".ico", ".jpg", ".jpeg", ".nef",
            ".orf", ".png", ".raw", ".tif", ".tiff", ".webp"
        },
    },
    "Vector Graphics": {
        "folder": "Vector_Graphics",
        "ext": {
            ".ai", ".eps", ".ps", ".svg"
        },
    },
    "Videos": {
        "folder": "Videos",
        "ext": {
            ".avi", ".flv", ".m4v", ".mkv", ".mp4", ".mpeg", ".mpg", ".mov", ".webm", ".wmv"
        },
    },
    "Audio": {
        "folder": "Audio",
        "ext": {
            ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"
        },
    },
    "Subtitles": {
        "folder": "Subtitles",
        "ext": {
            ".ass", ".ssa", ".sub", ".srt", ".vtt"
        },
    },
    "Archives": {
        "folder": "Archives",
        "ext": {
            ".7z", ".bz2", ".gz", ".rar", ".tar", ".tar.bz2", ".tar.gz", ".tar.xz", ".tgz", ".tbz2", ".xz", ".zst", ".zip"
        },
    },
    "Disk Images": {
        "folder": "Disk_Images",
        "ext": {
            ".bin", ".cue", ".dmg", ".img", ".iso", ".vhd", ".vhdx", ".vmdk"
        },
    },
    "Virtualization": {
        "folder": "Virtualization",
        "ext": {
            ".ova", ".ovf"
        },
    },
    "Executables": {
        "folder": "Executables",
        "ext": {
            ".app", ".class", ".exe", ".run", ".jar"
        },
    },
    "Packages": {
        "folder": "Packages",
        "ext": {
            ".apk", ".deb", ".egg", ".gem", ".msi", ".msix", ".npm", ".pkg", ".rpm", ".whl"
        },
    },
    "Code": {
        "folder": "Code",
        "ext": {
            ".c", ".cc", ".cpp", ".cs", ".go", ".js", ".java", ".kt", ".kts",
            ".lua", ".mjs", ".py", ".pyc", ".pm", ".rs", ".swift", ".ts", ".tsx", ".jsx",
            ".ex", ".exs", ".erl", ".h", ".hpp", ".pkt"
        },
    },
    "Notebooks": {
        "folder": "Notebooks",
        "ext": {
            ".ipynb", ".nb", ".rmd", ".sage"
        },
    },
    "Scripts": {
        "folder": "Scripts",
        "ext": {
            ".awk", ".bash", ".csh", ".fish", ".groovy", ".ksh", ".pl", ".ps1", ".ps1xml",
            ".psm1", ".rb", ".sed", ".sh", ".zsh", ".iss"
        },
    },
    "Machine_Learning": {
        "folder": "Machine_Learning",
        "ext": {
            ".h5", ".hdf5", ".joblib", ".mat", ".npz", ".onnx", ".pb", ".pkl", ".pt", ".pth", ".sav"
        },
    },
    "Databases": {
        "folder": "Databases",
        "ext": {
            ".accdb", ".db", ".dump", ".mdb", ".sqlite", ".sqlite3", ".sql"
        },
    },
    "Spreadsheets": {
        "folder": "Spreadsheets",
        "ext": {
            ".csv", ".ods", ".xls", ".xlsb", ".xlsm", ".xlsx", ".tsv"
        },
    },
    "Presentations": {
        "folder": "Presentations",
        "ext": {
            ".key", ".odp", ".ppt", ".pptx"
        },
    },
    "Fonts": {
        "folder": "Fonts",
        "ext": {
            ".eot", ".pfb", ".pfa", ".otf", ".ttf", ".woff", ".woff2"
        },
    },
    "3D_Models": {
        "folder": "3D_Models",
        "ext": {
            ".3ds", ".blend", ".fbx", ".gltf", ".glb", ".obj", ".ply", ".stl"
        },
    },
    "CAD": {
        "folder": "CAD",
        "ext": {
            ".dwg", ".dxf", ".iges", ".igs", ".stp", ".step"
        },
    },
    "GIS": {
        "folder": "GIS",
        "ext": {
            ".dbf", ".geojson", ".gpx", ".kml", ".kmz", ".shp", ".shx"
        },
    },
    "Ebooks": {
        "folder": "Ebooks",
        "ext": {
            ".azw", ".azw3", ".epub", ".fb2", ".mobi"
        },
    },
    "Web": {
        "folder": "Web",
        "ext": {
            ".css", ".html", ".htm", ".map", ".wasm", ".xhtml", ".less"
        },
    },
    "Config_and_System": {
        "folder": "Config_System",
        "ext": {
            ".conf", ".cfg", ".ini", ".plist", ".reg", ".service", ".socket", ".sys"
        },
    },
    "Certificates": {
        "folder": "Certificates",
        "ext": {
            ".cer", ".crt", ".der", ".key", ".p12", ".pfx", ".pem"
        },
    },
    "Logs": {
        "folder": "Logs",
        "ext": {
            ".err", ".log", ".out", ".trace"
        },
    },
    "Licenses": {
        "folder": "Licenses",
        "ext": {
            "COPYING", "LICENCE", "LICENSE", "LICENSE.txt"
        },
    },
    "Subprojects": {
        "folder": "Subprojects",
        "ext": {
            "CHANGELOG", "CHANGELOG.md", "README", "README.md"
        },
    },
    "Misc": {
        "folder": "Misc",
        "ext": {
            ".bak", ".crdownload", ".isoinfo", ".part", ".tmp"
        },
    },
}
"""
FOLDR CATEGORIES is a dictionary that defines 31 categories of files, each with a corresponding folder name and a set of file extensions. The categories include Documents, Text & Data, Images, Vector Graphics, Videos, Audio, Subtitles, Archives, Disk Images, Virtualization, Executables, Packages, Code, Notebooks, Scripts, Machine Learning, Databases, Spreadsheets, Presentations, Fonts, 3D Models, CAD, GIS, Ebooks, Web files, Config & System files, Certificates, Logs, Licenses, Subprojects (like README and CHANGELOG), and Miscellaneous files.

- Documents: 9
- Text & Data: 8
- Images: 15
- Vector Graphics: 4
- Videos: 10
- Audio: 8
- Subtitles: 5
- Archives: 13
- Disk Images: 8
- Virtualization: 2
- Executables: 5
- Packages: 10
- Code: 23
- Notebooks: 4
- Scripts: 14
- Machine Learning: 11
- Databases: 7
- Spreadsheets: 7
- Presentations: 4
- Fonts: 7
- 3D Models: 8
- CAD: 6
- GIS: 7
- Ebooks: 5
- Config & System: 8
- Certificates: 7
- Logs: 4
- Licenses: 4
- Subprojects: 4
- Misc: 5

Total: 31 categories, 239 extensions

"""