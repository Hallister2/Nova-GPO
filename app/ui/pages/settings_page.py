from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.log import get_logger
from app.core.settings import save_settings
from app.gpo.archive import (
    list_archived_backups,
    permanently_delete_archived_backup,
    purge_expired_archives,
    restore_archived_backup,
)
from app.gpo.backup_catalog import scan_backup_library
from app.ui.widgets import badge, badge_item, configure_enterprise_table, readonly_item

_log = get_logger(__name__)


class _DroppableTable(QTableWidget):
    """QTableWidget that accepts folder drops from the file manager."""

    paths_dropped = Signal(list)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        dirs = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and Path(url.toLocalFile()).is_dir()
        ]
        if dirs:
            self.paths_dropped.emit(dirs)
            event.acceptProposedAction()
        else:
            event.ignore()


class SettingsPage(QWidget):
    library_refresh_needed = Signal()
    backup_roots_changed = Signal(list)

    def __init__(self, settings: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("Title")
        layout.addWidget(title)

        subtitle = QLabel("Manage backup source directories used by the dashboard and comparison tools.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(self._build_directories_tab(), "Backup Directories")
        tabs.addTab(self._build_recycle_bin_tab(), "Recycle Bin")
        layout.addWidget(tabs, 1)

    # ── public API ────────────────────────────────────────────────────────

    def sync_source_tables(self, roots: list[str]) -> None:
        self._populate_source_table(self.settings_sources_table, roots)

    def refresh_recycle_bin(self, roots: list[str]) -> None:
        items = list_archived_backups(roots)
        self.recycle_table.setSortingEnabled(False)
        self.recycle_table.setRowCount(0)

        for item in items:
            row = self.recycle_table.rowCount()
            self.recycle_table.insertRow(row)
            self.recycle_table.setItem(row, 0, readonly_item(str(item.source_index), item.archived_path))
            self.recycle_table.setItem(row, 1, readonly_item(item.display_name, item.archived_path))
            self.recycle_table.setItem(row, 2, readonly_item(_display_time(item.archived_at), item.archived_path))
            self.recycle_table.setItem(row, 3, readonly_item(item.original_path, item.archived_path))
            self.recycle_table.setItem(row, 4, badge_item(item.status, item.archived_path))
            self.recycle_table.setItem(row, 5, readonly_item(item.archived_path, item.archived_path))
            self.recycle_table.setCellWidget(
                row, 4,
                badge(item.status, "valid" if item.status == "Restorable" else "review", min_width=102),
            )

        self.recycle_table.setSortingEnabled(True)
        self.recycle_count_label.setText(f"{len(items)} archived")

    # ── builders ──────────────────────────────────────────────────────────

    def _build_directories_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)

        heading = QLabel("Backup Directories")
        heading.setObjectName("PanelTitle")
        panel_layout.addWidget(heading)

        self.settings_sources_table = _DroppableTable(0, 3)
        self.settings_sources_table.setHorizontalHeaderLabels(["Source", "Directory", "Status"])
        configure_enterprise_table(self.settings_sources_table, row_height=38)
        self.settings_sources_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        self.settings_sources_table.paths_dropped.connect(self._add_dropped_directories)
        hdr = self.settings_sources_table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(2, 110)
        panel_layout.addWidget(self.settings_sources_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        add_button = QPushButton("Add Directory")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add_directory)

        remove_button = QPushButton("Remove Selected")
        remove_button.setObjectName("GhostButton")
        remove_button.clicked.connect(self._remove_selected_directory)

        scan_button = QPushButton("Scan Library")
        scan_button.setObjectName("GhostButton")
        scan_button.clicked.connect(self.library_refresh_needed.emit)

        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch()
        actions.addWidget(scan_button)
        panel_layout.addLayout(actions)

        layout.addWidget(panel, 1)
        return tab

    def _build_recycle_bin_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        retention_panel = QFrame()
        retention_panel.setObjectName("RaisedPanel")
        ret_layout = QHBoxLayout(retention_panel)
        ret_layout.setContentsMargins(16, 14, 16, 14)
        ret_layout.setSpacing(10)

        retention_label = QLabel("Archive expiration")
        retention_label.setObjectName("PanelTitle")

        self.archive_retention_spin = QSpinBox()
        self.archive_retention_spin.setRange(0, 3650)
        self.archive_retention_spin.setSuffix(" days")
        self.archive_retention_spin.setValue(self._retention_days())
        self.archive_retention_spin.valueChanged.connect(self._save_retention_days)

        purge_button = QPushButton("Purge Expired")
        purge_button.setObjectName("GhostButton")
        purge_button.clicked.connect(lambda: self._purge_expired(show_message=True))

        ret_layout.addWidget(retention_label)
        ret_layout.addWidget(self.archive_retention_spin)
        ret_layout.addStretch()
        ret_layout.addWidget(purge_button)
        layout.addWidget(retention_panel)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)

        header = QHBoxLayout()
        heading = QLabel("Archived Backups")
        heading.setObjectName("PanelTitle")
        self.recycle_count_label = QLabel("0 archived")
        self.recycle_count_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addStretch()
        header.addWidget(self.recycle_count_label)
        panel_layout.addLayout(header)

        self.recycle_table = QTableWidget(0, 6)
        self.recycle_table.setHorizontalHeaderLabels(
            ["Source", "Backup", "Archived", "Original Path", "Status", "Archive Path"]
        )
        configure_enterprise_table(self.recycle_table, row_height=38)
        self.recycle_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        hdr = self.recycle_table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        panel_layout.addWidget(self.recycle_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)

        restore_button = QPushButton("Restore Selected")
        restore_button.setObjectName("PrimaryButton")
        restore_button.clicked.connect(self._restore_selected)

        delete_button = QPushButton("Delete Permanently")
        delete_button.setObjectName("GhostButton")
        delete_button.clicked.connect(self._delete_selected_permanently)

        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("GhostButton")
        refresh_button.clicked.connect(lambda: self.library_refresh_needed.emit())

        actions.addWidget(restore_button)
        actions.addWidget(delete_button)
        actions.addStretch()
        actions.addWidget(refresh_button)
        panel_layout.addLayout(actions)

        layout.addWidget(panel, 1)
        return tab

    # ── directory management ──────────────────────────────────────────────

    def _add_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add GPO Backup Directory")
        if not path:
            return

        roots = self._get_roots()
        if path in roots:
            QMessageBox.information(self, "Already Added", "That backup directory is already in the source list.")
            return

        roots.append(path)
        self._save_roots(roots)
        self.library_refresh_needed.emit()

    def _remove_selected_directory(self) -> None:
        selected_paths = self._selected_source_paths()
        if not selected_paths:
            QMessageBox.information(self, "No Source Selected", "Select a backup directory to remove.")
            return

        roots = self._get_roots()
        remaining = [r for r in roots if r not in selected_paths]
        self._save_roots(remaining)
        self.library_refresh_needed.emit()

    def _add_dropped_directories(self, paths: list[str]) -> None:
        roots = self._get_roots()
        added = [p for p in paths if p not in roots]
        if not added:
            return
        roots.extend(added)
        self._save_roots(roots)
        self.library_refresh_needed.emit()

    def _populate_source_table(self, table: QTableWidget, roots: list[str]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)

        for index, root in enumerate(roots, start=1):
            row = table.rowCount()
            table.insertRow(row)
            status_text, status_state = _source_status(root)
            table.setItem(row, 0, readonly_item(str(index), root))
            table.setItem(row, 1, readonly_item(root, root))
            table.setItem(row, 2, badge_item(status_text, root))
            table.setCellWidget(row, 2, badge(status_text, status_state, min_width=102))

        table.setSortingEnabled(True)

    def _selected_source_paths(self) -> set[str]:
        paths: set[str] = set()
        for index in self.settings_sources_table.selectedIndexes():
            item = self.settings_sources_table.item(index.row(), 1)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole) or item.text()
            if path:
                paths.add(str(path))
        return paths

    # ── archive / recycle management ──────────────────────────────────────

    def _restore_selected(self) -> None:
        selected_paths = self._selected_archive_paths()
        if not selected_paths:
            QMessageBox.information(self, "No Archive Selected", "Select one or more archived backups to restore.")
            return

        failures: list[str] = []
        for archived_path in selected_paths:
            try:
                restore_archived_backup(archived_path)
            except Exception as error:
                failures.append(f"{archived_path}: {error}")

        self.library_refresh_needed.emit()

        if failures:
            QMessageBox.warning(self, "Restore Incomplete", "\n".join(failures))
            return

        QMessageBox.information(self, "Restored", "Selected archived backups were restored.")

    def _delete_selected_permanently(self) -> None:
        selected_paths = self._selected_archive_paths()
        if not selected_paths:
            QMessageBox.information(self, "No Archive Selected", "Select one or more archived backups to delete.")
            return

        answer = QMessageBox.question(
            self,
            "Delete Archived Backups",
            "Permanently delete the selected archived backups? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        failures: list[str] = []
        for archived_path in selected_paths:
            try:
                permanently_delete_archived_backup(archived_path)
            except Exception as error:
                _log.error("Failed to delete archive %s: %s", archived_path, error, exc_info=True)
                failures.append(f"{archived_path}: {error}")

        self.library_refresh_needed.emit()

        if failures:
            QMessageBox.warning(self, "Delete Incomplete", "\n".join(failures))
            return

        QMessageBox.information(self, "Deleted", "Selected archived backups were permanently deleted.")

    def _purge_expired(self, show_message: bool) -> None:
        try:
            removed = purge_expired_archives(self._get_roots(), self._retention_days())
        except Exception as error:
            _log.error("Purge failed: %s", error, exc_info=True)
            if show_message:
                QMessageBox.warning(self, "Purge Failed", str(error))
            return

        self.library_refresh_needed.emit()
        if show_message:
            QMessageBox.information(self, "Purge Complete", f"Removed {removed} expired archived backups.")

    def _selected_archive_paths(self) -> list[str]:
        paths: list[str] = []
        selected_rows = sorted({index.row() for index in self.recycle_table.selectedIndexes()})
        for row in selected_rows:
            item = self.recycle_table.item(row, 1)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole) or item.text()
            if path:
                paths.append(str(path))
        return paths

    # ── settings helpers ──────────────────────────────────────────────────

    def _get_roots(self) -> list[str]:
        storage = self.settings.setdefault("storage", {})
        roots = storage.get("backup_roots", [])
        if not isinstance(roots, list):
            roots = []
        legacy_root = str(storage.get("backup_root", "")).strip()
        clean_roots = [str(p).strip() for p in roots if str(p).strip()]
        if legacy_root and legacy_root not in clean_roots:
            clean_roots.insert(0, legacy_root)
        storage["backup_roots"] = clean_roots
        storage["backup_root"] = clean_roots[0] if clean_roots else ""
        return clean_roots

    def _save_roots(self, roots: list[str]) -> None:
        clean = []
        for root in roots:
            r = root.strip()
            if r and r not in clean:
                clean.append(r)
        storage = self.settings.setdefault("storage", {})
        storage["backup_roots"] = clean
        storage["backup_root"] = clean[0] if clean else ""
        save_settings(self.settings)
        self.sync_source_tables(clean)
        self.backup_roots_changed.emit(clean)

    def _retention_days(self) -> int:
        storage = self.settings.setdefault("storage", {})
        try:
            return max(0, int(storage.get("archive_retention_days", 60)))
        except (TypeError, ValueError):
            return 60

    def _save_retention_days(self, value: int) -> None:
        storage = self.settings.setdefault("storage", {})
        storage["archive_retention_days"] = max(0, int(value))
        save_settings(self.settings)

    def purge_on_startup(self) -> None:
        # Runs silently at startup without emitting library_refresh_needed.
        try:
            purge_expired_archives(self._get_roots(), self._retention_days())
        except Exception as error:
            _log.warning("Startup purge failed: %s", error)


# ── module-level helpers ──────────────────────────────────────────────────────

def _source_status(root: str) -> tuple[str, str]:
    from pathlib import Path
    path = Path(root)

    if not path.exists() or not path.is_dir():
        return ("Missing", "removed")

    try:
        items = scan_backup_library(str(path))
    except OSError:
        return ("Needs review", "review")

    if not items:
        return ("No backups", "unknown")

    if any(not item.is_valid for item in items):
        return ("Needs review", "review")

    return ("Found", "valid")


def _display_time(value: str) -> str:
    if value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.strftime("%m/%d/%Y %I:%M %p").replace(" 0", " ")
        except ValueError:
            return value
    return "Not reported"
