import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from application.database.database import db
from application.services.application_tab_lifecycle_client_service import (
    ApplicationTabLifecycleClientService,
)
from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)


app_module = importlib.import_module(
    "application.app"
)


class AppTabLifecycleClientTests(
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

        class TabLifecycleClientTestConfig:
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
            "tab-lifecycle-client-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    TabLifecycleClientTestConfig
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

    def test_client_service_is_registered_by_app_factory(
        self
    ):
        extension_key = (
            ApplicationTabLifecycleClientService
            .FLASK_EXTENSION_KEY
        )

        self.assertIn(
            extension_key,
            self.app.extensions,
        )

        self.assertTrue(
            self.app.extensions[
                extension_key
            ]
        )

    def test_html_is_not_injected_before_launcher_registration(
        self
    ):
        response = self.client.get(
            "/"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        response_html = (
            response.get_data(
                as_text=True
            )
        )

        self.assertNotIn(
            (
                "application_tab_lifecycle.js"
            ),
            response_html,
        )

        self.assertNotIn(
            (
                "league-mastery-tracker-"
                "tab-lifecycle"
            ),
            response_html,
        )

    def test_html_is_injected_after_lifecycle_registration(
        self
    ):
        self.app.extensions[
            ApplicationTabLifecycleService
            .FLASK_EXTENSION_KEY
        ] = Mock()

        response = self.client.get(
            "/"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        response_html = (
            response.get_data(
                as_text=True
            )
        )

        self.assertIn(
            (
                'id="league-mastery-tracker-'
                'tab-lifecycle"'
            ),
            response_html,
        )

        self.assertIn(
            (
                'src="/static/'
                'application_tab_lifecycle.js"'
            ),
            response_html,
        )

        self.assertIn(
            (
                'data-heartbeat-url="'
                '/application/tabs/heartbeat"'
            ),
            response_html,
        )

        self.assertIn(
            (
                'data-close-url="'
                '/application/tabs/close"'
            ),
            response_html,
        )

        self.assertIn(
            'data-csrf-token="',
            response_html,
        )

    def test_static_client_file_is_served(
        self
    ):
        response = self.client.get(
            (
                "/static/"
                "application_tab_lifecycle.js"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        javascript = response.get_data(
            as_text=True
        )

        self.assertIn(
            "navigator.sendBeacon",
            javascript,
        )

        self.assertIn(
            "sendHeartbeat",
            javascript,
        )

        self.assertIn(
            "sendCloseSignal",
            javascript,
        )


if __name__ == "__main__":
    unittest.main()