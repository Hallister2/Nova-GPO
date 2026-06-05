from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.settings import USER_DATA_DIR
from app.gpo.comparison_model import PolicyDiff, setting_changes
from app.reports.compare_report import actionable_items


def _rmtree(path: Path) -> None:
    """Remove a directory tree, clearing read-only flags on Windows if needed."""
    def _on_error(func, p, _exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_error)


LIBRARY_DIR = USER_DATA_DIR / "Library"
COMPARE_ARCHIVE_DIR = LIBRARY_DIR / "Compares"
COMPARE_RECORD_NAME = "compare.json"
COMPARE_HTML_NAME = "report.html"
COMPARE_MARKDOWN_NAME = "report.md"
COMPARE_SCHEMA_VERSION = 2
COMPARE_APP_VERSION = "Nova GPO"


@dataclass(frozen=True)
class CompareLibraryRecord:
    record_id: str
    title: str
    backup_a_title: str
    backup_b_title: str
    backup_a_path: str
    backup_b_path: str
    saved_at: str
    record_path: str
    html_path: str
    markdown_path: str
    total_items: int
    changed: int
    added: int
    removed: int
    reviewed: int
    actionable: int
    source_status: str


def save_compare_record(
    *,
    title_a: str,
    title_b: str,
    backup_a_path: str,
    backup_b_path: str,
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]],
    html_report: str,
    markdown_report: str,
) -> CompareLibraryRecord:
    saved_at = datetime.now().isoformat(timespec="seconds")
    record_id = _record_id(title_a, title_b, backup_a_path, backup_b_path, saved_at)
    destination = COMPARE_ARCHIVE_DIR / record_id
    destination.mkdir(parents=True, exist_ok=True)

    html_path = destination / COMPARE_HTML_NAME
    markdown_path = destination / COMPARE_MARKDOWN_NAME
    record_path = destination / COMPARE_RECORD_NAME

    html_path.write_text(html_report, encoding="utf-8")
    markdown_path.write_text(markdown_report, encoding="utf-8")

    findings = [_item_payload(item, review_notes.get(item.key, {})) for item in actionable_items(diff_items)]
    inventory = [_item_payload(item, review_notes.get(item.key, {})) for item in diff_items]

    payload = {
        "record_id": record_id,
        "schema_version": COMPARE_SCHEMA_VERSION,
        "app_version": COMPARE_APP_VERSION,
        "title": f"{title_a} vs {title_b}",
        "backup_a": {"title": title_a, "path": backup_a_path},
        "backup_b": {"title": title_b, "path": backup_b_path},
        "saved_at": saved_at,
        "html_path": str(html_path),
        "markdown_path": str(markdown_path),
        "generated_artifacts": {
            "html": str(html_path),
            "markdown": str(markdown_path),
        },
        "summary": _summary(diff_items, review_notes),
        "items": findings,
        "findings": findings,
        "inventory": inventory,
    }

    with record_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return _record_from_payload(payload, record_path)


def list_compare_records() -> list[CompareLibraryRecord]:
    if not COMPARE_ARCHIVE_DIR.exists():
        return []

    records: list[CompareLibraryRecord] = []
    for record_file in COMPARE_ARCHIVE_DIR.glob(f"*/{COMPARE_RECORD_NAME}"):
        payload = _read_record_payload(record_file)
        if payload:
            records.append(_record_from_payload(payload, record_file))

    return sorted(records, key=lambda record: record.saved_at, reverse=True)


def load_compare_record_payload(record_path: str) -> dict[str, Any]:
    path = Path(record_path)
    if path.is_dir():
        path = path / COMPARE_RECORD_NAME
    payload = _read_record_payload(path)
    if not payload:
        raise FileNotFoundError(f"Could not read saved compare review: {record_path}")
    payload.setdefault("record_path", str(path))
    return payload


def update_compare_record_reviews(record_path: str, reviews: dict[str, dict[str, str]]) -> None:
    path = Path(record_path)
    if path.is_dir():
        path = path / COMPARE_RECORD_NAME
    payload = _read_record_payload(path)
    if not payload:
        raise FileNotFoundError(f"Could not read saved compare review: {record_path}")

    changed = False
    for collection_name in ("findings", "items", "inventory"):
        items = payload.get(collection_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", ""))
            if key in reviews:
                item["review"] = reviews[key]
                changed = True

    summary = payload.setdefault("summary", {})
    if isinstance(summary, dict):
        findings = payload.get("findings") if isinstance(payload.get("findings"), list) else payload.get("items", [])
        summary["reviewed"] = sum(
            1 for item in findings
            if isinstance(item, dict) and _review_has_content(item.get("review", {}))
        )

    if changed:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)


