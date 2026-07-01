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
from app.review_status import REVIEW_STATUS_COLORS, REVIEW_STATUSES, normalize_review_status
from app.ui.branding import app_icon
from app.ui.widgets import badge

_REVIEW_STATUSES = [
    "Pending Review",
    "Add Policy to Align",
    "Add Setting to Align",
    "Remove Setting to Align",
    "Update Setting to Align",
    "Under Investigation",
    "Escalated",
    "No Action Required",
]

_REVIEW_STATUS_COLOR: dict[str, str] = {
    "Pending Review":          "#C8901A",  # amber  — unreviewed
    "Add Policy to Align":     "#3DDC84",  # green  — add whole policy
    "Add Setting to Align":    "#2EC9A0",  # teal   — add specific settings
    "Remove Setting to Align": "#FF6060",  # red    — remove settings
    "Update Setting to Align": "#FF8A1F",  # orange — change a value
    "Under Investigation":     "#4090C8",  # blue   — being worked
    "Escalated":               "#B040C8",  # purple — urgent
    "No Action Required":      "#707070",  # gray   — resolved / done
}

_REVIEW_PRIORITIES = ["Normal", "Low", "Medium", "High", "Critical"]
_REVIEW_STATUSES = REVIEW_STATUSES
_REVIEW_STATUS_COLOR = REVIEW_STATUS_COLORS

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
        ba = self.payload.get("backup_a") or {}
        bb = self.payload.get("backup_b") or {}
        self._backup_a_title = str(ba.get("title") or "Backup A")
        self._backup_b_title = str(bb.get("title") or "Backup B")
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
            f"{summary.get('ignored', 0)} ignored  |  "
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
            rs = normalize_review_status((self.reviews.get(key) or {}).get("status") or "Pending Review")
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
        self.detail_text.setHtml(
            _finding_detail_html(finding, self._backup_a_title, self._backup_b_title)
        )

        self.review_status.setCurrentText(normalize_review_status(review.get("status") or "Pending Review"))
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
    rs = normalize_review_status(review_status or "Pending Review")
    return f"{header}\n{name}\n{rs}"


def _apply_review_style(item: QListWidgetItem, review_status: str) -> None:
    color_hex = _REVIEW_STATUS_COLOR.get(
        normalize_review_status(review_status),
        _REVIEW_STATUS_COLOR["Pending Review"],
    )
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


