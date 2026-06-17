from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.log import get_logger
from app.gpo.backup_catalog import BackupCatalogItem
from app.ui.widgets import badge, badge_item, configure_enterprise_table, readonly_item

_log = get_logger(__name__)


class DashboardPage(QWidget):
    view_backup_requested = Signal(str)
    compare_backups_requested = Signal(str, str)
    archive_requested = Signal(list)
    refresh_library_requested = Signal()
    cancel_scan_requested = Signal()
    selection_changed = Signal(int)
    settings_page_requested = Signal()

    def __init__(self, settings: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.catalog_items: list[BackupCatalogItem] = []
        self.compare_records: list[Any] = []
        self.compare_pending_path = ""
        self._scan_in_progress = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        title = QLabel("Backup Library")
        title.setObjectName("Title")
        subtitle = QLabel("Live backup sources — select one to view, or two to compare.")
        subtitle.setObjectName("Muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)

        self.view_backups_btn = QPushButton("View Backup(s)")
        self.view_backups_btn.setObjectName("PrimaryButton")
        self.view_backups_btn.setMinimumWidth(140)
        self.view_backups_btn.setToolTip("View one selected backup, or compare two selected backups.")
        self.view_backups_btn.clicked.connect(self._on_view_backups_clicked)

        self.archive_button = QPushButton("Archive")
        self.archive_button.setObjectName("GhostButton")
        self.archive_button.setMinimumWidth(88)
        self.archive_button.clicked.connect(self._on_archive_clicked)

        self.refresh_button = QPushButton("Scan")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setMinimumWidth(72)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        header.addWidget(self.view_backups_btn)
        header.addWidget(self.archive_button)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        layout.addWidget(self._build_library_stats())
        layout.addWidget(self._build_backup_library_panel(), 1)

    # ── command bar ───────────────────────────────────────────────────────────

    def _build_command_bar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")
        panel.setMaximumHeight(66)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        self.library_status_label = QLabel("No backups found")
        self.library_status_label.setObjectName("PanelTitle")
        self.last_scan_label = QLabel("Not scanned")
        self.last_scan_label.setObjectName("Muted")

        self.view_backups_btn = QPushButton("View Backup(s)")
        self.view_backups_btn.setObjectName("PrimaryButton")
        self.view_backups_btn.setMinimumWidth(140)
        self.view_backups_btn.setToolTip("View (1 selected) or Compare (2 selected)  —  Enter")
        self.view_backups_btn.clicked.connect(self._on_view_backups_clicked)

        archive_button = QPushButton("Archive")
        archive_button.setObjectName("GhostButton")
        archive_button.setMinimumWidth(88)
        archive_button.clicked.connect(self._on_archive_clicked)

        refresh_button = QPushButton("Scan")
        refresh_button.setObjectName("GhostButton")
        refresh_button.setMinimumWidth(72)
        refresh_button.clicked.connect(self._on_refresh_clicked)

        stats = QVBoxLayout()
        stats.setSpacing(2)
        stats.addWidget(self.library_status_label)
        stats.addWidget(self.last_scan_label)

        layout.addLayout(stats)
        layout.addStretch(1)
        layout.addWidget(self.view_backups_btn)
        layout.addWidget(archive_button)
        layout.addWidget(refresh_button)

        return panel

    # ── library panel ─────────────────────────────────────────────────────────

    def _build_library_stats(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("RaisedPanel")

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        self.source_count_value = QLabel("0")
        self.backup_count_value = QLabel("0")
        self.warning_count_value = QLabel("0")
        self.last_scan_value = QLabel("Not scanned")

        layout.addWidget(_stat_card("Sources", self.source_count_value))
        layout.addWidget(_stat_card("Live Backups", self.backup_count_value))
        layout.addWidget(_stat_card("Warnings", self.warning_count_value))
        layout.addWidget(_stat_card("Last Scan", self.last_scan_value))
        layout.addStretch()

        return panel

    def _build_backup_library_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(10)

        heading = QLabel("Live Backup Sources")
        heading.setObjectName("PanelTitle")

        self.source_filter = QComboBox()
        self.source_filter.setMinimumWidth(132)
        self.source_filter.addItem("All Sources")
        self.source_filter.currentTextChanged.connect(self._apply_source_filter)

        self.status_filter = QComboBox()
        self.status_filter.setMinimumWidth(128)
        self.status_filter.addItems(["All Statuses", "Valid", "Needs review"])
        self.status_filter.currentTextChanged.connect(self._apply_row_filter)

        self.date_filter = QComboBox()
        self.date_filter.setMinimumWidth(124)
        self.date_filter.addItems(["Any Date", "Last 7 Days", "Last 30 Days", "Last 90 Days"])
        self.date_filter.currentTextChanged.connect(self._apply_row_filter)

        self.context_filter = QComboBox()
        self.context_filter.setMinimumWidth(166)
        self.context_filter.addItems([
            "All Contexts",
            "Duplicate Names",
            "Has Warnings",
            "Has Saved Report",
            "Recently Changed",
        ])
        self.context_filter.currentTextChanged.connect(self._apply_row_filter)

        open_settings_button = QPushButton("Manage Sources")
        open_settings_button.setObjectName("GhostButton")
        open_settings_button.setMinimumWidth(120)
        open_settings_button.clicked.connect(self._request_settings_page)

        header.addWidget(heading)
        header.addStretch()
        header.addWidget(self.source_filter)
        header.addWidget(self.status_filter)
        header.addWidget(self.date_filter)
        header.addWidget(self.context_filter)
        header.addWidget(open_settings_button)
        layout.addLayout(header)

        health_row = QHBoxLayout()
        health_row.setSpacing(16)
        self.valid_count_label = QLabel("0 valid")
        self.valid_count_label.setObjectName("Muted")
        self.warning_count_label = QLabel("0 warnings")
        self.warning_count_label.setObjectName("Muted")
        self.summary_label = QLabel("Select one backup to view, or two backups to compare.")
        self.summary_label.setObjectName("Muted")
        health_row.addWidget(self.valid_count_label)
        health_row.addWidget(self.warning_count_label)
        health_row.addStretch()
        health_row.addWidget(self.summary_label)
        layout.addLayout(health_row)

        self.backup_filter_box = QLineEdit()
        self.backup_filter_box.setPlaceholderText("Filter by GPO name, domain, path, status, or source...")
        self.backup_filter_box.setClearButtonEnabled(True)
        self.backup_filter_box.textChanged.connect(self._apply_row_filter)
        layout.addWidget(self.backup_filter_box)

        layout.addWidget(self._build_backup_table(), 1)
        self.empty_helper = self._build_empty_helper()
        self.empty_helper.setVisible(False)
        layout.addWidget(self.empty_helper, 1)

        return panel

    def _build_backup_table(self) -> QTableWidget:
        self.backup_table = QTableWidget(0, 6)
        self.backup_table.setHorizontalHeaderLabels(["Source", "GPO Name", "Date", "Status", "Reports", "Items"])
        configure_enterprise_table(self.backup_table, row_height=38)
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self.backup_table.horizontalHeader().setStretchLastSection(False)
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.backup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.backup_table.horizontalHeader().resizeSection(5, 60)
        self.backup_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.backup_table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self.backup_table.installEventFilter(self)
        return self.backup_table

    # ── public API ────────────────────────────────────────────────────────────

    def populate(
        self,
        catalog_items: list[BackupCatalogItem],
        scan_time: str | None = None,
    ) -> None:
        self.catalog_items = catalog_items
        self._populate_source_filter()
        self._apply_source_filter()

        if catalog_items:
            valid = sum(1 for i in catalog_items if i.is_valid)
            warnings = len(catalog_items) - valid
            self.valid_count_label.setText(f"{valid} valid")
            self.warning_count_label.setText(f"{warnings} warning{'s' if warnings != 1 else ''}")
        else:
            self.valid_count_label.setText("0 valid")
            self.warning_count_label.setText("0 warnings")

        if hasattr(self, "source_count_value"):
            warnings = len(catalog_items) - sum(1 for item in catalog_items if item.is_valid)
            self.source_count_value.setText(str(len(self._backup_roots())))
            self.backup_count_value.setText(str(len(catalog_items)))
            self.warning_count_value.setText(str(warnings))
            self.last_scan_value.setText(
                scan_time or (datetime.now().strftime("%I:%M %p").lstrip("0") if catalog_items else "Not scanned")
            )

        self._update_selection_summary()
        self._update_empty_helper()

    def set_compare_records(self, records: list[Any]) -> None:
        self.compare_records = records
        self._apply_row_filter()

    def get_selected_backup_paths(self) -> list[str]:
        rows = sorted({index.row() for index in self.backup_table.selectedIndexes()})
        paths: list[str] = []
        for row in rows:
            item = self.backup_table.item(row, 1)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                paths.append(str(path))
        return paths

    def pre_select_backup(self, backup_path: str) -> None:
        for row in range(self.backup_table.rowCount()):
            item = self.backup_table.item(row, 1)
            if item and item.data(Qt.ItemDataRole.UserRole) == backup_path:
                self.backup_table.clearSelection()
                self.backup_table.selectRow(row)
                self.backup_table.scrollToItem(item)
                self._update_selection_summary()
                return

    def begin_compare_pending(self, backup_path: str) -> None:
        self.compare_pending_path = backup_path
        self.pre_select_backup(backup_path)
        self._update_selection_summary()

    def clear_compare_pending(self) -> None:
        if not self.compare_pending_path:
            return
        self.compare_pending_path = ""
        self._update_selection_summary()

    def set_scan_state(self, scanning: bool, message: str = "") -> None:
        self._scan_in_progress = scanning
        label = "Cancel" if scanning else "Scan"
        self.refresh_button.setText(label)
        if hasattr(self, "empty_helper_scan_btn"):
            self.empty_helper_scan_btn.setText(label)
        if message:
            self.summary_label.setText(message)

    # ── signal handlers ───────────────────────────────────────────────────────

    def _request_settings_page(self) -> None:
        self.settings_page_requested.emit()

    def _on_refresh_clicked(self) -> None:
        if self._scan_in_progress:
            self.cancel_scan_requested.emit()
        else:
            self.refresh_library_requested.emit()

    def _on_view_backups_clicked(self) -> None:
        paths = self.get_selected_backup_paths()
        if len(paths) == 1:
            self.view_backup_requested.emit(paths[0])
        elif len(paths) == 2:
            self.compare_backups_requested.emit(paths[0], paths[1])

    def _on_row_double_clicked(self, row: int, col: int) -> None:
        item = self.backup_table.item(row, 1)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.view_backup_requested.emit(str(path))

    def _on_archive_clicked(self) -> None:
        paths = self.get_selected_backup_paths()
        if paths:
            self.archive_requested.emit(paths)

    def _on_selection_changed(self) -> None:
        count = len(self.get_selected_backup_paths())
        if count == 2:
            self.view_backups_btn.setText("Compare Backups")
        else:
            self.view_backups_btn.setText("View Backup(s)")
        self._update_selection_summary()
        self.selection_changed.emit(count)

    def _apply_backup_filter(self) -> None:
        self._apply_row_filter()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.backup_table and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            paths = self.get_selected_backup_paths()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and paths:
                self._on_view_backups_clicked()
                return True
            if key == Qt.Key.Key_Delete and paths:
                self.archive_requested.emit(paths)
                return True
        return super().eventFilter(obj, event)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _populate_source_filter(self) -> None:
        previous = self.source_filter.currentText()
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem("All Sources")
        for source_number in sorted({item.source_index for item in self.catalog_items}):
            self.source_filter.addItem(f"Source {source_number}")
        index = self.source_filter.findText(previous)
        self.source_filter.setCurrentIndex(index if index >= 0 else 0)
        self.source_filter.blockSignals(False)

    def _apply_source_filter(self) -> None:
        selected = self.source_filter.currentText()
        if selected == "All Sources":
            self._populate_backup_table(self.catalog_items)
        else:
            try:
                source_index = int(selected.rsplit(" ", 1)[1])
            except (IndexError, ValueError):
                source_index = 0
            self._populate_backup_table([
                item for item in self.catalog_items if item.source_index == source_index
            ])

    def _populate_backup_table(self, items: list[BackupCatalogItem]) -> None:
        self.backup_table.setSortingEnabled(False)
        self.backup_table.setRowCount(0)
        report_summaries = _saved_report_summaries(self.compare_records)

        for item in sorted(
            items,
            key=lambda i: (i.display_name.casefold(), i.source_index, i.folder_name.casefold()),
        ):
            row = self.backup_table.rowCount()
            self.backup_table.insertRow(row)

            source_item = readonly_item(str(item.source_index), sort_key=(item.source_index, item.display_name.casefold()))
            name_item = readonly_item(item.display_name, sort_key=_backup_name_sort_key(item))
            name_item.setData(Qt.ItemDataRole.UserRole, item.path)
            name_item.setToolTip(item.detail)
            date_item = readonly_item(
                _display_backup_time(item.backup_time, item.path),
                sort_key=_backup_time_sort_key(item.backup_time, item.path),
            )
            count_item = readonly_item(str(item.item_count), sort_key=item.item_count)
            status_item = badge_item(item.status, sort_key=(item.status.casefold(), item.display_name.casefold()))
            status_item.setToolTip(item.detail)
            status_badge = badge(item.status, "valid" if item.is_valid else "review", min_width=92)
            status_badge.setToolTip(item.detail)
            related_reports = report_summaries.get(item.path, [])
            report_count = len(related_reports)
            report_text = f"{report_count} report{'s' if report_count != 1 else ''}" if report_count else "None"
            report_item = readonly_item(
                "" if report_count else report_text,
                user_data=report_text,
                sort_key=(0 if report_count else 1, -report_count, item.display_name.casefold()),
            )
            report_item.setToolTip(_saved_report_tooltip(related_reports))

            self.backup_table.setItem(row, 0, source_item)
            self.backup_table.setItem(row, 1, name_item)
            self.backup_table.setItem(row, 2, date_item)
            self.backup_table.setItem(row, 3, status_item)
            self.backup_table.setItem(row, 4, report_item)
            self.backup_table.setItem(row, 5, count_item)
            self.backup_table.setCellWidget(row, 3, status_badge)
            if report_count:
                report_badge = badge(report_text, "review", min_width=92)
                report_badge.setToolTip(_saved_report_tooltip(related_reports))
                self.backup_table.setCellWidget(row, 4, report_badge)

        self.backup_table.setSortingEnabled(True)
        self.backup_table.sortItems(1, Qt.SortOrder.AscendingOrder)
        self._apply_row_filter()
        self._update_selection_summary()
        self._update_empty_helper()

    def _apply_row_filter(self) -> None:
        query = self.backup_filter_box.text().strip().casefold()
        status_filter = self.status_filter.currentText() if hasattr(self, "status_filter") else "All Statuses"
        date_filter = self.date_filter.currentText() if hasattr(self, "date_filter") else "Any Date"
        context_filter = self.context_filter.currentText() if hasattr(self, "context_filter") else "All Contexts"
        duplicate_names = _duplicate_display_names(self.catalog_items)
        saved_report_paths = _saved_report_paths(self.compare_records)
        newest_mtime_by_source = _newest_source_mtimes(self.catalog_items)

        for row in range(self.backup_table.rowCount()):
            haystack_parts: list[str] = []
            for col in range(self.backup_table.columnCount()):
                cell = self.backup_table.item(row, col)
                if cell is not None:
                    haystack_parts.append(cell.text())
                    if col == 4:
                        haystack_parts.append(str(cell.data(Qt.ItemDataRole.UserRole) or ""))
            path_item = self.backup_table.item(row, 1)
            if path_item is not None:
                haystack_parts.append(str(path_item.data(Qt.ItemDataRole.UserRole) or ""))
            haystack = " ".join(haystack_parts).casefold()
            status_item = self.backup_table.item(row, 3)
            status_text = str(status_item.data(Qt.ItemDataRole.UserRole) if status_item else "")
            backup_path = str(path_item.data(Qt.ItemDataRole.UserRole) if path_item else "")
            item = _catalog_item_for_path(self.catalog_items, backup_path)
            query_match = not query or query in haystack
            status_match = status_filter == "All Statuses" or status_text == status_filter
            date_match = _matches_date_filter(item, date_filter)
            context_match = _matches_context_filter(
                item,
                context_filter,
                duplicate_names,
                saved_report_paths,
                newest_mtime_by_source,
            )
            self.backup_table.setRowHidden(row, not (query_match and status_match and date_match and context_match))
        self._update_selection_summary()
        self._update_empty_helper()

    def _update_selection_summary(self) -> None:
        selected_count = len(self.get_selected_backup_paths())
        if self.compare_pending_path and selected_count < 2:
            self.summary_label.setText("Compare pending. Select one more backup to open Compare.")
        elif selected_count == 0 and not self.catalog_items:
            roots = self._backup_roots()
            if roots:
                self.summary_label.setText("No backups shown. Click Scan to refresh the configured backup sources.")
            else:
                self.summary_label.setText("Add a backup directory in Settings, then scan the library.")
        elif selected_count == 0:
            visible = _visible_row_count(self.backup_table)
            if visible != len(self.catalog_items):
                self.summary_label.setText(f"{visible} of {len(self.catalog_items)} backups shown. Select one to view or two to compare.")
            else:
                self.summary_label.setText(f"{len(self.catalog_items)} backups available. Select one to view or two to compare.")
        elif selected_count == 1:
            self.summary_label.setText("1 selected — Enter to view, select one more to compare.")
        elif selected_count == 2:
            self.summary_label.setText("2 selected — Enter to compare, Delete to archive.")
        else:
            self.summary_label.setText("Select only one backup to view or two backups to compare.")

    def _build_empty_helper(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(32, 48, 32, 48)
        layout.setSpacing(12)

        self.empty_helper_title = QLabel("Backup Library is empty")
        self.empty_helper_title.setObjectName("PanelTitle")
        self.empty_helper_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_helper_body = QLabel("")
        self.empty_helper_body.setObjectName("Muted")
        self.empty_helper_body.setWordWrap(True)
        self.empty_helper_body.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_helper_settings_btn = QPushButton("Set Up Directory")
        self.empty_helper_settings_btn.setObjectName("PrimaryButton")
        self.empty_helper_settings_btn.setFixedWidth(180)
        self.empty_helper_settings_btn.clicked.connect(self.settings_page_requested.emit)

        self.empty_helper_scan_btn = QPushButton("Scan")
        self.empty_helper_scan_btn.setObjectName("GhostButton")
        self.empty_helper_scan_btn.setFixedWidth(180)
        self.empty_helper_scan_btn.clicked.connect(self._on_refresh_clicked)

        layout.addStretch()
        layout.addWidget(self.empty_helper_title)
        layout.addWidget(self.empty_helper_body)
        layout.addSpacing(8)
        layout.addWidget(self.empty_helper_settings_btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_helper_scan_btn, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return frame

    def _update_empty_helper(self) -> None:
        total_rows = self.backup_table.rowCount()
        visible_rows = _visible_row_count(self.backup_table)
        has_visible_rows = visible_rows > 0
        self.backup_table.setVisible(has_visible_rows)
        if has_visible_rows:
            self.empty_helper.setVisible(False)
            return

        roots = self._backup_roots()
        self.empty_helper.setVisible(True)
        if total_rows:
            self.empty_helper_title.setText("No backups match the current filters")
            self.empty_helper_body.setText(
                "Adjust the source, status, date, context, or text filter to show more backups."
            )
            self.empty_helper_settings_btn.setVisible(False)
            self.empty_helper_scan_btn.setVisible(False)
        elif roots:
            self.empty_helper_title.setText("No backups are currently shown")
            self.empty_helper_body.setText(
                "Backup sources are configured, but no backups are loaded yet. Click Scan to refresh the library."
            )
            self.empty_helper_settings_btn.setVisible(True)
            self.empty_helper_settings_btn.setText("Manage Sources")
            self.empty_helper_scan_btn.setVisible(True)
        else:
            self.empty_helper_title.setText("Set up your Backup Library")
            self.empty_helper_body.setText(
                "Add the folder that contains your Group Policy backup directories, then run a scan."
            )
            self.empty_helper_settings_btn.setVisible(True)
            self.empty_helper_settings_btn.setText("Set Up Directory")
            self.empty_helper_scan_btn.setVisible(False)

    def _backup_roots(self) -> list[str]:
        storage = self.settings.setdefault("storage", {})
        roots = storage.get("backup_roots", [])
        if not isinstance(roots, list):
            roots = []
        legacy_root = str(storage.get("backup_root", "")).strip()
        clean = [str(root).strip() for root in roots if str(root).strip()]
        if legacy_root and legacy_root not in clean:
            clean.insert(0, legacy_root)
        return clean



# ── module helpers ─────────────────────────────────────────────────────────────

def _display_backup_time(backup_time: str, fallback_path: str) -> str:
    if backup_time:
        try:
            parsed = datetime.fromisoformat(backup_time)
            return parsed.strftime("%m/%d/%Y %I:%M %p").replace(" 0", " ")
        except ValueError:
            return backup_time
    try:
        modified = datetime.fromtimestamp(Path(fallback_path).stat().st_mtime)
        return modified.strftime("%m/%d/%Y %I:%M %p").replace(" 0", " ")
    except OSError:
        return "Not reported"


def _backup_name_sort_key(item: BackupCatalogItem) -> tuple[str, int, str]:
    return (item.display_name.casefold(), item.source_index, item.folder_name.casefold())


def _backup_time_sort_key(backup_time: str, fallback_path: str) -> float:
    if backup_time:
        try:
            return datetime.fromisoformat(backup_time).timestamp()
        except ValueError:
            pass
    try:
        return Path(fallback_path).stat().st_mtime
    except OSError:
        return 0.0


def _catalog_item_for_path(items: list[BackupCatalogItem], path: str) -> BackupCatalogItem | None:
    return next((item for item in items if item.path == path), None)


def _duplicate_display_names(items: list[BackupCatalogItem]) -> set[str]:
    sources_by_name: dict[str, set[int]] = {}
    for item in items:
        key = item.display_name.casefold()
        sources_by_name.setdefault(key, set()).add(item.source_index)
    return {name for name, sources in sources_by_name.items() if len(sources) > 1}


def _saved_report_paths(records: list[Any]) -> set[str]:
    paths: set[str] = set()
    for record in records:
        for attr in ("backup_a_path", "backup_b_path"):
            value = str(getattr(record, attr, "") or "")
            if value:
                paths.add(value)
    return paths


def _saved_report_summaries(records: list[Any]) -> dict[str, list[Any]]:
    summaries: dict[str, list[Any]] = {}
    for record in records:
        for attr in ("backup_a_path", "backup_b_path"):
            value = str(getattr(record, attr, "") or "")
            if value:
                summaries.setdefault(value, []).append(record)
    return summaries


def _saved_report_tooltip(records: list[Any]) -> str:
    if not records:
        return "No saved compare report contains this backup."
    lines = ["Saved compare reports containing this backup:"]
    for record in records[:6]:
        title = str(getattr(record, "title", "") or "Saved compare")
        saved_at = _display_saved_report_time(str(getattr(record, "saved_at", "") or ""))
        suffix = f" ({saved_at})" if saved_at else ""
        lines.append(f"- {title}{suffix}")
    remaining = len(records) - 6
    if remaining > 0:
        lines.append(f"- {remaining} more")
    return "\n".join(lines)


def _display_saved_report_time(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%m/%d/%Y %I:%M %p").replace(" 0", " ")
    except ValueError:
        return value


def _newest_source_mtimes(items: list[BackupCatalogItem]) -> dict[str, float]:
    newest: dict[str, float] = {}
    for item in items:
        try:
            mtime = Path(item.path).stat().st_mtime
        except OSError:
            continue
        current = newest.get(item.source_path, 0.0)
        if mtime > current:
            newest[item.source_path] = mtime
    return newest


def _item_timestamp(item: BackupCatalogItem | None) -> float:
    if item is None:
        return 0.0
    if item.backup_time:
        try:
            return datetime.fromisoformat(item.backup_time).timestamp()
        except ValueError:
            pass
    try:
        return Path(item.path).stat().st_mtime
    except OSError:
        return 0.0


def _matches_date_filter(item: BackupCatalogItem | None, label: str) -> bool:
    if label == "Any Date":
        return True
    days = {
        "Last 7 Days": 7,
        "Last 30 Days": 30,
        "Last 90 Days": 90,
    }.get(label)
    if days is None:
        return True
    timestamp = _item_timestamp(item)
    if timestamp <= 0:
        return False
    age_seconds = datetime.now().timestamp() - timestamp
    return age_seconds <= days * 24 * 60 * 60


def _matches_context_filter(
    item: BackupCatalogItem | None,
    label: str,
    duplicate_names: set[str],
    saved_report_paths: set[str],
    newest_mtime_by_source: dict[str, float],
) -> bool:
    if label == "All Contexts":
        return True
    if item is None:
        return False
    if label == "Duplicate Names":
        return item.display_name.casefold() in duplicate_names
    if label == "Has Warnings":
        return not item.is_valid
    if label == "Has Saved Report":
        return item.path in saved_report_paths
    if label == "Recently Changed":
        try:
            mtime = Path(item.path).stat().st_mtime
        except OSError:
            return False
        newest = newest_mtime_by_source.get(item.source_path, 0.0)
        return newest > 0 and newest - mtime <= 60
    return True


def _visible_row_count(table: QTableWidget) -> int:
    return sum(1 for row in range(table.rowCount()) if not table.isRowHidden(row))


def _short_value(value: str, limit: int = 180) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 3]}..."


def _stat_card(label_text: str, value_label: QLabel) -> QWidget:
    frame = QFrame()
    frame.setObjectName("MetricCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(3)

    value_label.setObjectName("Title")
    caption = QLabel(label_text)
    caption.setObjectName("Muted")

    layout.addWidget(value_label)
    layout.addWidget(caption)
    return frame
