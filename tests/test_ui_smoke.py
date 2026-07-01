from __future__ import annotations

import sys
import tempfile
import json
from pathlib import Path
import unittest

from PySide6.QtWidgets import QApplication

from app.gpo.gpo_model import GpoBackup
from app.ui.archived_compare_window import ArchivedCompareWindow
from app.ui.compare_window import CompareWindow
from app.ui.view_window import ViewWindow

# One QApplication for the entire module — Qt requires exactly one instance.
_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv[:1])
    return _app


def _empty_backup(path: str, name: str) -> GpoBackup:
    return GpoBackup(path=path, name=name, settings=[], detected_parsers=())


class TestViewWindowSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()
        cls.tmp = tempfile.mkdtemp()
        cls.backup = _empty_backup(cls.tmp, "Smoke Test GPO")

    def _win(self) -> ViewWindow:
        return ViewWindow(self.backup)

    def test_opens_without_error(self) -> None:
        win = self._win()
        self.assertIsNotNone(win)
        win.close()

    def test_title_contains_backup_name(self) -> None:
        win = self._win()
        self.assertIn("Smoke Test GPO", win.windowTitle())
        win.close()

    def test_expected_nav_buttons_present(self) -> None:
        win = self._win()
        for page in ("Summary", "Metadata", "Computer Configuration", "User Configuration"):
            self.assertIn(page, win.nav_buttons, f"Nav button '{page}' missing")
        win.close()

    def test_summary_page_is_default(self) -> None:
        win = self._win()
        self.assertEqual(win.stack.currentIndex(), 0)
        win.close()

    def test_page_navigation_does_not_crash(self) -> None:
        win = self._win()
        for page in ("Metadata", "Computer Configuration", "User Configuration", "Raw Settings", "Summary"):
            win._set_page(page)
        self.assertEqual(win.stack.currentIndex(), 0)
        win.close()

    def test_no_report_shows_raw_settings_count(self) -> None:
        # Empty backup dir → no gpreport.xml → report is None → raw path shown
        win = self._win()
        self.assertIsNone(win.report)
        win.close()


class TestCompareWindowSmoke(unittest.TestCase):
    _SETTINGS: dict = {"app": {"theme": "executive_dark"}}

    @classmethod
    def setUpClass(cls) -> None:
        _get_app()
        cls.tmp_a = tempfile.mkdtemp()
        cls.tmp_b = tempfile.mkdtemp()
        cls.backup_a = _empty_backup(cls.tmp_a, "Backup Alpha")
        cls.backup_b = _empty_backup(cls.tmp_b, "Backup Beta")

    def _win(self) -> CompareWindow:
        return CompareWindow(self.backup_a, self.backup_b, self._SETTINGS)

    def test_opens_without_error(self) -> None:
        win = self._win()
        self.assertIsNotNone(win)
        win.close()

    def test_title_contains_both_backup_names(self) -> None:
        win = self._win()
        title = win.windowTitle()
        self.assertIn("Backup Alpha", title)
        self.assertIn("Backup Beta", title)
        win.close()

    def test_filter_widgets_are_present(self) -> None:
        win = self._win()
        self.assertIsNotNone(win.search_box)
        self.assertIsNotNone(win.status_filter)
        self.assertIsNotNone(win.scope_filter)
        self.assertIsNotNone(win.review_filter)
        self.assertIsNotNone(win.review_filter)
        win.close()

    def test_empty_backups_produce_no_diff_items(self) -> None:
        win = self._win()
        self.assertEqual(len(win.diff_items), 0)
        win.close()

    def test_result_count_reflects_zero(self) -> None:
        win = self._win()
        self.assertIn("0", win.result_count.text())
        win.close()

    def test_status_filter_options(self) -> None:
        win = self._win()
        options = [win.status_filter.itemText(i) for i in range(win.status_filter.count())]
        self.assertIn("All Changes", options)
        self.assertIn("Different", options)
        win.close()

    def test_clear_filters_resets_state(self) -> None:
        win = self._win()
        win.search_box.setText("something")
        win.status_filter.setCurrentIndex(1)
        win._clear_filters()
        self.assertEqual(win.search_box.text(), "")
        self.assertEqual(win.status_filter.currentIndex(), 0)
        win.close()


class TestArchivedCompareWindowSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def test_opens_saved_review_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "compare.json"
            record_path.write_text(json.dumps({
                "title": "Saved Compare",
                "summary": {"total_items": 1, "actionable": 1, "reviewed": 0},
                "findings": [{
                    "key": "finding-1",
                    "name": "Browser Policy",
                    "status": "Changed",
                    "scope": "Computer Configuration",
                    "state_a": "Enabled",
                    "state_b": "Enabled",
                    "changes": ["Removed configured value from Backup B: example.test"],
                    "supporting_evidence": ["Registry artifact evidence"],
                    "review": {"status": "Pending Review", "priority": "Normal"},
                }],
            }), encoding="utf-8")

            win = ArchivedCompareWindow(str(record_path))
            self.assertEqual(win.list_widget.count(), 1)
            self.assertIn("Browser Policy", win.detail_title.text())
            win.close()

    def test_saved_review_detail_includes_directional_action_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "compare.json"
            policy_a = {
                "name": "Browser Policy",
                "state": "Enabled",
                "scope": "Computer Configuration",
                "category": "Group Policy Preferences > Registry",
                "policy_type": "Preference",
                "source": "gpreport.xml::Registry",
                "settings": ["Action: Replace", "Value: Old"],
            }
            policy_b = {
                **policy_a,
                "settings": ["Action: Update", "Value: Desired"],
            }
            record_path.write_text(json.dumps({
                "title": "Saved Compare",
                "summary": {"total_items": 1, "actionable": 1, "reviewed": 1},
                "findings": [{
                    "key": "finding-1",
                    "name": "Browser Policy",
                    "status": "Changed",
                    "scope": "Computer Configuration",
                    "state_a": "Enabled",
                    "state_b": "Enabled",
                    "policy_a": policy_a,
                    "policy_b": policy_b,
                    "changes": ["Value changed"],
                    "review": {"status": "Make Changes to A", "priority": "Normal"},
                }],
            }), encoding="utf-8")

            win = ArchivedCompareWindow(str(record_path))
            rendered = win.detail_text.toHtml()
            self.assertIn("Review Action Plan", rendered)
            self.assertIn("Update Browser Policy in Backup A", rendered)
            self.assertIn("Settings to apply to Backup A", rendered)
            self.assertIn("Desired", rendered)
            win.close()


if __name__ == "__main__":
    unittest.main()
