import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db


app_module = importlib.import_module(
    "application.app"
)


class AppSecurityConfigTests(unittest.TestCase):
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
        configuration_directory = (
            self.configuration_directory
        )
        backup_directory = self.backup_directory
        reference_directory = (
            self.reference_directory
        )
        database_file = self.database_file

        class SecurityTestConfig:
            TESTING = True
            DEBUG = True

            SECRET_KEY = (
                "unsafe-configured-test-key"
            )

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

        self.config_name = (
            "security-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    SecurityTestConfig
                ),
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

    def test_app_uses_generated_local_secret_key(self):
        app = self._create_app()

        key_file = (
            self.configuration_directory
            / "flask_secret_key.bin"
        )

        self.assertTrue(
            key_file.exists()
        )

        self.assertEqual(
            len(key_file.read_bytes()),
            64,
        )

        self.assertEqual(
            app.config["SECRET_KEY"],
            key_file.read_bytes(),
        )

    def test_local_key_overrides_configured_secret(self):
        app = self._create_app()

        self.assertNotEqual(
            app.config["SECRET_KEY"],
            "unsafe-configured-test-key",
        )

        self.assertIsInstance(
            app.config["SECRET_KEY"],
            bytes,
        )

    def test_secret_key_is_reused_across_app_instances(self):
        first_app = self._create_app()

        first_key = first_app.config[
            "SECRET_KEY"
        ]

        second_app = self._create_app()

        second_key = second_app.config[
            "SECRET_KEY"
        ]

        self.assertEqual(
            second_key,
            first_key,
        )

    def test_session_cookie_security_defaults(self):
        app = self._create_app()

        self.assertEqual(
            app.config["SESSION_COOKIE_NAME"],
            "league_mastery_tracker_session",
        )

        self.assertTrue(
            app.config["SESSION_COOKIE_HTTPONLY"]
        )

        self.assertEqual(
            app.config["SESSION_COOKIE_SAMESITE"],
            "Lax",
        )

        self.assertFalse(
            app.config["SESSION_COOKIE_SECURE"]
        )

    def test_csrf_protection_is_enabled(self):
        app = self._create_app()

        self.assertTrue(
            app.config["CSRF_ENABLED"]
        )

        extension_state = app.extensions[
            "league_mastery_tracker"
        ]

        self.assertTrue(
            extension_state["csrf_initialized"]
        )


if __name__ == "__main__":
    unittest.main()