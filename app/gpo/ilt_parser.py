"""
Translates GPP Item-Level Targeting (ILT) <Filters> XML into human-readable text.

Each preference item in a GPO Preferences XML can have a <Filters> child that
holds one or more targeting rules (FilterOs, FilterGroup, FilterIpRange, etc.).
This module converts those rules into plain-English strings suitable for display
and diffing.

Usage:
    from app.gpo import ilt_parser

    filters_elem = element.find("Filters")
    lines = ilt_parser.format_filters(filters_elem)   # list[str] or []
    present = ilt_parser.has_targeting(filters_elem)  # bool
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

# Sentinels that separate preference sections in a settings list. Consumers can
# split on these strings to render properties, common options, and ILT cleanly.
GPP_PROPERTIES_HEADER = "── Properties ──"
GPP_COMMON_HEADER = "── Common Options ──"
ILT_HEADER = "── Item-Level Targeting ──"

# Windows NT version → friendly OS name used in FilterOsRange
_OS_VERSIONS: dict[str, str] = {
    "5.0": "Windows 2000",
    "5.1": "Windows XP",
    "5.2": "Windows Server 2003",
    "6.0": "Windows Vista / Server 2008",
    "6.1": "Windows 7 / Server 2008 R2",
    "6.2": "Windows 8 / Server 2012",
    "6.3": "Windows 8.1 / Server 2012 R2",
    "10.0": "Windows 10 / Server 2016+",
}

_NON_TARGETING_FILTER_TAGS = {
    "FilterDataAvailable",
    "FilterDescription",
    "FilterName",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _clean_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _is_neg(attrs: dict[str, str]) -> bool:
    return attrs.get("not", "0") == "1"


def _is_targeting_filter_tag(tag: str) -> bool:
    return tag.startswith("Filter") and tag not in _NON_TARGETING_FILTER_TAGS and tag not in {"Filters", "FilterCollection"}


def _neg(attrs: dict[str, str]) -> str:
    return "NOT " if _is_neg(attrs) else ""


def _os_name(version: str) -> str:
    """Map a version string (e.g. '6.1', '6.1.0.0') to a friendly OS name."""
    v = version.strip()
    if v in _OS_VERSIONS:
        return _OS_VERSIONS[v]
    parts = v.split(".")
    short = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else v
    return _OS_VERSIONS.get(short, v)


# ── per-type translators ──────────────────────────────────────────────────────

def _describe(tag: str, attrs: dict[str, str]) -> str:
    """Return a single human-readable line for one ILT filter element."""
    neg = _neg(attrs)

    if tag == "FilterOs":
        name = attrs.get("name", "").strip()
        return f"{neg}OS: {name}" if name else f"{neg}OS filter"

    if tag == "FilterOsRange":
        lo = attrs.get("lowerVersion", "").strip()
        hi = attrs.get("upperVersion", "").strip()
        lo_name = _os_name(lo) if lo else ""
        hi_name = _os_name(hi) if hi else ""
        if lo_name and hi_name:
            return f"{neg}OS Range: {lo_name} to {hi_name}"
        if lo_name:
            return f"{neg}OS Range: {lo_name} and later"
        if hi_name:
            return f"{neg}OS Range: up to {hi_name}"
        return f"{neg}OS Range filter"

    if tag in ("FilterUser",):
        name = attrs.get("name", attrs.get("sid", "")).strip()
        return f"{neg}User: {name}" if name else f"{neg}User filter"

    if tag in ("FilterGroup", "FilterSecurity"):
        name = attrs.get("name", attrs.get("sid", "")).strip()
        return f"{neg}Security Group: {name}" if name else f"{neg}Security Group filter"

    if tag == "FilterComputer":
        name = attrs.get("name", "").strip()
        return f"{neg}Computer: {name}" if name else f"{neg}Computer filter"

    if tag == "FilterIpRange":
        lo = attrs.get("ipLow", attrs.get("lowerIP", "")).strip()
        hi = attrs.get("ipHigh", attrs.get("upperIP", "")).strip()
        if lo and hi:
            return f"{neg}IP Range: {lo} – {hi}"
        if lo:
            return f"{neg}IP: {lo}"
        return f"{neg}IP Range filter"

    if tag == "FilterSite":
        name = attrs.get("name", "").strip()
        return f"{neg}AD Site: {name}" if name else f"{neg}AD Site filter"

    if tag == "FilterMac":
        mac = attrs.get("mac", "").strip()
        return f"{neg}MAC Address: {mac}" if mac else f"{neg}MAC Address filter"

    if tag == "FilterMsi":
        name = attrs.get("name", "").strip()
        ver  = attrs.get("version", "").strip()
        text = f"MSI Installed: {name}" + (f" (v{ver})" if ver else "")
        return f"{neg}{text}" if name else f"{neg}MSI filter"

    if tag == "FilterFile":
        path = attrs.get("path", "").strip()
        ver  = attrs.get("version", "").strip()
        text = f"File Exists: {path}" + (f" (v{ver})" if ver else "")
        return f"{neg}{text}" if path else f"{neg}File filter"

    if tag == "FilterRegistry":
        hive  = attrs.get("hive", "").strip()
        key   = attrs.get("key", "").strip()
        value = attrs.get("valueName", attrs.get("value", "")).strip()
        data  = attrs.get("valueData", attrs.get("data", "")).strip()
        path  = "\\".join(p for p in [hive, key, value] if p)
        text  = f"Registry: {path}" + (f" = {data}" if data else "")
        return f"{neg}{text}" if path else f"{neg}Registry filter"

    if tag == "FilterDisk":
        raw = attrs.get("minSpace", attrs.get("space", "")).strip()
        if raw:
            try:
                mb = int(raw) // (1024 * 1024)
                size = f"{mb:,} MB" if mb >= 1 else f"{int(raw):,} bytes"
            except ValueError:
                size = raw
            return f"{neg}Free Disk Space ≥ {size}"
        return f"{neg}Disk Space filter"

    if tag == "FilterLdap":
        expr = attrs.get("filter", attrs.get("binding", "")).strip()
        return f"{neg}LDAP Query: {expr}" if expr else f"{neg}LDAP filter"

    if tag == "FilterWmi":
        query = attrs.get("query", "").strip()
        return f"{neg}WMI Query: {query}" if query else f"{neg}WMI filter"

    if tag == "FilterDateTime":
        parts = [f"{k}={v.strip()}" for k in ("start", "end", "timezone") if (v := attrs.get(k, "")).strip()]
        return f"{neg}Date/Time: {', '.join(parts)}" if parts else f"{neg}Date/Time filter"

    if tag == "FilterPortable":
        return f"{neg}Portable Computer"

    if tag == "FilterProcessMode":
        mode = attrs.get("mode", attrs.get("userContext", "")).strip()
        return f"{neg}Processing Mode: {mode}" if mode else f"{neg}Processing Mode filter"

    # Generic fallback — prefer any 'name', 'value', 'path', or 'query' attribute
    for key in ("name", "value", "path", "query", "filter"):
        val = attrs.get(key, "").strip()
        if val:
            label = tag.replace("Filter", "").strip() or tag
            return f"{neg}{label}: {val}"

    # Last resort: dump non-trivial attributes
    pairs = [f"{k}={v.strip()}" for k, v in sorted(attrs.items())
             if v.strip() and k not in {"not", "bool", "clsid"}]
    label = tag.replace("Filter", "").strip() or tag
    return f"{neg}{label}: {', '.join(pairs)}" if pairs else f"{neg}{label}"


def _registry_filter_lines(attrs: dict[str, str]) -> list[str]:
    ordered = [
        "bool",
        "not",
        "type",
        "subtype",
        "hive",
        "key",
        "valueName",
        "valueType",
        "valueData",
        "min",
        "max",
        "gte",
        "lte",
    ]
    return _structured_filter_lines("Registry Match", attrs, ordered)


def _structured_filter_lines(title: str, attrs: dict[str, str], ordered: list[str]) -> list[str]:
    if _is_neg(attrs):
        title += " (NOT)"

    lines = [title]
    seen: set[str] = set()
    for key in ordered:
        if key in attrs:
            lines.append(f"{_attribute_label(key)}: {_display_attr_value(key, attrs.get(key, ''))}")
            seen.add(key)

    for key, value in sorted(attrs.items()):
        if key in seen or key == "clsid":
            continue
        lines.append(f"{_attribute_label(key)}: {_display_attr_value(key, value)}")

    return lines


def _generic_filter_lines(tag: str, attrs: dict[str, str]) -> list[str]:
    title = _filter_title(tag)
    ordered_by_tag = {
        "FilterOs": ["bool", "not", "type", "class", "name", "version", "edition", "sp", "productType", "suite", "release", "hidden"],
        "FilterOsRange": ["bool", "not", "lowerVersion", "upperVersion", "productType", "suite"],
        "FilterUser": ["bool", "not", "name", "sid"],
        "FilterGroup": ["bool", "not", "name", "sid", "userContext", "primaryGroup", "localGroup"],
        "FilterSecurity": ["bool", "not", "name", "sid", "userContext", "primaryGroup", "localGroup"],
        "FilterComputer": ["bool", "not", "type", "name"],
        "FilterOrgUnit": ["bool", "not", "name", "userContext", "directMember"],
        "FilterIpRange": ["bool", "not", "ipLow", "ipHigh", "lowerIP", "upperIP"],
        "FilterSite": ["bool", "not", "name"],
        "FilterMac": ["bool", "not", "mac", "vendor"],
        "FilterMsi": ["bool", "not", "name", "productCode", "version", "language"],
        "FilterFile": ["bool", "not", "type", "path", "file", "folder", "version", "min", "max", "gte", "lte", "date", "size", "exists", "hidden"],
        "FilterDisk": ["bool", "not", "drive", "minSpace", "space", "freeSpace"],
        "FilterLdap": ["bool", "not", "binding", "filter", "searchFilter", "attribute"],
        "FilterWmi": ["bool", "not", "namespace", "query"],
        "FilterDateTime": ["bool", "not", "start", "end", "date", "time", "timezone", "gte", "lte"],
        "FilterPortable": ["bool", "not"],
        "FilterProcessMode": ["bool", "not", "mode", "userContext"],
        "FilterRunOnce": ["bool", "not", "id", "hidden"],
        "FilterVariable": ["bool", "not", "variableName", "value"],
    }
    return _structured_filter_lines(title, attrs, ordered_by_tag.get(tag, ["bool", "not", "name", "value", "path", "query", "filter"]))


def _collection_filter_lines(attrs: dict[str, str]) -> list[str]:
    ordered = ["bool", "not", "hidden"]
    return _structured_filter_lines("Targeting Group", attrs, ordered)


def _filter_title(tag: str) -> str:
    return {
        "FilterOs": "Operating System",
        "FilterOsRange": "Operating System Range",
        "FilterUser": "User Match",
        "FilterGroup": "Security Group Match",
        "FilterSecurity": "Security Match",
        "FilterComputer": "Computer Match",
        "FilterOrgUnit": "Organizational Unit Match",
        "FilterIpRange": "IP Range Match",
        "FilterSite": "AD Site Match",
        "FilterMac": "MAC Address Match",
        "FilterMsi": "MSI Match",
        "FilterFile": "File Match",
        "FilterRegistry": "Registry Match",
        "FilterDisk": "Disk Space Match",
        "FilterLdap": "LDAP Match",
        "FilterWmi": "WMI Match",
        "FilterDateTime": "Date/Time Match",
        "FilterPortable": "Portable Computer Match",
        "FilterProcessMode": "Processing Mode Match",
        "FilterRunOnce": "Run Once Match",
        "FilterVariable": "Environment Variable Match",
    }.get(tag, tag.replace("Filter", "").strip() or tag)


def _attribute_label(key: str) -> str:
    return {
        "bool": "Join",
        "not": "Negated",
        "type": "Type",
        "subtype": "Subtype",
        "hive": "Hive",
        "key": "Key",
        "valueName": "Value name",
        "valueType": "Value type",
        "valueData": "Value data",
        "displayDecimal": "Display decimal",
        "min": "Minimum",
        "max": "Maximum",
        "gte": "Greater than or equal",
        "lte": "Less than or equal",
        "userContext": "User context",
        "primaryGroup": "Primary group",
        "localGroup": "Local group",
        "directMember": "Direct member",
        "productCode": "Product code",
        "ipLow": "IP low",
        "ipHigh": "IP high",
        "lowerIP": "IP low",
        "upperIP": "IP high",
        "lowerVersion": "Lower version",
        "upperVersion": "Upper version",
        "minSpace": "Minimum free space",
        "freeSpace": "Free space",
        "searchFilter": "Search filter",
        "variableName": "Variable name",
        "id": "ID",
        "sp": "Service pack",
    }.get(key, _labelize(key))


def _display_attr_value(key: str, value: str) -> str:
    clean = str(value).strip()
    if key in {"not", "userContext", "primaryGroup", "localGroup", "directMember", "gte", "lte", "hidden", "displayDecimal"}:
        return _yes_no(clean, default=clean)
    if key == "type":
        return {
            "MATCHVALUE": "Match value",
            "KEYEXISTS": "Key exists",
            "VALUEEXISTS": "Value exists",
            "EXISTS": "Exists",
            "VERSION": "Version",
            "SIZE": "Size",
            "DATE": "Date",
            "NETBIOS": "NetBIOS",
            "NE": "Not equal",
        }.get(clean.upper(), clean)
    if key == "subtype":
        return {
            "SUBSTRING": "Substring",
            "EXACT": "Exact",
            "VERSION": "Version",
            "EXISTS": "Exists",
        }.get(clean.upper(), clean)
    return clean


def _yes_no(value: str, default: str = "") -> str:
    clean = str(value).strip().lower()
    if clean in {"1", "true", "yes", "y"}:
        return "Yes"
    if clean in {"0", "false", "no", "n"}:
        return "No"
    return default or str(value).strip()


def _labelize(value: str) -> str:
    label = ""
    for i, char in enumerate(value):
        if i and char.isupper() and value[i - 1].islower():
            label += " "
        label += char
    return label[:1].upper() + label[1:]


# ── tree walker ───────────────────────────────────────────────────────────────

def _walk(elem: ET.Element, out: list[str], depth: int) -> None:
    """
    Recursively walk a <Filters> or <FilterCollection> element, appending
    human-readable lines to *out*.
    """
    pad = "  " * depth
    for child in elem:
        tag = _clean_tag(child.tag)

        if tag == "FilterCollection":
            for index, line in enumerate(_collection_filter_lines(child.attrib)):
                prefix = "• " if index == 0 else "  "
                out.append(f"{pad}{prefix}{line}")
            _walk(child, out, depth + 1)

        elif _is_targeting_filter_tag(tag):
            lines = _registry_filter_lines(child.attrib) if tag == "FilterRegistry" else _generic_filter_lines(tag, child.attrib)
            for index, line in enumerate(lines):
                prefix = "• " if index == 0 else "  "
                out.append(f"{pad}{prefix}{line}")


# ── public API ────────────────────────────────────────────────────────────────

def format_filters(filters_elem: ET.Element | None) -> list[str]:
    """
    Convert a <Filters> element into a list of human-readable strings.

    Returns an empty list when *filters_elem* is None or has no child rules.
    When rules are present the first element is always ILT_HEADER, followed by
    indented rule descriptions so callers can split on the header.
    """
    if filters_elem is None:
        return []
    lines: list[str] = []
    _walk(filters_elem, lines, depth=0)
    return [ILT_HEADER] + lines if lines else []


def has_targeting(filters_elem: ET.Element | None) -> bool:
    """Return True if the element contains at least one targeting rule."""
    if filters_elem is None:
        return False
    for child in filters_elem.iter():
        tag = _clean_tag(child.tag)
        if _is_targeting_filter_tag(tag):
            return True
    return False
