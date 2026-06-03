from __future__ import annotations

"""Section-aware parser for Windows Security Template files (GptTmpl.inf).

GptTmpl.inf is a Windows security template in INI format.  The generic
backup_loader INI parser treats every line the same.  This module understands
the section semantics:

  [System Access]          – account / lockout policy (key = integer)
  [Kerberos Policy]        – Kerberos ticket settings
  [Privilege Rights]       – user-right assignments (value = SID list)
  [Registry Values]        – inline registry values (value = type,data)
  [Event Audit]            – legacy per-category audit settings
  [System/Security/Application Log] – event log size & retention
  [Group Membership]       – restricted group members / memberof
  [Registry Keys]          – registry key ACLs (skipped – ACL binary blobs)
  [File Security]          – file ACLs (skipped)
"""

from pathlib import Path

from app.core.log import get_logger
from app.gpo.gpo_model import GpoSetting
from app.gpo.sid_resolver import resolve_privilege_name, resolve_sid_list

_log = get_logger(__name__)

# ── Section-to-category mapping ───────────────────────────────────────────────

_SECTION_CATEGORIES: dict[str, str] = {
    "system access":          "Security Template > Account Policy",
    "kerberos policy":        "Security Template > Kerberos Policy",
    "privilege rights":       "Security Template > User Rights Assignment",
    "registry values":        "Security Template > Registry Values",
    "event audit":            "Security Template > Audit Policy",
    "system log":             "Security Template > System Event Log",
    "security log":           "Security Template > Security Event Log",
    "application log":        "Security Template > Application Event Log",
    "group membership":       "Security Template > Restricted Groups",
    "registry keys":          "Security Template > Registry Key Security",
    "file security":          "Security Template > File Security",
    "service general setting":"Security Template > System Services",
}

# ── Human-readable labels for System Access keys ─────────────────────────────

_SYSTEM_ACCESS_LABELS: dict[str, str] = {
    "minimumpasswordage":          "Minimum password age (days)",
    "maximumpasswordage":          "Maximum password age (days)",
    "minimumpasswordlength":       "Minimum password length",
    "passwordcomplexity":          "Password must meet complexity requirements",
    "passwordhistorysize":         "Enforce password history (remembered passwords)",
    "lockoutbadcount":             "Account lockout threshold (invalid attempts)",
    "resetlockoutcount":           "Reset account lockout counter after (minutes)",
    "lockoutduration":             "Account lockout duration (minutes)",
    "requirelogontochangepassword":"Require logon to change password",
    "forcelogoffwhenhourexpire":   "Force logoff when logon hours expire",
    "newadministratorname":        "Rename administrator account",
    "newguestname":                "Rename guest account",
    "cleartextpassword":           "Store passwords using reversible encryption",
    "lsaanonymousnamelookup":      "Allow anonymous SID/Name translation",
    "enableadminaccount":          "Administrator account status",
    "enableguestaccount":          "Guest account status",
    "obcaseinsensitive":           "Case-insensitive object names",
}

_KERBEROS_LABELS: dict[str, str] = {
    "maxticketage":          "Maximum service ticket lifetime (hours)",
    "maxrenewage":           "Maximum user ticket renewal lifetime (days)",
    "maxserviceage":         "Maximum service ticket lifetime (minutes)",
    "maxclockskew":          "Maximum clock synchronisation tolerance (minutes)",
    "ticketvalidateclient":  "Enforce user logon restrictions",
}

_EVENT_LOG_LABELS: dict[str, str] = {
    "maximumlogsize":         "Maximum log size (kilobytes)",
    "auditlogretentionperiod":"Retention method",
    "retentiondays":          "Retain log for (days)",
    "restrictguestaccess":    "Prevent local guests from accessing log",
}

