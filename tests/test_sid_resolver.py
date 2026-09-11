from __future__ import annotations

import unittest

from app.gpo.sid_resolver import resolve_privilege_name, resolve_sid, resolve_sid_list


class TestResolveSid(unittest.TestCase):
    def test_well_known_sid_resolves_by_name(self) -> None:
        self.assertEqual(resolve_sid("S-1-1-0"), "Everyone")

    def test_builtin_admins_sid_resolves(self) -> None:
        self.assertEqual(resolve_sid("S-1-5-32-544"), "BUILTIN\\Administrators")

    def test_lookup_is_case_insensitive(self) -> None:
        self.assertEqual(resolve_sid("s-1-1-0"), "Everyone")

    def test_unknown_sid_without_api_falls_back_to_original(self) -> None:
        unknown = "S-1-5-21-111111111-222222222-333333333-1001"
        self.assertEqual(resolve_sid(unknown, use_api=False), unknown)

    def test_whitespace_is_trimmed(self) -> None:
        self.assertEqual(resolve_sid("  S-1-1-0  "), "Everyone")


class TestResolvePrivilegeName(unittest.TestCase):
    def test_known_privilege_resolves(self) -> None:
        self.assertEqual(
            resolve_privilege_name("SeInteractiveLogonRight"),
            "Allow log on locally",
        )

    def test_unknown_privilege_falls_back_to_original(self) -> None:
        self.assertEqual(resolve_privilege_name("SeSomeMadeUpRight"), "SeSomeMadeUpRight")

    def test_privilege_name_is_trimmed(self) -> None:
        self.assertEqual(
            resolve_privilege_name("  SeShutdownPrivilege  "),
            "Shut down the system",
        )


class TestResolveSidList(unittest.TestCase):
    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(resolve_sid_list(""), "")

    def test_whitespace_only_returns_empty(self) -> None:
        self.assertEqual(resolve_sid_list("   "), "")

    def test_single_sid_with_asterisk_marker(self) -> None:
        self.assertEqual(resolve_sid_list("*S-1-5-32-544"), "BUILTIN\\Administrators")

    def test_multiple_sids_resolve_in_order(self) -> None:
        self.assertEqual(
            resolve_sid_list("*S-1-5-32-544,*S-1-1-0"),
            "BUILTIN\\Administrators, Everyone",
        )

    def test_non_sid_tokens_pass_through_unchanged(self) -> None:
        self.assertEqual(
            resolve_sid_list("*S-1-1-0,Administrators"),
            "Everyone, Administrators",
        )

    def test_unknown_sid_in_list_falls_back_to_original(self) -> None:
        unknown = "S-1-5-21-999-999-999-1001"
        self.assertEqual(resolve_sid_list(f"*{unknown}"), unknown)


if __name__ == "__main__":
    unittest.main()