def rename_compare_record(record_path: str, new_title: str) -> None:
    path = Path(record_path)
    if not path.exists():
        raise FileNotFoundError(f"Compare record not found: {record_path}")

    payload = _read_record_payload(path)
    if not payload:
        raise ValueError(f"Could not read compare record: {record_path}")

    payload["title"] = new_title.strip()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def delete_compare_record(record_path: str) -> None:
    path = Path(record_path)
    if path.name == COMPARE_RECORD_NAME:
        target = path.parent
    else:
        target = path

    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Saved compare review was not found: {record_path}")

    expected_root = COMPARE_ARCHIVE_DIR.resolve()
    resolved_target = target.resolve()
    if expected_root not in resolved_target.parents and resolved_target != expected_root:
        raise ValueError(f"Refusing to delete outside compare library: {record_path}")

    _rmtree(target)


def _summary(diff_items: list[PolicyDiff], review_notes: dict[str, dict[str, str]]) -> dict[str, int]:
    findings = actionable_items(diff_items)
    return {
        "total_items": len(diff_items),
        "actionable": len(findings),
        "changed": sum(1 for item in diff_items if item.status == "Different"),
        "added": sum(1 for item in diff_items if item.status == "Added"),
        "removed": sum(1 for item in diff_items if item.status == "Removed"),
        "reviewed": sum(
            1 for item in findings
            if _review_has_content(review_notes.get(item.key, {}))
        ),
    }


def _item_payload(item: PolicyDiff, review: dict[str, str]) -> dict[str, Any]:
    policy = item.policy_b or item.policy_a
    return {
        "key": item.key,
        "name": policy.name if policy else item.key,
        "status": item.status,
        "scope": item.scope,
        "category": policy.category if policy else "",
        "policy_type": policy.policy_type if policy else "",
        "source": policy.source if policy else "",
        "supported": policy.supported if policy else "",
        "state_a": item.state_a,
        "state_b": item.state_b,
        "changes": setting_changes(item),
        "supporting_evidence": list(item.supporting_evidence),
        "review": {
            "status": review.get("status", "Pending Review"),
            "priority": review.get("priority", "Normal"),
            "owner": review.get("owner", ""),
            "ticket": review.get("ticket", ""),
            "tags": review.get("tags", ""),
            "notes": review.get("notes", ""),
            "updated_at": review.get("updated_at", ""),
        },
    }


def _review_has_content(note: dict[str, str]) -> bool:
    return (
        note.get("status", "Pending Review") != "Pending Review"
        or note.get("priority", "Normal") != "Normal"
        or bool(note.get("owner", "").strip())
        or bool(note.get("ticket", "").strip())
        or bool(note.get("tags", "").strip())
        or bool(note.get("notes", "").strip())
        # legacy field names
        or note.get("disposition", "Not Reviewed") not in ("Not Reviewed", "Pending Review", "")
        or bool(note.get("note", "").strip())
    )


def _read_record_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _record_from_payload(payload: dict[str, Any], record_path: Path) -> CompareLibraryRecord:
    backup_a = payload.get("backup_a", {}) if isinstance(payload.get("backup_a"), dict) else {}
    backup_b = payload.get("backup_b", {}) if isinstance(payload.get("backup_b"), dict) else {}
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    backup_a_path = str(backup_a.get("path", ""))
    backup_b_path = str(backup_b.get("path", ""))
    html_path = str(payload.get("html_path") or record_path.with_name(COMPARE_HTML_NAME))
    markdown_path = str(payload.get("markdown_path") or record_path.with_name(COMPARE_MARKDOWN_NAME))

    return CompareLibraryRecord(
        record_id=str(payload.get("record_id") or record_path.parent.name),
        title=str(payload.get("title") or "Saved comparison"),
        backup_a_title=str(backup_a.get("title") or "Backup A"),
        backup_b_title=str(backup_b.get("title") or "Backup B"),
        backup_a_path=backup_a_path,
        backup_b_path=backup_b_path,
        saved_at=str(payload.get("saved_at") or ""),
        record_path=str(record_path),
        html_path=html_path,
        markdown_path=markdown_path,
        total_items=_int(summary.get("total_items")),
        changed=_int(summary.get("changed")),
        added=_int(summary.get("added")),
        removed=_int(summary.get("removed")),
        reviewed=_int(summary.get("reviewed")),
        actionable=_int(summary.get("actionable")) or (
            _int(summary.get("changed")) + _int(summary.get("added")) + _int(summary.get("removed"))
        ),
        source_status=_source_status(backup_a_path, backup_b_path),
    )


def _source_status(path_a: str, path_b: str) -> str:
    exists_a = bool(path_a) and Path(path_a).exists()
    exists_b = bool(path_b) and Path(path_b).exists()
    if exists_a and exists_b:
        return "Sources available"
    if exists_a or exists_b:
        return "One source missing"
    return "Sources missing"


def _record_id(title_a: str, title_b: str, path_a: str, path_b: str, saved_at: str) -> str:
    identity = "\n".join([title_a, title_b, path_a, path_b, saved_at])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
