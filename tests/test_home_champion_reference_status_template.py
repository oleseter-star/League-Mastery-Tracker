import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db


app_module = importlib.import_module(
    "application.app"
)

home_module = importlib.import_module(
    "application.routes.home"
)


class HomeChampionReferenceStatusTemplateTests(
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

        class HomeStatusTemplateTestConfig:
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
            "home-status-template-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    HomeStatusTemplateTestConfig
                ),
            },
        )

        self.config_patch.start()

        self.bootstrap_patch = patch.object(
            app_module,
            "ChampionReferenceBootstrapService",
        )

        bootstrap_class = (
            self.bootstrap_patch.start()
        )

        bootstrap_class.return_value.bootstrap.return_value = {
            "active_source": "database",
            "reference_data_available": False,
            "database_fallback": True,
            "data_dragon_version": None,
            "locale": None,
            "dataset_directory": None,
            "icons_directory": None,
            "warnings": [],
            "merge": None,
        }

        self.dashboard_patch = patch.object(
            home_module.DashboardService,
            "get_home_dashboard",
            return_value={
                "persons": [],
                "person_count": 0,
            },
        )

        self.dashboard_patch.start()

        self.status_patch = patch.object(
            home_module,
            "ChampionReferenceStatusService",
        )

        self.status_service_class = (
            self.status_patch.start()
        )

        self.status_service = (
            self.status_service_class
            .return_value
        )

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

        self.status_patch.stop()
        self.dashboard_patch.stop()
        self.bootstrap_patch.stop()
        self.config_patch.stop()

        self.temporary_directory.cleanup()

    @staticmethod
    def _build_status(
        *,
        active_source="bundled",
        active_source_label=(
            "Bundled dataset"
        ),
        reference_data_available=True,
        uses_bundled_fallback=True,
        uses_local_cache=False,
        database_only=False,
        version="15.14.1",
        locale="en_US",
        dataset_count=170,
        database_count=171,
        missing_name_count=1,
        missing_image_count=1,
        missing_metadata_count=1,
        has_missing_metadata=True,
        last_successful_update=(
            "2026-07-23T12:30:45+00:00"
        ),
        last_update_error=None,
        warnings=None,
    ):
        return {
            "active_source": active_source,
            "active_source_label": (
                active_source_label
            ),
            "reference_data_available": (
                reference_data_available
            ),
            "uses_bundled_fallback": (
                uses_bundled_fallback
            ),
            "uses_local_cache": (
                uses_local_cache
            ),
            "database_only": database_only,
            "data_dragon_version": version,
            "locale": locale,
            "dataset_champion_count": (
                dataset_count
            ),
            "database_champion_count": (
                database_count
            ),
            "missing_name_count": (
                missing_name_count
            ),
            "missing_image_count": (
                missing_image_count
            ),
            "missing_metadata_count": (
                missing_metadata_count
            ),
            "has_missing_metadata": (
                has_missing_metadata
            ),
            "last_successful_update": (
                last_successful_update
            ),
            "last_update_error": (
                last_update_error
            ),
            "warnings": list(
                warnings
                or []
            ),
        }

    def _get_home_html(
        self,
        status,
    ):
        self.status_service.get_status.return_value = (
            status
        )

        response = self.client.get(
            "/"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        return response.get_data(
            as_text=True
        )

    def test_reference_status_section_is_visible(
        self
    ):
        html = self._get_home_html(
            self._build_status()
        )

        self.assertIn(
            "Champion reference data",
            html,
        )

        self.assertIn(
            "Bundled dataset",
            html,
        )

    def test_version_locale_and_counts_are_visible(
        self
    ):
        html = self._get_home_html(
            self._build_status()
        )

        self.assertIn(
            "15.14.1",
            html,
        )

        self.assertIn(
            "en_US",
            html,
        )

        self.assertIn(
            "170",
            html,
        )

        self.assertIn(
            "171",
            html,
        )

    def test_bundled_fallback_is_explained(
        self
    ):
        html = self._get_home_html(
            self._build_status()
        )

        self.assertIn(
            (
                "The application is using "
                "the bundled dataset."
            ),
            html,
        )

    def test_local_cache_source_is_explained(
        self
    ):
        html = self._get_home_html(
            self._build_status(
                active_source="local_cache",
                active_source_label=(
                    "Local cache"
                ),
                uses_bundled_fallback=False,
                uses_local_cache=True,
            )
        )

        self.assertIn(
            "Local cache",
            html,
        )

        self.assertIn(
            (
                "The application is using "
                "a newer local cache."
            ),
            html,
        )

    def test_database_only_fallback_is_explained(
        self
    ):
        html = self._get_home_html(
            self._build_status(
                active_source="database_only",
                active_source_label=(
                    "Database only"
                ),
                reference_data_available=False,
                uses_bundled_fallback=False,
                database_only=True,
                version=None,
                locale=None,
                dataset_count=None,
                last_successful_update=None,
                warnings=[
                    (
                        "Champion reference data "
                        "is unavailable."
                    ),
                ],
            )
        )

        self.assertIn(
            "Database only",
            html,
        )

        self.assertIn(
            (
                "Existing database content "
                "remains available."
            ),
            html,
        )

        self.assertIn(
            (
                "Champion reference data "
                "is unavailable."
            ),
            html,
        )

    def test_missing_metadata_and_management_link_are_visible(
        self
    ):
        html = self._get_home_html(
            self._build_status(
                missing_name_count=2,
                missing_image_count=3,
                missing_metadata_count=4,
            )
        )

        self.assertIn(
            "4",
            html,
        )

        self.assertIn(
            "2",
            html,
        )

        self.assertIn(
            "3",
            html,
        )

        self.assertIn(
            "Manage missing champion names",
            html,
        )

        self.assertIn(
            "/champions/missing",
            html,
        )

    def test_manual_update_form_and_last_update_are_visible(
        self
    ):
        html = self._get_home_html(
            self._build_status()
        )

        self.assertIn(
            (
                "/dashboard/"
                "reference-data/refresh"
            ),
            html,
        )

        self.assertIn(
            "Check for updates",
            html,
        )

        self.assertIn(
            "2026-07-23T12:30:45+00:00",
            html,
        )

        self.assertNotIn(
            "ddragon.leagueoflegends.com",
            html,
        )


if __name__ == "__main__":
    unittest.main()