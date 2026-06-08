from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.gpo import ilt_parser
from app.gpo.sid_resolver import resolve_privilege_name


GP_NS = "http://www.microsoft.com/GroupPolicy/Settings"
REG_NS = "http://www.microsoft.com/GroupPolicy/Settings/Registry"
NS = {
    "gp": GP_NS,
    "reg": REG_NS,
}


@dataclass(frozen=True)
class GpoReportPolicy:
    scope: str
    name: str
    state: str
    category: str
    supported: str
    explain: str
    settings: list[str]
    policy_type: str = "Administrative Template"
    source: str = "gpreport.xml"
    identity: str = ""


@dataclass(frozen=True)
class GpoReportSummary:
    name: str
    domain: str
    created_time: str
    modified_time: str
    computer_enabled: str
    user_enabled: str
    policies: list[GpoReportPolicy]


def load_gpreport(backup_folder: str) -> GpoReportSummary | None:
    report_path = Path(backup_folder) / "gpreport.xml"

    if not report_path.exists():
        return None

    try:
        stat = report_path.stat()
    except OSError:
        return None

    return _load_gpreport_cached(str(report_path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=256)
def _load_gpreport_cached(
    report_path: str,
    _modified_time_ns: int,
    _file_size: int,
) -> GpoReportSummary | None:
    path = Path(report_path)
    if not path.exists():
        return None

    root = _read_xml_root(path)

    name = _text(root, "gp:Name")
    domain = _text(root.find("gp:Identifier", NS), "gp:Domain")
    created_time = _text(root, "gp:CreatedTime")
    modified_time = _text(root, "gp:ModifiedTime")

    computer = root.find("gp:Computer", NS)
    user = root.find("gp:User", NS)

    computer_enabled = _text(computer, "gp:Enabled") if computer is not None else "false"
    user_enabled = _text(user, "gp:Enabled") if user is not None else "false"

    policies: list[GpoReportPolicy] = []
    policies.extend(_read_policies(computer, "Computer Configuration"))
    policies.extend(_read_policies(user, "User Configuration"))

    # WMI filter linkage — the actual WQL query lives in AD, but we can surface
    # the filter name/description so changes to linked filters appear in diffs.
    filter_name = _text(root, "gp:FilterName")
    if not filter_name:
        # Some report versions nest it under a different element
        filter_elem = root.find("gp:Filter", NS)
        if filter_elem is not None:
            filter_name = _text(filter_elem, "gp:Name") or _text(filter_elem, "gp:FilterName")
    if filter_name:
        filter_desc = _text(root, "gp:FilterDescription")
        filter_id   = _text(root, "gp:FilterID") or _text(root, "gp:FilterGuid")
        settings: list[str] = [f"Linked filter: {filter_name}"]
        if filter_desc:
            settings.append(f"Description: {filter_desc}")
        if filter_id:
            settings.append(f"Filter ID: {filter_id}")
        policies.append(
            GpoReportPolicy(
                scope="Computer Configuration",
                name=filter_name,
                state="Linked",
                category="WMI Filter",
                supported="",
                explain=filter_desc or "",
                settings=settings,
                policy_type="WMI Filter",
                source="gpreport.xml::WMI Filter",
                identity=_identity("wmifilter", filter_name),
            )
        )

    return GpoReportSummary(
        name=name,
        domain=domain,
        created_time=created_time,
        modified_time=modified_time,
        computer_enabled=computer_enabled,
        user_enabled=user_enabled,
        policies=policies,
    )


def _read_xml_root(path: Path) -> ET.Element:
    data = path.read_bytes()

    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return ET.fromstring(data.decode(encoding))
        except (UnicodeError, ET.ParseError):
            continue

    return ET.fromstring(data.decode("utf-16", errors="ignore"))


def _read_policies(section: ET.Element | None, scope: str) -> list[GpoReportPolicy]:
    if section is None:
        return []

    policies: list[GpoReportPolicy] = []

    for policy in _iter_local(section, "Policy"):
        name = _child_text(policy, "Name")
        category = _category_path(policy)
        policies.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state=_child_text(policy, "State"),
                category=category,
                supported=_child_text(policy, "Supported"),
                explain=_child_text(policy, "Explain"),
                settings=_policy_settings(policy),
                policy_type="Administrative Template",
                source="gpreport.xml::Administrative Template",
                identity=_policy_identity(scope, "Administrative Template", policy, name, category),
            )
        )

    policies.extend(_read_preference_items(section, scope))
    policies.extend(_read_extension_data(section, scope))

    return policies


def _read_preference_items(section: ET.Element, scope: str) -> list[GpoReportPolicy]:
    items: list[GpoReportPolicy] = []

    for elem in section.iter():
        tag = _clean_tag(elem.tag)

        if tag == "Policy" or not _is_preference_item(elem):
            continue

        name = _display_name(elem)
        if not name:
            continue

        preference_type = _preference_type(tag)
        settings = _preference_settings(elem)

        items.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state=_preference_state(elem),
                category=f"Group Policy Preferences > {preference_type}",
                supported="",
                explain=_preference_explain(elem),
                settings=settings,
                policy_type="Preference",
                source=f"gpreport.xml::{preference_type}",
                identity=_preference_identity(scope, preference_type, elem, name),
            )
        )

    return items


