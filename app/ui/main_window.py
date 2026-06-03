from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QFileSystemWatcher,
    QObject,
    QSettings,
    QSize,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QCursor, QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core.log import get_logger
from app.core.settings import APP_ROOT, save_settings
from app.core.update_checker import check_for_updates
from app.ui.branding import APP_LOGO_PATH, app_icon
from app.ui.styles import THEME_LABELS, build_stylesheet
from app.gpo.archive import archive_backup, restore_archived_backup
from app.gpo.backup_catalog import BackupCatalogItem, scan_backup_library
from app.gpo.backup_loader import load_gpo_backup
from app.library_store import delete_compare_record, list_compare_records, rename_compare_record
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.home_page import HomePage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.search_page import SearchPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.archived_compare_window import ArchivedCompareWindow
from app.ui.compare_window import CompareWindow
from app.ui.view_window import ViewWindow
from app.ui.toast import ToastManager

_log = get_logger(__name__)
ASSETS_DIR = APP_ROOT / "assets"

_QSETTINGS_ORG = "Hallister Labs"
_QSETTINGS_APP = "Nova GPO"

# Page indices in the QStackedWidget
_PAGE_DASHBOARD = 0
_PAGE_LIBRARY = 1
_PAGE_SEARCH = 2
_PAGE_REPORTS = 3
_PAGE_SETTINGS = 4
_PAGE_NAMES = ["Dashboard", "Backup Library", "Search", "Reports", "Settings"]


class _ScanWorker(QObject):
    finished = Signal(list)
    progress = Signal(str)

    def __init__(self, roots: list[str]) -> None:
        super().__init__()
        self.roots = roots

    def run(self) -> None:
        items: list[BackupCatalogItem] = []
        total = len(self.roots)
        for source_index, root in enumerate(self.roots, start=1):
            self.progress.emit(f"Scanning source {source_index} of {total}…")
            try:
                items.extend(scan_backup_library(root, source_index=source_index))
            except Exception as error:
                _log.warning("Library scan failed for %s: %s", root, error, exc_info=True)
                self.progress.emit(f"Scan skipped source {source_index}: {error}")
        self.finished.emit(items)


class _UpdateCheckWorker(QObject):
    finished = Signal(bool, object, str, bool)

    def __init__(self, manual: bool, timeout: int = 5) -> None:
        super().__init__()
        self.manual = manual
        self.timeout = timeout

    def run(self) -> None:
        try:
            result = check_for_updates(timeout=self.timeout)
        except Exception as error:
            self.finished.emit(False, None, str(error), self.manual)
            return
        self.finished.emit(True, result, "", self.manual)


