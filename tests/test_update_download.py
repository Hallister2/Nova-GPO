import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.ui.main_window import _extract_sha256, _friendly_download_error, _is_github_download_url, _sha256_file


class UpdateDownloadTests(unittest.TestCase):
    def test_extract_sha256_prefers_matching_installer_line(self) -> None:
        expected = "a" * 64
        other = "b" * 64
        text = f"{other}  Other.exe\n{expected}  NovaGPOSetup_0.8.exe\n"

        self.assertEqual(_extract_sha256(text, "NovaGPOSetup_0.8.exe"), expected)

    def test_extract_sha256_requires_unambiguous_hash_without_filename(self) -> None:
        expected = "c" * 64

        self.assertEqual(_extract_sha256(expected, "NovaGPOSetup_0.8.exe"), expected)
        self.assertEqual(_extract_sha256(f"{expected}\n{'d' * 64}", "NovaGPOSetup_0.8.exe"), "")

    def test_sha256_file_hashes_content(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "installer.exe"
            path.write_bytes(b"nova gpo")

            self.assertEqual(_sha256_file(str(path)), hashlib.sha256(b"nova gpo").hexdigest())

    def test_github_download_url_validation(self) -> None:
        self.assertTrue(_is_github_download_url("https://github.com/Hallister2/Nova-GPO/releases/download/x/app.exe"))
        self.assertTrue(_is_github_download_url("https://objects.githubusercontent.com/github-production-release-asset/app.exe"))
        self.assertFalse(_is_github_download_url("https://example.com/app.exe"))

    def test_friendly_download_error_explains_checksum_failures(self) -> None:
        self.assertIn(
            "checksum asset was malformed",
            _friendly_download_error("Checksum file did not contain a SHA-256 hash for this installer."),
        )
        self.assertIn(
            "checksum did not match",
            _friendly_download_error("Downloaded installer checksum did not match the GitHub release checksum."),
        )


if __name__ == "__main__":
    unittest.main()
