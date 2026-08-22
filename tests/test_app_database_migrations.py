import importlib
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db
from application.services.database_migration_service import (
    DatabaseVersionError,
)


app_module = importlib.import_module(
    "application.app"
)


class AppDatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "test.db"
        )

        self.configuration_directory = (
            self.root_directory
            / "configuration"
        )

        self.backup_directory = (
            self.root_directory
            / "backups"
        )

        self.reference_directory = (
            self.root_directory
            / "reference"
        )

        database_uri = (
            "sqlite:///"
            + self.database_file.as_posix()
        )

        root_directory = self.root_directory
        database_file = self.database_file
        configuration_directory = (
            self.configuration_directory
        )
        backup_directory = self.backup_directory
        reference_directory = (
            self.reference_directory
        )

        class MigrationTestConfig:
            TESTING = False
            DEBUG = False

            SQLALCHEMY_DATABASE_URI = database_uri
            SQLALCHEMY_TRACK_MODIFICATIONS = False

            DATABASE_FILE = str(
                database_file
            )

            CONFIG_DIR = str(
                configuration_directory
            )

            BACKUP_DIR = str(
                backup_directory
            )

            REFERENCE_DIR = str(
                reference_directory
            )

            RIOT_API_KEY = None

            @classmethod
            def ensure_directories(cls):
                root_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                configuration_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                backup_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                reference_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

        self.config_name = "migration-test"

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: MigrationTestConfig,
            },
        )

        self.config_patch.start()

        self.created_apps = []

    def tearDown(self):
        for app in self.created_apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

        self.config_patch.stop()
        self.temporary_directory.cleanup()

    def _create_app(self):
        app = app_module.create_app(
            self.config_name
        )

        self.created_apps.append(
            app
        )

        return app

    def test_new_database_is_versioned_without_backup(self):
        app = self._create_app()

        self.assertTrue(
            self.database_file.exists()
        )

        self.assertEqual(
            app.config[
                "STARTUP_DATABASE_MIGRATION_RESULT"
            ]["schema_version"],
            1,
        )

        self.assertEqual(
            list(
                self.backup_directory.glob("*.db")
            ),
            [],
        )

    def test_existing_unversioned_database_is_backed_up_first(
        self
    ):
        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            connection.execute(
                """
                CREATE TABLE legacy_records (
                    id INTEGER PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

            connection.execute(
                """
                INSERT INTO legacy_records (
                    value
                )
                VALUES (
                    ?
                )
                """,
                (
                    "preserved",
                ),
            )

            connection.commit()

        finally:
            connection.close()

        app = self._create_app()

        backup_files = list(
            self.backup_directory.glob(
                "league_mastery_tracker_*.db"
            )
        )

        self.assertEqual(
            len(backup_files),
            1,
        )

        backup_connection = sqlite3.connect(
            str(backup_files[0])
        )

        try:
            row = backup_connection.execute(
                """
                SELECT value
                FROM legacy_records
                WHERE id = 1
                """
            ).fetchone()

            metadata_table = backup_connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'application_metadata'
                """
            ).fetchone()

        finally:
            backup_connection.close()

        self.assertEqual(
            row,
            (
                "preserved",
            ),
        )

        self.assertIsNone(
            metadata_table
        )

        self.assertTrue(
            app.config[
                "STARTUP_DATABASE_MIGRATION_RESULT"
            ]["baselined_existing_database"]
        )

    def test_newer_database_is_rejected_without_modification(
        self
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
                    "999",
                ),
            )

            connection.commit()

        finally:
            connection.close()

        with self.assertRaises(
            DatabaseVersionError
        ):
            self._create_app()

        self.assertEqual(
            list(
                self.backup_directory.glob("*.db")
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()