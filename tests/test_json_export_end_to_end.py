import importlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.json_export_validation_service import (
    JsonExportValidationService,
)


app_module = importlib.import_module(
    "application.app"
)


class JsonExportEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "export-end-to-end.db"
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
        backup_directory = self.backup_directory
        reference_directory = (
            self.reference_directory
        )

        class JsonExportEndToEndConfig:
            TESTING = True
            DEBUG = False

            SQLALCHEMY_DATABASE_URI = database_uri
            SQLALCHEMY_TRACK_MODIFICATIONS = False

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

            RIOT_API_KEY = (
                "must-not-appear-in-export"
            )

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
            "json-export-end-to-end-test"
        )

        self.config_patch = patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    JsonExportEndToEndConfig
                ),
            },
        )

        self.config_patch.start()

        self.app = app_module.create_app(
            self.config_name
        )

        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

        self.config_patch.stop()
        self.temporary_directory.cleanup()

    def _create_complete_dataset(self):
        with self.app.app_context():
            person = Person(
                display_name="Ægir Export",
            )

            db.session.add(
                person
            )

            db.session.flush()

            account = RiotAccount(
                person_id=person.id,
                game_name="ExportPlayer",
                tag_line="EUW",
                puuid="end-to-end-puuid",
                platform_region="euw1",
                last_sync=datetime(
                    2026,
                    7,
                    16,
                    16,
                    30,
                    0,
                    tzinfo=timezone.utc,
                ),
            )

            db.session.add(
                account
            )

            db.session.flush()

            champion = Champion(
                riot_champion_id=22,
                name="Ashe",
                image="Ashe.png",
                source="data_dragon",
            )

            db.session.add(
                champion
            )

            db.session.flush()

            mastery = ChampionMastery(
                riot_account_id=account.id,
                champion_id=champion.id,
                mastery_points=123456,
            )

            db.session.add(
                mastery
            )

            db.session.commit()

    def test_actual_app_download_produces_valid_complete_export(
        self
    ):
        self._create_complete_dataset()

        response = self.client.get(
            "/settings/data-export/download"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        document = json.loads(
            response.data.decode(
                "utf-8"
            )
        )

        validated_counts = (
            JsonExportValidationService
            .validate_document(
                document
            )
        )

        self.assertEqual(
            validated_counts,
            {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 1,
                "mastery_records": 1,
            },
        )

        exported_person = (
            document[
                "data"
            ]["persons"][0]
        )

        exported_account = (
            exported_person[
                "riot_accounts"
            ][0]
        )

        exported_mastery = (
            exported_account[
                "champion_mastery"
            ][0]
        )

        self.assertEqual(
            exported_person["display_name"],
            "Ægir Export",
        )

        self.assertEqual(
            exported_account["game_name"],
            "ExportPlayer",
        )

        self.assertEqual(
            exported_account["tag_line"],
            "EUW",
        )

        self.assertEqual(
            exported_account["puuid"],
            "end-to-end-puuid",
        )

        self.assertEqual(
            exported_mastery,
            {
                "riot_champion_id": 22,
                "mastery_points": 123456,
            },
        )

        serialized_document = json.dumps(
            document,
            ensure_ascii=False,
        )

        self.assertNotIn(
            "must-not-appear-in-export",
            serialized_document,
        )

        self.assertNotIn(
            "SECRET_KEY",
            serialized_document,
        )

        self.assertNotIn(
            "RIOT_API_KEY",
            serialized_document,
        )

    def test_actual_app_registers_export_page_and_download(
        self
    ):
        page_response = self.client.get(
            "/settings/data-export"
        )

        download_response = self.client.get(
            "/settings/data-export/download"
        )

        self.assertEqual(
            page_response.status_code,
            200,
        )

        self.assertEqual(
            download_response.status_code,
            200,
        )

        self.assertIn(
            b"Download JSON export",
            page_response.data,
        )

        self.assertEqual(
            download_response.content_type,
            "application/json; charset=utf-8",
        )

        self.assertTrue(
            download_response.headers[
                "Content-Disposition"
            ].startswith(
                "attachment; filename="
            )
        )


if __name__ == "__main__":
    unittest.main()