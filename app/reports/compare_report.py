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
from app.gpo.ilt_parser import GPP_COMMON_HEADER, GPP_PROPERTIES_HEADER, ILT_HEADER
from app.review_status import REVIEW_STATUSES, normalize_review_status
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

    writer.writerow([
        "Policy Name",
        "Status",
        "Risk",
        "Scope",
        "Type",
        "Source",
        "State A",
        "State B",
        "Review Status",
        "Priority",
        "Owner",
        "Ticket",
        "Tags",
        "Changes",
        "Recommended Actions",
        "Supporting Evidence",
    ])
    for item in _items_for_profile(diff_items, profile):
        name = item.policy_b.name if item.policy_b else (item.policy_a.name if item.policy_a else "Unknown")
        review = (review_notes or {}).get(item.key, {})
        actions = [
            f"{action} {target}: {detail}"
            for action, target, detail in remediation_steps(item)
        ]
        writer.writerow([
            name,
            _status_label(item.status),
            risk_tag(item),
            item.scope,
            _policy_type(item),
            _policy_source(item),
            item.state_a,
            item.state_b,
            normalize_review_status(review.get("status", "Pending Review")),
            review.get("priority", "Normal"),
            review.get("owner", ""),
            review.get("ticket", ""),
            review.get("tags", ""),
            "; ".join(setting_changes(item)),
            "; ".join(actions),
            "; ".join(item.supporting_evidence),
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
        review_status = normalize_review_status(review.get("status", "Pending Review"))
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
        report.append("#### Review Summary")
        report.append("")
        for label, value in _markdown_review_summary(item, review):
            report.append(f"- {label}: {value}")
        report.append("")
        report.append("#### Detected Changes")
        report.append("")

        for change in setting_changes(item):
            report.append(f"- {change}")

        remediation = remediation_steps(item)
        if remediation:
            report.append("")
            report.append("#### Remediation")
            report.append("")
            for action, target, detail in remediation:
                report.append(f"- **{action} {target}:** {detail}")

        report.append("")
        report.append("#### Compared Values")
        report.append("")
        report.extend(_markdown_policy_values("Backup A", item.policy_a))
        report.append("")
        report.extend(_markdown_policy_values("Backup B", item.policy_b))

        if item.supporting_evidence:
            report.append("")
            report.append("#### Supporting Evidence")
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
    report_items = _items_for_profile(diff_items, profile)
    verdict = _executive_verdict(summary, risks, report_items, notes)
    status_overview = "" if profile == "executive" else _html_status_overview(report_items, notes)

    summary_items = "".join(
        f'<div class="summary-chip"><strong>{escape(str(value))}</strong><span>{escape(label)}</span></div>'
        for label, value in [
            ("Compared", summary["total"]),
            ("Actionable", summary["actionable"]),
            ("Reviewed", summary["reviewed"]),
            ("Pending", summary["unreviewed"]),
            ("Different", summary["changed"]),
            ("Missing in A", summary["missing_in_a"]),
            ("Missing in B", summary["missing_in_b"]),
            ("Security", risks.get("Security", 0)),
            ("Protection", risks.get("Protection", 0)),
            ("Ignored", summary["ignored"]),
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

    policy_sections = "" if profile == "executive" else _html_policy_sections(report_items, notes, title_a, title_b)
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
    h1{{font-size:24px;font-weight:700;margin-bottom:4px}}
    h2{{font-size:16px;font-weight:600;color:#c0c3c7;margin:28px 0 10px}}
    h3{{font-size:14px;font-weight:600;margin-bottom:6px}}
    .muted{{color:#9aa0a6;font-size:13px}}
    .cover{{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:start;padding:20px 22px;background:linear-gradient(135deg,#1f2023 0%,#18191b 64%,#23190f 100%);border:1px solid rgba(255,255,255,.08);border-radius:10px;box-shadow:0 16px 40px rgba(0,0,0,.22)}}
    .brand-row{{display:flex;align-items:center;gap:12px;margin-bottom:10px}}
    .brand-mark{{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:8px;background:#101112;border:1px solid rgba(255,138,31,.35);color:#ff8a1f;font-weight:900;letter-spacing:.04em}}
    .brand-text{{display:flex;flex-direction:column;line-height:1.1}}
    .brand-text strong{{font-size:18px;letter-spacing:.12em}}
    .brand-text span{{font-size:11px;color:#ff8a1f;font-weight:800;letter-spacing:.12em}}
    .cover-actions{{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}}
    .meta{{display:flex;flex-wrap:wrap;gap:12px 22px;margin-top:14px}}
    .meta-item span{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#9aa0a6;margin-bottom:2px}}
    table{{width:100%;border-collapse:collapse}}
    th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid rgba(255,255,255,.07)}}
    th{{background:#202123;color:#c0c3c7;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
    tr:last-child td{{border-bottom:none}}
    .summary-table{{max-width:360px;background:#18191b;border-radius:8px;border:1px solid rgba(255,255,255,.07);overflow:hidden}}
    .report-summary-bar{{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 10px;padding:10px;background:#18191b;border:1px solid rgba(255,255,255,.07);border-radius:8px}}
    .summary-chip{{display:flex;align-items:baseline;gap:6px;min-height:34px;padding:6px 10px;background:#101112;border:1px solid rgba(255,255,255,.07);border-radius:6px}}
    .summary-chip strong{{font-size:16px;color:#f4f6f8;line-height:1}}
    .summary-chip span{{color:#9aa0a6;font-size:12px;font-weight:700;white-space:nowrap}}
    .diagnostics-details{{margin:0 0 12px;color:#c0c3c7}}
    .diagnostics-details summary{{cursor:pointer;display:inline-flex;align-items:center;gap:6px;color:#9aa0a6;font-size:12px;font-weight:700}}
    .diagnostics-details summary::-webkit-details-marker{{display:none}}
    .diagnostics-details summary::before{{content:"+";display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:4px;background:#18191b;color:#ff8a1f}}
    .diagnostics-details[open] summary::before{{content:"-"}}
    .diagnostics-details .summary-table{{margin-top:8px}}
    .verdict{{margin:14px 0 0;padding:12px 14px;background:rgba(130,182,255,.08);border:1px solid rgba(130,182,255,.22);border-left:4px solid #82b6ff;border-radius:0 8px 8px 0;color:#d8e7ff;font-weight:700}}
    .status-overview{{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 12px}}
    .status-pill{{display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border:1px solid rgba(255,255,255,.1);border-radius:999px;background:#18191b;color:#d0d4d8;font-size:12px;font-weight:800;text-decoration:none}}
    .status-pill .count{{color:#ff8a1f}}
    .report-toolbar{{position:sticky;top:0;z-index:10;display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 18px;padding:10px 0;background:#101112;border-bottom:1px solid rgba(255,255,255,.07)}}
    .status-nav{{display:flex;flex-wrap:wrap;gap:8px;flex:1}}
    .status-link{{display:inline-flex;gap:6px;align-items:center;padding:6px 10px;background:#18191b;border:1px solid rgba(255,255,255,.1);border-radius:6px;color:#d0d4d8;text-decoration:none;font-size:12px;font-weight:700}}
    .status-link:hover{{border-color:#ff8a1f;color:#fff}}
    .status-count{{color:#ff8a1f}}
    .toolbar-actions{{display:flex;gap:8px;margin-left:auto}}
    .report-button{{appearance:none;border:1px solid rgba(255,255,255,.12);border-radius:6px;background:#18191b;color:#f4f6f8;padding:6px 10px;font:700 12px "Segoe UI",Arial,sans-serif;cursor:pointer}}
    .report-button:hover{{border-color:#ff8a1f}}
    .status-section{{margin:20px 0 28px;scroll-margin-top:20px}}
    .status-heading{{display:flex;align-items:center;gap:10px;padding:9px 0 8px;border-bottom:1px solid rgba(255,255,255,.08);margin-bottom:12px}}
    .status-heading h2{{margin:0;flex:1}}
    .policy-card{{background:#18191b;border:1px solid rgba(255,255,255,.07);border-radius:8px;margin-bottom:18px;overflow:hidden}}
    details.policy-card summary{{cursor:pointer;list-style:none}}
    details.policy-card summary::-webkit-details-marker{{display:none}}
    details.policy-card summary::before{{content:"+";display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:4px;background:#101112;color:#ff8a1f;font-weight:800;margin-right:2px}}
    details.policy-card[open] summary::before{{content:"-"}}
    .policy-header{{display:flex;align-items:center;gap:10px;padding:12px 16px;background:#202123;border-bottom:1px solid rgba(255,255,255,.07)}}
    .policy-heading{{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}}
    .policy-name{{font-weight:600;font-size:14px}}
    .policy-summary{{display:flex;flex-wrap:wrap;gap:6px 16px;color:#9aa0a6;font-size:12px}}
    .policy-summary strong{{color:#d0d4d8}}
    .policy-body{{padding:16px}}
    .finding-tools{{display:flex;justify-content:flex-end;gap:8px;margin-bottom:10px}}
    .review-decision{{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;margin-bottom:14px}}
    .decision-cell{{background:#101112;border:1px solid rgba(255,255,255,.07);border-radius:6px;padding:8px 10px}}
    .decision-cell span{{display:block;color:#9aa0a6;font-size:10px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;margin-bottom:2px}}
    .decision-cell strong{{font-size:12px;color:#f4f6f8}}
    .attrs{{display:flex;flex-wrap:wrap;gap:6px 24px;margin-bottom:10px}}
    .attr{{font-size:12px;color:#9aa0a6}}.attr strong{{color:#c0c3c7}}
    .status-strip{{display:grid;grid-template-columns:1fr 1fr;margin-bottom:14px;border:1px solid rgba(255,255,255,.07);overflow:hidden;border-radius:6px}}
    .strip-cell{{padding:9px 11px;background:#101112;border-right:1px solid rgba(255,255,255,.07)}}
    .strip-cell:last-child{{border-right:0}}
    .strip-cell span{{display:block;color:#9aa0a6;font-size:11px;font-weight:700;text-transform:uppercase;margin-bottom:2px}}
    .delta{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:3px solid #ff8a1f;padding:10px 12px;margin:6px 0 14px;border-radius:0 4px 4px 0}}
    .remediation{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:3px solid #82b6ff;padding:10px 12px;margin:6px 0 14px;border-radius:0 4px 4px 0}}
    .remediation td{{font-size:12px;vertical-align:top}}
    .remediation-action{{width:110px;color:#82b6ff;font-weight:800;text-transform:uppercase;letter-spacing:.03em}}
    .remediation-target{{width:100px;color:#c0c3c7;font-weight:700}}
    .action-plan{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:4px solid #82b6ff;border-radius:6px;padding:12px;margin:6px 0 16px}}
    .action-title{{font-size:14px;font-weight:800;color:#f4f6f8;margin-bottom:4px}}
    .action-lead{{color:#c0c3c7;font-size:13px;margin-bottom:10px}}
    .action-fields{{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;margin:8px 0 12px}}
    .action-field{{padding:8px;background:#18191b;border:1px solid rgba(255,255,255,.07);border-radius:6px}}
    .action-field span{{display:block;color:#9aa0a6;font-size:10px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;margin-bottom:2px}}
    .action-field strong{{font-size:12px;color:#f4f6f8}}
    .direction-note{{background:rgba(255,138,31,.08);border:1px solid rgba(255,138,31,.24);border-left:3px solid #ff8a1f;border-radius:0 6px 6px 0;padding:10px 12px;margin:6px 0 16px;color:#d0d4d8;font-size:13px}}
    .action-stack{{display:grid;grid-template-columns:1fr;gap:12px}}
    .compare-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:6px}}
    .side-card{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:4px solid #9aa0a6;border-radius:6px;padding:10px 12px}}
    .side-card.b{{border-left-color:#ff8a1f}}
    .side-title{{color:#9aa0a6;font-weight:700;margin-bottom:8px}}
    .section-title{{color:#ff8a1f;margin:14px 0 6px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}}
    .kv{{width:100%;border-collapse:collapse;background:#101112;border:1px solid rgba(255,255,255,.07);margin:4px 0 10px}}
    .kv td{{padding:4px 7px;border-bottom:1px solid rgba(255,255,255,.05);font-size:12px;vertical-align:top}}
    .kv tr:last-child td{{border-bottom:0}}
    .kv tr.kv-diff td{{background:rgba(255,138,31,.11);border-bottom-color:rgba(255,138,31,.18)}}
    .kv-key{{width:34%;color:#9aa0a6;font-weight:700;white-space:nowrap}}
    .kv-value{{color:#d0d4d8}}
    .ilt-card{{background:#101112;border:1px solid rgba(255,255,255,.07);border-left:3px solid #82b6ff;border-radius:4px;padding:8px 10px;margin:6px 0 10px}}
    .ilt-card.diff{{border-left-color:#ff8a1f;background:rgba(255,138,31,.08)}}
    .ilt-title{{color:#82b6ff;font-size:12px;font-weight:800;margin-bottom:5px}}
    details.targeting-details{{margin-top:8px}}
    details.targeting-details summary{{cursor:pointer;color:#ff8a1f;font-size:12px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;margin:14px 0 6px}}
    details.targeting-details summary::-webkit-details-marker{{display:none}}
    details.targeting-details summary::before{{content:"+";display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:4px;background:#18191b;color:#ff8a1f;margin-right:6px}}
    details.targeting-details[open] summary::before{{content:"-"}}
    ul{{padding-left:18px;margin-top:4px}}
    li{{font-size:13px;color:#d0d4d8;margin-bottom:3px}}
    .badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase}}
    .badge-status-changed{{background:rgba(255,165,0,.15);color:#e8a040;border:1px solid rgba(255,165,0,.3)}}
    .badge-status-different{{background:rgba(255,165,0,.15);color:#e8a040;border:1px solid rgba(255,165,0,.3)}}
    .badge-status-added{{background:rgba(130,182,255,.15);color:#82b6ff;border:1px solid rgba(130,182,255,.35)}}
    .badge-status-removed{{background:rgba(220,53,69,.2);color:#f07070;border:1px solid rgba(220,53,69,.35)}}
    .badge-status-unchanged{{background:rgba(255,255,255,.07);color:#9aa0a6;border:1px solid rgba(255,255,255,.12)}}
    .review-note{{margin-top:12px;padding:9px 12px;background:rgba(255,165,0,.08);border-left:3px solid #e8804080;border-radius:0 4px 4px 0;font-size:13px}}
    .evidence{{margin-top:12px;padding:9px 12px;background:#101112;border:1px solid rgba(255,255,255,.07);border-radius:6px;color:#c0c3c7;font-size:12px}}
    .appendix{{margin-top:34px;padding-top:14px;border-top:1px solid rgba(255,255,255,.08)}}
    @media (max-width:900px){{body{{padding:24px 18px}}.cover{{grid-template-columns:1fr}}.cover-actions{{justify-content:flex-start}}.compare-grid,.action-fields,.review-decision{{grid-template-columns:1fr}}.report-toolbar{{position:static}}}}
    @media print{{body{{background:#fff;color:#111;padding:18px}}.cover,.report-toolbar{{position:static;background:#fff;box-shadow:none}}.policy-card,.meta,.summary-table,.side-card,.delta,.action-plan,.decision-cell{{background:#fff;color:#111;border-color:#ddd}}.muted,.attr,.side-title,.strip-cell span{{color:#555}}.toolbar-actions,.cover-actions,.finding-tools{{display:none}}}}
    .footer{{margin-top:48px;padding-top:16px;border-top:1px solid rgba(255,255,255,.07);color:#9aa0a6;font-size:12px}}
  </style>
</head>
<body>
  <header class="cover">
    <div>
      <div class="brand-row">
        <div class="brand-mark">N</div>
        <div class="brand-text"><strong>NOVA</strong><span>GPO</span></div>
      </div>
      <h1>Comparison Report</h1>
      <div class="muted">{escape(title_a)} vs {escape(title_b)}</div>
      <div class="verdict">{escape(verdict)}</div>
      <div class="meta">
        <div class="meta-item"><span>Generated</span>{escape(now)}</div>
        <div class="meta-item"><span>Nova GPO</span>{escape(__version__)}</div>
        <div class="meta-item"><span>Profile</span>{escape(profile)}</div>
      </div>
    </div>
    <div class="cover-actions">
      <button class="report-button" type="button" onclick="printReport()">Print / PDF</button>
      <button class="report-button" type="button" data-copy-target="body">Copy Report</button>
    </div>
  </header>

  <div class="report-summary-bar" aria-label="Executive Summary">
    {summary_items}
  </div>
  {status_overview}

  {policy_heading}
  {policy_sections}

  <section class="appendix">
    <details class="diagnostics-details">
      <summary>Parser Diagnostics Appendix</summary>
      <table class="summary-table">
        <tbody>{diagnostics_rows}</tbody>
      </table>
    </details>
  </section>

  <div class="footer">Generated by Nova GPO {escape(__version__)} &mdash; Hallister Labs &mdash; {escape(now)} &mdash; Report profile: {escape(profile)}</div>
  <script>
    function setAllFindings(open) {{
      document.querySelectorAll('details.policy-card').forEach(function(card) {{ card.open = open; }});
    }}
    function copyTextFromSelector(selector) {{
      var target = selector === 'body' ? document.body : document.querySelector(selector);
      if (!target || !navigator.clipboard) {{ return; }}
      navigator.clipboard.writeText(target.innerText.trim());
    }}
    function printReport() {{
      setAllFindings(true);
      window.print();
    }}
    document.addEventListener('click', function(event) {{
      var button = event.target.closest('[data-copy-target]');
      if (!button) {{ return; }}
      copyTextFromSelector(button.getAttribute('data-copy-target'));
    }});
    window.addEventListener('beforeprint', function() {{ setAllFindings(true); }});
  </script>
</body>
</html>
"""


def _html_policy_sections(
    report_items: list[PolicyDiff],
    notes: dict[str, dict[str, str]],
    title_a: str,
    title_b: str,
) -> str:
    grouped: dict[str, list[PolicyDiff]] = {}
    for item in report_items:
        status = normalize_review_status(notes.get(item.key, {}).get("status", "Pending Review"))
        grouped.setdefault(status, []).append(item)

    if not grouped:
        return ""

    ordered_statuses = [status for status in REVIEW_STATUSES if status in grouped]
    ordered_statuses.extend(sorted(status for status in grouped if status not in ordered_statuses))

    nav = "".join(
        f'<a class="status-link" href="#{_anchor_id(status)}">{escape(status)} '
        f'<span class="status-count">{len(grouped[status])}</span></a>'
        for status in ordered_statuses
    )
    sections = []
    index = 0
    for status in ordered_statuses:
        items = grouped[status]
        cards = []
        for item in items:
            index += 1
            cards.append(_html_policy_section(item, notes, title_a, title_b, index))
        sections.append(
            f'<section class="status-section" id="{_anchor_id(status)}">'
            f'<div class="status-heading"><h2>{escape(status)}</h2><span class="badge badge-status-unchanged">{len(items)} item(s)</span></div>'
            f'{"".join(cards)}</section>'
        )

    return (
        '<div class="report-toolbar">'
        f'<div class="status-nav">{nav}</div>'
        '<div class="toolbar-actions">'
        '<button class="report-button" type="button" onclick="setAllFindings(true)">Expand All</button>'
        '<button class="report-button" type="button" onclick="setAllFindings(false)">Collapse All</button>'
        '</div>'
        '</div>'
        f'{"".join(sections)}'
    )


def _html_status_overview(
    report_items: list[PolicyDiff],
    notes: dict[str, dict[str, str]],
) -> str:
    counts: dict[str, int] = {}
    for item in report_items:
        status = normalize_review_status(notes.get(item.key, {}).get("status", "Pending Review"))
        counts[status] = counts.get(status, 0) + 1
    if not counts:
        return ""
    ordered = [status for status in REVIEW_STATUSES if status in counts]
    ordered.extend(sorted(status for status in counts if status not in ordered))
    pills = "".join(
        f'<a class="status-pill" href="#{_anchor_id(status)}">{escape(status)} <span class="count">{counts[status]}</span></a>'
        for status in ordered
    )
    return f'<nav class="status-overview" aria-label="Review Status Summary">{pills}</nav>'


def _executive_verdict(
    summary: dict[str, int],
    risks: dict[str, int],
    report_items: list[PolicyDiff],
    notes: dict[str, dict[str, str]],
) -> str:
    if summary["actionable"] == 0:
        return "No actionable differences were detected in this comparison."

    review_counts: dict[str, int] = {}
    for item in report_items:
        review_status = normalize_review_status(notes.get(item.key, {}).get("status", "Pending Review"))
        review_counts[review_status] = review_counts.get(review_status, 0) + 1

    directional_parts = [
        f"{count} {status}"
        for status, count in review_counts.items()
        if status in {"Make Changes to A", "Make Changes to B", "Remove From A", "Remove From B"}
    ]
    review_clause = ", ".join(directional_parts[:3])
    if not review_clause:
        review_clause = f"{summary['unreviewed']} pending review"

    risk_bits = []
    if risks.get("Security", 0):
        risk_bits.append(f"{risks['Security']} security-impacting")
    if risks.get("Protection", 0):
        risk_bits.append(f"{risks['Protection']} protection-impacting")
    risk_clause = f" Includes {', '.join(risk_bits)} finding(s)." if risk_bits else ""
    return f"{summary['actionable']} actionable finding(s): {review_clause}.{risk_clause}"


def _anchor_id(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in value.casefold()).strip("-")
    return f"review-{slug or 'section'}"


def _html_policy_section(
    item: PolicyDiff,
    notes: dict[str, dict[str, str]],
    title_a: str,
    title_b: str,
    index: int,
) -> str:
    name = item.policy_b.name if item.policy_b else (item.policy_a.name if item.policy_a else "Unknown")
    review = notes.get(item.key, {})
    review_status = normalize_review_status(review.get("status", "Pending Review"))
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
    action_plan_html = _review_action_plan_html(item, review_status, title_a, title_b)
    direction_note_html = "" if action_plan_html else _review_direction_note_html(review_status)
    remediation_html = _remediation_html(item)
    summary_bits = [
        ("Review", review_status),
        ("Risk", risk_tag(item)),
        ("State", f"{item.state_a or 'Not present'} -> {item.state_b or 'Not present'}"),
    ]
    if changes:
        summary_bits.append(("Delta", changes[0]))
    summary_html = "".join(
        f'<span><strong>{escape(label)}:</strong> {escape(value)}</span>'
        for label, value in summary_bits
    )
    review_decision_html = _review_decision_html(review, review_status)

    note_html = _review_html(review)
    evidence_html = _evidence_html(item.supporting_evidence)

    return f"""
<details class="policy-card" id="finding-{index}">
  <summary class="policy-header">
    <span class="policy-heading">
      <span class="policy-name">{escape(name)}</span>
      <span class="policy-summary">{summary_html}</span>
    </span>
    <span class="badge {escape(status_cls)}">{escape(status_label)}</span>
  </summary>
  <div class="policy-body">
    <div class="finding-tools">
      <button class="report-button" type="button" data-copy-target="#finding-{index}">Copy Finding</button>
      <button class="report-button" type="button" data-copy-target="#finding-{index} .action-plan">Copy Action Plan</button>
    </div>
    <p class="section-title">Reviewer Decision</p>
    {review_decision_html}
    <div class="status-strip">
      <div class="strip-cell"><span>Status</span><strong>{escape(status_label)}</strong></div>
      <div class="strip-cell"><span>State</span><strong>{escape(item.state_a or 'Not present')} &rarr; {escape(item.state_b or 'Not present')}</strong></div>
    </div>
    <div class="attrs">{attr_html}</div>
    {action_plan_html}
    {direction_note_html}
    <p class="section-title">Actual Delta</p>
    <div class="delta">
      <ul>{changes_html}</ul>
    </div>
    {remediation_html}
    <p class="section-title">Compared Values</p>
    <div class="compare-grid">
      {_side_card_html("Backup A", item.policy_a, "Not present in Backup A.", "a", item.policy_b)}
      {_side_card_html("Backup B", item.policy_b, "Not present in Backup B.", "b", item.policy_a)}
    </div>
    {evidence_html}
    {note_html}
  </div>
</details>
"""


def remediation_steps(item: PolicyDiff) -> list[tuple[str, str, str]]:
    """Return concrete remediation rows as (action, target, detail)."""
    if item.policy_a is None and item.policy_b is not None:
        return _create_policy_steps("Backup A", "Backup B", item.policy_b) + [
            ("Remove", "Backup B", "Alternative: remove this policy/item from Backup B if Backup A is the desired baseline."),
        ]

    if item.policy_a is not None and item.policy_b is None:
        return _create_policy_steps("Backup B", "Backup A", item.policy_a) + [
            ("Remove", "Backup A", "Alternative: remove this policy/item from Backup A if Backup B is the desired baseline."),
        ]

    if item.policy_a is None or item.policy_b is None:
        return [("Review", "Both", "No comparable policy details are available. Review the source backups manually.")]

    steps: list[tuple[str, str, str]] = []
    steps.extend(_update_policy_steps("Backup B", "Backup A", item.policy_b, item.policy_a))
    steps.extend(_update_policy_steps("Backup A", "Backup B", item.policy_a, item.policy_b))
    if not steps:
        steps.append(("Review", "Both", "No exact setting-level remediation was generated. Review metadata, formatting, or unsupported parser detail."))
    return steps


def _create_policy_steps(target_label: str, source_label: str, source_policy) -> list[tuple[str, str, str]]:
    steps = [
        (
            "Create",
            target_label,
            f"Create/recreate '{source_policy.name}' under {source_policy.scope} > {source_policy.category or 'Not reported'} using {source_label} as the source.",
        ),
        ("Set", target_label, f"State: {source_policy.state or 'Not configured'}"),
    ]
    for detail in _policy_setting_details(source_policy):
        steps.append(("Set", target_label, detail))
    return steps


def _update_policy_steps(target_label: str, source_label: str, target_policy, source_policy) -> list[tuple[str, str, str]]:
    steps: list[tuple[str, str, str]] = []
    if target_policy is None or source_policy is None:
        return steps

    if _norm_text(target_policy.state) != _norm_text(source_policy.state):
        steps.append(("Update", target_label, f"Set state to '{source_policy.state or 'Not configured'}' to match {source_label}."))

    target_entries = _setting_entry_map(target_policy)
    source_entries = _setting_entry_map(source_policy)
    if target_entries or source_entries:
        for key in sorted(set(source_entries) & set(target_entries)):
            source_entry = source_entries[key]
            target_entry = target_entries[key]
            if _norm_text(source_entry["value"]) == _norm_text(target_entry["value"]):
                continue
            steps.append((
                "Update",
                target_label,
                (
                    f"{source_entry['context']}: set to {_quote_value(source_entry['value'])} "
                    f"to match {source_label} (currently {_quote_value(target_entry['value'])})."
                ),
            ))

        for key in sorted(set(source_entries) - set(target_entries)):
            source_entry = source_entries[key]
            steps.append((
                "Add/Update",
                target_label,
                f"{source_entry['context']}: add {_quote_value(source_entry['value'])} to match {source_label}.",
            ))

        for key in sorted(set(target_entries) - set(source_entries)):
            target_entry = target_entries[key]
            steps.append((
                "Remove",
                target_label,
                f"{target_entry['context']}: remove {_quote_value(target_entry['value'])}; it is not present in {source_label}.",
            ))
        return steps

    target_settings = {_norm_text(setting): setting for setting in target_policy.settings}
    source_settings = {_norm_text(setting): setting for setting in source_policy.settings}

    for key in sorted(set(source_settings) - set(target_settings)):
        setting = source_settings[key]
        if _is_section_header(setting):
            continue
        steps.append(("Add/Update", target_label, f"{_setting_context(setting)} to match {source_label}: {_clean_setting(setting)}"))

    for key in sorted(set(target_settings) - set(source_settings)):
        setting = target_settings[key]
        if _is_section_header(setting):
            continue
        steps.append(("Remove", target_label, f"{_setting_context(setting)} not present in {source_label}: {_clean_setting(setting)}"))

    return steps


def _policy_setting_details(policy) -> list[str]:
    details: list[str] = []
    current = "Properties"
    for setting in policy.settings or []:
        if setting == GPP_PROPERTIES_HEADER:
            current = "Properties"
            continue
        if setting == GPP_COMMON_HEADER:
            current = "Common Options"
            continue
        if setting == ILT_HEADER:
            current = "Item-Level Targeting"
            continue
        label, value = _split_setting_line(setting)
        if label and value:
            details.append(f"{current}: {label}: {value}")
        elif label:
            details.append(f"{current}: {label}")
    return details


def _setting_context(setting: str) -> str:
    raw = setting
    clean = setting.strip()
    if clean.startswith("•") or clean.startswith("â€¢"):
        return "Item-Level Targeting rule"
    if raw.startswith("  "):
        return "Item-Level Targeting attribute"
    return "Setting"


def _clean_setting(setting: str) -> str:
    clean = setting.strip().lstrip("•").lstrip("â€¢").lstrip("Ã¢â‚¬Â¢").strip()
    return clean.replace("::", ":")


def _split_setting_line(setting: str) -> tuple[str, str]:
    clean = _clean_setting(setting)
    if ":" not in clean:
        return clean, ""
    label, value = clean.split(":", 1)
    return label.strip(), value.strip().lstrip(":").strip()


def _is_targeting_rule_title(setting: str) -> bool:
    clean = setting.strip()
    return clean.startswith("•") or clean.startswith("â€¢") or clean.startswith("Ã¢â‚¬Â¢")


def _setting_entry_map(policy) -> dict[tuple[str, str, str], dict[str, str]]:
    entries: dict[tuple[str, str, str], dict[str, str]] = {}
    section = "Properties"
    rule = ""
    rule_index = 0

    for setting in policy.settings or []:
        if setting == GPP_PROPERTIES_HEADER:
            section = "Properties"
            rule = ""
            rule_index = 0
            continue
        if setting == GPP_COMMON_HEADER:
            section = "Common Options"
            rule = ""
            rule_index = 0
            continue
        if setting == ILT_HEADER:
            section = "Item-Level Targeting"
            rule = ""
            rule_index = 0
            continue
        if _is_targeting_rule_title(setting):
            rule_index += 1
            rule = _clean_setting(setting)
            continue

        label, value = _split_setting_line(setting)
        if not label:
            continue
        rule_key = f"{rule_index}:{rule}" if rule else ""
        key = (_norm_text(section), _norm_text(rule_key), _norm_text(label))
        context = " > ".join(part for part in (section, rule, label) if part)
        entries[key] = {
            "context": context,
            "label": label,
            "value": value,
            "raw": _clean_setting(setting),
        }

    return entries


def _quote_value(value: str) -> str:
    clean = str(value or "").strip()
    return f"'{clean}'" if clean else "(blank)"


def _is_section_header(setting: str) -> bool:
    return setting in {GPP_PROPERTIES_HEADER, GPP_COMMON_HEADER, ILT_HEADER}


def _norm_text(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _remediation_html(item: PolicyDiff) -> str:
    steps = remediation_steps(item)
    if not steps:
        return ""
    rows = "".join(
        "<tr>"
        f'<td class="remediation-action">{escape(action)}</td>'
        f'<td class="remediation-target">{escape(target)}</td>'
        f"<td>{escape(detail)}</td>"
        "</tr>"
        for action, target, detail in steps
    )
    return (
        '<p class="section-title">Remediation</p>'
        f'<div class="remediation"><table><tbody>{rows}</tbody></table></div>'
    )


def _review_decision_html(review: dict[str, str], review_status: str) -> str:
    priority = review.get("priority", "Normal").strip() or "Normal"
    owner = review.get("owner", "").strip() or "Unassigned"
    ticket = review.get("ticket", "").strip() or "Not linked"
    tags = review.get("tags", "").strip() or "None"
    return (
        '<div class="review-decision">'
        f'<div class="decision-cell"><span>Status</span><strong>{escape(review_status)}</strong></div>'
        f'<div class="decision-cell"><span>Priority</span><strong>{escape(priority)}</strong></div>'
        f'<div class="decision-cell"><span>Owner</span><strong>{escape(owner)}</strong></div>'
        f'<div class="decision-cell"><span>Ticket / Tags</span><strong>{escape(ticket)} / {escape(tags)}</strong></div>'
        '</div>'
    )


def _review_action_plan_html(item: PolicyDiff, review_status: str, title_a: str, title_b: str) -> str:
    plan = _review_action_plan(item, review_status, title_a, title_b)
    if plan is None:
        return ""

    (
        title,
        lead,
        action_label,
        target_label,
        source_label,
        desired_title,
        desired_policy,
        current_title,
        current_policy,
    ) = plan
    desired_html = _side_card_html(desired_title, desired_policy, "No desired source settings were captured.", "b", current_policy)
    current_html = ""
    if current_title:
        current_html = _side_card_html(current_title, current_policy, "This item is not currently present.", "a", desired_policy)

    return (
        '<p class="section-title">Review Action Plan</p>'
        '<div class="action-plan">'
        f'<div class="action-title">{escape(title)}</div>'
        f'<div class="action-lead">{escape(lead)}</div>'
        '<div class="action-fields">'
        f'<div class="action-field"><span>Action</span><strong>{escape(action_label)}</strong></div>'
        f'<div class="action-field"><span>Target</span><strong>{escape(target_label)}</strong></div>'
        f'<div class="action-field"><span>Align With</span><strong>{escape(source_label)}</strong></div>'
        f'<div class="action-field"><span>Review Status</span><strong>{escape(review_status)}</strong></div>'
        '</div>'
        f'<div class="action-stack">{desired_html}{current_html}</div>'
        '</div>'
    )


def _review_action_plan(item: PolicyDiff, review_status: str, title_a: str, title_b: str):
    name = item.policy_b.name if item.policy_b else (item.policy_a.name if item.policy_a else item.key)
    if review_status == "Make Changes to A":
        return (
            f"Update {name} in Backup A",
            "Apply the Backup B configuration below to Backup A.",
            "Apply settings",
            f"Backup A ({title_a})",
            f"Backup B ({title_b})",
            f"Settings to apply to Backup A ({title_a}) to align with Backup B ({title_b})",
            item.policy_b,
            f"Current settings in Backup A ({title_a})",
            item.policy_a,
        )
    if review_status == "Make Changes to B":
        return (
            f"Update {name} in Backup B",
            "Apply the Backup A configuration below to Backup B.",
            "Apply settings",
            f"Backup B ({title_b})",
            f"Backup A ({title_a})",
            f"Settings to apply to Backup B ({title_b}) to align with Backup A ({title_a})",
            item.policy_a,
            f"Current settings in Backup B ({title_b})",
            item.policy_b,
        )
    if review_status == "Remove From A":
        return (
            f"Remove {name} from Backup A",
            "Remove or unconfigure the item shown below from Backup A.",
            "Remove setting",
            f"Backup A ({title_a})",
            "No source backup required",
            f"Settings currently in Backup A ({title_a})",
            item.policy_a,
            "",
            None,
        )
    if review_status == "Remove From B":
        return (
            f"Remove {name} from Backup B",
            "Remove or unconfigure the item shown below from Backup B.",
            "Remove setting",
            f"Backup B ({title_b})",
            "No source backup required",
            f"Settings currently in Backup B ({title_b})",
            item.policy_b,
            "",
            None,
        )
    return None


def _review_direction_note_html(review_status: str) -> str:
    if review_status in NON_ACTIONABLE_REVIEW_STATUSES:
        return ""
    if review_status == "Pending Review":
        text = "This finding is still pending review. Select a directional review status before using it as an implementation plan."
    else:
        text = (
            f"{review_status} is a review state, not an implementation direction. "
            "Set this finding to Make Changes to A, Make Changes to B, Remove From A, or Remove From B to produce exact target/source instructions."
        )
    return f'<div class="direction-note">{escape(text)}</div>'


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


def _side_card_html(title: str, policy, missing_text: str, side: str, peer_policy=None) -> str:
    if policy is None:
        body = f"<p>{escape(missing_text)}</p>"
    else:
        sections = _split_preference_sections(policy.settings or [])
        peer_sections = _split_preference_sections(peer_policy.settings or []) if peer_policy else None
        properties_html = _settings_section_html(
            "Properties",
            sections["properties"],
            peer_sections["properties"] if peer_sections else None,
        )
        common_html = _settings_section_html(
            "Common Options",
            sections["common"],
            peer_sections["common"] if peer_sections else None,
        )
        targeting_html = _targeting_section_html(
            sections["targeting"],
            peer_sections["targeting"] if peer_sections else None,
        )
        if not (properties_html or common_html or targeting_html):
            properties_html = "<p>No additional configured value details were captured for this policy type.</p>"
        body = (
            f'<div class="attr"><strong>State:</strong> {escape(policy.state or "Not reported")}</div>'
            f'<div class="attr"><strong>Category:</strong> {escape(policy.category or "Not reported")}</div>'
            f'<div class="attr"><strong>Source:</strong> {escape(policy.source or "gpreport.xml")}</div>'
            f"{properties_html}"
            f"{common_html}"
            f"{targeting_html}"
        )

    side_class = "side-card b" if side == "b" else "side-card"
    return f'<div class="{side_class}"><div class="side-title">{escape(title)}</div>{body}</div>'


def _split_preference_sections(settings: list[str]) -> dict[str, list[str]]:
    sections = {"properties": [], "common": [], "targeting": []}
    current = "properties"
    for setting in settings:
        if setting == GPP_PROPERTIES_HEADER:
            current = "properties"
            continue
        if setting == GPP_COMMON_HEADER:
            current = "common"
            continue
        if setting == ILT_HEADER:
            current = "targeting"
            continue
        sections[current].append(setting)
    return sections


def _settings_section_html(title: str, settings: list[str], peer_settings: list[str] | None = None) -> str:
    if not settings:
        return ""
    peer_normalized = {_normalize_setting_for_diff(setting) for setting in (peer_settings or [])}
    rows = "".join(
        _kv_row_html(
            setting,
            changed=peer_settings is not None and _normalize_setting_for_diff(setting) not in peer_normalized,
        )
        for setting in settings
    )
    return f'<p class="section-title">{escape(title)}</p><table class="kv">{rows}</table>'


def _kv_row_html(setting: str, changed: bool = False) -> str:
    key, value = _split_setting_line(setting)
    class_attr = ' class="kv-diff"' if changed else ""
    if not value:
        return f'<tr{class_attr}><td colspan="2" class="kv-value"><strong>{escape(key)}</strong></td></tr>'
    return (
        f'<tr{class_attr}><td class="kv-key">{escape(key)}</td>'
        f'<td class="kv-value">{escape(value)}</td></tr>'
    )


def _targeting_section_html(rules: list[str], peer_rules: list[str] | None = None) -> str:
    if not rules:
        return ""
    cards: list[str] = []
    current_title = ""
    current_rows: list[str] = []
    peer_rule_set = {_normalize_setting_for_diff(rule) for rule in (peer_rules or [])}

    def flush() -> None:
        nonlocal current_title, current_rows
        if not current_title and not current_rows:
            return
        title = current_title or "Targeting Rule"
        changed = (
            peer_rules is not None
            and (
                _normalize_setting_for_diff(current_title) not in peer_rule_set
                or any(_normalize_setting_for_diff(row) not in peer_rule_set for row in current_rows if row.strip())
            )
        )
        rows = "".join(
            _kv_row_html(
                row.strip(),
                changed=peer_rules is not None and _normalize_setting_for_diff(row) not in peer_rule_set,
            )
            for row in current_rows
            if row.strip()
        )
        diff_class = " diff" if changed else ""
        cards.append(
            f'<div class="ilt-card{diff_class}"><div class="ilt-title">{escape(title)}</div>'
            f'<table class="kv">{rows}</table></div>'
        )
        current_title = ""
        current_rows = []

    for rule in rules:
        clean = rule.strip()
        if clean.startswith("•"):
            flush()
            current_title = clean.lstrip("•").strip()
        else:
            current_rows.append(clean)

    flush()
    if len(cards) > 1:
        return (
            '<details class="targeting-details">'
            f'<summary>Targeting Information ({len(cards)} rules)</summary>'
            f'{"".join(cards)}'
            '</details>'
        )
    return f'<p class="section-title">Targeting Information</p>{"".join(cards)}'


def _normalize_setting_for_diff(setting: str) -> str:
    return " ".join(setting.strip().casefold().split())


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


def _markdown_review_summary(item: PolicyDiff, review: dict[str, str]) -> list[tuple[str, str]]:
    changes = setting_changes(item)
    targeting = _targeting_summary(item)
    return [
        ("State", f"{item.state_a or 'Not present'} -> {item.state_b or 'Not present'}"),
        ("Targeting", targeting),
        ("Primary delta", changes[0] if changes else "No setting-level delta was reported."),
        ("Review", normalize_review_status(review.get("status", "Pending Review"))),
    ]


def _targeting_summary(item: PolicyDiff) -> str:
    if not item.policy_a and item.policy_b:
        return "Added with policy"
    if item.policy_a and not item.policy_b:
        return "Removed with policy"
    if not item.policy_a or not item.policy_b:
        return "Not comparable"
    a = _split_preference_sections(item.policy_a.settings or [])["targeting"]
    b = _split_preference_sections(item.policy_b.settings or [])["targeting"]
    if not a and not b:
        return "None"
    if not a and b:
        return "Added"
    if a and not b:
        return "Removed"
    return "Changed" if a != b else "No change"


def _markdown_policy_values(label: str, policy) -> list[str]:
    if policy is None:
        return [f"**{label}:** Not present."]

    lines = [
        f"**{label}: {policy.name or 'Unknown'}**",
        f"- State: {policy.state or 'Not reported'}",
        f"- Category: {policy.category or 'Not reported'}",
        f"- Type: {policy.policy_type or 'Unknown'}",
        f"- Source: {policy.source or 'gpreport.xml'}",
    ]
    if policy.supported:
        lines.append(f"- Supported On: {policy.supported}")

    sections = _split_preference_sections(policy.settings or [])
    for title, key in [
        ("Properties", "properties"),
        ("Common Options", "common"),
        ("Item-Level Targeting", "targeting"),
    ]:
        values = sections[key]
        if not values:
            continue
        lines.append(f"- {title}:")
        for setting in values:
            label_text, value = _split_setting_line(setting)
            if value:
                lines.append(f"  - {label_text}: {value}")
            elif label_text:
                lines.append(f"  - {label_text}")

    if not any(line.startswith("- Properties:") or line.startswith("- Common") or line.startswith("- Item-Level") for line in lines):
        lines.append("- Configured values: No additional configured value details were captured for this policy type.")
    return lines


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
            "review_summary": {
                label.lower().replace(" ", "_"): value
                for label, value in _markdown_review_summary(item, notes.get(item.key, {}))
            },
            "remediation": [
                {"action": action, "target": target, "detail": detail}
                for action, target, detail in remediation_steps(item)
            ],
            "risk": risk_tag(item),
            "supporting_evidence": list(item.supporting_evidence),
            "policy_a": _policy_dict(item.policy_a),
            "policy_b": _policy_dict(item.policy_b),
            "review": _normalized_review(notes.get(item.key, {})),
        })

    payload = {
        "schema_version": 2,
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


def _normalized_review(review: dict[str, str]) -> dict[str, str]:
    return {
        **review,
        "status": normalize_review_status(review.get("status", "Pending Review")),
    }


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
        if normalize_review_status(notes.get(item.key, {}).get("status", "Pending Review")) in NON_ACTIONABLE_REVIEW_STATUSES
    )
    reviewed = sum(
        1 for item in actionable_items(diff_items)
        if normalize_review_status(notes.get(item.key, {}).get("status", "Pending Review")) != "Pending Review"
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
