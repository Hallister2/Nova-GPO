from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.gpo.diff_engine import compare_backups
from app.gpo.gpo_model import DiffStatus, GpoBackup, GpoDiffItem, GpoSetting
from app.gpo.gpreport_parser import GpoReportPolicy, GpoReportSummary


@dataclass(frozen=True)
class PolicyDiff:
    status: str
    key: str
    scope: str
    state_a: str
    state_b: str
    policy_a: GpoReportPolicy | None
    policy_b: GpoReportPolicy | None
    supporting_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompareSummary:
    added: int
    changed: int
    removed: int
    unchanged: int
    same_state: int
    different_state: int


def build_policy_diff(
    report_a: GpoReportSummary | None,
    report_b: GpoReportSummary | None,
) -> list[PolicyDiff]:
    policies_a = _policy_map(report_a.policies if report_a else [])
    policies_b = _policy_map(report_b.policies if report_b else [])

    all_keys = sorted(set(policies_a) | set(policies_b))
    items: list[PolicyDiff] = []

    for key in all_keys:
        policy_a = policies_a.get(key)
        policy_b = policies_b.get(key)

        if policy_a is None and policy_b is not None:
            items.append(PolicyDiff(
                status="Added",
                key=key,
                scope=policy_b.scope,
                state_a="",
                state_b=policy_b.state,
                policy_a=None,
                policy_b=policy_b,
            ))
            continue

        if policy_a is not None and policy_b is None:
            items.append(PolicyDiff(
                status="Removed",
                key=key,
                scope=policy_a.scope,
                state_a=policy_a.state,
                state_b="",
                policy_a=policy_a,
                policy_b=None,
            ))
            continue

        if policy_a is None or policy_b is None:
            continue

        status = "Unchanged"
        if policy_signature(policy_a) != policy_signature(policy_b):
            status = "Changed"

        items.append(PolicyDiff(
            status=status,
            key=key,
            scope=policy_b.scope,
            state_a=policy_a.state,
            state_b=policy_b.state,
            policy_a=policy_a,
            policy_b=policy_b,
        ))

    return _suppress_extension_duplicates(items)


def build_backup_diff(
    backup_a: GpoBackup,
    backup_b: GpoBackup,
    report_a: GpoReportSummary | None,
    report_b: GpoReportSummary | None,
) -> list[PolicyDiff]:
    items = build_policy_diff(report_a, report_b)
    items.extend(_artifact_policy_diffs(compare_backups(backup_a, backup_b), backup_a, backup_b))
    items = _attach_artifact_evidence(items)
    return sorted(items, key=lambda item: (_status_sort(item.status), item.scope, item.key))


def summarize_diffs(items: list[PolicyDiff]) -> CompareSummary:
    status_counts = {"Added": 0, "Changed": 0, "Removed": 0, "Unchanged": 0}
    same_state = 0
    different_state = 0

    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
        if states_match(item):
            same_state += 1
        else:
            different_state += 1

    return CompareSummary(
        added=status_counts["Added"],
        changed=status_counts["Changed"],
        removed=status_counts["Removed"],
        unchanged=status_counts["Unchanged"],
        same_state=same_state,
        different_state=different_state,
    )


def states_match(item: PolicyDiff) -> bool:
    return normalize_text(item.state_a) == normalize_text(item.state_b)


def policy_signature(policy: GpoReportPolicy) -> tuple[str, str, tuple[str, ...]]:
    return (
        normalize_text(policy.state),
        normalize_text(policy.policy_type),
        normalize_text(policy.category),
        normalize_multiline(policy.supported),
        normalize_multiline(policy.source),
        tuple(sorted(normalize_multiline(setting) for setting in policy.settings)),
    )


