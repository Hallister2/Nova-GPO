from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.gpo.archive import (
    ARCHIVE_DIR_NAME,
    ARCHIVE_META_NAME,
    archive_backup,
    list_archived_backups,
    permanently_delete_archived_backup,
    purge_expired_archives,
    restore_archived_backup,
)


def _make_backup(root: Path, name: str = "TestGPO") -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "gpreport.xml").write_text("<root/>", encoding="utf-8")
    (folder / "bkupInfo.xml").write_text("<root/>", encoding="utf-8")
    return folder


class TestArchiveBackup(unittest.TestCase):

    def test_moves_folder_to_archived(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)

            result = archive_backup(str(backup))

            self.assertFalse(backup.exists())
            archived = Path(result.archived_path)
            self.assertTrue(archived.exists())
            self.assertIn(ARCHIVE_DIR_NAME, str(archived))

    def test_writes_metadata_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)

            result = archive_backup(str(backup))

            meta_file = Path(result.archived_path) / ARCHIVE_META_NAME
            self.assertTrue(meta_file.exists())
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            self.assertIn("original_path", data)
            self.assertIn("archived_at", data)

    def test_raises_if_folder_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                archive_backup(str(Path(tmp) / "DoesNotExist"))

    def test_unique_name_on_collision(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup_a = _make_backup(root, "TestGPO")
            result_a = archive_backup(str(backup_a))

            backup_b = _make_backup(root, "TestGPO")
            result_b = archive_backup(str(backup_b))

            self.assertNotEqual(result_a.archived_path, result_b.archived_path)
            self.assertTrue(Path(result_a.archived_path).exists())
            self.assertTrue(Path(result_b.archived_path).exists())


class TestRestoreBackup(unittest.TestCase):

    def test_restores_to_original_location(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            original_path = str(backup)

            result = archive_backup(original_path)
            restored = restore_archived_backup(result.archived_path)

            self.assertEqual(restored, original_path)
            self.assertTrue(Path(original_path).exists())
            self.assertFalse(Path(result.archived_path).exists())

    def test_removes_meta_file_on_restore(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            result = archive_backup(str(backup))

            restore_archived_backup(result.archived_path)

            meta_file = Path(backup) / ARCHIVE_META_NAME
            self.assertFalse(meta_file.exists())

    def test_raises_if_archive_missing(self) -> None:
        with self.assertRaises(FileNotFoundError):
            restore_archived_backup("/nonexistent/path/backup")

    def test_raises_if_target_already_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            result = archive_backup(str(backup))
            _make_backup(root, "TestGPO")

            with self.assertRaises(FileExistsError):
                restore_archived_backup(result.archived_path)


class TestListArchivedBackups(unittest.TestCase):

    def test_lists_archived_items(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            archive_backup(str(backup))

            items = list_archived_backups([str(root)])

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].display_name, "TestGPO")

    def test_empty_when_no_archives(self) -> None:
        with TemporaryDirectory() as tmp:
            items = list_archived_backups([str(Path(tmp))])
            self.assertEqual(items, [])

    def test_status_restorable_when_original_gone(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            archive_backup(str(backup))

            items = list_archived_backups([str(root)])
            self.assertEqual(items[0].status, "Restorable")

    def test_status_conflict_when_original_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            archive_backup(str(backup))
            _make_backup(root, "TestGPO")

            items = list_archived_backups([str(root)])
            self.assertEqual(items[0].status, "Conflict")


class TestPermanentDelete(unittest.TestCase):

    def test_deletes_archived_folder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            result = archive_backup(str(backup))

            permanently_delete_archived_backup(result.archived_path)

            self.assertFalse(Path(result.archived_path).exists())

    def test_raises_if_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            permanently_delete_archived_backup("/nonexistent/archive")


class TestPurgeExpiredArchives(unittest.TestCase):

    def test_purges_old_archives(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            result = archive_backup(str(backup))

            archived_path = Path(result.archived_path)
            meta_file = archived_path / ARCHIVE_META_NAME
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            data["archived_at"] = "2000-01-01T00:00:00"
            meta_file.write_text(json.dumps(data), encoding="utf-8")

            removed = purge_expired_archives([str(root)], retention_days=30)

            self.assertEqual(removed, 1)
            self.assertFalse(archived_path.exists())

    def test_keeps_recent_archives(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            result = archive_backup(str(backup))

            removed = purge_expired_archives([str(root)], retention_days=365)

            self.assertEqual(removed, 0)
            self.assertTrue(Path(result.archived_path).exists())

    def test_zero_retention_purges_all(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            archive_backup(str(backup))

            time.sleep(0.01)
            removed = purge_expired_archives([str(root)], retention_days=0)

            self.assertEqual(removed, 1)

    def test_negative_retention_purges_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = _make_backup(root)
            archive_backup(str(backup))

            removed = purge_expired_archives([str(root)], retention_days=-1)

            self.assertEqual(removed, 0)


if __name__ == "__main__":
    unittest.main()