_AUDIT_LABELS: dict[str, str] = {
    "auditsystemevents":    "Audit system events",
    "auditlogonevents":     "Audit logon events",
    "auditobjectaccess":    "Audit object access",
    "auditprivilegeuse":    "Audit privilege use",
    "auditpolicychange":    "Audit policy change",
    "auditaccountmanage":   "Audit account management",
    "auditdsaccess":        "Audit directory service access",
    "auditaccountlogon":    "Audit account logon events",
    "auditprocesstracking": "Audit process tracking",
}

_REGISTRY_TYPES: dict[str, str] = {
    "1": "REG_SZ",
    "2": "REG_EXPAND_SZ",
    "3": "REG_BINARY",
    "4": "REG_DWORD",
    "7": "REG_MULTI_SZ",
}

# ── Public entry point ────────────────────────────────────────────────────────

def load_security_template(
    path: Path,
    root: Path,
    resolve_sids: bool = False,
) -> list[GpoSetting]:
    """Parse a GptTmpl.inf file and return structured GpoSetting objects."""
    try:
        raw = _read_text(path)
    except OSError as exc:
        _log.warning("Cannot read security template %s: %s", path, exc)
        return []

    relative = path.relative_to(root).as_posix()
    items: list[GpoSetting] = []
    section = ""
    section_key = ""

    for raw_line in raw.splitlines():
        line = raw_line.strip()

        if not line or line.startswith(";") or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            section_key = section.lower()
            continue

        # [Service General Setting] uses CSV lines without '=':
        #   "ServiceName",startup_type,"SDDL"
        if "=" not in line:
            if section_key == "service general setting" and "," in line:
                parts = line.split(",", 2)
                svc_name = parts[0].strip().strip('"')
                svc_rest = ",".join(parts[1:]).strip()
                if svc_name:
                    category = _SECTION_CATEGORIES.get(section_key, f"Security Template > {section}")
                    setting = _parse_service_setting(svc_name, svc_rest, category, relative)
                    if setting:
                        items.append(setting)
            continue

        name_raw, _, value_raw = line.partition("=")
        name = name_raw.strip()
        value = value_raw.strip()

        if not name:
            continue

        setting = _parse_entry(
            section=section,
            section_key=section_key,
            name=name,
            value=value,
            relative=relative,
            resolve_sids=resolve_sids,
        )
        if setting:
            items.append(setting)

    _log.debug("Security template %s: %d setting(s) extracted", relative, len(items))
    return items


# ── Per-section parsers ───────────────────────────────────────────────────────

def _parse_entry(
    section: str,
    section_key: str,
    name: str,
    value: str,
    relative: str,
    resolve_sids: bool,
) -> GpoSetting | None:
    category = _SECTION_CATEGORIES.get(section_key)

    # Skip metadata-only sections
    if section_key in {"unicode", "version"}:
        return None

    if category is None:
        # Unknown section — emit as generic security template entry
        category = f"Security Template > {section}" if section else "Security Template"

    if section_key == "privilege rights":
        return _parse_privilege_right(name, value, category, relative, resolve_sids)

    if section_key == "registry values":
        return _parse_registry_value(name, value, category, relative)

    if section_key == "event audit":
        return _parse_audit_entry(name, value, category, relative)

    if section_key in {"system log", "security log", "application log"}:
        return _parse_event_log_entry(name, value, category, relative)

    if section_key == "group membership":
        return _parse_group_membership(name, value, category, relative, resolve_sids)

    if section_key == "system access":
        return _parse_system_access(name, value, category, relative)

    if section_key == "kerberos policy":
        return _parse_kerberos(name, value, category, relative)

    if section_key == "file security":
        return _parse_file_security(name, value, category, relative)

    if section_key == "registry keys":
        return _parse_registry_key_security(name, value, category, relative)

    if section_key == "service general setting":
        return _parse_service_setting(name, value, category, relative)

    # Generic fallback
    return GpoSetting(
        key=f"sectmpl::{relative}::{section_key}::{name}".lower(),
        category=category,
        name=name,
        value=value,
        source_file=relative,
    )


