import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from application.routes.database_restore import (
    database_restore_bp,
)
from application.services.database_restore_service import (
    DatabaseRestoreService,
)


class DatabaseRestoreRouteTests(unittest.TestCase):
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

        template_directory = (
            Path(__file__).resolve().parents[1]
            / "application"
            / "templates"
        )

        self.app = Flask(
            __name__,
            template_folder=str(
                template_directory
            ),
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "database-restore-route-test-key"
            ),
            CSRF_ENABLED=False,
            DATABASE_FILE=str(
                self.database_file
            ),
            BACKUP_DIR=str(
                self.backup_directory
            ),
            CONFIG_DIR=str(
                self.configuration_directory
            ),
            STARTUP_DATABASE_RESTORE_RESULT={
                "applied": False,
                "reason": "no_pending_restore",
                "safety_backup_file": None,
                "source_backup_file_name": None,
            },
        )

        self.app.jinja_env.globals[
            "csrf_token"
        ] = lambda: "test-csrf-token"

        self.app.register_blueprint(
            database_restore_bp
        )

        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_backup(
        self,
        file_name,
        value="backup-data",
        schema_version=1,
    ):
        backup_file = (
            self.backup_directory
            / file_name
        )

        connection = sqlite3.connect(
            str(backup_file)
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

        return backup_file

    def test_restore_page_shows_when_no_backups_exist(self):
        response = self.client.get(
            "/settings/database-restore"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"No database backups are available.",
            response.data,
        )

    def test_valid_backup_is_displayed(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T140000000000Z.db"
        )

        self._create_backup(
            file_name
        )

        response = self.client.get(
            "/settings/database-restore"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            file_name.encode(
                "utf-8"
            ),
            response.data,
        )

        self.assertIn(
            b"Stage this restore",
            response.data,
        )

        self.assertIn(
            b'name="_csrf_token"',
            response.data,
        )

    def test_restore_requires_exact_confirmation(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T140001000000Z.db"
        )

        self._create_backup(
            file_name
        )

        response = self.client.post(
            "/settings/database-restore/stage",
            data={
                "backup_file_name": file_name,
                "confirmation": "restore",
            },
            follow_redirects=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"Type RESTORE exactly",
            response.data,
        )

        with self.app.app_context():
            self.assertIsNone(
                DatabaseRestoreService
                .get_pending_restore()
            )

    def test_valid_backup_can_be_staged_from_route(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T140002000000Z.db"
        )

        self._create_backup(
            file_name,
            value="selected-restore-data",
        )

        response = self.client.post(
            "/settings/database-restore/stage",
            data={
                "backup_file_name": file_name,
                "confirmation": "RESTORE",
            },
            follow_redirects=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"Database restore staged",
            response.data,
        )

        self.assertIn(
            b"Restart required",
            response.data,
        )

        self.assertIn(
            file_name.encode(
                "utf-8"
            ),
            response.data,
        )

        with self.app.app_context():
            pending_restore = (
                DatabaseRestoreService
                .get_pending_restore()
            )

        self.assertIsNotNone(
            pending_restore
        )

        self.assertEqual(
            pending_restore[
                "source_backup_file_name"
            ],
            file_name,
        )

    def test_pending_restore_can_be_cancelled_from_route(
        self
    ):
        file_name = (
            "league_mastery_tracker_"
            "20260716T140003000000Z.db"
        )

        self._create_backup(
            file_name
        )

        with self.app.app_context():
            DatabaseRestoreService.stage_restore(
                file_name
            )

        response = self.client.post(
            "/settings/database-restore/cancel",
            follow_redirects=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"pending database restore was cancelled",
            response.data,
        )

        with self.app.app_context():
            self.assertIsNone(
                DatabaseRestoreService
                .get_pending_restore()
            )

    def test_corrupted_backup_is_displayed_as_invalid(self):
        file_name = (
            "league_mastery_tracker_"
            "20260716T140004000000Z.db"
        )

        (
            self.backup_directory
            / file_name
        ).write_bytes(
            b"not-a-valid-sqlite-database"
        )

        response = self.client.get(
            "/settings/database-restore"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            file_name.encode(
                "utf-8"
            ),
            response.data,
        )

        self.assertIn(
            b"This backup cannot be restored",
            response.data,
        )


if __name__ == "__main__":
    unittest.main()