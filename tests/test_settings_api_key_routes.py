import re
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

    def test_delete_failure_hides_raw_operating_system_error(
        self
    ):
        controlled_message = (
            "The stored Riot API key could not be removed. "
            "It may still be available to League Mastery Tracker. "
            "Try again."
        )

        raw_error = OSError(
            "Permission denied: "
            "C:\\Users\\Synthetic\\AppData\\Local\\LMT\\key.dpapi; "
            "/tmp/synthetic-lmt/key.dpapi; "
            "RGAPI-synthetic-secret-marker"
        )

        self.app.config["CSRF_ENABLED"] = True

        settings_response = self.client.get(
            "/settings"
        )

        token_match = re.search(
            r'name="_csrf_token"\s+value="([^"]+)"',
            settings_response.get_data(
                as_text=True
            ),
        )

        self.assertIsNotNone(
            token_match,
        )

        with patch(
            "application.routes.settings."
            "RiotApiKeyService.delete_local_api_key",
            side_effect=raw_error,
        ) as delete_local_api_key:
            response = self.client.post(
                "/settings/riot-api-key/delete",
                data={
                    "_csrf_token": token_match.group(1),
                },
                follow_redirects=True,
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.request.path,
            "/settings",
        )

        delete_local_api_key.assert_called_once_with()

        page = response.get_data(
            as_text=True
        )

        self.assertEqual(
            page.count(controlled_message),
            1,
        )

        self.assertRegex(
            page,
            r'<p\s+class="flash flash-error"[^>]*role="alert"',
        )

        self.assertNotIn(
            str(raw_error),
            page,
        )

        for sensitive_detail in (
            r"C:\\Users\\Synthetic\\AppData",
            "/tmp/synthetic-lmt",
            "Permission denied",
            "RGAPI-synthetic-secret-marker",
        ):
            with self.subTest(
                sensitive_detail=sensitive_detail,
            ):
                self.assertNotIn(
                    sensitive_detail,
                    page,
                )

    def test_save_failure_hides_raw_operating_system_error(
        self
    ):
        submitted_key = (
            "RGAPI-synthetic-submitted-key-marker"
        )

        controlled_message = (
            "The Riot API key could not be saved. "
            "A previously stored key, if any, may still be "
            "available to League Mastery Tracker. Try again."
        )

        deletion_message = (
            "The stored Riot API key could not be removed. "
            "It may still be available to League Mastery Tracker. "
            "Try again."
        )

        raw_error = OSError(
            "Directory creation denied: "
            "C:\\Users\\Synthetic\\AppData\\Local\\LMT\\key.dpapi; "
            "/tmp/synthetic-lmt/key.dpapi; "
            "RGAPI-synthetic-os-error-marker"
        )

        self.app.config["CSRF_ENABLED"] = True

        settings_response = self.client.get(
            "/settings"
        )

        token_match = re.search(
            r'name="_csrf_token"\s+value="([^"]+)"',
            settings_response.get_data(
                as_text=True
            ),
        )

        self.assertIsNotNone(
            token_match,
        )

        with patch(
            "application.routes.settings."
            "RiotApiKeyService.save_api_key",
            side_effect=raw_error,
        ) as save_api_key:
            response = self.client.post(
                "/settings/riot-api-key",
                data={
                    "_csrf_token": token_match.group(1),
                    "api_key": submitted_key,
                },
                follow_redirects=True,
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.request.path,
            "/settings",
        )

        save_api_key.assert_called_once_with(
            submitted_key
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
            r'<p\s+class="flash flash-error"[^>]*role="alert"',
        )

        self.assertNotIn(
            "The Riot API key was saved.",
            page,
        )

        self.assertNotIn(
            deletion_message,
            page,
        )

        self.assertNotIn(
            str(raw_error),
            page,
        )

        for sensitive_detail in (
            r"C:\\Users\\Synthetic\\AppData",
            "/tmp/synthetic-lmt",
            "Directory creation denied",
            "key.dpapi",
            "RGAPI-synthetic-submitted-key-marker",
            "RGAPI-synthetic-os-error-marker",
            "Traceback",
            "OSError",
        ):
            with self.subTest(
                sensitive_detail=sensitive_detail,
            ):
                self.assertNotIn(
                    sensitive_detail,
                    page,
                )


if __name__ == "__main__":
    unittest.main()