def _category_path(policy: ET.Element) -> str:
    category = _first_child(policy, "Category")

    if category is None:
        return "Not reported"

    if category.text and category.text.strip():
        return category.text.strip()

    names = [
        item.text.strip()
        for item in category.iter()
        if _clean_tag(item.tag) == "Name"
        and item.text
        and item.text.strip()
    ]

    if names:
        return " > ".join(names)

    return "Not reported"


def _text(parent: ET.Element | None, path: str) -> str:
    if parent is None:
        return ""

    node = parent.find(path, NS)

    if node is None or node.text is None:
        return ""

    return node.text.strip()


def _policy_settings(policy: ET.Element) -> list[str]:
    settings: list[str] = []

    for elem in policy.iter():
        tag = _clean_tag(elem.tag)

        if tag not in {
            "Numeric",
            "String",
            "Decimal",
            "Boolean",
            "Enum",
            "ListBox",
            "EditText",
            "CheckBox",
            "DropDownList",
        }:
            continue

        name = elem.attrib.get("name", "").strip() or _child_text(elem, "Name")
        value = elem.attrib.get("value", "").strip() or _child_text(elem, "Value")

        if not value and elem.text:
            value = elem.text.strip()

        list_values = [
            _compact_text(child)
            for child in _iter_local(elem, "Data")
            if _compact_text(child)
        ]

        if list_values:
            value = ", ".join(list_values)

        if name and value:
            settings.append(f"{name}: {value}")
        elif value:
            settings.append(value)

    return _dedupe(settings)


def _policy_identity(
    scope: str,
    policy_type: str,
    policy: ET.Element,
    name: str,
    category: str,
) -> str:
    registry_identity = _policy_registry_identity(policy)
    if registry_identity:
        return _identity("policy", scope, policy_type, registry_identity)

    return _identity("policy", scope, policy_type, name or category)


def _policy_registry_identity(policy: ET.Element) -> str:
    registry_setting = _first_descendant(policy, "RegistrySetting")
    if registry_setting is None:
        return ""

    key_path = _child_text(registry_setting, "KeyPath")
    value = _first_descendant(registry_setting, "Value")
    value_name = _child_text(value, "Name") if value is not None else ""

    if key_path or value_name:
        return _identity("registry", key_path, value_name)

    return ""


def _is_preference_item(elem: ET.Element) -> bool:
    tag = _clean_tag(elem.tag)

    if tag in {
        "Properties",
        "Filters",
        "FilterCollection",
        "FilterComputer",
        "FilterFile",
        "FilterGroup",
        "FilterRegistry",
        "FilterUser",
        "GPOSettingOrder",
        "Values",
    }:
        return False

    if _first_child(elem, "Properties") is not None:
        return True

    if elem.attrib.get("uid") and elem.attrib.get("name"):
        return True

    return False


def _display_name(elem: ET.Element) -> str:
    return (
        elem.attrib.get("name", "").strip()
        or elem.attrib.get("status", "").strip()
        or _child_text(elem, "Name")
    )


def _preference_type(tag: str) -> str:
    words = {
        "EnvironmentVariable": "Environment Variable",
        "EnvironmentVariables": "Environment Variables",
        "Registry": "Registry",
        "Folder": "Folder",
        "Folders": "Folders",
        "Shortcut": "Shortcut",
        "Drive": "Drive Map",
        "DriveMap": "Drive Map",
        "Printer": "Printer",
        "SharedPrinter": "Printer",
        "PortPrinter": "Printer",
        "TcpipPrinter": "Printer",
        "LocalPrinter": "Printer",
        "ScheduledTask": "Scheduled Task",
        "ScheduledTaskV2": "Scheduled Task",
        "ImmediateTask": "Scheduled Task",
        "ImmediateTaskV2": "Scheduled Task",
        "Task": "Scheduled Task",
        "TaskV2": "Scheduled Task",
        "File": "File",
        "Files": "Files",
        "Group": "Local User/Group",
        "User": "Local User/Group",
        "LocalGroup": "Local User/Group",
        "LocalUser": "Local User/Group",
        "Service": "Service",
        "Services": "Service",
        "IniFile": "INI File",
        "Ini": "INI File",
        "DataSource": "Data Source",
        "InternetSettings": "Internet Settings",
        "PowerOption": "Power Option", "Power": "Power Option",
        "NetShare": "Network Share", "NetworkShare": "Network Share",
        "NetOption": "Network Option", "VpnOption": "Network Option",
        "DialupOption": "Network Option",
        "Device": "Device",
        "UserLocale": "Regional Options", "SystemLocale": "Regional Options",
        "InputLocale": "Regional Options", "RegionalOptions": "Regional Options",
        "FolderOptions": "Folder Options", "OpenWith": "Folder Options",
        "StartMenuTaskbar": "Start Menu/Taskbar",
    }
    return words.get(tag, tag)


