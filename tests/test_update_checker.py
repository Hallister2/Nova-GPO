from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.update_checker import (
    UpdateCheckError,
    _clean_version,
    _fetch_highest_release,
    _release_version,
    _is_newer_version,
    check_for_updates,
)


class UpdateCheckerTests(unittest.TestCase):
    def test_clean_version_removes_leading_v(self) -> None:
        self.assertEqual(_clean_version("v1.2.3"), "1.2.3")
        self.assertEqual(_clean_version("V2.0"), "2.0")

    def test_newer_version_compares_numeric_parts(self) -> None:
        self.assertTrue(_is_newer_version("0.2", "0.1"))
        self.assertTrue(_is_newer_version("1.0.1", "1.0"))
        self.assertFalse(_is_newer_version("1.0", "1.0.1"))
        self.assertFalse(_is_newer_version("1.0.0", "1.0"))

    def test_no_github_release_is_not_an_update_error(self) -> None:
        no_release = UpdateCheckError("No GitHub releases were found for Nova GPO.")
        no_release.no_release = True

        with patch("app.core.update_checker._fetch_highest_release", side_effect=no_release):
            result = check_for_updates()

        self.assertFalse(result.release_found)
        self.assertFalse(result.is_update_available)
        self.assertEqual(result.release_name, "No releases found")

    def test_highest_release_uses_version_tag_not_github_latest_flag(self) -> None:
        releases = [
            {"tag_name": "0.1", "draft": False, "prerelease": False},
            {"tag_name": "0.5", "draft": False, "prerelease": True},
            {"tag_name": "0.4", "draft": True, "prerelease": False},
        ]

        with patch("app.core.update_checker._fetch_releases", return_value=releases):
            release = _fetch_highest_release(timeout=1)

        self.assertEqual(release["tag_name"], "0.5")

    def test_check_for_updates_reports_prerelease_update(self) -> None:
        release = {
            "tag_name": "0.5",
            "name": "Nova GPO 0.5",
            "html_url": "https://github.com/Hallister2/Nova-GPO/releases/tag/0.5",
            "draft": False,
            "prerelease": True,
        }

        with patch("app.core.update_checker._fetch_highest_release", return_value=release):
            result = check_for_updates()

        self.assertTrue(result.release_found)
        self.assertTrue(result.is_update_available)
        self.assertTrue(result.is_prerelease)
        self.assertEqual(result.latest_version, "0.5")

    def test_release_version_uses_release_name_when_tag_is_wrong(self) -> None:
        release = {
            "tag_name": "v0.1-beta",
            "name": "v0.5-beta",
        }

        self.assertEqual(_release_version(release), "0.5-beta")


if __name__ == "__main__":
    unittest.main()
