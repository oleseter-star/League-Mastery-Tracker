import importlib
import unittest
from unittest.mock import patch

from flask import Blueprint, Flask

from application.services.champion_reference_update_service import (
    ChampionReferenceUpdateError,
)


dashboard_module = importlib.import_module(
    "application.routes.dashboard"
)


home_bp = Blueprint(
    "home",
    __name__,
)


@home_bp.route("/")
def home():
    return "Test home"


class DashboardChampionReferenceStatusTrackingTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "dashboard-reference-status-test"
            ),
            CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE=None,
            CHAMPION_REFERENCE_LAST_UPDATE_ERROR=None,
        )

        self.app.register_blueprint(
            home_bp
        )

        self.app.register_blueprint(
            dashboard_module.dashboard_bp
        )

        self.client = (
            self.app.test_client()
        )

        self.updated_result = {
            "status": "updated",
            "updated": True,
            "forced": False,
            "previous_version": (
                "15.14.1"
            ),
            "data_dragon_version": (
                "15.15.1"
            ),
            "active_source": (
                "local_cache"
            ),
            "dataset": {
                "manifest": {
                    "data_dragon_version": (
                        "15.15.1"
                    ),
                    "generated_at": (
                        "2026-07-23T16:45:00+00:00"
                    ),
                },
            },
            "merge": {
                "created": 2,
                "updated": 3,
                "unchanged": 4,
                "preserved_manual": 1,
                "preserved_existing": 5,
                "database_count": 15,
            },
        }

    def _post_update(
        self,
        *,
        result=None,
        error=None,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceUpdateService",
        ) as update_service_class:
            update_service = (
                update_service_class.return_value
            )

            if error is not None:
                update_service.update_reference_data.side_effect = (
                    error
                )

            else:
                update_service.update_reference_data.return_value = (
                    result
                    if result is not None
                    else self.updated_result
                )

            return self.client.post(
                "/dashboard/reference-data/refresh"
            )

    def test_successful_update_records_generated_timestamp(
        self,
    ):
        self._post_update()

        self.assertEqual(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
            ],
            "2026-07-23T16:45:00+00:00",
        )

    def test_successful_update_clears_previous_error(
        self,
    ):
        self.app.config[
            "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
        ] = (
            "Previous controlled error."
        )

        self._post_update()

        self.assertIsNone(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
            ]
        )

    def test_current_check_does_not_replace_success_timestamp(
        self,
    ):
        existing_timestamp = (
            "2026-07-22T10:00:00+00:00"
        )

        self.app.config[
            "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
        ] = existing_timestamp

        current_result = {
            "status": "current",
            "updated": False,
            "forced": False,
            "previous_version": (
                "15.15.1"
            ),
            "data_dragon_version": (
                "15.15.1"
            ),
            "active_source": (
                "local_cache"
            ),
            "dataset": None,
            "merge": None,
        }

        self._post_update(
            result=current_result
        )

        self.assertEqual(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
            ],
            existing_timestamp,
        )

    def test_current_check_clears_previous_error(
        self,
    ):
        self.app.config[
            "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
        ] = (
            "Previous controlled error."
        )

        current_result = {
            "status": "current",
            "updated": False,
            "forced": False,
            "previous_version": (
                "15.15.1"
            ),
            "data_dragon_version": (
                "15.15.1"
            ),
            "active_source": (
                "local_cache"
            ),
            "dataset": None,
            "merge": None,
        }

        self._post_update(
            result=current_result
        )

        self.assertIsNone(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
            ]
        )

    def test_failed_update_records_controlled_error(
        self,
    ):
        self._post_update(
            error=(
                ChampionReferenceUpdateError(
                    "Sensitive internal failure."
                )
            )
        )

        self.assertEqual(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
            ],
            (
                "Champion reference data could "
                "not be updated."
            ),
        )

    def test_failed_update_preserves_success_timestamp(
        self,
    ):
        existing_timestamp = (
            "2026-07-22T10:00:00+00:00"
        )

        self.app.config[
            "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
        ] = existing_timestamp

        self._post_update(
            error=(
                ChampionReferenceUpdateError(
                    "Update failed."
                )
            )
        )

        self.assertEqual(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
            ],
            existing_timestamp,
        )

    def test_internal_error_text_is_not_stored(
        self,
    ):
        self._post_update(
            error=(
                ChampionReferenceUpdateError(
                    "C:\\private\\reference\\manifest.json"
                )
            )
        )

        stored_error = self.app.config[
            "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
        ]

        self.assertNotIn(
            "C:\\private",
            stored_error,
        )

        self.assertNotIn(
            "manifest.json",
            stored_error,
        )

    def test_invalid_generated_timestamp_is_not_recorded(
        self,
    ):
        self.updated_result[
            "dataset"
        ][
            "manifest"
        ][
            "generated_at"
        ] = "   "

        self._post_update()

        self.assertIsNone(
            self.app.config[
                "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
            ]
        )


if __name__ == "__main__":
    unittest.main()