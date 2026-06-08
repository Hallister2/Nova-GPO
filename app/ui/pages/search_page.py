from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
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
_RESULT_ROLE = 0x0101


class _SearchWorker(QObject):
    finished = Signal(list, str, bool, str)
    progress = Signal(str)

    def __init__(self, roots: list[str], query: str, filters: dict[str, Any]) -> None:
        super().__init__()
        self.roots = roots
        self.query = query
        self.filters = filters
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            results = search_backup_library(
                self.roots,
                self.query,
                limit=_SEARCH_LIMIT,
                source_filter=self.filters["source_filter"],
                type_filter=self.filters["type_filter"],
                scope_filter=self.filters["scope_filter"],
                category_filter=self.filters["category_filter"],
                field_filter=self.filters["field_filter"],
                security_only=self.filters["security_only"],
                exact=self.filters["exact"],
                progress_callback=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except Exception as error:
            _log.error("Search failed: %s", error, exc_info=True)
            self.finished.emit([], self.query, False, str(error))
            return
        self.finished.emit(results, self.query, self._cancel_requested, "")


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
        self._search_thread: QThread | None = None
        self._search_worker: _SearchWorker | None = None

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
        layout.addWidget(self._build_results_area(), 1)
        self.empty_state = self._build_empty_state()
        layout.addWidget(self.empty_state, 1)
        self._set_empty_state("Ready to search", "Enter a term and run a search across the loaded backup sources.")

        self.global_search_box.returnPressed.connect(self._run_search)
        self.global_search_table.cellDoubleClicked.connect(
            lambda row, col: self._open_selected_result()
        )
        self.global_search_table.itemSelectionChanged.connect(self._update_result_details)

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

    def cancel_current_search(self) -> None:
        if self._is_search_running():
            self._cancel_search()
            assert self._search_thread is not None
            self._search_thread.quit()
            self._search_thread.wait(1500)

    # ── builders ──────────────────────────────────────────────────────────

    def _build_filter_bar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("FilterBar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.global_search_box = QLineEdit()
        self.global_search_box.setPlaceholderText(
            "Search all backups, policies, settings, registry paths, scripts..."
        )
        self.global_search_box.setMinimumWidth(280)

        self.global_source_filter = QComboBox()
        self.global_source_filter.setMinimumWidth(112)
        self.global_source_filter.addItem("All Sources")

        self.global_type_filter = QComboBox()
        self.global_type_filter.setMinimumWidth(116)
        self.global_type_filter.addItems(
            [
                "All Types",
                "GPO Backup",
                "Administrative Template",
                "Security Setting",
                "Firewall Rule",
                "AppLocker",
                "Preference",
                "Artifact",
            ]
        )

        self.global_scope_filter = QComboBox()
        self.global_scope_filter.setMinimumWidth(116)
        self.global_scope_filter.addItems(
            ["All Scopes", "Backup", "Computer Configuration", "User Configuration", "Artifacts"]
        )

        self.global_category_filter = QComboBox()
        self.global_category_filter.setMinimumWidth(124)
        self.global_category_filter.addItems(
            ["All Categories", "Security", "Firewall", "Audit", "Password", "Registry", "Scripts"]
        )

        self.global_field_filter = QComboBox()
        self.global_field_filter.setMinimumWidth(112)
        self.global_field_filter.addItems(["All Fields", "Values Only", "Names Only", "Paths/Categories"])

        self.security_only = QCheckBox("Security")
        self.security_only.setObjectName("Muted")

        self.exact_search = QCheckBox("Exact phrase")
        self.exact_search.setObjectName("Muted")

        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("PrimaryButton")
        self.search_button.setMinimumWidth(86)
        self.search_button.clicked.connect(self._run_search)

        self.open_button = QPushButton("Open Result")
        self.open_button.setObjectName("GhostButton")
        self.open_button.setMinimumWidth(106)
        self.open_button.clicked.connect(self._open_selected_result)

        clear_button = QPushButton("Clear")
        clear_button.setObjectName("GhostButton")
        clear_button.setMinimumWidth(72)
        clear_button.clicked.connect(self._clear_search)

        self.global_search_count = QLabel("0 results")
        self.global_search_count.setObjectName("Muted")
        self.global_search_count.setMinimumWidth(72)
        self.global_search_count.setWordWrap(False)

        search_row.addWidget(self.global_search_box, 1)
        search_row.addWidget(self.search_button)
        search_row.addWidget(self.open_button)
        search_row.addWidget(clear_button)
        search_row.addWidget(self.global_search_count)

        filter_row.addWidget(self.global_source_filter)
        filter_row.addWidget(self.global_type_filter)
        filter_row.addWidget(self.global_scope_filter)
        filter_row.addWidget(self.global_category_filter)
        filter_row.addWidget(self.global_field_filter)
        filter_row.addStretch(1)
        filter_row.addWidget(self.security_only)
        filter_row.addWidget(self.exact_search)

        layout.addLayout(search_row)
        layout.addLayout(filter_row)
        return panel

    def _build_results_area(self) -> QWidget:
        self.results_area = QSplitter(Qt.Orientation.Horizontal)
        self.results_area.addWidget(self._build_results_table())
        self.results_area.addWidget(self._build_details_panel())
        self.results_area.setStretchFactor(0, 3)
        self.results_area.setStretchFactor(1, 1)
        self.results_area.setSizes([760, 300])
        return self.results_area

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

    def _build_details_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Result Details")
        title.setObjectName("PanelTitle")
        self.result_detail_name = QLabel("Select a result to inspect it.")
        self.result_detail_name.setObjectName("PanelTitle")
        self.result_detail_name.setWordWrap(True)
        self.result_detail_meta = QLabel("")
        self.result_detail_meta.setObjectName("Muted")
        self.result_detail_meta.setWordWrap(True)
        self.result_detail_value = QPlainTextEdit()
        self.result_detail_value.setReadOnly(True)
        self.result_detail_value.setPlaceholderText("Search result value and source context")

        layout.addWidget(title)
        layout.addWidget(self.result_detail_name)
        layout.addWidget(self.result_detail_meta)
        layout.addWidget(self.result_detail_value, 1)
        return panel

    def _build_empty_state(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(32, 56, 32, 56)
        layout.setSpacing(10)

        self.empty_state_title = QLabel("")
        self.empty_state_title.setObjectName("PanelTitle")
        self.empty_state_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.empty_state_body = QLabel("")
        self.empty_state_body.setObjectName("Muted")
        self.empty_state_body.setWordWrap(True)
        self.empty_state_body.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()
        layout.addWidget(self.empty_state_title)
        layout.addWidget(self.empty_state_body)
        layout.addStretch()
        return frame

    # ── actions ───────────────────────────────────────────────────────────

    def _run_search(self) -> None:
        if self._is_search_running():
            self._cancel_search()
            return

        query = self.global_search_box.text().strip()
        if not query:
            self._set_empty_state("Ready to search", "Enter a term to search across the backup library.")
            return

        roots = self._get_backup_roots()
        if not roots:
            self._populate_results([], "")
            self._set_empty_state(
                "No backup sources configured",
                "Add a backup directory in Settings, then scan the Backup Library before searching.",
            )
            return

        filters = {
            "source_filter": self._selected_source_index(),
            "type_filter": self.global_type_filter.currentText(),
            "scope_filter": self.global_scope_filter.currentText(),
            "category_filter": self.global_category_filter.currentText(),
            "field_filter": self.global_field_filter.currentText(),
            "security_only": self.security_only.isChecked(),
            "exact": self.exact_search.isChecked(),
        }

        self._set_search_running(True, "Starting search...")
        self._search_thread = QThread(self)
        self._search_worker = _SearchWorker(roots, query, filters)
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.progress.connect(self._on_search_progress)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_worker.finished.connect(self._search_worker.deleteLater)
        self._search_thread.finished.connect(self._search_thread.deleteLater)
        self._search_thread.finished.connect(lambda: setattr(self, "_search_thread", None))
        self._search_thread.finished.connect(lambda: setattr(self, "_search_worker", None))
        self._search_thread.start()

    def _clear_search(self) -> None:
        if self._is_search_running():
            self._cancel_search()
        self.global_search_box.clear()
        self.global_source_filter.setCurrentIndex(0)
        self.global_type_filter.setCurrentIndex(0)
        self.global_scope_filter.setCurrentIndex(0)
        self.global_category_filter.setCurrentIndex(0)
        self.global_field_filter.setCurrentIndex(0)
        self.security_only.setChecked(False)
        self.exact_search.setChecked(False)
        self._populate_results([], "")
        self._set_empty_state("Ready to search", "Enter a term and run a search across the loaded backup sources.")

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
            name_item = self.global_search_table.item(row, 4)
            if name_item:
                name_item.setData(_RESULT_ROLE, result)

        self.global_search_table.setSortingEnabled(True)
        self._update_result_details()

        if len(results) >= _SEARCH_LIMIT and query:
            count_text = f"{len(results)}+ results"
            self.global_search_count.setToolTip("Limit reached. Narrow your query to see more targeted results.")
        else:
            count_text = f"{len(results)} results"
            self.global_search_count.setToolTip("")
        self.global_search_count.setText(count_text)

        if results:
            self.results_area.setVisible(True)
            self.global_search_table.setVisible(True)
            self.empty_state.setVisible(False)
        elif query:
            self._set_empty_state(
                "No matching results",
                "Try a broader term, clear one or more filters, or scan the Backup Library to refresh searchable data.",
            )
        else:
            self.results_area.setVisible(False)

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

    def _selected_result(self) -> SearchResult | None:
        selected_rows = sorted({index.row() for index in self.global_search_table.selectedIndexes()})
        if not selected_rows:
            return None
        item = self.global_search_table.item(selected_rows[0], 4)
        result = item.data(_RESULT_ROLE) if item else None
        return result if isinstance(result, SearchResult) else None

    def _update_result_details(self) -> None:
        result = self._selected_result()
        if result is None:
            self.result_detail_name.setText("Select a result to inspect it.")
            self.result_detail_meta.setText("")
            self.result_detail_value.clear()
            return

        self.result_detail_name.setText(result.name or result.backup_name)
        meta = [
            f"Backup: {result.backup_name}",
            f"Type: {result.result_type}",
            f"Scope: {result.scope}",
            f"Category: {result.category}",
            f"File: {result.source_file or 'Backup metadata'}",
        ]
        self.result_detail_meta.setText("\n".join(meta))
        self.result_detail_value.setPlainText(result.value or "No value captured for this result.")

    def _selected_source_index(self) -> int | None:
        selected = self.global_source_filter.currentText()
        if selected == "All Sources":
            return None
        try:
            return int(selected.rsplit(" ", 1)[1])
        except (IndexError, ValueError):
            return None

    def _is_search_running(self) -> bool:
        return bool(self._search_thread and self._search_thread.isRunning())

    def _cancel_search(self) -> None:
        if self._search_worker:
            self._search_worker.cancel()
        self._set_search_running(True, "Cancelling search...")

    def _on_search_progress(self, message: str) -> None:
        self.global_search_count.setText("Searching...")
        self._set_empty_state("Searching", message)

    def _on_search_finished(self, results: list[SearchResult], query: str, cancelled: bool, error: str) -> None:
        self._set_search_running(False)
        if error:
            self._populate_results([], "")
            self._set_empty_state("Search failed", error)
            return
        if cancelled:
            self._set_empty_state("Search cancelled", "Run another search when you are ready.")
            return
        self._populate_results(results, query)

    def _set_search_running(self, running: bool, message: str = "") -> None:
        self.search_button.setText("Cancel" if running else "Search")
        self.search_button.setObjectName("GhostButton" if running else "PrimaryButton")
        self.search_button.style().unpolish(self.search_button)
        self.search_button.style().polish(self.search_button)
        self.open_button.setEnabled(not running)
        self.global_search_box.setEnabled(not running)
        if message:
            self._set_empty_state("Searching", message)

    def _set_empty_state(self, title: str, body: str) -> None:
        self.empty_state_title.setText(title)
        self.empty_state_body.setText(body)
        self.empty_state.setVisible(True)
        self.results_area.setVisible(False)


def _short_value(value: str, limit: int = 180) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 3]}..."