def _finding_detail_html(
    finding: dict[str, Any],
    backup_a_title: str = "Backup A",
    backup_b_title: str = "Backup B",
) -> str:
    C_RAISED = "#202123"
    C_BORDER = "rgba(255,255,255,0.08)"
    C_TEXT   = "#F4F6F8"
    C_MUTED  = "#85888E"
    C_LABEL  = "#C0C3C7"
    C_ORANGE = "#FF8A1F"
    C_GREEN  = "#3DDC84"
    C_RED    = "#FF4D4D"
    C_BLUE   = "#82B6FF"

    status      = str(finding.get("status") or "Unknown")
    name        = str(finding.get("name") or finding.get("key") or "")
    scope       = str(finding.get("scope") or "")
    cat         = str(finding.get("category") or "").strip()
    policy_type = str(finding.get("policy_type") or "").strip()
    supported   = str(finding.get("supported") or "").strip()
    state_a     = str(finding.get("state_a") or "").strip()
    state_b     = str(finding.get("state_b") or "").strip()
    changes: list[str]  = [str(c) for c in (finding.get("changes") or []) if c]
    evidence: list[str] = [str(e) for e in (finding.get("supporting_evidence") or []) if e]
    if isinstance(finding.get("policy_a"), dict) or isinstance(finding.get("policy_b"), dict):
        return _full_finding_detail_html(finding, backup_a_title, backup_b_title)

    path = (
        f"{scope}  ›  {cat}"
        if cat and cat not in ("Not reported", "Not categorized")
        else scope
    )

    # ── classify change strings ───────────────────────────────────────────────
    state_change_str: str | None = None
    a_needs:      list[str] = []   # B has; A must add
    b_needs:      list[str] = []   # A has; B must add / A must remove
    other_changes: list[str] = []

    for c in changes:
        cl = c.lower()
        if cl.startswith("state changed"):
            state_change_str = c
        elif c.startswith("Added configured value in Backup B:"):
            a_needs.append(c.split("Added configured value in Backup B:", 1)[1].strip())
        elif c.startswith("Removed configured value from Backup B:"):
            b_needs.append(c.split("Removed configured value from Backup B:", 1)[1].strip())
        elif c.startswith("Added configured value:"):
            a_needs.append(c.split("Added configured value:", 1)[1].strip())
        elif c.startswith("Removed configured value:"):
            b_needs.append(c.split("Removed configured value:", 1)[1].strip())
        elif cl.startswith("policy is missing") or "no setting-level differences" in cl:
            pass  # covered by status header or intentionally suppressed
        else:
            other_changes.append(c)

    # ── ILT / targeting from evidence ────────────────────────────────────────
    ilt_kw  = ("ilt", "target", "wmi")
    ilt_ev  = [e for e in evidence if any(k in e.lower() for k in ilt_kw)]
    other_ev = [e for e in evidence if e not in ilt_ev]

    # ── per-status header + action wording ───────────────────────────────────
    if status in ("Added", "Missing in A"):
        header_color = C_GREEN
        header_text  = f"Update {backup_a_title} — add this policy to align with {backup_b_title}"
        action_label = f"Add to {backup_a_title}"
        action_color = C_GREEN
        state_show   = state_b
    elif status in ("Removed", "Missing in B"):
        header_color = C_RED
        header_text  = f"Update {backup_b_title} — add this policy to align with {backup_a_title}"
        action_label = f"Add to {backup_b_title}"
        action_color = C_RED
        state_show   = state_a
    else:  # Different
        header_color = C_ORANGE
        action_color = C_ORANGE
        state_show   = ""
        has_add        = bool(a_needs)
        has_rem        = bool(b_needs)
        has_state_diff = (state_a.lower() != state_b.lower()) and bool(state_a or state_b)
        if has_add and has_rem:
            n_a = len(a_needs)
            n_r = len(b_needs)
            header_text = (
                f"Update {backup_a_title} — add {n_a} setting{'s' if n_a != 1 else ''} "
                f"and remove {n_r} setting{'s' if n_r != 1 else ''} to align"
            )
        elif has_add:
            n = len(a_needs)
            header_text = (
                f"Update {backup_a_title} — add {n} setting{'s' if n != 1 else ''} "
                f"to align with {backup_b_title}"
            )
        elif has_rem:
            n = len(b_needs)
            header_text = (
                f"Update {backup_a_title} — remove {n} setting{'s' if n != 1 else ''} "
                f"to align with {backup_b_title}"
            )
        elif has_state_diff or state_change_str:
            header_text = (
                f"Update {backup_a_title} — change policy state to align with {backup_b_title}"
            )
        else:
            header_text = (
                f"Review {backup_a_title} — settings may need alignment with {backup_b_title}"
            )
        action_label = "Update the following"

    parts: list[str] = [f"<div style='font-size:13px; line-height:1.65; color:{C_TEXT};'>"]

    # ── backup identity strip ─────────────────────────────────────────────────
    parts.append(
        f"<table cellspacing='0' cellpadding='0'"
        f" style='width:100%; border-collapse:collapse; margin-bottom:14px;"
        f" border:1px solid {C_BORDER}; border-radius:4px;'>"
        f"<tr>"
        f"<td width='50%' style='padding:7px 12px; background:{C_RAISED};"
        f" border-right:1px solid {C_BORDER};'>"
        f"<span style='color:{C_MUTED}; font-size:10px; font-weight:700;"
        f" text-transform:uppercase; letter-spacing:0.4px;'>Backup A</span><br>"
        f"<span style='color:{C_LABEL}; font-size:12px;'>{_esc(backup_a_title)}</span>"
        f"</td>"
        f"<td width='50%' style='padding:7px 12px; background:{C_RAISED};'>"
        f"<span style='color:{C_MUTED}; font-size:10px; font-weight:700;"
        f" text-transform:uppercase; letter-spacing:0.4px;'>Backup B</span><br>"
        f"<span style='color:{C_LABEL}; font-size:12px;'>{_esc(backup_b_title)}</span>"
        f"</td>"
        f"</tr>"
        f"</table>"
    )

    # header banner
    parts.append(
        f"<p style='color:{header_color}; font-weight:800; font-size:12px;"
        f" margin:0 0 14px 0; text-transform:uppercase; letter-spacing:0.5px;"
        f" padding:8px 12px; background:{C_RAISED}; border-left:3px solid {header_color};'>"
        f"{_esc(header_text)}</p>"
    )

    # sub-heading
    parts.append(
        f"<p style='color:{C_BLUE}; font-weight:700; font-size:11px;"
        f" text-transform:uppercase; letter-spacing:0.5px; margin:0 0 10px 0;'>"
        f"To align the policies:</p>"
    )

    # ── document table ────────────────────────────────────────────────────────
    parts.append(
        f"<table cellspacing='0' cellpadding='0'"
        f" style='width:100%; border-collapse:collapse; margin-bottom:16px;'>"
    )

    def dr(label: str, body_html: str, lc: str = C_MUTED) -> str:
        return (
            f"<tr>"
            f"<td style='color:{lc}; font-size:11px; font-weight:700; text-transform:uppercase;"
            f" letter-spacing:0.3px; width:140px; white-space:nowrap; padding:7px 12px 7px 0;"
            f" vertical-align:top; border-bottom:1px solid {C_BORDER};'>{_esc(label)}</td>"
            f"<td style='color:{C_TEXT}; font-size:12px; line-height:1.6; padding:7px 0 7px 4px;"
            f" vertical-align:top; border-bottom:1px solid {C_BORDER};'>{body_html}</td>"
            f"</tr>"
        )

    def sep_row(label: str, color: str) -> str:
        return (
            f"<tr><td colspan='2' style='padding:12px 0 6px 0; color:{color};"
            f" font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:0.4px;"
            f" border-top:2px solid {C_BORDER};'>{_esc(label)}:</td></tr>"
        )

    if path:
        parts.append(dr("Path", f"<span style='color:{C_TEXT};'>{_esc(path)}</span>"))
    if name:
        parts.append(dr("Settings", f"<span style='color:{C_TEXT};'>{_esc(name)}</span>"))
    if supported:
        parts.append(dr("Supported On", f"<span style='color:{C_MUTED};'>{_esc(supported)}</span>"))

    parts.append(sep_row(action_label, action_color))

    # State
    if status == "Different":
        if state_a.lower() != state_b.lower() and (state_a or state_b):
            state_html = (
                f"<span style='color:{C_MUTED};'>{_esc(state_a or 'Not configured')}</span>"
                f"<span style='color:{C_ORANGE};'> &rarr; </span>"
                f"<span style='color:{C_ORANGE}; font-weight:700;'>"
                f"{_esc(state_b or 'Not configured')}</span>"
            )
            parts.append(dr("State", state_html, C_LABEL))
        elif state_change_str:
            parts.append(dr("State", f"<span style='color:{C_ORANGE};'>{_esc(state_change_str)}</span>", C_LABEL))
        elif state_b:
            parts.append(dr("State", f"<span style='color:{C_TEXT}; font-weight:700;'>{_esc(state_b)}</span>", C_LABEL))
    elif state_show:
        parts.append(dr("State", f"<span style='color:{C_TEXT}; font-weight:700;'>{_esc(state_show)}</span>", C_LABEL))

    # Additional setting information
    if status == "Different":
        add_lines: list[str] = []
        for v in a_needs:
            add_lines.append(f"<span style='color:{C_GREEN};'>+ {_esc(v)}</span>")
        for v in b_needs:
            add_lines.append(f"<span style='color:{C_RED};'>&#8722; {_esc(v)}</span>")
        if add_lines:
            parts.append(dr("Additional setting information", "<br>".join(add_lines), C_LABEL))
        elif other_changes:
            parts.append(dr(
                "Additional setting information",
                "<br>".join(f"<span style='color:{C_TEXT};'>{_esc(c)}</span>" for c in other_changes),
                C_LABEL,
            ))
            other_changes = []
    else:
        all_vals = a_needs + b_needs
        if all_vals:
            parts.append(dr(
                "Additional setting information",
                "<br>".join(f"<span style='color:{C_TEXT};'>{_esc(v)}</span>" for v in all_vals),
                C_LABEL,
            ))

    # Targeting information
    if ilt_ev:
        parts.append(dr(
            "Targeting information",
            "<br>".join(f"<span style='color:{C_TEXT};'>{_esc(i)}</span>" for i in ilt_ev),
            C_LABEL,
        ))
    else:
        parts.append(dr(
            "Targeting information",
            f"<span style='color:{C_MUTED}; font-style:italic;'>None</span>",
            C_LABEL,
        ))

    parts.append("</table>")

    # ── overflow changes not captured above ───────────────────────────────────
    if other_changes:
        parts.append(
            f"<p style='color:{C_LABEL}; font-weight:800; font-size:12px; margin:14px 0 8px 0;"
            f" text-transform:uppercase; letter-spacing:0.5px; padding:5px 10px;"
            f" background:{C_RAISED}; border-left:3px solid {C_LABEL};'>Additional Changes</p>"
        )
        parts.append("<ul style='margin:0 0 16px 0; padding-left:18px; line-height:1.8;'>")
        for c in other_changes:
            cl = c.lower()
            color = C_GREEN if cl.startswith("added") else (C_RED if cl.startswith("removed") else C_TEXT)
            parts.append(f"<li style='color:{color}; padding:2px 0;'>{_esc(c)}</li>")
        parts.append("</ul>")

    # ── supporting evidence (non-ILT) ─────────────────────────────────────────
    if other_ev:
        parts.append(
            f"<p style='color:{C_LABEL}; font-weight:800; font-size:12px; margin:14px 0 8px 0;"
            f" text-transform:uppercase; letter-spacing:0.5px; padding:5px 10px;"
            f" background:{C_RAISED}; border-left:3px solid {C_LABEL};'>Supporting Evidence</p>"
        )
        parts.append("<ul style='margin:0; padding-left:18px; line-height:1.8;'>")
        for ev in other_ev:
            ev_lower = ev.lower()
            accent = C_GREEN if "added" in ev_lower else (C_RED if ("removed" in ev_lower or "missing" in ev_lower) else C_LABEL)
            if "): " in ev:
                src, _, desc = ev.partition("): ")
                parts.append(
                    f"<li style='padding:3px 0;'>"
                    f"<span style='color:{C_MUTED}; font-size:11px;'>{_esc(src)})</span><br>"
                    f"<span style='color:{accent}; padding-left:10px;'>&#8627; {_esc(desc)}</span>"
                    f"</li>"
                )
            else:
                parts.append(f"<li style='color:{accent}; padding:3px 0;'>{_esc(ev)}</li>")
        parts.append("</ul>")

    # ── policy definition footer ──────────────────────────────────────────────
    def_rows: list[tuple[str, str]] = []
    if cat and cat not in ("Not reported", "Not categorized"):
        def_rows.append(("Category", cat))
    if policy_type:
        def_rows.append(("Type", policy_type))
    if supported:
        def_rows.append(("Supported On", supported))
    source = str(finding.get("source") or "").strip()
    if source:
        def_rows.append(("Source", source))

    if def_rows:
        parts.append(
            f"<p style='color:{C_LABEL}; font-weight:800; font-size:12px; margin:14px 0 8px 0;"
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
                f"<td style='color:{C_MUTED}; font-size:11px; font-weight:700; text-transform:uppercase;"
                f" letter-spacing:0.4px; width:95px; white-space:nowrap; padding:5px 10px 5px 0;"
                f" vertical-align:top; border-bottom:1px solid {C_BORDER};'>{_esc(lbl)}</td>"
                f"<td style='color:{C_TEXT}; font-size:12px; padding:5px 0; vertical-align:top;"
                f" border-bottom:1px solid {C_BORDER};'>{_esc(val)}</td>"
                f"</tr>"
            )
        parts.append("</table>")

    parts.append("</div>")
    return "".join(parts)


