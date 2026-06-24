from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from collections import Counter
from pathlib import Path

from app.gpo.backup_catalog import scan_backup_library
from app.gpo.archive import archive_backup, list_archived_backups, permanently_delete_archived_backup, purge_expired_archives, restore_archived_backup
from app.gpo.backup_loader import load_gpo_backup
from app.gpo.comparison_model import build_backup_diff, build_policy_diff
from app.gpo.diff_engine import compare_backups
from app.gpo.search import search_backup_library
from app.review_store import load_review_notes, save_review_notes
from app.gpo.gpreport_parser import GpoReportPolicy, GpoReportSummary, load_gpreport
from app.reports.compare_report import markdown_report


ROOT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = ROOT / "GPO Backups"


def _require_sample_backups() -> None:
    if not BACKUP_ROOT.exists():
        raise unittest.SkipTest("Optional GPO Backups sample fixture is not present.")


class GpoReportParserTests(unittest.TestCase):
    def test_loads_admin_template_and_preference_items(self) -> None:
        _require_sample_backups()
        items = scan_backup_library(str(BACKUP_ROOT))
        reports = [load_gpreport(item.path) for item in items]

        policy_types = Counter(
            policy.policy_type
            for report in reports
            if report is not None
            for policy in report.policies
        )

        self.assertGreaterEqual(policy_types["Administrative Template"], 1)
        self.assertGreaterEqual(policy_types["Preference"], 1)

    def test_preference_items_participate_in_comparison(self) -> None:
        _require_sample_backups()
        items = scan_backup_library(str(BACKUP_ROOT))
        reports = {item.display_name: load_gpreport(item.path) for item in items}

        diff_items = build_policy_diff(
            reports["ENT - Win Std OneDrive Settings - User"],
            reports["ENT - Win Std OneDrive Settings - User - Test"],
        )

        preference_diffs = [
            item
            for item in diff_items
            if (item.policy_a and item.policy_a.policy_type == "Preference")
            or (item.policy_b and item.policy_b.policy_type == "Preference")
        ]

        self.assertGreaterEqual(len(preference_diffs), 1)

    def test_markdown_report_includes_review_notes(self) -> None:
        _require_sample_backups()
        items = scan_backup_library(str(BACKUP_ROOT))
        diff_items = build_policy_diff(
            load_gpreport(items[0].path),
            load_gpreport(items[2].path),
        )

        report = markdown_report(
            "Backup A",
            "Backup B",
            diff_items[:1],
            {
                diff_items[0].key: {
                    "status": "Make Changes to A",
                    "priority": "High",
                    "notes": "Validate before rollout. CHG456.",
                }
            },
        )

        self.assertIn("- Review Status: Make Changes to A", report)
        self.assertIn("- Priority: High", report)
        self.assertIn("CHG456", report)

    def test_category_move_is_reported_as_changed_policy(self) -> None:
        policy_a = GpoReportPolicy(
            scope="Computer Configuration",
            name="Configure firewall protection",
            state="Enabled",
            category="Old Security Category",
            supported="Windows",
            explain="",
            settings=[],
            identity="policy::computer configuration::administrative template::configure firewall protection",
        )
        policy_b = GpoReportPolicy(
            scope="Computer Configuration",
            name="Configure firewall protection",
            state="Enabled",
            category="New Security Category",
            supported="Windows",
            explain="",
            settings=[],
            identity="policy::computer configuration::administrative template::configure firewall protection",
        )

        diff_items = build_policy_diff(
            _summary([policy_a]),
            _summary([policy_b]),
        )

        self.assertEqual(len(diff_items), 1)
        self.assertEqual(diff_items[0].status, "Different")

    def test_preference_registry_identity_ignores_volatile_uid(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _write_gpreport(
                Path(first),
                uid="{11111111-1111-1111-1111-111111111111}",
                value="1",
            )
            _write_gpreport(
                Path(second),
                uid="{22222222-2222-2222-2222-222222222222}",
                value="2",
            )

            report_a = load_gpreport(first)
            report_b = load_gpreport(second)

        self.assertIsNotNone(report_a)
        self.assertIsNotNone(report_b)
        assert report_a is not None
        assert report_b is not None

        diff_items = build_policy_diff(report_a, report_b)

        self.assertEqual(len(diff_items), 1)
        self.assertEqual(diff_items[0].status, "Different")

    def test_raw_xml_value_changes_keep_same_setting_key(self) -> None:
        with TemporaryDirectory() as root:
            old_folder = Path(root) / "old"
            new_folder = Path(root) / "new"
            old_folder.mkdir()
            new_folder.mkdir()
            (old_folder / "settings.xml").write_text("<Root><Setting>Old</Setting></Root>", encoding="utf-8")
            (new_folder / "settings.xml").write_text("<Root><Setting>New</Setting></Root>", encoding="utf-8")

            diff_items = compare_backups(
                load_gpo_backup(str(old_folder)),
                load_gpo_backup(str(new_folder)),
            )

        self.assertEqual(len(diff_items), 1)
        self.assertEqual(diff_items[0].status.value, "changed")

    def test_preference_xml_is_parsed_as_preference_artifact(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root) / "backup"
            pref_folder = folder / "User" / "Preferences" / "Registry"
            pref_folder.mkdir(parents=True)
            pref_folder.joinpath("Registry.xml").write_text(
                """<RegistrySettings>
  <Registry name="DisableReport" uid="{111}">
    <Properties action="U" hive="HKEY_CURRENT_USER" key="Software\\OneDrive" name="DisableReport" type="REG_DWORD" value="1" />
  </Registry>
</RegistrySettings>""",
                encoding="utf-8",
            )

            backup = load_gpo_backup(str(folder))

        matches = [setting for setting in backup.settings if setting.name == "DisableReport"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].category, "Group Policy Preferences > Registry")
        self.assertIn("Software\\OneDrive", matches[0].value)
        self.assertIn("Registry value: HKEY_CURRENT_USER\\Software\\OneDrive\\DisableReport", matches[0].value)
        self.assertIn("Data: 1", matches[0].value)

    def test_preference_registry_item_level_targeting_includes_full_match_details(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root) / "backup"
            pref_folder = folder / "User" / "Preferences" / "Registry"
            pref_folder.mkdir(parents=True)
            pref_folder.joinpath("Registry.xml").write_text(
                """<RegistrySettings>
  <Registry name="OneDrive2" uid="{111}" bypassErrors="1">
    <Properties action="U" hive="HKEY_CURRENT_USER" key="Software\\Microsoft\\Windows\\CurrentVersion\\Run" name="OneDrive2" type="REG_SZ" value="&quot;C:\\Program Files\\Microsoft OneDrive\\OneDrive.exe&quot; /background" />
    <Filters>
      <FilterRegistry bool="AND" not="1" type="MATCHVALUE" subtype="SUBSTRING" hive="HKEY_LOCAL_MACHINE" key="SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" valueName="AutoAdminLogon" valueType="REG_SZ" valueData="1" min="0.0.0.0" max="0.0.0.0" gte="1" lte="0" />
    </Filters>
  </Registry>
</RegistrySettings>""",
                encoding="utf-8",
            )

            backup = load_gpo_backup(str(folder))

        matches = [setting for setting in backup.settings if setting.name == "OneDrive2"]
        self.assertEqual(len(matches), 1)
        value = matches[0].value
        self.assertIn("Registry Match (NOT)", value)
        self.assertIn("Properties", value)
        self.assertIn("Common Options", value)
        self.assertIn("Stop processing on error: No", value)
        self.assertIn("Run in logged-on user's context: No", value)
        self.assertIn("Join: AND", value)
        self.assertIn("Type: Match value", value)
        self.assertIn("Subtype: Substring", value)
        self.assertIn("Value name: AutoAdminLogon", value)
        self.assertIn("Value type: REG_SZ", value)
        self.assertIn("Value data: 1", value)
        self.assertIn("Greater than or equal: Yes", value)
        self.assertIn("Less than or equal: No", value)

    def test_preference_common_options_accept_alternate_attribute_names(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root) / "backup"
            pref_folder = folder / "User" / "Preferences" / "Registry"
            pref_folder.mkdir(parents=True)
            pref_folder.joinpath("Registry.xml").write_text(
                """<RegistrySettings>
  <Registry name="AltOptions" uid="{111}" stopOnError="0" runInLoggedOnUserSecurityContext="1" removeWhenNoLongerApplied="1" once="1">
    <Properties action="U" hive="HKEY_CURRENT_USER" key="Software\\Example" name="AltOptions" type="REG_SZ" value="1" />
  </Registry>
</RegistrySettings>""",
                encoding="utf-8",
            )

            backup = load_gpo_backup(str(folder))

        matches = [setting for setting in backup.settings if setting.name == "AltOptions"]
        self.assertEqual(len(matches), 1)
        value = matches[0].value
        self.assertIn("Stop processing on error: Yes", value)
        self.assertIn("Run in logged-on user's context: Yes", value)
        self.assertIn("Remove when no longer applied: Yes", value)
        self.assertIn("Apply once and do not reapply: Yes", value)

    def test_common_preference_xml_types_are_semantically_parsed(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root) / "backup"
            drive_folder = folder / "User" / "Preferences" / "Drives"
            printer_folder = folder / "User" / "Preferences" / "Printers"
            group_folder = folder / "Machine" / "Preferences" / "Groups"
            service_folder = folder / "Machine" / "Preferences" / "Services"
            task_folder = folder / "Machine" / "Preferences" / "ScheduledTasks"
            for path in (drive_folder, printer_folder, group_folder, service_folder, task_folder):
                path.mkdir(parents=True)

            drive_folder.joinpath("Drives.xml").write_text(
                """<Drives><Drive name="Map S" uid="{d}"><Properties action="U" letter="S:" location="\\\\server\\share" persistent="1" label="Share" /></Drive></Drives>""",
                encoding="utf-8",
            )
            printer_folder.joinpath("Printers.xml").write_text(
                """<Printers><SharedPrinter name="Front Desk" uid="{p}"><Properties action="C" path="\\\\print\\front" default="1" /></SharedPrinter></Printers>""",
                encoding="utf-8",
            )
            group_folder.joinpath("Groups.xml").write_text(
                """<Groups><Group name="Administrators" uid="{g}"><Properties action="U" groupName="Administrators"><Members><Member name="DOMAIN\\HelpDesk" action="ADD" /></Members></Properties></Group></Groups>""",
                encoding="utf-8",
            )
            service_folder.joinpath("Services.xml").write_text(
                """<NTServices><NTService name="Spooler" uid="{s}"><Properties action="U" serviceName="Spooler" startupType="Automatic" serviceAction="START" /></NTService></NTServices>""",
                encoding="utf-8",
            )
            task_folder.joinpath("ScheduledTasks.xml").write_text(
                """<ScheduledTasks><TaskV2 name="Cleanup" uid="{t}"><Properties action="U" taskName="Cleanup" appName="powershell.exe" args="-File cleanup.ps1" runAs="SYSTEM" /></TaskV2></ScheduledTasks>""",
                encoding="utf-8",
            )

            backup = load_gpo_backup(str(folder))

        values = {setting.name: setting for setting in backup.settings}
        self.assertIn("S:", values)
        self.assertIn("Location: \\\\server\\share", values["S:"].value)
        self.assertIn("Front Desk", values)
        self.assertIn("Shared path: \\\\print\\front", values["Front Desk"].value)
        self.assertIn("Administrators", values)
        self.assertIn("Member: DOMAIN\\HelpDesk (ADD)", values["Administrators"].value)
        self.assertIn("Spooler", values)
        self.assertIn("Startup type: Automatic", values["Spooler"].value)
        self.assertIn("Cleanup", values)
        self.assertIn("Command: powershell.exe", values["Cleanup"].value)
        self.assertIn("Group Policy Preferences Parser", backup.detected_parsers)

    def test_backup_manifest_filesystem_entries_are_not_policy_artifacts(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root) / "backup"
            folder.mkdir()
            folder.joinpath("Backup.xml").write_text(
                """<GroupPolicyObject xmlns:bkp="http://www.microsoft.com/GroupPolicy/GPOOperations">
  <GroupPolicyExtension>
    <FSObjectDir bkp:Path="%GPO_USER_FSPATH%\\Preferences" bkp:Location="DomainSysvol\\GPO\\User\\Preferences" />
    <FSObjectFile bkp:Path="%GPO_USER_FSPATH%\\Preferences\\Registry\\Registry.xml" bkp:Location="DomainSysvol\\GPO\\User\\Preferences\\Registry\\Registry.xml" />
  </GroupPolicyExtension>
</GroupPolicyObject>""",
                encoding="utf-8",
            )
            folder.joinpath("bkupInfo.xml").write_text(
                "<BackupInst><BackupTime>2026-06-01T09:00:00</BackupTime><GPOGuid>{111}</GPOGuid></BackupInst>",
                encoding="utf-8",
            )

            backup = load_gpo_backup(str(folder))

        self.assertFalse(any(setting.name in {"FSObjectDir", "FSObjectFile"} for setting in backup.settings))
        self.assertFalse(any(setting.name in {"BackupTime", "GPOGuid"} for setting in backup.settings))

    def test_artifact_diffs_are_included_in_backup_comparison(self) -> None:
        with TemporaryDirectory() as root:
            old_folder = Path(root) / "old"
            new_folder = Path(root) / "new"
            old_pref = old_folder / "User" / "Preferences" / "Registry"
            new_pref = new_folder / "User" / "Preferences" / "Registry"
            old_pref.mkdir(parents=True)
            new_pref.mkdir(parents=True)
            _write_preference_xml(old_pref / "Registry.xml", "DisableReport", "0")
            _write_preference_xml(new_pref / "Registry.xml", "DisableReport", "1")

            diff_items = build_backup_diff(
                load_gpo_backup(str(old_folder)),
                load_gpo_backup(str(new_folder)),
                None,
                None,
            )

        artifact_changes = [item for item in diff_items if item.key.startswith("artifact::")]
        self.assertEqual(len(artifact_changes), 1)
        self.assertEqual(artifact_changes[0].status, "Different")
        self.assertEqual(artifact_changes[0].policy_b.policy_type, "Preference")
        self.assertEqual(artifact_changes[0].scope, "User Configuration")

    def test_global_search_finds_configured_values(self) -> None:
        with TemporaryDirectory() as root:
            backup_folder = Path(root) / "Library" / "{111}"
            pref_folder = backup_folder / "User" / "Preferences" / "Registry"
            pref_folder.mkdir(parents=True)
            _write_preference_xml(pref_folder / "Registry.xml", "DisableReport", "1")

            results = search_backup_library([str(Path(root) / "Library")], "DisableReport")

        self.assertGreaterEqual(len(results), 1)
        self.assertTrue(any(result.name == "DisableReport" for result in results))

    def test_archive_restore_and_catalog_skip_archived_backups(self) -> None:
        with TemporaryDirectory() as root:
            library = Path(root) / "Library"
            backup_folder = library / "{111}"
            backup_folder.mkdir(parents=True)
            backup_folder.joinpath("bkupInfo.xml").write_text("<Backup />", encoding="utf-8")

            archived = archive_backup(str(backup_folder))
            catalog_items = scan_backup_library(str(library))
            archived_items = list_archived_backups([str(library)])

            self.assertFalse(backup_folder.exists())
            self.assertEqual(catalog_items, [])
            self.assertEqual(len(archived_items), 1)

            restored_path = restore_archived_backup(archived.archived_path)

            self.assertEqual(restored_path, str(backup_folder))
            self.assertTrue(backup_folder.exists())

    def test_purge_expired_archives_removes_old_archive(self) -> None:
        with TemporaryDirectory() as root:
            library = Path(root) / "Library"
            backup_folder = library / "{111}"
            backup_folder.mkdir(parents=True)
            archived = archive_backup(str(backup_folder))

            removed = purge_expired_archives([str(library)], 0)

            self.assertEqual(removed, 1)
            self.assertFalse(Path(archived.archived_path).exists())

    def test_permanently_delete_archived_backup(self) -> None:
        with TemporaryDirectory() as root:
            library = Path(root) / "Library"
            backup_folder = library / "{111}"
            backup_folder.mkdir(parents=True)
            archived = archive_backup(str(backup_folder))

            permanently_delete_archived_backup(archived.archived_path)

            self.assertFalse(Path(archived.archived_path).exists())

    def test_review_notes_persist_for_comparison_pair(self) -> None:
        with TemporaryDirectory() as root:
            first = str(Path(root) / "a")
            second = str(Path(root) / "b")
            save_review_notes(first, second, {
                "item": {
                    "status": "No Action Required",
                    "priority": "High",
                    "notes": "Looks good. Validated in pilot.",
                    "updated_at": "2026-06-01T10:00:00",
                }
            })

            loaded = load_review_notes(second, first)

        self.assertEqual(loaded["item"]["status"], "No Action Required")
        self.assertEqual(loaded["item"]["priority"], "High")
        self.assertIn("Looks good", loaded["item"]["notes"])


