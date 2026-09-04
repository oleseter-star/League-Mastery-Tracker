from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
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

        self.tracked_paths = set()

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

        self.tracked_paths.add(
            Path(relative_path).as_posix()
        )

    def _audit(
        self,
        *,
        intentional_exceptions=(),
    ):
        return RepositoryLanguageAuditService(
            project_root=self.project_root,
            tracked_paths=tuple(
                sorted(self.tracked_paths)
            ),
            intentional_exceptions=(
                intentional_exceptions
            ),
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
            self._audit(
                intentional_exceptions=(
                    {
                        "path": "tests/test_unicode_fixture.py",
                        "line": 'PERSON_NAME = "Bjørn"',
                        "finding_type": "norwegian_character",
                        "reason": "Intentional Person-name fixture.",
                    },
                    {
                        "path": "tests/test_unicode_fixture.py",
                        "line": (
                            'SECOND_PERSON_NAME = "Ægir Export"'
                        ),
                        "finding_type": "norwegian_character",
                        "reason": "Intentional Person-name fixture.",
                    },
                ),
            ),
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


class CurrentRepositoryLanguageAuditTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.project_root = (
            Path(__file__).resolve().parent.parent
        )

    def _audit_repository(self):
        service = RepositoryLanguageAuditService(
            project_root=self.project_root,
        )
        audit_repository = getattr(
            service,
            "audit_repository",
            None,
        )
        self.assertIsNotNone(
            audit_repository,
            "The production audit must expose tracked-file outcomes.",
        )
        return service, audit_repository()

    def test_current_tracked_repository_is_clean(
        self,
    ):
        _service, result = self._audit_repository()
        completed_process = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=self.project_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tracked_paths = tuple(
            path_bytes.decode(
                "utf-8",
                errors="surrogateescape",
            )
            for path_bytes in completed_process.stdout.split(b"\0")
            if path_bytes
        )
        outcomes = result["outcomes"]
        outcome_paths = tuple(
            outcome["path"]
            for outcome in outcomes
        )
        outcome_paths_by_category = {
            category: tuple(
                outcome["path"]
                for outcome in outcomes
                if outcome["outcome"] == category
            )
            for category in (
                "audited_text",
                "intentional_binary_exclusion",
                "controlled_non_language_exclusion",
            )
        }
        classified_paths = tuple(
            path
            for category in outcome_paths_by_category.values()
            for path in category
        )

        failure_details = "\n".join(
            (
                f'{finding["path"]}:'
                f'{finding["line_number"]} '
                f'{finding["category"]}/'
                f'{finding["finding_type"]}: '
                f'{", ".join(finding["matched_terms"])}'
            )
            for finding in result["findings"]
        )

        self.assertEqual(
            result["findings"],
            [],
            failure_details,
        )
        self.assertEqual(
            result["counts"]["audit_error"],
            0,
            failure_details,
        )
        self.assertEqual(
            result["counts"]["tracked_files"],
            359,
        )
        self.assertEqual(len(tracked_paths), 359)
        self.assertEqual(result["tracked_paths"], tracked_paths)
        self.assertEqual(len(outcomes), 359)
        self.assertEqual(
            result["counts"]["audited_text"],
            185,
        )
        self.assertEqual(
            len(outcome_paths_by_category["audited_text"]),
            185,
        )
        self.assertEqual(
            result["counts"]["intentional_binary_exclusion"],
            174,
        )
        self.assertEqual(
            len(
                outcome_paths_by_category[
                    "intentional_binary_exclusion"
                ]
            ),
            174,
        )
        self.assertEqual(
            result["counts"]["controlled_non_language_exclusion"],
            0,
        )
        self.assertEqual(
            len(
                outcome_paths_by_category[
                    "controlled_non_language_exclusion"
                ]
            ),
            0,
        )
        self.assertEqual(len(classified_paths), 359)
        self.assertEqual(len(tracked_paths), len(set(tracked_paths)))
        self.assertEqual(len(outcome_paths), len(set(outcome_paths)))
        self.assertEqual(outcome_paths, tracked_paths)

        category_path_sets = tuple(
            set(paths)
            for paths in outcome_paths_by_category.values()
        )
        self.assertTrue(
            all(
                category_path_sets[index].isdisjoint(
                    category_path_sets[other_index]
                )
                for index in range(len(category_path_sets))
                for other_index in range(index + 1, len(category_path_sets))
            )
        )
        self.assertEqual(
            len(classified_paths),
            len(set(classified_paths)),
        )
        self.assertEqual(
            set(classified_paths),
            set(tracked_paths),
        )

    def test_production_path_set_matches_git_ls_files_exactly(
        self,
    ):
        service, _result = self._audit_repository()

        completed_process = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=self.project_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        expected_paths = tuple(
            path_bytes.decode(
                "utf-8",
                errors="surrogateescape",
            )
            for path_bytes in completed_process.stdout.split(b"\0")
            if path_bytes
        )

        self.assertEqual(
            service.get_tracked_paths(),
            expected_paths,
        )

    def test_default_exceptions_are_narrow_and_documented(
        self,
    ):
        _service, result = self._audit_repository()

        self.assertGreater(
            len(result["applied_exceptions"]),
            0,
        )

        for exception in result["applied_exceptions"]:
            self.assertTrue(exception["path"])
            self.assertTrue(exception["line"])
            self.assertIn(
                exception["finding_type"],
                {
                    "norwegian_character",
                    "norwegian_vocabulary",
                    "controlled_terminology",
                },
            )
            self.assertTrue(exception["reason"])


if __name__ == "__main__":
    unittest.main()
