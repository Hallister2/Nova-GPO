from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path

from app import __version__
from app.gpo.comparison_model import PolicyDiff, setting_changes
from app.reports.insights import diagnostics_dict, parser_diagnostics, risk_counts, risk_tag


ACTIONABLE_STATUSES = {"Added", "Changed", "Different", "Removed"}
NON_ACTIONABLE_REVIEW_STATUSES = {"No Action Required"}


def actionable_items(diff_items: list[PolicyDiff]) -> list[PolicyDiff]:
    return [item for item in diff_items if item.status in ACTIONABLE_STATUSES]


def csv_report(
    title_a: str,
    title_b: str,
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
    profile: str = "full",
) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    if profile == "executive":
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Backup A", title_a])
        writer.writerow(["Backup B", title_b])
        summary = _summary_counts(diff_items, review_notes)
        writer.writerow(["Total compared", summary["total"]])
        writer.writerow(["Actionable findings", summary["actionable"]])
        writer.writerow(["Ignored", summary["ignored"]])
        writer.writerow(["Reviewed", summary["reviewed"]])
        writer.writerow(["Pending review", summary["unreviewed"]])
        writer.writerow(["Different", summary["changed"]])
        writer.writerow(["Missing in A", summary["missing_in_a"]])
        writer.writerow(["Missing in B", summary["missing_in_b"]])
        for label, value in risk_counts(diff_items).items():
            writer.writerow([f"{label} impact", value])
        return output.getvalue()

    writer.writerow(["Policy Name", "Status", "Risk", "Scope", "Type", "Source", "Changes"])
    for item in _items_for_profile(diff_items, profile):
        name = item.policy_b.name if item.policy_b else (item.policy_a.name if item.policy_a else "Unknown")
        writer.writerow([
            name,
            _status_label(item.status),
            risk_tag(item),
            item.scope,
            _policy_type(item),
            _policy_source(item),
            "; ".join(setting_changes(item)),
        ])
    return output.getvalue()


def executive_summary(
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
) -> str:
    summary = _summary_counts(diff_items, review_notes)

    lines = [
        f"Nova GPO compared {summary['total']} total items.",
        f"{summary['actionable']} actionable finding(s) need review.",
        f"{summary['ignored']} finding(s) were marked no action required.",
        f"{summary['reviewed']} actionable finding(s) have review status updates.",
        f"{summary['unreviewed']} actionable finding(s) are still pending review.",
        f"{summary['changed']} policies changed between the selected backups.",
        f"{summary['missing_in_a']} policies are missing in Backup A.",
        f"{summary['missing_in_b']} policies are missing in Backup B.",
    ]

    return "\n".join(lines)


