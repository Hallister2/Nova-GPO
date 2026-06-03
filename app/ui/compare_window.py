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


_WINDOW_FLAGS = (
    Qt.WindowType.Dialog |
    Qt.WindowType.WindowTitleHint |
    Qt.WindowType.WindowSystemMenuHint |
    Qt.WindowType.WindowCloseButtonHint |
    Qt.WindowType.WindowMaximizeButtonHint
)


class CompareWindow(QDialog):
    def __init__(self, backup_a: GpoBackup, backup_b: GpoBackup, settings: dict[str, Any], parent=None) -> None:
        super().__init__(parent, _WINDOW_FLAGS)

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
        # Per-row caches — populated in _build_accordion_row, cleared on full rebuild
        self._row_frames: dict[str, QFrame] = {}
        self._row_toggle_btns: dict[str, QPushButton] = {}
        self._row_detail_panels: dict[str, QFrame] = {}
        self._row_detail_texts: dict[str, QTextEdit] = {}
        self._row_review_widgets: dict[str, dict] = {}
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
        self.change_scroll.setVisible(False)
        self._clear_change_list_layout()
        self.current_review_key = ""
        self.review_status = None
        self.review_priority = None
        self.review_owner_box = None
        self.review_ticket_box = None
        self.review_tags_box = None
        self.review_notes_box = None
        self._accordion_rows = []
        self._review_badges = {}
        self._expanded_row = None
        self._expanded_detail_text = None
        self._row_frames = {}
        self._row_toggle_btns = {}
        self._row_detail_panels = {}
        self._row_detail_texts = {}
        self._row_review_widgets = {}
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
            empty = QLabel("No comparison results match the current filters.", self.change_list_content)
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(180)
            self.change_list_layout.addWidget(empty)
            self.change_list_layout.addStretch()
            self.change_scroll.setVisible(True)
            return

        visible = items[: self._visible_count]
        for item in visible:
            row = self._build_accordion_row(item)
            self._accordion_rows.append(row)
            self.change_list_layout.addWidget(row)

        remaining = len(items) - len(visible)
        if remaining > 0:
            next_batch = min(_PAGE_SIZE, remaining)
            load_btn = QPushButton(
                f"Show {next_batch} more  ({remaining} remaining)",
                self.change_list_content,
            )
            load_btn.setObjectName("GhostButton")
            load_btn.clicked.connect(self._load_more_rows)
            self.change_list_layout.addWidget(load_btn)

        self.change_list_layout.addStretch()
        self.change_scroll.setVisible(True)
        QTimer.singleShot(0, self._adjust_expanded_detail_height)

    def _clear_change_list_layout(self) -> None:
        while self.change_list_layout.count():
            item = self.change_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        self.change_list_content.updateGeometry()
        self.change_scroll.viewport().update()

    def _build_accordion_row(self, item: PolicyDiff) -> QFrame:
        row = QFrame(self.change_list_content)
        row.setObjectName("AccordionRow")
        row.setProperty("expanded", item.key == self.expanded_key)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        policy_name = item.policy_b.name if item.policy_b else item.policy_a.name if item.policy_a else "Unknown"
        policy_type = _policy_type(item)
        status_label = _status_label(item.status)

        # Create header_frame first so all child widgets can use it as parent,
        # keeping them alien (no native HWND) and avoiding SetParent flashes.
        header_frame = QFrame(row)
        header_frame.setCursor(Qt.CursorShape.PointingHandCursor)

        status_badge = badge(status_label, item.status.lower(), min_width=112, parent=header_frame)

        scope_label = QLabel(_short_cell(item.scope, 30), header_frame)
        scope_label.setObjectName("Muted")
        scope_label.setToolTip(item.scope)

        type_label = QLabel(_short_cell(policy_type, 28), header_frame)
        type_label.setObjectName("Muted")
        type_label.setToolTip(policy_type)

        name_label = QLabel(policy_name, header_frame)
        name_label.setObjectName("StatusLabel")
        name_label.setWordWrap(True)
        name_label.setToolTip(policy_name)

        review_status = self.review_notes.get(item.key, {}).get("status", "Pending Review")
        review_badge = badge(review_status, _review_badge_state(review_status), min_width=128, parent=header_frame)
        review_badge.setVisible(review_status != "Pending Review")
        self._review_badges[item.key] = review_badge

        toggle = QPushButton("Collapse" if item.key == self.expanded_key else "Open", header_frame)
        toggle.setObjectName("GhostButton")
        toggle.clicked.connect(lambda checked=False, key=item.key: self._toggle_expanded_row(key))

        sep1 = QLabel("›", header_frame)
        sep1.setObjectName("Muted")
        sep2 = QLabel("›", header_frame)
        sep2.setObjectName("Muted")

        header = QHBoxLayout(header_frame)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(status_badge)
        header.addSpacing(6)
        header.addWidget(scope_label)
        header.addWidget(sep1)
        header.addWidget(type_label)
        header.addWidget(sep2)
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

        # Pre-build the detail panel for every row so toggling is pure show/hide.
        # This runs inside change_scroll.setVisible(False) so there are no native
        # window flashes regardless of how many widgets are created here.
        detail = self._build_expanded_details(item, row)
        detail.setVisible(item.key == self.expanded_key)
        layout.addWidget(detail)

        self._row_frames[item.key] = row
        self._row_toggle_btns[item.key] = toggle
        self._row_detail_panels[item.key] = detail

        if item.key == self.expanded_key:
            self._expanded_row = row
            self.current_review_key = item.key

        return row

    def _load_more_rows(self) -> None:
        self._visible_count += _PAGE_SIZE
        self._populate_accordion(self.filtered_items)

    def _toggle_expanded_row(self, key: str) -> None:
        self._save_review_for_current_item()

        prev_key = self.expanded_key
        self.expanded_key = "" if self.expanded_key == key else key

        # Collapse previously expanded row — just hide its detail panel.
        if prev_key and prev_key != self.expanded_key:
            if prev_key in self._row_detail_panels:
                self._row_detail_panels[prev_key].setVisible(False)
            if prev_key in self._row_frames:
                row = self._row_frames[prev_key]
                row.setProperty("expanded", "false")
                row.style().unpolish(row)
                row.style().polish(row)
            if prev_key in self._row_toggle_btns:
                self._row_toggle_btns[prev_key].setText("Open")

        # Expand newly selected row — just show its pre-built detail panel.
        if self.expanded_key:
            # If this key isn't in the visible page yet, rebuild to include it.
            if self.expanded_key not in self._row_detail_panels:
                idx = next(
                    (i for i, it in enumerate(self.filtered_items) if it.key == self.expanded_key), 0
                )
                self._visible_count = max(self._visible_count, idx + 1)
                self._populate_accordion(self.filtered_items)
                return

            if self.expanded_key in self._row_detail_panels:
                self._row_detail_panels[self.expanded_key].setVisible(True)
            if self.expanded_key in self._row_frames:
                row = self._row_frames[self.expanded_key]
                row.setProperty("expanded", "true")
                row.style().unpolish(row)
                row.style().polish(row)
                self._expanded_row = row
            if self.expanded_key in self._row_toggle_btns:
                self._row_toggle_btns[self.expanded_key].setText("Collapse")

            # Restore the instance-level review widget references for this row.
            w = self._row_review_widgets.get(self.expanded_key, {})
            self.review_status = w.get("status")
            self.review_priority = w.get("priority")
            self.review_owner_box = w.get("owner_box")
            self.review_ticket_box = w.get("ticket_box")
            self.review_tags_box = w.get("tags_box")
            self.review_notes_box = w.get("notes_box")
            self._expanded_detail_text = self._row_detail_texts.get(self.expanded_key)
            self.current_review_key = self.expanded_key
            self._scroll_to_expanded_pending = True

            item = next((it for it in self.filtered_items if it.key == self.expanded_key), None)
            if item:
                self._load_review_controls(item)
        else:
            # Collapsed everything.
            self.review_status = None
            self.review_priority = None
            self.review_owner_box = None
            self.review_ticket_box = None
            self.review_tags_box = None
            self.review_notes_box = None
            self._expanded_detail_text = None
            self._expanded_row = None
            self.current_review_key = ""

        self._update_review_progress()
        QTimer.singleShot(0, self._adjust_expanded_detail_height)

    def _change_summary_text(self, item: PolicyDiff) -> str:
        if item.status == "Added":
            return "This policy exists in Backup B but was not present in Backup A."

        if item.status == "Removed":
            return "This policy existed in Backup A but is not present in Backup B."

        if item.status == "Changed":
            return "This policy exists in both backups, but one or more reported values changed."

        return "This policy appears unchanged between the selected backups."

    def _build_expanded_details(self, item: PolicyDiff, parent: QWidget) -> QFrame:
        panel = QFrame(parent)
        panel.setObjectName("AccordionDetail")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        summary = QLabel(self._change_summary_text(item), panel)
        summary.setObjectName("Muted")
        summary.setWordWrap(True)
        outer.addWidget(summary)

        splitter = QSplitter(Qt.Orientation.Horizontal, panel)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)

        # ── LEFT: change detail ──────────────────────────────────────────
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.setSpacing(6)

        details = QTextEdit(left)
        details.setObjectName("DetailText")
        details.setReadOnly(True)
        details.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        details.setHtml(self._diff_detail_html(item))
        self._row_detail_texts[item.key] = details

        # Re-fit height whenever the document lays out (initial render + text reflow on resize)
        details.document().documentLayout().documentSizeChanged.connect(
            lambda _: QTimer.singleShot(0, self._adjust_expanded_detail_height)
        )

        open_a_btn = QPushButton("Open Backup A", left)
        open_a_btn.setObjectName("GhostButton")
        open_b_btn = QPushButton("Open Backup B", left)
        open_b_btn.setObjectName("GhostButton")
        open_a_btn.clicked.connect(lambda: self._open_backup_in_view(self.backup_a))
        open_b_btn.clicked.connect(lambda: self._open_backup_in_view(self.backup_b))

        open_row = QHBoxLayout()
        open_row.setSpacing(8)
        open_row.addWidget(open_a_btn)
        open_row.addWidget(open_b_btn)
        open_row.addStretch()

        left_layout.addWidget(details)
        left_layout.addLayout(open_row)

        # ── RIGHT: review panel ──────────────────────────────────────────
        right = QFrame(splitter)
        right.setObjectName("Panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(4)

        review_title = QLabel("Review", right)
        review_title.setObjectName("PanelTitle")
        right_layout.addWidget(review_title)
        right_layout.addSpacing(4)

        review = self._review_for_item(item)

        row_status = QComboBox(right)
        row_status.addItems(_REVIEW_STATUSES)
        row_status.setCurrentText(review.get("status", "Pending Review"))

        row_priority = QComboBox(right)
        row_priority.addItems(_REVIEW_PRIORITIES)
        row_priority.setCurrentText(review.get("priority", "Normal"))

        row_owner = QLineEdit(right)
        row_owner.setPlaceholderText("Reviewer or owner")
        row_owner.setText(review.get("owner", ""))

        row_ticket = QLineEdit(right)
        row_ticket.setPlaceholderText("Change, incident, or ticket")
        row_ticket.setText(review.get("ticket", ""))

        row_tags = QLineEdit(right)
        row_tags.setPlaceholderText("Tags, separated by commas")
        row_tags.setText(review.get("tags", ""))

        row_notes = QTextEdit(right)
        row_notes.setPlaceholderText("Notes, observations, follow-up actions...")
        row_notes.setPlainText(review.get("notes", ""))

        # Cache per-row widget references so _toggle_expanded_row can restore them.
        self._row_review_widgets[item.key] = {
            "status": row_status,
            "priority": row_priority,
            "owner_box": row_owner,
            "ticket_box": row_ticket,
            "tags_box": row_tags,
            "notes_box": row_notes,
        }

        # If this is the currently expanded key, bind the instance variables now.
        if item.key == self.expanded_key:
            self.review_status = row_status
            self.review_priority = row_priority
            self.review_owner_box = row_owner
            self.review_ticket_box = row_ticket
            self.review_tags_box = row_tags
            self.review_notes_box = row_notes
            self._expanded_detail_text = details

        _item_key = item.key

        def _live_badge_update(status: str) -> None:
            if not self.loading_review and _item_key in self._review_badges:
                _apply_review_badge(self._review_badges[_item_key], status)

        row_status.currentTextChanged.connect(_live_badge_update)
        row_status.currentTextChanged.connect(self._schedule_review_save)
        row_priority.currentTextChanged.connect(self._schedule_review_save)
        row_owner.textChanged.connect(self._schedule_review_save)
        row_ticket.textChanged.connect(self._schedule_review_save)
        row_tags.textChanged.connect(self._schedule_review_save)
        row_notes.textChanged.connect(self._schedule_review_save)

        for lbl_text, widget in (
            ("Status", row_status),
            ("Priority", row_priority),
        ):
            lbl = QLabel(lbl_text, right)
            lbl.setObjectName("Muted")
            right_layout.addWidget(lbl)
            right_layout.addWidget(widget)
            right_layout.addSpacing(4)

        for lbl_text, widget in (
            ("Owner", row_owner),
            ("Ticket / Change", row_ticket),
            ("Tags", row_tags),
        ):
            lbl = QLabel(lbl_text, right)
            lbl.setObjectName("Muted")
            right_layout.addWidget(lbl)
            right_layout.addWidget(widget)
            right_layout.addSpacing(4)

        add_delta_btn = QPushButton("Add Delta", right)
        add_delta_btn.setObjectName("GhostButton")
        add_delta_btn.setToolTip("Append the detected change summary to the notes.")
        add_delta_btn.clicked.connect(lambda: self._append_delta_to_notes(item))
        reviewed_next_btn = QPushButton("Reviewed + Next", right)
        reviewed_next_btn.setObjectName("GhostButton")
        reviewed_next_btn.setToolTip("Mark this item as reviewed and move to the next finding.")
        reviewed_next_btn.clicked.connect(self._mark_reviewed_and_next)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        quick_row.addWidget(add_delta_btn)
        quick_row.addWidget(reviewed_next_btn)
        right_layout.addLayout(quick_row)
        right_layout.addSpacing(4)

        notes_lbl = QLabel("Notes", right)
        notes_lbl.setObjectName("Muted")
        right_layout.addWidget(notes_lbl)
        right_layout.addWidget(row_notes, 1)
        right_layout.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        outer.addWidget(splitter, 1)

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

        state_a = item.state_a or "Not present"
        state_b = item.state_b or "Not present"
        states_differ = _norm(state_a) != _norm(state_b)

        if states_differ:
            state_cell = (
                f"<td width='50%' style='background:{t['code_bg']}; border-left:1px solid {t['border']}; padding:10px 14px;'>"
                f"<span style='color:{t['label']}; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>State Change</span><br>"
                f"<span style='font-size:13px;'><b>{escape(state_a)}</b>"
                f" <span style='color:{t['label']}; padding:0 5px;'>→</span>"
                f"<b style='color:{t['orange']};'>{escape(state_b)}</b></span>"
                f"</td>"
            )
        else:
            state_cell = (
                f"<td width='50%' style='background:{t['code_bg']}; border-left:1px solid {t['border']}; padding:10px 14px;'>"
                f"<span style='color:{t['label']}; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;'>State</span><br>"
                f"<span style='font-size:13px; color:{t['label']};'>{escape(state_a)}</span>"
                f"</td>"
            )

        return f"""
<div style="font-size:13px; line-height:1.6; color:{t['text']};">
  <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:16px; border-radius:6px; overflow:hidden;">
    <tr>
      <td width="50%" style="background:{status_color}; padding:10px 14px;">
        <span style="color:{t['text']}; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; opacity:0.8;">Status</span><br>
        <b style="font-size:14px;">{escape(_status_label(item.status))}</b>
      </td>
      {state_cell}
    </tr>
  </table>

  <p style="color:{t['orange']}; font-weight:800; font-size:12px; margin:0 0 6px 0;
     padding:5px 10px; border-left:3px solid {t['orange']}; background:{t['code_bg']};
     text-transform:uppercase; letter-spacing:0.6px;">Actual Delta</p>
  <div style="margin-bottom:20px;">
    {delta}
  </div>

  <p style="font-weight:800; font-size:12px; color:{t['label']}; margin:0 0 6px 0;
     padding:5px 10px; border-left:3px solid {t['label']}; background:{t['code_bg']};
     text-transform:uppercase; letter-spacing:0.6px;">Compared Values</p>
  <table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:20px;">
    <tr>
      <td width="50%" style="vertical-align:top; padding-right:6px;">
        {_backup_card_html("Backup A", t["label"], item.policy_a, "Not present in Backup A.", item, t, "a")}
      </td>
      <td width="50%" style="vertical-align:top; padding-left:6px;">
        {_backup_card_html("Backup B", t["orange"], item.policy_b, "Not present in Backup B.", item, t, "b")}
      </td>
    </tr>
  </table>

  <p style="font-weight:800; font-size:12px; color:{t['label']}; margin:0 0 6px 0;
     padding:5px 10px; border-left:3px solid {t['label']}; background:{t['code_bg']};
     text-transform:uppercase; letter-spacing:0.6px;">Policy Definition</p>
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
        lbl = t["label"]
        return f"<p style='color:{lbl}; font-style:italic;'>{escape(missing_text)}</p>"

    all_settings, forced_side = (
        _settings_for_context(policy.settings, item, t, side) if item is not None else (policy.settings, "")
    )
    # Separate ILT lines from regular settings so they render in their own section
    regular, ilt_rules = _split_ilt(all_settings)

    html = f"<p style='color:{t['label']}; font-size:11px; font-weight:700; margin:0 0 6px 0; text-transform:uppercase; letter-spacing:0.4px;'>Configured values</p>"
    html += _settings_html(regular, item, t, forced_side)
    if ilt_rules:
        html += (
            f"<p style='color:{t['label']}; font-size:11px; font-weight:700; margin:10px 0 4px 0; text-transform:uppercase; letter-spacing:0.4px;'>Item-Level Targeting</p>"
            + _settings_html(ilt_rules, item, t, forced_side)
        )
    return html


def _backup_card_html(title: str, color: str, policy, missing_text: str, item: PolicyDiff, t: dict, side: str) -> str:
    return (
        f"<div style='background:{t['code_bg']}; border:1px solid {t['border']}; "
        f"border-top:3px solid {color}; padding:10px 12px; margin:4px 0; border-radius:4px;'>"
        f"<p style='color:{color}; font-weight:800; margin:0 0 10px 0;"
        f" font-size:11px; text-transform:uppercase; letter-spacing:0.5px;'>{escape(title)}</p>"
        f"{_configured_html(policy, missing_text, item, t, side)}"
        "</div>"
    )


def _settings_html(settings: list[str], item: PolicyDiff | None, t: dict, forced_side: str = "") -> str:
    if not settings:
        lbl = t["label"]
        return f"<p style='color:{lbl}; font-style:italic; font-size:12px;'>No changed values on this side.</p>"

    rows = "".join(_setting_li(setting, item, t, forced_side) for setting in settings)
    return f"<ul style='margin:4px 0; padding-left:16px; line-height:1.7;'>{rows}</ul>"


def _setting_li(setting: str, item: PolicyDiff | None, t: dict, forced_side: str = "") -> str:
    side = forced_side or ((_setting_side(setting, item)) if item is not None else "")
    if side == "added":
        bg, fg = t["added_bg"], t["success"]
        base_style = f"background:{bg}; color:{fg}; padding:2px 5px; border-radius:3px; display:inline-block;"
    elif side == "removed":
        bg, fg = t["removed_bg"], t["danger"]
        base_style = f"background:{bg}; color:{fg}; padding:2px 5px; border-radius:3px; display:inline-block;"
    else:
        base_style = f"color:{t['text']};"

    # Split comma-separated account/value lists so each entry is its own sub-bullet
    if "," in setting and ":" not in setting:
        parts = [p.strip() for p in re.split(r",\s*", setting) if p.strip()]
        if len(parts) > 1:
            return "".join(
                f"<li style='padding:2px 0;'><span style='{base_style}'>{escape(p)}</span></li>"
                for p in parts
            )

    return f"<li style='padding:2px 0;'><span style='{base_style}'>{escape(setting)}</span></li>"


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
    rows: list[str] = []
    for value in values:
        # Comma-separated lists (User Rights accounts, group members, etc.) have no ":" label prefix.
        # Split them so each entry gets its own bullet instead of appearing as one long line.
        if "," in value and ":" not in value:
            parts = [p.strip() for p in re.split(r",\s*", value) if p.strip()]
            if len(parts) > 1:
                rows.extend(
                    f"<li style='padding:2px 0; color:{t['text']};'>{escape(p)}</li>"
                    for p in parts
                )
                continue
        rows.append(f"<li style='padding:2px 0;'>{escape(value)}</li>")

    return (
        f"<div style='border-left:3px solid {color}; padding:8px 14px; margin:6px 0;"
        f" background:{t['card_bg']}; border-radius:0 4px 4px 0;'>"
        f"<p style='font-weight:700; margin:0 0 8px 0; color:{color};"
        f" font-size:12px; text-transform:uppercase; letter-spacing:0.4px;'>{escape(title)}</p>"
        f"<ul style='margin:0; padding-left:16px; line-height:1.7;'>{''.join(rows)}</ul>"
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
        lbl = t["label"]
        return f"<p style='color:{lbl}; font-style:italic;'>No policy definition was available for this comparison item.</p>"

    rows: list[str] = []
    if policy.category and policy.category != "Not reported":
        rows.append(_def_row("Category", policy.category, t))
    if policy.policy_type and policy.policy_type not in {"Administrative Template"}:
        rows.append(_def_row("Type", policy.policy_type, t))
    if policy.supported:
        rows.append(_def_row("Supported On", policy.supported, t))
    rows.append(_def_row("Source", policy.source or "gpreport.xml", t))

    # Only show Explanation when it contains something useful (not a raw Se*Privilege name)
    explain = (policy.explain or "").strip()
    if explain and not explain.startswith("Se") and not explain.startswith("MACHINE\\"):
        rows.append(
            f"<div style='margin:6px 0;'>"
            f"<span style='color:{t['label']}; font-size:11px; font-weight:700;"
            f" text-transform:uppercase; letter-spacing:0.4px;'>Explanation</span>"
            f"<p style='margin:4px 0 0 0; color:{t['text']}; font-size:12px;"
            f" line-height:1.6;'>{_multiline_html(explain)}</p>"
            f"</div>"
        )

    return f"<div style='display:grid; gap:4px;'>{''.join(rows)}</div>"


def _def_row(label: str, value: str, t: dict) -> str:
    return (
        f"<div style='display:flex; gap:12px; align-items:baseline; padding:3px 0;"
        f" border-bottom:1px solid {t['border']};'>"
        f"<span style='color:{t['label']}; font-size:11px; font-weight:700;"
        f" text-transform:uppercase; letter-spacing:0.4px; white-space:nowrap; min-width:90px;'>{escape(label)}</span>"
        f"<span style='color:{t['text']}; font-size:12px;'>{escape(value)}</span>"
        "</div>"
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
