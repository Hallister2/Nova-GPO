from __future__ import annotations

"""Binary parser for Windows Registry.pol files.

Registry.pol uses the PReg format:
  - 8-byte header: b"PReg\\x01\\x00\\x00\\x00"
  - Repeated records:  [key\\0 ; value_name\\0 ; type_dword ; size_dword ; data ]
    where fields are delimited by the UTF-16LE characters '[', ';', and ']',
    and all string fields are null-terminated UTF-16LE.

The original loader decoded the entire file as UTF-16LE and split on text
semicolons, which worked for string values but produced garbage for numeric
types (DWORD, QWORD) and binary blobs.  This parser reads the binary fields
correctly and decodes each value based on its registry type.
"""

from pathlib import Path

from app.core.log import get_logger
from app.gpo.gpo_model import GpoSetting

_log = get_logger(__name__)

POL_HEADER = b"PReg\x01\x00\x00\x00"

# Registry key prefix → human-readable category.  Checked in order; first match wins.
_KEY_CATEGORY_MAP: list[tuple[str, str]] = [
    ("software\\policies\\microsoft\\windows\\deviceguard",          "Registry Policy > Device Guard"),
    ("software\\policies\\microsoft\\windows\\bitlocker",            "Registry Policy > BitLocker"),
    ("software\\policies\\microsoft\\windows nt\\audit",             "Registry Policy > Advanced Audit"),
    ("software\\policies\\microsoft\\windows\\windowsupdate",        "Registry Policy > Windows Update"),
    ("software\\policies\\microsoft\\windows defender",              "Registry Policy > Windows Defender"),
    ("software\\policies\\microsoft\\windows\\powershell",           "Registry Policy > PowerShell"),
    ("software\\policies\\microsoft\\windows nt\\terminal services", "Registry Policy > Remote Desktop"),
    ("software\\policies\\microsoft\\windows\\firewall",             "Registry Policy > Firewall"),
    ("software\\policies\\microsoft\\windows\\network connections",  "Registry Policy > Network"),
    ("software\\policies\\microsoft\\windows\\laps",                 "Registry Policy > LAPS"),
    ("software\\policies\\microsoft\\onedrive",                      "Registry Policy > OneDrive"),
    ("software\\policies\\microsoft\\windows\\applocker",            "Registry Policy > AppLocker"),
    ("software\\policies\\microsoft\\windows\\installer",            "Registry Policy > Windows Installer"),
    ("software\\policies\\microsoft\\windows nt\\rpc",               "Registry Policy > RPC"),
    ("system\\currentcontrolset\\control\\deviceguard",              "Registry Policy > Device Guard"),
    ("system\\currentcontrolset\\control\\lsa",                      "Registry Policy > Local Security Authority"),
    ("system\\currentcontrolset\\control\\secureboot",               "Registry Policy > Secure Boot"),
    ("system\\currentcontrolset\\control\\credentialguard",          "Registry Policy > Credential Guard"),
]


def _registry_category(key: str) -> str:
    key_lower = key.lower().replace("/", "\\")
    for prefix, category in _KEY_CATEGORY_MAP:
        if prefix in key_lower:
            return category
    return "Registry Policy"

# UTF-16LE byte sequences for delimiter characters
_OPEN  = b"[\x00"
_SEMI  = b";\x00"
_CLOSE = b"]\x00"
_NULL2 = b"\x00\x00"

# Registry type IDs → name
_REG_TYPE_NAMES: dict[int, str] = {
    0:  "REG_NONE",
    1:  "REG_SZ",
    2:  "REG_EXPAND_SZ",
    3:  "REG_BINARY",
    4:  "REG_DWORD",
    5:  "REG_DWORD_BIG_ENDIAN",
    6:  "REG_LINK",
    7:  "REG_MULTI_SZ",
    8:  "REG_RESOURCE_LIST",
    9:  "REG_FULL_RESOURCE_DESCRIPTOR",
    10: "REG_RESOURCE_REQUIREMENTS_LIST",
    11: "REG_QWORD",
}


# ── Public entry point ────────────────────────────────────────────────────────

def load_registry_pol(
    pol_path: Path,
    root: Path,
    resolve_sids: bool = False,
) -> list[GpoSetting]:
    if not pol_path.is_file():
        return []

    try:
        data = pol_path.read_bytes()
    except OSError as exc:
        _log.warning("Cannot read Registry.pol %s: %s", pol_path, exc)
        return []

    if not data.startswith(POL_HEADER):
        _log.warning("Registry.pol %s has an unexpected header — file may be corrupted or truncated", pol_path)
        return []

    records = _parse_preg(data[len(POL_HEADER):], pol_path)
    relative = pol_path.relative_to(root).as_posix()
    settings: list[GpoSetting] = []

    for rec in records:
        key = rec["key"]
        value_name = rec["value_name"]
        type_name = rec["type_name"]
        decoded = rec["decoded"]

        if not key:
            continue

        display_name = f"{key}\\{value_name}" if value_name else key
        setting_key = f"registry::{relative}::{key}::{value_name}".lower()

        settings.append(
            GpoSetting(
                key=setting_key,
                category=_registry_category(key),
                name=display_name,
                value=f"{type_name}: {decoded}" if decoded else type_name,
                source_file=relative,
            )
        )

    _log.debug("Registry.pol %s: %d record(s) parsed", relative, len(settings))
    return settings


