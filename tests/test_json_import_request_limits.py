import json
import re
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import application.app as app_module
from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.routes.json_import import (
    SESSION_STAGING_TOKEN_KEY,
)


class JsonImportRequestLimitTests(
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
            / "request-limit.db"
        )

        self.backup_directory = (
            temporary_path
            / "backups"
        )

        self.configuration_directory = (
            temporary_path
            / "configuration"
        )

        database_file = self.database_file
        backup_directory = self.backup_directory
        configuration_directory = (
            self.configuration_directory
        )

        class JsonImportRequestLimitConfig:
            TESTING = True

            SQLALCHEMY_DATABASE_URI = (
                "sqlite:///"
                + database_file.as_posix()
            )

            SQLALCHEMY_TRACK_MODIFICATIONS = False

            DATABASE_FILE = database_file
            BACKUP_DIR = backup_directory
            CONFIG_DIR = configuration_directory

            @staticmethod
            def ensure_directories():
                database_file.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                backup_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                configuration_directory.mkdir(
                    parents=True,
                    exist_ok=True,
                )

        self.config_name = (
            "json_import_request_limit_test"
        )

        with patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    JsonImportRequestLimitConfig
                )
            },
            clear=False,
        ):
            with patch.object(
                app_module.LocalSecretKeyService,
                "get_or_create_secret_key",
                return_value=(
                    b"json-import-request-limit-secret-"
                    b"012345678901234567890123456789"
                ),
            ):
                with patch.object(
                    app_module.DatabaseRestoreService,
                    "apply_pending_restore",
                    return_value=None,
                ):
                    self.app = (
                        app_module.create_app(
                            self.config_name
                        )
                    )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        self.client = (
            self.app.test_client()
        )

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
                            "Request Limit Person"
                        ),
                        "riot_accounts": [
                            {
                                "game_name": (
                                    "RequestLimitPlayer"
                                ),
                                "tag_line": "EUW",
                                "puuid": (
                                    "request-limit-puuid"
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
                                        "mastery_points": 875,
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
    ):
        return json.dumps(
            self._build_document(),
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

    def _get_csrf_token(
        self,
        response=None,
    ):
        if response is None:
            response = self.client.get(
                "/settings/data-import"
            )

        response_text = response.get_data(
            as_text=True
        )

        token_match = re.search(
            (
                r'name="_csrf_token"'
                r'\s+value="([^"]+)"'
            ),
            response_text,
        )

        self.assertIsNotNone(
            token_match,
            "The JSON import page did not contain a CSRF token.",
        )

        return token_match.group(
            1
        )

    def _marker_file(
        self,
    ):
        return (
            self.configuration_directory
            / "json_import"
            / "pending_import.json"
        )

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

    def _get_session_staging_token(
        self,
    ):
        with self.client.session_transaction() as session_data:
            return session_data.get(
                SESSION_STAGING_TOKEN_KEY
            )

    def test_oversized_upload_returns_friendly_import_page(
        self
    ):
        self.app.config[
            "JSON_IMPORT_MAX_FILE_SIZE_BYTES"
        ] = 1024

        self.app.config[
            "MAX_CONTENT_LENGTH"
        ] = 2048

        csrf_token = self._get_csrf_token()

        response = self.client.post(
            "/settings/data-import/stage",
            data={
                "_csrf_token": csrf_token,
                "import_file": (
                    BytesIO(
                        b"x" * 4096
                    ),
                    "oversized.json",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "The selected import file is too large.",
            response_text,
        )

        self.assertIn(
            "Select export file",
            response_text,
        )

        self.assertIsNone(
            self._get_session_staging_token()
        )

        self.assertFalse(
            self._marker_file().exists()
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

    def test_oversized_upload_redirect_disables_caching(
        self
    ):
        self.app.config[
            "JSON_IMPORT_MAX_FILE_SIZE_BYTES"
        ] = 1024

        self.app.config[
            "MAX_CONTENT_LENGTH"
        ] = 2048

        csrf_token = self._get_csrf_token()

        response = self.client.post(
            "/settings/data-import/stage",
            data={
                "_csrf_token": csrf_token,
                "import_file": (
                    BytesIO(
                        b"x" * 4096
                    ),
                    "oversized.json",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            response.headers[
                "Location"
            ],
            "/settings/data-import",
        )

        self.assertIn(
            "no-store",
            response.headers[
                "Cache-Control"
            ],
        )

        self.assertEqual(
            response.headers[
                "X-Content-Type-Options"
            ],
            "nosniff",
        )

        self.assertFalse(
            self._marker_file().exists()
        )

    def test_complete_app_stages_real_multipart_upload(
        self
    ):
        csrf_token = self._get_csrf_token()

        response = self.client.post(
            "/settings/data-import/stage",
            data={
                "_csrf_token": csrf_token,
                "import_file": (
                    BytesIO(
                        self._serialize_document()
                    ),
                    "complete-app-export.json",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "Ready to import",
            response_text,
        )

        self.assertIn(
            "complete-app-export.json",
            response_text,
        )

        self.assertIn(
            "Request Limit Person",
            response_text,
        )

        self.assertIsNotNone(
            self._get_session_staging_token()
        )

        self.assertTrue(
            self._marker_file().is_file()
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

    def test_complete_app_executes_staged_upload_end_to_end(
        self
    ):
        upload_csrf_token = (
            self._get_csrf_token()
        )

        stage_response = self.client.post(
            "/settings/data-import/stage",
            data={
                "_csrf_token": (
                    upload_csrf_token
                ),
                "import_file": (
                    BytesIO(
                        self._serialize_document()
                    ),
                    "complete-app-export.json",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        execution_csrf_token = (
            self._get_csrf_token(
                stage_response
            )
        )

        execution_response = (
            self.client.post(
                "/settings/data-import/execute",
                data={
                    "_csrf_token": (
                        execution_csrf_token
                    ),
                    "confirmation_text": "IMPORT",
                },
                follow_redirects=True,
            )
        )

        response_text = (
            execution_response.get_data(
                as_text=True
            )
        )

        self.assertEqual(
            execution_response.status_code,
            200,
        )

        self.assertIn(
            "The JSON import was completed.",
            response_text,
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

        mastery_record = (
            db.session.query(
                ChampionMastery
            )
            .one()
        )

        self.assertEqual(
            mastery_record.mastery_points,
            875,
        )

        self.assertEqual(
            len(
                self._backup_files()
            ),
            1,
        )

        self.assertIsNone(
            self._get_session_staging_token()
        )

        self.assertFalse(
            self._marker_file().exists()
        )


if __name__ == "__main__":
    unittest.main()