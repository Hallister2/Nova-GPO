from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu

from app.gpo.search import SearchResult
from app.ui.pages.search_page import SearchPage

_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv[:1])
    return _app


class TestSearchPageContextMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def setUp(self) -> None:
        self.page = SearchPage({}, lambda: [])
        result = SearchResult(
            source_index=1,
            source_path="/root",
            backup_name="Test GPO",
            backup_path="/root/TestGPO",
            result_type="Administrative Template",
            scope="Computer Configuration",
            name="Test Policy",
            category="Windows Components",
            value="Enabled",
            source_file="gpreport.xml",
        )
        self.page._populate_results([result], "test")

    def tearDown(self) -> None:
        self.page.close()

    def test_context_menu_builds_without_error(self) -> None:
        self.page.global_search_table.selectRow(0)
        with patch.object(QMenu, "exec", return_value=None):
            self.page._on_results_context_menu(
                self.page.global_search_table.visualItemRect(
                    self.page.global_search_table.item(0, 1)
                ).center()
            )

    def test_context_menu_no_row_is_a_no_op(self) -> None:
        with patch.object(QMenu, "exec", return_value=None) as mock_exec:
            from PySide6.QtCore import QPoint
            self.page._on_results_context_menu(QPoint(0, 10_000))
            mock_exec.assert_not_called()

    def test_copy_to_clipboard_wired(self) -> None:
        with patch.object(QApplication, "clipboard") as mock_clipboard:
            self.page._copy_to_clipboard("some value")
            mock_clipboard.return_value.setText.assert_called_once_with("some value")

    def test_matched_field_is_bolded(self) -> None:
        # "name" is in the result's matched_fields (set in setUp isn't; build
        # one explicitly here so the bolding logic itself is under test).
        result = SearchResult(
            source_index=1, source_path="/root", backup_name="Test GPO",
            backup_path="/root/TestGPO", result_type="Administrative Template",
            scope="Computer Configuration", name="Password Policy", category="Security",
            value="Enabled", source_file="gpreport.xml", matched_fields=("name",),
        )
        self.page._populate_results([result], "password")
        name_item = self.page.global_search_table.item(0, 2)
        category_item = self.page.global_search_table.item(0, 3)
        self.assertTrue(name_item.font().bold())
        self.assertFalse(category_item.font().bold())

    def test_unmatched_row_has_no_bold_fields(self) -> None:
        self.page._populate_results(
            [SearchResult(
                source_index=1, source_path="/root", backup_name="Test GPO",
                backup_path="/root/TestGPO", result_type="Administrative Template",
                scope="Computer Configuration", name="Some Policy", category="Other",
                value="Enabled", source_file="gpreport.xml", matched_fields=(),
            )],
            "test",
        )
        for col in (2, 3, 4):
            self.assertFalse(self.page.global_search_table.item(0, col).font().bold())


class TestSearchPageCatalogReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def test_refresh_source_filter_caches_catalog_items(self) -> None:
        from app.gpo.backup_catalog import BackupCatalogItem

        page = SearchPage({}, lambda: ["/some/root"])
        items = [
            BackupCatalogItem(
                source_index=1, source_path="/some/root", display_name="GPO",
                folder_name="GPO", path="/some/root/GPO", is_valid=True,
                status="Valid", detail="",
            )
        ]
        page.refresh_source_filter(items)
        self.assertEqual(page._catalog_items, items)
        page.close()

    def test_search_without_a_scan_yet_shows_guidance_not_a_crash(self) -> None:
        # Roots are configured, but refresh_source_filter() was never called
        # (i.e. the Backup Library has never been scanned this session).
        page = SearchPage({}, lambda: ["/some/root"])
        page.global_search_box.setText("anything")
        page._run_search()
        # The page is never shown in this test, so isVisible() is always False
        # regardless of what the widget requested — isHidden() reflects the
        # explicit setVisible() call made by _set_empty_state().
        self.assertFalse(page.empty_state.isHidden())
        self.assertIn("scan", page.empty_state_title.text().lower())
        page.close()

    def test_search_worker_receives_cached_catalog_items(self) -> None:
        from app.gpo.backup_catalog import BackupCatalogItem

        page = SearchPage({}, lambda: ["/some/root"])
        items = [
            BackupCatalogItem(
                source_index=1, source_path="/some/root", display_name="GPO",
                folder_name="GPO", path="/some/root/GPO", is_valid=True,
                status="Valid", detail="",
            )
        ]
        page.refresh_source_filter(items)
        page.global_search_box.setText("gpo")
        page._run_search()
        try:
            self.assertIsNotNone(page._search_worker)
            self.assertEqual(page._search_worker.catalog_items, items)
        finally:
            page.cancel_current_search()
            page.close()


class TestSearchPageResultLimitHint(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def _result(self, n: int) -> SearchResult:
        return SearchResult(
            source_index=1, source_path="/root", backup_name=f"GPO {n}",
            backup_path=f"/root/GPO{n}", result_type="Administrative Template",
            scope="Computer Configuration", name=f"Policy {n}", category="Windows Components",
            value="Enabled", source_file="gpreport.xml",
        )

    def test_hint_hidden_when_under_limit(self) -> None:
        page = SearchPage({}, lambda: [])
        page._populate_results([self._result(1), self._result(2)], "policy")
        self.assertTrue(page.search_hint_label.isHidden())
        page.close()

    def test_hint_shown_when_limit_reached(self) -> None:
        from app.ui.pages.search_page import _SEARCH_LIMIT

        page = SearchPage({}, lambda: [])
        page._populate_results([self._result(i) for i in range(_SEARCH_LIMIT)], "policy")
        # Page is never shown in this test — isHidden() reflects the explicit
        # setVisible(True) call, unlike isVisible() which needs a shown ancestor.
        self.assertFalse(page.search_hint_label.isHidden())
        self.assertIn("1,000", page.search_hint_label.text())
        page.close()


if __name__ == "__main__":
    unittest.main()
