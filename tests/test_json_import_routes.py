import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Blueprint, Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.routes.json_import import (
    SESSION_STAGING_TOKEN_KEY,
    json_import_bp,
)


class JsonImportRouteTests(
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
            / "route-test.db"
        )

        self.backup_directory = (
            temporary_path
            / "backups"
        )

        self.configuration_directory = (
            temporary_path
            / "configuration"
        )

        template_directory = (
            Path(__file__).resolve().parents[1]
            / "application"
            / "templates"
        )

        self.app = Flask(
            __name__,
            template_folder=str(
                template_directory
            ),
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY="route-test-secret",
            SQLALCHEMY_DATABASE_URI=(
                "sqlite:///"
                + self.database_file.as_posix()
            ),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            DATABASE_FILE=self.database_file,
            BACKUP_DIR=self.backup_directory,
            CONFIG_DIR=self.configuration_directory,
        )

        self.app.jinja_env.globals[
            "csrf_token"
        ] = lambda: "test-csrf-token"

        db.init_app(
            self.app
        )

        self._register_stub_blueprints()

        self.app.register_blueprint(
            json_import_bp
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

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

    def _register_stub_blueprints(
        self
    ):
        """
        Register the endpoint names referenced by json_import.html.

        The isolated route test app does not register the project's
        real home or settings blueprints.
        """

        home_blueprint = Blueprint(
            "home",
            __name__,
        )

        settings_blueprint = Blueprint(
            "settings",
            __name__,
        )

        @home_blueprint.route(
            "/",
            methods=["GET"],
        )
        def home():
            return "Test dashboard"

        @settings_blueprint.route(
            "/settings",
            methods=["GET"],
        )
        def get_settings():
            return "Test settings"

        self.app.register_blueprint(
            home_blueprint
        )

        self.app.register_blueprint(
            settings_blueprint
        )

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
    ):
        return {
            "riot_champion_id": (
                riot_champion_id
            ),
            "name": "Ashe",
            "image": "Ashe.png",
            "source": "data_dragon",
        }

    def _account(
        self,
        puuid="route-puuid",
        mastery=None,
    ):
        return {
            "game_name": "RoutePlayer",
            "tag_line": "EUW",
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
        accounts=None,
    ):
        return {
            "display_name": "Route Person",
            "riot_accounts": list(
                accounts
                or []
            ),
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

    def _stage_document(
        self,
        document,
        follow_redirects=True,
    ):
        return self.client.post(
            "/settings/data-import/stage",
            data={
                "import_file": (
                    BytesIO(
                        self._serialize_document(
                            document
                        )
                    ),
                    "portable-export.json",
                )
            },
            content_type="multipart/form-data",
            follow_redirects=follow_redirects,
        )

    def _get_session_token(
        self
    ):
        with self.client.session_transaction() as session_data:
            return session_data.get(
                SESSION_STAGING_TOKEN_KEY
            )

    def _marker_file(
        self
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

    def test_get_import_page_without_active_stage(
        self
    ):
        response = self.client.get(
            "/settings/data-import"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "Select export file",
            response.get_data(
                as_text=True
            ),
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

    def test_valid_upload_is_staged_and_previewed(
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

        response = self._stage_document(
            document
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
            "portable-export.json",
            response_text,
        )

        self.assertIn(
            "Route Person",
            response_text,
        )

        self.assertIsNotNone(
            self._get_session_token()
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
            self._backup_files(),
            [],
        )

    def test_missing_upload_is_rejected(
        self
    ):
        response = self.client.post(
            "/settings/data-import/stage",
            data={},
            follow_redirects=True,
        )

        self.assertIn(
            "Select a JSON export file",
            response.get_data(
                as_text=True
            ),
        )

        self.assertIsNone(
            self._get_session_token()
        )

        self.assertFalse(
            self._marker_file().exists()
        )

    def test_invalid_json_is_rejected_without_stage(
        self
    ):
        response = self.client.post(
            "/settings/data-import/stage",
            data={
                "import_file": (
                    BytesIO(
                        b"not valid json"
                    ),
                    "invalid.json",
                )
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertIn(
            "could not be saved or verified",
            response.get_data(
                as_text=True
            ),
        )

        self.assertIsNone(
            self._get_session_token()
        )

        self.assertFalse(
            self._marker_file().exists()
        )

    def test_execute_staged_import_succeeds(
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
                                    "mastery_points": 750,
                                }
                            ]
                        )
                    ]
                )
            ],
        )

        self._stage_document(
            document
        )

        response = self.client.post(
            "/settings/data-import/execute",
            data={
                "confirmation_text": "IMPORT"
            },
            follow_redirects=True,
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertIn(
            "The JSON import was completed",
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

        self.assertEqual(
            len(
                self._backup_files()
            ),
            1,
        )

        self.assertIsNone(
            self._get_session_token()
        )

        self.assertFalse(
            self._marker_file().exists()
        )

    def test_wrong_confirmation_preserves_stage(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        self._stage_document(
            document
        )

        original_token = (
            self._get_session_token()
        )

        response = self.client.post(
            "/settings/data-import/execute",
            data={
                "confirmation_text": "import"
            },
            follow_redirects=True,
        )

        self.assertIn(
            "Type IMPORT exactly",
            response.get_data(
                as_text=True
            ),
        )

        self.assertEqual(
            self._get_session_token(),
            original_token,
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
            self._backup_files(),
            [],
        )

    def test_existing_puuid_displays_blocked_preview(
        self
    ):
        local_person = Person(
            display_name="Local Person"
        )

        db.session.add(
            local_person
        )

        db.session.flush()

        db.session.add(
            RiotAccount(
                person_id=local_person.id,
                game_name="LocalPlayer",
                tag_line="LOCAL",
                puuid="shared-route-puuid",
                platform_region="euw1",
            )
        )

        db.session.commit()

        document = self._build_document(
            persons=[
                self._person(
                    accounts=[
                        self._account(
                            puuid=(
                                "shared-route-puuid"
                            )
                        )
                    ]
                )
            ]
        )

        response = self._stage_document(
            document
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertIn(
            "Import blocked",
            response_text,
        )

        self.assertIn(
            "Local Person",
            response_text,
        )

        self.assertNotIn(
            'name="confirmation_text"',
            response_text,
        )

        execution_response = (
            self.client.post(
                "/settings/data-import/execute",
                data={
                    "confirmation_text": "IMPORT"
                },
                follow_redirects=True,
            )
        )

        self.assertIn(
            "conflicts",
            execution_response.get_data(
                as_text=True
            ),
        )

        self.assertEqual(
            db.session.query(
                Person
            ).count(),
            1,
        )

        self.assertEqual(
            self._backup_files(),
            [],
        )

        self.assertTrue(
            self._marker_file().is_file()
        )

    def test_cancel_removes_staged_import(
        self
    ):
        document = self._build_document(
            persons=[
                self._person()
            ]
        )

        self._stage_document(
            document
        )

        response = self.client.post(
            "/settings/data-import/cancel",
            follow_redirects=True,
        )

        self.assertIn(
            "temporary JSON import was cancelled",
            response.get_data(
                as_text=True
            ),
        )

        self.assertIsNone(
            self._get_session_token()
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

    def test_stale_session_token_is_cleared(
        self
    ):
        with self.client.session_transaction() as session_data:
            session_data[
                SESSION_STAGING_TOKEN_KEY
            ] = "0" * 32

        response = self.client.get(
            "/settings/data-import"
        )

        self.assertIn(
            "could not be saved or verified",
            response.get_data(
                as_text=True
            ),
        )

        self.assertIsNone(
            self._get_session_token()
        )


if __name__ == "__main__":
    unittest.main()