def markdown_report(
    title_a: str,
    title_b: str,
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
    profile: str = "full",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notes = review_notes or {}

    report: list[str] = []

    report.append("# Nova GPO Comparison Report")
    report.append("")
    report.append(f"Generated: {now}")
    report.append(f"App Version: {__version__}")
    report.append(f"Profile: {profile}")
    report.append("")
    report.append(f"Backup A: {title_a}")
    report.append(f"Backup B: {title_b}")
    report.append("")
    report.append("## Executive Summary")
    report.append("")
    report.append(executive_summary(diff_items, notes))
    report.append("")
    report.extend(_markdown_insights(diff_items))

    if profile == "executive":
        return "\n".join(report)

    report_items = _items_for_profile(diff_items, profile)
    section_title = "Raw Inventory" if profile == "raw" else "Actionable Findings"
    report.append(f"## {section_title}")
    report.append("")

    if not report_items:
        report.append("No actionable differences were detected.")
        report.append("")
        return "\n".join(report)

    for item in report_items:
        report.append(f"### {item.policy_b.name if item.policy_b else item.policy_a.name}")
        report.append("")
        report.append(f"- Status: {_status_label(item.status)}")
        report.append(f"- Risk: {risk_tag(item)}")
        report.append(f"- Scope: {item.scope}")
        report.append(f"- Type: {_policy_type(item)}")
        report.append(f"- Source: {_policy_source(item)}")
        review = notes.get(item.key, {})
        review_status = review.get("status", "Pending Review")
        report.append(f"- Review Status: {review_status}")
        if review.get("priority", "Normal") != "Normal":
            report.append(f"- Priority: {review['priority']}")
        for label, key in [
            ("Owner", "owner"),
            ("Ticket", "ticket"),
            ("Tags", "tags"),
        ]:
            value = review.get(key, "").strip()
            if value:
                report.append(f"- {label}: {value}")
        if review.get("notes", "").strip():
            report.append(f"- Notes: {review['notes'].strip()}")
        report.append("")
        report.append("### Detected Changes")
        report.append("")

        for change in setting_changes(item):
            report.append(f"- {change}")

        if item.supporting_evidence:
            report.append("")
            report.append("### Supporting Evidence")
            report.append("")
            for evidence in item.supporting_evidence:
                report.append(f"- {evidence}")

        report.append("")

    return "\n".join(report)


def html_report(
    title_a: str,
    title_b: str,
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
    profile: str = "full",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notes = review_notes or {}

    summary = _summary_counts(diff_items, notes)
    risks = risk_counts(diff_items)
    diagnostics = parser_diagnostics(diff_items)

    summary_rows = "".join(
        f"<tr><td>{escape(label)}</td><td><strong>{escape(str(value))}</strong></td></tr>"
        for label, value in [
            ("Total compared", summary["total"]),
            ("Actionable findings", summary["actionable"]),
            ("Ignored", summary["ignored"]),
            ("Reviewed", summary["reviewed"]),
            ("Pending review", summary["unreviewed"]),
            ("Different", summary["changed"]),
            ("Missing in A", summary["missing_in_a"]),
            ("Missing in B", summary["missing_in_b"]),
            ("Security-impacting", risks.get("Security", 0)),
            ("Protection-impacting", risks.get("Protection", 0)),
        ]
    )

    diagnostics_rows = "".join(
        f"<tr><td>{escape(label)}</td><td><strong>{escape(str(value))}</strong></td></tr>"
        for label, value in [
            ("Parsed policy items", diagnostics.parsed_policy_items),
            ("Raw artifact items", diagnostics.artifact_items),
            ("Security items", diagnostics.security_items),
            ("Preference items", diagnostics.preference_items),
        ]
    )

    report_items = _items_for_profile(diff_items, profile)
    policy_sections = "" if profile == "executive" else "".join(_html_policy_section(item, notes) for item in report_items)
    if profile != "executive" and not policy_sections:
        policy_sections = '<div class="policy-card"><div class="policy-body">No actionable differences were detected.</div></div>'
    policy_heading = "" if profile == "executive" else "<h2>{}</h2>".format(
        "Raw Inventory" if profile == "raw" else "Actionable Findings"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Nova GPO Comparison Report</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#101112;color:#f4f6f8;font-family:"Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.6;padding:40px 48px}}
    h1{{font-size:24px;font-weight:600;margin-bottom:4px}}
    h2{{font-size:16px;font-weight:600;color:#c0c3c7;margin:28px 0 10px}}
    h3{{font-size:14px;font-weight:600;margin-bottom:6px}}
    .muted{{color:#9aa0a6;font-size:13px}}
    .meta{{display:flex;gap:32px;margin:16px 0 28px;padding:16px 20px;background:#18191b;border-radius:8px;border:1px solid rgba(255,255,255,.07)}}
    .meta-item span{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#9aa0a6;margin-bottom:2px}}
    table{{width:100%;border-collapse:collapse}}
    th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid rgba(255,255,255,.07)}}
    th{{background:#202123;color:#c0c3c7;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
    tr:last-child td{{border-bottom:none}}
    .summary-table{{max-width:360px;background:#18191b;border-radius:8px;border:1px solid rgba(255,255,255,.07);overflow:hidden}}
    .policy-card{{background:#18191b;border:1px solid rgba(255,255,255,.07);border-radius:8px;margin-bottom:18px;overflow:hidden}}
    .policy-header{{display:flex;align-items:center;gap:10px;padding:12px 16px;background:#202123;border-bottom:1px solid rgba(255,255,255,.07)}}
    .policy-name{{font-weight:600;flex:1;font-size:14px}}
    .policy-body{{padding:16px}}
    .attrs{{display:flex;flex-wrap:wrap;gap:6px 24px;margin-bottom:10px}}
    .attr{{font-size:12px;color:#9aa0a6}}.attr strong{{color:#c0c3c7}}
    .status-strip{{display:grid;grid-template-columns:1fr 1fr;margin-bottom:14px;border:1px solid rgba(255,255,255,.07);overflow:hidden;border-radius:6px}}
    .strip-cell{{padding:9px 11px;background:#101112;border-right:1px solid rgba(255,255,255,.07)}}
    .strip-cell:last-child{{border-right:0}}
    .strip-cell span{{display:block;color:#9aa0a6;font-size:11px;font-weight:700;text-transform:uppercase;margin-bottom:2px}}
    .delta{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:3px solid #ff8a1f;padding:10px 12px;margin:6px 0 14px;border-radius:0 4px 4px 0}}
    .compare-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:6px}}
    .side-card{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:4px solid #9aa0a6;border-radius:6px;padding:10px 12px}}
    .side-card.b{{border-left-color:#ff8a1f}}
    .side-title{{color:#9aa0a6;font-weight:700;margin-bottom:8px}}
    .section-title{{color:#ff8a1f;margin:14px 0 6px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}}
    ul{{padding-left:18px;margin-top:4px}}
    li{{font-size:13px;color:#d0d4d8;margin-bottom:3px}}
    .badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase}}
    .badge-status-changed{{background:rgba(255,165,0,.15);color:#e8a040;border:1px solid rgba(255,165,0,.3)}}
    .badge-status-added{{background:rgba(100,180,100,.15);color:#8acf8a;border:1px solid rgba(100,180,100,.3)}}
    .badge-status-removed{{background:rgba(220,53,69,.2);color:#f07070;border:1px solid rgba(220,53,69,.35)}}
    .badge-status-unchanged{{background:rgba(255,255,255,.07);color:#9aa0a6;border:1px solid rgba(255,255,255,.12)}}
    .review-note{{margin-top:12px;padding:9px 12px;background:rgba(255,165,0,.08);border-left:3px solid #e8804080;border-radius:0 4px 4px 0;font-size:13px}}
    .evidence{{margin-top:12px;padding:9px 12px;background:#101112;border:1px solid rgba(255,255,255,.07);border-radius:6px;color:#c0c3c7;font-size:12px}}
    @media print{{body{{background:#fff;color:#111;padding:18px}}.policy-card,.meta,.summary-table,.side-card,.delta{{background:#fff;color:#111;border-color:#ddd}}.muted,.attr,.side-title,.strip-cell span{{color:#555}}}}
    .footer{{margin-top:48px;padding-top:16px;border-top:1px solid rgba(255,255,255,.07);color:#9aa0a6;font-size:12px}}
  </style>
</head>
<body>
  <h1>Nova GPO Comparison Report</h1>
  <div class="meta">
    <div class="meta-item"><span>Generated</span>{escape(now)}</div>
    <div class="meta-item"><span>Nova GPO</span>{escape(__version__)}</div>
    <div class="meta-item"><span>Profile</span>{escape(profile)}</div>
    <div class="meta-item"><span>Backup A</span>{escape(title_a)}</div>
    <div class="meta-item"><span>Backup B</span>{escape(title_b)}</div>
  </div>

  <h2>Executive Summary</h2>
  <table class="summary-table">
    <tbody>{summary_rows}</tbody>
  </table>

  <h2>Parser Diagnostics</h2>
  <table class="summary-table">
    <tbody>{diagnostics_rows}</tbody>
  </table>

  {policy_heading}
  {policy_sections}

  <div class="footer">Nova GPO {escape(__version__)} &mdash; Hallister Labs &mdash; Generated {escape(now)}</div>
</body>
</html>
"""


def _html_policy_section(item: PolicyDiff, notes: dict[str, dict[str, str]]) -> str:
    name = item.policy_b.name if item.policy_b else (item.policy_a.name if item.policy_a else "Unknown")
    review = notes.get(item.key, {})
    review_status = review.get("status", "Pending Review")
    changes = setting_changes(item)

    status_cls = f"badge-status-{item.status.lower()}"
    status_label = _status_label(item.status)

    attrs = [
        ("Scope", item.scope),
        ("Risk", risk_tag(item)),
        ("Type", _policy_type(item)),
        ("Source", _policy_source(item)),
        ("State A", item.state_a or "—"),
        ("State B", item.state_b or "—"),
        ("Review Status", review_status),
    ]
    if review.get("priority", "Normal") != "Normal":
        attrs.append(("Priority", review["priority"]))

    attr_html = "".join(f'<div class="attr"><strong>{escape(k)}:</strong> {escape(v)}</div>' for k, v in attrs)
    changes_html = "".join(f"<li>{escape(c)}</li>" for c in changes)

    note_html = _review_html(review)
    evidence_html = _evidence_html(item.supporting_evidence)

    return f"""
<div class="policy-card">
  <div class="policy-header">
    <span class="policy-name">{escape(name)}</span>
    <span class="badge {escape(status_cls)}">{escape(status_label)}</span>
  </div>
  <div class="policy-body">
    <div class="status-strip">
      <div class="strip-cell"><span>Status</span><strong>{escape(status_label)}</strong></div>
      <div class="strip-cell"><span>State</span><strong>{escape(item.state_a or 'Not present')} &rarr; {escape(item.state_b or 'Not present')}</strong></div>
    </div>
    <div class="attrs">{attr_html}</div>
    <p class="section-title">Actual Delta</p>
    <div class="delta">
      <ul>{changes_html}</ul>
    </div>
    <p class="section-title">Compared Values</p>
    <div class="compare-grid">
      {_side_card_html("Backup A", item.policy_a, "Not present in Backup A.", "a")}
      {_side_card_html("Backup B", item.policy_b, "Not present in Backup B.", "b")}
    </div>
    {evidence_html}
    {note_html}
  </div>
</div>
"""


def _policy_type(item: PolicyDiff) -> str:
    if item.policy_b:
        return item.policy_b.policy_type
    if item.policy_a:
        return item.policy_a.policy_type
    return "Unknown"


def _status_label(status: str) -> str:
    return {
        "Added": "Missing in A",
        "Removed": "Missing in B",
        "Unchanged": "Same",
    }.get(status, status)


def _side_card_html(title: str, policy, missing_text: str, side: str) -> str:
    if policy is None:
        body = f"<p>{escape(missing_text)}</p>"
    else:
        settings = policy.settings or ["No configured value details were found."]
        settings_html = "".join(f"<li>{escape(setting)}</li>" for setting in settings)
        body = (
            f'<div class="attr"><strong>State:</strong> {escape(policy.state or "Not reported")}</div>'
            f'<div class="attr"><strong>Category:</strong> {escape(policy.category or "Not reported")}</div>'
            f'<div class="attr"><strong>Source:</strong> {escape(policy.source or "gpreport.xml")}</div>'
            '<div class="attr" style="margin-top:8px"><strong>Configured values</strong></div>'
            f"<ul>{settings_html}</ul>"
        )

    side_class = "side-card b" if side == "b" else "side-card"
    return f'<div class="{side_class}"><div class="side-title">{escape(title)}</div>{body}</div>'


def _review_html(review: dict[str, str]) -> str:
    rows: list[str] = []
    if review.get("priority", "Normal") != "Normal":
        rows.append(f"<p><strong>Priority:</strong> {escape(review['priority'])}</p>")
    for label, key in [
        ("Owner", "owner"),
        ("Ticket", "ticket"),
        ("Tags", "tags"),
    ]:
        value = review.get(key, "").strip()
        if value:
            rows.append(f"<p><strong>{label}:</strong> {escape(value)}</p>")
    notes_text = review.get("notes", "").strip()
    if notes_text:
        rows.append(f"<p><strong>Notes:</strong> {escape(notes_text)}</p>")
    updated = review.get("updated_at", "").strip()
    if updated:
        rows.append(f"<p><strong>Last updated:</strong> {escape(updated)}</p>")

    if not rows:
        return ""

    body = "".join(rows)
    return f'<div class="review-note">{body}</div>'


def _evidence_html(evidence: tuple[str, ...]) -> str:
    if not evidence:
        return ""
    rows = "".join(f"<li>{escape(item)}</li>" for item in evidence)
    return f'<div class="evidence"><strong>Supporting Evidence</strong><ul>{rows}</ul></div>'


def _policy_source(item: PolicyDiff) -> str:
    if item.policy_b:
        return item.policy_b.source
    if item.policy_a:
        return item.policy_a.source
    return "gpreport.xml"


def json_report(
    title_a: str,
    title_b: str,
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
) -> str:
    notes = review_notes or {}
    now = datetime.now().isoformat(timespec="seconds")

    summary = _summary_counts(diff_items, notes)

    def _policy_dict(policy) -> dict | None:
        if policy is None:
            return None
        return {
            "name": policy.name,
            "scope": policy.scope,
            "state": policy.state,
            "category": policy.category,
            "policy_type": policy.policy_type,
            "source": policy.source,
            "supported": policy.supported,
            "settings": policy.settings,
            "explain": policy.explain,
        }

    records = []
    for item in diff_items:
        name = item.policy_b.name if item.policy_b else (item.policy_a.name if item.policy_a else "Unknown")
        records.append({
            "key": item.key,
            "name": name,
            "status": _status_label(item.status),
            "scope": item.scope,
            "state_a": item.state_a,
            "state_b": item.state_b,
            "changes": setting_changes(item),
            "risk": risk_tag(item),
            "supporting_evidence": list(item.supporting_evidence),
            "policy_a": _policy_dict(item.policy_a),
            "policy_b": _policy_dict(item.policy_b),
            "review": notes.get(item.key, {}),
        })

    payload = {
        "generated": now,
        "app_version": __version__,
        "backup_a": title_a,
        "backup_b": title_b,
        "summary": {
            "total": summary["total"],
            "actionable": summary["actionable"],
            "ignored": summary["ignored"],
            "reviewed": summary["reviewed"],
            "unreviewed": summary["unreviewed"],
            "changed": summary["changed"],
            "missing_in_a": summary["missing_in_a"],
            "missing_in_b": summary["missing_in_b"],
            "risk_counts": risk_counts(diff_items),
        },
        "diagnostics": diagnostics_dict(diff_items),
        "items": records,
        "findings": [record for record, item in zip(records, diff_items) if item.status in ACTIONABLE_STATUSES],
        "inventory": records,
    }

    return json.dumps(payload, indent=2, ensure_ascii=False)


def write_report_bundle(
    path: str,
    title_a: str,
    title_b: str,
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
) -> None:
    target = Path(path)
    notes = review_notes or {}
    stem = target.stem or "nova-gpo-comparison"
    artifacts = {
        f"{stem}.html": html_report(title_a, title_b, diff_items, notes),
        f"{stem}.md": markdown_report(title_a, title_b, diff_items, notes),
        f"{stem}.json": json_report(title_a, title_b, diff_items, notes),
        f"{stem}-summary.csv": csv_report(title_a, title_b, diff_items, notes, profile="executive"),
    }

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, body in artifacts.items():
            bundle.writestr(name, body)


def _markdown_insights(diff_items: list[PolicyDiff]) -> list[str]:
    diagnostics = parser_diagnostics(diff_items)
    risks = risk_counts(diff_items)
    lines = ["## Risk Summary", ""]
    if risks:
        for label, value in risks.items():
            lines.append(f"- {label}: {value}")
    else:
        lines.append("- No actionable risk categories detected.")
    lines.extend([
        "",
        "## Parser Diagnostics",
        "",
        f"- Parsed policy items: {diagnostics.parsed_policy_items}",
        f"- Raw artifact items: {diagnostics.artifact_items}",
        f"- Security items: {diagnostics.security_items}",
        f"- Preference items: {diagnostics.preference_items}",
        "",
    ])
    return lines


def _items_for_profile(diff_items: list[PolicyDiff], profile: str) -> list[PolicyDiff]:
    if profile == "raw":
        return diff_items
    return actionable_items(diff_items)


def _summary_counts(
    diff_items: list[PolicyDiff],
    review_notes: dict[str, dict[str, str]] | None = None,
) -> dict[str, int]:
    notes = review_notes or {}
    changed = sum(1 for item in diff_items if item.status in {"Changed", "Different"})
    added = sum(1 for item in diff_items if item.status == "Added")
    removed = sum(1 for item in diff_items if item.status == "Removed")
    ignored = sum(
        1 for item in actionable_items(diff_items)
        if notes.get(item.key, {}).get("status", "Pending Review") in NON_ACTIONABLE_REVIEW_STATUSES
    )
    reviewed = sum(
        1 for item in actionable_items(diff_items)
        if notes.get(item.key, {}).get("status", "Pending Review") != "Pending Review"
    )
    actionable = changed + added + removed - ignored
    return {
        "total": len(diff_items),
        "actionable": actionable,
        "ignored": ignored,
        "reviewed": reviewed,
        "unreviewed": max(0, actionable - reviewed),
        "changed": changed,
        "missing_in_a": added,
        "missing_in_b": removed,
    }
