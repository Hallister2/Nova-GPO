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
from app.reports.compare_report import actionable_items, json_report, markdown_report, html_report, remediation_steps


def _rmtree(path: Path) -> None:
    """Remove a directory tree, clearing read-only flags on Windows if needed."""
    def _on_error(func, p, _exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_error)


LIBRARY_DIR = USER_DATA_DIR / "Library"
COMPARE_ARCHIVE_DIR = LIBRARY_DIR / "Compares"
COMPARE_RECORD_NAME = "compare.json"
COMPARE_INDEX_NAME = "index.json"
COMPARE_HTML_NAME = "report.html"
COMPARE_MARKDOWN_NAME = "report.md"
COMPARE_SCHEMA_VERSION = 3
COMPARE_APP_VERSION = "Nova GPO"
NON_ACTIONABLE_REVIEW_STATUSES = {"No Action Required"}


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
    ignored: int
    source_status: str
    risk_counts: dict[str, int]
    diagnostics: dict[str, Any]


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
        "diagnostics": _diagnostics(diff_items),
        "items": findings,
        "findings": findings,
        "inventory": inventory,
    }

    with record_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    record = _record_from_payload(payload, record_path)
    _rebuild_compare_index()
    return record


def list_compare_records() -> list[CompareLibraryRecord]:
    if not COMPARE_ARCHIVE_DIR.exists():
        return []

    indexed = _read_compare_index()
    if indexed is not None:
        return indexed

    return _rebuild_compare_index()


def _list_compare_records_from_payloads() -> list[CompareLibraryRecord]:
    records: list[CompareLibraryRecord] = []
    for record_file in COMPARE_ARCHIVE_DIR.glob(f"*/{COMPARE_RECORD_NAME}"):
        payload = _read_record_payload(record_file)
        if payload:
            if _repair_compare_payload_summary(payload):
                _write_record_payload(record_file, payload)
            records.append(_record_from_payload(payload, record_file))

    return sorted(records, key=lambda record: record.saved_at, reverse=True)


def repair_compare_record_summaries() -> int:
    if not COMPARE_ARCHIVE_DIR.exists():
        return 0

    repaired = 0
    for record_file in COMPARE_ARCHIVE_DIR.glob(f"*/{COMPARE_RECORD_NAME}"):
        payload = _read_record_payload(record_file)
        if payload and _repair_compare_payload_summary(payload):
            _write_record_payload(record_file, payload)
            repaired += 1

    return repaired


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

    changed = _repair_compare_payload_summary(payload) or changed

    if changed:
        _write_record_payload(path, payload)
        _rebuild_compare_index()


def rename_compare_record(record_path: str, new_title: str) -> None:
    path = Path(record_path)
    if not path.exists():
        raise FileNotFoundError(f"Compare record not found: {record_path}")

    payload = _read_record_payload(path)
    if not payload:
        raise ValueError(f"Could not read compare record: {record_path}")

    payload["title"] = new_title.strip()
    _write_record_payload(path, payload)
    _rebuild_compare_index()


def regenerate_compare_record(record_path: str) -> CompareLibraryRecord:
    path = Path(record_path)
    if path.is_dir():
        path = path / COMPARE_RECORD_NAME
    if not path.exists():
        raise FileNotFoundError(f"Compare record not found: {record_path}")

    payload = _read_record_payload(path)
    if not payload:
        raise ValueError(f"Could not read compare record: {record_path}")

    backup_a = payload.get("backup_a", {}) if isinstance(payload.get("backup_a"), dict) else {}
    backup_b = payload.get("backup_b", {}) if isinstance(payload.get("backup_b"), dict) else {}
    title_a = str(backup_a.get("title") or "Backup A")
    title_b = str(backup_b.get("title") or "Backup B")
    backup_a_path = str(backup_a.get("path") or "")
    backup_b_path = str(backup_b.get("path") or "")

    missing = [
        label for label, backup_path in (("Backup A", backup_a_path), ("Backup B", backup_b_path))
        if not backup_path or not Path(backup_path).exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Cannot regenerate because source backup folder(s) are missing: "
            + ", ".join(missing)
        )

    from app.gpo.backup_loader import load_gpo_backup
    from app.gpo.gpreport_parser import load_gpreport
    from app.gpo.comparison_model import build_backup_diff

    backup_a_model = load_gpo_backup(backup_a_path)
    backup_b_model = load_gpo_backup(backup_b_path)
    report_a = load_gpreport(backup_a_path)
    report_b = load_gpreport(backup_b_path)
    diff_items = build_backup_diff(backup_a_model, backup_b_model, report_a, report_b)
    review_notes = _reviews_from_payload(payload)

    html_path = Path(str(payload.get("html_path") or path.with_name(COMPARE_HTML_NAME)))
    markdown_path = Path(str(payload.get("markdown_path") or path.with_name(COMPARE_MARKDOWN_NAME)))
    json_path = path.with_name("report.json")

    html_path.write_text(html_report(title_a, title_b, diff_items, review_notes), encoding="utf-8")
    markdown_path.write_text(markdown_report(title_a, title_b, diff_items, review_notes), encoding="utf-8")
    json_path.write_text(json_report(title_a, title_b, diff_items, review_notes), encoding="utf-8")

    findings = [_item_payload(item, review_notes.get(item.key, {})) for item in actionable_items(diff_items)]
    inventory = [_item_payload(item, review_notes.get(item.key, {})) for item in diff_items]

    payload["app_version"] = COMPARE_APP_VERSION
    payload["regenerated_at"] = datetime.now().isoformat(timespec="seconds")
    payload["html_path"] = str(html_path)
    payload["markdown_path"] = str(markdown_path)
    payload["generated_artifacts"] = {
        "html": str(html_path),
        "markdown": str(markdown_path),
        "json": str(json_path),
    }
    payload["summary"] = _summary(diff_items, review_notes)
    payload["diagnostics"] = _diagnostics(diff_items)
    payload["items"] = findings
    payload["findings"] = findings
    payload["inventory"] = inventory

    _write_record_payload(path, payload)
    _rebuild_compare_index()
    return _record_from_payload(payload, path)


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
    _rebuild_compare_index()


