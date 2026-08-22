import re
import unittest
from pathlib import Path


class CsrfTemplateTests(unittest.TestCase):
    def test_every_post_form_contains_csrf_token(self):
        project_root = Path(
            __file__
        ).resolve().parents[1]

        template_directory = (
            project_root
            / "application"
            / "templates"
        )

        form_pattern = re.compile(
            r"<form\b"
            r"(?P<attributes>[^>]*)>"
            r"(?P<body>.*?)"
            r"</form>",
            re.IGNORECASE | re.DOTALL,
        )

        post_method_pattern = re.compile(
            r"\bmethod\s*=\s*[\"']post[\"']",
            re.IGNORECASE,
        )

        csrf_field_pattern = re.compile(
            r"<input\b"
            r"(?=[^>]*\btype\s*=\s*[\"']hidden[\"'])"
            r"(?=[^>]*\bname\s*=\s*[\"']_csrf_token[\"'])"
            r"(?=[^>]*\bvalue\s*=\s*[\"']"
            r"\{\{\s*csrf_token\(\)\s*\}\}"
            r"[\"'])"
            r"[^>]*>",
            re.IGNORECASE | re.DOTALL,
        )

        missing_tokens = []

        for template_file in sorted(
            template_directory.rglob("*.html")
        ):
            template_text = template_file.read_text(
                encoding="utf-8"
            )

            for form_number, match in enumerate(
                form_pattern.finditer(
                    template_text
                ),
                start=1,
            ):
                attributes = match.group(
                    "attributes"
                )

                if not post_method_pattern.search(
                    attributes
                ):
                    continue

                form_body = match.group(
                    "body"
                )

                if csrf_field_pattern.search(
                    form_body
                ):
                    continue

                line_number = (
                    template_text.count(
                        "\n",
                        0,
                        match.start(),
                    )
                    + 1
                )

                relative_path = (
                    template_file.relative_to(
                        project_root
                    )
                )

                missing_tokens.append(
                    (
                        str(relative_path),
                        form_number,
                        line_number,
                    )
                )

        self.assertEqual(
            missing_tokens,
            [],
            (
                "POST forms missing a valid CSRF field: "
                f"{missing_tokens}"
            ),
        )


if __name__ == "__main__":
    unittest.main()