import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Blueprint, Flask

from application.routes.settings import settings_bp
from application.services.csrf_service import CsrfService


class SettingsBackupRouteTests(unittest.TestCase):
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

        self.configuration_directory = (
            self.root_directory
            / "configuration"
        )

        project_root = (
            Path(__file__)
            .resolve()
            .parents[1]
        )

        template_directory = (
            project_root
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
            SECRET_KEY="settings-backup-test-key",
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
            RIOT_API_KEY=None,
            STARTUP_BACKUP_ERROR=None,
        )

        CsrfService.init_app(
            self.app
        )

        home_bp = Blueprint(
            "home",
            __name__,
        )

        @home_bp.get("/")
        def home():
            return "Home"

        self.app.register_blueprint(
            home_bp
        )

        self.app.register_blueprint(
            settings_bp
        )

        self._create_test_database()

        self.client = (
            self.app.test_client()
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_test_database(self):
        connection = sqlite3.connect(
            str(
                self.database_file
            )
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
                    "settings-route-test",
                ),
            )

            connection.commit()

        finally:
            connection.close()

    def test_settings_page_shows_no_backups_initially(
        self,
    ):
        response = self.client.get(
            "/settings"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        page = response.get_data(
            as_text=True
        )

        self.assertIn(
            (
                "No database backups are "
                "available yet."
            ),
            page,
        )

    def test_manual_backup_route_creates_valid_backup(
        self,
    ):
        response = self.client.post(
            "/settings/backups/create",
            follow_redirects=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        page = response.get_data(
            as_text=True
        )

        self.assertIn(
            "Database backup created:",
            page,
        )

        backup_files = list(
            self.backup_directory.glob(
                "league_mastery_tracker_*.db"
            )
        )

        self.assertEqual(
            len(
                backup_files
            ),
            1,
        )

        connection = sqlite3.connect(
            str(
                backup_files[0]
            )
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
                "settings-route-test",
            ),
        )

    def test_consecutive_manual_backups_use_unique_files(
        self,
    ):
        first_response = (
            self.client.post(
                "/settings/backups/create"
            )
        )

        second_response = (
            self.client.post(
                "/settings/backups/create"
            )
        )

        self.assertEqual(
            first_response.status_code,
            302,
        )

        self.assertEqual(
            second_response.status_code,
            302,
        )

        backup_files = list(
            self.backup_directory.glob(
                "league_mastery_tracker_*.db"
            )
        )

        self.assertEqual(
            len(
                backup_files
            ),
            2,
        )

        backup_names = {
            backup_file.name
            for backup_file in backup_files
        }

        self.assertEqual(
            len(
                backup_names
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()