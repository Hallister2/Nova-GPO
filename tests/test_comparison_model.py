from __future__ import annotations

import unittest

from app.gpo.comparison_model import (
    PolicyDiff,
    build_backup_diff,
    filter_diffs,
    policy_signature,
    setting_changes,
    states_match,
)
from app.gpo.gpo_model import GpoBackup, GpoSetting
from app.gpo.gpreport_parser import GpoReportPolicy, GpoReportSummary


def _policy(
    name: str = "Test Policy",
    state: str = "Enabled",
    policy_type: str = "Preference",
    category: str = "General",
    scope: str = "Computer Configuration",
    source: str = "gpreport.xml",
    settings: list[str] | None = None,
    explain: str = "",
    supported: str = "",
) -> GpoReportPolicy:
    return GpoReportPolicy(
        name=name,
        state=state,
        policy_type=policy_type,
        category=category,
        scope=scope,
        source=source,
        settings=settings or [],
        explain=explain,
        supported=supported,
    )


def _diff(
    status: str = "Changed",
    policy_a: GpoReportPolicy | None = None,
    policy_b: GpoReportPolicy | None = None,
    scope: str = "Computer Configuration",
    state_a: str = "Enabled",
    state_b: str = "Enabled",
    use_none_a: bool = False,
    use_none_b: bool = False,
) -> PolicyDiff:
    pa = None if use_none_a else (policy_a if policy_a is not None else _policy())
    pb = None if use_none_b else (policy_b if policy_b is not None else _policy())
    key_policy = pb or pa
    return PolicyDiff(
        status=status,
        key=f"{scope}::{key_policy.name if key_policy else 'unknown'}".lower(),
        scope=scope,
        state_a=state_a,
        state_b=state_b,
        policy_a=pa,
        policy_b=pb,
    )


class TestStatesMatch(unittest.TestCase):

    def test_same_state_matches(self) -> None:
        item = _diff(state_a="Enabled", state_b="Enabled")
        self.assertTrue(states_match(item))

    def test_different_state_does_not_match(self) -> None:
        item = _diff(state_a="Enabled", state_b="Disabled")
        self.assertFalse(states_match(item))

    def test_case_insensitive_match(self) -> None:
        item = _diff(state_a="enabled", state_b="Enabled")
        self.assertTrue(states_match(item))

    def test_empty_states_match(self) -> None:
        item = _diff(state_a="", state_b="")
        self.assertTrue(states_match(item))


class TestSettingChanges(unittest.TestCase):

    def test_missing_in_a(self) -> None:
        item = _diff(policy_b=_policy(), status="Added", use_none_a=True)
        changes = setting_changes(item)
        self.assertTrue(any("Backup A" in c for c in changes))

    def test_missing_in_b(self) -> None:
        item = _diff(policy_a=_policy(), status="Removed", use_none_b=True)
        changes = setting_changes(item)
        self.assertTrue(any("Backup B" in c for c in changes))

    def test_state_change_detected(self) -> None:
        pa = _policy(state="Enabled")
        pb = _policy(state="Disabled")
        item = _diff(policy_a=pa, policy_b=pb, state_a="Enabled", state_b="Disabled")
        changes = setting_changes(item)
        self.assertTrue(any("State changed" in c for c in changes))

    def test_added_setting_detected(self) -> None:
        pa = _policy(settings=[])
        pb = _policy(settings=["AllowRemoteDesktop: True"])
        item = _diff(policy_a=pa, policy_b=pb)
        changes = setting_changes(item)
        self.assertTrue(any("Added" in c for c in changes))

    def test_removed_setting_detected(self) -> None:
        pa = _policy(settings=["AllowRemoteDesktop: True"])
        pb = _policy(settings=[])
        item = _diff(policy_a=pa, policy_b=pb)
        changes = setting_changes(item)
        self.assertTrue(any("Removed" in c for c in changes))

    def test_collection_setting_reports_only_token_delta(self) -> None:
        pa = _policy(settings=["Websites to open in alternative browser: alpha.example.com, beta.example.com"])
        pb = _policy(settings=["Websites to open in alternative browser: alpha.example.com"])
        item = _diff(policy_a=pa, policy_b=pb)

        changes = setting_changes(item)

        self.assertEqual(
            changes,
            [
                "Removed configured value from Backup B: "
                "Websites to open in alternative browser: beta.example.com"
            ],
        )

    def test_no_changes_returns_message(self) -> None:
        p = _policy(settings=["Value: A"])
        item = _diff(policy_a=p, policy_b=p)
        changes = setting_changes(item)
        self.assertEqual(len(changes), 1)


