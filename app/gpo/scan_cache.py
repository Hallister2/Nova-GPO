from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.log import get_logger
from app.core.settings import USER_DATA_DIR
from app.gpo.backup_catalog import BackupCatalogItem

_log = get_logger(__name__)

SCAN_CACHE_PATH = USER_DATA_DIR / "Library" / "scan_cache.json"


@dataclass(frozen=True)
class ScanCache:
    roots: list[str]
    scanned_at: str
    elapsed_seconds: float
    items: list[BackupCatalogItem]
    errors: list[str]
    is_stale: bool = False


def load_scan_cache(roots: list[str]) -> ScanCache | None:
    """Load the last scan result if it matches the current source roots."""
    try:
        data = json.loads(SCAN_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        _log.warning("Could not read scan cache at %s", SCAN_CACHE_PATH, exc_info=True)
        return None

    cached_roots = [str(root) for root in data.get("roots", [])]
    if _normalize_roots(cached_roots) != _normalize_roots(roots):
        return None
    cached_fingerprint = data.get("source_fingerprint", {})

    try:
        return ScanCache(
            roots=cached_roots,
            scanned_at=str(data.get("scanned_at", "")),
            elapsed_seconds=float(data.get("elapsed_seconds", 0.0)),
            items=[_item_from_dict(item) for item in data.get("items", [])],
            errors=[str(error) for error in data.get("errors", [])],
            is_stale=cached_fingerprint != source_fingerprint(roots),
        )
    except Exception:
        _log.warning("Scan cache is invalid and will be ignored.", exc_info=True)
        return None


def save_scan_cache(
    roots: list[str],
    items: list[BackupCatalogItem],
    elapsed_seconds: float,
    errors: list[str] | None = None,
) -> None:
    data = {
        "version": 1,
        "roots": roots,
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "source_fingerprint": source_fingerprint(roots),
        "items": [asdict(item) for item in items],
        "errors": errors or [],
    }

    try:
        SCAN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = SCAN_CACHE_PATH.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(SCAN_CACHE_PATH)
    except Exception:
        _log.warning("Could not write scan cache at %s", SCAN_CACHE_PATH, exc_info=True)


def display_scan_time(scanned_at: str) -> str:
    if not scanned_at:
        return "Not scanned"
    try:
        parsed = datetime.fromisoformat(scanned_at)
    except ValueError:
        return scanned_at
    return parsed.strftime("%I:%M %p").lstrip("0")


def source_fingerprint(roots: list[str]) -> dict[str, Any]:
    """Cheaply describe source contents without recursively scanning every file."""
    fingerprint: dict[str, Any] = {}
    for root in roots:
        root_path = Path(root)
        key = str(root_path.expanduser()).casefold().rstrip("\\/")
        try:
            root_stat = root_path.stat()
        except OSError:
            fingerprint[key] = {"exists": False}
            continue

        children: list[dict[str, Any]] = []
        try:
            for child in sorted(root_path.iterdir(), key=lambda path: path.name.casefold()):
                if not child.is_dir() or child.name.casefold() == ".archived":
                    continue
                try:
                    child_stat = child.stat()
                except OSError:
                    children.append({"name": child.name, "missing": True})
                    continue
                children.append({
                    "name": child.name,
                    "mtime_ns": child_stat.st_mtime_ns,
                    "size": child_stat.st_size,
                })
        except OSError:
            children = []

        fingerprint[key] = {
            "exists": root_path.is_dir(),
            "mtime_ns": root_stat.st_mtime_ns,
            "children": children,
        }
    return fingerprint


def _normalize_roots(roots: list[str]) -> list[str]:
    return [str(Path(root).expanduser()).casefold().rstrip("\\/") for root in roots if str(root).strip()]


def _item_from_dict(data: dict[str, Any]) -> BackupCatalogItem:
    return BackupCatalogItem(
        source_index=int(data.get("source_index", 0)),
        source_path=str(data.get("source_path", "")),
        display_name=str(data.get("display_name", "")),
        folder_name=str(data.get("folder_name", "")),
        path=str(data.get("path", "")),
        is_valid=bool(data.get("is_valid", False)),
        status=str(data.get("status", "")),
        detail=str(data.get("detail", "")),
        domain=str(data.get("domain", "")),
        backup_time=str(data.get("backup_time", "")),
        item_count=int(data.get("item_count", 0)),
    )
