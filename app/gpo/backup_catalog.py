from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from app.core.log import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class BackupCatalogItem:
    source_index: int
    source_path: str
    display_name: str
    folder_name: str
    path: str
    is_valid: bool
    status: str
    detail: str
    domain: str = ""
    backup_time: str = ""
    item_count: int = 0


def scan_backup_library(root_path: str, source_index: int = 1) -> list[BackupCatalogItem]:
    root = Path(root_path)

    if not root.exists() or not root.is_dir():
        _log.warning("Backup root does not exist or is not a directory: %s", root_path)
        return []

    items: list[BackupCatalogItem] = []

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.lower() == ".archived":
            continue

        metadata = read_backup_metadata(child)
        display_name = metadata.get("display_name") or child.name
        has_registry_pol, item_count = _folder_file_inventory(child)
        is_valid, status, detail = _validate_backup_folder(child, has_registry_pol)

        items.append(
            BackupCatalogItem(
                source_index=source_index,
                source_path=str(root),
                display_name=display_name,
                folder_name=child.name,
                path=str(child),
                is_valid=is_valid,
                status=status,
                detail=detail,
                domain=metadata.get("domain", ""),
                backup_time=metadata.get("backup_time", ""),
                item_count=item_count,
            )
        )

    _log.info("Scanned %s: found %d backup(s)", root_path, len(items))
    return sorted(
        items,
        key=lambda item: (
            item.display_name.casefold(),
            item.source_index,
            item.folder_name.casefold(),
        ),
    )


def read_display_name(folder: Path) -> str:
    return read_backup_metadata(folder).get("display_name", "") or folder.name


def read_backup_metadata(folder: Path) -> dict[str, str]:
    bkup_info = folder / "bkupInfo.xml"

    if not bkup_info.exists():
        return {}

    try:
        tree = ET.parse(bkup_info)
        root = tree.getroot()

        namespace = {
            "ns": "http://www.microsoft.com/GroupPolicy/GPOOperations/Manifest"
        }

        return {
            "display_name": _manifest_text(root, "GPODisplayName", namespace),
            "domain": _manifest_text(root, "GPODomain", namespace),
            "backup_time": _manifest_text(root, "BackupTime", namespace),
        }

    except Exception:
        _log.warning("Failed to parse bkupInfo.xml in %s", folder, exc_info=True)

    return {}


def _manifest_text(root: ET.Element, tag_name: str, namespace: dict[str, str]) -> str:
    node = root.find(f"ns:{tag_name}", namespace)

    if node is not None and node.text:
        return node.text.strip()

    return ""


def _validate_backup_folder(folder: Path, has_registry_pol: bool) -> tuple[bool, str, str]:
    bkup_info = folder / "bkupInfo.xml"
    backup_xml = folder / "Backup.xml"
    gpreport_xml = folder / "gpreport.xml"

    missing: list[str] = []

    if not bkup_info.exists():
        missing.append("bkupInfo.xml")

    if not backup_xml.exists():
        missing.append("Backup.xml")

    if not gpreport_xml.exists():
        missing.append("gpreport.xml")

    if missing:
        return False, "Needs review", f"Missing: {', '.join(missing)}"

    if has_registry_pol:
        return True, "Valid", "Backup metadata and registry policy found."

    return True, "Valid", "Backup metadata found. No Registry.pol detected."


def _folder_file_inventory(folder: Path) -> tuple[bool, int]:
    has_registry_pol = False
    item_count = 0

    for path in folder.rglob("*"):
        if not path.is_file():
            continue

        item_count += 1
        if path.name.casefold() == "registry.pol":
            has_registry_pol = True

    return has_registry_pol, item_count