def _full_finding_detail_html(
    finding: dict[str, Any],
    backup_a_title: str,
    backup_b_title: str,
) -> str:
    colors = {
        "raised": "#202123",
        "panel": "#151617",
        "border": "rgba(255,255,255,0.08)",
        "text": "#F4F6F8",
        "muted": "#85888E",
        "label": "#C0C3C7",
        "orange": "#FF8A1F",
        "blue": "#82B6FF",
    }
    status = str(finding.get("status") or "Unknown")
    review = finding.get("review") if isinstance(finding.get("review"), dict) else {}
    review_status = normalize_review_status(review.get("status") or "Pending Review")
    changes = [str(c) for c in (finding.get("changes") or []) if c]
    evidence = [str(e) for e in (finding.get("supporting_evidence") or []) if e]
    policy_a = finding.get("policy_a") if isinstance(finding.get("policy_a"), dict) else None
    policy_b = finding.get("policy_b") if isinstance(finding.get("policy_b"), dict) else None

    html = [
        f"<div style='font-size:13px; line-height:1.55; color:{colors['text']};'>",
        (
            f"<div style='background:{colors['raised']}; border:1px solid {colors['border']};"
            f" border-left:3px solid {colors['orange']}; padding:9px 12px; margin:0 0 12px 0;'>"
            f"<div style='color:{colors['muted']}; font-size:10px; font-weight:800; text-transform:uppercase;'>Review Context</div>"
            f"<div style='font-weight:800; color:{colors['text']}; margin-top:2px;'>"
            f"{_esc(status)} &nbsp;·&nbsp; {_esc(normalize_review_status(review.get('status') or 'Pending Review'))}</div>"
            "</div>"
        ),
    ]
    action_plan = _saved_review_action_plan_html(finding, review_status, backup_a_title, backup_b_title, colors)
    if action_plan:
        html.append(action_plan)
    if changes:
        html.append(_summary_card_html("Detected Delta", changes, colors["orange"], colors))
    html.append(
        f"<p style='color:{colors['blue']}; font-weight:800; font-size:11px; text-transform:uppercase;"
        f" letter-spacing:0.5px; margin:14px 0 8px 0;'>Complete configuration data</p>"
    )
    html.append(_policy_config_card_html("Backup A", backup_a_title, policy_a, colors["label"], colors))
    html.append(_policy_config_card_html("Backup B", backup_b_title, policy_b, colors["orange"], colors))
    if evidence:
        html.append(_summary_card_html("Supporting Evidence", evidence, colors["label"], colors))
    html.append("</div>")
    return "".join(html)


