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

    @staticmethod
    def _result(findings=()):
        findings = list(findings)
        return {
            "tracked_paths": (),
            "outcomes": (),
            "findings": findings,
            "counts": {
                "tracked_files": 0,
                "audited_text": 0,
                "intentional_binary_exclusion": 0,
                "controlled_non_language_exclusion": 0,
                "audit_error": sum(
                    finding.get("category") == "audit_error"
                    for finding in findings
                ),
            },
            "applied_exceptions": (),
        }

    def test_clean_repository_returns_zero(
        self,
    ):
        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit_repository.return_value = (
                self._result()
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
            0,
        )

        self.assertIn(
            "Repository language audit passed",
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
            service_class.return_value.audit_repository.return_value = (
                self._result(findings)
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

    def test_finding_path_and_line_reference_are_terminal_safe(
        self,
    ):
        synthetic_path = (
            "application/templates/base.html"
            "\nFORGED-PATH"
            "\r"
            "\t"
            "\x1b[2J"
        )
        synthetic_line_number = (
            "12\nFORGED-LINE\r\t\x1b[31m"
        )
        findings = [
            {
                "path": synthetic_path,
                "line_number": synthetic_line_number,
                "category": "user_facing",
                "matched_terms": ("synthetic_term",),
                "line": "Synthetic finding message.",
            },
        ]

        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit_repository.return_value = (
                self._result(findings)
            )
            standard_output = io.StringIO()
            standard_error = io.StringIO()

            with (
                redirect_stdout(standard_output),
                redirect_stderr(standard_error),
            ):
                exit_code = audit_repository_language.main(
                    project_root=self.project_root
                )

        self.assertEqual(exit_code, 1)
        service_class.return_value.audit_repository.assert_called_once_with()
        self.assertEqual(standard_error.getvalue(), "")
        self.assertEqual(
            standard_output.getvalue().splitlines(),
            [
                "Repository language audit",
                "Total findings: 1",
                "user_facing: 1",
                (
                    "application/templates/base.html\\nFORGED-PATH"
                    "\\r\\t\\x1b[2J:"
                    "12\\nFORGED-LINE\\r\\t\\x1b[31m "
                    "[user_facing/language] synthetic_term: "
                    "Synthetic finding message."
                ),
            ],
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
            service_class.return_value.audit_repository.return_value = (
                self._result(findings)
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
            service_class.return_value.audit_repository.return_value = (
                self._result()
            )

            audit_repository_language.main(
                project_root=self.project_root
            )

        service_class.assert_called_once_with(
            project_root=(
                self.project_root.resolve()
            ),
            intentional_exceptions=(),
        )

    def test_intentional_exceptions_are_forwarded(
        self,
    ):
        intentional_exceptions = (
            {
                "path": "tests/fixtures/legacy.txt",
                "line": 'MESSAGE = "Ingen oversettelse"',
                "finding_type": "norwegian_vocabulary",
                "reason": "Deliberate detector fixture.",
            },
        )

        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit_repository.return_value = (
                self._result()
            )

            audit_repository_language.main(
                project_root=self.project_root,
                intentional_exceptions=intentional_exceptions,
            )

        service_class.assert_called_once_with(
            project_root=(
                self.project_root.resolve()
            ),
            intentional_exceptions=intentional_exceptions,
        )

    def test_unexpected_failure_is_controlled(
        self,
    ):
        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit_repository.side_effect = (
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


class AuditRepositoryLanguageTrackedContractTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(
            self.temporary_directory.name
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _clean_result():
        return {
            "tracked_paths": ("README.md", "image.png"),
            "outcomes": (
                {
                    "path": "README.md",
                    "outcome": "audited_text",
                    "encoding": "utf-8",
                },
                {
                    "path": "image.png",
                    "outcome": (
                        "intentional_binary_exclusion"
                    ),
                    "encoding": None,
                },
            ),
            "findings": [],
            "counts": {
                "tracked_files": 2,
                "audited_text": 1,
                "intentional_binary_exclusion": 1,
                "controlled_non_language_exclusion": 0,
                "audit_error": 0,
            },
            "applied_exceptions": (),
        }

    def test_clean_audit_reports_concise_outcome_counts(
        self,
    ):
        result = self._clean_result()

        self.assertEqual(
            result["findings"],
            [],
        )

        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit_repository.return_value = (
                result
            )

            standard_output = io.StringIO()
            standard_error = io.StringIO()

            with (
                redirect_stdout(standard_output),
                redirect_stderr(standard_error),
            ):
                exit_code = audit_repository_language.main(
                    project_root=self.project_root
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            standard_output.getvalue(),
            (
                "Repository language audit passed: "
                "2 tracked files; "
                "1 audited text; "
                "1 intentional binary exclusions; "
                "0 controlled non-language exclusions; "
                "0 findings; "
                "0 audit errors.\n"
            ),
        )
        self.assertEqual(standard_error.getvalue(), "")

    def test_controlled_audit_error_returns_nonzero(
        self,
    ):
        result = self._clean_result()
        result["findings"] = [
            {
                "path": "broken.txt",
                "line_number": 0,
                "category": "audit_error",
                "finding_type": "audit_error",
                "matched_terms": ("unsupported_encoding",),
                "line": "Tracked text could not be decoded.",
            },
        ]
        result["counts"] = {
            **result["counts"],
            "audit_error": 1,
        }

        with patch.object(
            audit_repository_language,
            "RepositoryLanguageAuditService",
        ) as service_class:
            service_class.return_value.audit_repository.return_value = (
                result
            )
            standard_output = io.StringIO()

            with redirect_stdout(standard_output):
                exit_code = audit_repository_language.main(
                    project_root=self.project_root
                )

        self.assertEqual(exit_code, 1)
        output = standard_output.getvalue()
        self.assertIn("broken.txt:0", output)
        self.assertIn("audit_error", output)


class RepositoryLanguageAuditArtifactTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent

    def _read_artifact(self, file_name):
        return (self.project_root / file_name).read_text(
            encoding="utf-8",
        )

    def _section(self, content, title, next_title=None):
        self.assertIn(title, content)
        section = content.split(title, 1)[1]
        if next_title is not None:
            self.assertIn(next_title, section)
            section = section.split(next_title, 1)[0]
        return section

    def test_language_audit_artifact_records_current_counts(
        self,
    ):
        content = self._read_artifact(
            "Step10-language-audit.txt"
        )

        for record in (
            "Tracked paths: 352",
            "Audited text: 178",
            "Intentional binary exclusions: 174",
            "Controlled non-language exclusions: 0",
            "Audit errors: 0",
            "Findings: 0",
        ):
            self.assertEqual(content.count(record), 1)

        self.assertIn(
            "This artifact records no PyInstaller build result and no Windows acceptance result.",
            content,
        )

        self.assertIn(
            (
                "Step 10.14 repository-wide language verification "
                "is complete."
            ),
            content,
        )

        self.assertIn(
            (
                "Focused verification: 54 tests passed with 0 failures, "
                "0 errors, and 0 skips."
            ),
            content,
        )

        self.assertNotIn(
            "The final focused run contains 50 tests",
            content,
        )

        self.assertNotIn(
            (
                "A final repository-wide language verification remains "
                "scheduled for Step 10.14"
            ),
            content,
        )

    def test_language_audit_artifact_documents_canonical_invocation(
        self,
    ):
        content = self._read_artifact(
            "Step10-language-audit.txt"
        )
        command = "python -B audit_repository_language.py"
        invocation_block = (
            "Audit invocation\n"
            "----------------\n"
            "Run the following command from the repository root:\n"
            "\n"
            "python -B audit_repository_language.py\n"
        )

        command_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip() == command
        ]

        self.assertEqual(command_lines, [command])
        self.assertEqual(content.count(invocation_block), 1)

    def test_test_results_artifact_distinguishes_verification_stages(
        self,
    ):
        content = self._read_artifact(
            "Step10-test-results.txt"
        )
        restricted = self._section(
            content,
            "Original restricted full-suite run",
            "Focused elevated application-server rerun",
        )
        elevated = self._section(
            content,
            "Focused elevated application-server rerun",
            "Reconciled Step 10.15 result",
        )
        reconciled = self._section(
            content,
            "Reconciled Step 10.15 result",
            "Step 10.6 Slice 6 focused verification",
        )
        slice_six = self._section(
            content,
            "Step 10.6 Slice 6 focused verification",
        )

        for section, records in (
            (
                restricted,
                (
                    "Executed: 783",
                    "Passed: 768",
                    "Failures: 0",
                    "Errors: 2",
                    "Skipped: 13",
                    "sandbox-only PermissionError failures",
                    "local loopback",
                    "tests.test_application_server_service",
                    "affected assertions",
                ),
            ),
            (
                elevated,
                (
                    "tests.test_application_server_service",
                    "Executed: 16",
                    "Passed: 16",
                    "Failures: 0",
                    "Errors: 0",
                    "Skipped: 0",
                    "required local socket permission",
                    "not a second full-suite run",
                ),
            ),
            (
                reconciled,
                (
                    "Executed: 783",
                    "Passed: 770",
                    "Failures: 0",
                    "Errors: 0",
                    "Skipped: 13",
                    "Reconciliation replaces only those two errors",
                    "not a single unrestricted all-green full-suite invocation",
                ),
            ),
            (
                slice_six,
                (
                    "Executed: 50",
                    "Passed: 50",
                    "Failures: 0",
                    "Errors: 0",
                    "Skipped: 0",
                ),
            ),
        ):
            for record in records:
                self.assertIn(record, section)

        self.assertIn(
            "Step 10.15 full automated regression verification is complete.",
            content,
        )
        self.assertIn("Modules: 87", restricted)
        self.assertIn("Elapsed: 72.930 seconds", restricted)
        self.assertIn(
            "The full suite ran exactly once in the restricted environment",
            content,
        )
        self.assertIn(
            "sandbox-only PermissionError failures",
            content,
        )
        self.assertIn(
            "The elevated run was focused, not a second full-suite run",
            content,
        )
        self.assertIn(
            "Reconciliation replaces only those two errors",
            content,
        )
        self.assertIn(
            "5 Windows application-instance locking",
            content,
        )
        self.assertIn(
            "4 encrypted Riot API-key Windows tests",
            content,
        )
        self.assertIn("3 Windows DPAPI tests", content)
        self.assertIn(
            "1 optional PyInstaller resource parser without pefile",
            content,
        )
        self.assertNotIn("This is the verified Step 10.5 integration checkpoint", content)
        self.assertIn(
            "No PyInstaller build result or Windows acceptance result is recorded here.",
            content,
        )
        self.assertIn(
            "The new console-free Windows build remains Step 10.16.",
            content,
        )


if __name__ == "__main__":
    unittest.main()