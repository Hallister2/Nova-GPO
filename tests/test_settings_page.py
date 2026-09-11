from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.gpo.archive import ArchivedBackup
from app.ui.pages.settings_page import SettingsPage

_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv[:1])
    return _app


def _archived(name: str, source_index: int = 1) -> ArchivedBackup:
    return ArchivedBackup(
        source_index=source_index,
        source_path=f"/source-{source_index}",
        archived_path=f"/source-{source_index}/.Archived/{name}",
        original_path=f"/source-{source_index}/{name}",
        display_name=name,
        archived_at="2026-01-01T00:00:00",
        status="Restorable",
    )


def _pump_until(condition, timeout_s: float = 3.0) -> None:
    app = _get_app()
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition was not met within the timeout")
        app.processEvents()


class TestSettingsPageRecycleBinThreading(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def setUp(self) -> None:
        self.page = SettingsPage({"storage": {}})

    def tearDown(self) -> None:
        if self.page._recycle_scan_thread is not None:
            self.page._recycle_scan_thread.wait(2000)
        self.page.close()

    def test_refresh_does_not_block_the_caller(self) -> None:
        # Regression test: list_archived_backups() does real filesystem I/O
        # (walking every archived folder and parsing metadata) and must not
        # run on the calling (UI) thread — refresh_recycle_bin() should return
        # almost immediately even if the scan itself is slow.
        def slow_scan(roots):
            time.sleep(0.3)
            return [_archived("Slow GPO")]

        with patch("app.ui.pages.settings_page.list_archived_backups", side_effect=slow_scan):
            start = time.monotonic()
            self.page.refresh_recycle_bin(["/source-1"])
            elapsed = time.monotonic() - start

            self.assertLess(elapsed, 0.15, "refresh_recycle_bin() blocked waiting for the scan")
            # The mock must stay active until the background thread actually
            # calls it — thread.start() returns immediately, so the real scan
            # runs asynchronously after this point, not before it.
            _pump_until(lambda: self.page.recycle_table.rowCount() == 1)

    def test_table_populates_after_scan_completes(self) -> None:
        with patch(
            "app.ui.pages.settings_page.list_archived_backups",
            return_value=[_archived("Alpha GPO"), _archived("Beta GPO", source_index=2)],
        ):
            self.page.refresh_recycle_bin(["/source-1", "/source-2"])
            _pump_until(lambda: self.page.recycle_table.rowCount() == 2)

        self.assertEqual(self.page.recycle_count_label.text(), "2 archived")

    def test_overlapping_refresh_calls_scan_again_with_latest_roots(self) -> None:
        calls: list[list[str]] = []

        def recording_scan(roots):
            calls.append(list(roots))
            time.sleep(0.2)
            return [_archived(f"GPO for {roots}")]

        with patch("app.ui.pages.settings_page.list_archived_backups", side_effect=recording_scan):
            self.page.refresh_recycle_bin(["/first"])
            # This arrives while the first scan is still running in the background.
            self.page.refresh_recycle_bin(["/second"])
            self.assertEqual(self.page._recycle_scan_pending_roots, ["/second"])

            _pump_until(lambda: self.page._recycle_scan_pending_roots is None and calls == [["/first"], ["/second"]])
            _pump_until(lambda: self.page.recycle_table.rowCount() == 1)

        self.assertEqual(calls, [["/first"], ["/second"]])

    def test_scan_failure_does_not_crash_and_shows_empty_list(self) -> None:
        with patch(
            "app.ui.pages.settings_page.list_archived_backups",
            side_effect=OSError("permission denied"),
        ):
            self.page.refresh_recycle_bin(["/source-1"])
            _pump_until(lambda: self.page.recycle_count_label.text() == "0 archived")

        self.assertEqual(self.page.recycle_table.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
