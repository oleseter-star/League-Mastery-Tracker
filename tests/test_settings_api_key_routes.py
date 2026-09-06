import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Blueprint, Flask

from application.routes.settings import settings_bp
from application.services.csrf_service import CsrfService


class _SettingsHtmlParser(HTMLParser):
    """
    Capture the API-key form and status elements from rendered HTML.
    """

    def __init__(self):
        super().__init__()
        self.elements = []
        self.forms = []
        self.ids = {}
        self.statuses = []
        self._form_indexes = []
        self._status_indexes = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        form_index = (
            self._form_indexes[-1]
            if self._form_indexes
            else None
        )

        if tag == "form":
            form_index = len(self.forms)
            self.forms.append(
                {
                    "attributes": attributes,
                    "index": form_index,
                }
            )
            self._form_indexes.append(form_index)

        element = {
            "tag": tag,
            "attributes": attributes,
            "form_index": form_index,
        }
        self.elements.append(element)

        element_id = attributes.get("id")
        if element_id:
            self.ids.setdefault(element_id, []).append(element)

        if attributes.get("role") == "status":
            self.statuses.append(
                {
                    "attributes": attributes,
                    "interactive": False,
                    "tag": tag,
                    "text": [],
                }
            )
            self._status_indexes.append(
                len(self.statuses) - 1
            )

        if tag in {"a", "button", "input", "select", "textarea"}:
            for status_index in self._status_indexes:
                self.statuses[status_index]["interactive"] = True

    def handle_endtag(self, tag):
        if tag == "form":
            self._form_indexes.pop()

        if (
            self._status_indexes
            and self.statuses[
                self._status_indexes[-1]
            ]["tag"] == tag
        ):
            self._status_indexes.pop()

    def handle_data(self, data):
        for status_index in self._status_indexes:
            self.statuses[status_index]["text"].append(data)


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

    def _parse_settings_html(self, page):
        parser = _SettingsHtmlParser()
        parser.feed(page)
        return parser

    def _assert_api_key_save_form(
        self,
        page,
        disabled,
    ):
        parser = self._parse_settings_html(page)
        save_form = next(
            form
            for form in parser.forms
            if form["attributes"].get("action")
            == "/settings/riot-api-key"
        )

        self.assertEqual(
            save_form["attributes"].get("method"),
            "post",
        )

        form_elements = [
            element
            for element in parser.elements
            if element["form_index"] == save_form["index"]
        ]
        csrf_fields = [
            element
            for element in form_elements
            if element["tag"] == "input"
            and element["attributes"].get("name")
            == "_csrf_token"
            and element["attributes"].get("type")
            == "hidden"
        ]
        self.assertEqual(len(csrf_fields), 1)

        password_inputs = [
            element
            for element in form_elements
            if element["tag"] == "input"
            and element["attributes"].get("id") == "api_key"
        ]
        self.assertEqual(len(password_inputs), 1)
        password_input = password_inputs[0]
        self.assertEqual(
            password_input["attributes"].get("name"),
            "api_key",
        )
        self.assertEqual(
            password_input["attributes"].get("type"),
            "password",
        )
        self.assertEqual(
            password_input["attributes"].get("autocomplete"),
            "off",
        )
        self.assertEqual(
            "disabled" in password_input["attributes"],
            disabled,
        )

        labels = [
            element
            for element in form_elements
            if element["tag"] == "label"
            and element["attributes"].get("for") == "api_key"
        ]
        self.assertEqual(len(labels), 1)

        save_buttons = [
            element
            for element in form_elements
            if element["tag"] == "button"
            and element["attributes"].get("type") == "submit"
        ]
        self.assertEqual(len(save_buttons), 1)
        self.assertEqual(
            "disabled" in save_buttons[0]["attributes"],
            disabled,
        )

        described_by = password_input["attributes"].get(
            "aria-describedby"
        ).split()
        self.assertIn("api-key-help", described_by)
        for element_id in described_by:
            self.assertEqual(
                len(parser.ids.get(element_id, [])),
                1,
            )

        return parser, described_by

    def test_local_key_shows_dpapi_status(self):
        key_status = {
            "configured": True,
            "source": "local",
            "masked_key": "••••••••CDEF",
            "error": None,
        }

        with patch.object(sys, "platform", "win32"), patch(
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
                "The stored Riot API key could not be read safely."
            ),
        }

        with patch.object(sys, "platform", "win32"), patch(
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

        warning = re.search(
            r'<div\s+class="notice notice-error"\s+role="alert"\s*>'
            r"(?P<content>.*?)</div>",
            page,
            re.DOTALL,
        )
        self.assertIsNotNone(warning)
        warning_text = self.normalize_html_whitespace(
            re.sub(r"<[^>]+>", " ", warning.group("content"))
        )

        self.assertEqual(
            warning_text,
            (
                "The securely stored Riot API key could not be read. "
                "It may be unavailable or damaged. Your other "
                "application data remains safe. Save a new Riot API key "
                "below to replace it."
            ),
        )

        self.assertIn(
            "Save a new Riot API key",
            normalized_page,
        )

        self.assertNotIn("decrypting a file", warning_text)
        self.assertNotIn("Windows user", warning_text)

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

        with patch.object(sys, "platform", "win32"), patch(
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

    def test_linux_available_storage_uses_secret_service_guidance(self):
        key_status = {
            "configured": True,
            "source": "local",
            "masked_key": "••••••••CDEF",
            "error": None,
        }
        storage_status = {
            "available": True,
            "error": None,
        }

        with patch.object(sys, "platform", "linux"), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
        ) as get_status, patch(
            "application.routes.settings."
            "RiotApiKeyService.get_persistent_storage_status",
            return_value=storage_status,
        ) as get_storage_status:
            response = self.client.get("/settings")

        page = response.get_data(as_text=True)
        linux_copy = (
            "On Linux, saved Riot API keys are stored securely in "
            "your desktop Secret Service."
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.count(linux_copy), 1)
        self.assertNotIn("Windows DPAPI", page)
        self.assertNotIn("The same Windows user", page)
        self._assert_api_key_save_form(page, disabled=False)
        self.assertIn("••••••••CDEF", page)
        get_status.assert_called_once_with()
        get_storage_status.assert_called_once_with()

    def test_linux_unavailable_storage_disables_persistent_save(self):
        key_status = {
            "configured": False,
            "source": None,
            "masked_key": None,
            "error": "Persistent Riot API key storage is unavailable.",
        }
        storage_status = {
            "available": False,
            "error": "Persistent Riot API key storage is unavailable.",
        }
        unavailable_copy = (
            "Secure Riot API key storage is unavailable for this Linux "
            "session. Persistent saving is disabled. You can still provide "
            "RIOT_API_KEY through the environment."
        )

        with patch.object(sys, "platform", "linux"), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
        ), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_persistent_storage_status",
            return_value=storage_status,
        ):
            response = self.client.get("/settings")

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.count(unavailable_copy), 1)
        parser, described_by = self._assert_api_key_save_form(
            page,
            disabled=True,
        )
        self.assertIn("api-key-storage-help", described_by)
        storage_help = parser.ids["api-key-storage-help"]
        self.assertEqual(len(storage_help), 1)
        self.assertEqual(storage_help[0]["tag"], "p")
        matching_statuses = [
            status
            for status in parser.statuses
            if status["attributes"].get("id")
            == "api-key-storage-help"
        ]
        self.assertEqual(len(matching_statuses), 1)
        self.assertFalse(matching_statuses[0]["interactive"])
        self.assertEqual(
            self.normalize_html_whitespace(
                "".join(matching_statuses[0]["text"])
            ),
            unavailable_copy,
        )
        self.assertNotIn('role="alert"', page[page.find(unavailable_copy) - 100:page.find(unavailable_copy) + len(unavailable_copy) + 100])
        for detail in (
            "Windows DPAPI",
            "D-Bus",
            "SecretStorage",
            "Traceback",
            "Persistent Riot API key storage is unavailable.",
        ):
            self.assertNotIn(detail, page)

    def test_linux_unavailable_storage_keeps_environment_key_visible(self):
        environment_key = "RGAPI-environment-key-must-not-render-1234"
        key_status = {
            "configured": True,
            "source": "environment",
            "masked_key": "••••••••1234",
            "error": None,
        }
        storage_status = {
            "available": False,
            "error": "backend detail must not render",
        }

        with patch.object(sys, "platform", "linux"), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
        ), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_persistent_storage_status",
            return_value=storage_status,
        ):
            response = self.client.get("/settings")

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("••••••••1234", page)
        self.assertIn("Environment variable", page)
        self.assertNotIn(environment_key, page)
        self.assertRegex(page, r'<input[^>]*id="api_key"[^>]*disabled')
        self.assertNotIn("Encrypted with", page)
        self.assertNotIn("Remove locally stored key", page)
        self.assertNotIn("backend detail must not render", page)

    def test_other_platform_unavailable_storage_disables_persistent_save(
        self
    ):
        key_status = {
            "configured": False,
            "source": None,
            "masked_key": None,
            "error": "backend detail must not render",
        }
        unavailable_copy = (
            "Secure Riot API key storage is unavailable on this platform. "
            "Persistent saving is disabled. You can still provide "
            "RIOT_API_KEY through the environment."
        )

        with patch.object(sys, "platform", "darwin"), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
        ):
            response = self.client.get("/settings")

        page = response.get_data(as_text=True)
        parser, described_by = self._assert_api_key_save_form(
            page,
            disabled=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.count(unavailable_copy), 1)
        self.assertIn("api-key-storage-help", described_by)
        self.assertEqual(len(parser.ids["api-key-storage-help"]), 1)
        matching_statuses = [
            status
            for status in parser.statuses
            if status["attributes"].get("id")
            == "api-key-storage-help"
        ]
        self.assertEqual(len(matching_statuses), 1)
        self.assertFalse(matching_statuses[0]["interactive"])
        self.assertEqual(
            self.normalize_html_whitespace(
                "".join(matching_statuses[0]["text"])
            ),
            unavailable_copy,
        )
        for detail in (
            "Windows",
            "DPAPI",
            "Linux",
            "Secret Service",
            "D-Bus",
            "SecretStorage",
            "backend detail must not render",
        ):
            self.assertNotIn(detail, page)

    def test_windows_storage_keeps_dpapi_guidance_and_enabled_save(self):
        key_status = {
            "configured": True,
            "source": "local",
            "masked_key": "••••••••CDEF",
            "error": None,
        }

        with patch.object(sys, "platform", "win32"), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
        ), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_persistent_storage_status",
            return_value={"available": True, "error": None},
        ) as get_storage_status:
            response = self.client.get("/settings")

        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("••••••••CDEF", page)
        self.assertIn("Stored locally by the application", page)
        self.assertIn("Encrypted with Windows DPAPI", page)
        self.assertIn("The same Windows user on this computer", page)
        self.assertNotIn("On Linux, saved Riot API keys", page)
        self._assert_api_key_save_form(page, disabled=False)
        get_storage_status.assert_not_called()

    def test_direct_save_post_keeps_existing_controlled_failure_path(self):
        key_status = {
            "configured": False,
            "source": None,
            "masked_key": None,
            "error": None,
        }
        submitted_key = "RGAPI-direct-post-race-key-1234567890"
        controlled_message = (
            "The Riot API key could not be saved. "
            "A previously stored key, if any, may still be "
            "available to League Mastery Tracker. Try again."
        )
        self.app.config["CSRF_ENABLED"] = True

        with patch.object(sys, "platform", "linux"), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_status",
            return_value=key_status,
        ), patch(
            "application.routes.settings."
            "RiotApiKeyService.get_persistent_storage_status",
            return_value={"available": True, "error": None},
        ):
            settings_response = self.client.get("/settings")

        token_match = re.search(
            r'name="_csrf_token"\s+value="([^"]+)"',
            settings_response.get_data(as_text=True),
        )
        self.assertIsNotNone(token_match)

        raw_error = OSError(
            "C:\\Synthetic\\SecretService\\riot-key.bin; "
            "/synthetic/secret-service/riot-key; "
            "org.freedesktop.secrets; "
            "SecretStorageMissingDependency; "
            "RGAPI-SYNTHETIC-SETTINGS-KEY; "
            "Traceback (most recent call last): "
            "SYNTHETIC_SETTINGS_TRACEBACK_FRAME"
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

        page = response.get_data(as_text=True)
        save_api_key.assert_called_once_with(submitted_key)
        self.assertEqual(response.status_code, 200)
        self.assertIn(controlled_message, page)
        self.assertNotIn(submitted_key, page)
        self.assertNotIn(str(raw_error), page)
        self.assertRegex(
            page,
            r'<p\s+class="flash flash-error"[^>]*role="alert"',
        )
        for sensitive_detail in (
            r"C:\\Synthetic\\SecretService\\riot-key.bin",
            "/synthetic/secret-service/riot-key",
            "org.freedesktop.secrets",
            "SecretStorageMissingDependency",
            "RGAPI-SYNTHETIC-SETTINGS-KEY",
            "Traceback (most recent call last):",
            "SYNTHETIC_SETTINGS_TRACEBACK_FRAME",
            type(raw_error).__name__,
            repr(raw_error),
        ):
            self.assertNotIn(sensitive_detail, page)
        self.assertFalse(
            (self.root_directory / "configuration").exists()
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
