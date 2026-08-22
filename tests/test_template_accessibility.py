import unittest
from pathlib import Path


class TemplateAccessibilityTests(
    unittest.TestCase
):
    """
    Protect the Step 10 accessibility contracts in project templates.
    """

    PROJECT_ROOT = Path(
        __file__
    ).resolve().parents[1]

    TEMPLATE_DIR = (
        PROJECT_ROOT
        / "application"
        / "templates"
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

    def test_persons_display_name_has_label(self):
        content = self._read_template(
            "persons.html"
        )

        self.assertIn(
            'for="display_name"',
            content,
        )

        self.assertIn(
            'id="display_name"',
            content,
        )

    def test_person_detail_account_fields_have_labels(self):
        content = self._read_template(
            "person_detail.html"
        )

        for field_name in (
            "game_name",
            "tag_line",
            "platform_region",
            "display_name",
        ):
            with self.subTest(
                field=field_name
            ):
                self.assertIn(
                    f'for="{field_name}"',
                    content,
                )

                self.assertIn(
                    f'id="{field_name}"',
                    content,
                )

    def test_person_detail_champion_images_have_alt_text(self):
        content = self._read_template(
            "person_detail.html"
        )

        self.assertIn(
            'alt="{{ champion.champion_name }}"',
            content,
        )

    def test_person_detail_missing_images_have_accessible_name(self):
        content = self._read_template(
            "person_detail.html"
        )

        self.assertIn(
            'role="img"',
            content,
        )

        self.assertIn(
            (
                'aria-label="{{ champion.'
                'champion_name }} image unavailable"'
            ),
            content,
        )

    def test_settings_api_key_field_has_label(self):
        content = self._read_template(
            "settings.html"
        )

        self.assertIn(
            'for="api_key"',
            content,
        )

        self.assertIn(
            'id="api_key"',
            content,
        )

    def test_settings_api_key_help_is_connected(self):
        content = self._read_template(
            "settings.html"
        )

        self.assertIn(
            'aria-describedby="api-key-help"',
            content,
        )

        self.assertIn(
            'id="api-key-help"',
            content,
        )

    def test_json_import_file_field_has_label(self):
        content = self._read_template(
            "json_import.html"
        )

        self.assertIn(
            'for="import_file"',
            content,
        )

        self.assertIn(
            'id="import_file"',
            content,
        )

    def test_json_import_confirmation_has_label(self):
        content = self._read_template(
            "json_import.html"
        )

        self.assertIn(
            'for="confirmation_text"',
            content,
        )

        self.assertIn(
            'id="confirmation_text"',
            content,
        )

    def test_database_restore_confirmation_has_label(self):
        content = self._read_template(
            "database_restore.html"
        )

        self.assertIn(
            'for="confirmation-{{ loop.index }}"',
            content,
        )

        self.assertIn(
            'id="confirmation-{{ loop.index }}"',
            content,
        )

    def test_missing_champion_name_has_label(self):
        content = self._read_template(
            "missing_champions.html"
        )

        self.assertIn(
            'for="name-{{ champion.id }}"',
            content,
        )

        self.assertIn(
            'id="name-{{ champion.id }}"',
            content,
        )

    def test_missing_champion_label_is_screen_reader_accessible(self):
        content = self._read_template(
            "missing_champions.html"
        )

        self.assertIn(
            'class="sr-only"',
            content,
        )

        self.assertIn(
            "Champion name",
            content,
        )

    def test_error_states_use_alert_semantics(self):
        template_names = (
            "settings.html",
            "json_import.html",
            "json_export.html",
            "database_restore.html",
        )

        for template_name in template_names:
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                self.assertIn(
                    'role="alert"',
                    content,
                )

    def test_status_states_use_status_semantics(self):
        template_names = (
            "home.html",
            "settings.html",
            "json_import.html",
            "database_restore.html",
        )

        for template_name in template_names:
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                self.assertIn(
                    'role="status"',
                    content,
                )

    def test_table_templates_provide_column_headers(self):
        template_names = (
            "persons.html",
            "person_detail.html",
            "json_import.html",
            "missing_champions.html",
        )

        for template_name in template_names:
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                self.assertIn(
                    'scope="col"',
                    content,
                )

    def test_data_tables_have_accessible_captions(self):
        template_names = (
            "persons.html",
            "person_detail.html",
            "json_import.html",
            "missing_champions.html",
        )

        for template_name in template_names:
            with self.subTest(
                template=template_name
            ):
                content = self._read_template(
                    template_name
                )

                self.assertIn(
                    "<caption",
                    content,
                )

                self.assertIn(
                    'class="sr-only"',
                    content,
                )


if __name__ == "__main__":
    unittest.main()