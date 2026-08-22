import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.services.database_migration_service import (
    DatabaseMigrationService,
)
from application.services.json_export_service import (
    JsonExportError,
    JsonExportService,
)
from application.services.json_export_validation_service import (
    JsonExportValidationError,
)


class JsonExportValidationIntegrationTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "validation-integration.db"
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

    def test_internal_validation_failure_aborts_export(self):
        with patch(
            "application.services.json_export_service."
            "JsonExportValidationService.validate_document",
            side_effect=JsonExportValidationError(
                "Simulated internal validation failure."
            ),
        ):
            with self.assertRaisesRegex(
                JsonExportError,
                "failed internal validation",
            ):
                (
                    JsonExportService
                    .build_export_document()
                )


if __name__ == "__main__":
    unittest.main()