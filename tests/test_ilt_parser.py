from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from app.gpo.ilt_parser import ILT_HEADER, format_filters, has_targeting


class TestItemLevelTargetingParser(unittest.TestCase):

    def test_registry_match_emits_full_gpmc_attributes(self) -> None:
        filters = ET.fromstring(
            """<Filters>
  <FilterRegistry bool="AND" not="1" type="MATCHVALUE" subtype="SUBSTRING"
    hive="HKEY_LOCAL_MACHINE"
    key="SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon"
    valueName="AutoAdminLogon" valueType="REG_SZ" valueData="1"
    min="0.0.0.0" max="0.0.0.0" gte="1" lte="0" />
</Filters>"""
        )

        lines = format_filters(filters)

        self.assertEqual(lines[0], ILT_HEADER)
        joined = "\n".join(lines)
        self.assertIn("Registry Match (NOT)", joined)
        self.assertIn("Join: AND", joined)
        self.assertIn("Negated: Yes", joined)
        self.assertIn("Type: Match value", joined)
        self.assertIn("Subtype: Substring", joined)
        self.assertIn("Hive: HKEY_LOCAL_MACHINE", joined)
        self.assertIn("Key: SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon", joined)
        self.assertIn("Value name: AutoAdminLogon", joined)
        self.assertIn("Value type: REG_SZ", joined)
        self.assertIn("Value data: 1", joined)
        self.assertIn("Minimum: 0.0.0.0", joined)
        self.assertIn("Maximum: 0.0.0.0", joined)
        self.assertIn("Greater than or equal: Yes", joined)
        self.assertIn("Less than or equal: No", joined)

    def test_multiple_registry_matches_keep_each_rule_separate(self) -> None:
        filters = ET.fromstring(
            """<Filters>
  <FilterRegistry bool="AND" not="0" type="MATCHVALUE" hive="HKLM" key="Software\\A" valueName="Flag" valueType="REG_SZ" valueData="1" />
  <FilterRegistry bool="AND" not="0" type="KEYEXISTS" hive="HKCU" key="Software\\B" valueName="" valueType="" valueData="" />
</Filters>"""
        )

        lines = format_filters(filters)

        self.assertEqual(sum(1 for line in lines if "Registry Match" in line), 2)
        joined = "\n".join(lines)
        self.assertIn("Type: Match value", joined)
        self.assertIn("Type: Key exists", joined)
        self.assertIn("Key: Software\\A", joined)
        self.assertIn("Key: Software\\B", joined)

    def test_common_targeting_types_emit_structured_attributes(self) -> None:
        filters = ET.fromstring(
            """<Filters>
  <FilterWmi bool="AND" not="0" namespace="root\\CIMv2" query="select * from Win32_OperatingSystem" />
  <FilterFile bool="OR" not="1" type="EXISTS" path="C:\\Temp\\flag.txt" version="1.2.3" />
  <FilterGroup bool="AND" not="0" name="DOMAIN\\HelpDesk" sid="S-1-5-21-1" userContext="1" />
</Filters>"""
        )

        joined = "\n".join(format_filters(filters))

        self.assertIn("WMI Match", joined)
        self.assertIn("Namespace: root\\CIMv2", joined)
        self.assertIn("Query: select * from Win32_OperatingSystem", joined)
        self.assertIn("File Match (NOT)", joined)
        self.assertIn("Path: C:\\Temp\\flag.txt", joined)
        self.assertIn("Security Group Match", joined)
        self.assertIn("Name: DOMAIN\\HelpDesk", joined)
        self.assertIn("User context: Yes", joined)

    def test_discovered_backup_targeting_types_have_friendly_labels(self) -> None:
        filters = ET.fromstring(
            """<Filters>
  <FilterOrgUnit bool="AND" not="1" name="OU=Workstations,DC=example,DC=test" userContext="1" directMember="0" />
  <FilterRunOnce bool="AND" not="0" id="{111}" hidden="1" />
  <FilterVariable bool="AND" not="0" variableName="LogonServer" value="DC01" />
  <FilterOs bool="OR" not="0" type="NE" class="NT" version="10.0" edition="Professional" sp="0" hidden="1" />
  <FilterComputer bool="AND" not="0" type="NETBIOS" name="PC*" />
</Filters>"""
        )

        joined = "\n".join(format_filters(filters))

        self.assertIn("Organizational Unit Match (NOT)", joined)
        self.assertIn("Direct member: No", joined)
        self.assertIn("Run Once Match", joined)
        self.assertIn("Hidden: Yes", joined)
        self.assertIn("Environment Variable Match", joined)
        self.assertIn("Variable name: LogonServer", joined)
        self.assertIn("Operating System", joined)
        self.assertIn("Type: Not equal", joined)
        self.assertIn("Service pack: 0", joined)
        self.assertIn("Computer Match", joined)
        self.assertIn("Type: NetBIOS", joined)

    def test_nested_filter_collection_emits_group_metadata_and_child_rules(self) -> None:
        filters = ET.fromstring(
            """<Filters>
  <FilterCollection bool="OR" not="1" hidden="1">
    <FilterGroup bool="AND" not="0" name="DOMAIN\\HelpDesk" userContext="1" />
    <FilterFile bool="OR" not="0" type="EXISTS" path="C:\\Temp\\flag.txt" />
  </FilterCollection>
</Filters>"""
        )

        lines = format_filters(filters)
        joined = "\n".join(lines)

        self.assertIn("Targeting Group (NOT)", joined)
        self.assertIn("Join: OR", joined)
        self.assertIn("Negated: Yes", joined)
        self.assertIn("Hidden: Yes", joined)
        self.assertIn("Security Group Match", joined)
        self.assertIn("Name: DOMAIN\\HelpDesk", joined)
        self.assertIn("File Match", joined)
        self.assertIn("Path: C:\\Temp\\flag.txt", joined)

    def test_gpmc_filter_metadata_is_not_item_level_targeting(self) -> None:
        gpo = ET.fromstring(
            """<GPO>
  <FilterDataAvailable>true</FilterDataAvailable>
  <FilterName>Windows 11</FilterName>
  <FilterDescription>Target Windows 11 OS</FilterDescription>
</GPO>"""
        )

        self.assertFalse(has_targeting(gpo))
        self.assertEqual(format_filters(gpo), [])


if __name__ == "__main__":
    unittest.main()
