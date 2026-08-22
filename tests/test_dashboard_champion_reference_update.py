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


class DashboardChampionReferenceUpdateTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "dashboard-reference-update-test"
            ),
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

        self.update_result = {
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

    def _get_flashed_messages(
        self,
    ):
        with self.client.session_transaction() as session:
            return list(
                session.get(
                    "_flashes",
                    [],
                )
            )

    def _post_with_services(
        self,
        *,
        update_result=None,
        update_error=None,
    ):
        with patch.object(
            dashboard_module,
            "ChampionReferenceUpdateService",
            create=True,
        ) as update_service_class, patch.object(
            dashboard_module,
            "DataDragonService",
            create=True,
        ) as legacy_service_class:
            update_service = (
                update_service_class
                .return_value
            )

            if update_error is not None:
                update_service.update_reference_data.side_effect = (
                    update_error
                )

            else:
                update_service.update_reference_data.return_value = (
                    update_result
                    if update_result is not None
                    else self.update_result
                )

            legacy_service_class.return_value.refresh_reference_data.return_value = {
                "updated": False,
                "version": "15.14.1",
                "created": 0,
                "changed": 0,
                "unchanged": 0,
                "missing_references": 0,
            }

            response = self.client.post(
                "/dashboard/reference-data/refresh"
            )

        return {
            "response": response,
            "update_service_class": (
                update_service_class
            ),
            "update_service": (
                update_service
            ),
            "legacy_service_class": (
                legacy_service_class
            ),
        }

    def test_route_uses_new_update_service(
        self,
    ):
        result = self._post_with_services()

        result[
            "update_service_class"
        ].assert_called_once_with()

        result[
            "update_service"
        ].update_reference_data.assert_called_once_with()

        result[
            "legacy_service_class"
        ].assert_not_called()

    def test_successful_update_redirects_home(
        self,
    ):
        result = self._post_with_services()

        response = result[
            "response"
        ]

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            response.headers[
                "Location"
            ],
            "/",
        )

    def test_successful_update_flashes_merge_summary(
        self,
    ):
        self._post_with_services()

        flashes = (
            self._get_flashed_messages()
        )

        self.assertEqual(
            flashes,
            [
                (
                    "success",
                    (
                        "Champion reference data was updated "
                        "to version 15.15.1. "
                        "2 created, 3 updated, "
                        "and 4 unchanged. "
                        "1 manual entry and "
                        "5 existing champions "
                        "outside the dataset were preserved."
                    ),
                ),
            ],
        )

    def test_current_dataset_flashes_current_version(
        self,
    ):
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

        self._post_with_services(
            update_result=current_result
        )

        flashes = (
            self._get_flashed_messages()
        )

        self.assertEqual(
            flashes,
            [
                (
                    "success",
                    (
                        "Champion reference data is already "
                        "up to date at version 15.15.1."
                    ),
                ),
            ],
        )

    def test_update_failure_flashes_controlled_error(
        self,
    ):
        result = self._post_with_services(
            update_error=(
                ChampionReferenceUpdateError(
                    "internal update failure"
                )
            )
        )

        self.assertEqual(
            result[
                "response"
            ].status_code,
            302,
        )

        flashes = (
            self._get_flashed_messages()
        )

        self.assertEqual(
            flashes,
            [
                (
                    "error",
                    (
                        "Champion reference data could not be "
                        "updated. Existing local data remains "
                        "available."
                    ),
                ),
            ],
        )

    def test_internal_error_text_is_not_exposed(
        self,
    ):
        self._post_with_services(
            update_error=(
                ChampionReferenceUpdateError(
                    "sensitive internal path "
                    "C:\\private\\reference"
                )
            )
        )

        flashes = (
            self._get_flashed_messages()
        )

        combined_messages = " ".join(
            message
            for _, message in flashes
        )

        self.assertNotIn(
            "C:\\private\\reference",
            combined_messages,
        )

        self.assertNotIn(
            "sensitive internal path",
            combined_messages,
        )


if __name__ == "__main__":
    unittest.main()