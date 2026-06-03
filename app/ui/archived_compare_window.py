from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

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

_REVIEW_PRIORITIES = ["Normal", "Low", "Medium", "High", "Critical"]


class ArchivedCompareWindow(QDialog):
    def __init__(self, record_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record_path = record_path
        self.payload = load_compare_record_payload(record_path)
        self.findings = _record_findings(self.payload)
        self.current_key = ""
        self.loading = False
        self.reviews = {
            str(item.get("key", "")): dict(item.get("review", {}))
            for item in self.findings
            if isinstance(item, dict) and item.get("key")
        }

        self.setWindowTitle(f"Saved Compare Review - {self.payload.get('title', 'Saved comparison')}")
        self.setWindowIcon(app_icon())
        self.resize(1320, 800)
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

        save_btn = QPushButton("Save Review")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_all)

        layout.addLayout(copy, 1)
        layout.addWidget(save_btn)
        return panel

    def _build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        list_panel = QFrame()
        list_panel.setObjectName("Panel")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_layout.setSpacing(8)
        list_title = QLabel("Findings")
        list_title.setObjectName("PanelTitle")
        list_hint = QLabel(f"{len(self.findings)} actionable finding(s)")
        list_hint.setObjectName("Muted")
        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        for finding in self.findings:
            item = QListWidgetItem(_finding_label(finding))
            item.setData(Qt.ItemDataRole.UserRole, finding)
            item.setToolTip(str(finding.get("name") or finding.get("key") or "Unknown"))
            self.list_widget.addItem(item)
        list_layout.addWidget(list_title)
        list_layout.addWidget(list_hint)
        list_layout.addWidget(self.list_widget, 1)

        center = QFrame()
        center.setObjectName("Panel")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(10)

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
        state_layout.setSpacing(8)
        self.status_badge_slot = QHBoxLayout()
        self.status_badge_slot.setSpacing(6)
        self.state_label = QLabel("")
        self.state_label.setObjectName("StatusLabel")
        state_layout.addLayout(self.status_badge_slot)
        state_layout.addWidget(self.state_label, 1)

        self.detail_text = QTextEdit()
        self.detail_text.setObjectName("DetailText")
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(260)

        center_layout.addWidget(self.detail_title)
        center_layout.addWidget(self.detail_meta)
        center_layout.addWidget(self.state_strip)
        center_layout.addWidget(self.detail_text, 1)

        review_panel = QFrame()
        review_panel.setObjectName("Panel")
        review_panel.setMinimumWidth(320)
        review_layout = QVBoxLayout(review_panel)
        review_layout.setContentsMargins(16, 16, 16, 16)
        review_layout.setSpacing(8)

        review_title = QLabel("Review")
        review_title.setObjectName("PanelTitle")
        review_layout.addWidget(review_title)

        self.review_status = QComboBox()
        self.review_status.addItems(_REVIEW_STATUSES)
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
        self.notes_box.setMinimumHeight(150)

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
        splitter.setSizes([260, 650, 410])
        return splitter

    def _on_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
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
        self.state_label.setText(
            f"{finding.get('state_a', '') or 'Not present'} -> {finding.get('state_b', '') or 'Not present'}"
        )
        _replace_badge(self.status_badge_slot, badge(str(finding.get("status") or "Unknown"), _status_badge_state(finding), min_width=112))
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

    def _save_all(self) -> None:
        self._save_current()
        update_compare_record_reviews(self.record_path, self.reviews)
        self.accept()


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


def _finding_label(finding: dict[str, Any]) -> str:
    status = str(finding.get("status") or "Unknown")
    name = str(finding.get("name") or finding.get("key") or "Unknown")
    return f"{status}  |  {_short(name, 64)}"


def _finding_meta(finding: dict[str, Any]) -> str:
    return f"{finding.get('scope', 'Unknown')}  |  Archived compare finding"


def _finding_detail_html(finding: dict[str, Any]) -> str:
    parts = [
        "<div style='font-size:13px; line-height:1.55;'>",
        "<p style='font-weight:800; color:#ff8a1f; margin:0 0 8px 0;'>Actual Delta</p>",
        "<div style='background:#101112; border:1px solid rgba(255,255,255,.08); padding:10px 12px; border-radius:4px;'>",
    ]
    changes = finding.get("changes")
    if isinstance(changes, list) and changes:
        parts.append("<ul>")
        parts.extend(f"<li>{_esc(change)}</li>" for change in changes)
        parts.append("</ul>")
    else:
        parts.append("<p>No setting-level changes were recorded in the archive.</p>")
    parts.append("</div>")

    evidence = finding.get("supporting_evidence")
    if isinstance(evidence, list) and evidence:
        parts.append("<p style='font-weight:800; color:#c0c3c7; margin:16px 0 8px 0;'>Supporting Evidence</p>")
        parts.append("<div style='background:#101112; border:1px solid rgba(255,255,255,.08); padding:10px 12px; border-radius:4px;'>")
        parts.append("<ul>")
        parts.extend(f"<li>{_esc(item)}</li>" for item in evidence)
        parts.append("</ul></div>")

    parts.append("</div>")
    return "".join(parts)


def _replace_badge(slot: QHBoxLayout, replacement: QLabel) -> None:
    while slot.count():
        item = slot.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    slot.addWidget(replacement)


def _status_badge_state(finding: dict[str, Any]) -> str:
    return {
        "Changed": "changed",
        "Added": "added",
        "Missing in A": "added",
        "Removed": "removed",
        "Missing in B": "removed",
    }.get(str(finding.get("status") or ""), "unknown")


def _short(value: str, limit: int) -> str:
    clean = " ".join((value or "").split())
    return clean if len(clean) <= limit else f"{clean[:limit - 3]}..."


def _esc(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
