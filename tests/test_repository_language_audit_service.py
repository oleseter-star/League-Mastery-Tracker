from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from application.services.repository_language_audit_service import (
    RepositoryLanguageAuditService,
)


class RepositoryLanguageAuditServiceTests(
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

        return file_path

    def _audit(
        self,
        *,
        allowlisted_paths=None,
        allowlisted_phrases=None,
    ):
        return RepositoryLanguageAuditService(
            project_root=self.project_root,
            allowlisted_paths=(
                allowlisted_paths
                or ()
            ),
            allowlisted_phrases=(
                allowlisted_phrases
                or ()
            ),
        ).audit()

    def test_norwegian_template_text_is_classified_as_user_facing(
        self,
    ):
        self._write_text(
            "application/templates/settings.html",
            "<h1>Innstillinger</h1>\n",
        )

        findings = self._audit()

        self.assertEqual(
            findings,
            [
                {
                    "path": (
                        "application/templates/"
                        "settings.html"
                    ),
                    "line_number": 1,
                    "category": "user_facing",
                    "matched_terms": (
                        "innstillinger",
                    ),
                    "line": (
                        "<h1>Innstillinger</h1>"
                    ),
                },
            ],
        )

    def test_norwegian_python_text_is_classified_as_developer_facing(
        self,
    ):
        self._write_text(
            "application/services/example_service.py",
            (
                '"""Oppretter en lokal backup."""\n'
                "\n"
                'MESSAGE = "Backup kunne ikke opprettes."\n'
            ),
        )

        findings = self._audit()

        self.assertEqual(
            len(findings),
            2,
        )

        self.assertTrue(
            all(
                finding["category"]
                == "developer_facing"
                for finding in findings
            )
        )

        self.assertEqual(
            findings[0]["line_number"],
            1,
        )

        self.assertIn(
            "oppretter",
            findings[0]["matched_terms"],
        )

        self.assertEqual(
            findings[1]["line_number"],
            3,
        )

        self.assertIn(
            "kunne ikke",
            findings[1]["matched_terms"],
        )

    def test_norwegian_test_text_is_classified_as_test_only(
        self,
    ):
        self._write_text(
            "tests/test_example.py",
            (
                'EXPECTED_MESSAGE = '
                '"Programmet avsluttes."\n'
            ),
        )

        findings = self._audit()

        self.assertEqual(
            len(findings),
            1,
        )

        self.assertEqual(
            findings[0]["category"],
            "test_only",
        )

        self.assertIn(
            "programmet",
            findings[0]["matched_terms"],
        )

        self.assertIn(
            "avsluttes",
            findings[0]["matched_terms"],
        )

    def test_norwegian_documentation_is_classified_as_documentation(
        self,
    ):
        self._write_text(
            "README.md",
            (
                "# League Mastery Tracker\n\n"
                "Programmet fungerer uten internett.\n"
            ),
        )

        findings = self._audit()

        self.assertEqual(
            len(findings),
            1,
        )

        self.assertEqual(
            findings[0]["path"],
            "README.md",
        )

        self.assertEqual(
            findings[0]["line_number"],
            3,
        )

        self.assertEqual(
            findings[0]["category"],
            "documentation",
        )

    def test_multiple_terms_on_one_line_produce_one_finding(
        self,
    ):
        self._write_text(
            "application/templates/home.html",
            (
                "<p>Ingen personer er "
                "opprettet ennå.</p>\n"
            ),
        )

        findings = self._audit()

        self.assertEqual(
            len(findings),
            1,
        )

        self.assertEqual(
            findings[0]["matched_terms"],
            (
                "ingen",
                "personer",
                "opprettet",
                "ennå",
            ),
        )

    def test_excluded_directories_are_not_scanned(
        self,
    ):
        excluded_directories = (
            ".git",
            ".venv",
            "build",
            "dist",
            "__pycache__",
        )

        for directory_name in excluded_directories:
            self._write_text(
                (
                    f"{directory_name}/"
                    "ignored.py"
                ),
                (
                    'MESSAGE = '
                    '"Innstillinger"\n'
                ),
            )

        findings = self._audit()

        self.assertEqual(
            findings,
            [],
        )

    def test_binary_files_are_ignored(
        self,
    ):
        binary_file = (
            self.project_root
            / "application"
            / "static"
            / "image.png"
        )

        binary_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        binary_file.write_bytes(
            (
                b"\x89PNG\r\n\x1a\n"
                b"Innstillinger"
                b"\x00\xff"
            )
        )

        findings = self._audit()

        self.assertEqual(
            findings,
            [],
        )

    def test_unsupported_file_types_are_ignored(
        self,
    ):
        self._write_text(
            "application/static/generated.map",
            "Innstillinger\n",
        )

        findings = self._audit()

        self.assertEqual(
            findings,
            [],
        )

    def test_allowlisted_path_is_not_reported(
        self,
    ):
        self._write_text(
            "tests/fixtures/legacy_norwegian.txt",
            "Programmet avsluttes.\n",
        )

        findings = self._audit(
            allowlisted_paths=(
                (
                    "tests/fixtures/"
                    "legacy_norwegian.txt"
                ),
            ),
        )

        self.assertEqual(
            findings,
            [],
        )

    def test_allowlisted_phrase_is_not_reported(
        self,
    ):
        self._write_text(
            "tests/test_encoding_fixture.py",
            (
                'VALUE = '
                '"Ingen oversettelse"\n'
            ),
        )

        findings = self._audit(
            allowlisted_phrases=(
                "Ingen oversettelse",
            ),
        )

        self.assertEqual(
            findings,
            [],
        )

    def test_english_text_and_unicode_fixture_data_are_not_reported(
        self,
    ):
        self._write_text(
            "tests/test_unicode_export.py",
            (
                'PERSON_NAME = "Ægir Export"\n'
                'SECOND_NAME = "Bjørn"\n'
                'MESSAGE = "The export completed."\n'
            ),
        )

        findings = self._audit()

        self.assertEqual(
            findings,
            [],
        )

    def test_findings_are_sorted_by_path_and_line_number(
        self,
    ):
        self._write_text(
            "tests/test_second.py",
            (
                'FIRST = "Innstillinger"\n'
                'SECOND = "Programmet avsluttes"\n'
            ),
        )

        self._write_text(
            "application/templates/home.html",
            "<p>Ingen personer.</p>\n",
        )

        findings = self._audit()

        finding_positions = [
            (
                finding["path"],
                finding["line_number"],
            )
            for finding in findings
        ]

        self.assertEqual(
            finding_positions,
            [
                (
                    "application/templates/home.html",
                    1,
                ),
                (
                    "tests/test_second.py",
                    1,
                ),
                (
                    "tests/test_second.py",
                    2,
                ),
            ],
        )

    def test_matching_is_case_insensitive(
        self,
    ):
        self._write_text(
            "application/templates/home.html",
            (
                "<p>INNSTILLINGER</p>\n"
                "<p>Programmet Avsluttes</p>\n"
            ),
        )

        findings = self._audit()

        self.assertEqual(
            len(findings),
            2,
        )

        self.assertEqual(
            findings[0]["matched_terms"],
            (
                "innstillinger",
            ),
        )

        self.assertEqual(
            findings[1]["matched_terms"],
            (
                "programmet",
                "avsluttes",
            ),
        )


if __name__ == "__main__":
    unittest.main()