def _summary(policies: list[GpoReportPolicy]) -> GpoReportSummary:
    return GpoReportSummary(
        name="Fixture",
        domain="example.test",
        created_time="",
        modified_time="",
        computer_enabled="true",
        user_enabled="false",
        policies=policies,
    )


def _write_gpreport(folder: Path, uid: str, value: str) -> None:
    folder.joinpath("gpreport.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<GPO xmlns="http://www.microsoft.com/GroupPolicy/Settings">
  <Name>Fixture</Name>
  <Identifier><Domain>example.test</Domain></Identifier>
  <Computer>
    <Enabled>true</Enabled>
    <ExtensionData>
      <Extension xmlns:q1="http://www.microsoft.com/GroupPolicy/Settings/Registry">
        <q1:RegistrySettings>
          <q1:Registry name="EnableFeature" status="EnableFeature" uid="{uid}">
            <q1:Properties action="U" hive="HKEY_LOCAL_MACHINE" key="Software\\Example" name="EnableFeature" type="REG_DWORD" value="{value}" />
          </q1:Registry>
        </q1:RegistrySettings>
      </Extension>
    </ExtensionData>
  </Computer>
  <User><Enabled>false</Enabled></User>
</GPO>
""",
        encoding="utf-8",
    )


def _write_preference_xml(path: Path, name: str, value: str) -> None:
    path.write_text(
        f"""<RegistrySettings>
  <Registry name="{name}" uid="{{111}}">
    <Properties action="U" hive="HKEY_CURRENT_USER" key="Software\\OneDrive" name="{name}" type="REG_DWORD" value="{value}" />
  </Registry>
</RegistrySettings>""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
