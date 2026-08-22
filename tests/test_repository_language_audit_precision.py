from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from application.services.repository_language_audit_service import (
    RepositoryLanguageAuditService,
)


class RepositoryLanguageAuditPrecisionTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.project_root = Path(
            self.temporary_directory.name
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_text(
        self,
        relative_path,
        content,
    ):
        file_path = (
            self.project_root
            / relative_path
        )

        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_path.write_text(
            content,
            encoding="utf-8",
        )

    def _audit(self):
        return RepositoryLanguageAuditService(
            project_root=self.project_root,
        ).audit()

    def test_english_product_terminology_is_not_reported(
        self,
    ):
        self._write_text(
            "application/templates/status.html",
            (
                "<p>"
                "The dashboard displays the local database "
                "backup status for each person."
                "</p>\n"
            ),
        )

        self.assertEqual(
            self._audit(),
            [],
        )

    def test_english_manual_metadata_text_is_not_reported(
        self,
    ):
        self._write_text(
            "application/services/example_service.py",
            (
                '"""Preserve manual metadata and local cache data."""\n'
            ),
        )

        self.assertEqual(
            self._audit(),
            [],
        )

    def test_english_update_and_import_text_is_not_reported(
        self,
    ):
        self._write_text(
            "README.md",
            (
                "Create a backup before a manual update, "
                "import, export, or database restore.\n"
            ),
        )

        self.assertEqual(
            self._audit(),
            [],
        )

    def test_english_unknown_champion_text_is_not_reported(
        self,
    ):
        self._write_text(
            "tests/test_unknown_champion.py",
            (
                'MESSAGE = '
                '"The unknown champion remains available."\n'
            ),
        )

        self.assertEqual(
            self._audit(),
            [],
        )

    def test_user_created_unicode_names_are_not_reported(
        self,
    ):
        self._write_text(
            "tests/test_unicode_fixture.py",
            (
                'PERSON_NAME = "Bjørn"\n'
                'SECOND_PERSON_NAME = "Ægir Export"\n'
            ),
        )

        self.assertEqual(
            self._audit(),
            [],
        )

    def test_distinctive_norwegian_text_is_still_reported(
        self,
    ):
        self._write_text(
            "application/templates/settings.html",
            (
                "<p>"
                "Programmet kunne ikke oppdateres, "
                "men eksisterende data er fortsatt tilgjengelig."
                "</p>\n"
            ),
        )

        findings = self._audit()

        self.assertEqual(
            len(findings),
            1,
        )

        self.assertEqual(
            findings[0]["category"],
            "user_facing",
        )

        self.assertIn(
            "programmet",
            findings[0]["matched_terms"],
        )

        self.assertIn(
            "kunne ikke",
            findings[0]["matched_terms"],
        )

        self.assertIn(
            "fortsatt",
            findings[0]["matched_terms"],
        )


if __name__ == "__main__":
    unittest.main()