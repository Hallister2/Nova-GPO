from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QWidget


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, text: str = "", sort_key: object | None = None) -> None:
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.sort_key if self.sort_key is not None else self.text().casefold()
        other_sort_key = getattr(other, "sort_key", None)
        right = other_sort_key if other_sort_key is not None else other.text().casefold()
        try:
            return left < right
        except TypeError:
            return str(left) < str(right)


def badge(text: str, state: str = "empty", min_width: int = 84, parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("StatusBadge")
    label.setProperty("state", state)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setMinimumWidth(min_width)
    return label


def badge_item(
    sort_text: str = "",
    user_data: object | None = None,
    sort_key: object | None = None,
) -> QTableWidgetItem:
    item = SortableTableWidgetItem("", sort_key)
    item.setData(Qt.ItemDataRole.UserRole, user_data if user_data is not None else sort_text)
    item.setData(Qt.ItemDataRole.DisplayRole, "")
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def readonly_item(
    text: str,
    user_data: object | None = None,
    sort_key: object | None = None,
) -> QTableWidgetItem:
    item = SortableTableWidgetItem(text, sort_key)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def configure_enterprise_table(table: QTableWidget, row_height: int = 42) -> None:
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setSortingEnabled(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.verticalHeader().setDefaultSectionSize(row_height)
