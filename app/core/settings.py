from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _get_app_root() -> Path:
    # When running as a PyInstaller frozen EXE, sys._MEIPASS is the directory
    # where bundled data files (assets/, etc.) are extracted at runtime.
    # In development, walk up from this file: app/core/settings.py -> project root.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _configure_ssl_for_frozen_exe() -> None:
    """Point Python's SSL stack at the CA bundle bundled by PyInstaller.

    Without this, HTTPS requests (update checker, download) fail silently or
    hang in the frozen EXE because the default CA path doesn't exist.
    """
    if not (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")):
        return

    meipass = Path(sys._MEIPASS)

    # Prefer certifi bundle if we bundled it
    certifi_ca = meipass / "certifi" / "cacert.pem"
    # Fall back to ssl_certs bundle (Python's built-in CA file)
    ssl_ca = meipass / "ssl_certs" / os.path.basename(
        __import__("ssl").get_default_verify_paths().cafile or "cacert.pem"
    )

    ca_file = str(certifi_ca) if certifi_ca.exists() else (
        str(ssl_ca) if ssl_ca.exists() else None
    )

    if ca_file:
        os.environ.setdefault("SSL_CERT_FILE", ca_file)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)


APP_ROOT = _get_app_root()
_configure_ssl_for_frozen_exe()
COMPANY_NAME = "Hallister Labs"
APP_NAME = "Nova GPO"


def _user_data_root() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / COMPANY_NAME / APP_NAME

    return Path.home() / f".{COMPANY_NAME.lower().replace(' ', '-')}" / APP_NAME


USER_DATA_DIR = _user_data_root()
CONFIG_DIR = USER_DATA_DIR
SETTINGS_PATH = CONFIG_DIR / "settings.json"
LEGACY_CONFIG_DIR = APP_ROOT / "config"
LEGACY_SETTINGS_PATH = LEGACY_CONFIG_DIR / "settings.json"


DEFAULT_SETTINGS: dict[str, Any] = {
    "app": {
        "name": "Nova GPO",
        "theme": "executive_dark",
        "check_for_updates_on_startup": True,
    },
    "storage": {
        "backup_root": "",
        "backup_roots": [],
        "reports_dir": "reports",
        "archive_retention_days": 60,
    },
    "parser": {
        "resolve_sids": False,
    },
}


def load_settings() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not SETTINGS_PATH.exists():
        migrated = _load_legacy_settings()
        settings = _migrate_settings(_merge_defaults(DEFAULT_SETTINGS, migrated or {}))
        save_settings(settings)
        return settings

    with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)

    return _migrate_settings(_merge_defaults(DEFAULT_SETTINGS, loaded))


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)


def _merge_defaults(defaults: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(defaults))

    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value

    return merged


def _migrate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    storage = settings.setdefault("storage", {})
    backup_roots = storage.get("backup_roots")
    legacy_root = storage.get("backup_root", "")

    if not isinstance(backup_roots, list):
        backup_roots = []

    clean_roots = [str(path).strip() for path in backup_roots if str(path).strip()]

    if legacy_root and legacy_root not in clean_roots:
        clean_roots.insert(0, str(legacy_root))

    storage["backup_roots"] = clean_roots
    storage["backup_root"] = clean_roots[0] if clean_roots else ""

    try:
        retention_days = int(storage.get("archive_retention_days", 60))
    except (TypeError, ValueError):
        retention_days = 60

    storage["archive_retention_days"] = max(0, retention_days)
    storage.pop("include_unchanged", None)
    settings.setdefault("parser", {}).pop("include_unchanged", None)
    return settings


def _load_legacy_settings() -> dict[str, Any] | None:
    if not LEGACY_SETTINGS_PATH.exists():
        return None

    try:
        with LEGACY_SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None

    return loaded if isinstance(loaded, dict) else None
