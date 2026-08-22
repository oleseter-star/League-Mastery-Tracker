import json
import unittest
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
from application.services.json_import_execution_service import (
    JsonImportExecutionError,
    JsonImportExecutionService,
)
from application.services.json_import_staging_service import (
    JsonImportStagingError,
    JsonImportStagingService,
)
from application.services.json_import_workflow_service import (
    JsonImportWorkflowError,
    JsonImportWorkflowService,
)


class JsonImportWorkflowServiceTests(
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
            / "workflow-test.db"
        )

        self.backup_directory = (
            temporary_path
            / "backups"
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
            SQLALCHEMY_DATABASE_URI=(
                "sqlite:///"
                + self.database_file.as_posix()
            ),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DATABASE_FILE=self.database_file,
            BACKUP_DIR=self.backup_directory,
            CONFIG_DIR=self.configuration_directory,
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

    def _serialize_document(
        self,
        document,
    ):
        return json.dumps(
            document,
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

    def _stream(
        self,
        document,
    ):
        return BytesIO(
            self._serialize_document(
                document
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
        puuid="workflow-puuid",
        game_name="WorkflowPlayer",
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
        display_name="Workflow Person",
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

    def _backup_files(
        self
    ):
        if not self.backup_directory.exists():
            return []

        return list(
            self.backup_directory.glob(
                "*.db"
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

    def _staged_files(
        self
    ):
        staging_directory = (
            self._staging_directory()
        )

        if not staging_directory.exists():
            return []

        return list(
            staging_directory.glob(
                "staged_import_*.json"
            )
        )

    def _stage_document(
        self,
        document,
        file_name="staged-workflow.json",
    ):
        return (
            JsonImportWorkflowService
            .stage_stream(
                stream=self._stream(
                    document
                ),
                file_name=file_name,
            )
        )

    def test_inspection_builds_preview_and_plan_without_writes(
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

        result = (
            JsonImportWorkflowService
            .inspect_stream(
                stream=self._stream(
                    document
                ),
                file_name="workflow.json",
            )
        )

        self.assertTrue(
            result["preview"][
                "can_import"
            ]
        )

        self.assertIsNotNone(
            result["plan"]
        )

        self.assertEqual(
            result["source"][
                "record_counts"
            ],
            {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 1,
                "mastery_records": 1,
            },
        )

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
            self._backup_files(),
            [],
        )

        self.assertFalse(
            self._marker_file().exists()
        )

    def test_blocking_inspection_returns_preview_without_plan(
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

        result = (
            JsonImportWorkflowService
            .inspect_stream(
                stream=self._stream(
                    document
                ),
                file_name="blocked.json",
            )
        )

        self.assertFalse(
            result["preview"][
                "can_import"
            ]
        )

        self.assertEqual(
            result["preview"][
                "summary"
            ][
                "blocker_count"
            ],
            1,
        )

        self.assertIsNone(
            result["plan"]
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_execution_requires_exact_confirmation(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        for invalid_confirmation in (
            None,
            "",
            "import",
            " IMPORT",
            "IMPORT ",
        ):
            with self.subTest(
                confirmation=(
                    invalid_confirmation
                )
            ):
                with self.assertRaises(
                    JsonImportWorkflowError
                ) as raised_context:
                    (
                        JsonImportWorkflowService
                        .execute_stream(
                            stream=self._stream(
                                document
                            ),
                            file_name="confirmation.json",
                            confirmation_text=(
                                invalid_confirmation
                            ),
                        )
                    )

                self.assertEqual(
                    raised_context.exception.stage,
                    "confirmation",
                )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_execution_runs_complete_safe_import(
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
                                    "mastery_points": 900,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        result = (
            JsonImportWorkflowService
            .execute_stream(
                stream=self._stream(
                    document
                ),
                file_name="execute.json",
                confirmation_text="IMPORT",
            )
        )

        self.assertTrue(
            result["execution"][
                "applied"
            ]
        )

        self.assertEqual(
            result["execution"][
                "created"
            ],
            {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 1,
                "mastery_records": 1,
            },
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            1,
        )

        self.assertEqual(
            db.session.query(
                RiotAccount
            ).count(),
            1,
        )

        self.assertEqual(
            db.session.query(
                Champion
            ).count(),
            1,
        )

        self.assertEqual(
            db.session.query(
                ChampionMastery
            ).count(),
            1,
        )

        self.assertEqual(
            len(
                self._backup_files()
            ),
            1,
        )

    def test_blocked_execution_stops_before_backup(
        self
    ):
        local_person = (
            self._create_local_person()
        )

        self._create_local_account(
            person=local_person,
            puuid="blocked-puuid",
        )

        db.session.commit()

        document = self._build_document(
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            puuid="blocked-puuid"
                        )
                    ]
                )
            ]
        )

        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .execute_stream(
                    stream=self._stream(
                        document
                    ),
                    file_name="blocked-execution.json",
                    confirmation_text="IMPORT",
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "preview",
        )

        self.assertIsNotNone(
            raised_context.exception.preview
        )

        self.assertFalse(
            raised_context.exception.preview[
                "can_import"
            ]
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            1,
        )

    def test_read_error_is_wrapped_with_stage(
        self
    ):
        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .inspect_stream(
                    stream=BytesIO(
                        b"not valid json"
                    ),
                    file_name="invalid.json",
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "read",
        )

        self.assertIsNotNone(
            raised_context.exception.__cause__
        )

    def test_execution_error_is_wrapped_with_stage(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        with patch.object(
            JsonImportExecutionService,
            "apply_plan",
            side_effect=JsonImportExecutionError(
                "forced execution error"
            ),
        ):
            with self.assertRaises(
                JsonImportWorkflowError
            ) as raised_context:
                (
                    JsonImportWorkflowService
                    .execute_stream(
                        stream=self._stream(
                            document
                        ),
                        file_name="execution-error.json",
                        confirmation_text="IMPORT",
                    )
                )

        self.assertEqual(
            raised_context.exception.stage,
            "execution",
        )

        self.assertIsNotNone(
            raised_context.exception.preview
        )

        self.assertIsInstance(
            raised_context.exception.__cause__,
            JsonImportExecutionError,
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

    def test_empty_import_is_no_op_without_backup(
        self
    ):
        document = self._build_document()

        result = (
            JsonImportWorkflowService
            .execute_stream(
                stream=self._stream(
                    document
                ),
                file_name="empty-import.json",
                confirmation_text="IMPORT",
            )
        )

        self.assertFalse(
            result["execution"][
                "applied"
            ]
        )

        self.assertEqual(
            result["execution"][
                "reason"
            ],
            "no_database_changes",
        )

        self.assertIsNone(
            result["execution"][
                "backup_file"
            ]
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_stage_stream_builds_preview_and_plan_from_persisted_file(
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

        result = self._stage_document(
            document
        )

        self.assertTrue(
            result["preview"][
                "can_import"
            ]
        )

        self.assertIsNotNone(
            result["plan"]
        )

        self.assertEqual(
            result["source"][
                "sha256"
            ],
            result["staging"][
                "sha256"
            ],
        )

        self.assertTrue(
            result["staging"][
                "staging_token"
            ]
        )

        self.assertTrue(
            self._marker_file().is_file()
        )

        self.assertEqual(
            len(
                self._staged_files()
            ),
            1,
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_inspect_staged_reloads_same_source_and_plan(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document,
            file_name="reload-source.json",
        )

        inspected = (
            JsonImportWorkflowService
            .inspect_staged(
                staged[
                    "staging"
                ][
                    "staging_token"
                ]
            )
        )

        self.assertEqual(
            inspected["source"],
            staged["source"],
        )

        self.assertEqual(
            inspected[
                "staging"
            ][
                "staging_token"
            ],
            staged[
                "staging"
            ][
                "staging_token"
            ],
        )

        self.assertEqual(
            inspected[
                "plan"
            ][
                "plan_sha256"
            ],
            staged[
                "plan"
            ][
                "plan_sha256"
            ],
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_execute_staged_imports_and_removes_staging_files(
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
                                    "mastery_points": 700,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        staged = self._stage_document(
            document
        )

        result = (
            JsonImportWorkflowService
            .execute_staged(
                staging_token=(
                    staged[
                        "staging"
                    ][
                        "staging_token"
                    ]
                ),
                confirmation_text="IMPORT",
            )
        )

        self.assertTrue(
            result["execution"][
                "applied"
            ]
        )

        self.assertTrue(
            result[
                "staging_cleanup"
            ][
                "cleared"
            ]
        )

        self.assertIsNone(
            result[
                "staging_cleanup"
            ][
                "error"
            ]
        )

        self.assertEqual(
            result["execution"][
                "created"
            ],
            {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 1,
                "mastery_records": 1,
            },
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            1,
        )

        self.assertEqual(
            db.session.query(
                RiotAccount
            ).count(),
            1,
        )

        self.assertEqual(
            db.session.query(
                Champion
            ).count(),
            1,
        )

        self.assertEqual(
            db.session.query(
                ChampionMastery
            ).count(),
            1,
        )

        self.assertEqual(
            len(
                self._backup_files()
            ),
            1,
        )

        self.assertFalse(
            self._marker_file().exists()
        )

        self.assertEqual(
            self._staged_files(),
            [],
        )

    def test_wrong_confirmation_preserves_staged_import(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document
        )

        staging_token = staged[
            "staging"
        ][
            "staging_token"
        ]

        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .execute_staged(
                    staging_token=(
                        staging_token
                    ),
                    confirmation_text="import",
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "confirmation",
        )

        inspected = (
            JsonImportWorkflowService
            .inspect_staged(
                staging_token
            )
        )

        self.assertEqual(
            inspected[
                "staging"
            ][
                "staging_token"
            ],
            staging_token,
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_blocked_staged_execution_preserves_source(
        self
    ):
        local_person = (
            self._create_local_person()
        )

        self._create_local_account(
            person=local_person,
            puuid="staged-conflict-puuid",
        )

        db.session.commit()

        document = self._build_document(
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            puuid=(
                                "staged-conflict-puuid"
                            )
                        )
                    ]
                )
            ]
        )

        staged = self._stage_document(
            document
        )

        staging_token = staged[
            "staging"
        ][
            "staging_token"
        ]

        self.assertFalse(
            staged["preview"][
                "can_import"
            ]
        )

        self.assertIsNone(
            staged["plan"]
        )

        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .execute_staged(
                    staging_token=(
                        staging_token
                    ),
                    confirmation_text="IMPORT",
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "preview",
        )

        self.assertIsNotNone(
            raised_context.exception.staging
        )

        inspected = (
            JsonImportWorkflowService
            .inspect_staged(
                staging_token
            )
        )

        self.assertFalse(
            inspected["preview"][
                "can_import"
            ]
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

        self.assertTrue(
            self._marker_file().is_file()
        )

    def test_cancel_staged_removes_source_without_database_change(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document
        )

        staging_token = staged[
            "staging"
        ][
            "staging_token"
        ]

        result = (
            JsonImportWorkflowService
            .cancel_staged(
                staging_token
            )
        )

        self.assertTrue(
            result["cancelled"]
        )

        self.assertFalse(
            self._marker_file().exists()
        )

        self.assertEqual(
            self._staged_files(),
            [],
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .inspect_staged(
                    staging_token
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "staging",
        )

    def test_tampered_staged_file_is_wrapped_as_staging_error(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document
        )

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

        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .inspect_staged(
                    staged[
                        "staging"
                    ][
                        "staging_token"
                    ]
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "staging",
        )

        self.assertIsInstance(
            raised_context.exception.__cause__,
            JsonImportStagingError,
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

    def test_consumption_failure_stops_before_database_execution(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document
        )

        staging_token = staged[
            "staging"
        ][
            "staging_token"
        ]

        with patch.object(
            JsonImportStagingService,
            "cancel_staged",
            side_effect=JsonImportStagingError(
                "forced consumption failure"
            ),
        ):
            with self.assertRaises(
                JsonImportWorkflowError
            ) as raised_context:
                (
                    JsonImportWorkflowService
                    .execute_staged(
                        staging_token=(
                            staging_token
                        ),
                        confirmation_text="IMPORT",
                    )
                )

        self.assertEqual(
            raised_context.exception.stage,
            "staging",
        )

        self.assertIsNotNone(
            raised_context.exception.staging
        )

        self.assertIsInstance(
            raised_context.exception.__cause__,
            JsonImportStagingError,
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

        self.assertTrue(
            self._marker_file().is_file()
        )

    def test_successful_staged_import_cannot_execute_twice(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document
        )

        staging_token = staged[
            "staging"
        ][
            "staging_token"
        ]

        first_result = (
            JsonImportWorkflowService
            .execute_staged(
                staging_token=(
                    staging_token
                ),
                confirmation_text="IMPORT",
            )
        )

        self.assertTrue(
            first_result[
                "staging_cleanup"
            ][
                "consumed"
            ]
        )

        with self.assertRaises(
            JsonImportWorkflowError
        ) as raised_context:
            (
                JsonImportWorkflowService
                .execute_staged(
                    staging_token=(
                        staging_token
                    ),
                    confirmation_text="IMPORT",
                )
            )

        self.assertEqual(
            raised_context.exception.stage,
            "staging",
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            1,
        )

        self.assertEqual(
            len(
                self._backup_files()
            ),
            1,
        )

        self.assertFalse(
            self._marker_file().exists()
        )

        self.assertEqual(
            self._staged_files(),
            [],
        )

    def test_execution_failure_still_consumes_staged_source(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        staged = self._stage_document(
            document
        )

        staging_token = staged[
            "staging"
        ][
            "staging_token"
        ]

        with patch.object(
            JsonImportExecutionService,
            "apply_plan",
            side_effect=JsonImportExecutionError(
                "forced staged execution error"
            ),
        ):
            with self.assertRaises(
                JsonImportWorkflowError
            ) as raised_context:
                (
                    JsonImportWorkflowService
                    .execute_staged(
                        staging_token=(
                            staging_token
                        ),
                        confirmation_text="IMPORT",
                    )
                )

        self.assertEqual(
            raised_context.exception.stage,
            "execution",
        )

        self.assertIsNotNone(
            raised_context.exception.staging
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            0,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

        self.assertFalse(
            self._marker_file().exists()
        )

        self.assertEqual(
            self._staged_files(),
            [],
        )

        with self.assertRaises(
            JsonImportWorkflowError
        ) as replay_context:
            (
                JsonImportWorkflowService
                .inspect_staged(
                    staging_token
                )
            )

        self.assertEqual(
            replay_context.exception.stage,
            "staging",
        )


if __name__ == "__main__":
    unittest.main()