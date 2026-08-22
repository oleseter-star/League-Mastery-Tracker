import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Blueprint, Flask

from application.routes.settings import settings_bp
from application.services.csrf_service import CsrfService


class SettingsApiKeyRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        project_root = Path(
            __file__
        ).resolve().parents[1]

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
            SECRET_KEY="settings-api-key-test-key",
            CSRF_ENABLED=False,
            DATABASE_FILE=str(
                self.root_directory
                / "test.db"
            ),
            BACKUP_DIR=str(
                self.root_directory
                / "backups"
            ),
            CONFIG_DIR=str(
                self.root_directory
                / "configuration"
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

        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def normalize_html_whitespace(html):
        """
        Collapse HTML whitespace without changing visible text.
        """

        return " ".join(
            html.split()
        )

    def test_local_key_shows_dpapi_status(self):
        key_status = {
            "configured": True,
            "source": "local",
            "masked_key": "••••••••CDEF",
            "error": None,
        }

        with patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
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

        normalized_page = (
            self.normalize_html_whitespace(
                page
            )
        )

        self.assertIn(
            "••••••••CDEF",
            page,
        )

        self.assertIn(
            "Encrypted with Windows DPAPI",
            normalized_page,
        )

        self.assertIn(
            "The same Windows user on this computer",
            normalized_page,
        )

    def test_decryption_error_is_displayed_safely(self):
        secret_value = (
            "RGAPI-this-secret-must-not-appear"
        )

        key_status = {
            "configured": False,
            "source": "local",
            "masked_key": None,
            "error": (
                "The locally stored Riot API key could not "
                "be decrypted. It may belong to another "
                "Windows user or may be damaged."
            ),
        }

        with patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
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

        normalized_page = (
            self.normalize_html_whitespace(
                page
            )
        )

        self.assertIn(
            (
                "The locally stored Riot API key "
                "could not be decrypted."
            ),
            normalized_page,
        )

        self.assertIn(
            "Save a new Riot API key",
            normalized_page,
        )

        self.assertIn(
            key_status["error"],
            normalized_page,
        )

        self.assertNotIn(
            secret_value,
            page,
        )

        self.assertIn(
            "Remove locally stored key",
            normalized_page,
        )

    def test_environment_key_is_not_described_as_dpapi_encrypted(
        self
    ):
        key_status = {
            "configured": True,
            "source": "environment",
            "masked_key": "••••••••1234",
            "error": None,
        }

        with patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
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

        normalized_page = (
            self.normalize_html_whitespace(
                page
            )
        )

        self.assertIn(
            "Environment variable",
            normalized_page,
        )

        self.assertNotIn(
            "The same Windows user on this computer",
            normalized_page,
        )

        self.assertNotIn(
            "Remove locally stored key",
            normalized_page,
        )


if __name__ == "__main__":
    unittest.main()