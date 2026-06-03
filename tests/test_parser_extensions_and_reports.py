from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gpo.backup_loader import load_gpo_backup
from app.gpo.comparison_model import PolicyDiff
from app.gpo.gpreport_parser import GpoReportPolicy, load_gpreport
from app.reports.compare_report import csv_report, html_report, markdown_report


def _policy(policy_type: str = "Administrative Template", name: str = "Example Policy") -> GpoReportPolicy:
    return GpoReportPolicy(
        scope="Computer Configuration",
        name=name,
        state="Configured",
        category="Example",
        supported="",
        explain="",
        settings=["Value: Enabled"],
        policy_type=policy_type,
        source="fixture",
        identity=f"fixture::{policy_type}::{name}",
    )


def _diff(
    policy_type: str = "Administrative Template",
    name: str = "Example Policy",
    status: str = "Changed",
) -> PolicyDiff:
    policy = _policy(policy_type, name)
    return PolicyDiff(
        status=status,
        key=policy.identity,
        scope=policy.scope,
        state_a="Configured",
        state_b="Configured",
        policy_a=policy,
        policy_b=policy,
    )


class ParserExtensionTests(unittest.TestCase):
    def test_applocker_file_is_parsed_as_named_rules(self) -> None:
        with TemporaryDirectory() as root:
            backup = Path(root) / "backup"
            app_locker_dir = backup / "Machine" / "Microsoft" / "Windows" / "AppLocker"
            app_locker_dir.mkdir(parents=True)
            app_locker_dir.joinpath("AppLocker.xml").write_text(
                """<AppLockerPolicy>
  <RuleCollection Type="Exe" EnforcementMode="Enabled">
    <FilePathRule Id="{111}" Name="Allow Windows" Action="Allow" UserOrGroupSid="S-1-1-0">
      <Conditions><FilePathCondition Path="%WINDIR%\\*" /></Conditions>
    </FilePathRule>
  </RuleCollection>
</AppLockerPolicy>""",
                encoding="utf-8",
            )

            parsed = load_gpo_backup(str(backup))

        names = {setting.name for setting in parsed.settings}
        self.assertIn("Exe Enforcement Mode", names)
        self.assertIn("Allow Windows", names)
        self.assertTrue(any(setting.category == "AppLocker > Exe" for setting in parsed.settings))

    def test_advanced_audit_policy_extension_is_parsed(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root)
            folder.joinpath("gpreport.xml").write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<GPO xmlns="http://www.microsoft.com/GroupPolicy/Settings"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Name>Audit Fixture</Name>
  <Identifier><Domain>example.test</Domain></Identifier>
  <Computer>
    <Enabled>true</Enabled>
    <ExtensionData>
      <Extension xsi:type="AuditSettings">
        <AuditSetting>
          <SubcategoryName>Logon</SubcategoryName>
          <SubcategoryGuid>{111}</SubcategoryGuid>
          <SettingValue>3</SettingValue>
        </AuditSetting>
      </Extension>
    </ExtensionData>
  </Computer>
  <User><Enabled>false</Enabled></User>
</GPO>""",
                encoding="utf-8",
            )

            report = load_gpreport(str(folder))

        self.assertIsNotNone(report)
        assert report is not None
        matches = [policy for policy in report.policies if policy.name == "Logon"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].category, "Security Setting > Advanced Audit Policy")
        self.assertIn("Success and Failure", matches[0].settings)

    def test_firewall_extension_is_parsed_as_rules(self) -> None:
        with TemporaryDirectory() as root:
            folder = Path(root)
            folder.joinpath("gpreport.xml").write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<GPO xmlns="http://www.microsoft.com/GroupPolicy/Settings"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Name>Firewall GPO</Name>
  <Identifier><Domain>example.test</Domain></Identifier>
  <Computer>
    <Enabled>true</Enabled>
    <ExtensionData>
      <Extension xsi:type="Firewall">
        <FirewallRule>
          <Name>Allow HTTPS</Name>
          <Enabled>true</Enabled>
          <Action>Allow</Action>
          <Direction>Inbound</Direction>
          <Protocol>TCP</Protocol>
          <LocalPorts>443</LocalPorts>
        </FirewallRule>
      </Extension>
    </ExtensionData>
  </Computer>
  <User><Enabled>false</Enabled></User>
</GPO>""",
                encoding="utf-8",
            )

            report = load_gpreport(str(folder))

        assert report is not None
        matches = [policy for policy in report.policies if policy.name == "Allow HTTPS"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].policy_type, "Firewall Rule")
        self.assertEqual(matches[0].category, "Firewall Rules")
        self.assertIn("Local ports: 443", matches[0].settings)


class ReportProfileTests(unittest.TestCase):
    def test_executive_markdown_omits_per_policy_sections(self) -> None:
        report = markdown_report("A", "B", [_diff(name="Per Policy")], profile="executive")

        self.assertIn("## Executive Summary", report)
        self.assertNotIn("### Per Policy", report)

    def test_executive_csv_is_metric_based(self) -> None:
        report = csv_report("A", "B", [_diff()], profile="executive")

        self.assertTrue(report.startswith("Metric,Value"))
        self.assertIn("Total compared,1", report)
        self.assertIn("Actionable findings,1", report)

    def test_html_profile_changes_heading(self) -> None:
        report = html_report("A", "B", [_diff(policy_type="Artifact")], profile="raw")

        self.assertIn("<h2>Raw Inventory</h2>", report)

    def test_html_report_uses_compare_window_style_sections(self) -> None:
        diff = [_diff(policy_type="Administrative Template", name="Browser Policy")]
        report = html_report(
            "A",
            "B",
            diff,
            {
                diff[0].key: {
                    "status": "Update Required",
                    "priority": "High",
                    "notes": "Validate before rollout. Ticket CHG789.",
                }
            },
        )

        self.assertIn("Actual Delta", report)
        self.assertIn("Compared Values", report)
        self.assertIn("Backup A", report)
        self.assertIn("Backup B", report)
        self.assertIn("CHG789", report)

    def test_standard_reports_omit_unchanged_inventory_items(self) -> None:
        report = markdown_report(
            "A",
            "B",
            [
                _diff(name="Changed Policy"),
                _diff(name="Same Policy", status="Unchanged"),
            ],
        )

        self.assertIn("Changed Policy", report)
        self.assertNotIn("Same Policy", report)
        self.assertIn("2 total items", report)
        self.assertIn("1 actionable", report)

    def test_raw_profile_includes_unchanged_inventory_items(self) -> None:
        report = html_report(
            "A",
            "B",
            [_diff(name="Same Policy", status="Unchanged")],
            profile="raw",
        )

        self.assertIn("Raw Inventory", report)
        self.assertIn("Same Policy", report)


if __name__ == "__main__":
    unittest.main()