def _preference_state(elem: ET.Element) -> str:
    disabled = elem.attrib.get("disabled", "").strip().lower()

    if disabled in {"1", "true", "yes"}:
        return "Disabled"

    if disabled in {"0", "false", "no"}:
        return "Enabled"

    return elem.attrib.get("status", "").strip() or "Configured"


def _preference_explain(elem: ET.Element) -> str:
    changed = elem.attrib.get("changed", "").strip()
    uid = elem.attrib.get("uid", "").strip()
    parts = []

    if changed:
        parts.append(f"Changed: {changed}")

    if uid:
        parts.append(f"UID: {uid}")

    return "\n".join(parts)


def _preference_settings(elem: ET.Element) -> list[str]:
    settings: list[str] = []

    for key, value in sorted(elem.attrib.items()):
        if key in {"changed", "clsid", "created", "image", "name", "status", "uid"}:
            continue

        if value.strip():
            settings.append(f"{key}: {value.strip()}")

    properties = _first_child(elem, "Properties")
    if properties is not None:
        for key, value in sorted(properties.attrib.items()):
            if value.strip():
                settings.append(f"{key}: {value.strip()}")

    filters = _first_child(elem, "Filters")
    settings.extend(ilt_parser.format_filters(filters))

    return _dedupe(settings)


def _preference_identity(
    scope: str,
    preference_type: str,
    elem: ET.Element,
    name: str,
) -> str:
    properties = _first_child(elem, "Properties")
    property_identity = _preference_property_identity(preference_type, properties)
    if property_identity:
        return _identity("preference", scope, preference_type, property_identity)

    uid = elem.attrib.get("uid", "").strip()
    if uid:
        return _identity("preference", scope, preference_type, uid)

    return _identity("preference", scope, preference_type, name)


def _preference_property_identity(preference_type: str, properties: ET.Element | None) -> str:
    if properties is None:
        return ""

    attrs = properties.attrib
    if preference_type == "Registry":
        return _identity(
            attrs.get("action", ""),
            attrs.get("hive", ""),
            attrs.get("key", ""),
            attrs.get("name", ""),
            attrs.get("type", ""),
        )

    if preference_type in {"Folder", "Folders"}:
        return _identity(attrs.get("path", ""))

    if preference_type in {"Environment Variable", "Environment Variables"}:
        return _identity(attrs.get("name", ""), attrs.get("user", ""))

    if preference_type in {"Drive Map", "Shortcut", "Printer", "Scheduled Task", "File", "Files"}:
        return _identity(
            attrs.get("name", ""),
            attrs.get("path", ""),
            attrs.get("targetPath", ""),
            attrs.get("location", ""),
            attrs.get("letter", ""),
            attrs.get("useLetter", ""),
            attrs.get("localName", ""),
            attrs.get("printerName", ""),
            attrs.get("taskName", ""),
        )

    if preference_type in {"Local User/Group", "Service", "INI File", "Data Source"}:
        return _identity(
            attrs.get("name", ""),
            attrs.get("groupName", ""),
            attrs.get("userName", ""),
            attrs.get("serviceName", ""),
            attrs.get("path", ""),
            attrs.get("section", ""),
            attrs.get("property", ""),
            attrs.get("dsn", ""),
        )

    important_values = [
        value
        for key, value in sorted(attrs.items())
        if key not in {"changed", "disabled", "image"}
    ]
    return _identity(*important_values)


def _iter_local(parent: ET.Element, tag_name: str) -> list[ET.Element]:
    return [elem for elem in parent.iter() if _clean_tag(elem.tag) == tag_name]


def _first_child(parent: ET.Element, tag_name: str) -> ET.Element | None:
    for child in parent:
        if _clean_tag(child.tag) == tag_name:
            return child

    return None


def _first_descendant(parent: ET.Element, tag_name: str) -> ET.Element | None:
    for elem in parent.iter():
        if elem is parent:
            continue

        if _clean_tag(elem.tag) == tag_name:
            return elem

    return None


def _child_text(parent: ET.Element | None, tag_name: str) -> str:
    if parent is None:
        return ""

    child = _first_child(parent, tag_name)

    if child is None:
        return ""

    return _compact_text(child)


def _value_from(elem: ET.Element, *names: str) -> str:
    for name in names:
        attr_value = elem.attrib.get(name, "").strip()
        if attr_value:
            return attr_value

    for name in names:
        text_value = _child_text(elem, name)
        if text_value:
            return text_value

    return ""


def _compact_text(elem: ET.Element) -> str:
    return " ".join(text.strip() for text in elem.itertext() if text.strip())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []

    for item in items:
        if item in seen:
            continue

        seen.add(item)
        results.append(item)

    return results


def _identity(*parts: str) -> str:
    clean_parts = [
        _normalize_identity_part(part)
        for part in parts
        if _normalize_identity_part(part)
    ]
    return "::".join(clean_parts)


def _normalize_identity_part(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _clean_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]

    return tag


