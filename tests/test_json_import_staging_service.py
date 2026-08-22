import json
import unittest
from datetime import datetime, timedelta, timezone
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
from application.services.json_import_staging_service import (
    JsonImportStagingError,
    JsonImportStagingService,
)


class JsonImportStagingServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        temporary_path = Path(
            self.temporary_directory.name
        )

        self.configuration_directory = (
            temporary_path
            / "configuration"
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            CONFIG_DIR=(
                self.configuration_directory
            ),
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
        db.session.rollback()
        db.session.remove()

        db.drop_all()

        self.app_context.pop()

        self.temporary_directory.cleanup()

    def _build_document(
        self,
    ):
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
                "persons": 1,
                "riot_accounts": 1,
                "champions": 1,
                "mastery_records": 1,
            },
            "data": {
                "champions": [
                    {
                        "riot_champion_id": 22,
                        "name": "Ashe",
                        "image": "Ashe.png",
                        "source": "data_dragon",
                    }
                ],
                "persons": [
                    {
                        "display_name": (
                            "Staged Person"
                        ),
                        "riot_accounts": [
                            {
                                "game_name": (
                                    "StagedPlayer"
                                ),
                                "tag_line": "EUW",
                                "puuid": (
                                    "staged-puuid"
                                ),
                                "platform_region": (
                                    "euw1"
                                ),
                                "last_sync": (
                                    "2026-07-16T11:00:00Z"
                                ),
                                "champion_mastery": [
                                    {
                                        "riot_champion_id": 22,
                                        "mastery_points": 500,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }

    def _serialize_document(
        self,
        document=None,
    ):
        return json.dumps(
            document
            or self._build_document(),
            ensure_ascii=False,
            indent=2,
        ).encode(
            "utf-8"
        )

    def _stage(
        self,
        file_name="portable-export.json",
        expiration_minutes=60,
    ):
        return (
            JsonImportStagingService
            .stage_stream(
                stream=BytesIO(
                    self._serialize_document()
                ),
                file_name=file_name,
                expiration_minutes=(
                    expiration_minutes
                ),
            )
        )

    def _staging_directory(
        self
    ):
        return (
            self.configuration_directory
            / "json_import"
        )

    def _marker_file(
        self
    ):
        return (
            self._staging_directory()
            / "pending_import.json"
        )

    def _read_marker(
        self
    ):
        return json.loads(
            self._marker_file().read_text(
                encoding="utf-8"
            )
        )

    def _write_marker(
        self,
        marker,
    ):
        self._marker_file().write_text(
            json.dumps(
                marker,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_stages_and_loads_exact_valid_file(
        self
    ):
        raw_bytes = (
            self._serialize_document()
        )

        stage_result = (
            JsonImportStagingService
            .stage_stream(
                stream=BytesIO(
                    raw_bytes
                ),
                file_name=(
                    r"C:\fakepath\portable-export.json"
                ),
            )
        )

        loaded = (
            JsonImportStagingService
            .load_staged(
                stage_result[
                    "staging_token"
                ]
            )
        )

        self.assertEqual(
            stage_result[
                "original_file_name"
            ],
            "portable-export.json",
        )

        self.assertEqual(
            loaded[
                "read_result"
            ][
                "document"
            ],
            self._build_document(),
        )

        marker = self._read_marker()

        staged_file = (
            self._staging_directory()
            / marker[
                "staged_file_name"
            ]
        )

        self.assertEqual(
            staged_file.read_bytes(),
            raw_bytes,
        )

        self.assertEqual(
            loaded[
                "read_result"
            ][
                "sha256"
            ],
            stage_result[
                "sha256"
            ],
        )

    def test_staging_uses_private_configuration_directory(
        self
    ):
        self._stage()

        self.assertTrue(
            self._marker_file().is_file()
        )

        staged_files = list(
            self._staging_directory().glob(
                "staged_import_*.json"
            )
        )

        self.assertEqual(
            len(
                staged_files
            ),
            1,
        )

        self.assertEqual(
            staged_files[0].parent,
            self._staging_directory(),
        )

    def test_new_stage_replaces_previous_stage(
        self
    ):
        first_stage = self._stage(
            file_name="first.json"
        )

        first_marker = (
            self._read_marker()
        )

        first_staged_file = (
            self._staging_directory()
            / first_marker[
                "staged_file_name"
            ]
        )

        second_stage = self._stage(
            file_name="second.json"
        )

        self.assertNotEqual(
            first_stage[
                "staging_token"
            ],
            second_stage[
                "staging_token"
            ],
        )

        self.assertFalse(
            first_staged_file.exists()
        )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "no longer active",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    first_stage[
                        "staging_token"
                    ]
                )
            )

        loaded = (
            JsonImportStagingService
            .load_staged(
                second_stage[
                    "staging_token"
                ]
            )
        )

        self.assertEqual(
            loaded[
                "staging"
            ][
                "original_file_name"
            ],
            "second.json",
        )

    def test_rejects_tampered_staged_file(
        self
    ):
        stage_result = self._stage()

        marker = self._read_marker()

        staged_file = (
            self._staging_directory()
            / marker[
                "staged_file_name"
            ]
        )

        staged_file.write_bytes(
            staged_file.read_bytes()
            + b" "
        )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "size has changed",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    stage_result[
                        "staging_token"
                    ]
                )
            )

    def test_rejects_tampered_marker_metadata(
        self
    ):
        stage_result = self._stage()

        marker = self._read_marker()

        marker[
            "record_counts"
        ][
            "persons"
        ] = 999

        self._write_marker(
            marker
        )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "marker metadata",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    stage_result[
                        "staging_token"
                    ]
                )
            )

    def test_rejects_path_traversal_in_marker(
        self
    ):
        stage_result = self._stage()

        marker = self._read_marker()

        marker[
            "staged_file_name"
        ] = "../outside.json"

        self._write_marker(
            marker
        )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "invalid staged file name",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    stage_result[
                        "staging_token"
                    ]
                )
            )

    def test_wrong_token_cannot_load_or_cancel_newer_stage(
        self
    ):
        stage_result = self._stage()

        wrong_token = "0" * (
            JsonImportStagingService
            .TOKEN_HEX_LENGTH
        )

        if (
            wrong_token
            == stage_result[
                "staging_token"
            ]
        ):
            wrong_token = "1" * (
                JsonImportStagingService
                .TOKEN_HEX_LENGTH
            )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "no longer active",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    wrong_token
                )
            )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "no longer active",
        ):
            (
                JsonImportStagingService
                .cancel_staged(
                    wrong_token
                )
            )

        loaded = (
            JsonImportStagingService
            .load_staged(
                stage_result[
                    "staging_token"
                ]
            )
        )

        self.assertEqual(
            loaded[
                "staging"
            ][
                "staging_token"
            ],
            stage_result[
                "staging_token"
            ],
        )

    def test_expired_stage_is_rejected(
        self
    ):
        created_at = datetime(
            2026,
            7,
            16,
            12,
            0,
            0,
            tzinfo=timezone.utc,
        )

        with patch.object(
            JsonImportStagingService,
            "_utc_now",
            return_value=created_at,
        ):
            stage_result = self._stage(
                expiration_minutes=1
            )

        with patch.object(
            JsonImportStagingService,
            "_utc_now",
            return_value=(
                created_at
                + timedelta(
                    minutes=2
                )
            ),
        ):
            with self.assertRaisesRegex(
                JsonImportStagingError,
                "expired",
            ):
                (
                    JsonImportStagingService
                    .load_staged(
                        stage_result[
                            "staging_token"
                        ]
                    )
                )

    def test_cancel_removes_marker_and_staged_file(
        self
    ):
        stage_result = self._stage()

        marker = self._read_marker()

        staged_file = (
            self._staging_directory()
            / marker[
                "staged_file_name"
            ]
        )

        cancel_result = (
            JsonImportStagingService
            .cancel_staged(
                stage_result[
                    "staging_token"
                ]
            )
        )

        self.assertTrue(
            cancel_result[
                "cancelled"
            ]
        )

        self.assertFalse(
            self._marker_file().exists()
        )

        self.assertFalse(
            staged_file.exists()
        )

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "no active staged",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    stage_result[
                        "staging_token"
                    ]
                )
            )

    def test_invalid_json_creates_no_staging_files(
        self
    ):
        with self.assertRaises(
            JsonImportStagingError
        ):
            (
                JsonImportStagingService
                .stage_stream(
                    stream=BytesIO(
                        b"not valid json"
                    ),
                    file_name="invalid.json",
                )
            )

        staging_directory = (
            self._staging_directory()
        )

        if staging_directory.exists():
            self.assertEqual(
                list(
                    staging_directory.iterdir()
                ),
                [],
            )

    def test_missing_staged_file_is_rejected(
        self
    ):
        stage_result = self._stage()

        marker = self._read_marker()

        staged_file = (
            self._staging_directory()
            / marker[
                "staged_file_name"
            ]
        )

        staged_file.unlink()

        with self.assertRaisesRegex(
            JsonImportStagingError,
            "missing or invalid",
        ):
            (
                JsonImportStagingService
                .load_staged(
                    stage_result[
                        "staging_token"
                    ]
                )
            )

    def test_staging_and_loading_do_not_modify_database(
        self
    ):
        person = Person(
            display_name="Existing Person"
        )

        db.session.add(
            person
        )

        db.session.flush()

        account = RiotAccount(
            person_id=person.id,
            game_name="ExistingPlayer",
            tag_line="LOCAL",
            puuid="existing-local-puuid",
            platform_region="euw1",
        )

        champion = Champion(
            riot_champion_id=99,
            name="Lux",
            image="Lux.png",
            source="data_dragon",
        )

        db.session.add_all(
            [
                account,
                champion,
            ]
        )

        db.session.flush()

        db.session.add(
            ChampionMastery(
                riot_account_id=account.id,
                champion_id=champion.id,
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

        stage_result = self._stage()

        (
            JsonImportStagingService
            .load_staged(
                stage_result[
                    "staging_token"
                ]
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