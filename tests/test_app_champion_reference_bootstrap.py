import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import current_app, has_app_context

from application.database.database import db


app_module = importlib.import_module(
    "application.app"
)


class AppChampionReferenceBootstrapTests(
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

        class ChampionBootstrapTestConfig:
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
            "champion-bootstrap-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    ChampionBootstrapTestConfig
                ),
            },
        )

        self.config_patch.start()

        self.created_apps = []

        self.bootstrap_result = {
            "active_source": "bundled",
            "reference_data_available": True,
            "database_fallback": False,
            "data_dragon_version": (
                "15.14.1"
            ),
            "locale": "en_US",
            "dataset_directory": (
                self.root_directory
                / "bundled"
                / "data_dragon"
            ),
            "icons_directory": (
                self.root_directory
                / "bundled"
                / "data_dragon"
                / "champion_icons"
            ),
            "warnings": [],
            "merge": {
                "created": 2,
                "updated": 0,
            },
        }

    def tearDown(self):
        for app in self.created_apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

        self.config_patch.stop()

        self.temporary_directory.cleanup()

    def _create_app(self):
        app = app_module.create_app(
            self.config_name
        )

        self.created_apps.append(
            app
        )

        return app

    def test_bootstrap_is_called_once_during_startup(
        self
    ):
        with patch.object(
            app_module,
            "ChampionReferenceBootstrapService",
            create=True,
        ) as bootstrap_class:
            bootstrap_instance = (
                bootstrap_class.return_value
            )

            bootstrap_instance.bootstrap.return_value = (
                self.bootstrap_result
            )

            self._create_app()

        bootstrap_class.assert_called_once_with()

        bootstrap_instance.bootstrap.assert_called_once_with()

    def test_bootstrap_runs_inside_application_context(
        self
    ):
        context_observation = {}

        def bootstrap():
            context_observation[
                "has_app_context"
            ] = has_app_context()

            context_observation[
                "database_file"
            ] = current_app.config[
                "DATABASE_FILE"
            ]

            return self.bootstrap_result

        with patch.object(
            app_module,
            "ChampionReferenceBootstrapService",
            create=True,
        ) as bootstrap_class:
            bootstrap_class.return_value.bootstrap.side_effect = (
                bootstrap
            )

            self._create_app()

        self.assertTrue(
            context_observation[
                "has_app_context"
            ]
        )

        self.assertEqual(
            context_observation[
                "database_file"
            ],
            str(
                self.database_file
            ),
        )

    def test_bootstrap_runs_after_database_tables_are_created(
        self
    ):
        database_tables_created = {
            "value": False,
        }

        original_create_all = (
            app_module.db.create_all
        )

        def create_all():
            original_create_all()

            database_tables_created[
                "value"
            ] = True

        def bootstrap():
            self.assertTrue(
                database_tables_created[
                    "value"
                ]
            )

            return self.bootstrap_result

        with patch.object(
            app_module.db,
            "create_all",
            side_effect=create_all,
        ), patch.object(
            app_module,
            "ChampionReferenceBootstrapService",
            create=True,
        ) as bootstrap_class:
            bootstrap_class.return_value.bootstrap.side_effect = (
                bootstrap
            )

            self._create_app()

        bootstrap_class.return_value.bootstrap.assert_called_once_with()

    def test_bootstrap_result_is_stored_in_app_config(
        self
    ):
        with patch.object(
            app_module,
            "ChampionReferenceBootstrapService",
            create=True,
        ) as bootstrap_class:
            bootstrap_class.return_value.bootstrap.return_value = (
                self.bootstrap_result
            )

            app = self._create_app()

        self.assertEqual(
            app.config[
                "STARTUP_CHAMPION_REFERENCE_RESULT"
            ],
            self.bootstrap_result,
        )


if __name__ == "__main__":
    unittest.main()