def setting_changes(item: PolicyDiff) -> list[str]:
    if item.policy_a is None and item.policy_b is not None:
        return ["Policy is missing in Backup A."]

    if item.policy_a is not None and item.policy_b is None:
        return ["Policy is missing in Backup B."]

    if item.policy_a is None or item.policy_b is None:
        return ["No comparable policy details are available."]

    changes: list[str] = []

    if normalize_text(item.policy_a.state) != normalize_text(item.policy_b.state):
        changes.append(
            f"State changed from '{item.policy_a.state or 'Not present'}' "
            f"to '{item.policy_b.state or 'Not present'}'."
        )

    if normalize_text(item.policy_a.policy_type) != normalize_text(item.policy_b.policy_type):
        changes.append(
            f"Type changed from '{item.policy_a.policy_type or 'Unknown'}' "
            f"to '{item.policy_b.policy_type or 'Unknown'}'."
        )

    if normalize_text(item.policy_a.category) != normalize_text(item.policy_b.category):
        changes.append(
            f"Category changed from '{item.policy_a.category or 'Not reported'}' "
            f"to '{item.policy_b.category or 'Not reported'}'."
        )

    settings_a = {normalize_multiline(setting): setting for setting in item.policy_a.settings}
    settings_b = {normalize_multiline(setting): setting for setting in item.policy_b.settings}

    collection_changes, collection_labels = _collection_setting_changes(
        item.policy_a.settings,
        item.policy_b.settings,
    )
    changes.extend(collection_changes)

    added_settings = [
        setting for setting in sorted(set(settings_b) - set(settings_a))
        if _setting_label(settings_b[setting]) not in collection_labels
    ]
    removed_settings = [
        setting for setting in sorted(set(settings_a) - set(settings_b))
        if _setting_label(settings_a[setting]) not in collection_labels
    ]

    for setting in added_settings:
        changes.append(f"Added configured value: {settings_b[setting]}")

    for setting in removed_settings:
        changes.append(f"Removed configured value: {settings_a[setting]}")

    if normalize_multiline(item.policy_a.supported) != normalize_multiline(item.policy_b.supported):
        changes.append("Supported-on text changed.")

    if not changes:
        return [
            "No setting-level differences were detected. The change may be metadata, formatting, or unsupported parser detail."
        ]

    return changes


def _collection_setting_changes(settings_a: list[str], settings_b: list[str]) -> tuple[list[str], set[str]]:
    changes: list[str] = []
    labels_with_collection_diff: set[str] = set()
    grouped_a = _collection_settings(settings_a)
    grouped_b = _collection_settings(settings_b)

    for label in sorted(set(grouped_a) | set(grouped_b)):
        values_a = grouped_a.get(label, [])
        values_b = grouped_b.get(label, [])
        norm_a = {normalize_multiline(value): value for value in values_a}
        norm_b = {normalize_multiline(value): value for value in values_b}

        added = [norm_b[key] for key in sorted(set(norm_b) - set(norm_a))]
        removed = [norm_a[key] for key in sorted(set(norm_a) - set(norm_b))]

        if not added and not removed:
            continue

        labels_with_collection_diff.add(label)
        for value in added:
            changes.append(f"Added configured value in Backup B: {label}: {value}")
        for value in removed:
            changes.append(f"Removed configured value from Backup B: {label}: {value}")

    return changes, labels_with_collection_diff


def _collection_settings(settings: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}

    for setting in settings:
        label, value = _split_setting(setting)
        values = _split_collection(value)
        if not label or not value:
            continue
        grouped[label] = values

    return grouped


def _setting_label(setting: str) -> str:
    return _split_setting(setting)[0]


def _split_setting(setting: str) -> tuple[str, str]:
    if ":" not in setting:
        return setting.strip(), ""

    label, value = setting.split(":", 1)
    return label.strip(), value.strip()


def _split_collection(value: str) -> list[str]:
    if not value:
        return []

    parts = [
        part.strip()
        for part in re.split(r",\s+|;\s+|\n+", value)
        if part.strip()
    ]
    return parts if len(parts) > 1 else [value.strip()]