# ── ExtensionData parsing ─────────────────────────────────────────────────────

# Script type codes used in gpreport.xml
_COMPUTER_SCRIPT_TYPES = {"0": "Startup", "1": "Shutdown"}
_USER_SCRIPT_TYPES     = {"0": "Logon",   "1": "Logoff"}

# Human-readable names for common security Account/Audit setting keys
_SECURITY_SETTING_LABELS: dict[str, str] = {
    "minimumpasswordage":       "Minimum password age (days)",
    "maximumpasswordage":       "Maximum password age (days)",
    "minimumpasswordlength":    "Minimum password length",
    "passwordcomplexity":       "Password complexity",
    "passwordhistorysize":      "Enforce password history",
    "lockoutbadcount":          "Account lockout threshold",
    "resetlockoutcount":        "Reset lockout counter after (minutes)",
    "lockoutduration":          "Account lockout duration (minutes)",
    "auditsystemevents":        "Audit system events",
    "auditlogonevents":         "Audit logon events",
    "auditobjectaccess":        "Audit object access",
    "auditprivilegeuse":        "Audit privilege use",
    "auditpolicychange":        "Audit policy change",
    "auditaccountmanage":       "Audit account management",
    "auditdsaccess":            "Audit directory service access",
    "auditaccountlogon":        "Audit account logon events",
    "auditprocesstracking":     "Audit process tracking",
    "maximumlogsize":           "Maximum log size (kilobytes)",
    "auditlogretentionperiod":  "Audit log retention method",
    "retentiondays":            "Retain log for (days)",
    "maxticketage":             "Max service ticket lifetime (hours)",
    "maxrenewage":              "Max user ticket renewal (days)",
    "maxserviceage":            "Max service ticket (minutes)",
    "maxclockskew":             "Max clock skew tolerance (minutes)",
    "ticketvalidateclient":     "Enforce user logon restrictions",
}

_AUDIT_VALUE_LABELS = {"0": "No auditing", "1": "Success", "2": "Failure", "3": "Success and Failure"}
_BOOL_VALUE_LABELS  = {"0": "Disabled", "1": "Enabled"}