def _summary(diff_items: list[PolicyDiff], review_notes: dict[str, dict[str, str]]) -> dict[str, int]:
    from app.reports.insights import risk_counts

    findings = actionable_items(diff_items)
    return {
        "total_items": len(diff_items),
        "actionable": sum(
            1 for item in findings
            if _review_status_is_actionable(review_notes.get(item.key, {}))
        ),
        "ignored": sum(
            1 for item in findings
            if _review_status_is_ignored(review_notes.get(item.key, {}))
        ),
        "changed": sum(1 for item in diff_items if item.status in {"Changed", "Different"}),
        "added": sum(1 for item in diff_items if item.status == "Added"),
        "removed": sum(1 for item in diff_items if item.status == "Removed"),
        "reviewed": sum(
            1 for item in findings
            if _review_has_content(review_notes.get(item.key, {}))
        ),
        "risk_counts": risk_counts(diff_items),
    }


def _diagnostics(diff_items: list[PolicyDiff]) -> dict[str, Any]:
    from app.reports.insights import diagnostics_dict

    return diagnostics_dict(diff_items)


def _item_payload(item: PolicyDiff, review: dict[str, str]) -> dict[str, Any]:
    from app.reports.insights import risk_tag

    policy = item.policy_b or item.policy_a
    return {
        "key": item.key,
        "name": policy.name if policy else item.key,
        "status": item.status,
        "scope": item.scope,
        "category": policy.category if policy else "",
        "policy_type": policy.policy_type if policy else "",
        "source": policy.source if policy else "",
        "risk": risk_tag(item),
        "supported": policy.supported if policy else "",
        "state_a": item.state_a,
        "state_b": item.state_b,
        "changes": setting_changes(item),
        "remediation": [
            {"action": action, "target": target, "detail": detail}
            for action, target, detail in remediation_steps(item)
        ],
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


def _reviews_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    reviews: dict[str, dict[str, str]] = {}
    for collection_name in ("inventory", "findings", "items"):
        items = payload.get(collection_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", ""))
            review = item.get("review", {})
            if key and isinstance(review, dict):
                reviews[key] = {
                    "status": str(review.get("status", "Pending Review")),
                    "priority": str(review.get("priority", "Normal")),
                    "owner": str(review.get("owner", "")),
                    "ticket": str(review.get("ticket", "")),
                    "tags": str(review.get("tags", "")),
                    "notes": str(review.get("notes", "")),
                    "updated_at": str(review.get("updated_at", "")),
                }
    return reviews


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


def _review_status_is_actionable(note: dict[str, str]) -> bool:
    return note.get("status", "Pending Review") not in NON_ACTIONABLE_REVIEW_STATUSES


def _review_status_is_ignored(note: dict[str, str]) -> bool:
    return note.get("status", "Pending Review") in NON_ACTIONABLE_REVIEW_STATUSES


def _payload_item_is_actionable(item: dict[str, Any]) -> bool:
    review = item.get("review", {})
    if not isinstance(review, dict):
        return True

    return _review_status_is_actionable(review)


def _payload_item_is_ignored(item: dict[str, Any]) -> bool:
    review = item.get("review", {})
    return isinstance(review, dict) and _review_status_is_ignored(review)


def _read_record_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _write_record_payload(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _repair_compare_payload_summary(payload: dict[str, Any]) -> bool:
    summary = payload.setdefault("summary", {})
    if not isinstance(summary, dict):
        payload["summary"] = {}
        summary = payload["summary"]

    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else payload.get("items", [])
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), list) else []

    if not isinstance(findings, list):
        findings = []

    if not isinstance(inventory, list):
        inventory = []

    next_summary = {
        "total_items": len(inventory) if inventory else _int(summary.get("total_items")),
        "actionable": sum(
            1 for item in findings
            if isinstance(item, dict) and _payload_item_is_actionable(item)
        ),
        "ignored": sum(
            1 for item in findings
            if isinstance(item, dict) and _payload_item_is_ignored(item)
        ),
        "changed": sum(
            1 for item in inventory
            if isinstance(item, dict) and item.get("status") in {"Changed", "Different"}
        ),
        "added": sum(
            1 for item in inventory
            if isinstance(item, dict) and item.get("status") == "Added"
        ),
        "removed": sum(
            1 for item in inventory
            if isinstance(item, dict) and item.get("status") == "Removed"
        ),
        "reviewed": sum(
            1 for item in findings
            if isinstance(item, dict) and _review_has_content(item.get("review", {}))
        ),
    }
    next_risks: dict[str, int] = {}
    for item in inventory:
        if not isinstance(item, dict) or item.get("status") == "Unchanged":
            continue
        risk = str(item.get("risk") or "Policy")
        next_risks[risk] = next_risks.get(risk, 0) + 1
    next_summary["risk_counts"] = next_risks

    changed = False
    for key, value in next_summary.items():
        if isinstance(value, dict):
            if summary.get(key) != value:
                summary[key] = value
                changed = True
            continue
        if _int(summary.get(key)) != value:
            summary[key] = value
            changed = True

    return changed


def _record_from_payload(payload: dict[str, Any], record_path: Path) -> CompareLibraryRecord:
    backup_a = payload.get("backup_a", {}) if isinstance(payload.get("backup_a"), dict) else {}
    backup_b = payload.get("backup_b", {}) if isinstance(payload.get("backup_b"), dict) else {}
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    diagnostics = payload.get("diagnostics", {}) if isinstance(payload.get("diagnostics"), dict) else {}
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
        actionable=_record_actionable_count(payload, summary),
        ignored=_record_ignored_count(payload, summary),
        source_status=_source_status(backup_a_path, backup_b_path),
        risk_counts=_dict_of_ints(summary.get("risk_counts")),
        diagnostics=diagnostics,
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


def _dict_of_ints(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _int(count) for key, count in value.items()}


def _read_compare_index() -> list[CompareLibraryRecord] | None:
    index_path = COMPARE_ARCHIVE_DIR / COMPARE_INDEX_NAME
    if not index_path.exists():
        return None

    try:
        with index_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or payload.get("schema_version") != COMPARE_SCHEMA_VERSION:
        return None

    entries = payload.get("records")
    if not isinstance(entries, list):
        return None

    record_files = list(COMPARE_ARCHIVE_DIR.glob(f"*/{COMPARE_RECORD_NAME}"))
    record_dirs = {path.parent.name for path in record_files}
    index_ids = {str(entry.get("record_id", "")) for entry in entries if isinstance(entry, dict)}
    if record_dirs != index_ids:
        return None

    mtimes = {path.parent.name: _path_mtime_ns(path) for path in record_files}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        if _int(entry.get("record_mtime_ns")) != mtimes.get(str(entry.get("record_id", ""))):
            return None

    records = [
        _record_from_payload(entry, Path(str(entry.get("record_path", ""))))
        for entry in entries
        if isinstance(entry, dict)
    ]
    return sorted(records, key=lambda record: record.saved_at, reverse=True)


def _rebuild_compare_index() -> list[CompareLibraryRecord]:
    if not COMPARE_ARCHIVE_DIR.exists():
        return []

    records = _list_compare_records_from_payloads()
    payload = {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "records": [_index_payload(record) for record in records],
    }
    COMPARE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with (COMPARE_ARCHIVE_DIR / COMPARE_INDEX_NAME).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return records


def _index_payload(record: CompareLibraryRecord) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "schema_version": COMPARE_SCHEMA_VERSION,
        "title": record.title,
        "backup_a": {"title": record.backup_a_title, "path": record.backup_a_path},
        "backup_b": {"title": record.backup_b_title, "path": record.backup_b_path},
        "saved_at": record.saved_at,
        "html_path": record.html_path,
        "markdown_path": record.markdown_path,
        "summary": {
            "total_items": record.total_items,
            "changed": record.changed,
            "added": record.added,
            "removed": record.removed,
            "reviewed": record.reviewed,
            "actionable": record.actionable,
            "ignored": record.ignored,
            "risk_counts": record.risk_counts,
        },
        "diagnostics": record.diagnostics,
        "record_path": record.record_path,
        "record_mtime_ns": _path_mtime_ns(Path(record.record_path)),
    }


def _path_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _record_actionable_count(payload: dict[str, Any], summary: dict[str, Any]) -> int:
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else payload.get("items", [])

    if isinstance(findings, list) and findings:
        return sum(
            1 for item in findings
            if isinstance(item, dict) and _payload_item_is_actionable(item)
        )

    if "actionable" in summary:
        return _int(summary.get("actionable"))

    return _int(summary.get("changed")) + _int(summary.get("added")) + _int(summary.get("removed"))


def _record_ignored_count(payload: dict[str, Any], summary: dict[str, Any]) -> int:
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else payload.get("items", [])

    if isinstance(findings, list) and findings:
        return sum(
            1 for item in findings
            if isinstance(item, dict) and _payload_item_is_ignored(item)
        )

    return _int(summary.get("ignored"))
