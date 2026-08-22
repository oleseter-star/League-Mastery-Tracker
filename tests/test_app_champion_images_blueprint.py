import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db


app_module = importlib.import_module(
    "application.app"
)

image_route_module = importlib.import_module(
    "application.routes.champion_images"
)


class AppChampionImagesBlueprintTests(
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

        class ChampionImagesTestConfig:
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
            "champion-images-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    ChampionImagesTestConfig
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

        self.bootstrap_patch.stop()
        self.config_patch.stop()

        self.temporary_directory.cleanup()

    def test_champion_image_route_is_registered(
        self
    ):
        route_rules = {
            rule.rule
            for rule in self.app.url_map.iter_rules()
        }

        self.assertIn(
            (
                "/champions/images/"
                "<string:image_filename>"
            ),
            route_rules,
        )

    def test_registered_route_returns_local_png(
        self
    ):
        image_file = (
            self.root_directory
            / "Annie.png"
        )

        image_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"registered-image"
        )

        image_file.write_bytes(
            image_bytes
        )

        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.return_value = {
                "active_source": "bundled",
                "image_file": image_file,
                "mime_type": "image/png",
                "placeholder": False,
            }

            response = self.client.get(
                "/champions/images/Annie.png"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.mimetype,
            "image/png",
        )

        self.assertEqual(
            response.data,
            image_bytes,
        )

    def test_registered_route_returns_placeholder(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.return_value = {
                "active_source": "database",
                "image_file": None,
                "mime_type": "image/svg+xml",
                "placeholder": True,
            }

            response = self.client.get(
                "/champions/images/Missing.png"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.mimetype,
            "image/svg+xml",
        )

        self.assertIn(
            "<svg",
            response.get_data(
                as_text=True
            ),
        )

    def test_existing_dashboard_route_remains_registered(
        self
    ):
        route_rules = {
            rule.rule
            for rule in self.app.url_map.iter_rules()
        }

        self.assertIn(
            "/dashboard",
            route_rules,
        )

        self.assertIn(
            (
                "/dashboard/"
                "reference-data/status"
            ),
            route_rules,
        )


if __name__ == "__main__":
    unittest.main()