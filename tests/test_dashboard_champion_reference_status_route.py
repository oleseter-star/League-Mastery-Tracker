import importlib
import unittest
from unittest.mock import patch

from flask import Flask


dashboard_module = importlib.import_module(
    "application.routes.dashboard"
)


class DashboardChampionReferenceStatusRouteTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "dashboard-reference-status-route-test"
            ),
        )

        self.app.register_blueprint(
            dashboard_module.dashboard_bp
        )

        self.client = (
            self.app.test_client()
        )

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

    def test_status_route_uses_status_service(
        self,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class:
            status_service = (
                status_service_class.return_value
            )

            status_service.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/dashboard/reference-data/status"
            )

        status_service_class.assert_called_once_with()

        status_service.get_status.assert_called_once_with()

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_status_route_returns_complete_status_json(
        self,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class:
            status_service_class.return_value.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/dashboard/reference-data/status"
            )

        self.assertEqual(
            response.get_json(),
            self.status_result,
        )

    def test_status_route_does_not_run_manual_update(
        self,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class, patch.object(
            dashboard_module,
            "ChampionReferenceUpdateService",
        ) as update_service_class:
            status_service_class.return_value.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/dashboard/reference-data/status"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        update_service_class.assert_not_called()

    def test_status_route_does_not_expose_internal_paths(
        self,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class:
            status_service_class.return_value.get_status.return_value = (
                self.status_result
            )

            response = self.client.get(
                "/dashboard/reference-data/status"
            )

        response_text = response.get_data(
            as_text=True
        )

        self.assertNotIn(
            "dataset_directory",
            response_text,
        )

        self.assertNotIn(
            "icons_directory",
            response_text,
        )

        self.assertNotIn(
            "C:\\",
            response_text,
        )

    def test_status_failure_returns_controlled_response(
        self,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceStatusService",
            create=True,
        ) as status_service_class:
            status_service_class.return_value.get_status.side_effect = (
                RuntimeError(
                    "C:\\private\\database.db"
                )
            )

            response = self.client.get(
                "/dashboard/reference-data/status"
            )

        self.assertEqual(
            response.status_code,
            503,
        )

        self.assertEqual(
            response.get_json(),
            {
                "status": "unavailable",
                "message": (
                    "Champion reference status "
                    "could not be read."
                ),
            },
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertNotIn(
            "C:\\private",
            response_text,
        )

        self.assertNotIn(
            "database.db",
            response_text,
        )

    def test_status_route_rejects_post(
        self,
    ):
        response = self.client.post(
            "/dashboard/reference-data/status"
        )

        self.assertEqual(
            response.status_code,
            405,
        )


if __name__ == "__main__":
    unittest.main()