import json
import unittest
from io import BytesIO
from unittest.mock import patch

from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.json_export_validation_service import (
    JsonExportValidationError,
)
from application.services.json_import_preview_service import (
    JsonImportPreviewError,
    JsonImportPreviewService,
)
from application.services.json_import_read_service import (
    JsonImportReadService,
)


class JsonImportPreviewServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=(
                "sqlite:///:memory:"
            ),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
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
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

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

        riot_account_count = 0
        mastery_record_count = 0

        for person in normalized_persons:
            accounts = person[
                "riot_accounts"
            ]

            riot_account_count += len(
                accounts
            )

            for account in accounts:
                mastery_record_count += len(
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
                    riot_account_count
                ),
                "champions": len(
                    normalized_champions
                ),
                "mastery_records": (
                    mastery_record_count
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

    def _build_read_result(
        self,
        document,
    ):
        raw_bytes = json.dumps(
            document,
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        return (
            JsonImportReadService
            .read_stream(
                stream=BytesIO(
                    raw_bytes
                ),
                file_name="import-preview.json",
            )
        )

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
        champion_mastery=None,
    ):
        return {
            "game_name": game_name,
            "tag_line": tag_line,
            "puuid": puuid,
            "platform_region": "euw1",
            "last_sync": (
                "2026-07-16T11:00:00Z"
            ),
            "champion_mastery": list(
                champion_mastery
                or []
            ),
        }

    def _person(
        self,
        display_name="Imported Person",
        riot_accounts=None,
    ):
        return {
            "display_name": display_name,
            "riot_accounts": list(
                riot_accounts
                or []
            ),
        }

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
        game_name="LocalPlayer",
        tag_line="LOCAL",
    ):
        account = RiotAccount(
            person_id=person.id,
            game_name=game_name,
            tag_line=tag_line,
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

    def test_builds_empty_preview(
        self
    ):
        document = self._build_document()

        preview = (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        self.assertTrue(
            preview["can_import"]
        )

        self.assertEqual(
            preview["blockers"],
            [],
        )

        self.assertEqual(
            preview["warnings"],
            [],
        )

        self.assertEqual(
            preview["summary"][
                "persons_in_file"
            ],
            0,
        )

        self.assertEqual(
            preview["summary"][
                "champions_in_file"
            ],
            0,
        )

    def test_marks_new_data_as_importable(
        self
    ):
        document = self._build_document(
            champions=[
                self._champion()
            ],
            persons=[
                self._person(
                    riot_accounts=[
                        self._account(
                            champion_mastery=[
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

        preview = (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        self.assertTrue(
            preview["can_import"]
        )

        self.assertEqual(
            preview["champions"][0][
                "status"
            ],
            "new",
        )

        self.assertEqual(
            preview["persons"][0][
                "status"
            ],
            "ready",
        )

        self.assertEqual(
            preview["persons"][0][
                "riot_accounts"
            ][0]["status"],
            "new",
        )

        self.assertEqual(
            preview["summary"][
                "new_champions"
            ],
            1,
        )

        self.assertEqual(
            preview["summary"][
                "new_riot_accounts"
            ],
            1,
        )

        self.assertEqual(
            preview["summary"][
                "mastery_records_on_new_accounts"
            ],
            1,
        )

    def test_existing_puuid_blocks_account_and_mastery(
        self
    ):
        local_person = (
            self._create_local_person()
        )

        self._create_local_account(
            person=local_person,
            puuid="shared-puuid",
        )

        self._create_local_champion()

        db.session.commit()

        document = self._build_document(
            champions=[
                self._champion()
            ],
            persons=[
                self._person(
                    display_name="Different Person",
                    riot_accounts=[
                        self._account(
                            puuid="shared-puuid",
                            champion_mastery=[
                                {
                                    "riot_champion_id": 22,
                                    "mastery_points": 500,
                                }
                            ],
                        )
                    ],
                )
            ],
        )

        preview = (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        self.assertFalse(
            preview["can_import"]
        )

        self.assertEqual(
            preview["summary"][
                "blocker_count"
            ],
            1,
        )

        self.assertEqual(
            preview["summary"][
                "blocked_riot_accounts"
            ],
            1,
        )

        self.assertEqual(
            preview["summary"][
                "mastery_records_on_blocked_accounts"
            ],
            1,
        )

        self.assertEqual(
            preview["persons"][0][
                "status"
            ],
            "blocked",
        )

        self.assertEqual(
            preview["persons"][0][
                "riot_accounts"
            ][0]["status"],
            "blocked_existing_puuid",
        )

        self.assertEqual(
            preview["blockers"][0][
                "code"
            ],
            "existing_puuid",
        )

    def test_existing_champion_is_reused(
        self
    ):
        self._create_local_champion()

        db.session.commit()

        document = self._build_document(
            champions=[
                self._champion()
            ]
        )

        preview = (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        self.assertTrue(
            preview["can_import"]
        )

        self.assertEqual(
            preview["champions"][0][
                "status"
            ],
            "existing",
        )

        self.assertFalse(
            preview["champions"][0][
                "metadata_differs"
            ]
        )

        self.assertEqual(
            preview["summary"][
                "existing_champions"
            ],
            1,
        )

        self.assertEqual(
            preview["summary"][
                "new_champions"
            ],
            0,
        )

    def test_changed_existing_champion_metadata_creates_warning(
        self
    ):
        self._create_local_champion(
            name=None,
            image=None,
            source="riot_api",
        )

        db.session.commit()

        document = self._build_document(
            champions=[
                self._champion()
            ]
        )

        preview = (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        self.assertTrue(
            preview["can_import"]
        )

        self.assertTrue(
            preview["champions"][0][
                "metadata_differs"
            ]
        )

        self.assertEqual(
            preview["summary"][
                "champion_metadata_warnings"
            ],
            1,
        )

        self.assertEqual(
            preview["warnings"][0][
                "code"
            ],
            "champion_metadata_differs",
        )

    def test_duplicate_display_name_is_warning_not_blocker(
        self
    ):
        self._create_local_person(
            display_name="Same Name"
        )

        db.session.commit()

        document = self._build_document(
            persons=[
                self._person(
                    display_name="Same Name"
                )
            ]
        )

        preview = (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        self.assertTrue(
            preview["can_import"]
        )

        self.assertEqual(
            preview["summary"][
                "blocker_count"
            ],
            0,
        )

        self.assertEqual(
            preview["summary"][
                "duplicate_display_name_warnings"
            ],
            1,
        )

        self.assertEqual(
            preview["warnings"][0][
                "code"
            ],
            "duplicate_display_name",
        )

        self.assertEqual(
            preview["persons"][0][
                "local_display_name_match_count"
            ],
            1,
        )

    def test_preview_does_not_modify_database(
        self
    ):
        local_person = (
            self._create_local_person()
        )

        local_account = (
            self._create_local_account(
                person=local_person
            )
        )

        local_champion = (
            self._create_local_champion()
        )

        db.session.add(
            ChampionMastery(
                riot_account_id=(
                    local_account.id
                ),
                champion_id=(
                    local_champion.id
                ),
                mastery_points=999,
            )
        )

        db.session.commit()

        counts_before = {
            "persons": (
                db.session.query(
                    Person
                ).count()
            ),
            "accounts": (
                db.session.query(
                    RiotAccount
                ).count()
            ),
            "champions": (
                db.session.query(
                    Champion
                ).count()
            ),
            "mastery": (
                db.session.query(
                    ChampionMastery
                ).count()
            ),
        }

        document = self._build_document(
            champions=[
                self._champion(
                    riot_champion_id=99,
                    name="Lux",
                    image="Lux.png",
                )
            ],
            persons=[
                self._person(
                    riot_accounts=[
                        self._account(
                            puuid="new-import-puuid",
                            champion_mastery=[
                                {
                                    "riot_champion_id": 99,
                                    "mastery_points": 321,
                                }
                            ],
                        )
                    ]
                )
            ],
        )

        (
            JsonImportPreviewService
            .build_preview(
                self._build_read_result(
                    document
                )
            )
        )

        counts_after = {
            "persons": (
                db.session.query(
                    Person
                ).count()
            ),
            "accounts": (
                db.session.query(
                    RiotAccount
                ).count()
            ),
            "champions": (
                db.session.query(
                    Champion
                ).count()
            ),
            "mastery": (
                db.session.query(
                    ChampionMastery
                ).count()
            ),
        }

        self.assertEqual(
            counts_after,
            counts_before,
        )

        self.assertFalse(
            db.session.new
        )

        self.assertFalse(
            db.session.dirty
        )

        self.assertFalse(
            db.session.deleted
        )

    def test_revalidates_document_before_database_read(
        self
    ):
        document = self._build_document()

        read_result = (
            self._build_read_result(
                document
            )
        )

        read_result["document"][
            "format"
        ] = "invalid-format"

        with self.assertRaises(
            JsonImportPreviewError
        ) as raised_context:
            (
                JsonImportPreviewService
                .build_preview(
                    read_result
                )
            )

        self.assertIsInstance(
            raised_context.exception.__cause__,
            JsonExportValidationError,
        )

    def test_wraps_database_read_error(
        self
    ):
        document = self._build_document()

        read_result = (
            self._build_read_result(
                document
            )
        )

        with patch.object(
            db.session,
            "execute",
            side_effect=SQLAlchemyError(
                "database failure"
            ),
        ):
            with self.assertRaisesRegex(
                JsonImportPreviewError,
                "could not be read",
            ):
                (
                    JsonImportPreviewService
                    .build_preview(
                        read_result
                    )
                )


if __name__ == "__main__":
    unittest.main()