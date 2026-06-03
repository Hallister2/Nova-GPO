from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.log import get_logger
from app.gpo.backup_catalog import BackupCatalogItem
from app.library_store import CompareLibraryRecord
from app.ui.widgets import badge

_log = get_logger(__name__)


class ReportsPage(QWidget):
    compare_backups_requested = Signal(str, str)
    open_compare_archive_requested = Signal(str)
    delete_compare_archive_requested = Signal(str)
    rename_compare_archive_requested = Signal(str, str)   # record_path, new_title
    backup_library_requested = Signal()

    def __init__(
        self,
        settings: dict[str, Any],
        get_backup_roots: Callable[[], list[str]],
        get_selected_paths: Callable[[], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._get_backup_roots = get_backup_roots
        self._get_selected_paths = get_selected_paths
        self._compare_records: list[CompareLibraryRecord] = []
        self._report_filter: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addWidget(self._build_stats_strip())
        layout.addWidget(self._build_reports_area(), 1)

    # ── public API ────────────────────────────────────────────────────────────

    def populate_compare_records(self, records: list[CompareLibraryRecord]) -> None:
        self._compare_records = records
        self._rebuild_stats()
        self._rebuild_cards()

    def update_stats(self, catalog_items: list[BackupCatalogItem], selected_count: int) -> None:
        self._rebuild_stats()
        if selected_count == 2:
            self._generate_btn.setText("Compare Selected")
            self._generate_btn.setEnabled(True)
        else:
            self._generate_btn.setText("Select 2 to Compare")
            self._generate_btn.setEnabled(False)

    # ── builders ──────────────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()

        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title = QLabel("Reports")
        title.setObjectName("Title")
        subtitle = QLabel("Saved compare results — open, rename, or delete archived reports.")
        subtitle.setObjectName("Muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        self._generate_btn = QPushButton("Select 2 to Compare")
        self._generate_btn.setObjectName("PrimaryButton")
        self._generate_btn.setEnabled(False)
        self._generate_btn.setToolTip(
            "Select two backups in the Backup Library, then click here to run a comparison."
        )
        self._generate_btn.clicked.connect(self._on_generate_clicked)

        row.addLayout(title_block, 1)
        row.addWidget(self._generate_btn)
        return row

    def _build_stats_strip(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")
        panel.setMaximumHeight(70)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(0)

        self._stat_reports = _stat_card("Saved Reports", "0")
        self._stat_findings = _stat_card("Actionable Findings", "0")
        self._stat_reviewed = _stat_card("Items Reviewed", "0")

        layout.addWidget(self._stat_reports)
        layout.addWidget(_vdivider())
        layout.addWidget(self._stat_findings)
        layout.addWidget(_vdivider())
        layout.addWidget(self._stat_reviewed)
        layout.addStretch()

        return panel

    def _build_reports_area(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._report_search = QLineEdit()
        self._report_search.setPlaceholderText("Filter reports by name or backup…")
        self._report_search.setClearButtonEnabled(True)
        self._report_search.textChanged.connect(self._on_report_filter_changed)
        filter_row.addWidget(self._report_search, 1)
        layout.addLayout(filter_row)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cards_container = QWidget()
        self._cards_container.setObjectName("AccordionContent")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 4, 4, 4)
        self._cards_layout.setSpacing(10)

        self._cards_scroll.setWidget(self._cards_container)
        layout.addWidget(self._cards_scroll, 1)

        self._rebuild_cards()
        return container

    def _on_report_filter_changed(self, text: str) -> None:
        self._report_filter = text.strip().lower()
        self._rebuild_cards()

    def _rebuild_stats(self) -> None:
        records = self._compare_records
        total_findings = sum(r.actionable for r in records)
        total_reviewed = sum(r.reviewed for r in records)
        self._stat_reports.findChild(QLabel, "stat_value").setText(str(len(records)))
        self._stat_findings.findChild(QLabel, "stat_value").setText(str(total_findings))
        self._stat_reviewed.findChild(QLabel, "stat_value").setText(str(total_reviewed))

    def _rebuild_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        q = self._report_filter
        visible = [
            r for r in self._compare_records
            if not q or q in r.title.lower()
            or q in r.backup_a_title.lower()
            or q in r.backup_b_title.lower()
        ] if self._compare_records else []

        if not self._compare_records:
            self._cards_layout.addWidget(self._build_empty_state())
            self._cards_layout.addStretch()
            return

        if not visible:
            no_match = QLabel(f'No reports match "{self._report_filter}".')
            no_match.setObjectName("Muted")
            no_match.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cards_layout.addWidget(no_match)
            self._cards_layout.addStretch()
            return

        for record in visible:
            self._cards_layout.addWidget(self._build_report_card(record))

        self._cards_layout.addStretch()

    def _build_report_card(self, record: CompareLibraryRecord) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 14, 20, 14)
        outer.setSpacing(8)

        # ── top row: title + actions ──────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(10)

        title_lbl = QLabel(record.title)
        title_lbl.setObjectName("PanelTitle")
        title_lbl.setWordWrap(True)

        open_btn = QPushButton("Open Review")
        open_btn.setObjectName("PrimaryButton")
        open_btn.setFixedHeight(28)
        open_btn.clicked.connect(lambda: self.open_compare_archive_requested.emit(record.record_path))

        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("GhostButton")
        rename_btn.setFixedHeight(28)
        rename_btn.clicked.connect(lambda: self._rename_record(record))

        delete_btn = QPushButton("Delete")
        delete_btn.setObjectName("GhostButton")
        delete_btn.setFixedHeight(28)
        delete_btn.clicked.connect(lambda: self.delete_compare_archive_requested.emit(record.record_path))

        top.addWidget(title_lbl, 1)
        top.addWidget(open_btn)
        top.addWidget(rename_btn)
        top.addWidget(delete_btn)
        outer.addLayout(top)

        # ── subtitle: Backup A → Backup B + date ─────────────────────────────
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)

        ab_lbl = QLabel(f"{record.backup_a_title}  →  {record.backup_b_title}")
        ab_lbl.setObjectName("Muted")
        ab_lbl.setWordWrap(True)

        date_lbl = QLabel(_display_record_time(record.saved_at))
        date_lbl.setObjectName("Muted")
        date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        sub_row.addWidget(ab_lbl, 1)
        sub_row.addWidget(date_lbl)
        outer.addLayout(sub_row)

        # ── divider ───────────────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("Separator")
        outer.addWidget(divider)

        # ── stats row ─────────────────────────────────────────────────────────
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)

        def _chip(label: str, value: str | int) -> QLabel:
            lbl = QLabel(f"{value}  {label}")
            lbl.setObjectName("Muted")
            return lbl

        stats_row.addWidget(_chip("compared", record.total_items))
        stats_row.addWidget(_chip("actionable", record.actionable))
        stats_row.addWidget(_chip("changed", record.changed))
        if record.added:
            stats_row.addWidget(_chip("missing in A", record.added))
        if record.removed:
            stats_row.addWidget(_chip("missing in B", record.removed))
        stats_row.addWidget(_chip("reviewed", record.reviewed))
        stats_row.addStretch()

        source_badge = badge(record.source_status, _source_badge_state(record.source_status), min_width=132)
        source_badge.setToolTip(
            "Saved reports remain available even when original backup folders are missing."
        )
        stats_row.addWidget(source_badge)
        outer.addLayout(stats_row)

        return card

    def _build_empty_state(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(32, 48, 32, 48)
        layout.setSpacing(12)

        heading = QLabel("No saved reports yet")
        heading.setObjectName("PanelTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QLabel(
            "Select two backups in the Backup Library and use Compare to run a comparison.\n"
            'Use "Save to Library" inside the Compare window to create a saved report here.'
        )
        body.setObjectName("Muted")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)

        go_btn = QPushButton("Open Backup Library")
        go_btn.setObjectName("GhostButton")
        go_btn.setFixedWidth(180)
        go_btn.clicked.connect(self.backup_library_requested.emit)

        layout.addStretch()
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addSpacing(8)
        layout.addWidget(go_btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        return frame

    # ── actions ───────────────────────────────────────────────────────────────

    def _on_generate_clicked(self) -> None:
        selected = self._get_selected_paths()
        if len(selected) == 2:
            self.compare_backups_requested.emit(selected[0], selected[1])
        else:
            QMessageBox.information(
                self,
                "Select Two Backups",
                "Select exactly two backups in the Backup Library, then click Compare & Save.",
            )

    def _rename_record(self, record: CompareLibraryRecord) -> None:
        new_title, ok = QInputDialog.getText(
            self,
            "Rename Report",
            "Name:",
            text=record.title,
        )
        if ok and new_title.strip():
            self.rename_compare_archive_requested.emit(record.record_path, new_title.strip())


# ── module helpers ─────────────────────────────────────────────────────────────

def _stat_card(label_text: str, initial_value: str) -> QWidget:
    frame = QFrame()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 0, 28, 0)
    layout.setSpacing(2)

    value_lbl = QLabel(initial_value)
    value_lbl.setObjectName("Title")
    value_lbl.setProperty("name", "stat_value")
    # Use findChild by object name later — set a QLabel child name
    value_lbl.setObjectName("stat_value")

    caption = QLabel(label_text)
    caption.setObjectName("Muted")

    layout.addWidget(value_lbl)
    layout.addWidget(caption)
    return frame


def _vdivider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setObjectName("Separator")
    line.setFixedWidth(1)
    return line


def _source_badge_state(status: str) -> str:
    if status == "Sources available":
        return "valid"
    if status == "One source missing":
        return "review"
    return "removed"


def _display_record_time(saved_at: str) -> str:
    if not saved_at:
        return "Not recorded"
    try:
        parsed = datetime.fromisoformat(saved_at)
    except ValueError:
        return saved_at
    return parsed.strftime("%m/%d/%Y  %I:%M %p").replace(" 0", " ")