def _read_extension_data(section: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Extract policy items from all <ExtensionData><Extension> blocks."""
    items: list[GpoReportPolicy] = []

    for ext_data in _iter_local(section, "ExtensionData"):
        for extension in ext_data:
            ext_type = _extension_type(extension)
            if ext_type == "scripts":
                items.extend(_parse_script_extension(extension, scope))
            elif ext_type in {"security", "securitysettings"}:
                items.extend(_parse_security_extension(extension, scope))
            elif ext_type in {"folderredirection", "folderredirectionsettings"}:
                items.extend(_parse_folder_redirection_extension(extension, scope))
            elif ext_type in {"auditsettings", "auditpolicy", "advancedauditpolicysettings"}:
                items.extend(_parse_audit_policy_extension(extension, scope))
            elif ext_type in {"applockersettings", "applocker", "applockers settings"}:
                items.extend(_parse_applocker_extension(extension, scope))
            elif ext_type in {"firewall", "firewallsettings", "windowsfirewall", "firewall rules"}:
                items.extend(_parse_firewall_extension(extension, scope))
            elif ext_type in {"registrysettings", "registry settings",
                               "internetexplorer", "internetsettings"}:
                # ADMX-backed policies (3rd-party templates, IE settings, etc.)
                items.extend(_parse_admx_extension(extension, scope))
            elif ext_type in {"wlansvcsettings", "wlansvc"}:
                items.extend(_parse_wlan_extension(extension, scope))
            elif ext_type in {"dot3svcsettings", "dot3svc"}:
                items.extend(_parse_dot3_extension(extension, scope))
            elif ext_type in {"publickeysettings", "publickey"}:
                items.extend(_parse_public_key_extension(extension, scope))
            elif ext_type in {"nrptsettings", "nrpt"}:
                items.extend(_parse_nrpt_extension(extension, scope))
            else:
                items.extend(_parse_generic_extension(extension, scope, ext_type))

    return items


def _extension_type(extension: ET.Element) -> str:
    """Derive a normalised extension type string from the element."""
    # Try xsi:type attribute first  (e.g. "q2:Scripts" → "scripts")
    xsi_ns = "http://www.w3.org/2001/XMLSchema-instance"
    xsi_type = extension.get(f"{{{xsi_ns}}}type", "")
    if xsi_type:
        local = xsi_type.split(":", 1)[-1].lower()
        return local

    # Fall back to the element tag
    return _clean_tag(extension.tag).lower()


def _parse_script_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    items: list[GpoReportPolicy] = []
    type_map = _COMPUTER_SCRIPT_TYPES if scope == "Computer Configuration" else _USER_SCRIPT_TYPES

    for script_block in extension.iter():
        tag = _clean_tag(script_block.tag)
        if tag not in {"Script", "script"}:
            continue

        # Find the type (Startup/Shutdown/Logon/Logoff)
        script_type_raw = (
            _child_text(script_block, "Type")
            or _child_text(script_block, "ScriptType")
        )
        script_kind = type_map.get(script_type_raw.strip(), script_type_raw or "Script")

        for script_entry in script_block:
            entry_tag = _clean_tag(script_entry.tag)
            if entry_tag not in {"Script", "script"}:
                continue

            name = (
                _child_text(script_entry, "Name")
                or _child_text(script_entry, "ScriptName")
            )
            if not name:
                continue

            params = _child_text(script_entry, "Parameters") or ""
            settings: list[str] = [f"Script: {name}"]
            if params:
                settings.append(f"Parameters: {params}")

            items.append(
                GpoReportPolicy(
                    scope=scope,
                    name=name,
                    state="Configured",
                    category=f"Scripts > {script_kind}",
                    supported="",
                    explain="",
                    settings=settings,
                    policy_type="Script",
                    source="gpreport.xml::Scripts",
                    identity=_identity("script", scope, script_kind, name),
                )
            )

    return items


def _parse_security_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    items: list[GpoReportPolicy] = []

    for elem in extension.iter():
        tag = _clean_tag(elem.tag)

        # ── User Rights Assignment (Se*Privilege → account list) ──────────────
        if tag == "UserRightsAssignment":
            items.extend(_parse_user_rights_assignment(elem, scope))
            continue

        # ── Security Options (registry-backed security settings) ──────────────
        if tag == "SecurityOptions":
            items.extend(_parse_security_option(elem, scope))
            continue

        # ── Simple key/value settings (Account, Audit, Kerberos, etc.) ────────
        if tag not in {"Account", "Audit", "Kerberos", "EventLog", "Option",
                       "SystemAccess", "account", "audit"}:
            continue

        name_raw = (
            _child_text(elem, "Name")
            or _child_text(elem, "SettingName")
        )
        if not name_raw:
            continue

        label = _SECURITY_SETTING_LABELS.get(name_raw.lower(), name_raw)

        value_raw = (
            _child_text(elem, "SettingNumber")
            or _child_text(elem, "SettingString")
            or _child_text(elem, "Value")
            or _child_text(elem, "Setting")
        )
        if not value_raw:
            continue

        # Decode audit and boolean values
        name_key = name_raw.lower()
        if "audit" in name_key:
            decoded = _AUDIT_VALUE_LABELS.get(value_raw.strip(), value_raw)
        elif name_key in {"passwordcomplexity", "ticketvalidateclient",
                          "cleartextpassword", "enableadminaccount"}:
            decoded = _BOOL_VALUE_LABELS.get(value_raw.strip(), value_raw)
        else:
            decoded = value_raw

        category = _security_category_from_tag(tag)
        items.append(
            GpoReportPolicy(
                scope=scope,
                name=label,
                state="Configured",
                category=category,
                supported="",
                explain="",
                settings=[decoded],
                policy_type="Security Setting",
                source="gpreport.xml::Security",
                identity=_identity("security", scope, category, name_raw),
            )
        )

    return items


def _parse_user_rights_assignment(elem: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse a single <UserRightsAssignment> block from gpreport.xml.

    The gpreport.xml already contains resolved account names in <Member><Name>,
    so no SID lookup is needed here.
    """
    priv_name = _child_text(elem, "Name")
    if not priv_name:
        return []

    label = resolve_privilege_name(priv_name)

    members: list[str] = []
    for child in elem.iter():
        if _clean_tag(child.tag) == "Member":
            member_name = _child_text(child, "Name")
            if member_name and member_name not in members:
                members.append(member_name)

    value = ", ".join(members) if members else "(no accounts assigned)"

    return [GpoReportPolicy(
        scope=scope,
        name=label,
        state="Configured",
        category="Security Setting > User Rights Assignment",
        supported="",
        explain=priv_name,
        settings=[value],
        policy_type="Security Setting",
        source="gpreport.xml::Security",
        identity=_identity("security", scope, "user rights", priv_name),
    )]


def _parse_security_option(elem: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse a single <SecurityOptions> block from gpreport.xml.

    Structure:
        <SecurityOptions>
            <KeyName>MACHINE\\...\\EnableSecuritySignature</KeyName>
            <SettingNumber>1</SettingNumber>
            <Display>
                <Name>Microsoft network server: Digitally sign communications (if client agrees)</Name>
                <DisplayBoolean>true</DisplayBoolean>   ← or <DisplayString>
            </Display>
        </SecurityOptions>
    """
    key_name = _child_text(elem, "KeyName")
    setting_number = _child_text(elem, "SettingNumber")

    display_elem = _first_child(elem, "Display")
    if display_elem is not None:
        friendly_name = _child_text(display_elem, "Name")
        display_bool = _child_text(display_elem, "DisplayBoolean")
        display_str = _child_text(display_elem, "DisplayString")
    else:
        friendly_name = ""
        display_bool = ""
        display_str = ""

    if not friendly_name:
        # Fall back to the last segment of the registry key path
        friendly_name = key_name.split("\\")[-1] if key_name else ""
    if not friendly_name:
        return []

    if display_bool:
        value = "Enabled" if display_bool.strip().lower() in {"true", "1"} else "Disabled"
    elif display_str:
        value = display_str
    elif setting_number:
        value = setting_number
    else:
        value = "Configured"

    return [GpoReportPolicy(
        scope=scope,
        name=friendly_name,
        state="Configured",
        category="Security Setting > Security Options",
        supported="",
        explain=key_name,
        settings=[value],
        policy_type="Security Setting",
        source="gpreport.xml::Security",
        identity=_identity("security", scope, "security options", key_name or friendly_name),
    )]


def _parse_folder_redirection_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    items: list[GpoReportPolicy] = []

    for folder in _iter_local(extension, "Folder"):
        name = _child_text(folder, "Name") or _child_text(folder, "Id")
        target = _child_text(folder, "Location") or _child_text(folder, "DestinationPath")
        if not name:
            continue

        settings = []
        if target:
            settings.append(f"Target: {target}")
        for child in folder.iter():
            child_tag = _clean_tag(child.tag)
            if child_tag in {"Name", "Id", "Location", "DestinationPath"}:
                continue
            text = (child.text or "").strip()
            if text:
                settings.append(f"{child_tag}: {text}")

        items.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state="Configured",
                category="Folder Redirection",
                supported="",
                explain="",
                settings=_dedupe(settings),
                policy_type="Folder Redirection",
                source="gpreport.xml::Folder Redirection",
                identity=_identity("folderredir", scope, name),
            )
        )

    return items


def _parse_firewall_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    items: list[GpoReportPolicy] = []

    for rule in extension.iter():
        tag = _clean_tag(rule.tag).lower()
        if tag not in {"rule", "firewallrule", "firewall rule"}:
            continue

        name = _value_from(rule, "Name", "DisplayName", "RuleName", "name", "displayName")
        if not name:
            continue

        settings = []
        for label, keys in (
            ("Enabled", ("Enabled", "enabled")),
            ("Action", ("Action", "action")),
            ("Direction", ("Direction", "direction")),
            ("Profile", ("Profile", "Profiles", "profile", "profiles")),
            ("Protocol", ("Protocol", "protocol")),
            ("Local ports", ("LocalPorts", "LocalPort", "localPorts", "localPort")),
            ("Remote ports", ("RemotePorts", "RemotePort", "remotePorts", "remotePort")),
            ("Program", ("Program", "Application", "program", "application")),
            ("Service", ("Service", "service")),
            ("Local addresses", ("LocalAddresses", "localAddresses")),
            ("Remote addresses", ("RemoteAddresses", "remoteAddresses")),
        ):
            value = _value_from(rule, *keys)
            if value:
                settings.append(f"{label}: {value}")

        items.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state=_value_from(rule, "Enabled", "enabled") or "Configured",
                category="Firewall Rules",
                supported="",
                explain=_value_from(rule, "Description", "description"),
                settings=_dedupe(settings),
                policy_type="Firewall Rule",
                source="gpreport.xml::Firewall",
                identity=_identity("firewall", scope, name),
            )
        )

    return items


def _parse_generic_extension(
    extension: ET.Element,
    scope: str,
    ext_type: str,
) -> list[GpoReportPolicy]:
    """Best-effort extraction of name/value pairs from an unknown extension."""
    items: list[GpoReportPolicy] = []

    for elem in extension.iter():
        if elem is extension:
            continue

        name = (
            elem.attrib.get("name")
            or elem.attrib.get("Name")
            or _child_text(elem, "Name")
            or _child_text(elem, "Setting")
        )
        value = (
            _child_text(elem, "Value")
            or _child_text(elem, "SettingNumber")
            or _child_text(elem, "SettingString")
            or (elem.text or "").strip()
        )

        if not name or not value:
            continue

        category = f"Extension > {ext_type.title()}" if ext_type else "Extension"
        items.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state="Configured",
                category=category,
                supported="",
                explain="",
                settings=[value],
                policy_type="Extension",
                source=f"gpreport.xml::{ext_type.title() if ext_type else 'Extension'}",
                identity=_identity("ext", scope, ext_type, name),
            )
        )

    return items


def _parse_admx_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Extract Administrative Template policies from RegistrySettings / InternetSettings
    extension blocks.  These contain the same <Policy> structure as top-level policies
    but are delivered through ExtensionData for 3rd-party ADMX templates (Office, Chrome,
    custom templates, IE Maintenance, etc.)."""
    items: list[GpoReportPolicy] = []
    for policy in _iter_local(extension, "Policy"):
        name = _child_text(policy, "Name")
        if not name:
            continue
        category = _category_path(policy)
        items.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state=_child_text(policy, "State"),
                category=category,
                supported=_child_text(policy, "Supported"),
                explain=_child_text(policy, "Explain"),
                settings=_policy_settings(policy),
                policy_type="Administrative Template",
                source="gpreport.xml::Administrative Template",
                identity=_policy_identity(scope, "Administrative Template", policy, name, category),
            )
        )
    return items


