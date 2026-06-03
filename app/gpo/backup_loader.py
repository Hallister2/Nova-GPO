from __future__ import annotations

"""GPO backup loader.

Collects all files in a backup folder in a single rglob pass and dispatches
them to the appropriate sub-parsers.  This avoids the multiple redundant
directory walks that the previous version performed.

Module-level configuration
--------------------------
Call ``configure(resolve_sids=True)`` once at application startup (e.g. in
main.py after loading settings) to enable SID resolution in security templates
and Registry.pol files without changing every call site.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.log import get_logger
from app.gpo.backup_catalog import read_display_name
from app.gpo.gpo_model import GpoBackup, GpoSetting
from app.gpo import ilt_parser
from app.gpo.registry_pol import load_registry_pol
from app.gpo.security_template import load_security_template

_log = get_logger(__name__)

# ── Module-level configuration ────────────────────────────────────────────────

_resolve_sids: bool = False


def configure(resolve_sids: bool = False) -> None:
    """Set loader-wide options.  Call once at startup from main.py."""
    global _resolve_sids
    _resolve_sids = resolve_sids
    _log.debug("backup_loader configured: resolve_sids=%s", resolve_sids)


# ── Public entry point ────────────────────────────────────────────────────────

def load_gpo_backup(folder_path: str) -> GpoBackup:
    root = Path(folder_path)

    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"GPO backup folder was not found: {folder_path}")

    # Single directory walk — split files by type for dispatch
    all_files = [p for p in root.rglob("*") if p.is_file()]

    xml_files:      list[Path] = []
    pref_xml_files: list[Path] = []
    ini_files:      list[Path] = []
    sec_tmpl_files: list[Path] = []
    pol_files:      list[Path] = []
    script_files:   list[Path] = []

    _SKIP_XML   = {"gpreport.xml", "backup.xml", "bkupinfo.xml", "manifest.xml"}
    _SCRIPT_EXT = {".ps1", ".bat", ".cmd", ".vbs", ".js"}

    applocker_files: list[Path] = []
    comment_files:   list[Path] = []

    for path in all_files:
        name_lower = path.name.lower()
        suffix     = path.suffix.lower()

        if name_lower == "gpo.cmt":
            comment_files.append(path)
            continue

        if name_lower == "comment.cmtx":
            comment_files.append(path)
            continue

        if suffix == ".xml":
            if name_lower in _SKIP_XML:
                continue
            if _is_applocker_xml(path):
                applocker_files.append(path)
            elif _is_preference_xml(path):
                pref_xml_files.append(path)
            else:
                xml_files.append(path)

        elif name_lower == "gpttmpl.inf":
            sec_tmpl_files.append(path)

        elif suffix in {".ini", ".inf"}:
            ini_files.append(path)

        elif name_lower == "registry.pol":
            pol_files.append(path)

        elif suffix in _SCRIPT_EXT:
            script_files.append(path)

    settings: list[GpoSetting] = []
    settings.extend(_load_backup_metadata(root))
    settings.extend(_load_comment_files(comment_files, root))
    settings.extend(_load_preference_xml(pref_xml_files, root))
    settings.extend(_load_xml(xml_files, root))
    settings.extend(_load_applocker(applocker_files, root))
    settings.extend(_load_security_templates(sec_tmpl_files, root))
    settings.extend(_load_ini_like(ini_files, root))
    settings.extend(_load_registry_pol(pol_files, root))
    settings.extend(_load_scripts(script_files, root))

    # Detect which parser types were present (no extra rglob needed)
    detected: list[str] = []
    if pol_files:
        detected.append("Registry Policy Parser")
    if pref_xml_files:
        detected.append("Group Policy Preferences Parser")
    if sec_tmpl_files:
        detected.append("Security Settings Parser")
    if applocker_files:
        detected.append("AppLocker Parser")
    if script_files:
        detected.append("Scripts Parser")

    backup_name = read_display_name(root)
    _log.debug(
        "Loaded backup '%s': %d settings, parsers: %s",
        backup_name, len(settings), tuple(detected),
    )
    return GpoBackup(
        path=str(root),
        name=backup_name,
        settings=settings,
        detected_parsers=tuple(detected),
    )


# ── Sub-parsers ───────────────────────────────────────────────────────────────

def _load_comment_files(files: list[Path], root: Path) -> list[GpoSetting]:
    """Parse GPO.cmt (free-text admin comment) and comment.cmtx (per-policy change notes)."""
    items: list[GpoSetting] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        name_lower = path.name.lower()

        if name_lower == "gpo.cmt":
            try:
                text = _read_text_with_fallback(path).strip()
            except OSError:
                continue
            if text:
                items.append(GpoSetting(
                    key=f"comment::gpo.cmt::comment",
                    category="Backup Metadata",
                    name="GPO Comment",
                    value=text,
                    source_file=relative,
                ))

        elif name_lower == "comment.cmtx":
            # XML format: policyComments > comments > admTemplate > comment[@policyRef]
            # resolved via resources > stringTable > string[@id]
            try:
                data = path.read_bytes()
                tree: ET.Element | None = None
                for enc in ("utf-8-sig", "utf-8", "utf-16"):
                    try:
                        tree = ET.fromstring(data.decode(enc))
                        break
                    except (UnicodeError, ET.ParseError):
                        continue
                if tree is None:
                    continue
            except OSError:
                continue

            # Build id→text lookup from <stringTable>
            string_map: dict[str, str] = {}
            for string_elem in tree.iter():
                if string_elem.tag.split("}")[-1] == "string":
                    sid = string_elem.get("id", "").strip()
                    text = (string_elem.text or "").strip()
                    if sid and text:
                        string_map[sid] = text

            # Emit one setting per comment with resolved text
            for comment_elem in tree.iter():
                if comment_elem.tag.split("}")[-1] != "comment":
                    continue
                policy_ref = comment_elem.get("policyRef", "").strip()
                raw_text   = comment_elem.get("commentText", "").strip()
                # Resolve $(resource.id) tokens
                if raw_text.startswith("$(resource.") and raw_text.endswith(")"):
                    res_id = raw_text[len("$(resource."):-1]
                    resolved = string_map.get(res_id, raw_text)
                else:
                    resolved = raw_text or string_map.get(policy_ref, "")

                if not resolved:
                    continue

                display_name = policy_ref.split(":")[-1] if ":" in policy_ref else policy_ref
                items.append(GpoSetting(
                    key=f"comment::cmtx::{policy_ref}".lower(),
                    category="Policy Comments",
                    name=display_name,
                    value=resolved,
                    source_file=relative,
                ))

    return items


def _load_preference_xml(files: list[Path], root: Path) -> list[GpoSetting]:
    items: list[GpoSetting] = []
    for xml_path in files:
        try:
            tree = ET.parse(xml_path)
            xml_root = tree.getroot()
        except ET.ParseError as exc:
            _log.warning("XML parse error in preference file %s: %s", xml_path, exc)
            continue

        relative = xml_path.relative_to(root).as_posix()
        for element in xml_root.iter():
            if element is xml_root or not _looks_like_preference_item(element):
                continue

            pref_type = _preference_type(_clean_tag(element.tag), relative)
            name      = _preference_name(element, pref_type)
            identity  = _preference_identity(element, relative, name, pref_type)
            values    = _preference_values(element, pref_type)

            if not values:
                continue

            items.append(
                GpoSetting(
                    key=f"preference::{relative}::{pref_type}::{identity}".lower(),
                    category=f"Group Policy Preferences > {pref_type}",
                    name=name,
                    value="; ".join(values),
                    source_file=relative,
                )
            )
    return items


def _load_xml(files: list[Path], root: Path) -> list[GpoSetting]:
    items: list[GpoSetting] = []
    for xml_path in files:
        try:
            tree = ET.parse(xml_path)
            xml_root = tree.getroot()
        except ET.ParseError as exc:
            _log.warning("XML parse error in %s: %s", xml_path, exc)
            continue

        relative = xml_path.relative_to(root).as_posix()
        occurrences: dict[str, int] = {}

        for element_path, element in _iter_xml_elements(xml_root):
            tag  = _clean_tag(element.tag)
            text = (element.text or "").strip()
            values = _xml_values(element, text)
            if not values:
                continue

            base_key = f"xml::{relative}::{element_path}"
            occurrences[base_key] = occurrences.get(base_key, 0) + 1
            n   = occurrences[base_key]
            key = base_key if n == 1 else f"{base_key}::{n}"

            items.append(
                GpoSetting(
                    key=key.lower(),
                    category="XML Raw",
                    name=tag,
                    value="; ".join(values),
                    source_file=relative,
                )
            )
    return items


def _load_security_templates(files: list[Path], root: Path) -> list[GpoSetting]:
    """Route GptTmpl.inf files to the section-aware security template parser."""
    items: list[GpoSetting] = []
    for path in files:
        items.extend(load_security_template(path, root, resolve_sids=_resolve_sids))
    return items


def _read_text_with_fallback(path: Path) -> str:
    """Read a text file trying UTF-16, UTF-8-BOM, UTF-8, then replace-on-error."""
    data = path.read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _load_ini_like(files: list[Path], root: Path) -> list[GpoSetting]:
    """Parse generic .ini / .inf files (GptTmpl.inf is handled separately)."""
    items: list[GpoSetting] = []
    for path in files:
        try:
            lines = _read_text_with_fallback(path).splitlines()
        except OSError:
            continue

        section = "General"
        for line in lines:
            clean = line.strip()
            if not clean or clean.startswith(";") or clean.startswith("#"):
                continue
            if clean.startswith("[") and clean.endswith("]"):
                section = clean.strip("[]")
                continue
            if "=" not in clean:
                continue

            name, _, value = clean.partition("=")
            name  = name.strip()
            value = value.strip()
            relative = path.relative_to(root).as_posix()

            items.append(
                GpoSetting(
                    key=f"ini::{relative}::{section}::{name}".lower(),
                    category=f"{_ini_file_type(path)} > {section}",
                    name=name,
                    value=value,
                    source_file=relative,
                )
            )
    return items


def _load_registry_pol(files: list[Path], root: Path) -> list[GpoSetting]:
    items: list[GpoSetting] = []
    for pol_path in files:
        items.extend(load_registry_pol(pol_path, root, resolve_sids=_resolve_sids))
    return items


def _load_scripts(files: list[Path], root: Path) -> list[GpoSetting]:
    items: list[GpoSetting] = []
    for script_path in files:
        relative = script_path.relative_to(root).as_posix()
        try:
            text = _read_text_with_fallback(script_path)
        except OSError:
            text = ""

        preview = " ".join(line.strip() for line in text.splitlines() if line.strip())[:500]
        scope   = _script_scope(script_path)
        value   = f"{scope} {script_path.suffix.lower()[1:].upper()} script"
        if preview:
            value = f"{value}; Preview: {preview}"

        items.append(
            GpoSetting(
                key=f"script::{relative}".lower(),
                category=f"Scripts > {scope}",
                name=script_path.name,
                value=value,
                source_file=relative,
            )
        )
    return items


def _is_applocker_xml(path: Path) -> bool:
    return "applocker" in path.as_posix().lower()


def _load_applocker(files: list[Path], root: Path) -> list[GpoSetting]:
    """Parse AppLocker policy XML files extracted from GPO backups."""
    items: list[GpoSetting] = []
    for xml_path in files:
        try:
            tree = ET.parse(xml_path)
            xml_root = tree.getroot()
        except ET.ParseError as exc:
            _log.warning("XML parse error in AppLocker file %s: %s", xml_path, exc)
            continue

        root_tag = _clean_tag(xml_root.tag).lower()
        if root_tag not in {"applockerpolicy", "policyapplocker"}:
            # Not actually AppLocker — hand off to generic XML
            items.extend(_load_xml([xml_path], root))
            continue

        relative = xml_path.relative_to(root).as_posix()

        for collection in xml_root.iter():
            if _clean_tag(collection.tag) != "RuleCollection":
                continue

            rule_type   = collection.attrib.get("Type", "Unknown")
            enforcement = collection.attrib.get("EnforcementMode", "NotConfigured")
            category    = f"AppLocker > {rule_type}"

            items.append(GpoSetting(
                key=f"applocker::{relative}::{rule_type}::enforcement".lower(),
                category=category,
                name=f"{rule_type} Enforcement Mode",
                value=enforcement,
                source_file=relative,
            ))

            for rule in collection:
                rule_tag  = _clean_tag(rule.tag)
                if not rule_tag.endswith("Rule"):
                    continue

                rule_name  = rule.attrib.get("Name", "Unnamed Rule")
                rule_id    = rule.attrib.get("Id", "")
                action     = rule.attrib.get("Action", "Allow")
                sid        = rule.attrib.get("UserOrGroupSid", "")
                desc       = rule.attrib.get("Description", "").strip()

                value_parts = [f"Action: {action}"]
                if sid:
                    value_parts.append(f"Applies to: {sid}")

                for cond in rule.iter():
                    cond_tag = _clean_tag(cond.tag)
                    if cond_tag == "FilePublisherCondition":
                        pub    = cond.attrib.get("PublisherName", "*")
                        prod   = cond.attrib.get("ProductName", "*")
                        binary = cond.attrib.get("BinaryName", "*")
                        value_parts.append(f"Publisher: {pub}; Product: {prod}; File: {binary}")
                    elif cond_tag == "FilePathCondition":
                        value_parts.append(f"Path: {cond.attrib.get('Path', '')}")
                    elif cond_tag == "FileHashCondition":
                        value_parts.append("Condition: file hash")

                if desc:
                    value_parts.append(f"Description: {desc}")

                items.append(GpoSetting(
                    key=f"applocker::{relative}::{rule_type}::{rule_id or rule_name}".lower(),
                    category=category,
                    name=rule_name,
                    value="; ".join(value_parts),
                    source_file=relative,
                ))

    return items


# ── XML helpers ───────────────────────────────────────────────────────────────

def _clean_tag(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _iter_xml_elements(root: ET.Element) -> list[tuple[str, ET.Element]]:
    items: list[tuple[str, ET.Element]] = []

    def walk(element: ET.Element, path: str) -> None:
        clean = _clean_tag(element.tag)
        element_path = f"{path}/{clean}" if path else clean
        items.append((element_path, element))
        for child in element:
            walk(child, element_path)

    walk(root, "")
    return items


def _xml_values(element: ET.Element, text: str) -> list[str]:
    values: list[str] = []
    if text:
        values.append(text)
    for key, value in sorted(element.attrib.items()):
        clean_value = value.strip()
        if clean_value:
            values.append(f"{key}={clean_value}")
    return values


def _is_preference_xml(path: Path) -> bool:
    return "preferences" in [part.lower() for part in path.parts]


def _looks_like_preference_item(element: ET.Element) -> bool:
    tag = _clean_tag(element.tag)
    if tag in {"Properties", "Filters", "FilterCollection", "Values", "Member", "Members"}:
        return False
    if element.attrib.get("name") or element.attrib.get("uid"):
        return True
    return _first_child(element, "Properties") is not None


def _first_child(parent: ET.Element, tag_name: str) -> ET.Element | None:
    for child in parent:
        if _clean_tag(child.tag) == tag_name:
            return child
    return None


# ── Preference helpers (unchanged from original) ──────────────────────────────

def _preference_type(tag: str, relative_path: str) -> str:
    path = relative_path.lower()
    # More-specific path checks must come before generic ones that share substrings
    if "folderoptions"    in path: return "Folder Options"
    if "poweroptions"     in path: return "Power Option"
    if "networkoptions"   in path: return "Network Option"
    if "networkshares"    in path: return "Network Share"
    if "regionaloptions"  in path: return "Regional Options"
    if "startmenutaskbar" in path: return "Start Menu/Taskbar"
    if "devices"          in path: return "Device"
    if "scheduledtasks"   in path: return "Scheduled Task"
    if "drives"           in path: return "Drive Map"
    if "registry"         in path: return "Registry"
    if "folders"          in path: return "Folder"
    if "files"            in path: return "File"
    if "shortcuts"        in path: return "Shortcut"
    if "environment"      in path: return "Environment Variable"
    if "printers"         in path: return "Printer"
    if "groups"           in path: return "Local User/Group"
    if "services"         in path: return "Service"
    if "internetsettings" in path: return "Internet Settings"

    return {
        "Drive": "Drive Map", "DriveMap": "Drive Map",
        "ScheduledTask": "Scheduled Task", "ScheduledTaskV2": "Scheduled Task",
        "ImmediateTask": "Scheduled Task", "ImmediateTaskV2": "Scheduled Task",
        "Task": "Scheduled Task", "TaskV2": "Scheduled Task",
        "Registry": "Registry", "Folder": "Folder", "File": "File",
        "Shortcut": "Shortcut", "EnvironmentVariable": "Environment Variable",
        "Printer": "Printer", "SharedPrinter": "Printer", "PortPrinter": "Printer",
        "TcpipPrinter": "Printer", "LocalPrinter": "Printer",
        "Group": "Local User/Group", "User": "Local User/Group",
        "LocalGroup": "Local User/Group", "LocalUser": "Local User/Group",
        "Service": "Service", "Services": "Service",
        "IniFile": "INI File", "Ini": "INI File",
        "DataSource": "Data Source",
        "InternetSettings": "Internet Settings",
        # New types
        "PowerOption": "Power Option", "Power": "Power Option",
        "NetShare": "Network Share", "NetworkShare": "Network Share",
        "NetOption": "Network Option", "VpnOption": "Network Option",
        "DialupOption": "Network Option",
        "Device": "Device",
        "UserLocale": "Regional Options", "SystemLocale": "Regional Options",
        "InputLocale": "Regional Options", "RegionalOptions": "Regional Options",
        "FolderOptions": "Folder Options", "OpenWith": "Folder Options",
        "StartMenuTaskbar": "Start Menu/Taskbar",
    }.get(tag, tag)


def _preference_name(element: ET.Element, pref_type: str) -> str:
    properties = _first_child(element, "Properties")
    attrs = properties.attrib if properties is not None else {}

    if pref_type == "Registry":
        return (attrs.get("name", "").strip()
                or element.attrib.get("name", "").strip()
                or _last_path_part(attrs.get("key", ""))
                or "Registry Preference")
    if pref_type == "Shortcut":
        return (element.attrib.get("name", "").strip()
                or attrs.get("shortcutPath", "").strip()
                or attrs.get("targetPath", "").strip()
                or "Shortcut Preference")
    if pref_type == "Folder":
        return attrs.get("path", "").strip() or element.attrib.get("name", "").strip() or "Folder Preference"
    if pref_type == "File":
        return (attrs.get("targetPath", "").strip()
                or attrs.get("fromPath", "").strip()
                or element.attrib.get("name", "").strip()
                or "File Preference")
    if pref_type == "Drive Map":
        return attrs.get("letter", "").strip() or attrs.get("useLetter", "").strip() or attrs.get("location", "").strip() or "Drive Map"
    if pref_type == "Printer":
        return element.attrib.get("name", "").strip() or attrs.get("localName", "").strip() or attrs.get("printerName", "").strip() or attrs.get("path", "").strip() or "Printer Preference"
    if pref_type == "Service":
        return attrs.get("serviceName", "").strip() or attrs.get("displayName", "").strip() or element.attrib.get("name", "").strip() or "Service Preference"
    if pref_type == "Local User/Group":
        return attrs.get("groupName", "").strip() or attrs.get("userName", "").strip() or element.attrib.get("name", "").strip() or "Local User/Group Preference"
    if pref_type == "Scheduled Task":
        return attrs.get("name", "").strip() or attrs.get("taskName", "").strip() or element.attrib.get("name", "").strip() or "Scheduled Task"
    if pref_type == "Device":
        return (attrs.get("class", "").strip()
                or attrs.get("instance", "").strip()
                or element.attrib.get("name", "").strip()
                or "Device Policy")
    if pref_type == "Regional Options":
        return (attrs.get("locale", attrs.get("userLocale", attrs.get("systemLocale", ""))).strip()
                or element.attrib.get("name", "").strip()
                or "Regional Settings")
    if pref_type == "Network Share":
        return attrs.get("name", "").strip() or attrs.get("path", "").strip() or element.attrib.get("name", "").strip() or "Network Share"
    return (element.attrib.get("name", "").strip()
            or attrs.get("name", "").strip()
            or attrs.get("path", "").strip()
            or attrs.get("targetPath", "").strip()
            or attrs.get("key", "").strip()
            or pref_type)


def _preference_identity(element: ET.Element, relative: str, name: str, pref_type: str) -> str:
    properties = _first_child(element, "Properties")
    attrs = properties.attrib if properties is not None else {}
    parts = [
        attrs.get(k, "")
        for k in (
            "hive", "key", "name", "path", "targetPath", "location",
            "letter", "useLetter", "serviceName", "groupName", "userName",
            "printerName", "localName", "taskName",
        )
    ]
    parts.append(name)
    identity = "::".join(p.strip().lower() for p in parts if p.strip())
    return identity or element.attrib.get("uid", "").strip().lower() or f"{relative}::{pref_type}"


def _preference_values(element: ET.Element, pref_type: str | None = None) -> list[str]:
    values: list[str] = []
    pref_type  = pref_type or _preference_type(_clean_tag(element.tag), "")
    properties = _first_child(element, "Properties")
    attrs      = properties.attrib if properties is not None else {}

    action = _preference_action(attrs.get("action", "") or element.attrib.get("action", ""))
    if action:
        values.append(f"Action: {action}")

    if pref_type == "Registry":
        path = _registry_value_path(attrs)
        if path:
            values.append(f"Registry value: {path}")
        if attrs.get("type", "").strip():
            values.append(f"Type: {attrs['type'].strip()}")
        if attrs.get("value", "").strip():
            values.append(f"Data: {attrs['value'].strip()}")
    elif pref_type == "Shortcut":
        for label, key in (("Shortcut","shortcutPath"),("Target","targetPath"),
                           ("Arguments","arguments"),("Start in","startIn")):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type in {"Folder", "File"}:
        for label, key in (
            ("Path","path"),("Source","fromPath"),("Target","targetPath"),
            ("Archive","archive"),("Suppress errors","suppress"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "Drive Map":
        for label, key in (
            ("Drive letter", "letter"), ("Drive letter", "useLetter"),
            ("Location", "location"), ("Label", "label"),
            ("Reconnect", "persistent"), ("Hide/show this drive", "thisDrive"),
            ("Hide/show all drives", "allDrives"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "Printer":
        for label, key in (
            ("Shared path", "path"), ("Local name", "localName"),
            ("Printer name", "printerName"), ("Port", "portName"),
            ("IP address", "ipAddress"), ("Location", "location"),
            ("Default printer", "default"), ("Delete all", "deleteAll"),
            ("Skip local", "skipLocal"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "Environment Variable":
        for label, key in (("Name","name"),("Value","value"),("User variable","user")):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "Scheduled Task":
        for label, key in (
            ("Task name", "name"), ("Task name", "taskName"),
            ("Run as", "runAs"), ("Logon type", "logonType"),
            ("Command", "appName"), ("Arguments", "args"),
            ("Start in", "startIn"), ("Enabled", "enabled"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
        # Dig into Task/Triggers and Task/Actions children
        for child in element.iter():
            child_tag = _clean_tag(child.tag)
            if child_tag in {"CalendarTrigger", "EventTrigger", "LogonTrigger",
                             "BootTrigger", "IdleTrigger", "TimeTrigger"}:
                trigger_label = child_tag.replace("Trigger", " Trigger")
                start = (child.find("StartBoundary") or child.find("*/StartBoundary") or None)
                start_text = (start.text or "").strip() if start is not None else ""
                values.append(f"Trigger: {trigger_label}" + (f" ({start_text})" if start_text else ""))
            elif child_tag == "Exec":
                cmd  = next((c.text or "" for c in child if _clean_tag(c.tag) == "Command"), "").strip()
                args = next((c.text or "" for c in child if _clean_tag(c.tag) == "Arguments"), "").strip()
                if cmd:
                    values.append(f"Command: {cmd}" + (f" {args}" if args else ""))
            elif child_tag == "Enabled" and child.text:
                values.append(f"Enabled: {child.text.strip()}")
    elif pref_type == "Local User/Group":
        for label, key in (
            ("Group", "groupName"), ("User", "userName"), ("New name", "newName"),
            ("Full name", "fullName"), ("Description", "description"),
            ("Password never expires", "acctExpires"), ("User cannot change password", "userCannotChangePassword"),
            ("Account disabled", "disabled"), ("Delete all users", "deleteAllUsers"),
            ("Delete all groups", "deleteAllGroups"), ("Remove accounts", "removeAccounts"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
        values.extend(_preference_member_values(element))
    elif pref_type == "Service":
        for label, key in (
            ("Service name", "serviceName"), ("Display name", "displayName"),
            ("Startup type", "startupType"), ("Service action", "serviceAction"),
            ("Account", "accountName"), ("Timeout", "timeout"),
            ("First failure", "firstFailure"), ("Second failure", "secondFailure"),
            ("Subsequent failures", "thirdFailure"), ("Reset fail count after", "resetFailCountDelay"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "INI File":
        for label, key in (("Path", "path"), ("Section", "section"), ("Property", "property"), ("Value", "value")):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "Data Source":
        for label, key in (("DSN", "dsn"), ("Driver", "driver"), ("Server", "server"), ("Database", "database")):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
    elif pref_type == "Internet Settings":
        _INET_LABELS = {
            "proxyEnable":      "Proxy enabled",
            "proxyServer":      "Proxy server",
            "proxyOverride":    "Bypass proxy for",
            "autoConfigURL":    "Auto-config URL",
            "enableAutoDetect": "Auto-detect settings",
            "autoconfigurl":    "Auto-config URL",
        }
        labeled_keys: set[str] = set()
        for attr_key, label in _INET_LABELS.items():
            val = attrs.get(attr_key, "").strip()
            if val:
                values.append(f"{label}: {val}")
                labeled_keys.add(attr_key.lower())
        # Emit remaining significant attributes under their raw names
        for k, v in sorted(attrs.items()):
            if k.lower() not in labeled_keys:
                v = v.strip()
                if v and k not in {"changed", "clsid", "disabled", "image", "name", "status", "uid"}:
                    values.append(f"{_labelize(k)}: {v}")
    elif pref_type == "Power Option":
        for label, key in (
            ("Plan name", "name"), ("Plan GUID", "planGuid"),
            ("Setting GUID", "settingGuid"),
            ("AC value", "valueACIndex"), ("DC value", "valueDCIndex"),
        ):
            val = attrs.get(key, element.attrib.get(key, "")).strip()
            if val:
                values.append(f"{label}: {val}")
        values.extend(_important_preference_attributes(attrs))

    elif pref_type == "Network Share":
        for label, key in (
            ("Share name", "name"), ("Path", "path"), ("Comment", "comment"),
            ("Share type", "type"), ("Max users", "limitUsersCount"),
            ("Access-based enumeration", "abe"), ("Caching", "caching"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")

    elif pref_type == "Network Option":
        for label, key in (
            ("Connection name", "name"), ("Phone/hostname", "phonenumber"),
            ("Dial-up type", "type"), ("Dial automatically", "dialAutomatic"),
            ("Use default gateway", "useDefaultGateway"),
            ("Idle disconnect", "idleDisconnect"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
        values.extend(_important_preference_attributes(attrs))

    elif pref_type == "Device":
        for label, key in (
            ("Device class", "class"), ("Class GUID", "classGuid"),
            ("Instance ID", "instance"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
        dev_action = attrs.get("deviceAction", "").strip()
        if dev_action:
            values.append(f"Device action: {dev_action}")

    elif pref_type == "Regional Options":
        for label, key in (
            ("User locale", "locale"), ("System locale", "systemLocale"),
            ("UI language", "language"), ("Input locale", "inputLocale"),
            ("Timezone", "timeZoneName"), ("Timezone index", "timeZoneIndex"),
            ("Long date format", "sLongDate"), ("Short date format", "sShortDate"),
            ("Time format", "sTimeFormat"),
            ("Currency symbol", "sCurrency"),
            ("Decimal symbol", "sDecimal"), ("Thousands separator", "sThousand"),
        ):
            if attrs.get(key, "").strip():
                values.append(f"{label}: {attrs[key].strip()}")
        values.extend(_important_preference_attributes(attrs))

    elif pref_type == "Folder Options":
        _FOLDER_LABELS = {
            "showHidden": "Show hidden files",
            "showSuperHidden": "Show protected OS files",
            "hideExtensions": "Hide known file extensions",
            "hideFullPath": "Hide full path in title bar",
            "webViewInFolders": "Web view in folders",
            "openEachFolderInSameWindow": "Open folders in same window",
            "openEachFolderInOwnWindow": "Open each folder in own window",
            "rememberFolderSettings": "Remember folder settings",
            "simpleNetView": "Simple network view",
            "showEncryptedCompressed": "Show encrypted/compressed files in color",
            "useCheckBoxes": "Use check boxes to select items",
        }
        for attr_key, label in _FOLDER_LABELS.items():
            if attrs.get(attr_key, "").strip():
                values.append(f"{label}: {attrs[attr_key].strip()}")
        values.extend(_important_preference_attributes(attrs))

    elif pref_type == "Start Menu/Taskbar":
        _START_LABELS = {
            "lockTaskbar": "Lock taskbar",
            "taskbarSizeAuto": "Auto-hide taskbar",
            "showQuickLaunch": "Show Quick Launch bar",
            "startMenuLogoff": "Show Log Off in Start menu",
            "showRun": "Show Run command",
            "showHelp": "Show Help and Support",
            "showSearch": "Show Search",
            "showAllPrograms": "Always show All Programs",
            "noPinnedPrograms": "No pinned programs list",
        }
        for attr_key, label in _START_LABELS.items():
            if attrs.get(attr_key, "").strip():
                values.append(f"{label}: {attrs[attr_key].strip()}")
        values.extend(_important_preference_attributes(attrs))

    elif pref_type in {"Service", "Local User/Group"}:
        values.extend(_important_preference_attributes(attrs))

    for key, value in sorted(element.attrib.items()):
        if key in {"changed", "clsid", "disabled", "image", "name", "status", "uid"}:
            continue
        if value.strip():
            values.append(f"{key}: {value.strip()}")

    if properties is not None and not values:
        values.extend(_important_preference_attributes(properties.attrib))

    filters = _first_child(element, "Filters")
    values.extend(ilt_parser.format_filters(filters))

    return _dedupe(values)


def _preference_member_values(element: ET.Element) -> list[str]:
    values: list[str] = []
    for child in element.iter():
        tag = _clean_tag(child.tag)
        if tag not in {"Member", "Members"}:
            continue
        attrs = child.attrib
        name = attrs.get("name", "").strip() or attrs.get("sid", "").strip()
        action = _preference_action(attrs.get("action", "").strip())
        if not name:
            continue
        values.append(f"Member: {name}" + (f" ({action})" if action else ""))
    return values


def _important_preference_attributes(attrs: dict[str, str]) -> list[str]:
    ignored = {"changed","clsid","default","disabled","displayDecimal","image","name","status","uid"}
    return [
        f"{_labelize(k)}: {v.strip()}"
        for k, v in sorted(attrs.items())
        if k not in ignored and v.strip()
    ]


def _registry_value_path(attrs: dict[str, str]) -> str:
    parts = [attrs.get(k, "").strip() for k in ("hive", "key", "name")]
    return "\\".join(p for p in parts if p)


def _preference_action(value: str) -> str:
    return {"C": "Create", "U": "Update", "R": "Replace", "D": "Delete"}.get(
        value.strip().upper(), value.strip()
    )


def _labelize(value: str) -> str:
    label = ""
    for i, char in enumerate(value):
        if i and char.isupper() and value[i - 1].islower():
            label += " "
        label += char
    return label[:1].upper() + label[1:]


def _last_path_part(value: str) -> str:
    clean = value.strip().rstrip("\\/")
    if not clean:
        return ""
    return clean.replace("/", "\\").split("\\")[-1]


def _ini_file_type(path: Path) -> str:
    if path.suffix.lower() == ".inf":
        return "Security Template"
    if "fdeploy" in path.name.lower():
        return "Folder Redirection"
    return "Policy Text"


def _load_backup_metadata(root: Path) -> list[GpoSetting]:
    """Parse Backup.xml and manifest.xml for GPO identity and link metadata."""
    items: list[GpoSetting] = []
    for candidate in root.iterdir():
        if not candidate.is_file():
            continue
        name = candidate.name.lower()
        if name == "backup.xml":
            items.extend(_parse_backup_xml(candidate, root))
        elif name == "manifest.xml":
            items.extend(_parse_manifest_xml(candidate, root))
    return items


def _get_xml_text(xml_root: ET.Element, tag: str) -> str:
    for elem in xml_root.iter():
        if _clean_tag(elem.tag) == tag:
            return (elem.text or "").strip()
    return ""


def _parse_backup_xml(path: Path, root: Path) -> list[GpoSetting]:
    try:
        xml_root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    relative = path.relative_to(root).as_posix()
    fields = [
        ("GPO GUID",   _get_xml_text(xml_root, "GPOGuid")),
        ("GPO domain", _get_xml_text(xml_root, "GPODomain")),
        ("Comment",    _get_xml_text(xml_root, "Comment")),
    ]
    return [
        GpoSetting(
            key=f"metadata::backup.xml::{label.lower().replace(' ', '_')}",
            category="Backup Metadata",
            name=label,
            value=value,
            source_file=relative,
        )
        for label, value in fields
        if value
    ]


def _parse_manifest_xml(path: Path, root: Path) -> list[GpoSetting]:
    try:
        xml_root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    relative = path.relative_to(root).as_posix()
    items: list[GpoSetting] = []

    links: list[str] = []
    for elem in xml_root.iter():
        if _clean_tag(elem.tag) == "Link":
            som_path = elem.attrib.get("SOMPath", "").strip()
            som_type = elem.attrib.get("SOMType", "").strip()
            enabled  = elem.attrib.get("Enabled", "1").strip()
            if som_path:
                text = som_path
                if som_type:
                    text += f" ({som_type})"
                if enabled in ("0", "false"):
                    text += " [link disabled]"
                links.append(text)

    if links:
        items.append(GpoSetting(
            key="metadata::manifest.xml::gpo_links",
            category="Backup Metadata",
            name="GPO Links",
            value="; ".join(links),
            source_file=relative,
        ))

    return items


def _script_scope(path: Path) -> str:
    normalized = path.as_posix().lower()
    if "startup"  in normalized: return "Startup"
    if "shutdown" in normalized: return "Shutdown"
    if "logon"    in normalized: return "Logon"
    if "logoff"   in normalized: return "Logoff"
    if "/user/"    in f"/{normalized}/": return "User"
    if "/machine/" in f"/{normalized}/": return "Computer"
    return "Inventory"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            results.append(item)
    return results
