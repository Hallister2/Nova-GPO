from __future__ import annotations

import re
import sys

from app.core.log import get_logger

_log = get_logger(__name__)

# ── Well-known SID table ──────────────────────────────────────────────────────

WELL_KNOWN_SIDS: dict[str, str] = {
    "S-1-0-0":   "Null Authority",
    "S-1-1-0":   "Everyone",
    "S-1-2-0":   "Local",
    "S-1-2-1":   "Console Logon",
    "S-1-3-0":   "Creator Owner",
    "S-1-3-1":   "Creator Group",
    "S-1-3-4":   "Owner Rights",
    "S-1-5-1":   "Dialup",
    "S-1-5-2":   "Network",
    "S-1-5-3":   "Batch",
    "S-1-5-4":   "Interactive",
    "S-1-5-6":   "Service",
    "S-1-5-7":   "Anonymous",
    "S-1-5-8":   "Proxy",
    "S-1-5-9":   "Enterprise Domain Controllers",
    "S-1-5-10":  "Self",
    "S-1-5-11":  "Authenticated Users",
    "S-1-5-12":  "Restricted Code",
    "S-1-5-13":  "Terminal Server User",
    "S-1-5-14":  "Remote Interactive Logon",
    "S-1-5-15":  "This Organization",
    "S-1-5-17":  "IUSR",
    "S-1-5-18":  "Local System",
    "S-1-5-19":  "Local Service",
    "S-1-5-20":  "Network Service",
    "S-1-5-32-544": "BUILTIN\\Administrators",
    "S-1-5-32-545": "BUILTIN\\Users",
    "S-1-5-32-546": "BUILTIN\\Guests",
    "S-1-5-32-547": "BUILTIN\\Power Users",
    "S-1-5-32-548": "BUILTIN\\Account Operators",
    "S-1-5-32-549": "BUILTIN\\Server Operators",
    "S-1-5-32-550": "BUILTIN\\Print Operators",
    "S-1-5-32-551": "BUILTIN\\Backup Operators",
    "S-1-5-32-552": "BUILTIN\\Replicators",
    "S-1-5-32-554": "BUILTIN\\Pre-Windows 2000 Compatible Access",
    "S-1-5-32-555": "BUILTIN\\Remote Desktop Users",
    "S-1-5-32-556": "BUILTIN\\Network Configuration Operators",
    "S-1-5-32-557": "BUILTIN\\Incoming Forest Trust Builders",
    "S-1-5-32-558": "BUILTIN\\Performance Monitor Users",
    "S-1-5-32-559": "BUILTIN\\Performance Log Users",
    "S-1-5-32-560": "BUILTIN\\Windows Authorization Access Group",
    "S-1-5-32-561": "BUILTIN\\Terminal Server License Servers",
    "S-1-5-32-562": "BUILTIN\\Distributed COM Users",
    "S-1-5-32-569": "BUILTIN\\Cryptographic Operators",
    "S-1-5-32-573": "BUILTIN\\Event Log Readers",
    "S-1-5-32-574": "BUILTIN\\Certificate Service DCOM Access",
    "S-1-5-32-575": "BUILTIN\\RDS Remote Access Servers",
    "S-1-5-32-576": "BUILTIN\\RDS Endpoint Servers",
    "S-1-5-32-577": "BUILTIN\\RDS Management Servers",
    "S-1-5-32-578": "BUILTIN\\Hyper-V Administrators",
    "S-1-5-32-579": "BUILTIN\\Access Control Assistance Operators",
    "S-1-5-32-580": "BUILTIN\\Remote Management Users",
    "S-1-5-32-581": "BUILTIN\\Default Account",
    "S-1-5-32-582": "BUILTIN\\Storage Replica Administrators",
    "S-1-5-64-10": "NTLM Authentication",
    "S-1-5-64-14": "SChannel Authentication",
    "S-1-5-64-21": "Digest Authentication",
    "S-1-16-0":    "Untrusted Mandatory Level",
    "S-1-16-4096": "Low Mandatory Level",
    "S-1-16-8192": "Medium Mandatory Level",
    "S-1-16-8448": "Medium Plus Mandatory Level",
    "S-1-16-12288": "High Mandatory Level",
    "S-1-16-16384": "System Mandatory Level",
}

# ── Privilege / user-right name table ─────────────────────────────────────────

