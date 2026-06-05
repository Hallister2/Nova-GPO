from __future__ import annotations

import json
import os
import shutil
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


def _documents_folder() -> Path:
    """Return the user's Documents folder, respecting folder redirection via the registry."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            ) as key:
                path, _ = winreg.QueryValueEx(key, "Personal")
            return Path(path)
        except Exception:
            pass
    return Path.home() / "Documents"


def _user_data_root() -> Path:
    return _documents_folder() / APP_NAME


# ── canonical path structure ──────────────────────────────────────────────────
USER_DATA_DIR = _user_data_root()
CONFIG_DIR    = USER_DATA_DIR / "Config"
REPORTS_DIR   = USER_DATA_DIR / "Reports"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

# ── legacy paths ──────────────────────────────────────────────────────────────
# Old APPDATA location used before moving to Documents
_LEGACY_APPDATA_DIR = (
    Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    / COMPANY_NAME / APP_NAME
)
LEGACY_CONFIG_DIR    = APP_ROOT / "config"
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


def _ensure_data_dirs() -> None:
    """Create the full data directory tree under Documents/Nova GPO if missing."""
    for directory in (
        CONFIG_DIR,
        REPORTS_DIR,
        USER_DATA_DIR / "Library" / "Compares",
        USER_DATA_DIR / "Reviews",
        USER_DATA_DIR / "Logs",
    ):
        directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    _ensure_data_dirs()

    if not SETTINGS_PATH.exists():
        _migrate_from_appdata()
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
    # Check new Config subfolder first, then old app-root config dir
    candidates = [CONFIG_DIR / "settings.json", LEGACY_SETTINGS_PATH]
    for path in candidates:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                return loaded if isinstance(loaded, dict) else None
            except (OSError, json.JSONDecodeError):
                pass
    return None


def _migrate_from_appdata() -> None:
    """One-time migration: copy data from the old %APPDATA% location to Documents."""
    if not _LEGACY_APPDATA_DIR.exists():
        return

    # Map old path → new path
    moves = [
        (_LEGACY_APPDATA_DIR / "settings.json",        CONFIG_DIR / "settings.json"),
        (_LEGACY_APPDATA_DIR / "library" / "compares",  USER_DATA_DIR / "Library" / "Compares"),
        (_LEGACY_APPDATA_DIR / "reviews",               USER_DATA_DIR / "Reviews"),
    ]

    for src, dst in moves:
        if not src.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        except Exception:
            pass
