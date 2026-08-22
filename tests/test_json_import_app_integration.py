import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import application.app as app_module
from application.database.database import db
from application.services.json_import_read_service import (
    JsonImportReadService,
)
from application.services.json_import_staging_service import (
    JsonImportStagingService,
)


class JsonImportAppIntegrationTests(
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
            / "integration.db"
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

        class JsonImportIntegrationConfig:
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
            "json_import_integration_test"
        )

        with patch.dict(
            app_module.configurations,
            {
                self.config_name: (
                    JsonImportIntegrationConfig
                )
            },
            clear=False,
        ):
            with patch.object(
                app_module.LocalSecretKeyService,
                "get_or_create_secret_key",
                return_value=(
                    b"integration-test-secret-key-"
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

        self.client = (
            self.app.test_client()
        )

    def tearDown(self):
        try:
            with self.app.app_context():
                db.session.rollback()
                db.session.remove()

                db.drop_all()

                db.engine.dispose()

        finally:
            self.temporary_directory.cleanup()

    def test_complete_app_registers_json_import_routes(
        self
    ):
        expected_endpoints = {
            "json_import.get_json_import",
            "json_import.stage_json_import",
            "json_import.execute_json_import",
            "json_import.cancel_json_import",
        }

        self.assertTrue(
            expected_endpoints.issubset(
                self.app.view_functions.keys()
            )
        )

    def test_complete_app_configures_import_limits(
        self
    ):
        expected_file_limit = (
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        )

        expected_request_limit = (
            expected_file_limit
            + app_module
            .JSON_IMPORT_REQUEST_OVERHEAD_BYTES
        )

        self.assertEqual(
            self.app.config[
                "JSON_IMPORT_MAX_FILE_SIZE_BYTES"
            ],
            expected_file_limit,
        )

        self.assertEqual(
            self.app.config[
                "JSON_IMPORT_STAGING_EXPIRATION_MINUTES"
            ],
            (
                JsonImportStagingService
                .DEFAULT_EXPIRATION_MINUTES
            ),
        )

        self.assertEqual(
            self.app.config[
                "MAX_CONTENT_LENGTH"
            ],
            expected_request_limit,
        )

        self.assertGreater(
            self.app.config[
                "MAX_CONTENT_LENGTH"
            ],
            self.app.config[
                "JSON_IMPORT_MAX_FILE_SIZE_BYTES"
            ],
        )

    def test_import_page_is_available_through_complete_app(
        self
    ):
        response = self.client.get(
            "/settings/data-import"
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "Import portable JSON data",
            response_text,
        )

        self.assertIn(
            "Select export file",
            response_text,
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

    def test_settings_page_links_to_export_and_import(
        self
    ):
        api_key_status = {
            "configured": False,
            "source": None,
            "masked_key": None,
            "error": None,
        }

        with patch(
            (
                "application.routes.settings."
                "RiotApiKeyService.get_status"
            ),
            return_value=api_key_status,
        ):
            response = self.client.get(
                "/settings"
            )

        response_text = response.get_data(
            as_text=True
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            'href="/settings/data-export"',
            response_text,
        )

        self.assertIn(
            'href="/settings/data-import"',
            response_text,
        )

        self.assertIn(
            "Portable data",
            response_text,
        )

    def test_import_post_is_csrf_protected_in_complete_app(
        self
    ):
        response = self.client.post(
            "/settings/data-import/cancel"
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertIn(
            "invalid or missing CSRF token",
            response.get_data(
                as_text=True
            ),
        )


if __name__ == "__main__":
    unittest.main()