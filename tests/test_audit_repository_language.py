import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import audit_repository_language


class AuditRepositoryLanguageTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.project_root = Path(
            self.temporary_directory.name
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_clean_repository_returns_zero(
        self,
    ):
        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit.return_value = []

            standard_output = io.StringIO()

            with redirect_stdout(
                standard_output
            ):
                exit_code = (
                    audit_repository_language.main(
                        project_root=self.project_root
                    )
                )

        self.assertEqual(
            exit_code,
            0,
        )

        self.assertIn(
            "No Norwegian project-owned prose was found.",
            standard_output.getvalue(),
        )

    def test_findings_return_nonzero(
        self,
    ):
        findings = [
            {
                "path": "application/templates/home.html",
                "line_number": 12,
                "category": "user_facing",
                "matched_terms": (
                    "innstillinger",
                ),
                "line": "<a>Innstillinger</a>",
            },
        ]

        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit.return_value = (
                findings
            )

            standard_output = io.StringIO()

            with redirect_stdout(
                standard_output
            ):
                exit_code = (
                    audit_repository_language.main(
                        project_root=self.project_root
                    )
                )

        self.assertEqual(
            exit_code,
            1,
        )

    def test_report_contains_summary_and_finding_details(
        self,
    ):
        findings = [
            {
                "path": "application/templates/home.html",
                "line_number": 12,
                "category": "user_facing",
                "matched_terms": (
                    "innstillinger",
                    "tilbake",
                ),
                "line": (
                    "<a>Tilbake til innstillinger</a>"
                ),
            },
            {
                "path": "tests/test_example.py",
                "line_number": 44,
                "category": "test_only",
                "matched_terms": (
                    "programmet",
                    "avsluttes",
                ),
                "line": (
                    'EXPECTED = "Programmet avsluttes"'
                ),
            },
        ]

        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit.return_value = (
                findings
            )

            standard_output = io.StringIO()

            with redirect_stdout(
                standard_output
            ):
                audit_repository_language.main(
                    project_root=self.project_root
                )

        output = standard_output.getvalue()

        self.assertIn(
            "Total findings: 2",
            output,
        )

        self.assertIn(
            "user_facing: 1",
            output,
        )

        self.assertIn(
            "test_only: 1",
            output,
        )

        self.assertIn(
            (
                "application/templates/home.html:"
                "12"
            ),
            output,
        )

        self.assertIn(
            "innstillinger, tilbake",
            output,
        )

        self.assertIn(
            (
                "tests/test_example.py:"
                "44"
            ),
            output,
        )

    def test_service_receives_resolved_project_root(
        self,
    ):
        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit.return_value = []

            audit_repository_language.main(
                project_root=self.project_root
            )

        service_class.assert_called_once_with(
            project_root=(
                self.project_root.resolve()
            ),
            allowlisted_paths=(),
            allowlisted_phrases=(),
        )

    def test_allowlists_are_forwarded(
        self,
    ):
        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit.return_value = []

            audit_repository_language.main(
                project_root=self.project_root,
                allowlisted_paths=(
                    "tests/fixtures/legacy.txt",
                ),
                allowlisted_phrases=(
                    "Ingen oversettelse",
                ),
            )

        service_class.assert_called_once_with(
            project_root=(
                self.project_root.resolve()
            ),
            allowlisted_paths=(
                "tests/fixtures/legacy.txt",
            ),
            allowlisted_phrases=(
                "Ingen oversettelse",
            ),
        )

    def test_unexpected_failure_is_controlled(
        self,
    ):
        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit.side_effect = (
                OSError(
                    "C:\\private\\repository"
                )
            )

            error_output = io.StringIO()

            with redirect_stderr(
                error_output
            ):
                exit_code = (
                    audit_repository_language.main(
                        project_root=self.project_root
                    )
                )

        self.assertEqual(
            exit_code,
            2,
        )

        output = error_output.getvalue()

        self.assertIn(
            "The repository language audit could not be completed.",
            output,
        )

        self.assertNotIn(
            "C:\\private",
            output,
        )


if __name__ == "__main__":
    unittest.main()