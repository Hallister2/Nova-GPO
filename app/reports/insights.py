from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.gpo.comparison_model import PolicyDiff


@dataclass(frozen=True)
class ParserDiagnostics:
    total_items: int
    actionable_items: int
    parsed_policy_items: int
    artifact_items: int
    security_items: int
    preference_items: int
    source_counts: dict[str, int]
    type_counts: dict[str, int]
    scope_counts: dict[str, int]


def risk_tag(item: PolicyDiff) -> str:
    policy = item.policy_b or item.policy_a
    text = " ".join(
        [
            item.key,
            item.scope,
            policy.name if policy else "",
            policy.category if policy else "",
            policy.policy_type if policy else "",
            policy.source if policy else "",
            " ".join(policy.settings) if policy else "",
        ]
    ).lower()

    if any(token in text for token in ("password", "lockout", "kerberos", "audit", "privilege", "user rights", "security option")):
        return "Security"
    if any(token in text for token in ("firewall", "ipsec", "defender", "applocker", "application control")):
        return "Protection"
    if any(token in text for token in ("local group", "restricted group", "administrator", "delegat", "permission", "acl")):
        return "Access"
    if any(token in text for token in ("script", "startup", "shutdown", "logon", "logoff", "powershell", ".bat", ".cmd")):
        return "Scripts"
    if "preference" in text or "group policy preferences" in text:
        return "Preference"
    if "registry.pol" in text or "registry" in text:
        return "Registry"
    if "wmi filter" in text:
        return "WMI Filter"
    if policy and policy.policy_type == "Artifact":
        return "Artifact"
    return "Policy"


def risk_counts(items: list[PolicyDiff]) -> dict[str, int]:
    counts = Counter(risk_tag(item) for item in items if item.status != "Unchanged")
    return dict(sorted(counts.items()))


def parser_diagnostics(items: list[PolicyDiff]) -> ParserDiagnostics:
    policies = [item.policy_b or item.policy_a for item in items if item.policy_b or item.policy_a]
    type_counts = Counter(policy.policy_type or "Unknown" for policy in policies)
    source_counts = Counter(policy.source or "gpreport.xml" for policy in policies)
    scope_counts = Counter(item.scope or "Unknown" for item in items)

    return ParserDiagnostics(
        total_items=len(items),
        actionable_items=sum(1 for item in items if item.status != "Unchanged"),
        parsed_policy_items=sum(1 for policy in policies if (policy.source or "").startswith("gpreport.xml")),
        artifact_items=type_counts.get("Artifact", 0),
        security_items=sum(
            1 for policy in policies
            if "security" in (policy.policy_type or "").lower()
            or "security" in (policy.category or "").lower()
        ),
        preference_items=type_counts.get("Preference", 0),
        source_counts=dict(sorted(source_counts.items())),
        type_counts=dict(sorted(type_counts.items())),
        scope_counts=dict(sorted(scope_counts.items())),
    )


def diagnostics_dict(items: list[PolicyDiff]) -> dict[str, object]:
    diagnostics = parser_diagnostics(items)
    return {
        "total_items": diagnostics.total_items,
        "actionable_items": diagnostics.actionable_items,
        "parsed_policy_items": diagnostics.parsed_policy_items,
        "artifact_items": diagnostics.artifact_items,
        "security_items": diagnostics.security_items,
        "preference_items": diagnostics.preference_items,
        "source_counts": diagnostics.source_counts,
        "type_counts": diagnostics.type_counts,
        "scope_counts": diagnostics.scope_counts,
    }