def _saved_review_action_plan_html(
    finding: dict[str, Any],
    review_status: str,
    backup_a_title: str,
    backup_b_title: str,
    colors: dict[str, str],
) -> str:
    policy_a = finding.get("policy_a") if isinstance(finding.get("policy_a"), dict) else None
    policy_b = finding.get("policy_b") if isinstance(finding.get("policy_b"), dict) else None
    name = str(
        (policy_b or {}).get("name")
        or (policy_a or {}).get("name")
        or finding.get("name")
        or finding.get("key")
        or "Policy"
    )

    if review_status == "Make Changes to A":
        title = f"Update {name} in Backup A"
        lead = "Apply the Backup B configuration below to Backup A."
        desired = _policy_config_card_html("Settings to apply to Backup A", backup_b_title, policy_b, colors["blue"], colors)
        current = _policy_config_card_html("Current settings in Backup A", backup_a_title, policy_a, colors["label"], colors)
    elif review_status == "Make Changes to B":
        title = f"Update {name} in Backup B"
        lead = "Apply the Backup A configuration below to Backup B."
        desired = _policy_config_card_html("Settings to apply to Backup B", backup_a_title, policy_a, colors["blue"], colors)
        current = _policy_config_card_html("Current settings in Backup B", backup_b_title, policy_b, colors["label"], colors)
    elif review_status == "Remove From A":
        title = f"Remove {name} from Backup A"
        lead = "Remove or unconfigure the item shown below from Backup A."
        desired = _policy_config_card_html("Settings currently in Backup A", backup_a_title, policy_a, colors["blue"], colors)
        current = ""
    elif review_status == "Remove From B":
        title = f"Remove {name} from Backup B"
        lead = "Remove or unconfigure the item shown below from Backup B."
        desired = _policy_config_card_html("Settings currently in Backup B", backup_b_title, policy_b, colors["blue"], colors)
        current = ""
    else:
        return ""

    return (
        f"<div style='background:{colors['raised']}; border:1px solid {colors['border']};"
        f" border-left:4px solid {colors['blue']}; padding:12px; margin:0 0 12px 0;'>"
        f"<div style='color:{colors['blue']}; font-size:11px; font-weight:800; text-transform:uppercase;'>Review Action Plan</div>"
        f"<div style='font-size:14px; font-weight:800; color:{colors['text']}; margin-top:4px;'>{_esc(title)}</div>"
        f"<div style='color:{colors['label']}; margin:3px 0 10px 0;'>{_esc(lead)}</div>"
        f"{desired}{current}</div>"
    )


