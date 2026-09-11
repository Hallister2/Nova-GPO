from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.review_store import (
    _merge_old_notes,
    _migrate_disposition,
    _migrate_impact,
    load_review_notes,
    save_review_notes,
)


class TestMigrateDisposition(unittest.TestCase):
    def test_approved_maps_to_no_action_required(self) -> None:
        self.assertEqual(_migrate_disposition("Approved"), "No Action Required")

    def test_needs_review_maps_to_make_changes_to_a(self) -> None:
        self.assertEqual(_migrate_disposition("Needs Review"), "Make Changes to A")

    def test_risk_accepted_maps_to_no_action_required(self) -> None:
        self.assertEqual(_migrate_disposition("Risk Accepted"), "No Action Required")

    def test_rollback_candidate_maps_to_escalated(self) -> None:
        self.assertEqual(_migrate_disposition("Rollback Candidate"), "Escalated")

    def test_not_reviewed_maps_to_pending_review(self) -> None:
        self.assertEqual(_migrate_disposition("Not Reviewed"), "Pending Review")

    def test_unknown_value_defaults_to_pending_review(self) -> None:
        self.assertEqual(_migrate_disposition("Something Else"), "Pending Review")

    def test_empty_string_defaults_to_pending_review(self) -> None:
        self.assertEqual(_migrate_disposition(""), "Pending Review")


class TestMigrateImpact(unittest.TestCase):
    def test_known_levels_pass_through(self) -> None:
        for level in ("Low", "Medium", "High", "Critical"):
            self.assertEqual(_migrate_impact(level), level)

    def test_unknown_level_defaults_to_normal(self) -> None:
        self.assertEqual(_migrate_impact("Unknown"), "Normal")

    def test_empty_string_defaults_to_normal(self) -> None:
        self.assertEqual(_migrate_impact(""), "Normal")


class TestMergeOldNotes(unittest.TestCase):
    def test_merges_present_fields_in_order(self) -> None:
        value = {"owner": "Alice", "ticket": "TCK-1", "note": "Looks fine", "points": "5"}
        self.assertEqual(_merge_old_notes(value), "Alice\nTCK-1\nLooks fine\n5")

    def test_skips_blank_fields(self) -> None:
        value = {"owner": "Alice", "ticket": "", "note": "  ", "points": "5"}
        self.assertEqual(_merge_old_notes(value), "Alice\n5")

    def test_no_fields_present_returns_empty_string(self) -> None:
        self.assertEqual(_merge_old_notes({}), "")


class TestLoadReviewNotesMigration(unittest.TestCase):
    def test_missing_file_returns_empty_dict(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_review_dir = Path(tmp) / "Reviews"
            with patch("app.review_store.REVIEW_DIR", fake_review_dir), \
                 patch("app.review_store.LEGACY_REVIEW_DIR", Path(tmp) / "legacy"):
                self.assertEqual(load_review_notes("A", "B"), {})

    def test_round_trips_current_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_review_dir = Path(tmp) / "Reviews"
            with patch("app.review_store.REVIEW_DIR", fake_review_dir), \
                 patch("app.review_store.LEGACY_REVIEW_DIR", Path(tmp) / "legacy"):
                notes = {
                    "finding-1": {
                        "status": "Escalated",
                        "priority": "High",
                        "owner": "Bob",
                        "ticket": "TCK-9",
                        "tags": "urgent",
                        "notes": "Needs follow-up",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                }
                save_review_notes("A", "B", notes)

                loaded = load_review_notes("A", "B")

                self.assertEqual(loaded["finding-1"]["status"], "Escalated")
                self.assertEqual(loaded["finding-1"]["priority"], "High")
                self.assertEqual(loaded["finding-1"]["owner"], "Bob")

    def test_migrates_legacy_disposition_and_impact_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_review_dir = Path(tmp) / "Reviews"
            fake_review_dir.mkdir(parents=True)
            with patch("app.review_store.REVIEW_DIR", fake_review_dir), \
                 patch("app.review_store.LEGACY_REVIEW_DIR", Path(tmp) / "legacy"):
                from app.review_store import _review_path

                path = _review_path("A", "B")
                payload = {
                    "backup_a": "A",
                    "backup_b": "B",
                    "notes": {
                        "finding-1": {
                            "disposition": "Rollback Candidate",
                            "impact": "High",
                            "owner": "Carol",
                            "ticket": "TCK-3",
                            "note": "Old-style note",
                            "points": "3",
                        }
                    },
                }
                path.write_text(json.dumps(payload), encoding="utf-8")

                loaded = load_review_notes("A", "B")

                self.assertEqual(loaded["finding-1"]["status"], "Escalated")
                self.assertEqual(loaded["finding-1"]["priority"], "High")
                self.assertIn("Carol", loaded["finding-1"]["notes"])
                self.assertIn("Old-style note", loaded["finding-1"]["notes"])

    def test_falls_back_to_legacy_path_when_current_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_review_dir = Path(tmp) / "Reviews"
            fake_legacy_dir = Path(tmp) / "legacy"
            fake_legacy_dir.mkdir(parents=True)
            with patch("app.review_store.REVIEW_DIR", fake_review_dir), \
                 patch("app.review_store.LEGACY_REVIEW_DIR", fake_legacy_dir):
                from app.review_store import _legacy_review_path

                legacy_path = _legacy_review_path("A", "B")
                legacy_path.write_text(
                    json.dumps({"notes": {"finding-1": {"status": "Escalated"}}}),
                    encoding="utf-8",
                )

                loaded = load_review_notes("A", "B")

                self.assertEqual(loaded["finding-1"]["status"], "Escalated")

    def test_malformed_json_returns_empty_dict(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_review_dir = Path(tmp) / "Reviews"
            fake_review_dir.mkdir(parents=True)
            with patch("app.review_store.REVIEW_DIR", fake_review_dir), \
                 patch("app.review_store.LEGACY_REVIEW_DIR", Path(tmp) / "legacy"):
                from app.review_store import _review_path

                path = _review_path("A", "B")
                path.write_text("{not valid json", encoding="utf-8")

                self.assertEqual(load_review_notes("A", "B"), {})

    def test_non_dict_entries_are_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            fake_review_dir = Path(tmp) / "Reviews"
            fake_review_dir.mkdir(parents=True)
            with patch("app.review_store.REVIEW_DIR", fake_review_dir), \
                 patch("app.review_store.LEGACY_REVIEW_DIR", Path(tmp) / "legacy"):
                from app.review_store import _review_path

                path = _review_path("A", "B")
                path.write_text(
                    json.dumps({"notes": {"finding-1": "not a dict", "finding-2": {"status": "Escalated"}}}),
                    encoding="utf-8",
                )

                loaded = load_review_notes("A", "B")

                self.assertNotIn("finding-1", loaded)
                self.assertIn("finding-2", loaded)


if __name__ == "__main__":
    unittest.main()
