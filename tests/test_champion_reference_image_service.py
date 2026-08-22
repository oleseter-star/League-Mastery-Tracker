import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from application.services.champion_reference_image_service import (
    ChampionReferenceImageError,
    ChampionReferenceImageService,
)


class ChampionReferenceImageServiceTests(
    unittest.TestCase
):
    PNG_BYTES = (
        b"\x89PNG\r\n\x1a\n"
        b"test-champion-image"
    )

    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.bundled_directory = (
            self.root_directory
            / "bundled"
            / "data_dragon"
        )

        self.bundled_icons_directory = (
            self.bundled_directory
            / "champion_icons"
        )

        self.cache_directory = (
            self.root_directory
            / "reference"
            / "data_dragon"
        )

        self.cache_icons_directory = (
            self.cache_directory
            / "champion_icons"
        )

        self.source_service = Mock()

        self.service = (
            ChampionReferenceImageService(
                source_service=(
                    self.source_service
                )
            )
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_icon(
        self,
        icons_directory,
        filename="Annie.png",
        content=None,
    ):
        icons_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        icon_file = (
            icons_directory
            / filename
        )

        icon_file.write_bytes(
            content
            if content is not None
            else self.PNG_BYTES
        )

        return icon_file

    def _configure_source(
        self,
        *,
        active_source,
        icons_directory,
    ):
        self.source_service.select_source.return_value = {
            "active_source": active_source,
            "dataset": {
                "manifest": {
                    "data_dragon_version": (
                        "15.14.1"
                    ),
                },
            },
            "data_dragon_version": (
                "15.14.1"
            ),
            "locale": "en_US",
            "dataset_directory": (
                Path(
                    icons_directory
                ).parent
            ),
            "icons_directory": (
                Path(
                    icons_directory
                )
            ),
            "warnings": [],
        }

    def test_bundled_champion_image_is_resolved(
        self
    ):
        icon_file = self._create_icon(
            self.bundled_icons_directory
        )

        self._configure_source(
            active_source="bundled",
            icons_directory=(
                self.bundled_icons_directory
            ),
        )

        result = self.service.resolve_image(
            "Annie.png"
        )

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertEqual(
            result["image_file"],
            icon_file.resolve(),
        )

        self.assertEqual(
            result["mime_type"],
            "image/png",
        )

        self.assertFalse(
            result["placeholder"]
        )

    def test_local_cache_champion_image_is_resolved(
        self
    ):
        icon_file = self._create_icon(
            self.cache_icons_directory
        )

        self._configure_source(
            active_source="local_cache",
            icons_directory=(
                self.cache_icons_directory
            ),
        )

        result = self.service.resolve_image(
            "Annie.png"
        )

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["image_file"],
            icon_file.resolve(),
        )

        self.assertFalse(
            result["placeholder"]
        )

    def test_missing_image_returns_placeholder_result(
        self
    ):
        self._configure_source(
            active_source="bundled",
            icons_directory=(
                self.bundled_icons_directory
            ),
        )

        result = self.service.resolve_image(
            "Missing.png"
        )

        self.assertEqual(
            result,
            {
                "active_source": "bundled",
                "image_file": None,
                "mime_type": "image/svg+xml",
                "placeholder": True,
            },
        )

    def test_database_only_source_returns_placeholder(
        self
    ):
        self.source_service.select_source.return_value = {
            "active_source": "database",
            "dataset": None,
            "data_dragon_version": None,
            "locale": None,
            "dataset_directory": None,
            "icons_directory": None,
            "warnings": [],
        }

        result = self.service.resolve_image(
            "Annie.png"
        )

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertIsNone(
            result["image_file"]
        )

        self.assertTrue(
            result["placeholder"]
        )

        self.assertEqual(
            result["mime_type"],
            "image/svg+xml",
        )

    def test_invalid_png_content_returns_placeholder(
        self
    ):
        self._create_icon(
            self.bundled_icons_directory,
            content=b"not-a-png",
        )

        self._configure_source(
            active_source="bundled",
            icons_directory=(
                self.bundled_icons_directory
            ),
        )

        result = self.service.resolve_image(
            "Annie.png"
        )

        self.assertIsNone(
            result["image_file"]
        )

        self.assertTrue(
            result["placeholder"]
        )

    def test_empty_png_file_returns_placeholder(
        self
    ):
        self._create_icon(
            self.bundled_icons_directory,
            content=b"",
        )

        self._configure_source(
            active_source="bundled",
            icons_directory=(
                self.bundled_icons_directory
            ),
        )

        result = self.service.resolve_image(
            "Annie.png"
        )

        self.assertIsNone(
            result["image_file"]
        )

        self.assertTrue(
            result["placeholder"]
        )

    def test_source_selection_failure_returns_placeholder(
        self
    ):
        self.source_service.select_source.side_effect = (
            RuntimeError(
                "source selection failed"
            )
        )

        result = self.service.resolve_image(
            "Annie.png"
        )

        self.assertEqual(
            result,
            {
                "active_source": "database",
                "image_file": None,
                "mime_type": "image/svg+xml",
                "placeholder": True,
            },
        )

    def test_unsafe_image_filename_is_rejected_before_source_lookup(
        self
    ):
        with self.assertRaises(
            ChampionReferenceImageError
        ):
            self.service.resolve_image(
                "../Annie.png"
            )

        self.source_service.select_source.assert_not_called()

    def test_windows_path_is_rejected_before_source_lookup(
        self
    ):
        with self.assertRaises(
            ChampionReferenceImageError
        ):
            self.service.resolve_image(
                "folder\\Annie.png"
            )

        self.source_service.select_source.assert_not_called()

    def test_non_png_filename_is_rejected_before_source_lookup(
        self
    ):
        with self.assertRaises(
            ChampionReferenceImageError
        ):
            self.service.resolve_image(
                "Annie.jpg"
            )

        self.source_service.select_source.assert_not_called()

    def test_empty_filename_is_rejected_before_source_lookup(
        self
    ):
        with self.assertRaises(
            ChampionReferenceImageError
        ):
            self.service.resolve_image(
                "   "
            )

        self.source_service.select_source.assert_not_called()

    def test_image_resolution_does_not_contact_network(
        self
    ):
        self._create_icon(
            self.bundled_icons_directory
        )

        self._configure_source(
            active_source="bundled",
            icons_directory=(
                self.bundled_icons_directory
            ),
        )

        with patch(
            "requests.get"
        ) as requests_get:
            result = self.service.resolve_image(
                "Annie.png"
            )

        requests_get.assert_not_called()

        self.assertFalse(
            result["placeholder"]
        )


if __name__ == "__main__":
    unittest.main()