def filter_diffs(
    items: list[PolicyDiff],
    search_text: str = "",
    status_text: str = "All Changes",
    scope_text: str = "All Scopes",
) -> list[PolicyDiff]:
    search = search_text.strip().lower()
    filtered = items

    if status_text != "All Changes":
        filtered = [item for item in filtered if item.status == status_text]
    else:
        filtered = [item for item in filtered if item.status != "Unchanged"]

    if scope_text != "All Scopes":
        filtered = [item for item in filtered if item.scope == scope_text]

    if not search:
        return filtered

    return [
        item
        for item in filtered
        if search in item.key.lower()
        or search in item.status.lower()
        or search in item.scope.lower()
        or search in policy_text(item.policy_a).lower()
        or search in policy_text(item.policy_b).lower()
    ]


def policy_text(policy: GpoReportPolicy | None) -> str:
    if policy is None:
        return "Not present"

    return (
        f"Type: {policy.policy_type or 'Unknown'}\n"
        f"State: {policy.state or 'Unknown'}\n"
        f"Category: {policy.category or 'Not reported'}\n"
        f"Source: {policy.source or 'gpreport.xml'}\n"
        f"Supported: {policy.supported or 'Not specified'}\n"
        f"Configured Values:\n{settings_text(policy.settings)}\n"
        f"Explanation:\n{policy.explain or 'No explanation text was included.'}"
    )


def settings_text(settings: list[str]) -> str:
    if not settings:
        return "No configured value details were found."

    return "\n".join(f"- {setting}" for setting in settings)


def _policy_map(policies: list[GpoReportPolicy]) -> dict[str, GpoReportPolicy]:
    mapped: dict[str, GpoReportPolicy] = {}
    counts: dict[str, int] = {}

    for policy in policies:
        key = _policy_key(policy)
        count = counts.get(key, 0)
        counts[key] = count + 1

        if count:
            key = f"{key}::duplicate-{count + 1}"

        mapped[key] = policy

    return mapped


def _artifact_policy_diffs(
    diff_items: list[GpoDiffItem],
    backup_a: GpoBackup,
    backup_b: GpoBackup,
) -> list[PolicyDiff]:
    setting_a = {setting.key: setting for setting in backup_a.settings}
    setting_b = {setting.key: setting for setting in backup_b.settings}
    results: list[PolicyDiff] = []

    for diff_item in diff_items:
        policy_a = _setting_as_policy(setting_a.get(diff_item.key), backup_a.name, diff_item.old_value)
        policy_b = _setting_as_policy(setting_b.get(diff_item.key), backup_b.name, diff_item.new_value)
        primary = policy_b or policy_a
        if primary is None:
            continue

        status = _diff_status_text(diff_item.status)

        results.append(PolicyDiff(
            status=status,
            key=f"artifact::{diff_item.key}",
            scope=primary.scope,
            state_a=policy_a.state if policy_a else "",
            state_b=policy_b.state if policy_b else "",
            policy_a=policy_a,
            policy_b=policy_b,
        ))

    return results


def _attach_artifact_evidence(items: list[PolicyDiff]) -> list[PolicyDiff]:
    """Attach duplicate raw artifact changes to their friendly policy finding.

    registry.pol and gpreport.xml can describe the same policy change from two
    angles. Keep the friendly policy row reviewable and retain the raw artifact
    as supporting evidence instead of showing a second actionable row.
    """
    result = list(items)
    remove_keys: set[str] = set()

    for artifact in [item for item in result if _is_raw_artifact(item) and item.status != "Unchanged"]:
        match_index = next(
            (
                idx for idx, candidate in enumerate(result)
                if candidate.key != artifact.key
                and _evidence_status_compatible(artifact.status, candidate.status)
                and candidate.scope == artifact.scope
                and not _is_raw_artifact(candidate)
                and _artifact_matches_policy(artifact, candidate)
            ),
            -1,
        )
        if match_index < 0:
            continue

        evidence = result[match_index].supporting_evidence + (_evidence_text(artifact),)
        result[match_index] = replace(result[match_index], supporting_evidence=evidence)
        remove_keys.add(artifact.key)

    return [item for item in result if item.key not in remove_keys]


def _is_raw_artifact(item: PolicyDiff) -> bool:
    policy = item.policy_b or item.policy_a
    return bool(policy and policy.policy_type == "Artifact")


