import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from application.services.backup_service import BackupService


class BackupServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "league_mastery_tracker.db"
        )

        self.backup_directory = (
            self.root_directory
            / "backups"
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            DATABASE_FILE=str(
                self.database_file
            ),
            BACKUP_DIR=str(
                self.backup_directory
            ),
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        self._create_test_database()

    def tearDown(self):
        self.app_context.pop()
        self.temporary_directory.cleanup()

    def _create_test_database(self):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            connection.execute(
                """
                CREATE TABLE test_records (
                    id INTEGER PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                INSERT INTO test_records (
                    value
                )
                VALUES (
                    ?
                )
                """,
                (
                    "backup-test",
                ),
            )

            connection.commit()

        finally:
            connection.close()

    def test_create_backup_contains_database_data(self):
        result = BackupService.create_backup()

        self.assertTrue(
            result["created"]
        )

        backup_file = result[
            "backup_file"
        ]

        self.assertTrue(
            backup_file.exists()
        )

        connection = sqlite3.connect(
            str(backup_file)
        )

        try:
            row = connection.execute(
                """
                SELECT value
                FROM test_records
                WHERE id = 1
                """
            ).fetchone()

        finally:
            connection.close()

        self.assertEqual(
            row,
            (
                "backup-test",
            ),
        )

    def test_recent_backup_prevents_another_backup(self):
        first_result = (
            BackupService.create_backup_if_due(
                max_age_hours=24
            )
        )

        second_result = (
            BackupService.create_backup_if_due(
                max_age_hours=24
            )
        )

        self.assertTrue(
            first_result["created"]
        )

        self.assertFalse(
            second_result["created"]
        )

        self.assertEqual(
            second_result["reason"],
            "recent_backup_exists",
        )

        self.assertEqual(
            second_result["backup_file"],
            first_result["backup_file"],
        )

        self.assertEqual(
            len(
                BackupService.get_backup_files()
            ),
            1,
        )

    def test_old_backups_are_removed_by_retention(self):
        self.backup_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        for index in range(4):
            backup_file = (
                self.backup_directory
                / (
                    "league_mastery_tracker_"
                    f"20260101T00000{index}Z.db"
                )
            )

            connection = sqlite3.connect(
                str(backup_file)
            )

            connection.close()

            modified_time = 1000 + index

            os.utime(
                backup_file,
                (
                    modified_time,
                    modified_time,
                ),
            )

        result = BackupService.create_backup(
            retention_count=2
        )

        remaining_backups = (
            BackupService.get_backup_files()
        )

        self.assertTrue(
            result["created"]
        )

        self.assertEqual(
            result["deleted_old_backups"],
            3,
        )

        self.assertEqual(
            len(remaining_backups),
            2,
        )

        self.assertIn(
            result["backup_file"],
            remaining_backups,
        )


if __name__ == "__main__":
    unittest.main()