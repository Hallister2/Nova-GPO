from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.gpo.backup_catalog import BackupCatalogItem
from app.library_store import CompareLibraryRecord


class HomePage(QWidget):
    backup_library_requested = Signal()
    reports_requested = Signal()
    settings_requested = Signal()

    def __init__(self, get_backup_roots: Callable[[], list[str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._get_backup_roots = get_backup_roots

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(4)

        title = QLabel("Dashboard")
        title.setObjectName("Title")
        subtitle = QLabel("Operational overview for Group Policy backup review.")
        subtitle.setObjectName("Muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)

        scan_button = QPushButton("Open Backup Library")
        scan_button.setObjectName("PrimaryButton")
        scan_button.clicked.connect(self.backup_library_requested.emit)

        header.addLayout(title_block, 1)
        header.addWidget(scan_button)
        layout.addLayout(header)

        layout.addWidget(self._build_metrics_panel())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_focus_panel(), 2)
        body.addWidget(self._build_actions_panel(), 1)
        layout.addLayout(body, 1)

    def update_overview(
        self,
        catalog_items: list[BackupCatalogItem],
        compare_records: list[CompareLibraryRecord],
        selected_count: int,
    ) -> None:
        source_count = len(self._get_backup_roots())
        valid_count = sum(1 for item in catalog_items if item.is_valid)
        warning_count = len(catalog_items) - valid_count
        missing_sources = sum(1 for record in compare_records if record.source_status != "Sources available")

        self.sources_label.setText(str(source_count))
        self.backups_label.setText(str(len(catalog_items)))
        self.warnings_label.setText(str(warning_count))
        self.saved_reviews_label.setText(str(len(compare_records)))

        if selected_count == 2:
            self.focus_summary_label.setText("Two backups are selected in the Library and ready to compare.")
        elif compare_records:
            self.focus_summary_label.setText(
                f"{len(compare_records)} saved compare review(s) on record."
            )
        elif catalog_items:
            self.focus_summary_label.setText(
                "Backups are available. Open the Backup Library to view, compare, pin, or archive review work."
            )
        else:
            self.focus_summary_label.setText(
                "No backups are indexed yet. Add backup sources in Settings, then scan the Backup Library."
            )

        self.source_health_label.setText(
            f"{valid_count} valid backup(s), {warning_count} warning(s), {missing_sources} saved review(s) with missing sources."
        )

        if compare_records:
            latest = compare_records[0]
            self.latest_review_label.setText(
                f"Latest saved review: {latest.backup_a_title} vs {latest.backup_b_title}"
            )
            self.latest_review_detail_label.setText(
                f"{latest.actionable} actionable / {latest.ignored} ignored / {latest.reviewed} reviewed"
            )
        else:
            self.latest_review_label.setText("No saved compare reviews yet")
            self.latest_review_detail_label.setText("Save a Compare session to preserve notes and reports.")

    def _build_metrics_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")
        metrics = QHBoxLayout(panel)
        metrics.setContentsMargins(16, 14, 16, 14)
        metrics.setSpacing(12)

        self.sources_label = QLabel("0")
        self.backups_label = QLabel("0")
        self.warnings_label = QLabel("0")
        self.saved_reviews_label = QLabel("0")

        metrics.addWidget(_metric_card("Sources", self.sources_label, self.settings_requested.emit))
        metrics.addWidget(_metric_card("Live Backups", self.backups_label, self.backup_library_requested.emit))
        metrics.addWidget(_metric_card("Warnings", self.warnings_label, self.backup_library_requested.emit))
        metrics.addWidget(_metric_card("Saved Reviews", self.saved_reviews_label, self.reports_requested.emit))
        return panel

    def _build_focus_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Review Focus")
        title.setObjectName("PanelTitle")
        self.focus_summary_label = QLabel("Scan the Backup Library to begin.")
        self.focus_summary_label.setObjectName("Muted")
        self.focus_summary_label.setWordWrap(True)
        self.source_health_label = QLabel("No source health data yet.")
        self.source_health_label.setObjectName("Muted")
        self.source_health_label.setWordWrap(True)

        self.latest_review_label = QLabel("No saved compare reviews yet")
        self.latest_review_label.setObjectName("StatusLabel")
        self.latest_review_label.setWordWrap(True)
        self.latest_review_detail_label = QLabel("Save a Compare session to preserve notes and reports.")
        self.latest_review_detail_label.setObjectName("Muted")
        self.latest_review_detail_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.focus_summary_label)
        layout.addSpacing(8)
        layout.addWidget(self.source_health_label)
        layout.addSpacing(14)
        layout.addWidget(self.latest_review_label)
        layout.addWidget(self.latest_review_detail_label)
        layout.addStretch()
        return panel

    def _build_actions_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Next Actions")
        title.setObjectName("PanelTitle")
        library_button = QPushButton("Backup Library")
        library_button.setObjectName("PrimaryButton")
        library_button.clicked.connect(self.backup_library_requested.emit)
        reports_button = QPushButton("Reports")
        reports_button.setObjectName("GhostButton")
        reports_button.clicked.connect(self.reports_requested.emit)
        settings_button = QPushButton("Settings")
        settings_button.setObjectName("GhostButton")
        settings_button.clicked.connect(self.settings_requested.emit)

        layout.addWidget(title)
        layout.addWidget(_action_line("Library", "View live backup sources and choose backups to compare."))
        layout.addWidget(_action_line("Compare", "Select two backups in the Library to review changes."))
        layout.addWidget(_action_line("Reports", "Open saved compare reviews that remain available after source cleanup."))
        layout.addSpacing(8)
        layout.addWidget(library_button)
        layout.addWidget(reports_button)
        layout.addWidget(settings_button)
        layout.addStretch()
        return panel


class _ClickFrame(QFrame):
    def __init__(self, callback: Callable, parent=None) -> None:
        super().__init__(parent)
        self._callback = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setProperty("clickable", "true")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._callback()
        super().mousePressEvent(event)


def _metric_card(label: str, value_label: QLabel, on_click: Callable | None = None) -> QWidget:
    card = _ClickFrame(on_click) if on_click else QFrame()
    card.setObjectName("MetricCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(3)
    value_label.setObjectName("Title")
    value_label.setMinimumWidth(90)
    caption = QLabel(label)
    caption.setObjectName("Muted")
    layout.addWidget(value_label)
    layout.addWidget(caption)
    return card


def _action_line(title: str, detail: str) -> QWidget:
    row = QFrame()
    row.setObjectName("MetricCard")
    layout = QVBoxLayout(row)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(2)
    heading = QLabel(title)
    heading.setObjectName("StatusLabel")
    text = QLabel(detail)
    text.setObjectName("Muted")
    text.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(text)
    return row
