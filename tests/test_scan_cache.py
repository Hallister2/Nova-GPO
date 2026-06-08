import unittest
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gpo.backup_catalog import BackupCatalogItem
from app.gpo import scan_cache


class ScanCacheTests(unittest.TestCase):
    def test_round_trips_matching_roots(self) -> None:
        original_path = scan_cache.SCAN_CACHE_PATH
        with TemporaryDirectory() as tmp:
            try:
                scan_cache.SCAN_CACHE_PATH = Path(tmp) / "scan_cache.json"
                roots = [str(Path(tmp) / "Backups")]
                items = [
                    BackupCatalogItem(
                        source_index=1,
                        source_path=roots[0],
                        display_name="Policy A",
                        folder_name="{GUID}",
                        path=str(Path(tmp) / "Backups" / "{GUID}"),
                        is_valid=True,
                        status="Valid",
                        detail="OK",
                        domain="example.test",
                        backup_time="2026-06-01T12:00:00",
                        item_count=12,
                    )
                ]

                scan_cache.save_scan_cache(roots, items, 1.234, ["warning"])
                loaded = scan_cache.load_scan_cache(roots)

                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.items, items)
                self.assertEqual(loaded.errors, ["warning"])
                self.assertEqual(loaded.elapsed_seconds, 1.234)
                self.assertFalse(loaded.is_stale)
            finally:
                scan_cache.SCAN_CACHE_PATH = original_path

    def test_ignores_cache_for_different_roots(self) -> None:
        original_path = scan_cache.SCAN_CACHE_PATH
        with TemporaryDirectory() as tmp:
            try:
                scan_cache.SCAN_CACHE_PATH = Path(tmp) / "scan_cache.json"
                roots = [str(Path(tmp) / "Backups")]
                other_roots = [str(Path(tmp) / "OtherBackups")]

                scan_cache.save_scan_cache(roots, [], 0.1)

                self.assertIsNone(scan_cache.load_scan_cache(other_roots))
            finally:
                scan_cache.SCAN_CACHE_PATH = original_path

    def test_marks_cache_stale_when_source_fingerprint_changes(self) -> None:
        original_path = scan_cache.SCAN_CACHE_PATH
        with TemporaryDirectory() as tmp:
            try:
                scan_cache.SCAN_CACHE_PATH = Path(tmp) / "scan_cache.json"
                root = Path(tmp) / "Backups"
                root.mkdir()
                (root / "{FIRST}").mkdir()
                roots = [str(root)]

                scan_cache.save_scan_cache(roots, [], 0.1)
                time.sleep(0.01)
                (root / "{SECOND}").mkdir()

                loaded = scan_cache.load_scan_cache(roots)

                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertTrue(loaded.is_stale)
            finally:
                scan_cache.SCAN_CACHE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
