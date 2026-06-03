from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

_ICONS = {
    "success": "✓",
    "info": "●",
    "warning": "!",
    "error": "✕",
}

# Toasts with an action button stay visible longer
_TIMEOUT_PLAIN = 3500
_TIMEOUT_ACTION = 6000


class _Toast(QFrame):
    dismissed = Signal()

    def __init__(
        self,
        message: str,
        kind: str,
        parent: QWidget,
        action_label: str | None = None,
        action_callback: Callable | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 16, 9)
        layout.setSpacing(8)

        icon = QLabel(_ICONS.get(kind, "●"))
        icon.setObjectName("ToastIcon")
        icon.setProperty("kind", kind)

        text = QLabel(message)
        text.setObjectName("ToastText")
        text.setWordWrap(False)

        layout.addWidget(icon)
        layout.addWidget(text)

        has_action = bool(action_label and action_callback)
        if has_action:
            btn = QPushButton(action_label)
            btn.setObjectName("ToastAction")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda: self._run_action(action_callback))
            layout.addSpacing(4)
            layout.addWidget(btn)

        self.adjustSize()
        self.setMinimumWidth(200)

        timeout = _TIMEOUT_ACTION if has_action else _TIMEOUT_PLAIN
        QTimer.singleShot(timeout, self._dismiss)

    def _run_action(self, callback: Callable) -> None:
        callback()
        self._dismiss()

    def _dismiss(self) -> None:
        self.dismissed.emit()
        self.hide()
        self.deleteLater()


class ToastManager(QObject):
    """Displays non-blocking overlay toasts anchored to the bottom-right of a parent widget."""

    def __init__(self, anchor: QWidget) -> None:
        super().__init__(anchor)
        self._anchor = anchor
        self._active: list[_Toast] = []

    def success(self, message: str) -> None:
        self._show(message, "success")

    def success_undo(self, message: str, undo_callback: Callable) -> None:
        self._show(message, "success", action_label="Undo", action_callback=undo_callback)

    def success_action(self, message: str, action_label: str, action_callback: Callable) -> None:
        self._show(message, "success", action_label=action_label, action_callback=action_callback)

    def info(self, message: str) -> None:
        self._show(message, "info")

    def info_action(self, message: str, action_label: str, action_callback: Callable) -> None:
        self._show(message, "info", action_label=action_label, action_callback=action_callback)

    def warning(self, message: str) -> None:
        self._show(message, "warning")

    def warning_action(self, message: str, action_label: str, action_callback: Callable) -> None:
        self._show(message, "warning", action_label=action_label, action_callback=action_callback)

    def error(self, message: str) -> None:
        self._show(message, "error")

    def reposition(self) -> None:
        self._reposition()

    def _show(
        self,
        message: str,
        kind: str,
        action_label: str | None = None,
        action_callback: Callable | None = None,
    ) -> None:
        toast = _Toast(message, kind, self._anchor, action_label=action_label, action_callback=action_callback)
        self._active.append(toast)
        toast.dismissed.connect(lambda: self._remove(toast))
        toast.show()
        self._reposition()

    def _remove(self, toast: _Toast) -> None:
        if toast in self._active:
            self._active.remove(toast)
        self._reposition()

    def _reposition(self) -> None:
        margin = 16
        gap = 6
        bottom = self._anchor.height() - margin
        for toast in reversed(self._active):
            toast.adjustSize()
            x = self._anchor.width() - toast.width() - margin
            y = bottom - toast.height()
            toast.move(x, y)
            toast.raise_()
            bottom = y - gap
