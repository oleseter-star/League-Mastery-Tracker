import copy
import json
import sqlite3
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.backup_service import BackupService
from application.services.json_import_execution_service import (
    JsonImportExecutionError,
    JsonImportExecutionService,
)
from application.services.json_import_plan_service import (
    JsonImportPlanService,
)
from application.services.json_import_preview_service import (
    JsonImportPreviewService,
)
from application.services.json_import_read_service import (
    JsonImportReadService,
)


class JsonImportExecutionServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        temporary_path = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            temporary_path
            / "test.db"
        )

        self.backup_directory = (
            temporary_path
            / "backups"
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
            DATABASE_FILE=self.database_file,
            BACKUP_DIR=self.backup_directory,
        )

        db.init_app(
            self.app
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

    def tearDown(self):
        try:
            db.session.rollback()
            db.session.remove()

            db.drop_all()

            db.engine.dispose()

        finally:
            self.app_context.pop()

            self.temporary_directory.cleanup()

    def _build_document(
        self,
        champions=None,
        persons=None,
    ):
        normalized_champions = list(
            champions
            or []
        )

        normalized_persons = list(
            persons
            or []
        )

        account_count = 0
        mastery_count = 0

        for person in normalized_persons:
            accounts = person[
                "riot_accounts"
            ]

            account_count += len(
                accounts
            )

            for account in accounts:
                mastery_count += len(
                    account[
                        "champion_mastery"
                    ]
                )

        return {
            "format": (
                "league-mastery-tracker-export"
            ),
            "format_version": 1,
            "database_schema_version": 1,
            "exported_at": (
                "2026-07-16T12:00:00Z"
            ),
            "record_counts": {
                "persons": len(
                    normalized_persons
                ),
                "riot_accounts": (
                    account_count
                ),
                "champions": len(
                    normalized_champions
                ),
                "mastery_records": (
                    mastery_count
                ),
            },
            "data": {
                "champions": (
                    normalized_champions
                ),
                "persons": (
                    normalized_persons
                ),
            },
        }

    def _champion(
        self,
        riot_champion_id=22,
        name="Ashe",
        image="Ashe.png",
        source="data_dragon",
    ):
        return {
            "riot_champion_id": (
                riot_champion_id
            ),
            "name": name,
            "image": image,
            "source": source,
        }

    def _account(
        self,
        puuid="new-puuid",
        game_name="NewPlayer",
        tag_line="EUW",
        last_sync="2026-07-16T11:00:00Z",
        mastery=None,
    ):
        return {
            "game_name": game_name,
            "tag_line": tag_line,
            "puuid": puuid,
            "platform_region": "euw1",
            "last_sync": last_sync,
            "champion_mastery": list(
                mastery
                or []
            ),
        }

    def _person(
        self,
        display_name="Imported Person",
        accounts=None,
    ):
        return {
            "display_name": display_name,
            "riot_accounts": list(
                accounts
                or []
            ),
        }

    def _build_plan(
        self,
        document,
    ):
        raw_bytes = json.dumps(
            document,
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        read_result = (
            JsonImportReadService
            .read_stream(
                stream=BytesIO(
                    raw_bytes
                ),
                file_name="execution-test.json",
            )
        )

        preview = (
            JsonImportPreviewService
            .build_preview(
                read_result
            )
        )

        return (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=preview,
            )
        )

    def _create_local_person(
        self,
        display_name="Local Person",
    ):
        person = Person(
            display_name=display_name
        )

        db.session.add(
            person
        )

        db.session.flush()

        return person

    def _create_local_account(
        self,
        person,
        puuid="existing-puuid",
    ):
        account = RiotAccount(
            person_id=person.id,
            game_name="LocalPlayer",
            tag_line="LOCAL",
            puuid=puuid,
            platform_region="euw1",
        )

        db.session.add(
            account
        )

        db.session.flush()

        return account

    def _create_local_champion(
        self,
        riot_champion_id=22,
        name="Ashe",
        image="Ashe.png",
        source="data_dragon",
    ):
        champion = Champion(
            riot_champion_id=(
                riot_champion_id
            ),
            name=name,
            image=image,
            source=source,
        )

        db.session.add(
            champion
        )

        db.session.flush()

        return champion

    def _get_backup_files(
        self
    ):
        if not self.backup_directory.exists():
            return []

        return list(
            self.backup_directory.glob(
                "*.db"
            )
        )

    def test_applies_complete_import_with_required_backup(
        self
    ):
        document = self._build_document(
            champions=[
                self._champion()
            ],
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            mastery=[
                                {
                                    "riot_champion_id": 22,
                                    "mastery_points": 12345,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        plan = self._build_plan(
            document
        )

        result = (
            JsonImportExecutionService
            .apply_plan(
                plan
            )
        )

        self.assertTrue(
            result["applied"]
        )

        self.assertEqual(
            result["reason"],
            "import_applied",
        )

        self.assertEqual(
            result["created"],
            {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 1,
                "mastery_records": 1,
            },
        )

        self.assertEqual(
            result["reused"],
            {
                "champions": 0,
            },
        )

        self.assertTrue(
            result["backup_file"].is_file()
        )

        self.assertEqual(
            len(
                self._get_backup_files()
            ),
            1,
        )

        person = db.session.execute(
            db.select(
                Person
            )
        ).scalar_one()

        account = db.session.execute(
            db.select(
                RiotAccount
            )
        ).scalar_one()

        champion = db.session.execute(
            db.select(
                Champion
            )
        ).scalar_one()

        mastery = db.session.execute(
            db.select(
                ChampionMastery
            )
        ).scalar_one()

        self.assertEqual(
            person.display_name,
            "Imported Person",
        )

        self.assertEqual(
            account.person_id,
            person.id,
        )

        self.assertEqual(
            account.last_sync,
            datetime(
                2026,
                7,
                16,
                11,
                0,
                0,
            ),
        )

        self.assertEqual(
            mastery.riot_account_id,
            account.id,
        )

        self.assertEqual(
            mastery.champion_id,
            champion.id,
        )

        self.assertEqual(
            mastery.mastery_points,
            12345,
        )

        backup_connection = sqlite3.connect(
            str(
                result["backup_file"]
            )
        )

        try:
            backup_person_count = (
                backup_connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM persons
                    """
                ).fetchone()[0]
            )

        finally:
            backup_connection.close()

        self.assertEqual(
            backup_person_count,
            0,
        )

    def test_reuses_champion_without_overwriting_metadata(
        self
    ):
        local_champion = (
            self._create_local_champion(
                name=None,
                image=None,
                source="riot_api",
            )
        )

        local_champion_id = (
            local_champion.id
        )

        db.session.commit()

        document = self._build_document(
            champions=[
                self._champion()
            ],
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            mastery=[
                                {
                                    "riot_champion_id": 22,
                                    "mastery_points": 500,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        result = (
            JsonImportExecutionService
            .apply_plan(
                self._build_plan(
                    document
                )
            )
        )

        self.assertEqual(
            result["created"][
                "champions"
            ],
            0,
        )

        self.assertEqual(
            result["reused"][
                "champions"
            ],
            1,
        )

        champions = list(
            db.session.execute(
                db.select(
                    Champion
                )
            )
            .scalars()
            .all()
        )

        self.assertEqual(
            len(
                champions
            ),
            1,
        )

        self.assertEqual(
            champions[0].id,
            local_champion_id,
        )

        self.assertIsNone(
            champions[0].name
        )

        self.assertIsNone(
            champions[0].image
        )

        self.assertEqual(
            champions[0].source,
            "riot_api",
        )

        mastery = db.session.execute(
            db.select(
                ChampionMastery
            )
        ).scalar_one()

        self.assertEqual(
            mastery.champion_id,
            local_champion_id,
        )

    def test_refuses_plan_when_puuid_appears_after_planning(
        self
    ):
        document = self._build_document(
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            puuid="late-puuid"
                        )
                    ]
                )
            ]
        )

        plan = self._build_plan(
            document
        )

        local_person = (
            self._create_local_person()
        )

        self._create_local_account(
            person=local_person,
            puuid="late-puuid",
        )

        db.session.commit()

        with self.assertRaisesRegex(
            JsonImportExecutionError,
            "no longer matches",
        ):
            (
                JsonImportExecutionService
                .apply_plan(
                    plan
                )
            )

        self.assertEqual(
            self._get_backup_files(),
            [],
        )

    def test_refuses_plan_when_reused_champion_changes(
        self
    ):
        champion = (
            self._create_local_champion()
        )

        db.session.commit()

        document = self._build_document(
            champions=[
                self._champion()
            ]
        )

        plan = self._build_plan(
            document
        )

        champion.name = (
            "Changed Local Name"
        )

        db.session.commit()

        with self.assertRaisesRegex(
            JsonImportExecutionError,
            "Local metadata changed",
        ):
            (
                JsonImportExecutionService
                .apply_plan(
                    plan
                )
            )

        self.assertEqual(
            self._get_backup_files(),
            [],
        )

    def test_backup_failure_prevents_all_writes(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        plan = self._build_plan(
            document
        )

        with patch.object(
            BackupService,
            "create_backup",
            side_effect=OSError(
                "forced backup failure"
            ),
        ):
            with self.assertRaisesRegex(
                JsonImportExecutionError,
                "required database backup",
            ):
                (
                    JsonImportExecutionService
                    .apply_plan(
                        plan
                    )
                )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._get_backup_files(),
            [],
        )

    def test_failure_during_execution_rolls_back_all_writes(
        self
    ):
        document = self._build_document(
            champions=[
                self._champion()
            ],
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            mastery=[
                                {
                                    "riot_champion_id": 22,
                                    "mastery_points": 100,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        plan = self._build_plan(
            document
        )

        with patch.object(
            JsonImportExecutionService,
            "_create_mastery_record",
            side_effect=RuntimeError(
                "forced import failure"
            ),
        ):
            with self.assertRaisesRegex(
                JsonImportExecutionError,
                "rolled back",
            ):
                (
                    JsonImportExecutionService
                    .apply_plan(
                        plan
                    )
                )

        db.session.expire_all()

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            db.session.query(
                RiotAccount
            ).count(),
            0,
        )

        self.assertEqual(
            db.session.query(
                Champion
            ).count(),
            0,
        )

        self.assertEqual(
            db.session.query(
                ChampionMastery
            ).count(),
            0,
        )

        self.assertEqual(
            len(
                self._get_backup_files()
            ),
            1,
        )

    def test_refuses_uncommitted_scoped_session_changes(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        plan = self._build_plan(
            document
        )

        db.session.add(
            Person(
                display_name="Uncommitted Person"
            )
        )

        with self.assertRaisesRegex(
            JsonImportExecutionError,
            "uncommitted changes",
        ):
            (
                JsonImportExecutionService
                .apply_plan(
                    plan
                )
            )

        self.assertEqual(
            self._get_backup_files(),
            [],
        )

        db.session.rollback()

    def test_empty_plan_returns_no_op_without_backup(
        self
    ):
        document = self._build_document()

        result = (
            JsonImportExecutionService
            .apply_plan(
                self._build_plan(
                    document
                )
            )
        )

        self.assertFalse(
            result["applied"]
        )

        self.assertEqual(
            result["reason"],
            "no_database_changes",
        )

        self.assertIsNone(
            result["backup_file"]
        )

        self.assertEqual(
            self._get_backup_files(),
            [],
        )

    def test_tampered_plan_is_rejected_before_backup(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        immutable_plan = (
            self._build_plan(
                document
            )
        )

        tampered_plan = (
            JsonImportPlanService
            .to_plain_dict(
                immutable_plan
            )
        )

        tampered_plan[
            "persons"
        ][0][
            "display_name"
        ] = "Tampered Name"

        with self.assertRaisesRegex(
            JsonImportExecutionError,
            "failed validation",
        ):
            (
                JsonImportExecutionService
                .apply_plan(
                    tampered_plan
                )
            )

        self.assertEqual(
            self._get_backup_files(),
            [],
        )


if __name__ == "__main__":
    unittest.main()