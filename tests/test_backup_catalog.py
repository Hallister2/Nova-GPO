from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gpo.backup_catalog import read_backup_metadata, read_display_name, scan_backup_library

_BKUP_INFO_XML = """<?xml version="1.0" encoding="utf-8"?>
<BackupInst xmlns="http://www.microsoft.com/GroupPolicy/GPOOperations/Manifest">
  <GPODisplayName>{name}</GPODisplayName>
  <GPODomain>corp.example.com</GPODomain>
  <BackupTime>2026-01-15T10:30:00</BackupTime>
</BackupInst>
"""


def _write_valid_backup(root: Path, folder_name: str, display_name: str, with_registry_pol: bool = True) -> Path:
    backup_dir = root / folder_name
    backup_dir.mkdir(parents=True)
    (backup_dir / "bkupInfo.xml").write_text(_BKUP_INFO_XML.format(name=display_name), encoding="utf-8")
    (backup_dir / "Backup.xml").write_text("<GroupPolicyBackupScheme/>", encoding="utf-8")
    (backup_dir / "gpreport.xml").write_text("<GPO/>", encoding="utf-8")
    if with_registry_pol:
        (backup_dir / "DomainSysvol" / "GPO" / "Machine").mkdir(parents=True)
        (backup_dir / "DomainSysvol" / "GPO" / "Machine" / "Registry.pol").write_bytes(b"PReg")
    return backup_dir


class TestScanBackupLibrary(unittest.TestCase):
    def test_missing_root_returns_empty_list(self) -> None:
        missing = Path(tempfile.gettempdir()) / "nova_gpo_test_missing_root_xyz"
        self.assertFalse(missing.exists())
        self.assertEqual(scan_backup_library(str(missing)), [])

    def test_finds_valid_backup_with_registry_pol(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_valid_backup(root, "{GUID-1}", "Default Domain Policy")

            items = scan_backup_library(str(root))

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.display_name, "Default Domain Policy")
            self.assertEqual(item.domain, "corp.example.com")
            self.assertTrue(item.is_valid)
            self.assertEqual(item.status, "Valid")
            self.assertIn("registry policy found", item.detail)

    def test_valid_backup_without_registry_pol_still_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_valid_backup(root, "{GUID-2}", "No Registry GPO", with_registry_pol=False)

            items = scan_backup_library(str(root))

            self.assertEqual(len(items), 1)
            self.assertTrue(items[0].is_valid)
            self.assertIn("No Registry.pol detected", items[0].detail)

    def test_missing_required_files_marks_needs_review(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            incomplete = root / "{GUID-3}"
            incomplete.mkdir()
            (incomplete / "Backup.xml").write_text("<x/>", encoding="utf-8")
            # bkupInfo.xml and gpreport.xml intentionally missing.

            items = scan_backup_library(str(root))

            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertFalse(item.is_valid)
            self.assertEqual(item.status, "Needs review")
            self.assertIn("bkupInfo.xml", item.detail)
            self.assertIn("gpreport.xml", item.detail)

    def test_folder_name_used_when_no_display_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "UnnamedFolder"
            folder.mkdir()
            (folder / "Backup.xml").write_text("<x/>", encoding="utf-8")

            items = scan_backup_library(str(root))

            self.assertEqual(items[0].display_name, "UnnamedFolder")

    def test_archived_folder_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_valid_backup(root, "{GUID-4}", "Kept Policy")
            archived = root / ".Archived"
            archived.mkdir()
            (archived / "something.txt").write_text("x", encoding="utf-8")

            items = scan_backup_library(str(root))

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].display_name, "Kept Policy")

    def test_files_are_not_treated_as_backups(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not_a_folder.txt").write_text("x", encoding="utf-8")

            self.assertEqual(scan_backup_library(str(root)), [])

    def test_source_index_is_applied_to_every_item(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_valid_backup(root, "{GUID-5}", "Policy A")

            items = scan_backup_library(str(root), source_index=7)

            self.assertEqual(items[0].source_index, 7)

    def test_results_sorted_by_display_name_case_insensitive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_valid_backup(root, "{GUID-Z}", "zebra policy")
            _write_valid_backup(root, "{GUID-A}", "Alpha Policy")

            items = scan_backup_library(str(root))

            self.assertEqual([item.display_name for item in items], ["Alpha Policy", "zebra policy"])

    def test_should_cancel_stops_scan_early(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_valid_backup(root, "{GUID-6}", "Policy One")
            _write_valid_backup(root, "{GUID-7}", "Policy Two")

            items = scan_backup_library(str(root), should_cancel=lambda: True)

            self.assertEqual(items, [])


class TestReadBackupMetadata(unittest.TestCase):
    def test_missing_bkup_info_returns_empty_dict(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(read_backup_metadata(Path(tmp)), {})

    def test_parses_namespaced_manifest_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "bkupInfo.xml").write_text(_BKUP_INFO_XML.format(name="Parsed Policy"), encoding="utf-8")

            metadata = read_backup_metadata(folder)

            self.assertEqual(metadata["display_name"], "Parsed Policy")
            self.assertEqual(metadata["domain"], "corp.example.com")
            self.assertEqual(metadata["backup_time"], "2026-01-15T10:30:00")

    def test_malformed_xml_returns_empty_dict(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "bkupInfo.xml").write_text("<not valid xml", encoding="utf-8")

            self.assertEqual(read_backup_metadata(folder), {})

    def test_read_display_name_falls_back_to_folder_name(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "FallbackName"
            folder.mkdir()

            self.assertEqual(read_display_name(folder), "FallbackName")


if __name__ == "__main__":
    unittest.main()
