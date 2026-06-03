from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gpo.search import _filter_result, _matches, _scope_from_source, SearchResult


def _result(
    source_index: int = 1,
    source_path: str = "/root",
    backup_name: str = "Test GPO",
    backup_path: str = "/root/TestGPO",
    result_type: str = "Administrative Template",
    scope: str = "Computer Configuration",
    name: str = "Test Policy",
    category: str = "Windows Components",
    value: str = "Enabled",
    source_file: str = "gpreport.xml",
) -> SearchResult:
    return SearchResult(
        source_index=source_index,
        source_path=source_path,
        backup_name=backup_name,
        backup_path=backup_path,
        result_type=result_type,
        scope=scope,
        name=name,
        category=category,
        value=value,
        source_file=source_file,
    )


class TestMatches(unittest.TestCase):

    def test_single_term_match(self) -> None:
        self.assertTrue(_matches(["password"], "Password Policy"))

    def test_multi_term_all_must_match(self) -> None:
        self.assertTrue(_matches(["windows", "firewall"], "Windows Firewall Settings"))

    def test_multi_term_partial_no_match(self) -> None:
        self.assertFalse(_matches(["windows", "firewall"], "Windows Defender Settings"))

    def test_case_insensitive(self) -> None:
        # _matches lowercases the haystack; callers (search_backup_library) pre-lowercase terms
        self.assertTrue(_matches(["defender"], "Windows Defender Settings"))

    def test_empty_terms_matches_everything(self) -> None:
        self.assertTrue(_matches([], "Anything at all"))

    def test_no_match(self) -> None:
        self.assertFalse(_matches(["nonexistent"], "Windows Firewall"))

    def test_matches_across_multiple_values(self) -> None:
        self.assertTrue(_matches(["admin", "template"], "Admin Policy", "Template Config"))

    def test_exact_phrase_requires_terms_together(self) -> None:
        self.assertFalse(_matches(["admin", "template"], "Admin Policy", "Template Config", exact=True))
        self.assertTrue(_matches(["admin", "template"], "Admin Template Config", exact=True))

    def test_empty_haystack(self) -> None:
        self.assertFalse(_matches(["password"], ""))


class TestFilterResult(unittest.TestCase):

    def test_all_types_all_scopes_passes_everything(self) -> None:
        r = _result()
        self.assertTrue(_filter_result(r, "All Types", "All Scopes"))

    def test_type_filter_match(self) -> None:
        r = _result(result_type="Administrative Template")
        self.assertTrue(_filter_result(r, "Administrative Template", "All Scopes"))

    def test_type_filter_no_match(self) -> None:
        r = _result(result_type="Preference")
        self.assertFalse(_filter_result(r, "Administrative Template", "All Scopes"))

    def test_scope_filter_match(self) -> None:
        r = _result(scope="Computer Configuration")
        self.assertTrue(_filter_result(r, "All Types", "Computer Configuration"))

    def test_scope_filter_no_match(self) -> None:
        r = _result(scope="User Configuration")
        self.assertFalse(_filter_result(r, "All Types", "Computer Configuration"))

    def test_both_filters_must_match(self) -> None:
        r = _result(result_type="Administrative Template", scope="User Configuration")
        self.assertFalse(_filter_result(r, "Administrative Template", "Computer Configuration"))

    def test_both_filters_match(self) -> None:
        r = _result(result_type="GPO Backup", scope="Backup")
        self.assertTrue(_filter_result(r, "GPO Backup", "Backup"))


class TestScopeFromSource(unittest.TestCase):

    def test_user_scope(self) -> None:
        self.assertEqual(_scope_from_source("User/Scripts/Logon.ps1"), "User Configuration")

    def test_machine_scope(self) -> None:
        self.assertEqual(_scope_from_source("Machine/Registry.pol"), "Computer Configuration")

    def test_computer_scope(self) -> None:
        self.assertEqual(_scope_from_source("Computer/Scripts/Startup.bat"), "Computer Configuration")

    def test_unknown_falls_back_to_artifacts(self) -> None:
        self.assertEqual(_scope_from_source("something/else/file.xml"), "Artifacts")

    def test_empty_string_is_artifacts(self) -> None:
        self.assertEqual(_scope_from_source(""), "Artifacts")

    def test_backslash_path_user(self) -> None:
        self.assertEqual(_scope_from_source("User\\Scripts\\file.ps1"), "User Configuration")


class TestSearchBackupLibrary(unittest.TestCase):
    """Integration-style tests using a minimal on-disk backup structure."""

    def _make_minimal_backup(self, root: Path, name: str = "TestGPO") -> Path:
        folder = root / name
        folder.mkdir()
        (folder / "bkupInfo.xml").write_text(
            '<?xml version="1.0"?>'
            '<BackupInst xmlns="http://www.microsoft.com/GroupPolicy/GPOOperations/Manifest">'
            f'<GPODisplayName>{name}</GPODisplayName>'
            "<GPODomain>test.local</GPODomain>"
            "<BackupTime>2024-01-01T00:00:00</BackupTime>"
            "</BackupInst>",
            encoding="utf-8",
        )
        (folder / "Backup.xml").write_text("<root/>", encoding="utf-8")
        (folder / "gpreport.xml").write_text(
            '<?xml version="1.0"?><GPO xmlns:q1="http://www.microsoft.com/GroupPolicy/Settings" '
            'xmlns="http://www.microsoft.com/GroupPolicy/Settings"><Name>TestGPO</Name>'
            "<Computer><ExtensionData/></Computer><User><ExtensionData/></User></GPO>",
            encoding="utf-8",
        )
        return folder

    def test_returns_empty_for_empty_query(self) -> None:
        from app.gpo.search import search_backup_library
        with TemporaryDirectory() as tmp:
            self._make_minimal_backup(Path(tmp))
            results = search_backup_library([tmp], "")
            self.assertEqual(results, [])

    def test_finds_backup_by_name(self) -> None:
        from app.gpo.search import search_backup_library
        with TemporaryDirectory() as tmp:
            self._make_minimal_backup(Path(tmp), "MySpecialGPO")
            results = search_backup_library([tmp], "MySpecialGPO")
            self.assertTrue(len(results) > 0)
            self.assertTrue(any("MySpecialGPO" in r.backup_name for r in results))

    def test_no_results_for_unknown_term(self) -> None:
        from app.gpo.search import search_backup_library
        with TemporaryDirectory() as tmp:
            self._make_minimal_backup(Path(tmp))
            results = search_backup_library([tmp], "TermThatWillNeverBeFound_xyz123")
            self.assertEqual(results, [])

    def test_limit_is_respected(self) -> None:
        from app.gpo.search import search_backup_library
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                self._make_minimal_backup(root, f"GPO_{i}")
            results = search_backup_library([tmp], "GPO", limit=3)
            self.assertLessEqual(len(results), 3)

    def test_source_filter_restricts_results(self) -> None:
        from app.gpo.search import search_backup_library
        with TemporaryDirectory() as tmp1, TemporaryDirectory() as tmp2:
            self._make_minimal_backup(Path(tmp1), "GPO_A")
            self._make_minimal_backup(Path(tmp2), "GPO_B")
            results = search_backup_library([tmp1, tmp2], "GPO", source_filter=2)
            self.assertTrue(all(r.source_index == 2 for r in results))


if __name__ == "__main__":
    unittest.main()
