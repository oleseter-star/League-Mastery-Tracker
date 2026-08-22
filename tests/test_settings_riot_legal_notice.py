import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


settings_module = importlib.import_module(
    "application.routes.settings"
)


class SettingsRiotLegalNoticeTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            STARTUP_BACKUP_ERROR=None,
        )

        self.template_file = (
            Path(__file__)
            .resolve()
            .parent
            .parent
            / "application"
            / "templates"
            / "settings.html"
        )

        self.template_content = (
            self.template_file.read_text(
                encoding="utf-8"
            )
        )

        self.notice = {
            "product_name": (
                "League Mastery Tracker"
            ),
            "boilerplate": (
                "League Mastery Tracker isn't "
                "endorsed by Riot Games."
            ),
            "asset_source": (
                "Riot Games Data Dragon"
            ),
            "asset_explanation": (
                "The application uses champion data "
                "and champion icons from Riot Games "
                "Data Dragon."
            ),
            "policy_url": (
                "https://developer.riotgames.com/"
                "policies/general"
            ),
            "data_dragon_url": (
                "https://developer.riotgames.com/"
                "docs/lol"
            ),
        }

    def test_settings_route_passes_legal_notice_to_template(
        self,
    ):
        api_key_status = {
            "configured": False,
            "source": None,
            "masked_key": None,
            "error": None,
        }

        backup_status = {
            "exists": False,
            "count": 0,
            "latest_file_name": None,
            "latest_modified": None,
            "latest_size_kib": None,
        }

        with (
            self.app.test_request_context(
                "/settings"
            ),
            patch.object(
                settings_module.RiotApiKeyService,
                "get_status",
                return_value=api_key_status,
            ),
            patch.object(
                settings_module,
                "_get_backup_status",
                return_value=backup_status,
            ),
            patch(
                "application.services."
                "riot_legal_notice_service."
                "RiotLegalNoticeService."
                "get_notice",
                return_value=self.notice,
            ) as get_notice,
            patch.object(
                settings_module,
                "render_template",
                return_value="rendered",
            ) as render_template,
        ):
            result = (
                settings_module.get_settings()
            )

        self.assertEqual(
            result,
            "rendered",
        )

        get_notice.assert_called_once_with()

        render_template.assert_called_once_with(
            "settings.html",
            api_key_status=api_key_status,
            backup_status=backup_status,
            startup_backup_error=None,
            riot_legal_notice=self.notice,
        )

    def test_template_contains_legal_information_heading(
        self,
    ):
        self.assertIn(
            "<h2>Legal information</h2>",
            self.template_content,
        )

    def test_template_displays_required_boilerplate(
        self,
    ):
        self.assertIn(
            (
                "{{ "
                "riot_legal_notice.boilerplate "
                "}}"
            ),
            self.template_content,
        )

    def test_template_displays_data_dragon_attribution(
        self,
    ):
        self.assertIn(
            (
                "{{ "
                "riot_legal_notice.asset_source "
                "}}"
            ),
            self.template_content,
        )

        self.assertIn(
            (
                "{{ "
                "riot_legal_notice.asset_explanation "
                "}}"
            ),
            self.template_content,
        )

    def test_template_links_to_official_riot_information(
        self,
    ):
        self.assertIn(
            (
                'href="{{ '
                'riot_legal_notice.policy_url '
                '}}"'
            ),
            self.template_content,
        )

        self.assertIn(
            (
                'href="{{ '
                'riot_legal_notice.data_dragon_url '
                '}}"'
            ),
            self.template_content,
        )

        self.assertGreaterEqual(
            self.template_content.count(
                'target="_blank"'
            ),
            3,
        )

        self.assertGreaterEqual(
            self.template_content.count(
                'rel="noopener noreferrer"'
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()