import re
import unittest
from pathlib import Path

from flask import Blueprint, Flask, render_template

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

    SHARED_PAGE_EXPECTATIONS = {
        "home.html": {
            "title": "Dashboard",
            "eyebrow": "League Mastery Tracker",
            "heading": "Dashboard",
            "description": (
                "Review persons, synchronize Champion Mastery, "
                "and check the local champion reference data used "
                "by the application."
            ),
            "actions": (
                ("/persons", "Manage persons"),
                ("/settings", "Settings"),
            ),
        },
        "persons.html": {
            "title": "Persons",
            "eyebrow": "Management",
            "heading": "Persons",
            "description": (
                "Create local persons and open them to manage "
                "connected Riot accounts and Champion Mastery."
            ),
            "actions": (),
        },
        "person_detail.html": {
            "title": "Shared Layout Person",
            "eyebrow": "Person",
            "heading": "Shared Layout Person",
            "description": (
                "Review connected Riot accounts and combined "
                "Champion Mastery for this person."
            ),
            "actions": (
                ("/persons", "All persons"),
            ),
        },
        "settings.html": {
            "title": "Settings",
            "eyebrow": "Administration",
            "heading": "Settings",
            "description": (
                "Manage the Riot API key, portable data, database "
                "backups, application storage, and controlled shutdown."
            ),
            "actions": (
                ("/", "Back to Dashboard"),
            ),
        },
        "json_export.html": {
            "title": "JSON export",
            "eyebrow": "Portable data",
            "heading": "JSON export",
            "description": (
                "Create one portable JSON file containing the "
                "application data."
            ),
            "actions": (
                ("/settings", "Back to Settings"),
            ),
        },
        "json_import.html": {
            "title": "JSON import",
            "eyebrow": "Portable data",
            "heading": "Import portable JSON data",
            "description": (
                "Validate and preview a League Mastery Tracker export "
                "before any database changes are allowed."
            ),
            "actions": (
                ("/settings", "Back to Settings"),
            ),
        },
        "database_restore.html": {
            "title": "Database restore",
            "eyebrow": "Database backup",
            "heading": "Database restore",
            "description": (
                "Restore the application database from an "
                "internally created backup."
            ),
            "actions": (
                ("/settings", "Back to Settings"),
            ),
        },
        "missing_champions.html": {
            "title": "Missing metadata",
            "eyebrow": "Reference data",
            "heading": "Missing metadata",
            "description": (
                "Add names for champions that are not yet included "
                "in the local Data Dragon reference data."
            ),
            "actions": (
                ("/", "Back to Dashboard"),
            ),
        },
    }

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

    @staticmethod
    def _parse_hex_color(value):
        normalized_value = value.lstrip("#")

        return tuple(
            int(
                normalized_value[index:index + 2],
                16,
            )
            for index in range(0, 6, 2)
        )

    @staticmethod
    def _relative_luminance(color):
        def linearize(channel):
            normalized_channel = channel / 255

            if normalized_channel <= 0.04045:
                return normalized_channel / 12.92

            return (
                (normalized_channel + 0.055) / 1.055
            ) ** 2.4

        red, green, blue = (
            linearize(channel)
            for channel in color
        )

        return (
            0.2126 * red
            + 0.7152 * green
            + 0.0722 * blue
        )

    @classmethod
    def _contrast_ratio(
        cls,
        first_color,
        second_color,
    ):
        first_luminance = cls._relative_luminance(
            first_color
        )
        second_luminance = cls._relative_luminance(
            second_color
        )

        lighter, darker = sorted(
            (first_luminance, second_luminance),
            reverse=True,
        )

        return (lighter + 0.05) / (darker + 0.05)

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

    def _render_navigation_page(
        self,
        blueprint_name,
    ):
        app = Flask(
            __name__,
            template_folder=str(
                self.TEMPLATE_DIR
            ),
        )

        app.config.from_object(
            Config
        )

        blueprint = Blueprint(
            blueprint_name,
            __name__,
        )

        route_path = (
            f"/{blueprint_name}-navigation-test"
        )

        @blueprint.get(route_path)
        def navigation_page():
            return render_template(
                "base.html"
            )

        app.register_blueprint(
            blueprint
        )

        response = app.test_client().get(
            route_path
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        return response.get_data(
            as_text=True
        )

    @classmethod
    def _render_shared_page(
        cls,
        template_name,
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

        app.jinja_env.globals[
            "csrf_token"
        ] = lambda: "shared-layout-test-token"

        app.jinja_env.globals[
            "url_for"
        ] = lambda endpoint, **values: (
            f"/{endpoint}"
        )

        context = {
            "persons": [],
            "person_count": 0,
            "champion_reference_status": {},
            "person": {
                "display_name": (
                    "Shared Layout Person"
                ),
                "id": 1,
            },
            "total_mastery": 0,
            "riot_accounts": [],
            "champions": [],
            "move_target_persons": [],
            "platform_regions": [],
            "api_key_status": {},
            "backup_status": {},
            "startup_backup_error": None,
            "riot_legal_notice": {
                "boilerplate": "Legal boilerplate",
                "asset_source": "Asset source",
                "asset_explanation": (
                    "Asset explanation"
                ),
                "policy_url": "/policy",
                "data_dragon_url": (
                    "/data-dragon"
                ),
            },
            "export_error": "Export unavailable",
            "export_summary": None,
            "prepared_import": None,
            "max_file_size_mib": 1,
            "startup_restore_result": None,
            "pending_restore_error": None,
            "pending_restore": None,
            "restore_candidates": [],
            "restore_candidates_error": None,
        }

        with app.test_request_context("/"):
            return render_template(
                template_name,
                **context,
            )

    def _get_primary_navigation_links(
        self,
        html,
    ):
        navigation_match = re.search(
            r'<nav\b[^>]*aria-label="Main navigation"[^>]*>'
            r'(?P<content>.*?)</nav>',
            html,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(
            navigation_match,
        )

        links = []

        for match in re.finditer(
                r'<a\b(?P<attributes>[^>]*)>'
                r'(?P<content>.*?)</a>',
                navigation_match.group(
                    "content"
                ),
                flags=re.DOTALL,
        ):
            attributes = match.group(
                "attributes"
            )

            def attribute_value(name):
                attribute_match = re.search(
                    rf'\b{re.escape(name)}\s*=\s*'
                    r'(?P<quote>["\'])'
                    r'(?P<value>.*?)'
                    r'(?P=quote)',
                    attributes,
                    flags=re.DOTALL,
                )

                if attribute_match is None:
                    if re.search(
                        rf'\b{re.escape(name)}\b',
                        attributes,
                    ):
                        return ""

                    return None

                return attribute_match.group(
                    "value"
                )

            links.append(
                {
                    "attributes": attributes,
                    "label": " ".join(
                        match.group(
                            "content"
                        ).split()
                    ),
                    "href": attribute_value(
                        "href"
                    ),
                    "aria_current": attribute_value(
                        "aria-current"
                    ),
                }
            )

        return links

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

    def test_dashboard_uses_champion_mastery_synchronization_copy(self):
        """
        Dashboard mastery controls should use synchronization terms.
        """

        html = self._render_shared_page(
            "home.html"
        )

        synchronization_sections = re.findall(
            r'<section\b[^>]*aria-labelledby="synchronize-heading"'
            r'[^>]*>(?P<section>.*?)</section>',
            html,
            flags=re.DOTALL,
        )

        self.assertEqual(
            len(synchronization_sections),
            1,
        )

        section = synchronization_sections[0]

        heading_labels = [
            " ".join(
                label.split()
            )
            for label in re.findall(
                r'<h2\b[^>]*id="synchronize-heading"[^>]*>'
                r'(?P<label>.*?)</h2>',
                section,
                flags=re.DOTALL,
            )
        ]

        self.assertEqual(
            heading_labels,
            [
                "Synchronize Champion Mastery",
            ],
        )

        self.assertNotIn(
            "Synchronize mastery",
            heading_labels,
        )

        normalized_section = " ".join(
            section.split()
        )

        self.assertIn(
            (
                "Synchronize locally stored Champion Mastery "
                "through the existing manual synchronization "
                "actions."
            ),
            normalized_section,
        )

        self.assertNotIn(
            (
                "Refresh locally stored Champion Mastery "
                "through the existing manual synchronization "
                "actions."
            ),
            normalized_section,
        )

    def test_dashboard_action_rows_use_local_spacing_class(self):
        """
        Dashboard action rows should use one local spacing rule.
        """

        template = self._read_template(
            "home.html"
        )

        self.assertNotIn(
            "style=",
            template,
        )

        self.assertNotIn(
            'style="margin-top: var(--space-5);"',
            template,
        )

        action_rows = re.findall(
            r'<div\b[^>]*class="actions dashboard-action-row"'
            r'[^>]*>',
            template,
        )

        self.assertEqual(
            len(action_rows),
            2,
        )

        stylesheet = self._read_static_file(
            "app.css"
        )

        self.assertEqual(
            stylesheet.count(
                ".dashboard-action-row"
            ),
            1,
        )

        declarations = self._get_stylesheet_rule(
            ".dashboard-action-row"
        )

        self.assertIsNotNone(
            declarations
        )

        declaration_entries = [
            (
                match.group(
                    "property"
                ),
                " ".join(
                    match.group(
                        "value"
                    ).split()
                ),
            )
            for match in re.finditer(
                r"(?P<property>[-a-z]+)\s*:\s*"
                r"(?P<value>[^;]+);",
                declarations,
            )
        ]

        self.assertEqual(
            declaration_entries,
            [
                (
                    "margin-top",
                    "var(--space-5)",
                ),
            ],
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
        Every shared page should supply only its page title portion.
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

                self.assertNotIn(
                    self.PRODUCT_NAME,
                    re.search(
                        r"{% block title %}"
                        r"(?P<title>.*?)"
                        r"{% endblock %}",
                        content,
                        flags=re.DOTALL,
                    ).group("title"),
                )

    def test_base_template_owns_canonical_document_title(self):
        """
        The base should append one canonical product suffix.
        """

        content = self._read_template(
            "base.html"
        )

        title_element = re.search(
            r"<title>(?P<content>.*?)</title>",
            content,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(
            title_element
        )

        normalized_title = " ".join(
            title_element.group(
                "content"
            ).split()
        )

        self.assertEqual(
            normalized_title.count(
                "{% block title %}"
            ),
            1,
        )

        self.assertEqual(
            normalized_title.count(
                'config["PRODUCT_NAME"]'
            ),
            1,
        )

        self.assertIn(
            "{% endblock %} · "
            '{{ config["PRODUCT_NAME"] }}',
            normalized_title,
        )

    def test_rendered_shared_pages_use_canonical_titles(self):
        """
        Every normal page should render one canonical document title.
        """

        for template_name, expected in (
            self.SHARED_PAGE_EXPECTATIONS.items()
        ):
            with self.subTest(
                template=template_name
            ):
                html = self._render_shared_page(
                    template_name
                )

                titles = re.findall(
                    r"<title>(?P<title>.*?)</title>",
                    html,
                    flags=re.DOTALL,
                )

                self.assertEqual(
                    len(titles),
                    1,
                )

                self.assertEqual(
                    " ".join(
                        titles[0].split()
                    ),
                    (
                        f'{expected["title"]} · '
                        f"{self.PRODUCT_NAME}"
                    ),
                )

                if template_name == "missing_champions.html":
                    self.assertNotEqual(
                        " ".join(
                            titles[0].split()
                        ),
                        (
                            "Missing champion data · "
                            f"{self.PRODUCT_NAME}"
                        ),
                    )

    def test_base_template_declares_shared_page_header_blocks(self):
        """
        The base should expose all page-specific header extension points.
        """

        content = self._read_template(
            "base.html"
        )

        for block_name in (
            "page_eyebrow",
            "page_heading",
            "page_description",
            "page_actions",
        ):
            with self.subTest(
                block=block_name
            ):
                self.assertEqual(
                    content.count(
                        "{% block "
                        f"{block_name} %}}"
                    ),
                    1,
                )

    def test_base_template_owns_one_page_header_structure(self):
        """
        Shared page-header elements should have one base-owned copy.
        """

        content = self._read_template(
            "base.html"
        )

        for structural_markup in (
            '<header class="page-header">',
            '<div class="page-header__content">',
            '<p class="page-header__eyebrow">',
            "<h1>",
            '<p class="page-header__description">',
            '<div class="page-header__actions">',
        ):
            with self.subTest(
                markup=structural_markup
            ):
                self.assertEqual(
                    content.count(
                        structural_markup
                    ),
                    1,
                )

    def test_shared_pages_override_header_blocks_without_structure(self):
        """
        Child templates should provide content, not header wrappers.
        """

        structural_markup = (
            '<header class="page-header">',
            '<div class="page-header__content">',
            '<p class="page-header__eyebrow">',
            "<h1>",
            '<p class="page-header__description">',
            '<div class="page-header__actions">',
        )

        for template_name in (
            self.SHARED_TEMPLATE_NAMES
        ):
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                for block_name in (
                    "page_eyebrow",
                    "page_heading",
                    "page_description",
                    "page_actions",
                    "content",
                ):
                    self.assertEqual(
                        content.count(
                            "{% block "
                            f"{block_name} %}}"
                        ),
                        1,
                    )

                for markup in structural_markup:
                    self.assertNotIn(
                        markup,
                        content,
                    )

    def test_rendered_shared_pages_preserve_complete_page_headers(self):
        """
        Rendered headers should retain page content and destinations.
        """

        for template_name, expected in (
            self.SHARED_PAGE_EXPECTATIONS.items()
        ):
            with self.subTest(
                template=template_name
            ):
                html = self._render_shared_page(
                    template_name
                )

                headers = re.findall(
                    r'<header class="page-header">'
                    r'(?P<header>.*?)</header>',
                    html,
                    flags=re.DOTALL,
                )

                self.assertEqual(
                    len(headers),
                    1,
                )

                header = headers[0]

                self.assertEqual(
                    header.count(
                        'class="page-header__eyebrow"'
                    ),
                    1,
                )

                self.assertEqual(
                    len(re.findall(
                        r"<h1>.*?</h1>",
                        header,
                        flags=re.DOTALL,
                    )),
                    1,
                )

                self.assertEqual(
                    header.count(
                        'class="page-header__description"'
                    ),
                    1,
                )

                self.assertEqual(
                    header.count(
                        'class="page-header__actions"'
                    ),
                    1,
                )

                normalized_header = " ".join(
                    header.split()
                )

                for visible_text in (
                    expected["eyebrow"],
                    expected["heading"],
                    expected["description"],
                ):
                    self.assertIn(
                        visible_text,
                        normalized_header,
                    )

                if template_name == "missing_champions.html":
                    page_heading_labels = [
                        " ".join(
                            label.split()
                        )
                        for label in re.findall(
                            r"<h1>(?P<label>.*?)</h1>",
                            header,
                            flags=re.DOTALL,
                        )
                    ]

                    self.assertEqual(
                        page_heading_labels,
                        [
                            "Missing metadata",
                        ],
                    )

                    self.assertNotIn(
                        "Missing champion data",
                        page_heading_labels,
                    )

                rendered_actions = re.findall(
                    r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>'
                    r'(?P<label>.*?)</a>',
                    header,
                    flags=re.DOTALL,
                )

                self.assertEqual(
                    [
                        (
                            href,
                            " ".join(label.split()),
                        )
                        for href, label in rendered_actions
                    ],
                    list(expected["actions"]),
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

    def test_primary_navigation_marks_current_blueprint_family(self):
        """
        Each normal page should expose one current navigation section.
        """

        expected_current_links = {
            "home": ("Dashboard", "/"),
            "champions": ("Dashboard", "/"),
            "persons": ("Persons", "/persons"),
            "settings": ("Settings", "/settings"),
            "json_export": ("Settings", "/settings"),
            "json_import": ("Settings", "/settings"),
            "database_restore": ("Settings", "/settings"),
        }

        for blueprint_name, expected_current_link in (
            expected_current_links.items()
        ):
            with self.subTest(
                blueprint=blueprint_name
            ):
                links = (
                    self._get_primary_navigation_links(
                        self._render_navigation_page(
                            blueprint_name
                        )
                    )
                )

                self.assertEqual(
                    [
                        link["label"]
                        for link in links
                    ],
                    [
                        "Dashboard",
                        "Persons",
                        "Settings",
                    ],
                )

                expected_links = [
                    {
                        "label": label,
                        "href": href,
                        "aria_current": (
                            "page"
                            if (label, href)
                            == expected_current_link
                            else None
                        ),
                    }
                    for label, href in (
                        ("Dashboard", "/"),
                        ("Persons", "/persons"),
                        ("Settings", "/settings"),
                    )
                ]

                self.assertEqual(
                    [
                        {
                            "label": link["label"],
                            "href": link["href"],
                            "aria_current": link[
                                "aria_current"
                            ],
                        }
                        for link in links
                    ],
                    expected_links,
                )

                current_links = [
                    link
                    for link in links
                    if re.search(
                        r'\baria-current\s*=\s*"page"',
                        link["attributes"],
                    )
                ]

                self.assertEqual(
                    len(current_links),
                    1,
                )

                self.assertEqual(
                    (
                        current_links[0]["label"],
                        current_links[0]["href"],
                    ),
                    expected_current_link,
                )

                for link in links:
                    if (
                        link["label"],
                        link["href"],
                    ) != expected_current_link:
                        self.assertNotRegex(
                            link["attributes"],
                            r"\baria-current\b",
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

    def test_default_form_control_boundary_meets_non_text_contrast(self):
        """
        Default native control boundaries need at least 3:1 contrast.
        """

        tokens = self._get_stylesheet_root_tokens()
        declarations = self._get_stylesheet_rule(
            'input[type="text"]'
        )

        self.assertEqual(
            tokens.get("--color-bg-subtle"),
            "#111827",
        )

        self.assertIsNotNone(declarations)

        for selector in (
            'input[type="text"]',
            'input[type="password"]',
            'input[type="file"]',
            "select",
            "textarea",
        ):
            with self.subTest(selector=selector):
                selector_declarations = (
                    self._get_stylesheet_rule(selector)
                )

                self.assertIsNotNone(selector_declarations)
                self.assertIn(
                    "var(--color-border-strong)",
                    selector_declarations,
                )
                self.assertIn(
                    "var(--color-bg-subtle)",
                    selector_declarations,
                )

        self.assertIn(
            "var(--color-border-strong)",
            declarations,
        )
        self.assertIn(
            "var(--color-bg-subtle)",
            declarations,
        )

        hover_declarations = self._get_stylesheet_rule(
            "input:hover"
        )
        focus_declarations = self._get_stylesheet_rule(
            "input:focus-visible"
        )

        self.assertIn(
            "var(--color-control-border-hover)",
            hover_declarations,
        )
        self.assertIn(
            "var(--color-focus)",
            focus_declarations,
        )

        contrast_ratio = self._contrast_ratio(
            self._parse_hex_color(
                tokens["--color-border-strong"]
            ),
            self._parse_hex_color(
                tokens["--color-bg-subtle"]
            ),
        )

        self.assertGreaterEqual(
            contrast_ratio,
            3.0,
            (
                "Default form-control boundary contrast is "
                f"{contrast_ratio:.2f}:1, below 3:1."
            ),
        )

    def test_shared_headings_wrap_unbroken_person_names(self):
        """
        Shared headings must preserve long Person names without clipping.
        """

        home_template = self._read_template(
            "home.html"
        )
        person_detail_template = self._read_template(
            "person_detail.html"
        )
        persons_template = self._read_template(
            "persons.html"
        )
        base_template = self._read_template(
            "base.html"
        )
        stylesheet = self._read_static_file(
            "app.css"
        )
        shared_heading_rule = re.search(
            r"h1\s*,\s*h2\s*,\s*h3\s*"
            r"\{(?P<declarations>[^{}]*)\}",
            stylesheet,
            flags=re.DOTALL,
        )
        person_detail_heading = re.search(
            r"\{% block page_heading %\}"
            r"(?P<content>.*?)"
            r"\{% endblock %\}",
            person_detail_template,
            flags=re.DOTALL,
        )
        base_heading = re.search(
            r"<h1>\s*"
            r"\{% block page_heading %\}"
            r"\{% endblock %\}\s*"
            r"</h1>",
            base_template,
            flags=re.DOTALL,
        )
        persons_table = re.search(
            r"<table>.*?<tbody>"
            r"(?P<body>.*?)"
            r"</tbody>.*?</table>",
            persons_template,
            flags=re.DOTALL,
        )

        self.assertRegex(
            home_template,
            r"<h3>\s*\{\{ person\.display_name \}\}\s*</h3>",
        )
        self.assertIsNotNone(person_detail_heading)
        self.assertEqual(
            " ".join(
                person_detail_heading.group(
                    "content"
                ).split()
            ),
            "{{ person.display_name }}",
        )
        self.assertIsNotNone(base_heading)
        self.assertIsNotNone(persons_table)
        self.assertIsNotNone(shared_heading_rule)

        person_row = re.search(
            r"\{% for person in persons %\}.*?"
            r"<tr>.*?<td>.*?"
            r"<a\b(?P<attributes>[^>]*)>"
            r"(?P<label>.*?)"
            r"</a>.*?</td>.*?</tr>.*?"
            r"\{% endfor %\}",
            persons_table.group("body"),
            flags=re.DOTALL,
        )

        self.assertIsNotNone(person_row)

        person_link_attributes = " ".join(
            person_row.group("attributes").split()
        )
        person_link_label = " ".join(
            person_row.group("label").split()
        )

        self.assertIn(
            "persons.get_person",
            person_link_attributes,
        )
        self.assertIn(
            "person_id=person.id",
            person_link_attributes,
        )
        self.assertEqual(
            person_link_label,
            "{{ person.display_name }}",
        )
        self.assertNotRegex(
            person_link_label,
            r"<h[1-3]\\b",
        )

        declarations = shared_heading_rule.group(
            "declarations"
        )

        self.assertLess(
            stylesheet.index(shared_heading_rule.group()),
            stylesheet.index("@media"),
        )
        self.assertIn(
            "overflow-wrap: anywhere;",
            declarations,
        )

        for prohibited_declaration in (
            "white-space: nowrap;",
            "overflow: hidden;",
            "text-overflow: ellipsis;",
            "word-break: break-all;",
        ):
            self.assertNotIn(
                prohibited_declaration,
                declarations,
            )

    def test_stylesheet_marks_current_primary_navigation_semantically(self):
        """
        Current navigation should remain visible without color alone.
        """

        declarations = (
            self._get_stylesheet_rule(
                '.main-nav a[aria-current="page"]'
            )
        )

        self.assertIsNotNone(
            declarations
        )

        self.assertRegex(
            declarations,
            r"text-decoration\s*:\s*underline\s*;",
        )

        self.assertIn(
            "var(--color-text)",
            declarations,
        )

        self.assertIn(
            "var(--font-weight-semibold)",
            declarations,
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
