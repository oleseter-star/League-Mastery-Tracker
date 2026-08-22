import importlib
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from application.config import Config
from application.database.database import db
from application.services.application_shutdown_service import (
    ApplicationShutdownService,
)


app_module = importlib.import_module(
    "application.app"
)


class SettingsShutdownControlTests(
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

        class SettingsShutdownTestConfig(Config):
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
            "settings-shutdown-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    SettingsShutdownTestConfig
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

    def _get_settings(self):
        with patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value={
                "configured": False,
                "masked_key": None,
                "source": None,
                "error": None,
            },
        ):
            return self.client.get(
                "/settings"
            )

    def _configure_shutdown_service(self):
        shutdown_service = Mock()

        shutdown_service.request_shutdown.return_value = (
            True
        )

        self.app.extensions[
            ApplicationShutdownService
            .FLASK_EXTENSION_KEY
        ] = shutdown_service

        return shutdown_service

    def test_settings_shows_canonical_product_information(
        self,
    ):
        template_content = (
            Path(__file__)
            .resolve()
            .parents[1]
            / "application"
            / "templates"
            / "settings.html"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'aria-labelledby="product-information-heading"',
            template_content,
        )

        self.assertIn(
            '<h2 id="product-information-heading">',
            template_content,
        )

        self.assertIn(
            'config["RELEASE_NAME"]',
            template_content,
        )

        self.assertIn(
            'config["APPLICATION_VERSION"]',
            template_content,
        )

        self.assertNotIn(
            Config.RELEASE_NAME,
            template_content,
        )

        self.assertNotIn(
            Config.APPLICATION_VERSION,
            template_content,
        )

        response = self._get_settings()

        self.assertEqual(
            response.status_code,
            200,
        )

        normalized_html = " ".join(
            response.get_data(
                as_text=True
            ).split()
        )

        self.assertIn(
            "> Product information </h2>",
            normalized_html,
        )

        self.assertIn(
            (
                '<dt class="metadata-label"> '
                "Product </dt> <dd> "
                f"{Config.RELEASE_NAME} </dd>"
            ),
            normalized_html,
        )

        self.assertIn(
            (
                '<dt class="metadata-label"> '
                "Application version </dt> <dd> "
                f"{Config.APPLICATION_VERSION} </dd>"
            ),
            normalized_html,
        )

        for existing_control in (
            'action="/settings/riot-api-key"',
            'href="/settings/data-export"',
            'href="/settings/data-import"',
            'href="/settings/database-restore"',
            'action="/settings/backups/create"',
            "Legal information",
        ):
            with self.subTest(
                existing_control=existing_control
            ):
                self.assertIn(
                    existing_control,
                    normalized_html,
                )

    def test_shutdown_control_is_hidden_without_service(
        self,
    ):
        response = self._get_settings()

        self.assertEqual(
            response.status_code,
            200,
        )

        html = response.get_data(
            as_text=True
        )

        self.assertNotIn(
            'action="/application/shutdown"',
            html,
        )

        self.assertNotIn(
            "Shut down the application",
            html,
        )

        self.assertNotIn(
            "Shut down League Mastery Tracker",
            html,
        )

    def test_shutdown_control_is_shown_when_available(
        self,
    ):
        self._configure_shutdown_service()

        response = self._get_settings()

        self.assertEqual(
            response.status_code,
            200,
        )

        html = response.get_data(
            as_text=True
        )

        self.assertIn(
            'action="/application/shutdown"',
            html,
        )

        self.assertIn(
            'method="post"',
            html,
        )

        self.assertIn(
            'name="_csrf_token"',
            html,
        )

        self.assertIn(
            "Shut down the application",
            html,
        )

        self.assertIn(
            "Shut down League Mastery Tracker",
            html,
        )

        self.assertIn(
            (
                "Are you sure you want to shut down "
            ),
            html,
        )

        self.assertIn(
            "League Mastery Tracker?",
            html,
        )

    def test_rendered_shutdown_form_can_be_submitted(
        self,
    ):
        shutdown_service = (
            self._configure_shutdown_service()
        )

        settings_response = (
            self._get_settings()
        )

        html = settings_response.get_data(
            as_text=True
        )

        token_match = re.search(
            (
                r'name="_csrf_token"'
                r'\s+value="([^"]+)"'
            ),
            html,
        )

        self.assertIsNotNone(
            token_match
        )

        csrf_token = token_match.group(
            1
        )

        shutdown_response = (
            self.client.post(
                "/application/shutdown",
                data={
                    "_csrf_token": (
                        csrf_token
                    ),
                },
            )
        )

        self.assertEqual(
            shutdown_response.status_code,
            202,
        )

        shutdown_service.request_shutdown.assert_called_once_with()

        shutdown_html = (
            shutdown_response.get_data(
                as_text=True
            )
        )

        self.assertIn(
            "Application is shutting down",
            shutdown_html,
        )

        self.assertIn(
            "You can close this browser window.",
            shutdown_html,
        )


if __name__ == "__main__":
    unittest.main()
