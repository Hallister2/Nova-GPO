from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.core.settings import APP_ROOT, USER_DATA_DIR
from app.review_status import normalize_review_status


REVIEW_DIR = USER_DATA_DIR / "Reviews"
LEGACY_REVIEW_DIR = APP_ROOT / "config" / "reviews"


def load_review_notes(backup_a_path: str, backup_b_path: str) -> dict[str, dict[str, str]]:
    path = _review_path(backup_a_path, backup_b_path)
    if not path.exists():
        legacy_path = _legacy_review_path(backup_a_path, backup_b_path)
        if legacy_path.exists():
            path = legacy_path

    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}

    notes = data.get("notes", data)
    if not isinstance(notes, dict):
        return {}

    clean: dict[str, dict[str, str]] = {}
    for key, value in notes.items():
        if not isinstance(value, dict):
            continue
        # Migrate old field names (disposition/impact/note/points/owner/ticket → status/priority/notes)
        review_status = normalize_review_status(value.get("status") or _migrate_disposition(value.get("disposition", "")))
        review_priority = str(value.get("priority") or _migrate_impact(value.get("impact", "")))
        review_notes = str(value.get("notes") or _merge_old_notes(value))
        clean[str(key)] = {
            "status": review_status,
            "priority": review_priority,
            "owner": str(value.get("owner", "")),
            "ticket": str(value.get("ticket", "")),
            "tags": str(value.get("tags", "")),
            "notes": review_notes,
            "updated_at": str(value.get("updated_at", "")),
        }

    return clean


def _migrate_disposition(old: str) -> str:
    return {
        "Approved": "No Action Required",
        "Needs Review": "Make Changes to A",
        "Risk Accepted": "No Action Required",
        "Rollback Candidate": "Escalated",
        "Not Reviewed": "Pending Review",
    }.get(old, "Pending Review")


def _migrate_impact(old: str) -> str:
    return {
        "Low": "Low", "Medium": "Medium", "High": "High", "Critical": "Critical",
    }.get(old, "Normal")


def _merge_old_notes(value: dict) -> str:
    parts = []
    for field in ("owner", "ticket", "note", "points"):
        text = str(value.get(field, "")).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def save_review_notes(
    backup_a_path: str,
    backup_b_path: str,
    notes: dict[str, dict[str, str]],
) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = _review_path(backup_a_path, backup_b_path)
    payload = {
        "backup_a": backup_a_path,
        "backup_b": backup_b_path,
        "notes": notes,
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _review_path(backup_a_path: str, backup_b_path: str) -> Path:
    identity = "\n".join(sorted([str(Path(backup_a_path)), str(Path(backup_b_path))]))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return REVIEW_DIR / f"{digest}.json"


def _legacy_review_path(backup_a_path: str, backup_b_path: str) -> Path:
    identity = "\n".join(sorted([str(Path(backup_a_path)), str(Path(backup_b_path))]))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return LEGACY_REVIEW_DIR / f"{digest}.json"