PRIVILEGE_NAMES: dict[str, str] = {
    "SeNetworkLogonRight":              "Access this computer from the network",
    "SeInteractiveLogonRight":          "Allow log on locally",
    "SeRemoteInteractiveLogonRight":    "Allow log on through Remote Desktop Services",
    "SeServiceLogonRight":              "Log on as a service",
    "SeBatchLogonRight":                "Log on as a batch job",
    "SeDenyNetworkLogonRight":          "Deny access to this computer from the network",
    "SeDenyInteractiveLogonRight":      "Deny log on locally",
    "SeDenyRemoteInteractiveLogonRight": "Deny log on through Remote Desktop Services",
    "SeDenyServiceLogonRight":          "Deny log on as a service",
    "SeDenyBatchLogonRight":            "Deny log on as a batch job",
    "SeShutdownPrivilege":              "Shut down the system",
    "SeRemoteShutdownPrivilege":        "Force shutdown from a remote system",
    "SeAuditPrivilege":                 "Generate security audits",
    "SeBackupPrivilege":                "Back up files and directories",
    "SeRestorePrivilege":               "Restore files and directories",
    "SeSecurityPrivilege":              "Manage auditing and security log",
    "SeTakeOwnershipPrivilege":         "Take ownership of files or other objects",
    "SeDebugPrivilege":                 "Debug programs",
    "SeSystemtimePrivilege":            "Change the system time",
    "SeTimeZonePrivilege":              "Change the time zone",
    "SeMachineAccountPrivilege":        "Add workstations to domain",
    "SeCreatePagefilePrivilege":        "Create a pagefile",
    "SeCreatePermanentPrivilege":       "Create permanent shared objects",
    "SeCreateTokenPrivilege":           "Create a token object",
    "SeCreateSymbolicLinkPrivilege":    "Create symbolic links",
    "SeCreateGlobalPrivilege":          "Create global objects",
    "SeIncreaseQuotaPrivilege":         "Adjust memory quotas for a process",
    "SeIncreaseBasePriorityPrivilege":  "Increase scheduling priority",
    "SeLoadDriverPrivilege":            "Load and unload device drivers",
    "SeLockMemoryPrivilege":            "Lock pages in memory",
    "SeManageVolumePrivilege":          "Perform volume maintenance tasks",
    "SeProfileSingleProcessPrivilege":  "Profile single process",
    "SeSystemProfilePrivilege":         "Profile system performance",
    "SeSystemEnvironmentPrivilege":     "Modify firmware environment values",
    "SeUndockPrivilege":                "Remove computer from docking station",
    "SeAssignPrimaryTokenPrivilege":    "Replace a process-level token",
    "SeIncreaseWorkingSetPrivilege":    "Increase a process working set",
    "SeImpersonatePrivilege":           "Impersonate a client after authentication",
    "SeRelabelPrivilege":               "Modify an object label",
    "SeTrustedCredManAccessPrivilege":  "Access Credential Manager as trusted caller",
    "SeSyncAgentPrivilege":             "Synchronize directory service data",
    "SeEnableDelegationPrivilege":      "Enable computer and user accounts to be trusted for delegation",
    "SeChangeNotifyPrivilege":          "Bypass traverse checking",
    "SeTcbPrivilege":                   "Act as part of the operating system",
}


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_sid(sid: str, use_api: bool = False) -> str:
    """Return a human-readable name for a SID string.

    Checks the well-known SID table first.  If *use_api* is True and the SID
    is not in the table, attempts a Windows API lookup via ctypes (no extra
    packages required).  Falls back to returning the original SID string.
    """
    upper = sid.strip().upper()
    result = WELL_KNOWN_SIDS.get(upper) or WELL_KNOWN_SIDS.get(sid.strip())
    if result:
        return result

    if use_api and sys.platform == "win32":
        resolved = _lookup_via_win32(sid.strip())
        if resolved:
            return resolved

    return sid.strip()


def resolve_privilege_name(name: str) -> str:
    """Return the human-readable policy name for a Se*Privilege / Se*Right constant."""
    return PRIVILEGE_NAMES.get(name.strip(), name.strip())


def resolve_sid_list(raw: str, use_api: bool = False) -> str:
    """Resolve a comma-separated list of SID tokens (with optional leading *).

    Handles the GptTmpl.inf format:  ``*S-1-5-32-544,*S-1-1-0,Administrators``
    Returns a comma-separated list of resolved names.
    """
    if not raw.strip():
        return ""

    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    resolved: list[str] = []
    for token in tokens:
        # Strip leading * (SID pointer marker in security templates)
        sid = token.lstrip("*")
        if re.match(r"^S-\d+-\d+", sid, re.IGNORECASE):
            resolved.append(resolve_sid(sid, use_api=use_api))
        else:
            resolved.append(token)

    return ", ".join(resolved)


# ── Windows API SID lookup ────────────────────────────────────────────────────

def _lookup_via_win32(sid_str: str) -> str | None:
    """Attempt a LookupAccountSid via ctypes. Returns None on any failure."""
    try:
        import ctypes
        import ctypes.wintypes

        advapi32 = ctypes.windll.advapi32

        # Convert string SID to binary SID
        p_sid = ctypes.c_void_p()
        if not advapi32.ConvertStringSidToSidW(sid_str, ctypes.byref(p_sid)):
            return None

        name_buf = ctypes.create_unicode_buffer(256)
        name_size = ctypes.wintypes.DWORD(256)
        domain_buf = ctypes.create_unicode_buffer(256)
        domain_size = ctypes.wintypes.DWORD(256)
        sid_type = ctypes.wintypes.DWORD()

        ok = advapi32.LookupAccountSidW(
            None,
            p_sid,
            name_buf, ctypes.byref(name_size),
            domain_buf, ctypes.byref(domain_size),
            ctypes.byref(sid_type),
        )

        ctypes.windll.kernel32.LocalFree(p_sid)

        if not ok:
            return None

        name = name_buf.value
        domain = domain_buf.value
        if domain and name:
            return f"{domain}\\{name}"
        return name or None

    except Exception as exc:
        _log.debug("Win32 SID lookup failed for %s: %s", sid_str, exc)
        return None
