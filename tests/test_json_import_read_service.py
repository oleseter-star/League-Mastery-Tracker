import hashlib
import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from application.services.json_export_validation_service import (
    JsonExportValidationError,
)
from application.services.json_import_read_service import (
    JsonImportReadError,
    JsonImportReadService,
)


class JsonImportReadServiceTests(
    unittest.TestCase
):
    def _build_valid_document(self):
        return {
            "format": (
                "league-mastery-tracker-export"
            ),
            "format_version": 1,
            "database_schema_version": 1,
            "exported_at": (
                "2026-07-16T12:00:00Z"
            ),
            "record_counts": {
                "persons": 0,
                "riot_accounts": 0,
                "champions": 0,
                "mastery_records": 0,
            },
            "data": {
                "champions": [],
                "persons": [],
            },
        }

    def _serialize_document(
        self,
        document,
    ):
        return json.dumps(
            document,
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

    def _serialize_text(
        self,
        document,
    ):
        return json.dumps(
            document,
            ensure_ascii=False,
        )

    def test_reads_valid_export_without_database_changes(
        self
    ):
        document = (
            self._build_valid_document()
        )

        raw_bytes = self._serialize_document(
            document
        )

        result = (
            JsonImportReadService
            .read_stream(
                stream=BytesIO(
                    raw_bytes
                ),
                file_name="valid-export.json",
            )
        )

        self.assertEqual(
            result["file_name"],
            "valid-export.json",
        )

        self.assertEqual(
            result["file_size_bytes"],
            len(
                raw_bytes
            ),
        )

        self.assertEqual(
            result["sha256"],
            hashlib.sha256(
                raw_bytes
            ).hexdigest(),
        )

        self.assertEqual(
            result["format"],
            "league-mastery-tracker-export",
        )

        self.assertEqual(
            result["format_version"],
            1,
        )

        self.assertEqual(
            result["database_schema_version"],
            1,
        )

        self.assertEqual(
            result["record_counts"],
            {
                "persons": 0,
                "riot_accounts": 0,
                "champions": 0,
                "mastery_records": 0,
            },
        )

        self.assertEqual(
            result["document"],
            document,
        )

    def test_normalizes_browser_fake_path(
        self
    ):
        document = (
            self._build_valid_document()
        )

        result = (
            JsonImportReadService
            .read_stream(
                stream=BytesIO(
                    self._serialize_document(
                        document
                    )
                ),
                file_name=(
                    r"C:\fakepath\portable-export.JSON"
                ),
            )
        )

        self.assertEqual(
            result["file_name"],
            "portable-export.JSON",
        )

    def test_accepts_utf8_byte_order_mark(
        self
    ):
        document = (
            self._build_valid_document()
        )

        raw_bytes = (
            b"\xef\xbb\xbf"
            + self._serialize_document(
                document
            )
        )

        result = (
            JsonImportReadService
            .read_stream(
                stream=BytesIO(
                    raw_bytes
                ),
                file_name="bom-export.json",
            )
        )

        self.assertEqual(
            result["document"],
            document,
        )

        self.assertEqual(
            result["file_size_bytes"],
            len(
                raw_bytes
            ),
        )

    def test_rejects_empty_file(
        self
    ):
        with self.assertRaisesRegex(
            JsonImportReadError,
            "empty",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        b""
                    ),
                    file_name="empty.json",
                )
            )

    def test_rejects_non_json_file_extension(
        self
    ):
        document = (
            self._build_valid_document()
        )

        with self.assertRaisesRegex(
            JsonImportReadError,
            r"\.json",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        self._serialize_document(
                            document
                        )
                    ),
                    file_name="export.txt",
                )
            )

    def test_rejects_file_larger_than_limit(
        self
    ):
        with self.assertRaisesRegex(
            JsonImportReadError,
            "too large",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        b"123456"
                    ),
                    file_name="large.json",
                    max_file_size_bytes=5,
                )
            )

    def test_rejects_invalid_utf8(
        self
    ):
        with self.assertRaisesRegex(
            JsonImportReadError,
            "valid UTF-8",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        b"\xff\xfe\xfa"
                    ),
                    file_name="invalid-utf8.json",
                )
            )

    def test_rejects_malformed_json(
        self
    ):
        with self.assertRaisesRegex(
            JsonImportReadError,
            "valid JSON",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        b'{"format":'
                    ),
                    file_name="malformed.json",
                )
            )

    def test_rejects_duplicate_top_level_object_key(
        self
    ):
        document = (
            self._build_valid_document()
        )

        serialized_text = (
            self._serialize_text(
                document
            )
        )

        original_field = (
            '"format": '
            '"league-mastery-tracker-export"'
        )

        duplicate_field = (
            '"format": '
            '"league-mastery-tracker-export", '
            '"format": '
            '"league-mastery-tracker-export"'
        )

        self.assertIn(
            original_field,
            serialized_text,
        )

        duplicate_document = (
            serialized_text.replace(
                original_field,
                duplicate_field,
                1,
            )
        )

        with self.assertRaisesRegex(
            JsonImportReadError,
            "duplicate JSON object keys",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        duplicate_document.encode(
                            "utf-8"
                        )
                    ),
                    file_name=(
                        "duplicate-top-level.json"
                    ),
                )
            )

    def test_rejects_duplicate_nested_object_key(
        self
    ):
        document = (
            self._build_valid_document()
        )

        serialized_text = (
            self._serialize_text(
                document
            )
        )

        original_field = (
            '"persons": []'
        )

        duplicate_field = (
            '"persons": [], '
            '"persons": []'
        )

        self.assertIn(
            original_field,
            serialized_text,
        )

        duplicate_document = (
            serialized_text.replace(
                original_field,
                duplicate_field,
                1,
            )
        )

        with self.assertRaisesRegex(
            JsonImportReadError,
            "duplicate JSON object keys",
        ):
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        duplicate_document.encode(
                            "utf-8"
                        )
                    ),
                    file_name=(
                        "duplicate-nested.json"
                    ),
                )
            )

    def test_rejects_nonstandard_json_numeric_constants(
        self
    ):
        document = (
            self._build_valid_document()
        )

        serialized_text = (
            self._serialize_text(
                document
            )
        )

        original_field = (
            '"format_version": 1'
        )

        self.assertIn(
            original_field,
            serialized_text,
        )

        for constant_name in (
            "NaN",
            "Infinity",
            "-Infinity",
        ):
            with self.subTest(
                constant_name=constant_name
            ):
                modified_document = (
                    serialized_text.replace(
                        original_field,
                        (
                            '"format_version": '
                            f"{constant_name}"
                        ),
                        1,
                    )
                )

                with self.assertRaisesRegex(
                    JsonImportReadError,
                    "NaN and Infinity are not allowed",
                ):
                    (
                        JsonImportReadService
                        .read_stream(
                            stream=BytesIO(
                                modified_document.encode(
                                    "utf-8"
                                )
                            ),
                            file_name=(
                                "nonstandard-number.json"
                            ),
                        )
                    )

    def test_wraps_export_validation_error(
        self
    ):
        document = (
            self._build_valid_document()
        )

        document["format"] = (
            "not-the-supported-format"
        )

        with self.assertRaises(
            JsonImportReadError
        ) as raised_context:
            (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        self._serialize_document(
                            document
                        )
                    ),
                    file_name="wrong-format.json",
                )
            )

        self.assertIn(
            "failed export format validation",
            str(
                raised_context.exception
            ),
        )

        self.assertIsInstance(
            raised_context.exception.__cause__,
            JsonExportValidationError,
        )

    def test_reads_valid_export_from_file_path(
        self
    ):
        document = (
            self._build_valid_document()
        )

        with TemporaryDirectory() as directory:
            file_path = (
                Path(
                    directory
                )
                / "portable-export.json"
            )

            file_path.write_bytes(
                self._serialize_document(
                    document
                )
            )

            result = (
                JsonImportReadService
                .read_file(
                    file_path
                )
            )

        self.assertEqual(
            result["file_name"],
            "portable-export.json",
        )

        self.assertEqual(
            result["document"],
            document,
        )


if __name__ == "__main__":
    unittest.main()