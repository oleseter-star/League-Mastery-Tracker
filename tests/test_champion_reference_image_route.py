import importlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.services.champion_reference_image_service import (
    ChampionReferenceImageError,
)


image_route_module = importlib.import_module(
    "application.routes.champion_images"
)


class ChampionReferenceImageRouteTests(
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

        self.image_file = (
            self.root_directory
            / "Annie.png"
        )

        self.image_file.write_bytes(
            self.PNG_BYTES
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
        )

        self.app.register_blueprint(
            image_route_module
            .champion_images_bp
        )

        self.client = (
            self.app.test_client()
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_local_png_is_returned(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service = (
                service_class.return_value
            )

            service.resolve_image.return_value = {
                "active_source": "bundled",
                "image_file": (
                    self.image_file
                ),
                "mime_type": "image/png",
                "placeholder": False,
            }

            response = self.client.get(
                "/champions/images/Annie.png"
            )

        try:
            self.assertEqual(
                response.status_code,
                200,
            )

            self.assertEqual(
                response.mimetype,
                "image/png",
            )

            self.assertEqual(
                response.data,
                self.PNG_BYTES,
            )
        finally:
            response.close()

    def test_route_uses_image_service(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service = (
                service_class.return_value
            )

            service.resolve_image.return_value = {
                "active_source": "bundled",
                "image_file": (
                    self.image_file
                ),
                "mime_type": "image/png",
                "placeholder": False,
            }

            response = self.client.get(
                "/champions/images/Annie.png"
            )

        try:
            service_class.assert_called_once_with()

            service.resolve_image.assert_called_once_with(
                "Annie.png"
            )
        finally:
            response.close()

    def test_missing_image_returns_svg_placeholder(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.return_value = {
                "active_source": "bundled",
                "image_file": None,
                "mime_type": "image/svg+xml",
                "placeholder": True,
            }

            response = self.client.get(
                "/champions/images/Missing.png"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.mimetype,
            "image/svg+xml",
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertIn(
            "<svg",
            response_text,
        )

        self.assertIn(
            "Champion",
            response_text,
        )

    def test_invalid_filename_returns_not_found(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.side_effect = (
                ChampionReferenceImageError(
                    "Invalid filename."
                )
            )

            response = self.client.get(
                "/champions/images/Annie.jpg"
            )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_windows_path_filename_is_rejected(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.side_effect = (
                ChampionReferenceImageError(
                    "Invalid filename."
                )
            )

            response = self.client.get(
                "/champions/images/folder%5CAnnie.png"
            )

        self.assertEqual(
            response.status_code,
            404,
        )

        service_class.return_value.resolve_image.assert_called_once_with(
            "folder\\Annie.png"
        )

    def test_unexpected_resolution_failure_returns_placeholder(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.side_effect = (
                RuntimeError(
                    "C:\\private\\champion_icons"
                )
            )

            response = self.client.get(
                "/champions/images/Annie.png"
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.mimetype,
            "image/svg+xml",
        )

        response_text = response.get_data(
            as_text=True
        )

        self.assertNotIn(
            "C:\\private",
            response_text,
        )

        self.assertNotIn(
            "champion_icons",
            response_text,
        )

    def test_image_is_rendered_inline(
        self
    ):
        with patch.object(
            image_route_module,
            "ChampionReferenceImageService",
        ) as service_class:
            service_class.return_value.resolve_image.return_value = {
                "active_source": "local_cache",
                "image_file": (
                    self.image_file
                ),
                "mime_type": "image/png",
                "placeholder": False,
            }

            response = self.client.get(
                "/champions/images/Annie.png"
            )

        try:
            content_disposition = (
                response.headers.get(
                    "Content-Disposition",
                    "",
                )
            )

            self.assertNotIn(
                "attachment",
                content_disposition.lower(),
            )
        finally:
            response.close()

    def test_route_rejects_post(
        self
    ):
        response = self.client.post(
            "/champions/images/Annie.png"
        )

        self.assertEqual(
            response.status_code,
            405,
        )


if __name__ == "__main__":
    unittest.main()
