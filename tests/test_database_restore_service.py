import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.services.database_restore_service import (
    DatabaseRestoreError,
    DatabaseRestoreService,
)


class DatabaseRestoreServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "live.db"
        )

        self.backup_directory = (
            self.root_directory
            / "backups"
        )

        self.configuration_directory = (
            self.root_directory
            / "configuration"
        )

        self.backup_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.configuration_directory.mkdir(
            parents=True,
            exist_ok=True,
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
            CONFIG_DIR=str(
                self.configuration_directory
            ),
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()
        self.temporary_directory.cleanup()

    def _create_database(
        self,
        database_file,
        value,
        schema_version=1,
        include_metadata=True,
    ):
        connection = sqlite3.connect(
            str(database_file)
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
                    value,
                ),
            )

            if include_metadata:
                connection.execute(
                    """
                    CREATE TABLE application_metadata (
                        key TEXT PRIMARY KEY NOT NULL,
                        value TEXT NOT NULL
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO application_metadata (
                        key,
                        value
                    )
                    VALUES (
                        ?,
                        ?
                    )
                    """,
                    (
                        "database_schema_version",
                        str(schema_version),
                    ),
                )

            connection.commit()

        finally:
            connection.close()

    def _create_backup(
        self,
        file_name,
        value="restore-test-data",
        schema_version=1,
        include_metadata=True,
    ):
        backup_file = (
            self.backup_directory
            / file_name
        )

        self._create_database(
            database_file=backup_file,
            value=value,
            schema_version=schema_version,
            include_metadata=include_metadata,
        )

        return backup_file

    @staticmethod
    def _read_value(
        database_file,
    ):
        connection = sqlite3.connect(
            str(database_file)
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

        return row[0]

    def test_valid_internal_backup_is_accepted(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120000000000Z.db"
        )

        backup_file = self._create_backup(
            file_name=file_name,
        )

        result = (
            DatabaseRestoreService.validate_backup(
                file_name
            )
        )

        self.assertTrue(
            result["valid"]
        )

        self.assertEqual(
            result["file_path"],
            backup_file.resolve(),
        )

        self.assertEqual(
            result["schema_version"],
            1,
        )

        self.assertFalse(
            result["unversioned"]
        )

    def test_unversioned_internal_backup_is_accepted(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120001000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
            include_metadata=False,
        )

        result = (
            DatabaseRestoreService.validate_backup(
                file_name
            )
        )

        self.assertTrue(
            result["valid"]
        )

        self.assertIsNone(
            result["schema_version"]
        )

        self.assertTrue(
            result["unversioned"]
        )

    def test_corrupted_backup_is_rejected(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120002000000Z.db"
        )

        (
            self.backup_directory
            / file_name
        ).write_bytes(
            b"this-is-not-a-sqlite-database"
        )

        with self.assertRaises(
            DatabaseRestoreError
        ):
            (
                DatabaseRestoreService
                .validate_backup(
                    file_name
                )
            )

    def test_newer_schema_backup_is_rejected(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120003000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
            schema_version=999,
        )

        with self.assertRaises(
            DatabaseRestoreError
        ):
            (
                DatabaseRestoreService
                .validate_backup(
                    file_name
                )
            )

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(
            DatabaseRestoreError
        ):
            (
                DatabaseRestoreService
                .validate_backup(
                    "../league_mastery_tracker_"
                    "20260716T120004000000Z.db"
                )
            )

    def test_restore_candidates_report_invalid_files_safely(self):
        valid_file_name = (
            "league_mastery_tracker_"
            "20260716T120005000000Z.db"
        )

        invalid_file_name = (
            "league_mastery_tracker_"
            "20260716T120006000000Z.db"
        )

        self._create_backup(
            file_name=valid_file_name,
        )

        (
            self.backup_directory
            / invalid_file_name
        ).write_bytes(
            b"damaged"
        )

        candidates = (
            DatabaseRestoreService
            .get_restore_candidates()
        )

        candidates_by_name = {
            candidate["file_name"]: candidate
            for candidate in candidates
        }

        self.assertTrue(
            candidates_by_name[
                valid_file_name
            ]["valid"]
        )

        self.assertFalse(
            candidates_by_name[
                invalid_file_name
            ]["valid"]
        )

    def test_valid_backup_can_be_staged(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120007000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
            value="staged-data",
        )

        pending_restore = (
            DatabaseRestoreService.stage_restore(
                file_name
            )
        )

        self.assertEqual(
            pending_restore[
                "source_backup_file_name"
            ],
            file_name,
        )

        self.assertTrue(
            pending_restore[
                "staged_file_path"
            ].exists()
        )

        self.assertEqual(
            len(pending_restore["sha256"]),
            64,
        )

        self.assertTrue(
            (
                self.configuration_directory
                / "database_restore"
                / "pending_restore.json"
            ).exists()
        )

    def test_staged_restore_does_not_require_source_backup(
        self
    ):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120008000000Z.db"
        )

        source_backup = self._create_backup(
            file_name=file_name,
            value="independent-stage",
        )

        DatabaseRestoreService.stage_restore(
            file_name
        )

        source_backup.unlink()

        pending_restore = (
            DatabaseRestoreService
            .get_pending_restore()
        )

        self.assertEqual(
            pending_restore[
                "source_backup_file_name"
            ],
            file_name,
        )

        self.assertEqual(
            self._read_value(
                pending_restore[
                    "staged_file_path"
                ]
            ),
            "independent-stage",
        )

    def test_modified_staged_database_is_rejected(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120009000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
        )

        pending_restore = (
            DatabaseRestoreService.stage_restore(
                file_name
            )
        )

        with pending_restore[
            "staged_file_path"
        ].open("ab") as file:
            file.write(
                b"tampered"
            )

        with self.assertRaises(
            DatabaseRestoreError
        ):
            (
                DatabaseRestoreService
                .get_pending_restore()
            )

    def test_pending_restore_replaces_live_database_and_creates_backup(
        self
    ):
        self._create_database(
            database_file=self.database_file,
            value="current-live-data",
        )

        file_name = (
            "league_mastery_tracker_"
            "20260716T120010000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
            value="restored-data",
        )

        DatabaseRestoreService.stage_restore(
            file_name
        )

        result = (
            DatabaseRestoreService
            .apply_pending_restore()
        )

        self.assertTrue(
            result["applied"]
        )

        self.assertEqual(
            self._read_value(
                self.database_file
            ),
            "restored-data",
        )

        safety_backup_file = result[
            "safety_backup_file"
        ]

        self.assertIsNotNone(
            safety_backup_file
        )

        self.assertTrue(
            safety_backup_file.exists()
        )

        self.assertEqual(
            self._read_value(
                safety_backup_file
            ),
            "current-live-data",
        )

        self.assertIsNone(
            DatabaseRestoreService
            .get_pending_restore()
        )

    def test_failed_safety_backup_preserves_database_and_pending_restore(
        self
    ):
        self._create_database(
            database_file=self.database_file,
            value="must-remain-live",
        )

        file_name = (
            "league_mastery_tracker_"
            "20260716T120011000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
            value="must-not-be-restored",
        )

        DatabaseRestoreService.stage_restore(
            file_name
        )

        with patch(
            "application.services."
            "database_restore_service."
            "BackupService.create_backup",
            side_effect=OSError(
                "Simulated backup failure."
            ),
        ):
            with self.assertRaises(
                DatabaseRestoreError
            ):
                (
                    DatabaseRestoreService
                    .apply_pending_restore()
                )

        self.assertEqual(
            self._read_value(
                self.database_file
            ),
            "must-remain-live",
        )

        self.assertIsNotNone(
            DatabaseRestoreService
            .get_pending_restore()
        )

    def test_pending_restore_can_be_cancelled(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T120012000000Z.db"
        )

        self._create_backup(
            file_name=file_name,
        )

        pending_restore = (
            DatabaseRestoreService.stage_restore(
                file_name
            )
        )

        staged_file = pending_restore[
            "staged_file_path"
        ]

        cancelled = (
            DatabaseRestoreService
            .cancel_pending_restore()
        )

        self.assertTrue(
            cancelled
        )

        self.assertFalse(
            staged_file.exists()
        )

        self.assertIsNone(
            DatabaseRestoreService
            .get_pending_restore()
        )


if __name__ == "__main__":
    unittest.main()