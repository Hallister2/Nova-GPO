from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem


def badge(text: str, state: str = "empty", min_width: int = 84) -> QLabel:
    label = QLabel(text)
    label.setObjectName("StatusBadge")
    label.setProperty("state", state)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setMinimumWidth(min_width)
    return label


def badge_item(sort_text: str = "", user_data: object | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem("")
    item.setData(Qt.ItemDataRole.UserRole, user_data if user_data is not None else sort_text)
    item.setData(Qt.ItemDataRole.DisplayRole, "")
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def readonly_item(text: str, user_data: object | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
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
