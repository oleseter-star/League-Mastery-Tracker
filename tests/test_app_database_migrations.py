import importlib
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db
from application.services.database_migration_service import (
    DatabaseVersionError,
)
from application.services.application_data_service import (
    ApplicationDataService,
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

    def _create_current_database(self):
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
                    str(
                        app_module
                        .DatabaseMigrationService
                        .CURRENT_DATABASE_SCHEMA_VERSION
                    ),
                ),
            )

            connection.commit()

        finally:
            connection.close()

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

    def _assert_automatic_startup_backup_failure_is_safe(
        self,
        raw_error,
        sensitive_details,
    ):
        controlled_message = (
            "The automatic startup database backup could not be "
            "completed. League Mastery Tracker continued without "
            "a confirmed new startup backup. Try creating a manual "
            "database backup."
        )

        self._create_current_database()

        with patch.object(
            app_module.BackupService,
            "create_backup_if_due",
            side_effect=raw_error,
        ) as create_backup_if_due:
            app = self._create_app()

        create_backup_if_due.assert_called_once_with()

        response = app.test_client().get(
            "/settings"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        page = response.get_data(
            as_text=True
        )

        self.assertEqual(
            page.count(controlled_message),
            1,
        )

        self.assertRegex(
            page,
            r'<p\s+class="notice notice-error"\s+'
            r'role="alert"\s*>',
        )

        self.assertNotIn(
            "Database backup created:",
            page,
        )

        self.assertNotIn(
            "league_mastery_tracker_",
            page,
        )

        self.assertIn(
            "Riot API key",
            page,
        )

        self.assertIn(
            "Create backup now",
            page,
        )

        self.assertNotIn(
            str(raw_error),
            page,
        )

        for sensitive_detail in (
            *sensitive_details,
            "Traceback",
            "OSError",
            "DatabaseError",
            "ValueError",
        ):
            with self.subTest(
                sensitive_detail=sensitive_detail,
            ):
                self.assertNotIn(
                    sensitive_detail,
                    page,
                )

    def test_automatic_startup_backup_os_error_hides_raw_details(
        self
    ):
        self._assert_automatic_startup_backup_failure_is_safe(
            OSError(
                "Directory permission denied: "
                "C:\\Users\\Synthetic\\AppData\\Local\\LMT\\backups; "
                "/tmp/synthetic-lmt/backups; "
                "RGAPI-synthetic-startup-marker"
            ),
            (
                r"C:\\Users\\Synthetic\\AppData",
                "/tmp/synthetic-lmt",
                "Directory permission denied",
                "RGAPI-synthetic-startup-marker",
            ),
        )

    def test_automatic_startup_backup_sqlite_error_hides_raw_details(
        self
    ):
        self._assert_automatic_startup_backup_failure_is_safe(
            sqlite3.DatabaseError(
                "SQLite backup failure: "
                "database disk image is malformed; "
                "SQLITE-synthetic-startup-marker"
            ),
            (
                "SQLite backup failure",
                "database disk image is malformed",
                "SQLITE-synthetic-startup-marker",
            ),
        )

    def test_automatic_startup_backup_validation_error_hides_raw_details(
        self
    ):
        self._assert_automatic_startup_backup_failure_is_safe(
            ValueError(
                "Backup validation failed: "
                "synthetic-validation-directory-marker"
            ),
            (
                "Backup validation failed",
                "synthetic-validation-directory-marker",
            ),
        )

    def test_frozen_legacy_data_is_excluded_during_startup(self):
        meipass_directory = (
            self.root_directory
            / "pyinstaller-extraction"
        )

        legacy_data_directory = (
            meipass_directory
            / "data"
        )

        legacy_marker_file = (
            legacy_data_directory
            / "frozen-startup-marker.bin"
        )

        data_directory = (
            self.root_directory
            / "persistent-data"
            / "LeagueMasteryTracker"
        )

        database_file = (
            data_directory
            / "database"
            / "test.db"
        )

        configuration_directory = (
            data_directory
            / "configuration"
        )

        backup_directory = (
            data_directory
            / "backups"
        )

        reference_directory = (
            data_directory
            / "reference"
        )

        legacy_marker_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_marker_file.write_bytes(
            b"frozen-startup-data"
        )

        class FrozenMigrationTestConfig:
            TESTING = True
            DEBUG = False
            SQLALCHEMY_DATABASE_URI = (
                "sqlite:///"
                + database_file.as_posix()
            )
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            DATABASE_FILE = str(database_file)
            CONFIG_DIR = str(configuration_directory)
            BACKUP_DIR = str(backup_directory)
            REFERENCE_DIR = str(reference_directory)
            RIOT_API_KEY = None
            PROJECT_ROOT = meipass_directory
            LEGACY_DATA_DIR = legacy_data_directory
            DATA_DIR = data_directory
            STARTUP_APPLICATION_DATA_MIGRATION_RESULT = None

            @classmethod
            def ensure_directories(cls):
                cls.STARTUP_APPLICATION_DATA_MIGRATION_RESULT = (
                    ApplicationDataService
                    .migrate_legacy_data(
                        legacy_data_directory=(
                            cls.LEGACY_DATA_DIR
                        ),
                        target_data_directory=(
                            cls.DATA_DIR
                        ),
                    )
                )

                for directory in (
                    cls.DATA_DIR,
                    database_file.parent,
                    configuration_directory,
                    backup_directory,
                    reference_directory,
                ):
                    directory.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

        config_name = "frozen-migration-test"

        with patch.dict(
            app_module.configurations,
            {
                config_name: FrozenMigrationTestConfig,
            },
        ), patch.object(
            sys,
            "frozen",
            True,
            create=True,
        ), patch.object(
            sys,
            "_MEIPASS",
            str(meipass_directory),
            create=True,
        ), patch.object(
            ApplicationDataService,
            "migrate_legacy_data",
            wraps=ApplicationDataService.migrate_legacy_data,
        ) as migrate_legacy_data:
            app = app_module.create_app(
                config_name
            )

        self.created_apps.append(app)

        migrate_legacy_data.assert_called_once_with(
            legacy_data_directory=legacy_data_directory,
            target_data_directory=data_directory,
        )

        self.assertFalse(
            FrozenMigrationTestConfig
            .STARTUP_APPLICATION_DATA_MIGRATION_RESULT[
                "migrated"
            ]
        )

        self.assertTrue(
            legacy_marker_file.exists()
        )

        self.assertFalse(
            (
                data_directory
                / legacy_marker_file.name
            ).exists()
        )

        self.assertTrue(
            database_file.exists()
        )


    def test_existing_database_gains_match_tables_without_version_change(
        self,
    ):
        self._create_current_database()

        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            connection.execute(
                """
                CREATE TABLE persons (
                    id INTEGER PRIMARY KEY,
                    display_name VARCHAR(120) NOT NULL
                )
                """
            )

            connection.execute(
                "INSERT INTO persons (display_name) VALUES ('Ole')"
            )

            connection.commit()

        finally:
            connection.close()

        app = self._create_app()

        self.assertEqual(
            app.config[
                "STARTUP_DATABASE_MIGRATION_RESULT"
            ]["schema_version"],
            1,
        )

        connection = sqlite3.connect(
            str(self.database_file)
        )

        try:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

            persons = connection.execute(
                "SELECT display_name FROM persons"
            ).fetchall()

        finally:
            connection.close()

        self.assertTrue(
            {
                "matches",
                "match_participants",
                "match_import_states",
            }.issubset(table_names)
        )

        self.assertEqual(
            persons,
            [("Ole",)],
        )


if __name__ == "__main__":
    unittest.main()