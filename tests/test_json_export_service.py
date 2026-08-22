import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.database_migration_service import (
    DatabaseMigrationService,
)
from application.services.json_export_service import (
    JsonExportError,
    JsonExportService,
)


class JsonExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "export-test.db"
        )

        database_uri = (
            "sqlite:///"
            + self.database_file.as_posix()
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=(
                database_uri
            ),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DATABASE_FILE=str(
                self.database_file
            ),
        )

        db.init_app(
            self.app
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        DatabaseMigrationService.initialize_or_migrate()

        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

        self.app_context.pop()
        self.temporary_directory.cleanup()

    def _create_complete_dataset(self):
        person_zulu = Person(
            display_name="Zulu",
        )

        person_ase = Person(
            display_name="Åse",
        )

        db.session.add_all(
            [
                person_zulu,
                person_ase,
            ]
        )

        db.session.flush()

        account_zulu = RiotAccount(
            person_id=person_zulu.id,
            game_name="ZedPlayer",
            tag_line="EUW",
            puuid="puuid-zulu",
            platform_region="euw1",
            last_sync=datetime(
                2026,
                7,
                16,
                10,
                30,
                45,
            ),
        )

        account_ase_second = RiotAccount(
            person_id=person_ase.id,
            game_name="Beta",
            tag_line="200",
            puuid="puuid-ase-beta",
            platform_region="euw1",
            last_sync=None,
        )

        account_ase_first = RiotAccount(
            person_id=person_ase.id,
            game_name="Alpha",
            tag_line="100",
            puuid="puuid-ase-alpha",
            platform_region="euw1",
            last_sync=datetime(
                2026,
                7,
                16,
                11,
                0,
                0,
                tzinfo=timezone.utc,
            ),
        )

        db.session.add_all(
            [
                account_zulu,
                account_ase_second,
                account_ase_first,
            ]
        )

        db.session.flush()

        champion_high = Champion(
            riot_champion_id=266,
            name="Aatrox",
            image="Aatrox.png",
            source="data_dragon",
        )

        champion_low = Champion(
            riot_champion_id=22,
            name="Ashe",
            image="Ashe.png",
            source="data_dragon",
        )

        champion_unknown = Champion(
            riot_champion_id=999999,
            name=None,
            image=None,
            source="riot_api",
        )

        db.session.add_all(
            [
                champion_high,
                champion_low,
                champion_unknown,
            ]
        )

        db.session.flush()

        mastery_records = [
            ChampionMastery(
                riot_account_id=(
                    account_ase_first.id
                ),
                champion_id=(
                    champion_high.id
                ),
                mastery_points=500,
            ),
            ChampionMastery(
                riot_account_id=(
                    account_ase_first.id
                ),
                champion_id=(
                    champion_low.id
                ),
                mastery_points=1500,
            ),
            ChampionMastery(
                riot_account_id=(
                    account_zulu.id
                ),
                champion_id=(
                    champion_unknown.id
                ),
                mastery_points=250,
            ),
        ]

        db.session.add_all(
            mastery_records
        )

        db.session.commit()

    def test_export_contains_versioned_top_level_contract(self):
        self._create_complete_dataset()

        exported_at = datetime(
            2026,
            7,
            16,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        document = (
            JsonExportService
            .build_export_document(
                exported_at=exported_at
            )
        )

        self.assertEqual(
            document["format"],
            "league-mastery-tracker-export",
        )

        self.assertEqual(
            document["format_version"],
            1,
        )

        self.assertEqual(
            document[
                "database_schema_version"
            ],
            1,
        )

        self.assertEqual(
            document["exported_at"],
            "2026-07-16T12:00:00Z",
        )

    def test_export_contains_correct_record_counts(self):
        self._create_complete_dataset()

        document = (
            JsonExportService
            .build_export_document()
        )

        self.assertEqual(
            document["record_counts"],
            {
                "persons": 2,
                "riot_accounts": 3,
                "champions": 3,
                "mastery_records": 3,
            },
        )

    def test_export_excludes_internal_database_ids(self):
        self._create_complete_dataset()

        document = (
            JsonExportService
            .build_export_document()
        )

        serialized_document = json.dumps(
            document
        )

        self.assertNotIn(
            '"person_id"',
            serialized_document,
        )

        self.assertNotIn(
            '"riot_account_id"',
            serialized_document,
        )

        self.assertNotIn(
            '"champion_id"',
            serialized_document,
        )

        self.assertNotIn(
            '"id"',
            serialized_document,
        )

    def test_persons_accounts_champions_and_mastery_are_sorted(
        self
    ):
        self._create_complete_dataset()

        document = (
            JsonExportService
            .build_export_document()
        )

        exported_champions = document[
            "data"
        ]["champions"]

        self.assertEqual(
            [
                champion[
                    "riot_champion_id"
                ]
                for champion in exported_champions
            ],
            [
                22,
                266,
                999999,
            ],
        )

        exported_persons = document[
            "data"
        ]["persons"]

        self.assertEqual(
            [
                person["display_name"]
                for person in exported_persons
            ],
            [
                "Zulu",
                "Åse",
            ],
        )

        ase_accounts = exported_persons[
            1
        ]["riot_accounts"]

        self.assertEqual(
            [
                account["game_name"]
                for account in ase_accounts
            ],
            [
                "Alpha",
                "Beta",
            ],
        )

        alpha_mastery = ase_accounts[
            0
        ]["champion_mastery"]

        self.assertEqual(
            [
                mastery[
                    "riot_champion_id"
                ]
                for mastery in alpha_mastery
            ],
            [
                22,
                266,
            ],
        )

    def test_last_sync_is_exported_as_utc_or_null(self):
        self._create_complete_dataset()

        document = (
            JsonExportService
            .build_export_document()
        )

        exported_persons = document[
            "data"
        ]["persons"]

        ase_accounts = exported_persons[
            1
        ]["riot_accounts"]

        self.assertEqual(
            ase_accounts[
                0
            ]["last_sync"],
            "2026-07-16T11:00:00Z",
        )

        self.assertIsNone(
            ase_accounts[
                1
            ]["last_sync"]
        )

        zulu_account = exported_persons[
            0
        ]["riot_accounts"][0]

        self.assertEqual(
            zulu_account["last_sync"],
            "2026-07-16T10:30:45Z",
        )

    def test_unknown_champion_is_preserved(self):
        self._create_complete_dataset()

        document = (
            JsonExportService
            .build_export_document()
        )

        unknown_champion = document[
            "data"
        ]["champions"][2]

        self.assertEqual(
            unknown_champion[
                "riot_champion_id"
            ],
            999999,
        )

        self.assertIsNone(
            unknown_champion["name"]
        )

        self.assertIsNone(
            unknown_champion["image"]
        )

        self.assertEqual(
            unknown_champion["source"],
            "riot_api",
        )

    def test_json_is_utf8_and_ends_with_newline(self):
        person = Person(
            display_name="Ægir Øst",
        )

        db.session.add(
            person
        )

        db.session.commit()

        export_bytes = (
            JsonExportService
            .build_export_bytes(
                exported_at=datetime(
                    2026,
                    7,
                    16,
                    12,
                    0,
                    0,
                    tzinfo=timezone.utc,
                )
            )
        )

        decoded_export = export_bytes.decode(
            "utf-8"
        )

        self.assertIn(
            "Ægir Øst",
            decoded_export,
        )

        self.assertTrue(
            decoded_export.endswith(
                "\n"
            )
        )

        parsed_export = json.loads(
            decoded_export
        )

        self.assertEqual(
            parsed_export[
                "data"
            ]["persons"][0]["display_name"],
            "Ægir Øst",
        )

    def test_export_filename_uses_utc_timestamp(self):
        file_name = (
            JsonExportService
            .build_export_file_name(
                exported_at=datetime(
                    2026,
                    7,
                    16,
                    14,
                    30,
                    0,
                    tzinfo=timezone.utc,
                )
            )
        )

        self.assertEqual(
            file_name,
            (
                "league_mastery_tracker_export_"
                "20260716T143000Z.json"
            ),
        )

    def test_export_fails_when_database_is_unversioned(self):
        connection = db.engine.raw_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                DELETE FROM application_metadata
                WHERE key = ?
                """,
                (
                    "database_schema_version",
                ),
            )

            connection.commit()

        finally:
            connection.close()

        with self.assertRaises(
            JsonExportError
        ):
            (
                JsonExportService
                .build_export_document()
            )


if __name__ == "__main__":
    unittest.main()