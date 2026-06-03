from __future__ import annotations

from PySide6.QtGui import QIcon

from app.core.settings import APP_ROOT


ASSETS_DIR = APP_ROOT / "assets"
APP_ICON_PATH = ASSETS_DIR / "Nova GPO - Icon.ico"
APP_ICON_FALLBACK_PATH = ASSETS_DIR / "Nova GPO - Icon.png"
APP_LOGO_PATH = ASSETS_DIR / "Nova GPO - Application Logo.png"


def app_icon() -> QIcon:
    primary = APP_ICON_PATH if APP_ICON_PATH.exists() else APP_ICON_FALLBACK_PATH
    return QIcon(str(primary))