def _parse_system_access(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    label = _SYSTEM_ACCESS_LABELS.get(name.lower(), name)
    decoded = _decode_boolean_or_int(name.lower(), value)
    return GpoSetting(
        key=f"sectmpl::{relative}::system_access::{name}".lower(),
        category=category,
        name=label,
        value=decoded,
        source_file=relative,
    )


def _parse_kerberos(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    label = _KERBEROS_LABELS.get(name.lower(), name)
    decoded = _decode_boolean_or_int(name.lower(), value)
    return GpoSetting(
        key=f"sectmpl::{relative}::kerberos::{name}".lower(),
        category=category,
        name=label,
        value=decoded,
        source_file=relative,
    )


def _parse_privilege_right(
    name: str, value: str, category: str, relative: str, resolve_sids: bool,
) -> GpoSetting:
    label = resolve_privilege_name(name)
    if value.strip():
        resolved = resolve_sid_list(value, use_api=resolve_sids)
    else:
        resolved = "(empty — no accounts assigned)"
    return GpoSetting(
        key=f"sectmpl::{relative}::privilege::{name}".lower(),
        category=category,
        name=label,
        value=resolved,
        source_file=relative,
    )


def _parse_registry_value(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    # Format: regpath = type_id,data
    type_str, _, data = value.partition(",")
    type_str = type_str.strip()
    data = data.strip().strip('"')
    type_name = _REGISTRY_TYPES.get(type_str, f"type {type_str}")

    # Strip leading MACHINE\ or SOFTWARE\ prefix to keep name readable
    display_name = name.replace("MACHINE\\", "").replace("SOFTWARE\\", "")

    decoded_value = f"{type_name}: {data}" if data else type_name
    return GpoSetting(
        key=f"sectmpl::{relative}::regval::{name}".lower(),
        category=category,
        name=display_name,
        value=decoded_value,
        source_file=relative,
    )


def _parse_audit_entry(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    label = _AUDIT_LABELS.get(name.lower(), name)
    decoded = _decode_audit_value(value)
    return GpoSetting(
        key=f"sectmpl::{relative}::audit::{name}".lower(),
        category=category,
        name=label,
        value=decoded,
        source_file=relative,
    )


def _parse_event_log_entry(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    label = _EVENT_LOG_LABELS.get(name.lower(), name)

    # AuditLogRetentionPeriod: 0=Overwrite, 1=Overwrite by days, 2=Never overwrite
    if name.lower() == "auditlogretentionperiod":
        value = {"0": "Overwrite events as needed", "1": "Overwrite events older than", "2": "Do not overwrite"}.get(value.strip(), value)

    return GpoSetting(
        key=f"sectmpl::{relative}::eventlog::{name}".lower(),
        category=category,
        name=label,
        value=value,
        source_file=relative,
    )


def _parse_group_membership(
    name: str, value: str, category: str, relative: str, resolve_sids: bool,
) -> GpoSetting:
    # Format: GroupName__Members = SID,SID,...  or  GroupName__Memberof = ...
    group, _, role = name.partition("__")
    group = group.strip()
    role = role.strip()

    # Resolve group SID if the group name looks like a SID
    if group.upper().startswith("*S-"):
        group = resolve_sid_list(group, use_api=resolve_sids)

    member_label = "Member of" if role.lower() == "memberof" else "Members"

    resolved_value = resolve_sid_list(value, use_api=resolve_sids) if value.strip() else "(none)"
    display_name = f"{group} – {member_label}"

    return GpoSetting(
        key=f"sectmpl::{relative}::group::{name}".lower(),
        category=category,
        name=display_name,
        value=resolved_value,
        source_file=relative,
    )


def _summarize_sddl(sddl: str) -> str:
    """Return a readable summary of an SDDL security-descriptor string."""
    if not sddl:
        return "(empty security descriptor)"
    allow_count = sddl.count("(A;")
    deny_count  = sddl.count("(D;")
    audit_count = sddl.count("(AU;")
    parts: list[str] = []
    if allow_count:
        parts.append(f"{allow_count} allow")
    if deny_count:
        parts.append(f"{deny_count} deny")
    if audit_count:
        parts.append(f"{audit_count} audit")
    ace_summary = (", ".join(parts) + " ACE(s)") if parts else "no ACEs"
    # Show truncated raw SDDL so operators can check it
    truncated = sddl if len(sddl) <= 120 else sddl[:120] + "…"
    return f"{ace_summary}; SDDL: {truncated}"


_SERVICE_STARTUP: dict[str, str] = {
    "2": "Automatic",
    "3": "Manual",
    "4": "Disabled",
}


def _parse_service_setting(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    # Format: "ServiceName",startup_type,"SDDL"
    # The name field is the raw line key (everything before '=') which may itself
    # be quoted — strip quotes and commas to get the actual service name.
    # The value field is: startup_type_int,"sddl_or_empty"
    service_name = name.strip().strip('"')

    parts = value.split(",", 1)
    startup_raw = parts[0].strip()
    startup = _SERVICE_STARTUP.get(startup_raw, f"type {startup_raw}")

    # Optional SDDL for the service DACL
    sddl = parts[1].strip().strip('"') if len(parts) > 1 else ""
    decoded = f"Startup: {startup}"
    if sddl:
        decoded += f"; ACL: {_summarize_sddl(sddl)}"

    return GpoSetting(
        key=f"sectmpl::{relative}::service::{service_name}".lower(),
        category=category,
        name=service_name,
        value=decoded,
        source_file=relative,
    )


def _parse_file_security(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    sddl = value.strip().strip('"')
    return GpoSetting(
        key=f"sectmpl::{relative}::filesec::{name}".lower(),
        category=category,
        name=name,
        value=_summarize_sddl(sddl),
        source_file=relative,
    )


def _parse_registry_key_security(
    name: str, value: str, category: str, relative: str,
) -> GpoSetting:
    # Format: propagation_mode,"SDDL"  — propagation is 0=Inherit, 1=Replace, 2=Deny
    _PROPAGATION = {"0": "Propagate permissions", "1": "Replace permissions", "2": "Do not allow"}
    mode_raw, _, rest = value.partition(",")
    mode_label = _PROPAGATION.get(mode_raw.strip(), mode_raw.strip())
    sddl = rest.strip().strip('"')
    summary = _summarize_sddl(sddl)
    return GpoSetting(
        key=f"sectmpl::{relative}::regkeysec::{name}".lower(),
        category=category,
        name=name,
        value=f"{mode_label}; {summary}",
        source_file=relative,
    )


# ── Value decoders ────────────────────────────────────────────────────────────

_BOOLEAN_KEYS = {
    "passwordcomplexity", "cleartextpassword", "requirelogontochangepassword",
    "forcelogoffwhenhourexpire", "lsaanonymousnamelookup", "enableadminaccount",
    "enableguestaccount", "obcaseinsensitive", "ticketvalidateclient",
    "restrictguestaccess",
}


def _decode_boolean_or_int(key: str, value: str) -> str:
    stripped = value.strip()
    if key in _BOOLEAN_KEYS:
        return {"0": "Disabled", "1": "Enabled"}.get(stripped, stripped)
    if stripped == "-1":
        return "No limit / not defined"
    return stripped


def _decode_audit_value(value: str) -> str:
    return {
        "0": "No auditing",
        "1": "Success",
        "2": "Failure",
        "3": "Success and Failure",
    }.get(value.strip(), value.strip())


# ── File reading helpers ──────────────────────────────────────────────────────

def _read_text(path: Path) -> str:
    # Security templates are often UTF-16 LE with BOM
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="ignore")