def _policy_config_card_html(
    side_label: str,
    backup_title: str,
    policy: dict[str, Any] | None,
    accent: str,
    colors: dict[str, str],
) -> str:
    if not policy:
        return (
            f"<div style='border:1px solid {colors['border']}; border-left:3px solid {accent};"
            f" background:{colors['panel']}; padding:12px; margin:0 0 12px 0;'>"
            f"<div style='color:{accent}; font-weight:800;'>{_esc(side_label)} · {_esc(backup_title)}</div>"
            f"<p style='color:{colors['muted']}; margin:8px 0 0 0;'>This item is not present in this backup.</p>"
            "</div>"
        )

    settings = [str(s) for s in (policy.get("settings") or [])]
    sections = _split_saved_policy_sections(settings)
    meta_rows = [
        ("Name", str(policy.get("name") or "Unknown")),
        ("State", str(policy.get("state") or "Not reported")),
        ("Path", _policy_path(policy)),
        ("Type", str(policy.get("policy_type") or "Unknown")),
        ("Source", str(policy.get("source") or "gpreport.xml")),
    ]
    supported = str(policy.get("supported") or "").strip()
    if supported:
        meta_rows.append(("Supported On", supported))

    html = [
        f"<div style='border:1px solid {colors['border']}; border-left:3px solid {accent};"
        f" background:{colors['panel']}; padding:12px; margin:0 0 12px 0;'>",
        f"<div style='color:{accent}; font-weight:800; margin-bottom:8px;'>{_esc(side_label)} · {_esc(backup_title)}</div>",
        _kv_table(meta_rows, colors),
        _section_table("Properties", sections["properties"], colors),
    ]
    if sections["common"]:
        html.append(_section_table("Common Options", sections["common"], colors))
    if sections["targeting"]:
        html.append(_targeting_cards_html(sections["targeting"], colors))
    explain = str(policy.get("explain") or "").strip()
    if explain:
        html.append(
            f"<div style='margin-top:10px;'><div style='color:{colors['orange']}; font-size:11px; font-weight:800;"
            f" text-transform:uppercase;'>Explanation</div>"
            f"<pre style='white-space:pre-wrap; color:{colors['text']}; background:{colors['raised']};"
            f" border:1px solid {colors['border']}; padding:8px; margin:5px 0 0 0;'>{_esc(explain)}</pre></div>"
        )
    html.append("</div>")
    return "".join(html)


