import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db
from application.services.application_shutdown_service import (
    ApplicationShutdownService,
)


app_module = importlib.import_module(
    "application.app"
)


class AppApplicationControlTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "database"
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
        backup_directory = (
            self.backup_directory
        )
        reference_directory = (
            self.reference_directory
        )

        class ApplicationControlTestConfig:
            TESTING = True
            DEBUG = False

            SQLALCHEMY_DATABASE_URI = (
                database_uri
            )

            SQLALCHEMY_TRACK_MODIFICATIONS = (
                False
            )

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

                database_file.parent.mkdir(
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
            "application-control-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    ApplicationControlTestConfig
                ),
            },
        )

        self.config_patch.start()

        self.app = app_module.create_app(
            self.config_name
        )

        self.client = (
            self.app.test_client()
        )

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

        self.config_patch.stop()

        self.temporary_directory.cleanup()

    def test_application_control_blueprint_is_registered(
        self
    ):
        self.assertIn(
            "application_control",
            self.app.blueprints,
        )

    def test_shutdown_route_is_registered_as_post_only(
        self
    ):
        shutdown_rules = [
            rule
            for rule in self.app.url_map.iter_rules()
            if rule.rule
            == "/application/shutdown"
        ]

        self.assertEqual(
            len(shutdown_rules),
            1,
        )

        shutdown_rule = (
            shutdown_rules[0]
        )

        self.assertIn(
            "POST",
            shutdown_rule.methods,
        )

        self.assertNotIn(
            "GET",
            shutdown_rule.methods,
        )

    def test_shutdown_post_requires_csrf_token(
        self
    ):
        response = self.client.post(
            "/application/shutdown"
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    def test_shutdown_service_is_not_created_by_app_factory(
        self
    ):
        self.assertNotIn(
            ApplicationShutdownService
            .FLASK_EXTENSION_KEY,
            self.app.extensions,
        )


if __name__ == "__main__":
    unittest.main()