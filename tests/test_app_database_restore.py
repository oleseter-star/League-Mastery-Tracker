import importlib
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.services.database_restore_service import (
    DatabaseRestoreError,
    DatabaseRestoreService,
)


app_module = importlib.import_module(
    "application.app"
)


class AppDatabaseRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "live.db"
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

        class RestoreTestConfig:
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

        self.config_name = "restore-test"

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: RestoreTestConfig,
            },
        )

        self.config_patch.start()

        self.staging_app = Flask(
            __name__
        )

        self.staging_app.config.update(
            TESTING=True,
            DATABASE_FILE=str(
                self.database_file
            ),
            CONFIG_DIR=str(
                self.configuration_directory
            ),
            BACKUP_DIR=str(
                self.backup_directory
            ),
        )

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

    def _create_database(
        self,
        database_file,
        value,
        include_metadata=True,
        schema_version=1,
    ):
        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

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
        value,
        include_metadata=True,
        schema_version=1,
    ):
        backup_file = (
            self.backup_directory
            / file_name
        )

        self._create_database(
            database_file=backup_file,
            value=value,
            include_metadata=include_metadata,
            schema_version=schema_version,
        )

        return backup_file

    def _stage_restore(
        self,
        backup_file_name,
    ):
        with self.staging_app.app_context():
            return (
                DatabaseRestoreService
                .stage_restore(
                    backup_file_name
                )
            )

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

    @staticmethod
    def _read_schema_version(
        database_file,
    ):
        connection = sqlite3.connect(
            str(database_file)
        )

        try:
            row = connection.execute(
                """
                SELECT value
                FROM application_metadata
                WHERE key = ?
                """,
                (
                    "database_schema_version",
                ),
            ).fetchone()

        finally:
            connection.close()

        if row is None:
            return None

        return int(
            row[0]
        )

    @staticmethod
    def _metadata_table_exists(
        database_file,
    ):
        connection = sqlite3.connect(
            str(database_file)
        )

        try:
            row = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'application_metadata'
                """
            ).fetchone()

        finally:
            connection.close()

        return row is not None

    def test_startup_without_pending_restore_continues_normally(
        self
    ):
        app = self._create_app()

        restore_result = app.config[
            "STARTUP_DATABASE_RESTORE_RESULT"
        ]

        self.assertFalse(
            restore_result["applied"]
        )

        self.assertEqual(
            restore_result["reason"],
            "no_pending_restore",
        )

        self.assertTrue(
            self.database_file.exists()
        )

    def test_pending_restore_is_applied_before_sqlalchemy(
        self
    ):
        self._create_database(
            database_file=self.database_file,
            value="old-live-data",
        )

        backup_file_name = (
            "league_mastery_tracker_"
            "20260716T130000000000Z.db"
        )

        self._create_backup(
            file_name=backup_file_name,
            value="restored-data",
        )

        self._stage_restore(
            backup_file_name
        )

        app = self._create_app()

        restore_result = app.config[
            "STARTUP_DATABASE_RESTORE_RESULT"
        ]

        self.assertTrue(
            restore_result["applied"]
        )

        self.assertEqual(
            restore_result[
                "source_backup_file_name"
            ],
            backup_file_name,
        )

        self.assertEqual(
            self._read_value(
                self.database_file
            ),
            "restored-data",
        )

        safety_backup_file = restore_result[
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
            "old-live-data",
        )

        with app.app_context():
            self.assertIsNone(
                DatabaseRestoreService
                .get_pending_restore()
            )

    def test_unversioned_restore_is_backed_up_and_baselined(
        self
    ):
        backup_file_name = (
            "league_mastery_tracker_"
            "20260716T130001000000Z.db"
        )

        self._create_backup(
            file_name=backup_file_name,
            value="unversioned-restored-data",
            include_metadata=False,
        )

        self._stage_restore(
            backup_file_name
        )

        app = self._create_app()

        restore_result = app.config[
            "STARTUP_DATABASE_RESTORE_RESULT"
        ]

        migration_result = app.config[
            "STARTUP_DATABASE_MIGRATION_RESULT"
        ]

        startup_backup_result = app.config[
            "STARTUP_BACKUP_RESULT"
        ]

        self.assertTrue(
            restore_result["applied"]
        )

        self.assertIsNone(
            restore_result["safety_backup_file"]
        )

        self.assertTrue(
            migration_result[
                "baselined_existing_database"
            ]
        )

        self.assertEqual(
            migration_result["schema_version"],
            1,
        )

        self.assertEqual(
            self._read_schema_version(
                self.database_file
            ),
            1,
        )

        self.assertEqual(
            self._read_value(
                self.database_file
            ),
            "unversioned-restored-data",
        )

        self.assertIsNotNone(
            startup_backup_result
        )

        pre_migration_backup = (
            startup_backup_result[
                "backup_file"
            ]
        )

        self.assertTrue(
            pre_migration_backup.exists()
        )

        self.assertFalse(
            self._metadata_table_exists(
                pre_migration_backup
            )
        )

        self.assertEqual(
            self._read_value(
                pre_migration_backup
            ),
            "unversioned-restored-data",
        )

    def test_tampered_pending_restore_aborts_startup_and_preserves_live_database(
        self
    ):
        self._create_database(
            database_file=self.database_file,
            value="must-remain-live",
        )

        backup_file_name = (
            "league_mastery_tracker_"
            "20260716T130002000000Z.db"
        )

        self._create_backup(
            file_name=backup_file_name,
            value="must-not-be-restored",
        )

        pending_restore = self._stage_restore(
            backup_file_name
        )

        with pending_restore[
            "staged_file_path"
        ].open("ab") as file:
            file.write(
                b"tampered-after-staging"
            )

        with self.assertRaises(
            DatabaseRestoreError
        ):
            self._create_app()

        self.assertEqual(
            self._read_value(
                self.database_file
            ),
            "must-remain-live",
        )

        marker_file = (
            self.configuration_directory
            / "database_restore"
            / "pending_restore.json"
        )

        self.assertTrue(
            marker_file.exists()
        )


if __name__ == "__main__":
    unittest.main()