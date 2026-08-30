from pathlib import Path
from tempfile import TemporaryDirectory
import inspect
import unittest
from unittest.mock import patch

import subprocess

from application.services import (
    repository_language_audit_service as audit_service_module,
)
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

        self.tracked_paths = set()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_text(
        self,
        relative_path,
        content,
        *,
        tracked=True,
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

        if tracked:
            self.tracked_paths.add(
                Path(relative_path).as_posix()
            )

        return file_path

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
                    "finding_type": (
                        "norwegian_vocabulary"
                    ),
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
                tracked=False,
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

        self.tracked_paths.add(
            "application/static/image.png"
        )

        findings = self._audit()

        self.assertEqual(
            findings,
            [],
        )

    def test_unknown_text_extension_is_audited(
        self,
    ):
        self._write_text(
            "application/static/generated.map",
            "Innstillinger\n",
        )

        findings = self._audit()

        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0]["path"],
            "application/static/generated.map",
        )

    def test_exact_intentional_fixture_is_not_reported(
        self,
    ):
        fixture_line = 'MESSAGE = "Programmet avsluttes."'

        self._write_text(
            "tests/fixtures/legacy_norwegian.txt",
            fixture_line + "\n",
        )

        findings = self._audit(
            intentional_exceptions=(
                {
                    "path": (
                        "tests/fixtures/"
                        "legacy_norwegian.txt"
                    ),
                    "line": fixture_line,
                    "finding_type": (
                        "norwegian_vocabulary"
                    ),
                    "reason": (
                        "Deliberate detector fixture."
                    ),
                },
            ),
        )

        self.assertEqual(
            findings,
            [],
        )

    def test_exact_intentional_line_is_not_reported(
        self,
    ):
        fixture_line = 'VALUE = "Ingen oversettelse"'

        self._write_text(
            "tests/test_encoding_fixture.py",
            fixture_line + "\n",
        )

        findings = self._audit(
            intentional_exceptions=(
                {
                    "path": "tests/test_encoding_fixture.py",
                    "line": fixture_line,
                    "finding_type": (
                        "norwegian_vocabulary"
                    ),
                    "reason": (
                        "Deliberate detector fixture."
                    ),
                },
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

        findings = self._audit(
            intentional_exceptions=(
                {
                    "path": "tests/test_unicode_export.py",
                    "line": 'PERSON_NAME = "Ægir Export"',
                    "finding_type": "norwegian_character",
                    "reason": "Intentional Person-name fixture.",
                },
                {
                    "path": "tests/test_unicode_export.py",
                    "line": 'SECOND_NAME = "Bjørn"',
                    "finding_type": "norwegian_character",
                    "reason": "Intentional Person-name fixture.",
                },
            ),
        )

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


class RepositoryLanguageAuditTrackedContractTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(
            self.temporary_directory.name
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_bytes(
        self,
        relative_path,
        content,
    ):
        file_path = self.project_root / relative_path
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        file_path.write_bytes(content)
        return file_path

    def _write_text(
        self,
        relative_path,
        content,
        encoding="utf-8",
    ):
        return self._write_bytes(
            relative_path,
            content.encode(encoding),
        )

    def _audit_repository(
        self,
        tracked_paths,
        **kwargs,
    ):
        parameters = inspect.signature(
            RepositoryLanguageAuditService
        ).parameters

        self.assertIn(
            "tracked_paths",
            parameters,
            "The service must accept an explicit tracked path set.",
        )

        service = RepositoryLanguageAuditService(
            project_root=self.project_root,
            tracked_paths=tracked_paths,
            **kwargs,
        )

        audit_repository = getattr(
            service,
            "audit_repository",
            None,
        )

        self.assertIsNotNone(
            audit_repository,
            "The service must expose explicit tracked-file outcomes.",
        )

        return audit_repository()

    def test_git_enumeration_is_nul_safe(
        self,
    ):
        completed_process = subprocess.CompletedProcess(
            args=["git", "ls-files", "-z"],
            returncode=0,
            stdout=(
                b".gitignore\0"
                b"docs/path with spaces.txt\0"
                b"tests/\xc3\x86gir.py\0"
            ),
            stderr=b"",
        )

        with patch.object(
            audit_service_module,
            "subprocess",
            create=True,
        ) as subprocess_module:
            subprocess_module.run.return_value = (
                completed_process
            )
            service = RepositoryLanguageAuditService(
                project_root=self.project_root,
            )

            get_tracked_paths = getattr(
                service,
                "get_tracked_paths",
                None,
            )

            self.assertIsNotNone(
                get_tracked_paths,
            )

            tracked_paths = get_tracked_paths()

        self.assertEqual(
            tracked_paths,
            (
                ".gitignore",
                "docs/path with spaces.txt",
                "tests/Ægir.py",
            ),
        )

        subprocess_module.run.assert_called_once()
        command = subprocess_module.run.call_args.args[0]
        self.assertEqual(
            command,
            ["git", "ls-files", "-z"],
        )
        self.assertFalse(
            subprocess_module.run.call_args.kwargs.get(
                "shell",
                False,
            )
        )

    def test_only_supplied_tracked_paths_are_audited(
        self,
    ):
        self._write_text(
            "tracked.txt",
            "English text.\n",
        )
        self._write_text(
            "untracked.txt",
            "Programmet kunne ikke starte.\n",
        )

        result = self._audit_repository(
            ("tracked.txt",),
        )

        self.assertEqual(
            result["tracked_paths"],
            ("tracked.txt",),
        )
        self.assertEqual(
            result["findings"],
            [],
        )

    def test_language_bearing_special_files_are_audited(
        self,
    ):
        tracked_paths = (
            ".gitignore",
            "application/static/status.svg",
            "LeagueMasteryTracker.spec",
            "tools/audit",
        )

        for relative_path in tracked_paths:
            self._write_text(
                relative_path,
                "Programmet kunne ikke starte.\n",
            )

        result = self._audit_repository(
            tracked_paths,
        )

        self.assertEqual(
            {
                finding["path"]
                for finding in result["findings"]
            },
            set(tracked_paths),
        )

    def test_supported_unicode_encodings_are_decoded(
        self,
    ):
        encoded_files = {
            "utf8.txt": (
                "Programmet avsluttes.\n".encode("utf-8")
            ),
            "utf8_bom.txt": (
                b"\xef\xbb\xbf"
                + "Programmet avsluttes.\n".encode("utf-8")
            ),
            "utf16_le.txt": (
                b"\xff\xfe"
                + "Programmet avsluttes.\n".encode("utf-16-le")
            ),
            "utf16_be.txt": (
                b"\xfe\xff"
                + "Programmet avsluttes.\n".encode("utf-16-be")
            ),
        }

        for relative_path, content in encoded_files.items():
            self._write_bytes(
                relative_path,
                content,
            )

        result = self._audit_repository(
            tuple(encoded_files),
        )

        self.assertEqual(
            {
                finding["path"]
                for finding in result["findings"]
            },
            set(encoded_files),
        )

        self.assertEqual(
            {
                outcome["encoding"]
                for outcome in result["outcomes"]
            },
            {
                "utf-8",
                "utf-8-sig",
                "utf-16-le",
                "utf-16-be",
            },
        )

    def test_malformed_encoding_is_a_controlled_audit_error(
        self,
    ):
        self._write_bytes(
            "broken.txt",
            b"\xff\xfe\x00",
        )

        result = self._audit_repository(
            ("broken.txt",),
        )

        self.assertEqual(
            result["outcomes"][0]["outcome"],
            "audit_error",
        )
        self.assertEqual(
            result["findings"][0]["path"],
            "broken.txt",
        )
        self.assertEqual(
            result["findings"][0]["category"],
            "audit_error",
        )

    def test_unsupported_text_encoding_is_a_controlled_audit_error(
        self,
    ):
        self._write_bytes(
            "legacy.txt",
            b"\x93Unsupported legacy text.\x94\n",
        )

        result = self._audit_repository(
            ("legacy.txt",),
        )

        self.assertEqual(
            result["outcomes"][0]["outcome"],
            "audit_error",
        )
        self.assertEqual(
            result["findings"][0]["path"],
            "legacy.txt",
        )

    def _assert_decodable_nul_is_audit_error(
        self,
        relative_path,
    ):
        self._write_bytes(
            relative_path,
            b'print("ok")\x00',
        )

        result = self._audit_repository(
            (relative_path,),
        )

        outcome = result["outcomes"][0]
        self.assertEqual(outcome["outcome"], "audit_error")
        self.assertNotEqual(
            outcome["outcome"],
            "intentional_binary_exclusion",
        )

        self.assertEqual(len(result["findings"]), 1)
        finding = result["findings"][0]
        self.assertEqual(finding["path"], relative_path)
        self.assertIn(
            "nul",
            finding["line"].casefold(),
        )

    def test_decodable_source_with_nul_is_audit_error(
        self,
    ):
        self._assert_decodable_nul_is_audit_error(
            "broken.py",
        )

    def test_decodable_text_with_nul_is_not_hidden_by_binary_suffix(
        self,
    ):
        self._assert_decodable_nul_is_audit_error(
            "broken.png",
        )

    def test_binary_asset_has_an_explicit_outcome(
        self,
    ):
        binary_files = {
            "application/static/image.png": (
                b"\x89PNG\r\n\x1a\n\x00\xff"
            ),
            "application/static/favicon.ico": (
                b"\x00\x00\x01\x00\x01\x00"
            ),
            "binary-with-text-suffix.txt": (
                b"\x89PNG\r\n\x1a\n\x00\xff"
            ),
        }

        for relative_path, content in binary_files.items():
            self._write_bytes(
                relative_path,
                content,
            )

        result = self._audit_repository(
            tuple(binary_files),
        )

        self.assertTrue(
            all(
                outcome["outcome"]
                == "intentional_binary_exclusion"
                for outcome in result["outcomes"]
            )
        )
        self.assertEqual(
            result["findings"],
            [],
        )

    def test_every_tracked_candidate_has_one_outcome(
        self,
    ):
        self._write_text(
            "one.txt",
            "English.\n",
        )
        self._write_bytes(
            "two.png",
            b"\x89PNG\r\n\x1a\n\x00",
        )

        result = self._audit_repository(
            (
                "one.txt",
                "two.png",
                "deleted.txt",
            ),
        )

        self.assertEqual(
            len(result["tracked_paths"]),
            3,
        )
        self.assertEqual(
            len(result["outcomes"]),
            3,
        )
        self.assertEqual(
            {
                outcome["outcome"]
                for outcome in result["outcomes"]
            },
            {
                "audited_text",
                "intentional_binary_exclusion",
                "audit_error",
            },
        )

    def test_tracked_non_file_has_a_controlled_outcome(
        self,
    ):
        (self.project_root / "vendor" / "submodule").mkdir(
            parents=True,
        )

        result = self._audit_repository(
            ("vendor/submodule",),
        )

        self.assertEqual(
            result["outcomes"][0]["outcome"],
            "controlled_non_language_exclusion",
        )
        self.assertEqual(result["findings"], [])

    def test_exact_fixture_exception_does_not_hide_adjacent_prose(
        self,
    ):
        allowed_line = 'PERSON_NAME = "Bjørn"'
        self._write_text(
            "tests/test_fixture.py",
            (
                allowed_line
                + "\n"
                + allowed_line
                + "  # Programmet avsluttes.\n"
            ),
        )

        result = self._audit_repository(
            ("tests/test_fixture.py",),
            intentional_exceptions=(
                {
                    "path": "tests/test_fixture.py",
                    "line": allowed_line,
                    "finding_type": "norwegian_character",
                    "reason": "Intentional Person-name fixture.",
                },
            ),
        )

        self.assertEqual(
            len(result["findings"]),
            1,
        )
        self.assertEqual(
            result["findings"][0]["line_number"],
            2,
        )
        self.assertIn(
            "programmet",
            result["findings"][0]["matched_terms"],
        )

    def test_controlled_terminology_is_detected_in_prose(
        self,
    ):
        phrases = (
            "player",
            "user account",
            "mastery score",
            "Synchronize mastery",
            "Champion Mastery points",
            "Missing champion data",
            "Reference update",
            "reference dataset",
            "champion database",
            "database import",
            "backup import",
            "last sync timestamp",
        )

        self._write_text(
            "README.md",
            "\n".join(
                f"Obsolete prose: {phrase}."
                for phrase in phrases
            )
            + "\n",
        )

        result = self._audit_repository(
            ("README.md",),
        )

        self.assertEqual(
            {
                term.casefold()
                for finding in result["findings"]
                for term in finding["matched_terms"]
            },
            {
                phrase.casefold()
                for phrase in phrases
            },
        )
        self.assertTrue(
            all(
                finding["finding_type"]
                == "controlled_terminology"
                for finding in result["findings"]
            )
        )

    def test_technical_and_protocol_values_are_not_reported(
        self,
    ):
        self._write_text(
            "application/services/example.py",
            (
                "player_id = 7\n"
                "player = Person()\n"
                "player.display_name = 'Example'\n"
                "last_sync = None\n"
                "champion_mastery = {}\n"
                "REFERENCE_UPDATE_ROUTE = "
                "'/dashboard/reference-data/refresh'\n"
                "MUTEX = "
                "'Local\\\\LeagueMasteryTracker.ApplicationInstance'\n"
                "THREAD = 'LeagueMasteryTrackerTabMonitor'\n"
                "DPAPI = 'LeagueMasteryTracker:RiotApiKey:v1'\n"
                "# The champion database table is migrated by SQLite.\n"
            ),
        )

        result = self._audit_repository(
            ("application/services/example.py",),
        )

        self.assertEqual(
            result["findings"],
            [],
        )


if __name__ == "__main__":
    unittest.main()