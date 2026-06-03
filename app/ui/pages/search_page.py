from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.log import get_logger
from app.gpo.backup_catalog import BackupCatalogItem
from app.gpo.search import SearchResult, search_backup_library
from app.ui.widgets import configure_enterprise_table, readonly_item

_log = get_logger(__name__)

_SEARCH_LIMIT = 1000


class SearchPage(QWidget):
    view_backup_requested = Signal(str)

    def __init__(
        self,
        settings: dict[str, Any],
        get_backup_roots: Callable[[], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._get_backup_roots = get_backup_roots

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)

        title = QLabel("Global Search")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Search GPO names, policy names, configured values, and parsed artifact contents across all backup sources."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_results_table(), 1)

        self.global_search_box.returnPressed.connect(self._run_search)
        self.global_search_table.cellDoubleClicked.connect(
            lambda row, col: self._open_selected_result()
        )

    # ── public API ────────────────────────────────────────────────────────

    def focus_search(self) -> None:
        self.global_search_box.setFocus()
        self.global_search_box.selectAll()

    def refresh_source_filter(self, catalog_items: list[BackupCatalogItem]) -> None:
        previous = self.global_source_filter.currentText()
        self.global_source_filter.blockSignals(True)
        self.global_source_filter.clear()
        self.global_source_filter.addItem("All Sources")
        for source_number in sorted({item.source_index for item in catalog_items}):
            self.global_source_filter.addItem(f"Source {source_number}")
        index = self.global_source_filter.findText(previous)
        self.global_source_filter.setCurrentIndex(index if index >= 0 else 0)
        self.global_source_filter.blockSignals(False)

    # ── builders ──────────────────────────────────────────────────────────

    def _build_filter_bar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("FilterBar")
        row = QHBoxLayout(panel)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)

        self.global_search_box = QLineEdit()
        self.global_search_box.setPlaceholderText(
            "Search all backups, policies, settings, registry paths, scripts..."
        )

        self.global_source_filter = QComboBox()
        self.global_source_filter.setMinimumWidth(120)
        self.global_source_filter.addItem("All Sources")

        self.global_type_filter = QComboBox()
        self.global_type_filter.setMinimumWidth(130)
        self.global_type_filter.addItems(
            ["All Types", "GPO Backup", "Administrative Template", "Preference", "Artifact"]
        )

        self.global_scope_filter = QComboBox()
        self.global_scope_filter.setMinimumWidth(140)
        self.global_scope_filter.addItems(
            ["All Scopes", "Backup", "Computer Configuration", "User Configuration", "Artifacts"]
        )

        self.exact_search = QCheckBox("Exact phrase")
        self.exact_search.setObjectName("Muted")

        search_button = QPushButton("Search")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self._run_search)

        open_button = QPushButton("Open Result")
        open_button.setObjectName("GhostButton")
        open_button.clicked.connect(self._open_selected_result)

        clear_button = QPushButton("Clear")
        clear_button.setObjectName("GhostButton")
        clear_button.clicked.connect(self._clear_search)

        self.global_search_count = QLabel("0 results")
        self.global_search_count.setObjectName("Muted")

        row.addWidget(self.global_search_box, 1)
        row.addWidget(self.global_source_filter)
        row.addWidget(self.global_type_filter)
        row.addWidget(self.global_scope_filter)
        row.addWidget(self.exact_search)
        row.addWidget(search_button)
        row.addWidget(open_button)
        row.addWidget(clear_button)
        row.addWidget(self.global_search_count)
        return panel

    def _build_results_table(self) -> QTableWidget:
        self.global_search_table = QTableWidget(0, 8)
        self.global_search_table.setHorizontalHeaderLabels(
            ["Source", "Backup", "Type", "Scope", "Name", "Category", "Value", "File"]
        )
        configure_enterprise_table(self.global_search_table, row_height=42)
        hdr = self.global_search_table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        return self.global_search_table

    # ── actions ───────────────────────────────────────────────────────────

    def _run_search(self) -> None:
        query = self.global_search_box.text().strip()
        if not query:
            QMessageBox.information(self, "Search Empty", "Enter a term to search across the backup library.")
            return

        results = search_backup_library(
            self._get_backup_roots(),
            query,
            limit=_SEARCH_LIMIT,
            source_filter=self._selected_source_index(),
            type_filter=self.global_type_filter.currentText(),
            scope_filter=self.global_scope_filter.currentText(),
            exact=self.exact_search.isChecked(),
        )
        self._populate_results(results, query)

    def _clear_search(self) -> None:
        self.global_search_box.clear()
        self._populate_results([], "")

    def _populate_results(self, results: list[SearchResult], query: str) -> None:
        self.global_search_table.setSortingEnabled(False)
        self.global_search_table.setRowCount(0)

        for result in results:
            row = self.global_search_table.rowCount()
            self.global_search_table.insertRow(row)
            self.global_search_table.setItem(row, 0, readonly_item(str(result.source_index), result.backup_path))
            self.global_search_table.setItem(row, 1, readonly_item(result.backup_name, result.backup_path))
            self.global_search_table.setItem(row, 2, readonly_item(result.result_type))
            self.global_search_table.setItem(row, 3, readonly_item(result.scope))
            self.global_search_table.setItem(row, 4, readonly_item(result.name))
            self.global_search_table.setItem(row, 5, readonly_item(result.category))
            self.global_search_table.setItem(row, 6, readonly_item(_short_value(result.value)))
            self.global_search_table.setItem(row, 7, readonly_item(result.source_file or "Backup metadata"))

        self.global_search_table.setSortingEnabled(True)

        if len(results) >= _SEARCH_LIMIT and query:
            count_text = f"{len(results)}+ results (limit reached — narrow your query)"
        else:
            count_text = f"{len(results)} results"
        self.global_search_count.setText(count_text)

    def _open_selected_result(self) -> None:
        selected_rows = sorted({index.row() for index in self.global_search_table.selectedIndexes()})
        if not selected_rows:
            QMessageBox.information(self, "No Result Selected", "Select a search result to open.")
            return

        path_item = self.global_search_table.item(selected_rows[0], 1)
        backup_path = path_item.data(0x0100) if path_item else ""  # Qt.ItemDataRole.UserRole = 0x0100
        if not backup_path:
            QMessageBox.warning(self, "Open Failed", "The selected result does not include a backup path.")
            return

        self.view_backup_requested.emit(str(backup_path))

    def _selected_source_index(self) -> int | None:
        selected = self.global_source_filter.currentText()
        if selected == "All Sources":
            return None
        try:
            return int(selected.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            return None


def _short_value(value: str, limit: int = 180) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 3]}..."
