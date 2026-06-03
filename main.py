from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.core.log import get_logger, setup_logging
from app.core.settings import load_settings
from app.gpo import backup_loader
from app.ui.branding import app_icon
from app.ui.main_window import MainWindow
from app.ui.styles import build_stylesheet


def main() -> int:
    setup_logging()
    log = get_logger(__name__)
    log.info("Nova GPO starting")

    app = QApplication(sys.argv)

    settings = load_settings()
    backup_loader.configure(
        resolve_sids=settings.get("parser", {}).get("resolve_sids", False)
    )
    theme_name = settings["app"].get("theme", "executive_dark")

    app.setApplicationName(settings["app"].get("name", "Nova GPO"))
    app.setOrganizationName("Hallister Labs")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(build_stylesheet(theme_name))

    window = MainWindow(settings)
    window.show()

    exit_code = app.exec()
    log.info("Nova GPO exiting with code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
