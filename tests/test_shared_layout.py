import re
import unittest
from pathlib import Path

from flask import Flask, render_template

from application.config import Config
from application.routes.persons import persons_bp


class SharedLayoutTests(
    unittest.TestCase
):
    """
    Verify the shared Step 10 template architecture.

    These tests protect presentation contracts without depending on
    individual route fixtures or database state.
    """

    PROJECT_ROOT = Path(
        __file__
    ).resolve().parents[1]

    TEMPLATE_DIR = (
        PROJECT_ROOT
        / "application"
        / "templates"
    )

    STATIC_DIR = (
        PROJECT_ROOT
        / "application"
        / "static"
    )

    SHARED_TEMPLATE_NAMES = (
        "home.html",
        "persons.html",
        "person_detail.html",
        "settings.html",
        "json_export.html",
        "json_import.html",
        "database_restore.html",
        "missing_champions.html",
    )

    PRODUCT_NAME = (
        "League Mastery Tracker"
    )

    RELEASE_NAME = (
        "League Mastery Tracker 2.0"
    )

    APPLICATION_VERSION = (
        "2.0.0"
    )

    WINDOWS_EXECUTABLE_NAME = (
        "LeagueMasteryTracker.exe"
    )

    @classmethod
    def _read_template(
        cls,
        file_name,
    ):
        return (
            cls.TEMPLATE_DIR
            / file_name
        ).read_text(
            encoding="utf-8"
        )

    @classmethod
    def _read_static_file(
        cls,
        file_name,
    ):
        return (
            cls.STATIC_DIR
            / file_name
        ).read_text(
            encoding="utf-8"
        )

    @classmethod
    def _get_stylesheet_rule(
        cls,
        selector,
    ):
        content = cls._read_static_file(
            "app.css"
        )

        content_without_comments = re.sub(
            r"/\*.*?\*/",
            "",
            content,
            flags=re.DOTALL,
        )

        matching_declarations = []

        for match in re.finditer(
            r"(?P<selectors>[^{}]+)"
            r"\{(?P<declarations>[^{}]*)\}",
            content_without_comments,
            flags=re.DOTALL,
        ):
            selectors = {
                " ".join(
                    candidate.split()
                )
                for candidate in (
                    match.group(
                        "selectors"
                    ).split(",")
                )
            }

            if selector in selectors:
                matching_declarations.append(
                    match.group(
                        "declarations"
                    )
                )

        if not matching_declarations:
            return None

        return "\n".join(
            matching_declarations
        )

    @classmethod
    def _get_stylesheet_root_tokens(cls):
        root_declarations = (
            cls._get_stylesheet_rule(
                ":root"
            )
        )

        if root_declarations is None:
            return {}

        return {
            match.group("name"): " ".join(
                match.group("value").split()
            )
            for match in re.finditer(
                r"(?P<name>--[a-z0-9-]+)"
                r"\s*:\s*"
                r"(?P<value>.*?)\s*;",
                root_declarations,
                flags=re.DOTALL,
            )
        }

    @classmethod
    def _render_persons_page(
        cls,
    ):
        app = Flask(
            __name__,
            template_folder=str(
                cls.TEMPLATE_DIR
            ),
        )

        app.config.from_object(
            Config
        )

        app.register_blueprint(
            persons_bp
        )

        app.jinja_env.globals[
            "csrf_token"
        ] = lambda: "shared-layout-test-token"

        with app.test_request_context(
            "/persons"
        ):
            return render_template(
                "persons.html",
                persons=[],
            )

    def test_application_identity_configuration_is_canonical(self):
        """
        Runtime configuration should expose one authoritative identity.
        """

        self.assertEqual(
            Config.PRODUCT_NAME,
            self.PRODUCT_NAME,
        )

        self.assertEqual(
            Config.RELEASE_NAME,
            self.RELEASE_NAME,
        )

        self.assertEqual(
            Config.APPLICATION_VERSION,
            self.APPLICATION_VERSION,
        )

        self.assertEqual(
            Config.WINDOWS_EXECUTABLE_NAME,
            self.WINDOWS_EXECUTABLE_NAME,
        )

    def test_application_version_uses_three_part_semantic_version(self):
        """
        The product release version should use major.minor.patch form.
        """

        self.assertRegex(
            Config.APPLICATION_VERSION,
            r"\A\d+\.\d+\.\d+\Z",
        )

    def test_rendered_shared_page_identifies_release_and_version(self):
        """
        A normal shared page should render canonical release metadata.
        """

        normalized_html = " ".join(
            self._render_persons_page().split()
        )

        self.assertIn(
            (
                "<title> Persons · "
                f"{self.PRODUCT_NAME} </title>"
            ),
            normalized_html,
        )

        self.assertIn(
            self.RELEASE_NAME,
            normalized_html,
        )

        self.assertIn(
            self.APPLICATION_VERSION,
            normalized_html,
        )

    def test_base_template_reads_identity_from_configuration(self):
        """
        The shared template must not define a second release source.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            'config["PRODUCT_NAME"]',
            content,
        )

        self.assertIn(
            'config["RELEASE_NAME"]',
            content,
        )

        self.assertIn(
            'config["APPLICATION_VERSION"]',
            content,
        )

        self.assertNotIn(
            self.APPLICATION_VERSION,
            content,
        )

    def test_base_template_exists(self):
        """
        The application should provide one shared base template.
        """

        self.assertTrue(
            (
                self.TEMPLATE_DIR
                / "base.html"
            ).is_file()
        )

    def test_shared_pages_extend_base_template(self):
        """
        Normal application pages should use the shared layout.
        """

        for template_name in (
            self.SHARED_TEMPLATE_NAMES
        ):
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                self.assertIn(
                    '{% extends "base.html" %}',
                    content,
                )

    def test_shared_pages_define_product_title(self):
        """
        Every shared page title should identify the product.
        """

        for template_name in (
            self.SHARED_TEMPLATE_NAMES
        ):
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                self.assertIn(
                    "{% block title %}",
                    content,
                )

                self.assertIn(
                    self.PRODUCT_NAME,
                    content,
                )

    def test_base_template_declares_english_document(self):
        """
        The shared document language should be English.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            '<html lang="en">',
            content,
        )

    def test_base_template_declares_utf8(self):
        """
        The shared document should explicitly use UTF-8.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            '<meta charset="utf-8">',
            content,
        )

    def test_base_template_has_viewport_metadata(self):
        """
        The shared layout should support responsive rendering.
        """

        content = self._read_template(
            "base.html"
        )

        normalized_content = " ".join(
            content.split()
        )

        self.assertIn(
            (
                'name="viewport" '
                'content="width=device-width, '
                'initial-scale=1"'
            ),
            normalized_content,
        )

    def test_base_template_uses_local_stylesheet(self):
        """
        The shared layout should load the local design system.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            "url_for('static', filename='app.css')",
            content,
        )

    def test_base_template_has_skip_link(self):
        """
        Keyboard users should be able to skip navigation.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            'class="skip-link"',
            content,
        )

        self.assertIn(
            'href="#main-content"',
            content,
        )

        self.assertIn(
            "Skip to main content",
            content,
        )

    def test_base_template_has_main_landmark(self):
        """
        The shared layout should provide one explicit main landmark.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            "<main",
            content,
        )

        self.assertIn(
            'id="main-content"',
            content,
        )

    def test_base_template_has_shared_navigation(self):
        """
        Shared navigation should expose the core destinations.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            "<nav",
            content,
        )

        self.assertIn(
            'aria-label="Main navigation"',
            content,
        )

        self.assertIn(
            "Dashboard",
            content,
        )

        self.assertIn(
            "Persons",
            content,
        )

        self.assertIn(
            "Settings",
            content,
        )

    def test_base_template_has_product_identity(self):
        """
        The shared header should identify League Mastery Tracker.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            'config["RELEASE_NAME"]',
            content,
        )

        self.assertIn(
            "LMT",
            content,
        )

    def test_base_template_renders_flash_messages(self):
        """
        Flash messages should remain available after layout reuse.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            "get_flashed_messages",
            content,
        )

        self.assertIn(
            "with_categories=true",
            content,
        )

        self.assertIn(
            'class="flash flash-{{ category }}"',
            content,
        )

        self.assertIn(
            'data-category="{{ category }}"',
            content,
        )

    def test_base_template_distinguishes_error_messages(self):
        """
        Error flash messages should use alert semantics.
        """

        content = self._read_template(
            "base.html"
        )

        normalized_content = " ".join(
            content.split()
        )

        self.assertIn(
            (
                '{% if category == "error" %} '
                'role="alert"'
            ),
            normalized_content,
        )

        self.assertIn(
            'role="status"',
            content,
        )

    def test_base_template_has_footer(self):
        """
        Shared pages should provide a common footer.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            "<footer",
            content,
        )

        self.assertIn(
            'class="site-footer"',
            content,
        )

    def test_base_template_supports_page_specific_content(self):
        """
        The layout should expose controlled extension points.
        """

        content = self._read_template(
            "base.html"
        )

        self.assertIn(
            "{% block head %}",
            content,
        )

        self.assertIn(
            "{% block content %}",
            content,
        )

        self.assertIn(
            "{% block scripts %}",
            content,
        )

    def test_shutdown_page_remains_standalone(self):
        """
        Controlled shutdown should not depend on shared navigation.

        The server may already be unavailable while this document
        remains open in the browser.
        """

        content = self._read_template(
            "application_shutdown.html"
        )

        self.assertNotIn(
            '{% extends "base.html" %}',
            content,
        )

        self.assertIn(
            '<html lang="en">',
            content,
        )

        self.assertIn(
            self.PRODUCT_NAME,
            content,
        )

        self.assertIn(
            "url_for('static', filename='app.css')",
            content,
        )

    def test_shutdown_page_has_viewport_metadata(self):
        """
        The standalone shutdown page should remain responsive.
        """

        content = self._read_template(
            "application_shutdown.html"
        )

        normalized_content = " ".join(
            content.split()
        )

        self.assertIn(
            (
                'name="viewport" '
                'content="width=device-width, '
                'initial-scale=1"'
            ),
            normalized_content,
        )

    def test_local_stylesheet_exists(self):
        """
        The shared design system must be bundled locally.
        """

        self.assertTrue(
            (
                self.STATIC_DIR
                / "app.css"
            ).is_file()
        )

    def test_stylesheet_does_not_import_external_assets(self):
        """
        Normal presentation should not depend on remote CSS assets.
        """

        content = self._read_static_file(
            "app.css"
        )

        lowered_content = (
            content.lower()
        )

        self.assertNotIn(
            "@import",
            lowered_content,
        )

        self.assertNotIn(
            "http://",
            lowered_content,
        )

        self.assertNotIn(
            "https://",
            lowered_content,
        )

    def test_stylesheet_declares_complete_design_token_families(self):
        """
        Shared visual values should have explicit semantic tokens.
        """

        tokens = (
            self._get_stylesheet_root_tokens()
        )

        expected_tokens = {
            "--font-family-sans": (
                "system-ui, -apple-system, BlinkMacSystemFont, "
                '"Segoe UI", sans-serif'
            ),
            "--font-size-xs": "0.78rem",
            "--font-size-sm": "0.9rem",
            "--font-size-base": "1rem",
            "--font-size-lg": "1.1rem",
            "--font-weight-medium": "650",
            "--font-weight-semibold": "700",
            "--font-weight-bold": "800",
            "--color-link-hover": "#bfdbfe",
            "--color-on-action": "#ffffff",
            "--color-control-border-hover": "#64748b",
            "--color-row-hover": (
                "rgb(255 255 255 / 0.025)"
            ),
            "--color-header-surface": (
                "rgb(11 17 32 / 0.92)"
            ),
            "--focus-ring-width": "3px",
            "--focus-ring-offset": "3px",
            "--size-brand-mark": "2rem",
            "--size-champion-image": "2.75rem",
            "--size-button-min-height": "2.65rem",
            "--size-control-min-height": "2.75rem",
            "--text-width": "50rem",
            "--empty-state-width": "38rem",
            "--dialog-width": "32rem",
        }

        for token_name, expected_value in (
            expected_tokens.items()
        ):
            with self.subTest(
                token=token_name
            ):
                self.assertEqual(
                    tokens.get(
                        token_name
                    ),
                    expected_value,
                )

    def test_existing_selectors_consume_design_tokens(self):
        """
        Existing primitives should consume tokens without new markup.
        """

        expected_consumption = (
            (
                "body",
                "--font-family-sans",
            ),
            (
                "body",
                "--font-size-base",
            ),
            (
                "h3",
                "--font-size-lg",
            ),
            (
                ".badge",
                "--font-size-xs",
            ),
            (
                ".form-help",
                "--font-size-sm",
            ),
            (
                "label",
                "--font-weight-medium",
            ),
            (
                ".site-brand",
                "--font-weight-semibold",
            ),
            (
                ".site-brand__mark",
                "--font-weight-bold",
            ),
            (
                "a:hover",
                "--color-link-hover",
            ),
            (
                "button",
                "--color-on-action",
            ),
            (
                "input:hover",
                "--color-control-border-hover",
            ),
            (
                "tbody tr:hover",
                "--color-row-hover",
            ),
            (
                ".site-header",
                "--color-header-surface",
            ),
            (
                "a:focus-visible",
                "--focus-ring-width",
            ),
            (
                "a:focus-visible",
                "--focus-ring-offset",
            ),
            (
                ".site-brand__mark",
                "--size-brand-mark",
            ),
            (
                ".champion-image",
                "--size-champion-image",
            ),
            (
                "button",
                "--size-button-min-height",
            ),
            (
                'input[type="text"]',
                "--size-control-min-height",
            ),
            (
                ".page-header__description",
                "--text-width",
            ),
            (
                ".empty-state p",
                "--empty-state-width",
            ),
            (
                ".shutdown-card",
                "--dialog-width",
            ),
        )

        for selector, token_name in (
            expected_consumption
        ):
            with self.subTest(
                selector=selector,
                token=token_name,
            ):
                declarations = (
                    self._get_stylesheet_rule(
                        selector
                    )
                )

                self.assertIsNotNone(
                    declarations
                )

                self.assertIn(
                    f"var({token_name})",
                    declarations,
                )

    def test_stylesheet_preserves_shared_visual_primitives(self):
        """
        The token refactor must retain each shared primitive family.
        """

        required_selectors = (
            "button",
            ".button",
            'input[type="text"]',
            "select",
            "textarea",
            ".card",
            ".badge",
            "table",
            ".main-nav",
            ".flash",
            ".notice",
        )

        for selector in required_selectors:
            with self.subTest(
                selector=selector
            ):
                self.assertIsNotNone(
                    self._get_stylesheet_rule(
                        selector
                    )
                )

    def test_stylesheet_has_visible_focus_contract(self):
        """
        Interactive controls should have visible keyboard focus.
        """

        content = self._read_static_file(
            "app.css"
        )

        self.assertIn(
            ":focus-visible",
            content,
        )

        self.assertIn(
            "--color-focus:",
            content,
        )

    def test_stylesheet_has_responsive_contract(self):
        """
        The design system should include narrow-window behavior.
        """

        content = self._read_static_file(
            "app.css"
        )

        self.assertIn(
            "@media (max-width:",
            content,
        )

        self.assertIn(
            ".table-scroll",
            content,
        )

    def test_stylesheet_respects_reduced_motion(self):
        """
        The local design system should honor reduced-motion settings.
        """

        content = self._read_static_file(
            "app.css"
        )

        self.assertIn(
            (
                "@media "
                "(prefers-reduced-motion: reduce)"
            ),
            content,
        )


if __name__ == "__main__":
    unittest.main()