# ── PReg binary parser ────────────────────────────────────────────────────────

def _parse_preg(body: bytes, source_path: Path | None = None) -> list[dict]:
    """Parse the body of a PReg file (after the 8-byte header) into records."""
    records: list[dict] = []
    pos = 0
    length = len(body)

    while pos < length - 1:
        # Scan for opening bracket
        idx = body.find(_OPEN, pos)
        if idx == -1:
            break
        pos = idx + len(_OPEN)

        # key  (null-terminated UTF-16LE)
        key, pos = _read_wstr(body, pos)

        pos = _skip_semi(body, pos)

        # value_name  (null-terminated UTF-16LE)
        value_name, pos = _read_wstr(body, pos)

        pos = _skip_semi(body, pos)

        # type  (4-byte little-endian DWORD)
        if pos + 4 > length:
            break
        type_id = int.from_bytes(body[pos:pos + 4], "little")
        pos += 4

        pos = _skip_semi(body, pos)

        # size  (4-byte little-endian DWORD)
        if pos + 4 > length:
            break
        size = int.from_bytes(body[pos:pos + 4], "little")
        pos += 4

        pos = _skip_semi(body, pos)

        # data  (raw bytes, length = size)
        if pos + size > length:
            _log.warning(
                "Registry.pol %s: record at offset %d claims %d bytes but only %d remain — file may be truncated",
                source_path, pos, size, length - pos,
            )
            raw_data = body[pos:length]
            pos = length
        else:
            raw_data = body[pos:pos + size]
            pos += size

        # skip closing bracket
        if body[pos:pos + 2] == _CLOSE:
            pos += 2

        records.append({
            "key": key,
            "value_name": value_name,
            "type_id": type_id,
            "type_name": _REG_TYPE_NAMES.get(type_id, f"REG_UNKNOWN_{type_id}"),
            "decoded": _decode_value(type_id, raw_data),
        })

    return records


def _read_wstr(data: bytes, pos: int) -> tuple[str, int]:
    """Read a null-terminated UTF-16LE string starting at *pos*.
    Returns (string, new_pos) where new_pos is just past the null terminator.
    """
    end = pos
    length = len(data)
    while end + 1 < length:
        if data[end] == 0 and data[end + 1] == 0:
            break
        end += 2
    value = data[pos:end].decode("utf-16-le", errors="replace")
    return value, end + 2  # skip the two-byte null


def _skip_semi(data: bytes, pos: int) -> int:
    if data[pos:pos + 2] == _SEMI:
        return pos + 2
    return pos


def _decode_value(type_id: int, raw: bytes) -> str:
    """Decode registry value bytes according to their type."""
    try:
        if type_id in (1, 2):  # REG_SZ / REG_EXPAND_SZ
            text = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
            return text

        if type_id == 4:  # REG_DWORD (little-endian)
            if len(raw) >= 4:
                return str(int.from_bytes(raw[:4], "little"))
            return _hex(raw)

        if type_id == 5:  # REG_DWORD_BIG_ENDIAN
            if len(raw) >= 4:
                return str(int.from_bytes(raw[:4], "big"))
            return _hex(raw)

        if type_id == 7:  # REG_MULTI_SZ
            text = raw.decode("utf-16-le", errors="replace")
            parts = [p for p in text.split("\x00") if p]
            return ", ".join(parts) if parts else ""

        if type_id == 11:  # REG_QWORD
            if len(raw) >= 8:
                return str(int.from_bytes(raw[:8], "little"))
            return _hex(raw)

        if type_id == 3:  # REG_BINARY
            return _hex(raw)

        if type_id == 0:  # REG_NONE
            return ""

        # Unknown / resource types — try string decode, fall back to hex
        try:
            text = raw.decode("utf-16-le", errors="strict").rstrip("\x00")
            if text and all(c.isprintable() or c.isspace() for c in text):
                return text
        except Exception:
            pass
        return _hex(raw)

    except Exception as exc:
        _log.debug("Registry value decode error (type %d): %s", type_id, exc)
        return _hex(raw)


def _hex(data: bytes) -> str:
    return data.hex().upper() if data else ""
