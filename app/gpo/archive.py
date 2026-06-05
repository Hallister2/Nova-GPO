from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.log import get_logger
from app.gpo.backup_catalog import read_display_name

_log = get_logger(__name__)


def _rmtree(path: Path) -> None:
    """Remove a directory tree, clearing read-only flags on Windows if needed."""
    def _on_error(func, p, _exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_error)


ARCHIVE_DIR_NAME = ".Archived"
ARCHIVE_META_NAME = ".nova_archive.json"


@dataclass(frozen=True)
class ArchivedBackup:
    source_index: int
    source_path: str
    archived_path: str
    original_path: str
    display_name: str
    archived_at: str
    status: str


def archive_backup(backup_path: str) -> ArchivedBackup:
    source = Path(backup_path)
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Backup folder was not found: {backup_path}")

    archive_root = source.parent / ARCHIVE_DIR_NAME
    archive_root.mkdir(exist_ok=True)

    destination = _unique_destination(archive_root / source.name)
    archived_at = datetime.now().isoformat(timespec="seconds")

    display_name = read_display_name(source)

    shutil.move(str(source), str(destination))
    _write_archive_metadata(destination, source, archived_at, display_name)
    _log.info("Archived '%s' -> %s", display_name, destination)

    return ArchivedBackup(
        source_index=0,
        source_path=str(source.parent),
        archived_path=str(destination),
        original_path=str(source),
        display_name=display_name,
        archived_at=archived_at,
        status="Archived",
    )


def restore_archived_backup(archived_path: str) -> str:
    source = Path(archived_path)
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Archived backup was not found: {archived_path}")

    metadata = _read_archive_metadata(source)
    original_path = Path(metadata.get("original_path") or source.parent.parent / source.name)

    if original_path.exists():
        raise FileExistsError(f"Restore target already exists: {original_path}")

    original_path.parent.mkdir(parents=True, exist_ok=True)
    meta_file = source / ARCHIVE_META_NAME
    if meta_file.exists():
        meta_file.unlink()

    shutil.move(str(source), str(original_path))
    _log.info("Restored '%s' -> %s", source.name, original_path)
    return str(original_path)


def list_archived_backups(roots: list[str]) -> list[ArchivedBackup]:
    items: list[ArchivedBackup] = []

    for source_index, root in enumerate(roots, start=1):
        archive_root = Path(root) / ARCHIVE_DIR_NAME
        if not archive_root.exists() or not archive_root.is_dir():
            continue

        for child in sorted(archive_root.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir():
                continue

            metadata = _read_archive_metadata(child)
            original_path = metadata.get("original_path") or str(Path(root) / child.name)
            archived_at = metadata.get("archived_at") or _mtime_iso(child)
            display_name = metadata.get("display_name") or child.name

            items.append(
                ArchivedBackup(
                    source_index=source_index,
                    source_path=str(root),
                    archived_path=str(child),
                    original_path=original_path,
                    display_name=display_name,
                    archived_at=archived_at,
                    status="Restorable" if not Path(original_path).exists() else "Conflict",
                )
            )

    return items


def purge_expired_archives(roots: list[str], retention_days: int) -> int:
    if retention_days < 0:
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0

    for archived in list_archived_backups(roots):
        archived_at = _parse_datetime(archived.archived_at)
        archived_path = Path(archived.archived_path)

        if archived_at > cutoff:
            continue

        _log.info("Purged expired archive: %s (archived %s)", archived_path, archived.archived_at)
        _rmtree(archived_path)
        removed += 1

    _log.info("Purge complete: removed %d expired archive(s)", removed)
    return removed


def permanently_delete_archived_backup(archived_path: str) -> None:
    path = Path(archived_path)
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Archived backup was not found: {archived_path}")

    _log.info("Permanently deleting archived backup: %s", archived_path)
    _rmtree(path)


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}-{suffix}")
    counter = 2

    while candidate.exists():
        candidate = path.with_name(f"{path.name}-{suffix}-{counter}")
        counter += 1

    return candidate


def _write_archive_metadata(destination: Path, original_path: Path, archived_at: str, display_name: str) -> None:
    metadata = {
        "display_name": display_name or original_path.name,
        "original_path": str(original_path),
        "archived_at": archived_at,
    }

    with (destination / ARCHIVE_META_NAME).open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)


def _read_archive_metadata(path: Path) -> dict[str, str]:
    meta_file = path / ARCHIVE_META_NAME
    if not meta_file.exists():
        return {}

    try:
        with meta_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return {str(key): str(value) for key, value in data.items()}


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromtimestamp(0)