def _parse_wlan_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse Wireless Network (802.11) Policy extension data."""
    items: list[GpoReportPolicy] = []
    for profile in extension.iter():
        tag = _clean_tag(profile.tag).lower()
        if tag not in {"wlanpolicies", "wlansvc"}:
            continue
        name = _child_text(profile, "name") or _child_text(profile, "Name")
        if not name:
            continue
        desc = _child_text(profile, "description") or _child_text(profile, "Description")
        settings: list[str] = []
        for flag_name, child_tag in (
            ("Auto-connect", "enableAutoConfig"),
            ("Show denied networks", "showDeniedNetwork"),
            ("Allow soft AP", "enableSoftAP"),
            ("Explicit credentials", "enableExplicitCreds"),
            ("GP profiles only", "onlyUseGPProfilesForAllowedNetworks"),
        ):
            val = _child_text(profile, child_tag)
            if val:
                settings.append(f"{flag_name}: {val}")
        # Count configured profiles
        profile_list = _first_child(profile, "profileList")
        if profile_list is not None:
            profile_count = sum(1 for c in profile_list if _clean_tag(c.tag) not in {"", "profileList"})
            if profile_count:
                settings.append(f"Profiles configured: {profile_count}")
        items.append(GpoReportPolicy(
            scope=scope,
            name=name,
            state="Configured",
            category="Wireless Network Policy",
            supported="",
            explain=desc,
            settings=_dedupe(settings),
            policy_type="Wireless Policy",
            source="gpreport.xml::WLanSvc",
            identity=_identity("wlan", scope, name),
        ))
    return items


def _parse_dot3_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse Wired Network (802.3 / 802.1X) Policy extension data."""
    items: list[GpoReportPolicy] = []
    for profile in extension.iter():
        tag = _clean_tag(profile.tag).lower()
        if tag not in {"lanpolicies", "dot3svc"}:
            continue
        name = _child_text(profile, "name") or _child_text(profile, "Name")
        if not name:
            continue
        desc = _child_text(profile, "description") or _child_text(profile, "Description")
        settings: list[str] = []
        for flag_name, child_tag in (
            ("Auto-connect", "enableAutoConfig"),
            ("Explicit credentials", "enableExplicitCreds"),
        ):
            val = _child_text(profile, child_tag)
            if val:
                settings.append(f"{flag_name}: {val}")
        # Check 802.1X enforcement
        for lan_profile in _iter_local(profile, "LANProfile"):
            onex = _child_text(lan_profile, "OneXEnforced")
            if onex:
                settings.append(f"802.1X enforced: {onex}")
        items.append(GpoReportPolicy(
            scope=scope,
            name=name,
            state="Configured",
            category="Wired Network Policy",
            supported="",
            explain=desc,
            settings=_dedupe(settings),
            policy_type="Wired Policy",
            source="gpreport.xml::Dot3Svc",
            identity=_identity("dot3", scope, name),
        ))
    return items


