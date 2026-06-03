from __future__ import annotations

import re
from datetime import datetime
from html import escape
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.branding import app_icon
from app.ui.styles import THEMES
from app.gpo.ilt_parser import ILT_HEADER
from app.gpo.comparison_model import (
    PolicyDiff,
    build_backup_diff,
    filter_diffs,
    setting_changes,
    summarize_diffs,
)

_REVIEW_STATUSES = [
    "Pending Review",
    "No Action Required",
    "Update Required",
    "Under Investigation",
    "Escalated",
]

_REVIEW_PRIORITIES = ["Normal", "Low", "Medium", "High", "Critical"]
from app.gpo.gpo_model import GpoBackup
from app.gpo.gpreport_parser import load_gpreport
from app.library_store import save_compare_record
from app.reports.compare_report import html_report, json_report, markdown_report
from app.review_store import load_review_notes, save_review_notes
from app.ui.widgets import badge


_PAGE_SIZE = 50


def _html_theme(t: dict) -> dict:
    def _rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    s, d, o = _rgb(t["success"]), _rgb(t["danger"]), _rgb(t["orange"])
    return {
        "code_bg":          t["app"],
        "card_bg":          t["panel"],
        "border":           t["raised"],
        "text":             t["text"],
        "label":            t["secondary"],
        "orange":           t["orange"],
        "success":          t["success"],
        "danger":           t["danger"],
        "added_bg":         f"rgba({s[0]},{s[1]},{s[2]},0.18)",
        "removed_bg":       f"rgba({d[0]},{d[1]},{d[2]},0.18)",
        "status_added":     f"rgba({s[0]},{s[1]},{s[2]},0.18)",
        "status_removed":   f"rgba({d[0]},{d[1]},{d[2]},0.18)",
        "status_changed":   f"rgba({o[0]},{o[1]},{o[2]},0.18)",
        "status_unchanged": t["raised"],
    }