def _evidence_status_compatible(artifact_status: str, candidate_status: str) -> bool:
    if artifact_status == candidate_status:
        return True
    return candidate_status == "Changed" and artifact_status in {"Added", "Removed"}


def _artifact_matches_policy(artifact: PolicyDiff, candidate: PolicyDiff) -> bool:
    artifact_text = normalize_multiline(policy_text(artifact.policy_a) + "\n" + policy_text(artifact.policy_b))
    candidate_text = normalize_multiline(policy_text(candidate.policy_a) + "\n" + policy_text(candidate.policy_b))
    if not artifact_text or not candidate_text:
        return False

    artifact_tokens = {
        token for token in re.split(r"[^a-z0-9_.-]+", artifact_text)
        if len(token) >= 6 and not token.startswith("software")
    }
    if not artifact_tokens:
        return False

    return any(token in candidate_text for token in artifact_tokens)


def _evidence_text(item: PolicyDiff) -> str:
    policy = item.policy_b or item.policy_a
    name = policy.name if policy else item.key
    source = policy.source if policy else "raw artifact"
    changes = "; ".join(setting_changes(item))
    return f"{name} ({source}): {changes}"


def _setting_as_policy(setting: GpoSetting | None, backup_name: str, value: str) -> GpoReportPolicy | None:
    if setting is None:
        return None

    policy_type = "Preference" if setting.category.startswith("Group Policy Preferences") else "Artifact"

    return GpoReportPolicy(
        scope=_scope_from_source(setting.source_file),
        name=setting.name or setting.key,
        state="Configured",
        category=setting.category or "Raw Artifact",
        supported="",
        explain=f"Parsed from {setting.source_file or backup_name}.",
        settings=_setting_value_lines(value or setting.value),
        policy_type=policy_type,
        source=setting.source_file,
        identity=f"artifact::{setting.key}",
    )


def _setting_value_lines(value: str) -> list[str]:
    lines = [
        part.strip()
        for part in (value or "").replace("\n", ";").split(";")
        if part.strip()
    ]
    return lines or ["No configured value details were found."]


def _scope_from_source(source_file: str) -> str:
    normalized = source_file.replace("\\", "/").lower()
    if "/user/" in f"/{normalized}/":
        return "User Configuration"
    if "/machine/" in f"/{normalized}/" or "/computer/" in f"/{normalized}/":
        return "Computer Configuration"
    return "Artifacts"


def _diff_status_text(status: DiffStatus) -> str:
    return {
        DiffStatus.ADDED: "Added",
        DiffStatus.REMOVED: "Removed",
        DiffStatus.CHANGED: "Changed",
        DiffStatus.UNCHANGED: "Unchanged",
    }[status]


def _status_sort(status: str) -> int:
    return {"Added": 0, "Changed": 1, "Removed": 2, "Unchanged": 3}.get(status, 4)


def _policy_key(policy: GpoReportPolicy) -> str:
    if policy.identity:
        return policy.identity

    return "::".join(
        normalize_multiline(part)
        for part in (policy.scope, policy.policy_type, policy.name)
        if normalize_multiline(part)
    )


def normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def normalize_multiline(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _suppress_extension_duplicates(items: list[PolicyDiff]) -> list[PolicyDiff]:
    """Drop raw Extension-type entries that are already represented by a richer Administrative Template entry.

    The gpreport.xml parser can produce two PolicyDiff items for the same underlying policy:
    one from the Extension/RegistrySettings section (policy_type='Extension') and one from
    the Administrative Template section (policy_type='Administrative Template'). When both
    exist for the same name+scope, keep only the Administrative Template version.
    """
    admx_covered: set[tuple[str, str]] = set()
    for item in items:
        policy = item.policy_b or item.policy_a
        if policy and policy.policy_type == "Administrative Template":
            admx_covered.add((item.scope, normalize_text(policy.name)))

    if not admx_covered:
        return items

    result: list[PolicyDiff] = []
    for item in items:
        policy = item.policy_b or item.policy_a
        if (
            policy
            and policy.policy_type == "Extension"
            and (item.scope, normalize_text(policy.name)) in admx_covered
        ):
            continue
        result.append(item)
    return result