def _parse_public_key_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse Public Key / EFS / Certificate Trust extension data."""
    items: list[GpoReportPolicy] = []
    for elem in extension.iter():
        tag = _clean_tag(elem.tag)
        if tag == "EFSSettings":
            settings: list[str] = []
            efs_allow_map = {"0": "Disabled", "1": "Enabled", "2": "Not configured"}
            allow = _child_text(elem, "AllowEFS")
            if allow:
                settings.append(f"EFS: {efs_allow_map.get(allow, allow)}")
            key_len = _child_text(elem, "KeyLen")
            if key_len and key_len != "0":
                settings.append(f"Key length: {key_len} bits")
            if settings:
                items.append(GpoReportPolicy(
                    scope=scope,
                    name="Encrypting File System (EFS)",
                    state="Configured",
                    category="Public Key Policies > EFS",
                    supported="",
                    explain="",
                    settings=settings,
                    policy_type="Security Setting",
                    source="gpreport.xml::PublicKey",
                    identity=_identity("pubkey", scope, "efs"),
                ))
        elif tag == "RootCertificateSettings":
            settings = []
            for flag_name, child_tag in (
                ("Allow new CAs", "AllowNewCAs"),
                ("Trust third-party CAs", "TrustThirdPartyCAs"),
                ("Require UPN naming", "RequireUPNNamingConstraints"),
            ):
                val = _child_text(elem, child_tag)
                if val:
                    settings.append(f"{flag_name}: {val}")
            if settings:
                items.append(GpoReportPolicy(
                    scope=scope,
                    name="Root Certificate Settings",
                    state="Configured",
                    category="Public Key Policies > Certificate Trust",
                    supported="",
                    explain="",
                    settings=settings,
                    policy_type="Security Setting",
                    source="gpreport.xml::PublicKey",
                    identity=_identity("pubkey", scope, "root certs"),
                ))
    return items


def _parse_nrpt_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse DNS Name Resolution Policy Table (NRPT) extension data."""
    items: list[GpoReportPolicy] = []
    for rule in extension.iter():
        tag = _clean_tag(rule.tag)
        if tag != "Rule":
            continue
        namespace = _child_text(rule, "Namespace") or _child_text(rule, "Name")
        if not namespace:
            continue
        settings: list[str] = []
        for label, child_tag in (
            ("DNS servers", "DnsServers"),
            ("DirectAccess", "DirectAccessEnabled"),
            ("IPsec required", "IPsecCARestriction"),
            ("Cert validation", "DnssecEnabled"),
        ):
            val = _child_text(rule, child_tag)
            if val:
                settings.append(f"{label}: {val}")
        items.append(GpoReportPolicy(
            scope=scope,
            name=namespace,
            state="Configured",
            category="Network > DNS Name Resolution Policy",
            supported="",
            explain="",
            settings=settings,
            policy_type="NRPT Rule",
            source="gpreport.xml::NRPT",
            identity=_identity("nrpt", scope, namespace),
        ))
    return items