def _policy_path(policy: dict[str, Any]) -> str:
    scope = str(policy.get("scope") or "")
    category = str(policy.get("category") or "").strip()
    if category and category not in ("Not reported", "Not categorized"):
        return f"{scope} > {category}" if scope else category
    return scope or "Not reported"


def _split_saved_policy_sections(settings: list[str]) -> dict[str, list[str]]:
    sections = {"properties": [], "common": [], "targeting": []}
    current = "properties"
    for setting in settings:
        if "Properties" in setting and "──" in setting:
            current = "properties"
            continue
        if "Common Options" in setting and "──" in setting:
            current = "common"
            continue
        if "Item-Level Targeting" in setting and "──" in setting:
            current = "targeting"
            continue
        if "Properties" in setting and setting.strip().startswith("â"):
            current = "properties"
            continue
        if "Common Options" in setting and setting.strip().startswith("â"):
            current = "common"
            continue
        if "Item-Level Targeting" in setting and setting.strip().startswith("â"):
            current = "targeting"
            continue
        sections[current].append(setting)
    return sections


def _section_table(title: str, settings: list[str], colors: dict[str, str]) -> str:
    if not settings:
        return ""
    rows = [_setting_pair(setting) for setting in settings if str(setting).strip()]
    return (
        f"<div style='margin-top:10px;'><div style='color:{colors['orange']}; font-size:11px; font-weight:800;"
        f" text-transform:uppercase;'>{_esc(title)}</div>{_kv_table(rows, colors)}</div>"
    )