class MainWindow(QMainWindow):
    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__()
        self.settings = settings
        self.catalog_items: list[BackupCatalogItem] = []
        self.compare_records = []
        self.nav_buttons: dict[str, QPushButton] = {}
        self.theme_buttons: dict[str, QPushButton] = {}
        self.current_theme = settings.get("app", {}).get("theme", "executive_dark")
        self._pending_compare_path = ""

        app_name = settings["app"].get("name", "Nova GPO")
        self.setWindowTitle(app_name)
        self.setWindowIcon(app_icon())
        self.resize(1120, 720)
        self.setMinimumSize(960, 640)

        root_widget = QWidget()
        root_layout = QHBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())

        # Instantiate pages
        self.home_page = HomePage(self._backup_roots, self)
        self.dashboard_page = DashboardPage(settings, self)
        self.search_page = SearchPage(settings, self._backup_roots, self)
        self.reports_page = ReportsPage(settings, self._backup_roots, self.dashboard_page.get_selected_backup_paths, self)
        self.settings_page = SettingsPage(settings, self)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.search_page)
        self.stack.addWidget(self.reports_page)
        self.stack.addWidget(self.settings_page)

        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(root_widget)

        # Toast overlay
        self._toast = ToastManager(self)

        # File-system watcher + debounce timer
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_debounce = QTimer(self)
        self._fs_debounce.setSingleShot(True)
        self._fs_debounce.setInterval(1500)
        self._fs_debounce.timeout.connect(self._refresh_library)
        self._fs_watcher.directoryChanged.connect(self._on_directory_changed)

        self._connect_signals()
        self.settings_page.purge_on_startup()
        self._restore_state()
        self._prepare_library_startup_state()
        self._refresh_compare_records()
        self._schedule_startup_update_check()

    # ── window lifecycle ──────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._save_state()
        update_thread = getattr(self, "_update_check_thread", None)
        if update_thread and update_thread.isRunning():
            update_thread.quit()
            update_thread.wait(1500)
        for w in QApplication.instance().topLevelWidgets():
            if w is not self and w.isVisible():
                w.close()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._toast.reposition()

    # ── state persistence ─────────────────────────────────────────────────

    def _save_state(self) -> None:
        s = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        s.setValue("geometry", self.saveGeometry())

    def _restore_state(self) -> None:
        s = QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
        if geom := s.value("geometry"):
            self.restoreGeometry(geom)
        self._set_page("Dashboard")

    # ── sidebar ───────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(214)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(12)

        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("BrandLogo")
        logo.setFixedSize(148, 48)
        logo.setPixmap(
            QPixmap(str(APP_LOGO_PATH)).scaled(
                148, 48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        logo_row.addWidget(logo)
        logo_row.addStretch()
        layout.addLayout(logo_row)
        layout.addSpacing(18)

        nav_items = [
            ("Dashboard", "Nav - Calendar.png", "Nav - Calendar Active.png"),
            ("Backup Library", "Nav - Meetings.png", "Nav - Meetings Active.png"),
            ("Search", "Nav - Logs.png", "Nav - Logs Active.png"),
            ("Reports", "Nav - Capture.png", "Nav - Capture Active.png"),
            ("Settings", "Nav - Settings.png", "Nav - Settings Active.png"),
        ]

        for index, (label, default_icon, active_icon) in enumerate(nav_items):
            button = QPushButton(label)
            button.setObjectName("SidebarButton")
            button.setProperty("active", "true" if index == 0 else "false")
            icon_path = active_icon if index == 0 else default_icon
            button.setIcon(QIcon(str(ASSETS_DIR / icon_path)))
            button.setIconSize(QSize(22, 22))
            button.clicked.connect(lambda _, name=label: self._set_page(name))
            self.nav_buttons[label] = button
            layout.addWidget(button)

        layout.addStretch()
        layout.addWidget(self._build_update_controls())
        layout.addSpacing(8)
        layout.addWidget(self._build_theme_toggle())
        layout.addSpacing(8)
        footer = QLabel(f"Hallister Labs\nNova GPO {__version__}")
        footer.setObjectName("Muted")
        layout.addWidget(footer)
        return sidebar

    def _build_theme_toggle(self) -> QFrame:
        container = QFrame()
        container.setObjectName("ThemeToggle")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        for theme_name, label in [("executive_dark", "Dark"), ("clean_light", "Light")]:
            button = QPushButton(label)
            button.setObjectName("ThemeButton")
            button.setProperty("active", "false")
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.setFixedSize(58, 28)
            button.clicked.connect(lambda _, t=theme_name: self._apply_theme(t))
            layout.addWidget(button)
            self.theme_buttons[theme_name] = button

        self._sync_theme_buttons()
        return container

    def _build_update_controls(self) -> QFrame:
        container = QFrame()
        container.setObjectName("SidebarUtility")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        check_button = QPushButton("Check Updates")
        check_button.setObjectName("SidebarUtilityButton")
        check_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        check_button.clicked.connect(lambda: self._check_for_updates(manual=True))
        layout.addWidget(check_button)

        self.update_on_startup_check = QCheckBox("On startup")
        self.update_on_startup_check.setObjectName("SidebarUtilityCheck")
        self.update_on_startup_check.setChecked(self._check_updates_on_startup())
        self.update_on_startup_check.stateChanged.connect(
            lambda _state: self._save_check_updates_on_startup()
        )
        layout.addWidget(self.update_on_startup_check)
        return container

    def _sync_theme_buttons(self) -> None:
        for theme_name, button in self.theme_buttons.items():
            button.setProperty("active", "true" if theme_name == self.current_theme else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    # ── signal wiring ─────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Dashboard
        self.home_page.backup_library_requested.connect(lambda: self._set_page("Backup Library"))
        self.home_page.reports_requested.connect(lambda: self._set_page("Reports"))
        self.home_page.settings_requested.connect(lambda: self._set_page("Settings"))

        # Backup Library
        self.dashboard_page.view_backup_requested.connect(self._view_backup)
        self.dashboard_page.compare_backups_requested.connect(self._compare_backups)
        self.dashboard_page.archive_requested.connect(self._archive_backups)
        self.dashboard_page.refresh_library_requested.connect(self._refresh_library)
        self.dashboard_page.settings_page_requested.connect(lambda: self._set_page("Settings"))
        self.dashboard_page.selection_changed.connect(self._on_selection_changed)

        # Search
        self.search_page.view_backup_requested.connect(self._view_backup)

        # Reports
        self.reports_page.compare_backups_requested.connect(self._compare_backups)
        self.reports_page.open_compare_archive_requested.connect(self._open_compare_archive)
        self.reports_page.delete_compare_archive_requested.connect(self._delete_compare_archive)
        self.reports_page.rename_compare_archive_requested.connect(self._rename_compare_archive)
        self.reports_page.backup_library_requested.connect(lambda: self._set_page("Backup Library"))

        # Settings
        self.settings_page.library_refresh_needed.connect(self._refresh_library)
        self.settings_page.backup_roots_changed.connect(lambda _: self._refresh_library())

        # Keyboard shortcuts
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_library)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self._refresh_library)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._open_search)

    def _open_search(self) -> None:
        self._set_page("Search")
        self.search_page.focus_search()

    # ── file-system watcher ───────────────────────────────────────────────

    def _on_directory_changed(self, path: str) -> None:
        _log.debug("FS watcher: directory changed: %s", path)
        self.statusBar().showMessage("Changes detected in backup directories — rescanning…")
        self._fs_debounce.start()

    def _update_fs_watcher(self, roots: list[str]) -> None:
        existing = set(self._fs_watcher.directories())
        new = set(roots)
        if to_remove := existing - new:
            self._fs_watcher.removePaths(list(to_remove))
        if to_add := new - existing:
            failed = self._fs_watcher.addPaths(list(to_add))
            if failed:
                _log.debug("FS watcher: could not watch (path missing?): %s", failed)

    # ── library scan (background thread) ──────────────────────────────────

    def _refresh_library(self) -> None:
        if getattr(self, "_scan_thread", None) and self._scan_thread.isRunning():
            _log.debug("Scan already in progress — ignoring duplicate refresh request")
            return

        roots = self._backup_roots()

        if not roots:
            self.catalog_items = []
            self.dashboard_page.populate([])
            self.search_page.refresh_source_filter([])
            self.settings_page.sync_source_tables([])
            self.settings_page.refresh_recycle_bin([])
            self.reports_page.update_stats([], 0)
            self._refresh_compare_records()
            self._update_home_page(0)
            self.statusBar().showMessage("No backup sources configured — add directories in Settings.")
            _log.info("Library refresh: no backup roots configured")
            return

        _log.info("Library scan started: %d root(s)", len(roots))
        self.statusBar().showMessage(f"Scanning {len(roots)} backup source(s)…")

        self._scan_thread = QThread(self)
        self._scan_worker = _ScanWorker(roots)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self.statusBar().showMessage)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.finished.connect(lambda: setattr(self, "_scan_thread", None))
        self._scan_thread.start()

    def _prepare_library_startup_state(self) -> None:
        self.catalog_items = []
        self.dashboard_page.populate([])
        self.search_page.refresh_source_filter([])
        self.settings_page.sync_source_tables(self._backup_roots())
        self.settings_page.refresh_recycle_bin(self._backup_roots())
        self.reports_page.update_stats([], 0)
        self._update_home_page(0)

        roots = self._backup_roots()
        if not roots:
            self.statusBar().showMessage("No backup sources configured - add directories in Settings.")
            return

        if self.settings.get("storage", {}).get("scan_on_startup", False):
            QTimer.singleShot(250, self._refresh_library)
            self.statusBar().showMessage("Startup scan scheduled.")
            return

        self.statusBar().showMessage("Backup sources configured - open Backup Library and click Scan when ready.")

    def _on_scan_finished(self, items: list[BackupCatalogItem]) -> None:
        self.catalog_items = items
        selected_count = len(self.dashboard_page.get_selected_backup_paths())

        self.dashboard_page.populate(items)
        self.search_page.refresh_source_filter(items)
        self.settings_page.sync_source_tables(self._backup_roots())
        self.settings_page.refresh_recycle_bin(self._backup_roots())
        self.reports_page.update_stats(items, selected_count)
        self._refresh_compare_records()
        self._update_home_page(selected_count)
        self._update_fs_watcher(self._backup_roots())

        time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        self.statusBar().showMessage(
            f"{len(items)} backup(s) found  ·  Last scanned {time_str}"
        )
        _log.info("Library scan complete: %d backup(s) found", len(items))

    def _refresh_compare_records(self) -> None:
        self.compare_records = list_compare_records()
        self.reports_page.populate_compare_records(self.compare_records)
        self._update_home_page(len(self.dashboard_page.get_selected_backup_paths()))

    def _on_selection_changed(self, count: int) -> None:
        self.reports_page.update_stats(self.catalog_items, count)
        self._update_home_page(count)
        self._maybe_open_pending_compare()

    def _update_home_page(self, selected_count: int) -> None:
        self.home_page.update_overview(self.catalog_items, self.compare_records, selected_count)

    # update checks

    def _schedule_startup_update_check(self) -> None:
        app_settings = self.settings.setdefault("app", {})
        if not bool(app_settings.get("check_for_updates_on_startup", True)):
            return
        QTimer.singleShot(1500, lambda: self._check_for_updates(manual=False))

    def _check_updates_on_startup(self) -> bool:
        app_settings = self.settings.setdefault("app", {})
        return bool(app_settings.get("check_for_updates_on_startup", True))

    def _save_check_updates_on_startup(self) -> None:
        app_settings = self.settings.setdefault("app", {})
        app_settings["check_for_updates_on_startup"] = self.update_on_startup_check.isChecked()
        save_settings(self.settings)

    def _check_for_updates(self, manual: bool) -> None:
        if getattr(self, "_update_check_thread", None) and self._update_check_thread.isRunning():
            if manual:
                self.statusBar().showMessage("Update check already in progress.")
            return

        if manual:
            self.statusBar().showMessage("Checking GitHub releases for updates...")

        self._update_check_thread = QThread(self)
        self._update_check_worker = _UpdateCheckWorker(manual=manual)
        self._update_check_worker.moveToThread(self._update_check_thread)
        self._update_check_thread.started.connect(self._update_check_worker.run)
        self._update_check_worker.finished.connect(self._on_update_check_finished)
        self._update_check_worker.finished.connect(self._update_check_thread.quit)
        self._update_check_worker.finished.connect(self._update_check_worker.deleteLater)
        self._update_check_thread.finished.connect(self._update_check_thread.deleteLater)
        self._update_check_thread.finished.connect(lambda: setattr(self, "_update_check_thread", None))
        self._update_check_thread.finished.connect(lambda: setattr(self, "_update_check_worker", None))
        self._update_check_thread.start()

    def _on_update_check_finished(self, ok: bool, result: object, error: str, manual: bool) -> None:
        if not ok or result is None:
            _log.info("Update check failed: %s", error)
            if manual:
                self.statusBar().showMessage("Update check failed.")
                self._toast.warning(error or "Unable to check for updates.")
            return

        if not getattr(result, "release_found", True):
            if manual:
                self.statusBar().showMessage("No Nova GPO releases found on GitHub yet.")
                self._toast.info("No GitHub releases found yet.")
            return

        if not result.is_update_available:
            if manual:
                self.statusBar().showMessage("Nova GPO is up to date.")
                self._toast.success(f"Nova GPO {result.current_version} is up to date.")
            return

        release_label = f"Nova GPO {result.latest_version}"
        if getattr(result, "is_prerelease", False):
            release_label = f"{release_label} prerelease"
        self.statusBar().showMessage(f"{release_label} is available.")
        self._toast.info_action(
            f"{release_label} is available.",
            "View Release",
            lambda: QDesktopServices.openUrl(QUrl(result.release_url)),
        )

    # ── dialogs ───────────────────────────────────────────────────────────

    def _view_backup(self, backup_path: str) -> None:
        try:
            backup = load_gpo_backup(backup_path)
        except Exception as error:
            _log.error("View failed for %s: %s", backup_path, error, exc_info=True)
            QMessageBox.critical(self, "View Failed", str(error))
            return

        window = ViewWindow(backup, self)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.compare_with_requested.connect(
            lambda path: self._handle_compare_from_view(path, window)
        )
        window.show()

    def _compare_backups(self, backup_a_path: str, backup_b_path: str) -> None:
        self._pending_compare_path = ""
        self.dashboard_page.clear_compare_pending()
        try:
            backup_a = load_gpo_backup(backup_a_path)
            backup_b = load_gpo_backup(backup_b_path)
        except Exception as error:
            _log.error("Compare failed: %s", error, exc_info=True)
            QMessageBox.critical(self, "Comparison Failed", str(error))
            return

        window = CompareWindow(backup_a, backup_b, self.settings, self)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.finished.connect(lambda _: self._refresh_compare_records())
        window.show()

    def _open_compare_archive(self, record_path: str) -> None:
        if not record_path:
            return

        path = Path(record_path)
        if not path.exists():
            QMessageBox.warning(
                self,
                "Review Missing",
                f"The saved compare review could not be found:\n{record_path}",
            )
            self._refresh_compare_records()
            return

        try:
            window = ArchivedCompareWindow(str(path), self)
        except Exception as error:
            QMessageBox.critical(self, "Open Review Failed", str(error))
            return
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.finished.connect(lambda _: self._refresh_compare_records())
        window.show()

    def _delete_compare_archive(self, record_path: str) -> None:
        answer = QMessageBox.question(
            self,
            "Delete Saved Review",
            "Delete this saved compare review from the Backup Library? This removes the archived report and review record.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            delete_compare_record(record_path)
        except Exception as error:
            QMessageBox.critical(self, "Delete Failed", str(error))
            return

        self._refresh_compare_records()
        self._toast.success("Saved compare review removed.")

    def _rename_compare_archive(self, record_path: str, new_title: str) -> None:
        try:
            rename_compare_record(record_path, new_title)
        except Exception as error:
            QMessageBox.critical(self, "Rename Failed", str(error))
            return

        self._refresh_compare_records()

    def _handle_compare_from_view(self, backup_path: str, view_window) -> None:
        view_window.accept()
        self._pending_compare_path = backup_path
        self._set_page("Backup Library")
        self.dashboard_page.begin_compare_pending(backup_path)

    def _maybe_open_pending_compare(self) -> None:
        if not self._pending_compare_path:
            return

        selected = self.dashboard_page.get_selected_backup_paths()
        if len(selected) != 2 or self._pending_compare_path not in selected:
            return

        other = next((path for path in selected if path != self._pending_compare_path), "")
        if not other:
            return

        pending = self._pending_compare_path
        self._pending_compare_path = ""
        self.dashboard_page.clear_compare_pending()
        self._compare_backups(pending, other)

    def _apply_theme(self, theme_name: str) -> None:
        if theme_name not in THEME_LABELS:
            theme_name = "executive_dark"
        self.current_theme = theme_name
        self.settings.setdefault("app", {})["theme"] = theme_name
        save_settings(self.settings)
        QApplication.instance().setStyleSheet(build_stylesheet(theme_name))
        self._sync_theme_buttons()

    def _archive_backups(self, paths: list[str]) -> None:
        message = (
            "Move the selected backup to the source .Archived folder?"
            if len(paths) == 1
            else f"Move {len(paths)} selected backups to their source .Archived folders?"
        )
        answer = QMessageBox.question(
            self, "Archive Selected Backups", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        archived_paths: list[str] = []
        failures: list[str] = []
        for backup_path in paths:
            try:
                result = archive_backup(backup_path)
                archived_paths.append(result.archived_path)
            except Exception as error:
                _log.error("Archive failed for %s: %s", backup_path, error, exc_info=True)
                failures.append(f"{backup_path}: {error}")

        self._refresh_library()

        if failures:
            QMessageBox.warning(self, "Archive Incomplete", "\n".join(failures))
            return

        count = len(archived_paths)

        def _undo() -> None:
            restore_failures: list[str] = []
            for ap in archived_paths:
                try:
                    restore_archived_backup(ap)
                except Exception as err:
                    _log.error("Restore failed for %s: %s", ap, err, exc_info=True)
                    restore_failures.append(str(err))
            self._refresh_library()
            if restore_failures:
                self._toast.warning(f"Restore incomplete — {len(restore_failures)} error(s).")
            else:
                self._toast.success(f"Restored {count} backup{'s' if count > 1 else ''}.")

        self._toast.success_undo(
            f"Archived {count} backup{'s' if count > 1 else ''} to .Archived.",
            _undo,
        )

    # ── navigation ────────────────────────────────────────────────────────

    def _set_page(self, page_name: str) -> None:
        page_map = {
            "Dashboard": _PAGE_DASHBOARD,
            "Backup Library": _PAGE_LIBRARY,
            "Search": _PAGE_SEARCH,
            "Reports": _PAGE_REPORTS,
            "Settings": _PAGE_SETTINGS,
        }
        index = page_map.get(page_name, _PAGE_DASHBOARD)
        active_name = page_name if page_name in self.nav_buttons else "Dashboard"
        self.stack.setCurrentIndex(index)

        for name, button in self.nav_buttons.items():
            button.setProperty("active", "true" if name == active_name else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    # ── shared helpers ────────────────────────────────────────────────────

    def _backup_roots(self) -> list[str]:
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
