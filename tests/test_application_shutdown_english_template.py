from pathlib import Path
import unittest

from application.services.repository_language_audit_service import (
    RepositoryLanguageAuditService,
)


class ApplicationShutdownEnglishTemplateTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.project_root = (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )

        cls.template_path = (
            cls.project_root
            / "application"
            / "templates"
            / "application_shutdown.html"
        )

        cls.template_content = (
            cls.template_path.read_text(
                encoding="utf-8"
            )
        )

        cls.normalized_content = " ".join(
            cls.template_content.split()
        )

    def test_template_uses_english_document_language(
        self,
    ):
        self.assertIn(
            '<html lang="en">',
            self.template_content,
        )

        self.assertNotIn(
            '<html lang="nb">',
            self.template_content,
        )

    def test_dynamic_page_title_is_preserved(
        self,
    ):
        self.assertIn(
            (
                "{{ page_title }} "
                "– League Mastery Tracker"
            ),
            self.normalized_content,
        )

    def test_dynamic_heading_and_message_are_preserved(
        self,
    ):
        self.assertIn(
            "<h1>{{ heading }}</h1>",
            self.normalized_content,
        )

        self.assertIn(
            "<p>{{ message }}</p>",
            self.normalized_content,
        )

    def test_close_fallback_is_written_in_english(
        self,
    ):
        self.assertIn(
            (
                "The application has shut down. "
                "The browser did not allow this tab "
                "to close automatically."
            ),
            self.normalized_content,
        )

        self.assertIn(
            "Close tab",
            self.normalized_content,
        )

        self.assertIn(
            (
                "If the tab remains open, "
                "you can close it manually."
            ),
            self.normalized_content,
        )

    def test_close_fallback_element_contract_is_preserved(
        self,
    ):
        self.assertIn(
            'id="close-fallback"',
            self.template_content,
        )

        self.assertIn(
            'id="close-tab-button"',
            self.template_content,
        )

        self.assertIn(
            "hidden",
            self.template_content,
        )

    def test_automatic_close_script_is_preserved(
        self,
    ):
        self.assertIn(
            "window.close();",
            self.template_content,
        )

        self.assertIn(
            "function attemptToCloseTab()",
            self.template_content,
        )

        self.assertIn(
            "function showFallback()",
            self.template_content,
        )

        self.assertIn(
            "closeButton.addEventListener",
            self.template_content,
        )

        self.assertIn(
            'window.addEventListener( "load"',
            self.normalized_content,
        )

        self.assertIn(
            "350",
            self.template_content,
        )

        self.assertIn(
            "1200",
            self.template_content,
        )

    def test_template_has_no_external_dependencies(
        self,
    ):
        normalized_content = (
            self.template_content.casefold()
        )

        self.assertNotIn(
            "http://",
            normalized_content,
        )

        self.assertNotIn(
            "https://",
            normalized_content,
        )

        self.assertNotIn(
            "//cdn.",
            normalized_content,
        )

    def test_template_contains_no_detected_norwegian_prose(
        self,
    ):
        findings = (
            RepositoryLanguageAuditService(
                project_root=(
                    self.project_root
                )
            )
            .audit()
        )

        shutdown_findings = [
            finding
            for finding in findings
            if finding["path"]
            == (
                "application/templates/"
                "application_shutdown.html"
            )
        ]

        self.assertEqual(
            shutdown_findings,
            [],
        )


if __name__ == "__main__":
    unittest.main()