import copy
import json
import unittest
from io import BytesIO

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.json_import_plan_service import (
    JsonImportPlanError,
    JsonImportPlanService,
)
from application.services.json_import_preview_service import (
    JsonImportPreviewService,
)
from application.services.json_import_read_service import (
    JsonImportReadService,
)


class JsonImportPlanServiceTests(
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
                file_name="import-plan.json",
            )
        )

    def _build_preview(
        self,
        read_result,
    ):
        return (
            JsonImportPreviewService
            .build_preview(
                read_result
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
        mastery=None,
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

    def test_builds_deeply_immutable_plan(
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
                                    "mastery_points": 123,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        read_result = (
            self._build_read_result(
                document
            )
        )

        preview = self._build_preview(
            read_result
        )

        plan = (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=preview,
            )
        )

        self.assertTrue(
            JsonImportPlanService
            .verify_plan(
                plan
            )
        )

        with self.assertRaises(
            TypeError
        ):
            plan[
                "plan_version"
            ] = 999

        with self.assertRaises(
            TypeError
        ):
            plan[
                "summary"
            ][
                "persons_to_create"
            ] = 999

        with self.assertRaises(
            TypeError
        ):
            plan[
                "persons"
            ][0][
                "display_name"
            ] = "Changed"

        self.assertIsInstance(
            plan["persons"],
            tuple,
        )

        self.assertIsInstance(
            plan["champions"],
            tuple,
        )

    def test_plan_contains_expected_create_actions(
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
                                    "mastery_points": 500,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        read_result = (
            self._build_read_result(
                document
            )
        )

        plan = (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=(
                    self._build_preview(
                        read_result
                    )
                ),
            )
        )

        plain_plan = (
            JsonImportPlanService
            .to_plain_dict(
                plan
            )
        )

        self.assertEqual(
            plain_plan[
                "champions"
            ][0]["action"],
            "create",
        )

        self.assertEqual(
            plain_plan[
                "persons"
            ][0]["action"],
            "create",
        )

        self.assertEqual(
            plain_plan[
                "persons"
            ][0][
                "riot_accounts"
            ][0]["action"],
            "create",
        )

        self.assertEqual(
            plain_plan[
                "persons"
            ][0][
                "riot_accounts"
            ][0][
                "champion_mastery"
            ][0]["action"],
            "create",
        )

        self.assertEqual(
            plain_plan[
                "summary"
            ][
                "mastery_records_to_create"
            ],
            1,
        )

    def test_existing_champion_uses_reuse_action(
        self
    ):
        self._create_local_champion()

        db.session.commit()

        document = self._build_document(
            champions=[
                self._champion()
            ]
        )

        read_result = (
            self._build_read_result(
                document
            )
        )

        plan = (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=(
                    self._build_preview(
                        read_result
                    )
                ),
            )
        )

        plain_plan = (
            JsonImportPlanService
            .to_plain_dict(
                plan
            )
        )

        champion_action = (
            plain_plan[
                "champions"
            ][0]
        )

        self.assertEqual(
            champion_action[
                "action"
            ],
            "reuse",
        )

        self.assertEqual(
            champion_action[
                "expected_local_metadata"
            ],
            {
                "name": "Ashe",
                "image": "Ashe.png",
                "source": "data_dragon",
            },
        )

        self.assertEqual(
            plain_plan[
                "summary"
            ][
                "champions_to_reuse"
            ],
            1,
        )

    def test_duplicate_display_name_warning_is_preserved(
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

        read_result = (
            self._build_read_result(
                document
            )
        )

        plan = (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=(
                    self._build_preview(
                        read_result
                    )
                ),
            )
        )

        plain_plan = (
            JsonImportPlanService
            .to_plain_dict(
                plan
            )
        )

        self.assertEqual(
            plain_plan[
                "summary"
            ][
                "warning_count"
            ],
            1,
        )

        self.assertEqual(
            plain_plan[
                "warnings"
            ][0]["code"],
            "duplicate_display_name",
        )

        self.assertEqual(
            plain_plan[
                "persons"
            ][0][
                "local_display_name_match_count"
            ],
            1,
        )

        self.assertEqual(
            plain_plan[
                "persons"
            ][0]["action"],
            "create",
        )

    def test_refuses_preview_with_existing_puuid_blocker(
        self
    ):
        local_person = (
            self._create_local_person()
        )

        self._create_local_account(
            person=local_person,
            puuid="shared-puuid",
        )

        db.session.commit()

        document = self._build_document(
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            puuid="shared-puuid"
                        )
                    ]
                )
            ]
        )

        read_result = (
            self._build_read_result(
                document
            )
        )

        preview = self._build_preview(
            read_result
        )

        self.assertFalse(
            preview["can_import"]
        )

        with self.assertRaisesRegex(
            JsonImportPlanError,
            "blocking conflicts",
        ):
            (
                JsonImportPlanService
                .build_plan(
                    import_read_result=(
                        read_result
                    ),
                    import_preview=preview,
                )
            )

    def test_refuses_stale_preview_after_database_change(
        self
    ):
        document = self._build_document(
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            puuid="became-existing"
                        )
                    ]
                )
            ]
        )

        read_result = (
            self._build_read_result(
                document
            )
        )

        original_preview = (
            self._build_preview(
                read_result
            )
        )

        local_person = (
            self._create_local_person()
        )

        self._create_local_account(
            person=local_person,
            puuid="became-existing",
        )

        db.session.commit()

        with self.assertRaisesRegex(
            JsonImportPlanError,
            "stale",
        ):
            (
                JsonImportPlanService
                .build_plan(
                    import_read_result=(
                        read_result
                    ),
                    import_preview=(
                        original_preview
                    ),
                )
            )

    def test_refuses_tampered_preview(
        self
    ):
        document = self._build_document()

        read_result = (
            self._build_read_result(
                document
            )
        )

        preview = self._build_preview(
            read_result
        )

        tampered_preview = copy.deepcopy(
            preview
        )

        tampered_preview[
            "summary"
        ][
            "new_riot_accounts"
        ] = 999

        with self.assertRaisesRegex(
            JsonImportPlanError,
            "does not match",
        ):
            (
                JsonImportPlanService
                .build_plan(
                    import_read_result=(
                        read_result
                    ),
                    import_preview=(
                        tampered_preview
                    ),
                )
            )

    def test_plan_hash_detects_modified_plain_copy(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        read_result = (
            self._build_read_result(
                document
            )
        )

        plan = (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=(
                    self._build_preview(
                        read_result
                    )
                ),
            )
        )

        plain_plan = (
            JsonImportPlanService
            .to_plain_dict(
                plan
            )
        )

        plain_plan[
            "persons"
        ][0][
            "display_name"
        ] = "Modified Name"

        with self.assertRaisesRegex(
            JsonImportPlanError,
            "integrity check",
        ):
            (
                JsonImportPlanService
                .verify_plan(
                    plain_plan
                )
            )

        original_plain_plan = (
            JsonImportPlanService
            .to_plain_dict(
                plan
            )
        )

        self.assertNotEqual(
            plain_plan[
                "persons"
            ][0][
                "display_name"
            ],
            original_plain_plan[
                "persons"
            ][0][
                "display_name"
            ],
        )

    def test_plan_build_does_not_modify_database(
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
                mastery_points=1000,
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
                    accounts=[
                        self._account(
                            puuid="new-plan-puuid",
                            mastery=[
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

        read_result = (
            self._build_read_result(
                document
            )
        )

        (
            JsonImportPlanService
            .build_plan(
                import_read_result=(
                    read_result
                ),
                import_preview=(
                    self._build_preview(
                        read_result
                    )
                ),
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


if __name__ == "__main__":
    unittest.main()