class TestFilterDiffs(unittest.TestCase):

    def _make_items(self) -> list[PolicyDiff]:
        return [
            _diff(status="Changed", scope="Computer Configuration"),
            _diff(status="Added", scope="User Configuration"),
            _diff(status="Removed", scope="Computer Configuration"),
            _diff(status="Unchanged", scope="Computer Configuration"),
        ]

    def test_default_excludes_unchanged(self) -> None:
        items = self._make_items()
        result = filter_diffs(items)
        self.assertTrue(all(i.status != "Unchanged" for i in result))
        self.assertEqual(len(result), 3)

    def test_status_filter(self) -> None:
        items = self._make_items()
        result = filter_diffs(items, status_text="Changed")
        self.assertTrue(all(i.status == "Changed" for i in result))

    def test_scope_filter(self) -> None:
        items = self._make_items()
        result = filter_diffs(items, scope_text="User Configuration")
        self.assertTrue(all(i.scope == "User Configuration" for i in result))

    def test_search_text_filter(self) -> None:
        pa = _policy(name="Windows Defender Settings")
        pb = _policy(name="Windows Defender Settings")
        items = [
            _diff(policy_a=pa, policy_b=pb),
            _diff(policy_a=_policy(name="Unrelated Policy"), policy_b=_policy(name="Unrelated Policy")),
        ]
        result = filter_diffs(items, search_text="Defender")
        self.assertEqual(len(result), 1)


class TestPolicySignature(unittest.TestCase):

    def test_identical_policies_have_same_signature(self) -> None:
        p = _policy(settings=["Value: A", "Mode: B"])
        self.assertEqual(policy_signature(p), policy_signature(p))

    def test_different_state_produces_different_signature(self) -> None:
        pa = _policy(state="Enabled")
        pb = _policy(state="Disabled")
        self.assertNotEqual(policy_signature(pa), policy_signature(pb))

    def test_settings_order_independent(self) -> None:
        pa = _policy(settings=["B: 2", "A: 1"])
        pb = _policy(settings=["A: 1", "B: 2"])
        self.assertEqual(policy_signature(pa), policy_signature(pb))


class TestSupportingEvidence(unittest.TestCase):
    def test_raw_registry_duplicate_is_attached_as_supporting_evidence(self) -> None:
        policy_a = _policy(
            name="Websites to open in alternative browser",
            policy_type="Administrative Template",
            settings=["Websites to open in alternative browser: NewVision.elaborders.com"],
        )
        policy_b = _policy(
            name="Websites to open in alternative browser",
            policy_type="Administrative Template",
            settings=[],
        )
        report_a = _summary([policy_a])
        report_b = _summary([policy_b])
        backup_a = GpoBackup(
            path="a",
            name="A",
            settings=[
                GpoSetting(
                    key="registry::software\\policies\\google\\chrome\\browserswitcherurllist::271",
                    category="Registry Policy",
                    name="Software\\Policies\\Google\\Chrome\\BrowserSwitcherUrlList\\271",
                    value="NewVision.elaborders.com",
                    source_file="DomainSysvol/GPO/Machine/registry.pol",
                )
            ],
        )
        backup_b = GpoBackup(path="b", name="B", settings=[])

        diffs = build_backup_diff(backup_a, backup_b, report_a, report_b)

        actionable = [item for item in diffs if item.status != "Unchanged"]
        self.assertEqual(len(actionable), 1)
        self.assertEqual(actionable[0].policy_b.name, "Websites to open in alternative browser")
        self.assertTrue(actionable[0].supporting_evidence)


def _summary(policies: list[GpoReportPolicy]) -> GpoReportSummary:
    return GpoReportSummary(
        name="Test",
        domain="example.test",
        created_time="",
        modified_time="",
        computer_enabled="true",
        user_enabled="false",
        policies=policies,
    )


if __name__ == "__main__":
    unittest.main()