class CompareWindow(QDialog):
    def __init__(self, backup_a: GpoBackup, backup_b: GpoBackup, settings: dict[str, Any], parent=None) -> None:
        super().__init__(parent)

        self.backup_a = backup_a
        self.backup_b = backup_b
        self.report_a = load_gpreport(backup_a.path)
        self.report_b = load_gpreport(backup_b.path)
        self.diff_items = build_backup_diff(backup_a, backup_b, self.report_a, self.report_b)
        self.filtered_items: list[PolicyDiff] = []
        self.review_notes: dict[str, dict[str, str]] = load_review_notes(backup_a.path, backup_b.path)
        self.current_review_key = ""
        self.loading_review = False
        self.expanded_key = ""
        self.review_status: QComboBox | None = None
        self.review_priority: QComboBox | None = None
        self.review_owner_box: QLineEdit | None = None
        self.review_ticket_box: QLineEdit | None = None
        self.review_tags_box: QLineEdit | None = None
        self.review_notes_box: QTextEdit | None = None
        self._accordion_rows: list[QFrame] = []
        self._review_badges: dict[str, QLabel] = {}
        self._visible_count: int = _PAGE_SIZE
        self._expanded_row: QFrame | None = None
        self._expanded_detail_text: QTextEdit | None = None
        self._scroll_to_expanded_pending = False
        self._review_save_timer = QTimer(self)
        self._review_save_timer.setSingleShot(True)
        self._review_save_timer.setInterval(450)
        self._review_save_timer.timeout.connect(self._save_review_for_current_item)

        theme_name = settings.get("app", {}).get("theme", "executive_dark")
        self._ht = _html_theme(THEMES.get(theme_name, THEMES["executive_dark"]))

        self.title_a = self.report_a.name if self.report_a and self.report_a.name else backup_a.name
        self.title_b = self.report_b.name if self.report_b and self.report_b.name else backup_b.name

        self.setWindowTitle(f"Compare GPOs - {self.title_a} vs {self.title_b}")
        self.setWindowIcon(app_icon())
        self.resize(1320, 800)
        self.setMinimumSize(980, 640)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowSystemMenuHint |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addWidget(self._build_filter_bar())

        root.addWidget(self._build_change_list_panel(), 1)
        self._populate_filters()
        self._apply_filters()
        self._update_review_progress()

        QShortcut(QKeySequence(Qt.Key.Key_Down), self).activated.connect(self._navigate_next)
        QShortcut(QKeySequence(Qt.Key.Key_Up), self).activated.connect(self._navigate_prev)

    def closeEvent(self, event) -> None:
        self._save_review_for_current_item()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._adjust_expanded_detail_height)

    def _build_header(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")
        panel.setMaximumHeight(104)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        copy = QVBoxLayout()
        copy.setSpacing(4)

        title = QLabel("Compare Group Policy Backups")
        title.setObjectName("Title")

        subtitle = QLabel(f"Backup A: {self.title_a}\nBackup B: {self.title_b}")
        subtitle.setObjectName("Muted")

        self.executive_summary_label = QLabel(_compact_summary(self.diff_items))
        self.executive_summary_label.setObjectName("Muted")

        copy.addWidget(title)
        copy.addWidget(subtitle)
        copy.addWidget(self.executive_summary_label)

        export_button = QPushButton("Export Markdown")
        export_button.setObjectName("GhostButton")
        export_button.clicked.connect(self._export_markdown)

        html_button = QPushButton("Export HTML")
        html_button.setObjectName("GhostButton")
        html_button.clicked.connect(self._export_html)

        json_button = QPushButton("Export JSON")
        json_button.setObjectName("GhostButton")
        json_button.clicked.connect(self._export_json)

        save_button = QPushButton("Save to Library")
        save_button.setObjectName("PrimaryButton")
        save_button.clicked.connect(self._save_to_library)

        layout.addLayout(copy, 1)
        layout.addWidget(export_button)
        layout.addWidget(html_button)
        layout.addWidget(json_button)
        layout.addWidget(save_button)

        return panel

    def _build_filter_bar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("FilterBar")
        panel.setMaximumHeight(58)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search compared policies...")

        self.status_filter = QComboBox()
        self.status_filter.setMinimumWidth(130)

        self.scope_filter = QComboBox()
        self.scope_filter.setMinimumWidth(138)

        self.review_filter = QComboBox()
        self.review_filter.setMinimumWidth(160)

        self.priority_filter = QComboBox()
        self.priority_filter.setMinimumWidth(130)

        self.actionable_only = QCheckBox("Actionable")
        self.actionable_only.setObjectName("Muted")
        self.actionable_only.setChecked(True)

        self.clear_button = QPushButton("Clear Filters")
        self.clear_button.setObjectName("GhostButton")

        self.result_count = QLabel()
        self.result_count.setObjectName("Muted")

        self.review_progress_label = QLabel()
        self.review_progress_label.setObjectName("Muted")

        layout.addWidget(self.search_box, 1)
        layout.addWidget(self.status_filter)
        layout.addWidget(self.scope_filter)
        layout.addWidget(self.review_filter)
        layout.addWidget(self.priority_filter)
        layout.addWidget(self.actionable_only)
        layout.addWidget(self.clear_button)
        layout.addWidget(self.result_count)
        layout.addWidget(self.review_progress_label)

        # Debounce text search — dropdowns apply immediately
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filters)
        self.search_box.textChanged.connect(lambda: self._search_timer.start())

        self.status_filter.currentTextChanged.connect(self._apply_filters)
        self.scope_filter.currentTextChanged.connect(self._apply_filters)
        self.review_filter.currentTextChanged.connect(self._apply_filters)
        self.priority_filter.currentTextChanged.connect(self._apply_filters)
        self.actionable_only.stateChanged.connect(self._apply_filters)
        self.clear_button.clicked.connect(self._clear_filters)

        return panel

    def _build_change_list_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("Change List")
        title.setObjectName("PanelTitle")

        self.change_list_summary = QLabel("No changes shown")
        self.change_list_summary.setObjectName("Muted")

        mark_all_button = QPushButton("Mark All As…")
        mark_all_button.setObjectName("GhostButton")
        mark_all_button.clicked.connect(self._mark_all_as)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.change_list_summary)
        header.addWidget(mark_all_button)

        self.change_list_content = QWidget()
        self.change_list_content.setObjectName("AccordionContent")

        self.change_list_layout = QVBoxLayout(self.change_list_content)
        self.change_list_layout.setContentsMargins(0, 0, 0, 0)
        self.change_list_layout.setSpacing(8)

        self.change_scroll = QScrollArea()
        self.change_scroll.setWidgetResizable(True)
        self.change_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.change_scroll.setWidget(self.change_list_content)

        layout.addLayout(header)
        layout.addWidget(self.change_scroll, 1)

        return panel

    def _populate_filters(self) -> None:
        self.status_filter.clear()
        self.status_filter.addItems(["All Changes", "Missing in A", "Changed", "Missing in B", "Same"])

        self.scope_filter.clear()
        self.scope_filter.addItems(["All Scopes", "Computer Configuration", "User Configuration"])

        self.review_filter.clear()
        self.review_filter.addItems(["All Reviews"] + _REVIEW_STATUSES)

        self.priority_filter.clear()
        self.priority_filter.addItems(["All Priorities"] + _REVIEW_PRIORITIES)

    def _clear_filters(self) -> None:
        self.search_box.clear()
        self.status_filter.setCurrentIndex(0)
        self.scope_filter.setCurrentIndex(0)
        self.review_filter.setCurrentIndex(0)
        self.priority_filter.setCurrentIndex(0)
        self.actionable_only.setChecked(True)
        self._apply_filters()

    def _apply_filters(self) -> None:
        filtered_items = filter_diffs(
            self.diff_items,
            search_text=self.search_box.text(),
            status_text=_status_filter_value(self.status_filter.currentText()),
            scope_text=self.scope_filter.currentText(),
        )
        if self.actionable_only.isChecked():
            filtered_items = [item for item in filtered_items if item.status != "Unchanged"]

        if self.review_filter.currentText() != "All Reviews":
            filtered_items = [
                item for item in filtered_items if self._review_for_item(item)["status"] == self.review_filter.currentText()
            ]
        if self.priority_filter.currentText() != "All Priorities":
            filtered_items = [
                item for item in filtered_items
                if self._review_for_item(item)["priority"] == self.priority_filter.currentText()
            ]

        self.filtered_items = filtered_items
        self._visible_count = _PAGE_SIZE
        self._populate_accordion(self.filtered_items)

    def _populate_accordion(self, items: list[PolicyDiff]) -> None:
        self._save_review_for_current_item()
        self._clear_change_list_layout()
        self.current_review_key = ""
        self.review_disposition = None
        self.review_impact = None
        self.review_owner_box = None
        self.review_ticket_box = None
        self.review_note_box = None
        self.review_points_box = None
        self._accordion_rows = []
        self._review_badges = {}
        self._expanded_row = None
        self._expanded_detail_text = None
        self._scroll_to_expanded_pending = bool(self.expanded_key)
        total_actionable = sum(1 for i in self.diff_items if i.status != "Unchanged")
        count_text = f"{len(items)} of {total_actionable} shown"
        self.result_count.setText(count_text)
        self.change_list_summary.setText(count_text)
        self._sync_filter_indicator()

        visible_keys = {item.key for item in items}
        if self.expanded_key and self.expanded_key not in visible_keys:
            self.expanded_key = items[0].key if items else ""

        if not items:
            empty = QLabel("No comparison results match the current filters.")
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(180)
            self.change_list_layout.addWidget(empty)
            self.change_list_layout.addStretch()
            return

        visible = items[: self._visible_count]
        for item in visible:
            row = self._build_accordion_row(item)
            self._accordion_rows.append(row)
            self.change_list_layout.addWidget(row)

        remaining = len(items) - len(visible)
        if remaining > 0:
            next_batch = min(_PAGE_SIZE, remaining)
            load_btn = QPushButton(f"Show {next_batch} more  ({remaining} remaining)")
            load_btn.setObjectName("GhostButton")
            load_btn.clicked.connect(self._load_more_rows)
            self.change_list_layout.addWidget(load_btn)

        self.change_list_layout.addStretch()
        QTimer.singleShot(0, self._adjust_expanded_detail_height)

    def _clear_change_list_layout(self) -> None:
        while self.change_list_layout.count():
            item = self.change_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        self.change_list_content.updateGeometry()
        self.change_scroll.viewport().update()

    def _build_accordion_row(self, item: PolicyDiff) -> QFrame:
        row = QFrame()
        row.setObjectName("AccordionRow")
        row.setProperty("expanded", item.key == self.expanded_key)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        policy_name = item.policy_b.name if item.policy_b else item.policy_a.name if item.policy_a else "Unknown"
        policy_type = _policy_type(item)
        status_label = _status_label(item.status)

        status_badge = badge(status_label, item.status.lower(), min_width=112)

        scope_label = QLabel(_short_cell(item.scope, 30))
        scope_label.setObjectName("Muted")
        scope_label.setToolTip(item.scope)

        type_label = QLabel(_short_cell(policy_type, 28))
        type_label.setObjectName("Muted")
        type_label.setToolTip(policy_type)

        name_label = QLabel(policy_name)
        name_label.setObjectName("StatusLabel")
        name_label.setWordWrap(True)
        name_label.setToolTip(policy_name)

        review_status = self.review_notes.get(item.key, {}).get("status", "Pending Review")
        review_badge = badge(review_status, _review_badge_state(review_status), min_width=128)
        review_badge.setVisible(review_status != "Pending Review")
        self._review_badges[item.key] = review_badge

        toggle = QPushButton("Collapse" if item.key == self.expanded_key else "Open")
        toggle.setObjectName("GhostButton")
        toggle.clicked.connect(lambda checked=False, key=item.key: self._toggle_expanded_row(key))

        # Wrap the header in a frame so clicking anywhere on the row (not just
        # the button) expands/collapses it.  Button clicks are consumed by the
        # button itself and do not propagate to the frame, so the button still
        # works independently.
        header_frame = QFrame()
        header_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(status_badge)
        header.addWidget(scope_label)
        header.addWidget(type_label)
        header.addWidget(name_label, 1)
        header.addWidget(review_badge)
        header.addWidget(toggle)

        _key = item.key
        header_frame.mousePressEvent = lambda event, key=_key: (
            self._toggle_expanded_row(key)
            if event.button() == Qt.MouseButton.LeftButton
            else None
        )

        layout.addWidget(header_frame)

        if item.key == self.expanded_key:
            self._expanded_row = row
            self.current_review_key = item.key
            layout.addWidget(self._build_expanded_details(item))

        return row

    def _load_more_rows(self) -> None:
        self._visible_count += _PAGE_SIZE
        self._populate_accordion(self.filtered_items)

    def _toggle_expanded_row(self, key: str) -> None:
        self._save_review_for_current_item()
        self.expanded_key = "" if self.expanded_key == key else key
        if self.expanded_key:
            idx = next((i for i, it in enumerate(self.filtered_items) if it.key == self.expanded_key), 0)
            self._visible_count = max(self._visible_count, idx + 1)
        self._populate_accordion(self.filtered_items)

    def _change_summary_text(self, item: PolicyDiff) -> str:
        if item.status == "Added":
            return "This policy exists in Backup B but was not present in Backup A."

        if item.status == "Removed":
            return "This policy existed in Backup A but is not present in Backup B."

        if item.status == "Changed":
            return "This policy exists in both backups, but one or more reported values changed."

        return "This policy appears unchanged between the selected backups."

    def _build_expanded_details(self, item: PolicyDiff) -> QFrame:
        panel = QFrame()
        panel.setObjectName("AccordionDetail")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        summary = QLabel(self._change_summary_text(item))
        summary.setObjectName("Muted")
        summary.setWordWrap(True)
        outer.addWidget(summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)

        # ── LEFT: change detail ──────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        details = QTextEdit()
        details.setObjectName("DetailText")
        details.setReadOnly(True)
        details.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        details.setHtml(self._diff_detail_html(item))
        self._expanded_detail_text = details

        # Re-fit height whenever the document lays out (initial render + text reflow on resize)
        details.document().documentLayout().documentSizeChanged.connect(
            lambda _: QTimer.singleShot(0, self._adjust_expanded_detail_height)
        )

        open_row = QHBoxLayout()
        open_row.setSpacing(8)
        open_a_btn = QPushButton("Open Backup A")
        open_a_btn.setObjectName("GhostButton")
        open_b_btn = QPushButton("Open Backup B")
        open_b_btn.setObjectName("GhostButton")
        open_a_btn.clicked.connect(lambda: self._open_backup_in_view(self.backup_a))
        open_b_btn.clicked.connect(lambda: self._open_backup_in_view(self.backup_b))
        open_row.addWidget(open_a_btn)
        open_row.addWidget(open_b_btn)
        open_row.addStretch()

        left_layout.addWidget(details)
        left_layout.addLayout(open_row)

        # ── RIGHT: review panel ──────────────────────────────────────────
        right = QFrame()
        right.setObjectName("Panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(4)

        review_title = QLabel("Review")
        review_title.setObjectName("PanelTitle")
        right_layout.addWidget(review_title)
        right_layout.addSpacing(4)

        review = self._review_for_item(item)
        self.loading_review = True

        self.review_status = QComboBox()
        self.review_status.addItems(_REVIEW_STATUSES)
        self.review_status.setCurrentText(review.get("status", "Pending Review"))

        self.review_priority = QComboBox()
        self.review_priority.addItems(_REVIEW_PRIORITIES)
        self.review_priority.setCurrentText(review.get("priority", "Normal"))

        self.review_owner_box = QLineEdit()
        self.review_owner_box.setPlaceholderText("Reviewer or owner")
        self.review_owner_box.setText(review.get("owner", ""))

        self.review_ticket_box = QLineEdit()
        self.review_ticket_box.setPlaceholderText("Change, incident, or ticket")
        self.review_ticket_box.setText(review.get("ticket", ""))

        self.review_tags_box = QLineEdit()
        self.review_tags_box.setPlaceholderText("Tags, separated by commas")
        self.review_tags_box.setText(review.get("tags", ""))

        self.review_notes_box = QTextEdit()
        self.review_notes_box.setPlaceholderText("Notes, observations, follow-up actions...")
        self.review_notes_box.setPlainText(review.get("notes", ""))

        def _live_badge_update(status: str) -> None:
            if not self.loading_review and self.current_review_key in self._review_badges:
                _apply_review_badge(self._review_badges[self.current_review_key], status)

        self.review_status.currentTextChanged.connect(_live_badge_update)
        self.review_status.currentTextChanged.connect(self._schedule_review_save)
        self.review_priority.currentTextChanged.connect(self._schedule_review_save)
        self.review_owner_box.textChanged.connect(self._schedule_review_save)
        self.review_ticket_box.textChanged.connect(self._schedule_review_save)
        self.review_tags_box.textChanged.connect(self._schedule_review_save)
        self.review_notes_box.textChanged.connect(self._schedule_review_save)
        self.loading_review = False

        for lbl_text, widget in (
            ("Status", self.review_status),
            ("Priority", self.review_priority),
        ):
            lbl = QLabel(lbl_text)
            lbl.setObjectName("Muted")
            right_layout.addWidget(lbl)
            right_layout.addWidget(widget)
            right_layout.addSpacing(4)

        for lbl_text, widget in (
            ("Owner", self.review_owner_box),
            ("Ticket / Change", self.review_ticket_box),
            ("Tags", self.review_tags_box),
        ):
            lbl = QLabel(lbl_text)
            lbl.setObjectName("Muted")
            right_layout.addWidget(lbl)
            right_layout.addWidget(widget)
            right_layout.addSpacing(4)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        add_delta_btn = QPushButton("Add Delta")
        add_delta_btn.setObjectName("GhostButton")
        add_delta_btn.setToolTip("Append the detected change summary to the notes.")
        add_delta_btn.clicked.connect(lambda: self._append_delta_to_notes(item))
        reviewed_next_btn = QPushButton("Reviewed + Next")
        reviewed_next_btn.setObjectName("GhostButton")
        reviewed_next_btn.setToolTip("Mark this item as reviewed and move to the next finding.")
        reviewed_next_btn.clicked.connect(self._mark_reviewed_and_next)
        quick_row.addWidget(add_delta_btn)
        quick_row.addWidget(reviewed_next_btn)
        right_layout.addLayout(quick_row)
        right_layout.addSpacing(4)

        notes_lbl = QLabel("Notes")
        notes_lbl.setObjectName("Muted")
        right_layout.addWidget(notes_lbl)
        right_layout.addWidget(self.review_notes_box, 1)
        right_layout.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        outer.addWidget(splitter, 1)

        self._update_review_progress()
        return panel

    def _adjust_expanded_detail_height(self) -> None:
        if self._expanded_detail_text is not None:
            doc_h = self._expanded_detail_text.document().size().toSize().height()
            new_min = max(200, doc_h + 24)
            if self._expanded_detail_text.minimumHeight() != new_min:
                self._expanded_detail_text.setMinimumHeight(new_min)
                self._expanded_detail_text.updateGeometry()

        if self._scroll_to_expanded_pending and self._expanded_row is not None:
            self.change_scroll.verticalScrollBar().setValue(self._expanded_row.y())
            self._scroll_to_expanded_pending = False

    def _diff_detail_html(self, item: PolicyDiff) -> str:
        t = self._ht
        definition_policy = item.policy_b or item.policy_a
        status_color = _status_color(item.status, t)
        delta = _setting_delta_html(item, t)

        return f"""
<div style="font-size:13px; line-height:1.55;">
  <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:18px; border-radius:6px; overflow:hidden;">
    <tr>
      <td width="50%" style="background:{status_color}; padding:10px 14px;">
        <span style="color:{t['text']}; font-size:12px; font-weight:600; opacity:0.7;">Status</span><br>
        <b style="font-size:14px;">{escape(_status_label(item.status))}</b>
      </td>
      <td width="50%" style="background:{t['code_bg']}; border-left:1px solid {t['border']}; padding:10px 14px;">
        <span style="color:{t['text']}; font-size:12px; font-weight:600; opacity:0.7;">State Change</span><br>
        <b style="font-size:14px;">{escape(item.state_a or 'Not present')}</b>
        <span style="color:{t['label']}; padding:0 6px;">&rarr;</span>
        <b style="font-size:14px;">{escape(item.state_b or 'Not present')}</b>
      </td>
    </tr>
  </table>

  <p style="color:{t['orange']}; font-weight:800; font-size:14px; margin:0 0 8px 0; padding-left:4px; border-left:3px solid {t['orange']}; padding:4px 0 4px 10px;">Actual Delta</p>
  <div style="background:{t['code_bg']}; border:1px solid {t['border']}; padding:10px 14px; margin-bottom:20px; border-radius:4px;">
    {delta}
  </div>

  <p style="font-weight:800; font-size:14px; color:{t['text']}; margin:0 0 8px 0; padding:4px 0 4px 10px; border-left:3px solid {t['label']};">Compared Values</p>
  <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:20px;">
    <tr>
      <td width="50%" style="vertical-align:top; padding-right:5px;">
        {_backup_card_html("Backup A", t["label"], item.policy_a, "Not present in Backup A.", item, t, "a")}
      </td>
      <td width="50%" style="vertical-align:top; padding-left:5px;">
        {_backup_card_html("Backup B", t["orange"], item.policy_b, "Not present in Backup B.", item, t, "b")}
      </td>
    </tr>
  </table>

  <p style="font-weight:800; font-size:14px; color:{t['text']}; margin:0 0 8px 0; padding:4px 0 4px 10px; border-left:3px solid {t['label']};">Policy Definition</p>
  {_definition_html(definition_policy, t)}
</div>
"""

    def _export_markdown(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Comparison Report",
            "nova-gpo-comparison.md",
            "Markdown Files (*.md);;All Files (*)",
        )

        if not path:
            return

        try:
            self._save_review_for_current_item()
            report = markdown_report(
                self.title_a,
                self.title_b,
                self.filtered_items or self.diff_items,
                self.review_notes,
            )
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(report)
        except Exception as error:
            QMessageBox.critical(self, "Export Failed", str(error))
            return

        QMessageBox.information(self, "Export Complete", f"Comparison report exported to:\n{path}")

    def _export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export HTML Comparison Report",
            "nova-gpo-comparison.html",
            "HTML Files (*.html);;All Files (*)",
        )

        if not path:
            return

        try:
            self._save_review_for_current_item()
            report = html_report(
                self.title_a,
                self.title_b,
                self.filtered_items or self.diff_items,
                self.review_notes,
            )
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(report)
        except Exception as error:
            QMessageBox.critical(self, "Export Failed", str(error))
            return

        QMessageBox.information(self, "Export Complete", f"HTML comparison report exported to:\n{path}")

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON Comparison Report",
            "nova-gpo-comparison.json",
            "JSON Files (*.json);;All Files (*)",
        )

        if not path:
            return

        try:
            self._save_review_for_current_item()
            report = json_report(
                self.title_a,
                self.title_b,
                self.filtered_items or self.diff_items,
                self.review_notes,
            )
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(report)
        except Exception as error:
            QMessageBox.critical(self, "Export Failed", str(error))
            return

        QMessageBox.information(self, "Export Complete", f"JSON comparison report exported to:\n{path}")

    def _save_to_library(self) -> None:
        try:
            self._save_review_for_current_item()
            record = save_compare_record(
                title_a=self.title_a,
                title_b=self.title_b,
                backup_a_path=self.backup_a.path,
                backup_b_path=self.backup_b.path,
                diff_items=self.diff_items,
                review_notes=self.review_notes,
                html_report=html_report(self.title_a, self.title_b, self.diff_items, self.review_notes),
                markdown_report=markdown_report(self.title_a, self.title_b, self.diff_items, self.review_notes),
            )
        except Exception as error:
            QMessageBox.critical(self, "Save Failed", str(error))
            return

        QMessageBox.information(
            self,
            "Saved to Library",
            f"Archived compare review saved.\n\n{record.title}",
        )

    def _review_for_item(self, item: PolicyDiff) -> dict[str, str]:
        review = self.review_notes.setdefault(item.key, {})
        defaults = {
            "status": "Pending Review",
            "priority": "Normal",
            "owner": "",
            "ticket": "",
            "tags": "",
            "notes": "",
            "updated_at": "",
        }
        for key, value in defaults.items():
            review.setdefault(key, value)
        return review

    def _load_review_controls(self, item: PolicyDiff | None) -> None:
        self.loading_review = True

        if item is None:
            if self.review_status is None or self.review_notes_box is None:
                self.loading_review = False
                return
            self.review_status.setCurrentText("Pending Review")
            if self.review_priority is not None:
                self.review_priority.setCurrentText("Normal")
            for box in (self.review_owner_box, self.review_ticket_box, self.review_tags_box):
                if box is not None:
                    box.clear()
            self.review_notes_box.clear()
            self.review_status.setEnabled(False)
            if self.review_priority is not None:
                self.review_priority.setEnabled(False)
            for box in (self.review_owner_box, self.review_ticket_box, self.review_tags_box):
                if box is not None:
                    box.setEnabled(False)
            self.review_notes_box.setEnabled(False)
            self.loading_review = False
            return

        review = self._review_for_item(item)
        self.review_status.setEnabled(True)
        self.review_status.setCurrentText(review.get("status", "Pending Review"))
        if self.review_priority is not None:
            self.review_priority.setEnabled(True)
            self.review_priority.setCurrentText(review.get("priority", "Normal"))
        for box, key in (
            (self.review_owner_box, "owner"),
            (self.review_ticket_box, "ticket"),
            (self.review_tags_box, "tags"),
        ):
            if box is not None:
                box.setEnabled(True)
                box.setText(review.get(key, ""))
        self.review_notes_box.setEnabled(True)
        self.review_notes_box.setPlainText(review.get("notes", ""))
        self.loading_review = False

    def _save_review_for_current_item(self) -> None:
        if self._review_save_timer.isActive():
            self._review_save_timer.stop()

        if (
            self.loading_review
            or not self.current_review_key
            or self.review_status is None
            or self.review_priority is None
            or self.review_owner_box is None
            or self.review_ticket_box is None
            or self.review_tags_box is None
            or self.review_notes_box is None
        ):
            return

        self.review_notes[self.current_review_key] = {
            "status": self.review_status.currentText(),
            "priority": self.review_priority.currentText(),
            "owner": self.review_owner_box.text().strip(),
            "ticket": self.review_ticket_box.text().strip(),
            "tags": self.review_tags_box.text().strip(),
            "notes": self.review_notes_box.toPlainText().strip(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_review_notes(self.backup_a.path, self.backup_b.path, self.review_notes)
        self._update_review_progress()

    def _schedule_review_save(self) -> None:
        if self.loading_review:
            return

        self._review_save_timer.start()

    def _update_review_progress(self) -> None:
        reviewed = len([
            note for note in self.review_notes.values()
            if _review_has_content(note)
        ])
        total_actionable = len([item for item in self.diff_items if item.status != "Unchanged"])
        self.review_progress_label.setText(f"{reviewed} reviewed / {total_actionable} actionable")



    def _navigate_next(self) -> None:
        if not self.filtered_items:
            return
        idx = next((i for i, it in enumerate(self.filtered_items) if it.key == self.expanded_key), -1)
        next_idx = min(idx + 1, len(self.filtered_items) - 1)
        if next_idx != idx:
            self._save_review_for_current_item()
            self.expanded_key = self.filtered_items[next_idx].key
            self._visible_count = max(self._visible_count, next_idx + 1)
            self._populate_accordion(self.filtered_items)

    def _navigate_prev(self) -> None:
        if not self.filtered_items:
            return
        idx = next((i for i, it in enumerate(self.filtered_items) if it.key == self.expanded_key), 0)
        prev_idx = max(idx - 1, 0)
        if prev_idx != idx:
            self._save_review_for_current_item()
            self.expanded_key = self.filtered_items[prev_idx].key
            self._visible_count = max(self._visible_count, prev_idx + 1)
            self._populate_accordion(self.filtered_items)

    def _mark_all_as(self) -> None:
        menu = QMenu(self)
        for status in _REVIEW_STATUSES[1:]:
            action = menu.addAction(status)
            action.triggered.connect(
                lambda checked=False, d=status: self._apply_bulk_review(d)
            )
        menu.exec(QCursor.pos())

    def _apply_bulk_review(self, status: str) -> None:
        for item in self.filtered_items:
            review = self._review_for_item(item)
            review["status"] = status
            review["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_review_notes(self.backup_a.path, self.backup_b.path, self.review_notes)
        self._update_review_progress()
        for item in self.filtered_items[: self._visible_count]:
            if item.key in self._review_badges:
                _apply_review_badge(self._review_badges[item.key], status)
        if self.review_filter.currentText() != "All Reviews":
            self._apply_filters()

    def _append_delta_to_notes(self, item: PolicyDiff) -> None:
        if self.review_notes_box is None:
            return
        existing = self.review_notes_box.toPlainText().strip()
        delta = "\n".join(f"- {change}" for change in setting_changes(item))
        if not delta:
            return
        next_text = f"{existing}\n\nDetected delta:\n{delta}" if existing else f"Detected delta:\n{delta}"
        self.review_notes_box.setPlainText(next_text)
        self.review_notes_box.moveCursor(QTextCursor.MoveOperation.End)
        self._schedule_review_save()

    def _mark_reviewed_and_next(self) -> None:
        if self.review_status is not None and self.review_status.currentText() == "Pending Review":
            self.review_status.setCurrentText("No Action Required")
        self._save_review_for_current_item()
        self._navigate_next()

    def _open_backup_in_view(self, backup) -> None:
        from app.ui.view_window import ViewWindow
        win = ViewWindow(backup, self)
        win.exec()

    def _sync_filter_indicator(self) -> None:
        active = (
            self.search_box.text().strip() != ""
            or self.status_filter.currentIndex() != 0
            or self.scope_filter.currentIndex() != 0
            or self.review_filter.currentIndex() != 0
            or self.priority_filter.currentIndex() != 0
            or not self.actionable_only.isChecked()
        )
        self.clear_button.setText("Clear Filters ●" if active else "Clear Filters")


def _policy_type(item: PolicyDiff) -> str:
    if item.policy_b:
        return item.policy_b.policy_type

    if item.policy_a:
        return item.policy_a.policy_type

    return "Unknown"


def _review_badge_state(status: str) -> str:
    return {
        "No Action Required": "valid",
        "Update Required": "review",
        "Under Investigation": "unknown",
        "Escalated": "removed",
    }.get(status, "empty")


def _apply_review_badge(bw: QLabel, disposition: str) -> None:
    bw.setText(disposition)
    bw.setProperty("state", _review_badge_state(disposition))
    bw.setVisible(disposition != "Not Reviewed")
    bw.style().unpolish(bw)
    bw.style().polish(bw)


def _compact_summary(items: list[PolicyDiff]) -> str:
    summary = summarize_diffs(items)
    return (
        f"{len(items)} total items  |  "
        f"{summary.added} missing in A  |  "
        f"{summary.changed} changed  |  "
        f"{summary.removed} missing in B"
    )


def _status_label(status: str) -> str:
    return {
        "Added": "Missing in A",
        "Removed": "Missing in B",
        "Unchanged": "Same",
    }.get(status, status)


def _status_filter_value(label: str) -> str:
    return {
        "Missing in A": "Added",
        "Missing in B": "Removed",
        "Same": "Unchanged",
    }.get(label, label)


def _review_has_content(note: dict[str, str]) -> bool:
    return (
        note.get("status", "Pending Review") != "Pending Review"
        or note.get("priority", "Normal") != "Normal"
        or bool(note.get("owner", "").strip())
        or bool(note.get("ticket", "").strip())
        or bool(note.get("tags", "").strip())
        or bool(note.get("notes", "").strip())
    )


def _short_cell(value: str, limit: int = 42) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= limit:
        return clean

    return f"{clean[: limit - 3]}..."


def _detail_row(label: str, value: str, t: dict) -> str:
    return (
        "<p>"
        f"<span style='color:{t['label']}; font-weight:700;'>{escape(label)}</span><br>"
        f"{escape(value)}"
        "</p>"
    )


def _split_ilt(settings: list[str]) -> tuple[list[str], list[str]]:
    try:
        idx = settings.index(ILT_HEADER)
        return settings[:idx], settings[idx + 1:]
    except ValueError:
        return settings, []


def _configured_html(policy, missing_text: str, item: PolicyDiff | None, t: dict, side: str) -> str:
    if policy is None:
        return f"<p>{escape(missing_text)}</p>"

    all_settings, forced_side = (
        _settings_for_context(policy.settings, item, t, side) if item is not None else (policy.settings, "")
    )
    # Separate ILT lines from regular settings so they render in their own section
    regular, ilt_rules = _split_ilt(all_settings)

    html = (
        _detail_row("State", policy.state or "Not reported", t)
        + f"<p style='color:{t['label']}; font-weight:700; margin:8px 0 4px 0;'>Relevant configured values</p>"
        + _settings_html(regular, item, t, forced_side)
    )
    if ilt_rules:
        html += (
            f"<p style='color:{t['label']}; font-weight:700; margin:10px 0 4px 0;'>Item-Level Targeting</p>"
            + _settings_html(ilt_rules, item, t, forced_side)
        )
    return html


def _backup_card_html(title: str, color: str, policy, missing_text: str, item: PolicyDiff, t: dict, side: str) -> str:
    return (
        f"<div style='background:{t['code_bg']}; border:1px solid {t['border']}; "
        f"border-left:4px solid {color}; padding:10px 12px; margin:8px 0;'>"
        f"<p style='color:{t['label']}; font-weight:700; margin:0 0 8px 0;'>{escape(title)}</p>"
        f"{_configured_html(policy, missing_text, item, t, side)}"
        "</div>"
    )


def _settings_html(settings: list[str], item: PolicyDiff | None, t: dict, forced_side: str = "") -> str:
    if not settings:
        return "<p>No changed configured values were found for this side.</p>"

    rows = "".join(_setting_li(setting, item, t, forced_side) for setting in settings)
    return f"<ul style='margin-top:4px;'>{rows}</ul>"


def _setting_li(setting: str, item: PolicyDiff | None, t: dict, forced_side: str = "") -> str:
    style = ""
    if forced_side or item is not None:
        side = forced_side or _setting_side(setting, item)
        if side == "added":
            bg, fg = t["added_bg"], t["success"]
            style = f" style='background:{bg}; color:{fg}; padding:3px 6px;'"
        elif side == "removed":
            bg, fg = t["removed_bg"], t["danger"]
            style = f" style='background:{bg}; color:{fg}; padding:3px 6px;'"

    return f"<li{style}>{escape(setting)}</li>"


def _setting_delta_html(item: PolicyDiff, t: dict) -> str:
    if item.policy_a is None and item.policy_b is not None:
        settings = _settings_html(item.policy_b.settings, None, t)
        return (
            f"<p><b style='color:{t['success']};'>Missing in Backup A</b></p>"
            "<p>This item only exists in Backup B.</p>"
            f"{settings}"
        )

    if item.policy_a is not None and item.policy_b is None:
        settings = _settings_html(item.policy_a.settings, None, t)
        return (
            f"<p><b style='color:{t['danger']};'>Missing in Backup B</b></p>"
            "<p>This item only exists in Backup A.</p>"
            f"{settings}"
        )

    if item.policy_a is None or item.policy_b is None:
        return "<p>No comparable policy details are available.</p>"

    sections: list[str] = []

    if _norm(item.policy_a.state) != _norm(item.policy_b.state):
        sections.append(
            _delta_card(
                "State changed",
                t["orange"],
                [f"Backup A: {item.policy_a.state or 'Not present'}", f"Backup B: {item.policy_b.state or 'Not present'}"],
                t,
            )
        )

    # Split ILT rules from regular settings before diffing so the header
    # sentinel and rule lines are handled in their own dedicated card.
    regular_a, ilt_a = _split_ilt(item.policy_a.settings)
    regular_b, ilt_b = _split_ilt(item.policy_b.settings)

    token_sections, token_labels = _token_delta_sections(regular_a, regular_b, t)
    sections.extend(token_sections)

    removed_settings, added_settings = _whole_setting_delta(regular_a, regular_b, token_labels)
    if added_settings:
        sections.append(_delta_card("Added in Backup B", t["success"], added_settings, t))
    if removed_settings:
        sections.append(_delta_card("Removed from Backup B", t["danger"], removed_settings, t))

    # ILT delta — only surface when targeting actually changed
    if ilt_a != ilt_b:
        ilt_lines: list[str] = []
        ilt_removed = [r for r in ilt_a if r not in ilt_b]
        ilt_added   = [a for a in ilt_b if a not in ilt_a]
        if ilt_removed:
            ilt_lines += [f"Removed: {r}" for r in ilt_removed]
        if ilt_added:
            ilt_lines += [f"Added: {a}" for a in ilt_added]
        if not ilt_a:
            ilt_lines = ["Targeting was added in Backup B."] + [f"  {r}" for r in ilt_b]
        elif not ilt_b:
            ilt_lines = ["Targeting was removed in Backup B."] + [f"  {r}" for r in ilt_a]
        sections.append(_delta_card("Item-Level Targeting changed", t["blue"], ilt_lines or ilt_b or ilt_a, t))

    if _norm(item.policy_a.category) != _norm(item.policy_b.category):
        sections.append(
            _delta_card(
                "Category changed",
                t["orange"],
                [f"Backup A: {item.policy_a.category or 'Not reported'}", f"Backup B: {item.policy_b.category or 'Not reported'}"],
                t,
            )
        )

    if _norm(item.policy_a.supported) != _norm(item.policy_b.supported):
        sections.append(_delta_card("Supported-on text changed", t["orange"], ["Review the policy definition section."], t))

    if not sections:
        return "<p>No setting-level differences were detected. The change may be metadata, formatting, or unsupported parser detail.</p>"

    return "".join(sections)


def _delta_card(title: str, color: str, values: list[str], t: dict) -> str:
    rows = "".join(f"<li>{escape(value)}</li>" for value in values)
    return (
        f"<div style='border-left:4px solid {color}; background:{t['card_bg']}; padding:8px 10px; margin:8px 0;'>"
        f"<p style='font-weight:700; margin:0 0 6px 0; color:{color};'>{escape(title)}</p>"
        f"<ul style='margin-top:4px;'>{rows}</ul>"
        "</div>"
    )


def _whole_setting_delta(settings_a: list[str], settings_b: list[str], ignored_labels: set[str]) -> tuple[list[str], list[str]]:
    a_map = {_norm(setting): setting for setting in settings_a}
    b_map = {_norm(setting): setting for setting in settings_b}

    removed = [
        value for key, value in sorted(a_map.items())
        if key not in b_map and _setting_label(value) not in ignored_labels
    ]
    added = [
        value for key, value in sorted(b_map.items())
        if key not in a_map and _setting_label(value) not in ignored_labels
    ]
    return removed, added


def _token_delta_sections(settings_a: list[str], settings_b: list[str], t: dict) -> tuple[list[str], set[str]]:
    sections: list[str] = []
    labels_with_token_diff: set[str] = set()
    grouped_a = _collection_settings(settings_a)
    grouped_b = _collection_settings(settings_b)

    for label in sorted(set(grouped_a) | set(grouped_b)):
        values_a = grouped_a.get(label, [])
        values_b = grouped_b.get(label, [])
        norm_a = {_norm(value): value for value in values_a}
        norm_b = {_norm(value): value for value in values_b}

        removed = [norm_a[key] for key in sorted(set(norm_a) - set(norm_b))]
        added = [norm_b[key] for key in sorted(set(norm_b) - set(norm_a))]

        if not added and not removed:
            continue

        labels_with_token_diff.add(label)
        if added:
            sections.append(_delta_card(f"Added in Backup B: {label}", t["success"], added, t))
        if removed:
            sections.append(_delta_card(f"Removed from Backup B: {label}", t["danger"], removed, t))

    return sections, labels_with_token_diff


def _token_delta_values(settings_a: list[str], settings_b: list[str]) -> tuple[list[str], list[str], set[str]]:
    removed_values: list[str] = []
    added_values: list[str] = []
    labels_with_token_diff: set[str] = set()
    grouped_a = _collection_settings(settings_a)
    grouped_b = _collection_settings(settings_b)

    for label in sorted(set(grouped_a) | set(grouped_b)):
        values_a = grouped_a.get(label, [])
        values_b = grouped_b.get(label, [])
        norm_a = {_norm(value): value for value in values_a}
        norm_b = {_norm(value): value for value in values_b}

        removed = [norm_a[key] for key in sorted(set(norm_a) - set(norm_b))]
        added = [norm_b[key] for key in sorted(set(norm_b) - set(norm_a))]

        if not added and not removed:
            continue

        labels_with_token_diff.add(label)
        removed_values.extend(f"{label}: {value}" for value in removed)
        added_values.extend(f"{label}: {value}" for value in added)

    return removed_values, added_values, labels_with_token_diff


def _collection_settings(settings: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}

    for setting in settings:
        label, value = _split_setting(setting)
        values = _split_collection(value)
        if not label or not value:
            continue
        grouped[label] = values

    return grouped


def _settings_for_context(settings: list[str], item: PolicyDiff, t: dict, side: str) -> tuple[list[str], str]:
    if item.policy_a is None or item.policy_b is None:
        return settings, ""

    removed_tokens, added_tokens, token_labels = _token_delta_values(item.policy_a.settings, item.policy_b.settings)
    removed, added = _whole_setting_delta(item.policy_a.settings, item.policy_b.settings, token_labels)

    if side == "a":
        values = removed_tokens + removed
        return values, "removed" if values else ""

    values = added_tokens + added
    return values, "added" if values else ""


def _setting_side(setting: str, item: PolicyDiff) -> str:
    if item.policy_a is None and item.policy_b is not None:
        return "added"
    if item.policy_a is not None and item.policy_b is None:
        return "removed"
    if item.policy_a is None or item.policy_b is None:
        return ""

    norm_setting = _norm(setting)
    a_settings = {_norm(value) for value in item.policy_a.settings}
    b_settings = {_norm(value) for value in item.policy_b.settings}

    if norm_setting in b_settings and norm_setting not in a_settings:
        return "added"
    if norm_setting in a_settings and norm_setting not in b_settings:
        return "removed"
    return ""


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


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _definition_html(policy, t: dict) -> str:
    if policy is None:
        return "<p>No policy definition was available for this comparison item.</p>"

    return (
        _detail_row("Category", policy.category or "Not reported", t)
        + _detail_row("Supported On", policy.supported or "Not specified", t)
        + _detail_row("Source", policy.source or "gpreport.xml", t)
        + f"<p style='color:{t['label']}; font-weight:700;'>Explanation</p>"
        + f"<p>{_multiline_html(policy.explain or 'No explanation text was included.')}</p>"
    )


def _status_color(status: str, t: dict) -> str:
    return {
        "Added":     t["status_added"],
        "Removed":   t["status_removed"],
        "Changed":   t["status_changed"],
        "Unchanged": t["status_unchanged"],
    }.get(status, t["status_unchanged"])




def _multiline_html(value: str) -> str:
    return "<br>".join(escape(line) for line in value.splitlines())
