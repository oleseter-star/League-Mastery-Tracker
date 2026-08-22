import importlib
import unittest
from unittest.mock import patch

from flask import Flask


home_module = importlib.import_module(
    "application.routes.home"
)


class HomeChampionReferenceStatusTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "home-champion-reference-status-test"
            ),
        )

        self.app.register_blueprint(
            home_module.home_bp
        )

        self.client = (
            self.app.test_client()
        )

        self.dashboard_result = {
            "persons": [
                {
                    "id": 1,
                    "display_name": (
                        "Test Person"
                    ),
                },
            ],
            "person_count": 1,
        }

        self.status_result = {
            "active_source": "bundled",
            "active_source_label": (
                "Bundled dataset"
            ),
            "reference_data_available": True,
            "uses_bundled_fallback": True,
            "uses_local_cache": False,
            "database_only": False,
            "data_dragon_version": (
                "15.14.1"
            ),
            "locale": "en_US",
            "dataset_champion_count": 170,
            "database_champion_count": 171,
            "missing_name_count": 1,
            "missing_image_count": 1,
            "missing_metadata_count": 1,
            "has_missing_metadata": True,
            "last_successful_update": (
                "2026-07-23T12:30:45+00:00"
            ),
            "last_update_error": None,
            "warnings": [],
        }

    def test_home_uses_existing_dashboard_service(
        self,
    ):
        with patch.object(
            home_module.DashboardService,
            "get_home_dashboard",
            return_value=(
                self.dashboard_result
            ),
        ) as dashboard_method, patch.object(
            home_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class, patch.object(
            home_module,
            "render_template",
            return_value="rendered",
        ):
            status_service_class.return_value.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        dashboard_method.assert_called_once_with()

    def test_home_uses_champion_reference_status_service(
        self,
    ):
        with patch.object(
            home_module.DashboardService,
            "get_home_dashboard",
            return_value=(
                self.dashboard_result
            ),
        ), patch.object(
            home_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class, patch.object(
            home_module,
            "render_template",
            return_value="rendered",
        ):
            response = self.client.get(
                "/"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        status_service_class.assert_called_once_with()

        status_service_class.return_value.get_status.assert_called_once_with()

    def test_home_renders_existing_person_context_and_status(
        self,
    ):
        with patch.object(
            home_module.DashboardService,
            "get_home_dashboard",
            return_value=(
                self.dashboard_result
            ),
        ), patch.object(
            home_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class, patch.object(
            home_module,
            "render_template",
            return_value="rendered",
        ) as render_template_mock:
            status_service_class.return_value.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        render_template_mock.assert_called_once_with(
            "home.html",
            persons=(
                self.dashboard_result[
                    "persons"
                ]
            ),
            person_count=1,
            champion_reference_status=(
                self.status_result
            ),
        )

    def test_status_failure_uses_safe_database_only_context(
        self,
    ):
        with patch.object(
            home_module.DashboardService,
            "get_home_dashboard",
            return_value=(
                self.dashboard_result
            ),
        ), patch.object(
            home_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class, patch.object(
            home_module,
            "render_template",
            return_value="rendered",
        ) as render_template_mock:
            status_service_class.return_value.get_status.side_effect = (
                RuntimeError(
                    "C:\\private\\reference"
                )
            )

            response = self.client.get(
                "/"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        render_call = (
            render_template_mock.call_args
        )

        status = render_call.kwargs[
            "champion_reference_status"
        ]

        self.assertEqual(
            status["active_source"],
            "database_only",
        )

        self.assertEqual(
            status["active_source_label"],
            "Database-only fallback",
        )

        self.assertTrue(
            status["database_only"]
        )

        self.assertFalse(
            status[
                "reference_data_available"
            ]
        )

        self.assertEqual(
            status["warnings"],
            [
                (
                    "Champion reference status "
                    "could not be read."
                ),
            ],
        )

        self.assertNotIn(
            "C:\\private",
            repr(
                status
            ),
        )

    def test_status_lookup_does_not_run_manual_update(
        self,
    ):
        with patch.object(
            home_module.DashboardService,
            "get_home_dashboard",
            return_value=(
                self.dashboard_result
            ),
        ), patch.object(
            home_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class, patch.object(
            home_module,
            "ChampionReferenceUpdateService",
            create=True,
        ) as update_service_class, patch.object(
            home_module,
            "render_template",
            return_value="rendered",
        ):
            status_service_class.return_value.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        update_service_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()