def _security_category_from_tag(tag: str) -> str:
    return {
        "account":      "Security Setting > Account Policy",
        "audit":        "Security Setting > Audit Policy",
        "kerberos":     "Security Setting > Kerberos Policy",
        "eventlog":     "Security Setting > Event Log",
        "option":       "Security Setting > Security Options",
        "systemaccess": "Security Setting > Account Policy",
    }.get(tag.lower(), "Security Setting")


_ADVANCED_AUDIT_VALUE_LABELS = {
    "0": "No auditing",
    "1": "Success",
    "2": "Failure",
    "3": "Success and Failure",
}


def _parse_audit_policy_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse the Advanced Audit Policy extension (100+ subcategories)."""
    items: list[GpoReportPolicy] = []

    for setting in _iter_local(extension, "AuditSetting"):
        name = (
            _child_text(setting, "SubcategoryName")
            or _child_text(setting, "CategoryName")
            or _child_text(setting, "Name")
        )
        if not name:
            continue

        value_raw  = _child_text(setting, "SettingValue") or _child_text(setting, "Value")
        guid       = _child_text(setting, "SubcategoryGuid") or _child_text(setting, "CategoryGuid")
        decoded    = _ADVANCED_AUDIT_VALUE_LABELS.get(value_raw.strip(), value_raw)

        items.append(
            GpoReportPolicy(
                scope=scope,
                name=name,
                state="Configured",
                category="Security Setting > Advanced Audit Policy",
                supported="",
                explain="",
                settings=[decoded] if decoded else [],
                policy_type="Security Setting",
                source="gpreport.xml::Advanced Audit Policy",
                identity=_identity("advaudit", scope, guid or name),
            )
        )

    return items


def _parse_applocker_extension(extension: ET.Element, scope: str) -> list[GpoReportPolicy]:
    """Parse AppLocker RuleCollection blocks from gpreport.xml ExtensionData."""
    items: list[GpoReportPolicy] = []

    for collection in _iter_local(extension, "RuleCollection"):
        rule_type   = collection.attrib.get("Type", "Unknown")
        enforcement = collection.attrib.get("EnforcementMode", "NotConfigured")
        category    = f"AppLocker > {rule_type}"

        # Enforcement mode entry
        items.append(
            GpoReportPolicy(
                scope=scope,
                name=f"{rule_type} Enforcement Mode",
                state="Configured",
                category=category,
                supported="",
                explain="",
                settings=[enforcement],
                policy_type="AppLocker",
                source="gpreport.xml::AppLocker",
                identity=_identity("applocker", scope, rule_type, "enforcement"),
            )
        )

        for rule in collection:
            rule_tag  = _clean_tag(rule.tag)
            if not rule_tag.endswith("Rule"):
                continue

            rule_name = rule.attrib.get("Name", "")
            rule_id   = rule.attrib.get("Id", "")
            action    = rule.attrib.get("Action", "Allow")
            sid       = rule.attrib.get("UserOrGroupSid", "")
            desc      = rule.attrib.get("Description", "").strip()

            settings: list[str] = [f"Action: {action}"]
            if sid:
                settings.append(f"Applies to: {sid}")

            for cond in rule.iter():
                cond_tag = _clean_tag(cond.tag)
                if cond_tag == "FilePublisherCondition":
                    pub    = cond.attrib.get("PublisherName", "*")
                    prod   = cond.attrib.get("ProductName", "*")
                    binary = cond.attrib.get("BinaryName", "*")
                    settings.append(f"Publisher: {pub}; Product: {prod}; File: {binary}")
                elif cond_tag == "FilePathCondition":
                    settings.append(f"Path: {cond.attrib.get('Path', '')}")
                elif cond_tag == "FileHashCondition":
                    settings.append("Condition: file hash")

            if desc:
                settings.append(f"Description: {desc}")

            if not rule_name:
                continue

            items.append(
                GpoReportPolicy(
                    scope=scope,
                    name=rule_name,
                    state="Configured",
                    category=category,
                    supported="",
                    explain=desc,
                    settings=_dedupe(settings),
                    policy_type="AppLocker",
                    source="gpreport.xml::AppLocker",
                    identity=_identity("applocker", scope, rule_type, rule_id or rule_name),
                )
            )

    return items
