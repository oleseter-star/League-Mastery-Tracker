import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.database.models import Person
from application.routes.json_export import json_export_bp
from application.services.database_migration_service import (
    DatabaseMigrationService,
)
from application.services.json_export_service import (
    JsonExportError,
)


class JsonExportRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "json-export-route-test.db"
        )

        database_uri = (
            "sqlite:///"
            + self.database_file.as_posix()
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
            SECRET_KEY=(
                "json-export-route-test-key"
            ),
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

        self.app.register_blueprint(
            json_export_bp
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        DatabaseMigrationService.initialize_or_migrate()

        db.create_all()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

        self.app_context.pop()
        self.temporary_directory.cleanup()

    def test_export_page_shows_record_counts(self):
        db.session.add_all(
            [
                Person(
                    display_name="Person One",
                ),
                Person(
                    display_name="Person Two",
                ),
            ]
        )

        db.session.commit()

        response = self.client.get(
            "/settings/data-export"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"JSON export",
            response.data,
        )

        self.assertIn(
            b"Persons",
            response.data,
        )

        self.assertIn(
            b">2<",
            response.data.replace(
                b"\n",
                b"",
            ).replace(
                b" ",
                b"",
            ),
        )

    def test_export_page_uses_mastery_points_copy(self):
        response = self.client.get(
            "/settings/data-export"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        html = response.get_data(
            as_text=True
        )

        scope_sections = re.findall(
            r'<section\b[^>]*aria-labelledby="export-scope-heading"'
            r'[^>]*>(?P<section>.*?)</section>',
            html,
            flags=re.DOTALL,
        )

        self.assertEqual(
            len(scope_sections),
            1,
        )

        included_articles = [
            article
            for article in re.findall(
                r'<article\b[^>]*>(?P<article>.*?)</article>',
                scope_sections[0],
                flags=re.DOTALL,
            )
            if re.search(
                r"<h3>\s*Included\s*</h3>",
                article,
                flags=re.DOTALL,
            )
        ]

        self.assertEqual(
            len(included_articles),
            1,
        )

        included_labels = [
            " ".join(
                label.split()
            )
            for label in re.findall(
                r"<li>(?P<label>.*?)</li>",
                included_articles[0],
                flags=re.DOTALL,
            )
        ]

        self.assertIn(
            "Mastery points",
            included_labels,
        )

        self.assertNotIn(
            "Champion Mastery points",
            included_labels,
        )

    def test_export_page_contains_download_link(self):
        response = self.client.get(
            "/settings/data-export"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"/settings/data-export/download",
            response.data,
        )

        self.assertIn(
            b"Download JSON export",
            response.data,
        )

        self.assertIn(
            b"Riot PUUIDs",
            response.data,
        )

    def test_export_page_does_not_display_person_data(self):
        private_display_name = (
            "Private Person Name 12345"
        )

        person = Person(
            display_name=private_display_name,
        )

        db.session.add(
            person
        )

        db.session.commit()

        response = self.client.get(
            "/settings/data-export"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotIn(
            private_display_name.encode(
                "utf-8"
            ),
            response.data,
        )

    def test_export_page_handles_service_error(self):
        with patch(
            "application.routes.json_export."
            "JsonExportService.build_export_document",
            side_effect=JsonExportError(
                "Simulated summary failure."
            ),
        ):
            response = self.client.get(
                "/settings/data-export"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            b"Export unavailable",
            response.data,
        )

        self.assertIn(
            b"Simulated summary failure",
            response.data,
        )

        self.assertNotIn(
            b"Download JSON export",
            response.data,
        )

    def test_download_returns_json_attachment(self):
        response = self.client.get(
            "/settings/data-export/download"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.content_type,
            "application/json; charset=utf-8",
        )

        content_disposition = response.headers.get(
            "Content-Disposition"
        )

        self.assertIsNotNone(
            content_disposition
        )

        self.assertRegex(
            content_disposition,
            re.compile(
                r'^attachment; filename="'
                r"league_mastery_tracker_export_"
                r"\d{8}T\d{6}Z"
                r'\.json"$'
            ),
        )

    def test_download_contains_valid_export_contract(self):
        person = Person(
            display_name="Export Route Person",
        )

        db.session.add(
            person
        )

        db.session.commit()

        response = self.client.get(
            "/settings/data-export/download"
        )

        document = json.loads(
            response.data.decode(
                "utf-8"
            )
        )

        self.assertEqual(
            document["format"],
            "league-mastery-tracker-export",
        )

        self.assertEqual(
            document["format_version"],
            2,
        )

        self.assertEqual(
            document[
                "database_schema_version"
            ],
            3,
        )

        self.assertEqual(
            document["record_counts"]["persons"],
            1,
        )

        self.assertEqual(
            document["data"]["persons"][0],
            {
                "display_name": (
                    "Export Route Person"
                ),
                "riot_accounts": [],
            },
        )

    def test_download_uses_utf8(self):
        person = Person(
            display_name="Ægir Øst",
        )

        db.session.add(
            person
        )

        db.session.commit()

        response = self.client.get(
            "/settings/data-export/download"
        )

        decoded_response = response.data.decode(
            "utf-8"
        )

        self.assertIn(
            "Ægir Øst",
            decoded_response,
        )

        self.assertTrue(
            decoded_response.endswith(
                "\n"
            )
        )

    def test_download_disables_caching_and_sniffing(self):
        response = self.client.get(
            "/settings/data-export/download"
        )

        self.assertEqual(
            response.headers.get(
                "Cache-Control"
            ),
            "no-store, max-age=0",
        )

        self.assertEqual(
            response.headers.get(
                "Pragma"
            ),
            "no-cache",
        )

        self.assertEqual(
            response.headers.get(
                "Expires"
            ),
            "0",
        )

        self.assertEqual(
            response.headers.get(
                "X-Content-Type-Options"
            ),
            "nosniff",
        )

    def test_export_failure_returns_plain_text_error(self):
        with patch(
            "application.routes.json_export."
            "JsonExportService.build_export_bytes",
            side_effect=JsonExportError(
                "Simulated export failure."
            ),
        ):
            response = self.client.get(
                "/settings/data-export/download"
            )

        self.assertEqual(
            response.status_code,
            500,
        )

        self.assertEqual(
            response.content_type,
            "text/plain; charset=utf-8",
        )

        self.assertIn(
            b"JSON export failed",
            response.data,
        )

        self.assertIn(
            b"Simulated export failure",
            response.data,
        )

        self.assertNotIn(
            "Content-Disposition",
            response.headers,
        )

        self.assertEqual(
            response.headers.get(
                "Cache-Control"
            ),
            "no-store, max-age=0",
        )

        self.assertEqual(
            response.headers.get(
                "X-Content-Type-Options"
            ),
            "nosniff",
        )


if __name__ == "__main__":
    unittest.main()