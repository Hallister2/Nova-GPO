from __future__ import annotations

from pathlib import Path


def analyze_backup_folder(folder_path: str) -> dict[str, int]:
    root = Path(folder_path)

    counts = {
        "xml": 0,
        "ini": 0,
        "inf": 0,
        "pol": 0,
        "scripts": 0,
        "total_files": 0,
    }

    if not root.exists() or not root.is_dir():
        return counts

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        counts["total_files"] += 1
        suffix = file_path.suffix.lower()

        if suffix == ".xml":
            counts["xml"] += 1
        elif suffix == ".ini":
            counts["ini"] += 1
        elif suffix == ".inf":
            counts["inf"] += 1
        elif suffix == ".pol":
            counts["pol"] += 1
        elif suffix in {".bat", ".cmd", ".ps1", ".vbs", ".js"}:
            counts["scripts"] += 1

    return counts