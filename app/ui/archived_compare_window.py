from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.settings import REPORTS_DIR
from app.library_store import load_compare_record_payload, update_compare_record_reviews
from app.ui.branding import app_icon
from app.ui.widgets import badge

_REVIEW_STATUSES = [
    "Pending Review",
    "No Action Required",
    "Update Required",
    "Under Investigation",
    "Escalated",
]

_REVIEW_STATUS_COLOR: dict[str, str] = {
    "Pending Review":      "#C8901A",  # amber  — unreviewed, needs attention
    "Update Required":     "#C84040",  # red    — action required
    "Escalated":           "#B040C8",  # purple — urgent
    "Under Investigation": "#4090C8",  # blue   — being worked
    "No Action Required":  "#707070",  # gray   — resolved / done
}

_REVIEW_PRIORITIES = ["Normal", "Low", "Medium", "High", "Critical"]

_WINDOW_FLAGS = (
    Qt.WindowType.Dialog |
    Qt.WindowType.WindowTitleHint |
    Qt.WindowType.WindowSystemMenuHint |
    Qt.WindowType.WindowCloseButtonHint |
    Qt.WindowType.WindowMaximizeButtonHint
)


class ArchivedCompareWindow(QDialog):
    def __init__(self, record_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, _WINDOW_FLAGS)
        self.record_path = record_path
        self.payload = load_compare_record_payload(record_path)
        self.findings = _record_findings(self.payload)
        self._all_findings = list(self.findings)  # unfiltered copy for search
        self.current_key = ""
        self.loading = False
        self.reviews = {
            str(item.get("key", "")): dict(item.get("review", {}))
            for item in self.findings
            if isinstance(item, dict) and item.get("key")
        }

        self.setWindowTitle(f"Saved Compare Review - {self.payload.get('title', 'Saved comparison')}")
        self.setWindowIcon(app_icon())
        self.resize(1400, 820)
        self.setMinimumSize(1060, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)

        if self.findings:
            self.list_widget.setCurrentRow(0)
        else:
            self._show_empty()

    def closeEvent(self, event) -> None:
        self._save_current()
        super().closeEvent(event)

    # ── header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        copy = QVBoxLayout()
        copy.setSpacing(5)
        title = QLabel(str(self.payload.get("title") or "Saved comparison"))
        title.setObjectName("Title")
        title.setWordWrap(True)
        summary = self.payload.get("summary", {}) if isinstance(self.payload.get("summary"), dict) else {}
        subtitle = QLabel(
            f"{summary.get('total_items', summary.get('total', 0))} compared  |  "
            f"{summary.get('actionable', len(self.findings))} actionable  |  "
            f"{summary.get('reviewed', 0)} reviewed"
        )
        subtitle.setObjectName("Muted")
        copy.addWidget(title)
        copy.addWidget(subtitle)

        export_btn = QPushButton("Export HTML")
        export_btn.setObjectName("GhostButton")
        export_btn.setToolTip("Save the full comparison report as an HTML file.")
        export_btn.clicked.connect(self._export_html)

        save_btn = QPushButton("Save Review")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_all)

        layout.addLayout(copy, 1)
        layout.addWidget(export_btn)
        layout.addWidget(save_btn)
        return panel

    # ── body ──────────────────────────────────────────────────────────────────

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── LEFT: findings list ───────────────────────────────────────────────
        list_panel = QFrame()
        list_panel.setObjectName("Panel")
        list_panel.setMinimumWidth(240)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_layout.setSpacing(8)

        list_title = QLabel("Findings")
        list_title.setObjectName("PanelTitle")
        self.list_hint = QLabel(f"{len(self.findings)} actionable finding(s)")
        self.list_hint.setObjectName("Muted")

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter findings…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)

        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        self._populate_list(self._all_findings)

        list_layout.addWidget(list_title)
        list_layout.addWidget(self.list_hint)
        list_layout.addWidget(self.search_box)
        list_layout.addWidget(self.list_widget, 1)

        # ── CENTER: detail ────────────────────────────────────────────────────
        center = QFrame()
        center.setObjectName("Panel")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 16, 18, 16)
        center_layout.setSpacing(8)

        self.detail_title = QLabel("No finding selected")
        self.detail_title.setObjectName("PanelTitle")
        self.detail_title.setWordWrap(True)
        self.detail_meta = QLabel("")
        self.detail_meta.setObjectName("Muted")
        self.detail_meta.setWordWrap(True)

        self.state_strip = QFrame()
        self.state_strip.setObjectName("RaisedPanel")
        state_layout = QHBoxLayout(self.state_strip)
        state_layout.setContentsMargins(12, 10, 12, 10)
        state_layout.setSpacing(10)
        self.status_badge_slot = QHBoxLayout()
        self.status_badge_slot.setSpacing(6)
        self.state_label = QLabel("")
        self.state_label.setObjectName("StatusLabel")
        state_layout.addLayout(self.status_badge_slot)
        state_layout.addWidget(self.state_label, 1)

        self.detail_text = QTextEdit()
        self.detail_text.setObjectName("DetailText")
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(220)

        center_layout.addWidget(self.detail_title)
        center_layout.addWidget(self.detail_meta)
        center_layout.addWidget(self.state_strip)
        center_layout.addWidget(self.detail_text, 1)

        # ── RIGHT: review panel ───────────────────────────────────────────────
        review_panel = QFrame()
        review_panel.setObjectName("Panel")
        review_panel.setMinimumWidth(300)
        review_layout = QVBoxLayout(review_panel)
        review_layout.setContentsMargins(16, 16, 16, 16)
        review_layout.setSpacing(8)

        review_title = QLabel("Review")
        review_title.setObjectName("PanelTitle")
        review_layout.addWidget(review_title)

        self.review_status = QComboBox()
        self.review_status.addItems(_REVIEW_STATUSES)
        self.review_status.currentTextChanged.connect(self._refresh_current_item)
        self.review_priority = QComboBox()
        self.review_priority.addItems(_REVIEW_PRIORITIES)
        self.owner_box = QLineEdit()
        self.owner_box.setPlaceholderText("Reviewer or owner")
        self.ticket_box = QLineEdit()
        self.ticket_box.setPlaceholderText("Change, incident, or ticket")
        self.tags_box = QLineEdit()
        self.tags_box.setPlaceholderText("Tags, separated by commas")
        self.notes_box = QTextEdit()
        self.notes_box.setPlaceholderText("Notes, observations, follow-up actions...")
        self.notes_box.setMinimumHeight(120)

        for label, widget in [
            ("Status", self.review_status),
            ("Priority", self.review_priority),
            ("Owner", self.owner_box),
            ("Ticket / Change", self.ticket_box),
            ("Tags", self.tags_box),
        ]:
            lbl = QLabel(label)
            lbl.setObjectName("Muted")
            review_layout.addWidget(lbl)
            review_layout.addWidget(widget)

        notes_lbl = QLabel("Notes")
        notes_lbl.setObjectName("Muted")
        review_layout.addWidget(notes_lbl)
        review_layout.addWidget(self.notes_box, 1)

        splitter.addWidget(list_panel)
        splitter.addWidget(center)
        splitter.addWidget(review_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([300, 700, 400])
        return splitter

    # ── list management ───────────────────────────────────────────────────────

    def _populate_list(self, findings: list[dict[str, Any]]) -> None:
        self.list_widget.clear()
        for finding in findings:
            key = str(finding.get("key", ""))
            rs = (self.reviews.get(key) or {}).get("status") or "Pending Review"
            item = QListWidgetItem(_finding_label(finding, rs))
            item.setData(Qt.ItemDataRole.UserRole, finding)
            item.setToolTip(str(finding.get("name") or finding.get("key") or ""))
            _apply_review_style(item, rs)
            self.list_widget.addItem(item)

    def _on_search(self, text: str) -> None:
        query = text.strip().lower()
        if query:
            filtered = [
                f for f in self._all_findings
                if query in str(f.get("name", "")).lower()
                or query in str(f.get("scope", "")).lower()
                or query in str(f.get("status", "")).lower()
            ]
        else:
            filtered = self._all_findings
        self.findings = filtered
        self.list_hint.setText(f"{len(filtered)} of {len(self._all_findings)} finding(s)")
        self._populate_list(filtered)
        if filtered:
            self.list_widget.setCurrentRow(0)
        else:
            self._show_empty()

    # ── item display ──────────────────────────────────────────────────────────

    def _on_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._save_current()
        if current is None:
            self._show_empty()
            return
        finding = current.data(Qt.ItemDataRole.UserRole)
        key = str(finding.get("key", ""))
        self.current_key = key
        review = self.reviews.setdefault(key, {})

        self.loading = True
        self.detail_title.setText(str(finding.get("name") or key))
        self.detail_meta.setText(_finding_meta(finding))

        state_a = str(finding.get("state_a") or "Not present")
        state_b = str(finding.get("state_b") or "Not present")
        if state_a.lower() != state_b.lower():
            self.state_label.setText(f"{state_a}  →  {state_b}")
            self.state_strip.setVisible(True)
        else:
            # Only show the strip to carry the badge; hide the redundant state text
            self.state_label.setText(state_a if state_a != "Not present" else "")
            self.state_strip.setVisible(True)

        _replace_badge(
            self.status_badge_slot,
            badge(str(finding.get("status") or "Unknown"), _status_badge_state(finding), min_width=112),
        )
        self.detail_text.setHtml(_finding_detail_html(finding))

        self.review_status.setCurrentText(str(review.get("status") or "Pending Review"))
        self.review_priority.setCurrentText(str(review.get("priority") or "Normal"))
        self.owner_box.setText(str(review.get("owner") or ""))
        self.ticket_box.setText(str(review.get("ticket") or ""))
        self.tags_box.setText(str(review.get("tags") or ""))
        self.notes_box.setPlainText(str(review.get("notes") or ""))
        self.loading = False

    def _show_empty(self) -> None:
        self.current_key = ""
        self.detail_title.setText("No actionable findings")
        self.detail_meta.setText("")
        self.state_label.setText("")
        _replace_badge(self.status_badge_slot, QLabel())
        self.detail_text.setPlainText("This archived compare has no actionable findings to review.")

    # ── persistence ───────────────────────────────────────────────────────────

    def _save_current(self) -> None:
        if self.loading or not self.current_key:
            return
        self.reviews[self.current_key] = {
            "status": self.review_status.currentText(),
            "priority": self.review_priority.currentText(),
            "owner": self.owner_box.text().strip(),
            "ticket": self.ticket_box.text().strip(),
            "tags": self.tags_box.text().strip(),
            "notes": self.notes_box.toPlainText().strip(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _refresh_current_item(self) -> None:
        if self.loading:
            return
        item = self.list_widget.currentItem()
        if item is None:
            return
        finding = item.data(Qt.ItemDataRole.UserRole)
        rs = self.review_status.currentText()
        item.setText(_finding_label(finding, rs))
        _apply_review_style(item, rs)

    def _save_all(self) -> None:
        self._save_current()
        update_compare_record_reviews(self.record_path, self.reviews)
        self.accept()

    # ── export ────────────────────────────────────────────────────────────────

    def _export_html(self) -> None:
        safe_title = (self.payload.get("title") or "report").replace(" ", "_").replace("/", "-")[:60]
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Comparison Report",
            str(REPORTS_DIR / f"{safe_title}.html"),
            "HTML Files (*.html);;All Files (*)",
        )
        if not path:
            return

        # Prefer the pre-generated HTML stored in the archive
        stored_html = (
            self.payload.get("html_path")
            or (self.payload.get("generated_artifacts") or {}).get("html", "")
        )
        if stored_html and Path(stored_html).exists():
            shutil.copy(stored_html, path)
        else:
            # Fall back: generate minimal HTML from findings data
            html = _generate_fallback_html(self.payload, self.findings)
            Path(path).write_text(html, encoding="utf-8")

        QMessageBox.information(self, "Export Complete", f"Report exported to:\n{path}")


# ── module helpers ─────────────────────────────────────────────────────────────

def _record_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings = payload.get("findings")
    if isinstance(findings, list):
        return [item for item in findings if isinstance(item, dict)]
    items = payload.get("items")
    if isinstance(items, list):
        return [
            item for item in items
            if isinstance(item, dict) and item.get("status") not in ("Unchanged", "Same")
        ]
    return []


def _finding_label(finding: dict[str, Any], review_status: str = "") -> str:
    status = str(finding.get("status") or "Unknown")
    name = str(finding.get("name") or finding.get("key") or "Unknown")
    scope = str(finding.get("scope") or "")
    scope_short = scope.split(" ")[-1] if scope else ""   # "Configuration" → last word only
    header = f"{status}  ·  {scope_short}" if scope_short else status
    rs = review_status or "Pending Review"
    return f"{header}\n{name}\n{rs}"


def _apply_review_style(item: QListWidgetItem, review_status: str) -> None:
    color_hex = _REVIEW_STATUS_COLOR.get(review_status, _REVIEW_STATUS_COLOR["Pending Review"])
    item.setForeground(QColor(color_hex))


def _finding_meta(finding: dict[str, Any]) -> str:
    scope = str(finding.get("scope") or "Unknown scope")
    category = str(finding.get("category") or "").strip()
    policy_type = str(finding.get("policy_type") or "").strip()

    if category and category not in ("Not reported", "Not categorized"):
        return f"{scope}  ›  {category}"
    if policy_type:
        return f"{scope}  ›  {policy_type}"
    return scope


def _reconciliation_steps(finding: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (label, description) pairs describing what each backup needs to align."""
    status = str(finding.get("status") or "")
    state_a = str(finding.get("state_a") or "").strip()
    state_b = str(finding.get("state_b") or "").strip()
    changes: list[str] = [str(c) for c in (finding.get("changes") or []) if c]

    steps: list[tuple[str, str]] = []

    if status == "Added":
        state_note = f" — set state to \"{state_b}\"" if state_b and state_b != "Not present" else ""
        steps.append(("Add to Backup A", f"This policy is only in Backup B{state_note}."))
        for c in changes:
            if c.startswith("Added configured value:"):
                steps.append(("Configure in A", c.split(":", 1)[1].strip()))

    elif status in ("Removed", "Missing in B"):
        state_note = f" — set state to \"{state_a}\"" if state_a and state_a != "Not present" else ""
        steps.append(("Add to Backup B", f"This policy is only in Backup A{state_note}."))
        for c in changes:
            if c.startswith("Added configured value:"):
                steps.append(("Configure in B", c.split(":", 1)[1].strip()))

    elif status == "Missing in A":
        state_note = f" — set state to \"{state_b}\"" if state_b and state_b != "Not present" else ""
        steps.append(("Add to Backup A", f"This policy is only in Backup B{state_note}."))

    elif status == "Different":
        if state_a and state_b and state_a.lower() != state_b.lower():
            steps.append(("State differs", f"Backup A: \"{state_a}\"  →  Backup B: \"{state_b}\""))

        for c in changes:
            cl = c.lower()
            if cl.startswith("state changed"):
                continue  # already handled above
            elif cl.startswith("no setting-level differences"):
                steps.append(("Note", "Difference may be metadata, formatting, or an unsupported parser detail."))
            elif c.startswith("Added configured value in Backup B:"):
                val = c.split("Added configured value in Backup B:", 1)[1].strip()
                steps.append(("Backup A is missing", val))
            elif c.startswith("Removed configured value from Backup B:"):
                val = c.split("Removed configured value from Backup B:", 1)[1].strip()
                steps.append(("Backup B is missing", val))
            elif c.startswith("Added configured value:"):
                steps.append(("Backup A is missing", c.split(":", 1)[1].strip()))
            elif c.startswith("Removed configured value:"):
                steps.append(("Backup B is missing", c.split(":", 1)[1].strip()))
            elif "supported-on text changed" in cl:
                steps.append(("Policy Definition", "Review and align the Supported On attribute."))
            elif cl.startswith("type changed from"):
                steps.append(("Policy Type", c))
            elif cl.startswith("category changed from"):
                steps.append(("Category", c))
            else:
                steps.append(("Review", c))

    return steps


def _finding_detail_html(finding: dict[str, Any]) -> str:
    # Dark theme palette (matches executive_dark)
    C_BG     = "#101112"
    C_RAISED = "#202123"
    C_BORDER = "rgba(255,255,255,0.08)"
    C_TEXT   = "#F4F6F8"
    C_MUTED  = "#85888E"
    C_LABEL  = "#C0C3C7"
    C_ORANGE = "#FF8A1F"
    C_GREEN  = "#3DDC84"
    C_RED    = "#FF4D4D"
    C_BLUE   = "#82B6FF"

    parts = [f"<div style='font-size:13px; line-height:1.65; color:{C_TEXT};'>"]

    # ── To Align These Policies ───────────────────────────────────────────────
    steps = _reconciliation_steps(finding)
    if steps:
        parts.append(
            f"<p style='color:{C_BLUE}; font-weight:800; font-size:12px; margin:0 0 6px 0;"
            f" text-transform:uppercase; letter-spacing:0.5px; padding:6px 10px;"
            f" background:{C_RAISED}; border-left:3px solid {C_BLUE};'>"
            f"To Align These Policies</p>"
        )
        parts.append(
            f"<table cellspacing='0' cellpadding='0'"
            f" style='width:100%; border-collapse:collapse; margin-bottom:18px;'>"
        )
        for i, (label, desc) in enumerate(steps):
            row_bg = "#191b1d" if i % 2 == 0 else "transparent"
            cl = label.lower()
            if "missing" in cl or "add to" in cl or "configure" in cl:
                label_color = C_ORANGE
            elif "differs" in cl or "review" in cl or "note" in cl:
                label_color = C_MUTED
            else:
                label_color = C_BLUE
            parts.append(
                f"<tr style='background:{row_bg};'>"
                f"<td style='color:{label_color}; font-size:11px; font-weight:700;"
                f" text-transform:uppercase; letter-spacing:0.3px; width:155px;"
                f" white-space:nowrap; padding:7px 10px 7px 12px; vertical-align:top;"
                f" border-bottom:1px solid {C_BORDER};'>{_esc(label)}</td>"
                f"<td style='color:{C_TEXT}; font-size:12px; line-height:1.6;"
                f" padding:7px 12px 7px 4px; vertical-align:top;"
                f" border-bottom:1px solid {C_BORDER};'>{_esc(desc)}</td>"
                f"</tr>"
            )
        parts.append("</table>")

    # ── Actual Delta ──────────────────────────────────────────────────────────
    parts.append(
        f"<p style='color:{C_ORANGE}; font-weight:800; font-size:12px; margin:0 0 8px 0;"
        f" text-transform:uppercase; letter-spacing:0.5px; padding:5px 10px;"
        f" background:{C_RAISED}; border-left:3px solid {C_ORANGE};'>Actual Delta</p>"
    )

    changes = finding.get("changes")
    if isinstance(changes, list) and changes:
        parts.append(f"<ul style='margin:0 0 18px 0; padding-left:18px; line-height:1.8;'>")
        for change in changes:
            cs = str(change)
            cl = cs.lower()
            if cl.startswith("added"):
                color = C_GREEN
            elif cl.startswith("removed"):
                color = C_RED
            else:
                color = C_TEXT
            parts.append(f"<li style='color:{color}; padding:2px 0;'>{_esc(cs)}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            f"<p style='color:{C_MUTED}; font-style:italic; margin-bottom:16px;'>"
            "No setting-level changes were recorded in the archive.</p>"
        )

    # ── Supporting Evidence ───────────────────────────────────────────────────
    evidence = finding.get("supporting_evidence")
    if isinstance(evidence, list) and evidence:
        parts.append(
            f"<p style='color:{C_LABEL}; font-weight:800; font-size:12px; margin:0 0 8px 0;"
            f" text-transform:uppercase; letter-spacing:0.5px; padding:5px 10px;"
            f" background:{C_RAISED}; border-left:3px solid {C_LABEL};'>Supporting Evidence</p>"
        )
        parts.append(f"<ul style='margin:0; padding-left:18px; line-height:1.8;'>")
        for ev in evidence:
            ev_str = str(ev)
            ev_lower = ev_str.lower()
            if "added" in ev_lower:
                accent = C_GREEN
            elif "removed" in ev_lower or "missing" in ev_lower:
                accent = C_RED
            else:
                accent = C_LABEL

            # Split "SettingName (source/path): description text" for readability
            if "): " in ev_str:
                src, _, desc = ev_str.partition("): ")
                parts.append("<li style='padding:3px 0;'>")
                parts.append(
                    f"<span style='color:{C_MUTED}; font-size:11px;'>{_esc(src)})</span><br>"
                    f"<span style='color:{accent}; padding-left:10px;'>↳ {_esc(desc)}</span>"
                )
                parts.append("</li>")
            else:
                parts.append(
                    f"<li style='color:{accent}; padding:3px 0;'>{_esc(ev_str)}</li>"
                )
        parts.append("</ul>")

    # ── Policy Definition ─────────────────────────────────────────────────────
    category = str(finding.get("category") or "").strip()
    policy_type = str(finding.get("policy_type") or "").strip()
    source = str(finding.get("source") or "").strip()
    supported = str(finding.get("supported") or "").strip()

    def_rows: list[str] = []
    if category and category not in ("Not reported", "Not categorized"):
        def_rows.append(("Category", category))
    if policy_type:
        def_rows.append(("Type", policy_type))
    if supported:
        def_rows.append(("Supported On", supported))
    if source:
        def_rows.append(("Source", source))

    if def_rows:
        parts.append(
            f"<p style='color:{C_LABEL}; font-weight:800; font-size:12px; margin:16px 0 8px 0;"
            f" text-transform:uppercase; letter-spacing:0.5px; padding:5px 10px;"
            f" background:{C_RAISED}; border-left:3px solid {C_LABEL};'>Policy Definition</p>"
        )
        parts.append(
            f"<table cellspacing='0' cellpadding='0'"
            f" style='width:100%; border-collapse:collapse; margin-bottom:12px;'>"
        )
        for lbl, val in def_rows:
            parts.append(
                f"<tr>"
                f"<td style='color:{C_MUTED}; font-size:11px; font-weight:700;"
                f" text-transform:uppercase; letter-spacing:0.4px; width:95px;"
                f" white-space:nowrap; padding:5px 10px 5px 0; vertical-align:top;"
                f" border-bottom:1px solid {C_BORDER};'>{_esc(lbl)}</td>"
                f"<td style='color:{C_TEXT}; font-size:12px; padding:5px 0;"
                f" vertical-align:top; border-bottom:1px solid {C_BORDER};'>{_esc(val)}</td>"
                f"</tr>"
            )
        parts.append("</table>")
    elif not category:
        parts.append(
            f"<p style='color:{C_MUTED}; font-size:11px; font-style:italic; margin-top:12px;'>"
            f"Category not recorded — re-save this comparison to capture full policy metadata.</p>"
        )

    parts.append("</div>")
    return "".join(parts)


def _generate_fallback_html(payload: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    title = _esc(str(payload.get("title") or "Saved Comparison"))
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    rows = ""
    for f in findings:
        name = _esc(str(f.get("name") or f.get("key") or ""))
        status = _esc(str(f.get("status") or ""))
        scope = _esc(str(f.get("scope") or ""))
        changes = f.get("changes") or []
        change_html = "".join(f"<li>{_esc(str(c))}</li>" for c in changes) if changes else "<li>No changes recorded</li>"
        review = f.get("review") or {}
        review_status = _esc(str(review.get("status") or "Pending Review"))
        notes = _esc(str(review.get("notes") or ""))
        rows += f"""
<tr>
  <td style="padding:8px;border-bottom:1px solid #333;vertical-align:top;">{status}</td>
  <td style="padding:8px;border-bottom:1px solid #333;vertical-align:top;"><b>{name}</b><br>
    <small style="color:#888;">{scope}</small><br>
    <ul style="margin:6px 0 0 0;">{change_html}</ul>
  </td>
  <td style="padding:8px;border-bottom:1px solid #333;vertical-align:top;">{review_status}<br>
    <small>{notes}</small>
  </td>
</tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{title}</title>
<style>body{{font-family:Segoe UI,sans-serif;background:#101112;color:#F4F6F8;margin:24px;}}
h1{{color:#FF8A1F;}} table{{width:100%;border-collapse:collapse;}} th{{background:#202123;padding:8px;text-align:left;}}
</style></head>
<body>
<h1>{title}</h1>
<p style="color:#888;">{summary.get('total_items',0)} compared &nbsp;·&nbsp; {summary.get('actionable',0)} actionable</p>
<table><thead><tr><th>Status</th><th>Finding</th><th>Review</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""


def _replace_badge(slot: QHBoxLayout, replacement: QLabel) -> None:
    while slot.count():
        item = slot.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    slot.addWidget(replacement)


def _status_badge_state(finding: dict[str, Any]) -> str:
    return {
        "Different":  "changed",
        "Added":      "added",
        "Missing in A": "added",
        "Removed":    "removed",
        "Missing in B": "removed",
    }.get(str(finding.get("status") or ""), "unknown")


def _esc(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
