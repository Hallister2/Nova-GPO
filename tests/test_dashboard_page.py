from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMenu

from app.gpo.backup_catalog import BackupCatalogItem
from app.ui.pages.dashboard_page import DashboardPage

_app: QApplication | None = None


def _get_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv[:1])
    return _app


def _item(
    display_name: str,
    path: str,
    source_index: int = 1,
    is_valid: bool = True,
    backup_time: str = "2026-01-01T00:00:00",
) -> BackupCatalogItem:
    return BackupCatalogItem(
        source_index=source_index,
        source_path=f"source-{source_index}",
        display_name=display_name,
        folder_name=path,
        path=path,
        is_valid=is_valid,
        status="Valid" if is_valid else "Needs review",
        detail="",
        backup_time=backup_time,
    )


class TestDashboardPageGrouping(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _get_app()

    def setUp(self) -> None:
        self.items = [
            _item("Alpha GPO", "p1", source_index=1, is_valid=True, backup_time="2026-01-01T00:00:00"),
            _item("Alpha GPO", "p2", source_index=2, is_valid=False, backup_time="2026-02-01T00:00:00"),
            _item("Beta GPO", "p3", source_index=1, is_valid=True, backup_time="2026-01-15T00:00:00"),
        ]
        self.page = DashboardPage({"storage": {}})
        self.page.populate(self.items)

    def tearDown(self) -> None:
        self.page.close()

    def _row_for_path(self, path: str) -> int:
        for row in range(self.page.backup_table.rowCount()):
            item = self.page.backup_table.item(row, 1)
            if item and item.data(0x0100) == path:  # Qt.ItemDataRole.UserRole
                return row
        raise AssertionError(f"No row found for path {path!r}")

    def test_grouped_by_default(self) -> None:
        self.assertTrue(self.page.group_by_source)
        header_rows = [row for row, is_header in self.page._row_is_header.items() if is_header]
        self.assertEqual(len(header_rows), 2)  # Source 1, Source 2

    def test_group_header_shows_count_and_warning(self) -> None:
        header_texts = [
            self.page.backup_table.item(row, 0).text()
            for row, is_header in self.page._row_is_header.items()
            if is_header
        ]
        source_1_header = next(t for t in header_texts if "Source 1" in t)
        source_2_header = next(t for t in header_texts if "Source 2" in t)
        self.assertIn("2 backups", source_1_header)
        self.assertNotIn("needs review", source_1_header)
        self.assertIn("1 backup", source_2_header)
        self.assertIn("1 needs review", source_2_header)

    def test_group_header_includes_source_folder_name(self) -> None:
        # Header format: "Source N  ·  FolderName  ·  N backups [·  W needs review]"
        header_texts = [
            self.page.backup_table.item(row, 0).text()
            for row, is_header in self.page._row_is_header.items()
            if is_header
        ]
        source_1_header = next(t for t in header_texts if "Source 1" in t)
        self.assertIn("source-1", source_1_header)
        self.assertLess(
            source_1_header.index("Source 1"),
            source_1_header.index("source-1"),
        )
        self.assertLess(
            source_1_header.index("source-1"),
            source_1_header.index("2 backups"),
        )

    def test_source_folder_label_strips_trailing_separator(self) -> None:
        from app.ui.pages.dashboard_page import _source_folder_label

        self.assertEqual(_source_folder_label("D:\\Backups\\GPO\\Environment3"), "Environment3")
        self.assertEqual(_source_folder_label("D:\\Backups\\GPO\\Environment3\\"), "Environment3")
        self.assertEqual(_source_folder_label(""), "")

    def test_group_orders_by_display_name_within_source(self) -> None:
        # p1 (Alpha GPO) and p3 (Beta GPO) are both in the Source 1 group.
        row_p1 = self._row_for_path("p1")
        row_p3 = self._row_for_path("p3")
        self.assertLess(row_p1, row_p3)

    def test_header_rows_excluded_from_selection(self) -> None:
        for row, is_header in self.page._row_is_header.items():
            if is_header:
                self.assertIsNone(self.page.backup_table.item(row, 1))

    def test_toggle_group_by_source_flattens_table(self) -> None:
        self.page._toggle_group_by_source()
        self.assertFalse(self.page.group_by_source)
        self.assertEqual(self.page.backup_table.rowCount(), len(self.items))
        self.assertEqual(len(self.page._row_is_header), 0)

    def test_collapse_toggle_updates_header_marker(self) -> None:
        header_row = next(row for row, is_header in self.page._row_is_header.items() if is_header)
        before = self.page.backup_table.item(header_row, 0).text()
        self.page._on_cell_clicked(header_row, 0)
        # Row indices are stable across a rebuild (rows are hidden, not removed).
        after = self.page.backup_table.item(header_row, 0).text()
        self.assertNotEqual(before[0], after[0])
        self.assertEqual(before[2:], after[2:])

    def test_collapse_all_hides_child_rows(self) -> None:
        self.page._collapse_all_groups()
        row_p1 = self._row_for_path("p1")
        self.assertTrue(self.page.backup_table.isRowHidden(row_p1))

    def test_expand_all_restores_child_rows(self) -> None:
        self.page._collapse_all_groups()
        self.page._expand_all_groups()
        row_p1 = self._row_for_path("p1")
        self.assertFalse(self.page.backup_table.isRowHidden(row_p1))

    def test_collapse_all_keeps_table_visible(self) -> None:
        # Regression test: collapsing every group leaves zero visible *backup*
        # rows (only headers), which must not be confused with "no backups
        # match the filters" — the table itself should stay showing.
        self.page._collapse_all_groups()
        self.assertFalse(self.page.backup_table.isHidden())
        self.assertTrue(self.page.empty_helper.isHidden())

    def test_filters_matching_nothing_shows_empty_helper(self) -> None:
        self.page.backup_filter_box.setText("no-such-backup-xyz")
        self.assertTrue(self.page.backup_table.isHidden())
        self.assertFalse(self.page.empty_helper.isHidden())

    def test_status_filter_hides_group_with_no_matches(self) -> None:
        # Source 1 (p1, p3) is all valid; only Source 2 (p2) has a "Needs review" item.
        self.page.status_filter.setCurrentText("Needs review")
        header_rows = [row for row, is_header in self.page._row_is_header.items() if is_header]
        source_1_header_row = next(
            row for row in header_rows if "Source 1" in self.page.backup_table.item(row, 0).text()
        )
        self.assertTrue(self.page.backup_table.isRowHidden(source_1_header_row))

    def test_filters_button_label_reflects_active_count(self) -> None:
        self.page.status_filter.setCurrentText("Needs review")
        self.assertEqual(self.page.filters_button.text(), "Filters (1)")
        self.page._clear_popover_filters()
        self.assertEqual(self.page.filters_button.text(), "Filters")

    def test_compare_tray_shows_chips_for_two_selections(self) -> None:
        row_p1 = self._row_for_path("p1")
        row_p3 = self._row_for_path("p3")
        self.page.backup_table.selectRow(row_p1)
        from PySide6.QtWidgets import QTableWidgetSelectionRange
        self.page.backup_table.setRangeSelected(
            QTableWidgetSelectionRange(row_p3, 0, row_p3, self.page.backup_table.columnCount() - 1), True
        )
        # The page itself is never shown in this test, so isVisible() would
        # always be False regardless of what the widget requested — isHidden()
        # reflects the explicit setVisible() call made in _rebuild_compare_tray.
        self.assertFalse(self.page.compare_tray.isHidden())
        self.assertEqual(len(self.page.get_selected_backup_paths()), 2)

    def test_deselect_backup_removes_from_selection(self) -> None:
        row_p1 = self._row_for_path("p1")
        row_p3 = self._row_for_path("p3")
        self.page.backup_table.selectRow(row_p1)
        from PySide6.QtWidgets import QTableWidgetSelectionRange
        self.page.backup_table.setRangeSelected(
            QTableWidgetSelectionRange(row_p3, 0, row_p3, self.page.backup_table.columnCount() - 1), True
        )
        self.page._deselect_backup("p1")
        self.assertEqual(self.page.get_selected_backup_paths(), ["p3"])

    def test_search_reveals_matches_inside_a_collapsed_group(self) -> None:
        # Regression test: a match inside a group the user collapsed earlier
        # must still show up while a search/filter is active — collapse state
        # should not be able to hide search results.
        source_1_header_row = next(
            row for row, is_header in self.page._row_is_header.items()
            if is_header and "Source 1" in self.page.backup_table.item(row, 0).text()
        )
        self.page._on_cell_clicked(source_1_header_row, 0)  # collapse Source 1
        self.assertIn("source 1", self.page._collapsed_groups)

        self.page.backup_filter_box.setText("Alpha")
        row_p1 = self._row_for_path("p1")  # Alpha GPO lives in Source 1
        self.assertFalse(self.page.backup_table.isRowHidden(row_p1))

    def test_clearing_search_restores_collapsed_state(self) -> None:
        source_1_header_row = next(
            row for row, is_header in self.page._row_is_header.items()
            if is_header and "Source 1" in self.page.backup_table.item(row, 0).text()
        )
        self.page._on_cell_clicked(source_1_header_row, 0)  # collapse Source 1
        self.page.backup_filter_box.setText("Alpha")
        self.page.backup_filter_box.setText("")

        row_p1 = self._row_for_path("p1")
        self.assertTrue(self.page.backup_table.isRowHidden(row_p1))

    def test_collapse_does_not_touch_filesystem(self) -> None:
        # Regression test: collapse/expand used to trigger a full table
        # rebuild, which (via _apply_row_filter) always computed
        # _newest_source_mtimes — a stat() call per backup — even though that
        # data is only used by the "Recently Changed" context filter. With the
        # default "All Contexts" filter active, no stat() call should happen.
        header_row = next(row for row, is_header in self.page._row_is_header.items() if is_header)
        with patch("pathlib.Path.stat", side_effect=AssertionError("stat() should not be called")):
            self.page._on_cell_clicked(header_row, 0)
            self.page._collapse_all_groups()
            self.page._expand_all_groups()

    def test_collapse_does_not_recreate_row_items(self) -> None:
        # Regression test: collapse/expand must only toggle row visibility and
        # the header marker, not rebuild the table (which would recreate every
        # QTableWidgetItem/badge widget just to hide a few rows).
        row_p3 = self._row_for_path("p3")
        item_before = self.page.backup_table.item(row_p3, 1)
        header_row = next(row for row, is_header in self.page._row_is_header.items() if is_header)
        self.page._on_cell_clicked(header_row, 0)
        item_after = self.page.backup_table.item(row_p3, 1)
        self.assertIs(item_before, item_after)

    def test_context_menus_build_without_error(self) -> None:
        with patch.object(QMenu, "exec", return_value=None):
            self.page._show_row_context_menu(["p1"])
            self.page._show_row_context_menu(["p1", "p3"])
            self.page._show_group_header_context_menu()

    def test_copy_to_clipboard_sets_text(self) -> None:
        # Real OS clipboard access can be extremely slow to unavailable on a
        # headless/CI Windows session (clipboard ownership contention), so this
        # verifies the call is wired correctly without touching the real clipboard.
        with patch.object(QApplication, "clipboard") as mock_clipboard:
            self.page._copy_to_clipboard("some/path")
            mock_clipboard.return_value.setText.assert_called_once_with("some/path")


if __name__ == "__main__":
    unittest.main()
