from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import app.library_store as library_store
from app.gpo.comparison_model import PolicyDiff
from app.gpo.gpreport_parser import GpoReportPolicy


class TestCompareLibraryStore(unittest.TestCase):
    def test_saved_compare_record_survives_missing_source_backups(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                backup_a = Path(root) / "backup-a"
                backup_b = Path(root) / "backup-b"
                backup_a.mkdir()
                backup_b.mkdir()

                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(backup_a),
                    backup_b_path=str(backup_b),
                    diff_items=[_diff()],
                    review_notes={"Test Policy": {"status": "No Action Required", "notes": "Reviewed."}},
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                self.assertTrue(Path(record.html_path).exists())
                self.assertEqual(record.source_status, "Sources available")

                backup_a.rmdir()
                backup_b.rmdir()
                records = library_store.list_compare_records()

                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].title, "Baseline vs Candidate")
                self.assertEqual(records[0].source_status, "Sources missing")
                self.assertEqual(records[0].reviewed, 1)
                self.assertEqual(records[0].actionable, 0)
                self.assertEqual(records[0].ignored, 1)
                self.assertTrue(Path(records[0].html_path).exists())
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir

    def test_compare_record_index_is_written_and_used(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(Path(root) / "backup-a"),
                    backup_b_path=str(Path(root) / "backup-b"),
                    diff_items=[_diff("Password Policy")],
                    review_notes={},
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                index_path = library_store.COMPARE_ARCHIVE_DIR / library_store.COMPARE_INDEX_NAME
                self.assertTrue(index_path.exists())

                records = library_store.list_compare_records()

                self.assertEqual(records[0].record_id, record.record_id)
                self.assertEqual(records[0].risk_counts.get("Security"), 1)
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir

    def test_delete_compare_record_removes_saved_review_folder(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                backup_a = Path(root) / "backup-a"
                backup_b = Path(root) / "backup-b"
                backup_a.mkdir()
                backup_b.mkdir()

                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(backup_a),
                    backup_b_path=str(backup_b),
                    diff_items=[_diff()],
                    review_notes={},
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                library_store.delete_compare_record(record.record_path)

                self.assertFalse(Path(record.record_path).exists())
                self.assertEqual(library_store.list_compare_records(), [])
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir

    def test_saved_compare_record_separates_findings_from_inventory(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(Path(root) / "backup-a"),
                    backup_b_path=str(Path(root) / "backup-b"),
                    diff_items=[_diff("Changed Policy"), _diff("Same Policy", status="Unchanged")],
                    review_notes={},
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                payload = json.loads(Path(record.record_path).read_text(encoding="utf-8"))

                self.assertEqual(payload["summary"]["total_items"], 2)
                self.assertEqual(payload["summary"]["actionable"], 1)
                self.assertEqual(payload["summary"]["ignored"], 0)
                self.assertEqual(payload["schema_version"], library_store.COMPARE_SCHEMA_VERSION)
                self.assertEqual([item["name"] for item in payload["findings"]], ["Changed Policy"])
                self.assertEqual(len(payload["inventory"]), 2)
                self.assertIn("changes", payload["findings"][0])
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir

    def test_update_compare_record_reviews_edits_saved_findings(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(Path(root) / "backup-a"),
                    backup_b_path=str(Path(root) / "backup-b"),
                    diff_items=[_diff("Changed Policy")],
                    review_notes={},
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                library_store.update_compare_record_reviews(
                    record.record_path,
                    {"Changed Policy": {"status": "No Action Required", "priority": "Normal", "notes": "Done."}},
                )
                payload = library_store.load_compare_record_payload(record.record_path)

                self.assertEqual(payload["findings"][0]["review"]["status"], "No Action Required")
                self.assertEqual(payload["summary"]["reviewed"], 1)
                self.assertEqual(payload["summary"]["actionable"], 0)
                self.assertEqual(payload["summary"]["ignored"], 1)
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir

    def test_actionable_count_excludes_no_action_required_reviews(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(Path(root) / "backup-a"),
                    backup_b_path=str(Path(root) / "backup-b"),
                    diff_items=[
                        _diff("No Action Policy"),
                        _diff("Pending Policy"),
                    ],
                    review_notes={
                        "No Action Policy": {
                            "status": "No Action Required",
                            "priority": "Normal",
                            "notes": "Reviewed.",
                        }
                    },
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                payload = library_store.load_compare_record_payload(record.record_path)
                records = library_store.list_compare_records()

                self.assertEqual(payload["summary"]["actionable"], 1)
                self.assertEqual(payload["summary"]["ignored"], 1)
                self.assertEqual(records[0].actionable, 1)
                self.assertEqual(records[0].ignored, 1)
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir

    def test_list_compare_records_repairs_stale_summary_counts(self) -> None:
        with TemporaryDirectory() as root:
            original_dir = library_store.COMPARE_ARCHIVE_DIR
            library_store.COMPARE_ARCHIVE_DIR = Path(root) / "library" / "compares"
            try:
                record = library_store.save_compare_record(
                    title_a="Baseline",
                    title_b="Candidate",
                    backup_a_path=str(Path(root) / "backup-a"),
                    backup_b_path=str(Path(root) / "backup-b"),
                    diff_items=[_diff("No Action Policy"), _diff("Pending Policy")],
                    review_notes={
                        "No Action Policy": {
                            "status": "No Action Required",
                            "priority": "Normal",
                            "notes": "Done.",
                        }
                    },
                    html_report="<html>report</html>",
                    markdown_report="# report",
                )

                payload = library_store.load_compare_record_payload(record.record_path)
                payload["summary"]["actionable"] = 2
                payload["summary"].pop("ignored", None)
                Path(record.record_path).write_text(json.dumps(payload), encoding="utf-8")

                records = library_store.list_compare_records()
                repaired = library_store.load_compare_record_payload(record.record_path)

                self.assertEqual(records[0].actionable, 1)
                self.assertEqual(records[0].ignored, 1)
                self.assertEqual(repaired["summary"]["actionable"], 1)
                self.assertEqual(repaired["summary"]["ignored"], 1)
            finally:
                library_store.COMPARE_ARCHIVE_DIR = original_dir


def _diff(name: str = "Test Policy", status: str = "Different") -> PolicyDiff:
    policy = GpoReportPolicy(
        scope="Computer Configuration",
        name=name,
        state="Enabled",
        category="Administrative Template",
        supported="Windows",
        explain="",
        settings=["Value: A"],
    )
    return PolicyDiff(
        status=status,
        key=name,
        scope="Computer Configuration",
        state_a="Enabled",
        state_b="Enabled",
        policy_a=policy,
        policy_b=policy,
    )


if __name__ == "__main__":
    unittest.main()