def _targeting_cards_html(settings: list[str], colors: dict[str, str]) -> str:
    cards: list[str] = []
    current_title = "Targeting Rule"
    current_rows: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal current_title, current_rows
        if not current_rows and current_title == "Targeting Rule":
            return
        cards.append(
            f"<div style='background:{colors['raised']}; border:1px solid {colors['border']};"
            f" border-left:3px solid {colors['blue']}; padding:8px; margin:6px 0;'>"
            f"<div style='color:{colors['blue']}; font-weight:800; margin-bottom:5px;'>{_esc(current_title)}</div>"
            f"{_kv_table(current_rows, colors)}</div>"
        )
        current_title = "Targeting Rule"
        current_rows = []

    for setting in settings:
        clean = str(setting).strip()
        if not clean:
            continue
        if clean.startswith("•") or clean.startswith("â€¢"):
            flush()
            current_title = _clean_saved_setting(clean)
        else:
            current_rows.append(_setting_pair(clean))
    flush()
    if not cards:
        return ""
    return (
        f"<div style='margin-top:10px;'><div style='color:{colors['blue']}; font-size:11px; font-weight:800;"
        f" text-transform:uppercase;'>Item-Level Targeting</div>{''.join(cards)}</div>"
    )


def _kv_table(rows: list[tuple[str, str]], colors: dict[str, str]) -> str:
    if not rows:
        return f"<p style='color:{colors['muted']}; margin:4px 0;'>No values recorded.</p>"
    body = ""
    for label, value in rows:
        display_value = _esc(value) if value else f"<span style='color:{colors['muted']};'>(blank)</span>"
        body += (
            "<tr>"
            f"<td style='color:{colors['muted']}; font-weight:800; width:34%; padding:4px 10px 4px 0;"
            f" border-bottom:1px solid {colors['border']}; vertical-align:top;'>{_esc(label)}</td>"
            f"<td style='color:{colors['text']}; padding:4px 0; border-bottom:1px solid {colors['border']};"
            f" vertical-align:top;'>{display_value}</td>"
            "</tr>"
        )
    return (
        f"<table cellspacing='0' cellpadding='0' width='100%' style='border-collapse:collapse;"
        f" background:{colors['raised']}; border:1px solid {colors['border']}; margin-top:5px;'>{body}</table>"
    )


def _setting_pair(setting: str) -> tuple[str, str]:
    clean = _clean_saved_setting(setting)
    if ":" not in clean:
        return clean, ""
    label, value = clean.split(":", 1)
    return label.strip(), value.strip().lstrip(":").strip()


def _clean_saved_setting(setting: str) -> str:
    return str(setting).strip().lstrip("•").lstrip("â€¢").strip().replace("::", ":")


def _summary_card_html(title: str, lines: list[str], accent: str, colors: dict[str, str]) -> str:
    rows = "".join(f"<li style='padding:2px 0; color:{colors['text']};'>{_esc(line)}</li>" for line in lines)
    return (
        f"<div style='background:{colors['raised']}; border:1px solid {colors['border']};"
        f" border-left:3px solid {accent}; padding:8px 12px; margin:0 0 12px 0;'>"
        f"<div style='color:{accent}; font-size:11px; font-weight:800; text-transform:uppercase;'>{_esc(title)}</div>"
        f"<ul style='margin:6px 0 0 0; padding-left:18px;'>{rows}</ul></div>"
    )


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
        review_status = _esc(normalize_review_status(review.get("status") or "Pending Review"))
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
<p style="color:#888;">{summary.get('total_items',0)} compared &nbsp;·&nbsp; {summary.get('actionable',0)} actionable &nbsp;·&nbsp; {summary.get('ignored',0)} ignored</p>
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
