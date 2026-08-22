import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.services.database_migration_service import (
    DatabaseMigrationService,
    DatabaseVersionError,
)


class DatabaseMigrationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "league_mastery_tracker.db"
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            DATABASE_FILE=str(
                self.database_file
            ),
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()
        self.temporary_directory.cleanup()

    def _read_metadata_value(
        self,
        key,
    ):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            row = connection.execute(
                """
                SELECT value
                FROM application_metadata
                WHERE key = ?
                """,
                (
                    key,
                ),
            ).fetchone()

        finally:
            connection.close()

        if row is None:
            return None

        return row[0]

    def _create_versioned_database(
        self,
        version=1,
    ):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
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
                    str(version),
                ),
            )

            connection.execute(
                """
                CREATE TABLE existing_records (
                    id INTEGER PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                INSERT INTO existing_records (
                    value
                )
                VALUES (
                    ?
                )
                """,
                (
                    "preserve-this-data",
                ),
            )

            connection.commit()

        finally:
            connection.close()

    def _table_exists(
        self,
        table_name,
    ):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            row = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = ?
                """,
                (
                    table_name,
                ),
            ).fetchone()

        finally:
            connection.close()

        return row is not None

    def test_new_database_is_initialized_as_version_one(self):
        result = (
            DatabaseMigrationService
            .initialize_or_migrate()
        )

        self.assertTrue(
            self.database_file.exists()
        )

        self.assertTrue(
            result["initialized"]
        )

        self.assertFalse(
            result["baselined_existing_database"]
        )

        self.assertEqual(
            result["schema_version"],
            1,
        )

        self.assertEqual(
            result["migrated_versions"],
            [],
        )

        self.assertEqual(
            self._read_metadata_value(
                "database_schema_version"
            ),
            "1",
        )

    def test_existing_unversioned_database_is_baselined(self):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            connection.execute(
                """
                CREATE TABLE existing_records (
                    id INTEGER PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                INSERT INTO existing_records (
                    value
                )
                VALUES (
                    ?
                )
                """,
                (
                    "preserve-this-data",
                ),
            )

            connection.commit()

        finally:
            connection.close()

        result = (
            DatabaseMigrationService
            .initialize_or_migrate()
        )

        self.assertTrue(
            result["initialized"]
        )

        self.assertTrue(
            result["baselined_existing_database"]
        )

        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            row = connection.execute(
                """
                SELECT value
                FROM existing_records
                WHERE id = 1
                """
            ).fetchone()

        finally:
            connection.close()

        self.assertEqual(
            row,
            (
                "preserve-this-data",
            ),
        )

        self.assertEqual(
            DatabaseMigrationService
            .get_database_schema_version(),
            1,
        )

    def test_initialized_database_reuses_current_version(self):
        first_result = (
            DatabaseMigrationService
            .initialize_or_migrate()
        )

        second_result = (
            DatabaseMigrationService
            .initialize_or_migrate()
        )

        self.assertTrue(
            first_result["initialized"]
        )

        self.assertFalse(
            second_result["initialized"]
        )

        self.assertFalse(
            second_result["baselined_existing_database"]
        )

        self.assertEqual(
            second_result["schema_version"],
            1,
        )

        self.assertEqual(
            second_result["migrated_versions"],
            [],
        )

    def test_newer_database_version_is_rejected(self):
        self._create_versioned_database(
            version=999
        )

        with self.assertRaises(
            DatabaseVersionError
        ):
            (
                DatabaseMigrationService
                .initialize_or_migrate()
            )

    def test_invalid_database_version_is_rejected(self):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
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
                    "not-a-number",
                ),
            )

            connection.commit()

        finally:
            connection.close()

        with self.assertRaises(
            DatabaseVersionError
        ):
            (
                DatabaseMigrationService
                .initialize_or_migrate()
            )

    def test_export_format_version_is_defined(self):
        self.assertEqual(
            DatabaseMigrationService
            .get_export_format_version(),
            1,
        )

    def test_empty_database_starts_at_current_schema_version(self):
        with patch.object(
            DatabaseMigrationService,
            "CURRENT_DATABASE_SCHEMA_VERSION",
            3,
        ):
            result = (
                DatabaseMigrationService
                .initialize_or_migrate()
            )

        self.assertEqual(
            result["schema_version"],
            3,
        )

        self.assertEqual(
            result["migrated_versions"],
            [],
        )

        self.assertEqual(
            self._read_metadata_value(
                "database_schema_version"
            ),
            "3",
        )

    def test_database_is_migrated_from_version_one_to_two(self):
        self._create_versioned_database(
            version=1
        )

        def migrate_to_version_two(
            connection,
        ):
            connection.execute(
                """
                CREATE TABLE schema_two_records (
                    id INTEGER PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                INSERT INTO schema_two_records (
                    value
                )
                VALUES (
                    ?
                )
                """,
                (
                    "migration-completed",
                ),
            )

        with patch.object(
            DatabaseMigrationService,
            "CURRENT_DATABASE_SCHEMA_VERSION",
            2,
        ), patch.object(
            DatabaseMigrationService,
            "MIGRATIONS",
            {
                2: migrate_to_version_two,
            },
        ):
            result = (
                DatabaseMigrationService
                .initialize_or_migrate()
            )

        self.assertFalse(
            result["initialized"]
        )

        self.assertEqual(
            result["schema_version"],
            2,
        )

        self.assertEqual(
            result["migrated_versions"],
            [
                2,
            ],
        )

        self.assertEqual(
            self._read_metadata_value(
                "database_schema_version"
            ),
            "2",
        )

        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            migrated_row = connection.execute(
                """
                SELECT value
                FROM schema_two_records
                WHERE id = 1
                """
            ).fetchone()

            existing_row = connection.execute(
                """
                SELECT value
                FROM existing_records
                WHERE id = 1
                """
            ).fetchone()

        finally:
            connection.close()

        self.assertEqual(
            migrated_row,
            (
                "migration-completed",
            ),
        )

        self.assertEqual(
            existing_row,
            (
                "preserve-this-data",
            ),
        )

    def test_missing_migration_is_rejected_without_version_change(
        self
    ):
        self._create_versioned_database(
            version=1
        )

        with patch.object(
            DatabaseMigrationService,
            "CURRENT_DATABASE_SCHEMA_VERSION",
            2,
        ), patch.object(
            DatabaseMigrationService,
            "MIGRATIONS",
            {},
        ):
            with self.assertRaises(
                DatabaseVersionError
            ):
                (
                    DatabaseMigrationService
                    .initialize_or_migrate()
                )

        self.assertEqual(
            self._read_metadata_value(
                "database_schema_version"
            ),
            "1",
        )

        self.assertFalse(
            self._table_exists(
                "schema_two_records"
            )
        )

    def test_failed_migration_is_fully_rolled_back(self):
        self._create_versioned_database(
            version=1
        )

        def failing_migration(
            connection,
        ):
            connection.execute(
                """
                CREATE TABLE partial_migration_records (
                    id INTEGER PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                INSERT INTO partial_migration_records (
                    value
                )
                VALUES (
                    ?
                )
                """,
                (
                    "must-be-rolled-back",
                ),
            )

            raise RuntimeError(
                "Simulated migration failure."
            )

        with patch.object(
            DatabaseMigrationService,
            "CURRENT_DATABASE_SCHEMA_VERSION",
            2,
        ), patch.object(
            DatabaseMigrationService,
            "MIGRATIONS",
            {
                2: failing_migration,
            },
        ):
            with self.assertRaises(
                DatabaseVersionError
            ):
                (
                    DatabaseMigrationService
                    .initialize_or_migrate()
                )

        self.assertEqual(
            self._read_metadata_value(
                "database_schema_version"
            ),
            "1",
        )

        self.assertFalse(
            self._table_exists(
                "partial_migration_records"
            )
        )

        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            existing_row = connection.execute(
                """
                SELECT value
                FROM existing_records
                WHERE id = 1
                """
            ).fetchone()

        finally:
            connection.close()

        self.assertEqual(
            existing_row,
            (
                "preserve-this-data",
            ),
        )


if __name__ == "__main__":
    unittest.main()