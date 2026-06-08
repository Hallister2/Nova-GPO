from __future__ import annotations

from dataclasses import dataclass
import json
import re
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import GITHUB_REPOSITORY, __version__


LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"


class UpdateCheckError(RuntimeError):
    """Raised when the update check cannot reach or parse the release feed."""


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    release_name: str
    release_url: str
    is_update_available: bool
    release_found: bool = True
    is_prerelease: bool = False
    download_url: str = ""
    asset_name: str = ""
    checksum_url: str = ""
    checksum_name: str = ""


def check_for_updates(timeout: int = 5) -> UpdateCheckResult:
    try:
        payload = _fetch_highest_release(timeout=timeout)
    except UpdateCheckError as error:
        if getattr(error, "no_release", False):
            current_version = _clean_version(__version__)
            return UpdateCheckResult(
                current_version=current_version,
                latest_version=current_version,
                release_name="No releases found",
                release_url=RELEASES_URL,
                is_update_available=False,
                release_found=False,
            )
        raise
    latest_version = _release_version(payload)
    if not latest_version:
        raise UpdateCheckError("The latest release did not include a recognizable version.")

    release_url = str(payload.get("html_url") or RELEASES_URL).strip()
    release_name = str(payload.get("name") or payload.get("tag_name") or latest_version).strip()
    current_version = _clean_version(__version__)
    is_prerelease = bool(payload.get("prerelease", False))
    download_url, asset_name = _find_installer_asset(payload)
    checksum_url, checksum_name = _find_checksum_asset(payload, asset_name)

    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        release_name=release_name,
        release_url=release_url,
        is_update_available=_is_newer_version(latest_version, current_version),
        is_prerelease=is_prerelease,
        download_url=download_url,
        asset_name=asset_name,
        checksum_url=checksum_url,
        checksum_name=checksum_name,
    )


def _fetch_highest_release(timeout: int) -> dict[str, Any]:
    releases = _fetch_releases(timeout=timeout)
    candidates = [
        release for release in releases
        if isinstance(release, dict)
        and not bool(release.get("draft", False))
        and _version_parts(_release_version(release))
    ]
    if not candidates:
        update_error = UpdateCheckError("No GitHub releases were found for Nova GPO.")
        update_error.no_release = True
        raise update_error

    return max(
        candidates,
        key=lambda release: _version_parts(_release_version(release)),
    )


def _fetch_releases(timeout: int) -> list[dict[str, Any]]:
    payload = _fetch_github_json(RELEASES_API, timeout=timeout)
    if not isinstance(payload, list):
        raise UpdateCheckError("GitHub returned an unexpected release response.")
    return payload


def _fetch_latest_release(timeout: int) -> dict[str, Any]:
    payload = _fetch_github_json(LATEST_RELEASE_API, timeout=timeout)
    if not isinstance(payload, dict):
        raise UpdateCheckError("GitHub returned an unexpected release response.")
    return payload


def _fetch_github_json(url: str, timeout: int) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Nova-GPO-Update-Checker",
        },
    )

    try:
        with urlopen(request, timeout=timeout, context=_github_ssl_context()) as response:
            data = response.read().decode("utf-8")
    except HTTPError as error:
        if error.code == 404:
            update_error = UpdateCheckError("No GitHub releases were found for Nova GPO.")
            update_error.no_release = True
            raise update_error from error
        raise UpdateCheckError(f"GitHub returned HTTP {error.code}.") from error
    except URLError as error:
        raise UpdateCheckError(_format_url_error(error)) from error
    except ssl.SSLCertVerificationError as error:
        raise UpdateCheckError(_certificate_error_message()) from error
    except TimeoutError as error:
        raise UpdateCheckError("The update check timed out.") from error

    try:
        payload = json.loads(data)
    except json.JSONDecodeError as error:
        raise UpdateCheckError("GitHub returned an unreadable release response.") from error

    return payload


def _github_ssl_context() -> ssl.SSLContext:
    if sys.platform == "win32":
        try:
            import truststore

            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            pass

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _format_url_error(error: URLError) -> str:
    reason = getattr(error, "reason", error)
    if _is_certificate_error(reason):
        return _certificate_error_message()
    return f"Could not reach GitHub: {reason}"


def _is_certificate_error(error: object) -> bool:
    if isinstance(error, ssl.SSLCertVerificationError):
        return True
    return "CERTIFICATE_VERIFY_FAILED" in str(error)


def _certificate_error_message() -> str:
    return (
        "Could not verify GitHub's SSL certificate. "
        "Check Windows certificates or any HTTPS-inspection security tool, then try again."
    )


def _clean_version(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    return cleaned


def _release_version(release: dict[str, Any]) -> str:
    versions = [
        _extract_version(str(release.get("tag_name") or "")),
        _extract_version(str(release.get("name") or "")),
    ]
    versions = [version for version in versions if version]
    if not versions:
        return ""
    return max(versions, key=_version_parts)


def _extract_version(value: str) -> str:
    match = re.search(r"\bv?(\d+(?:\.\d+){1,3}(?:[-.][A-Za-z0-9]+)?)\b", value.strip())
    return _clean_version(match.group(1)) if match else ""


def _is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = _version_parts(candidate)
    current_parts = _version_parts(current)
    width = max(len(candidate_parts), len(current_parts), 1)
    candidate_parts.extend([0] * (width - len(candidate_parts)))
    current_parts.extend([0] * (width - len(current_parts)))
    return candidate_parts > current_parts


def _find_installer_asset(release: dict[str, Any]) -> tuple[str, str]:
    """Return (download_url, asset_name) for the best Windows installer in the release."""
    assets = release.get("assets")
    if not isinstance(assets, list):
        return "", ""

    _PREFERRED = {"setup", "installer", "install"}

    candidates: list[dict[str, Any]] = [
        asset for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name", "")).lower().endswith((".exe", ".msi"))
        and str(asset.get("browser_download_url", "")).startswith("https://")
    ]

    if not candidates:
        return "", ""

    # Prefer assets whose names contain recognisable installer keywords
    preferred = [
        a for a in candidates
        if any(kw in a.get("name", "").lower() for kw in _PREFERRED)
    ]
    best = preferred[0] if preferred else candidates[0]
    return str(best.get("browser_download_url", "")), str(best.get("name", ""))


def _find_checksum_asset(release: dict[str, Any], asset_name: str) -> tuple[str, str]:
    assets = release.get("assets")
    if not isinstance(assets, list) or not asset_name:
        return "", ""

    asset_base = asset_name.lower()
    candidates: list[dict[str, Any]] = [
        asset for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("browser_download_url", "")).startswith("https://")
        and _looks_like_checksum_asset(str(asset.get("name", "")), asset_base)
    ]

    if not candidates:
        return "", ""

    specific = [
        asset for asset in candidates
        if str(asset.get("name", "")).lower().startswith(asset_base)
    ]
    best = specific[0] if specific else candidates[0]
    return str(best.get("browser_download_url", "")), str(best.get("name", ""))


def _looks_like_checksum_asset(name: str, installer_name: str) -> bool:
    lower = name.lower()
    if lower in {"sha256sums.txt", "sha256sum.txt", "checksums.txt", "checksum.txt"}:
        return True
    if lower.endswith((".sha256", ".sha256sum", ".sha256.txt")):
        return True
    return installer_name in lower and "sha256" in lower


def _version_parts(value: str) -> list[int]:
    parts = []
    for chunk in re.split(r"[^0-9]+", value):
        if chunk:
            parts.append(int(chunk))
    return parts
