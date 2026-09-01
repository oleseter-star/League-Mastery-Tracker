from pathlib import Path
import re
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

    def test_close_fallback_explanation_announces_as_status(
        self,
    ):
        """
        The revealed close explanation should be announced without
        placing the close button inside a live region.
        """

        fallback_container = re.search(
            r"<div(?P<attributes>[^>]*)>"
            r"(?P<content>.*?)"
            r"</div>",
            self.template_content,
            flags=re.DOTALL,
        )
        fallback_section = re.search(
            r"<section(?P<attributes>[^>]*)>.*?"
            r"<div[^>]*id=\"close-fallback\"",
            self.template_content,
            flags=re.DOTALL,
        )
        fallback_main = re.search(
            r"<main(?P<attributes>[^>]*)>.*?"
            r"<section[^>]*>.*?"
            r"<div[^>]*id=\"close-fallback\"",
            self.template_content,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(
            fallback_container,
        )
        self.assertIsNotNone(fallback_section)
        self.assertIsNotNone(fallback_main)

        container_attributes = (
            fallback_container.group(
                "attributes"
            )
        )
        container_content = (
            fallback_container.group(
                "content"
            )
        )

        self.assertIn(
            'id="close-fallback"',
            container_attributes,
        )
        self.assertRegex(
            container_attributes,
            r"\bhidden\b",
        )
        self.assertNotRegex(
            container_attributes,
            r"\b(?:role|aria-live|aria-atomic)\s*=",
        )
        self.assertNotRegex(
            fallback_section.group("attributes"),
            r"\b(?:role|aria-live|aria-atomic)\s*=",
        )
        self.assertNotRegex(
            fallback_main.group("attributes"),
            r"\b(?:role|aria-live|aria-atomic)\s*=",
        )

        explanation = re.search(
            r"<p(?P<attributes>[^>]*)>"
            r"(?P<content>.*?)"
            r"</p>",
            container_content,
            flags=re.DOTALL,
        )
        close_button = re.search(
            r"<button(?P<attributes>[^>]*)>"
            r"(?P<content>.*?)"
            r"</button>",
            container_content,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(explanation)
        self.assertIsNotNone(close_button)
        self.assertEqual(
            " ".join(
                explanation.group("content").split()
            ),
            (
                "The application has shut down. "
                "The browser did not allow this tab "
                "to close automatically."
            ),
        )
        self.assertEqual(
            re.findall(
                r'\brole\s*=\s*"([^"]+)"',
                explanation.group("attributes"),
            ),
            ["status"],
        )
        self.assertNotIn(
            'role="alert"',
            explanation.group("attributes"),
        )
        self.assertNotRegex(
            explanation.group("content"),
            r"<\s*(?:a|button|input|select|textarea)\b"
            r"|\b(?:role|tabindex)\s*=",
        )
        self.assertIn(
            'id="close-tab-button"',
            close_button.group("attributes"),
        )
        self.assertEqual(
            " ".join(
                close_button.group("content").split()
            ),
            "Close tab",
        )
        self.assertLess(
            explanation.end(),
            close_button.start(),
        )
        self.assertNotRegex(
            close_button.group("attributes"),
            r"\b(?:role|aria-live|aria-atomic)\s*=",
        )
        self.assertEqual(
            re.findall(
                r'\brole\s*=\s*"([^"]+)"',
                container_content,
            ),
            ["status"],
        )
        self.assertNotRegex(
            container_content,
            r"\b(?:aria-live|aria-atomic)\s*=",
        )
        fallback_lookup = re.search(
            r"\b(?:const|let|var)\s+"
            r"(?P<variable>[A-Za-z_$][\w$]*)\s*"
            r"=\s*\(\s*"
            r"document\.getElementById\(\s*"
            r"(?P<quote>[\"'])close-fallback(?P=quote)"
            r"\s*\)\s*\)\s*;",
            self.template_content,
            flags=re.DOTALL,
        )
        show_fallback = re.search(
            r"function\s+"
            r"(?P<function_name>showFallback)\s*\(\s*\)\s*"
            r"\{(?P<body>.*?)^[ \t]{12}\}",
            self.template_content,
            flags=(
                re.DOTALL
                | re.MULTILINE
            ),
        )

        self.assertIsNotNone(fallback_lookup)
        self.assertIsNotNone(show_fallback)

        fallback_variable = fallback_lookup.group(
            "variable"
        )
        show_fallback_name = show_fallback.group(
            "function_name"
        )

        self.assertRegex(
            show_fallback.group("body"),
            rf"\b{re.escape(fallback_variable)}"
            r"\.hidden\s*=\s*false\s*;",
        )
        self.assertRegex(
            self.template_content,
            rf"window\.setTimeout\(\s*"
            rf"{re.escape(show_fallback_name)}\s*,\s*"
            r"300\s*\)",
        )
        self.assertRegex(
            self.template_content,
            rf"window\.setTimeout\(\s*"
            rf"{re.escape(show_fallback_name)}\s*,\s*"
            r"1200\s*\)",
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