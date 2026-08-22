import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from application.services.champion_reference_icon_download_service import (
    ChampionReferenceIconDownloadError,
    ChampionReferenceIconDownloadService,
)


class ChampionReferenceIconDownloadServiceTests(
    unittest.TestCase
):
    PNG_BYTES = (
        b"\x89PNG\r\n\x1a\n"
        b"test-champion-icon"
    )

    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.output_directory = Path(
            self.temporary_directory.name
        )

        self.service = (
            ChampionReferenceIconDownloadService()
        )

        self.version = "15.14.1"

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _build_champions():
        return [
            {
                "riot_champion_id": 1,
                "name": "Annie",
                "image_filename": "Annie.png",
            },
            {
                "riot_champion_id": 2,
                "name": "Olaf",
                "image_filename": "Olaf.png",
            },
        ]

    def _build_response(
        self,
        content=None,
    ):
        response = Mock()

        response.content = (
            content
            if content is not None
            else self.PNG_BYTES
        )

        return response

    def test_all_champion_icons_are_downloaded(
        self
    ):
        response = self._build_response()

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ):
            result = self.service.download_icons(
                champions=self._build_champions(),
                data_dragon_version=self.version,
                output_directory=(
                    self.output_directory
                ),
            )

        icons_directory = (
            self.output_directory
            / "champion_icons"
        )

        self.assertTrue(
            (
                icons_directory
                / "Annie.png"
            ).is_file()
        )

        self.assertTrue(
            (
                icons_directory
                / "Olaf.png"
            ).is_file()
        )

        self.assertEqual(
            (
                icons_directory
                / "Annie.png"
            ).read_bytes(),
            self.PNG_BYTES,
        )

        self.assertEqual(
            result["downloaded"],
            2,
        )

        self.assertEqual(
            result["icons_directory"],
            icons_directory.resolve(),
        )

    def test_expected_data_dragon_urls_are_used(
        self
    ):
        response = self._build_response()

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ) as get_mock:
            self.service.download_icons(
                champions=self._build_champions(),
                data_dragon_version=self.version,
                output_directory=(
                    self.output_directory
                ),
            )

        self.assertEqual(
            get_mock.call_args_list,
            [
                call(
                    (
                        "https://ddragon.leagueoflegends.com/"
                        "cdn/15.14.1/img/champion/Annie.png"
                    ),
                    timeout=15,
                ),
                call(
                    (
                        "https://ddragon.leagueoflegends.com/"
                        "cdn/15.14.1/img/champion/Olaf.png"
                    ),
                    timeout=15,
                ),
            ],
        )

        self.assertEqual(
            response.raise_for_status.call_count,
            2,
        )

    def test_download_order_is_deterministic(
        self
    ):
        champions = list(
            reversed(
                self._build_champions()
            )
        )

        response = self._build_response()

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ) as get_mock:
            self.service.download_icons(
                champions=champions,
                data_dragon_version=self.version,
                output_directory=(
                    self.output_directory
                ),
            )

        requested_urls = [
            current_call.args[0]
            for current_call in (
                get_mock.call_args_list
            )
        ]

        self.assertEqual(
            requested_urls,
            [
                (
                    "https://ddragon.leagueoflegends.com/"
                    "cdn/15.14.1/img/champion/Annie.png"
                ),
                (
                    "https://ddragon.leagueoflegends.com/"
                    "cdn/15.14.1/img/champion/Olaf.png"
                ),
            ],
        )

    def test_existing_icon_directory_is_replaced(
        self
    ):
        icons_directory = (
            self.output_directory
            / "champion_icons"
        )

        icons_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        old_icon = (
            icons_directory
            / "OldChampion.png"
        )

        old_icon.write_bytes(
            self.PNG_BYTES
        )

        response = self._build_response()

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ):
            self.service.download_icons(
                champions=self._build_champions(),
                data_dragon_version=self.version,
                output_directory=(
                    self.output_directory
                ),
            )

        self.assertFalse(
            old_icon.exists()
        )

        self.assertTrue(
            (
                icons_directory
                / "Annie.png"
            ).exists()
        )

        self.assertTrue(
            (
                icons_directory
                / "Olaf.png"
            ).exists()
        )

    def test_failed_download_preserves_existing_icons(
        self
    ):
        icons_directory = (
            self.output_directory
            / "champion_icons"
        )

        icons_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        old_icon = (
            icons_directory
            / "OldChampion.png"
        )

        old_icon.write_bytes(
            self.PNG_BYTES
        )

        valid_response = self._build_response()

        invalid_response = self._build_response(
            content=b"not-a-png"
        )

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            side_effect=[
                valid_response,
                invalid_response,
            ],
        ):
            with self.assertRaises(
                ChampionReferenceIconDownloadError
            ):
                self.service.download_icons(
                    champions=(
                        self._build_champions()
                    ),
                    data_dragon_version=(
                        self.version
                    ),
                    output_directory=(
                        self.output_directory
                    ),
                )

        self.assertTrue(
            old_icon.is_file()
        )

        self.assertEqual(
            old_icon.read_bytes(),
            self.PNG_BYTES,
        )

        self.assertFalse(
            (
                icons_directory
                / "Annie.png"
            ).exists()
        )

    def test_empty_image_response_is_rejected(
        self
    ):
        response = self._build_response(
            content=b""
        )

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ):
            with self.assertRaises(
                ChampionReferenceIconDownloadError
            ):
                self.service.download_icons(
                    champions=[
                        self._build_champions()[0]
                    ],
                    data_dragon_version=(
                        self.version
                    ),
                    output_directory=(
                        self.output_directory
                    ),
                )

    def test_non_png_response_is_rejected(
        self
    ):
        response = self._build_response(
            content=b"<html>error</html>"
        )

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ):
            with self.assertRaises(
                ChampionReferenceIconDownloadError
            ):
                self.service.download_icons(
                    champions=[
                        self._build_champions()[0]
                    ],
                    data_dragon_version=(
                        self.version
                    ),
                    output_directory=(
                        self.output_directory
                    ),
                )

    def test_invalid_data_dragon_version_is_rejected(
        self
    ):
        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
        ) as get_mock:
            with self.assertRaises(
                ChampionReferenceIconDownloadError
            ):
                self.service.download_icons(
                    champions=(
                        self._build_champions()
                    ),
                    data_dragon_version=(
                        "../15.14.1"
                    ),
                    output_directory=(
                        self.output_directory
                    ),
                )

        get_mock.assert_not_called()

    def test_empty_champion_collection_is_rejected(
        self
    ):
        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
        ) as get_mock:
            with self.assertRaises(
                ChampionReferenceIconDownloadError
            ):
                self.service.download_icons(
                    champions=[],
                    data_dragon_version=(
                        self.version
                    ),
                    output_directory=(
                        self.output_directory
                    ),
                )

        get_mock.assert_not_called()

    def test_invalid_champion_entry_is_rejected(
        self
    ):
        with self.assertRaises(
            ChampionReferenceIconDownloadError
        ):
            self.service.download_icons(
                champions=[
                    "not-a-champion",
                ],
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
            )

    def test_duplicate_champion_id_is_rejected(
        self
    ):
        champions = self._build_champions()

        champions[1][
            "riot_champion_id"
        ] = 1

        with self.assertRaises(
            ChampionReferenceIconDownloadError
        ):
            self.service.download_icons(
                champions=champions,
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
            )

    def test_duplicate_image_filename_is_rejected(
        self
    ):
        champions = self._build_champions()

        champions[1][
            "image_filename"
        ] = "Annie.png"

        with self.assertRaises(
            ChampionReferenceIconDownloadError
        ):
            self.service.download_icons(
                champions=champions,
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
            )

    def test_unsafe_image_filename_is_rejected(
        self
    ):
        champions = self._build_champions()

        champions[0][
            "image_filename"
        ] = "../Annie.png"

        with self.assertRaises(
            ChampionReferenceIconDownloadError
        ):
            self.service.download_icons(
                champions=champions,
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
            )

    def test_temporary_directories_are_removed_after_success(
        self
    ):
        response = self._build_response()

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ):
            self.service.download_icons(
                champions=self._build_champions(),
                data_dragon_version=self.version,
                output_directory=(
                    self.output_directory
                ),
            )

        self.assertFalse(
            (
                self.output_directory
                / "champion_icons.tmp"
            ).exists()
        )

        self.assertFalse(
            (
                self.output_directory
                / "champion_icons.previous"
            ).exists()
        )

    def test_temporary_directories_are_removed_after_failure(
        self
    ):
        response = self._build_response(
            content=b"not-a-png"
        )

        with patch(
            "application.services."
            "champion_reference_icon_download_service."
            "requests.get",
            return_value=response,
        ):
            with self.assertRaises(
                ChampionReferenceIconDownloadError
            ):
                self.service.download_icons(
                    champions=(
                        self._build_champions()
                    ),
                    data_dragon_version=(
                        self.version
                    ),
                    output_directory=(
                        self.output_directory
                    ),
                )

        self.assertFalse(
            (
                self.output_directory
                / "champion_icons.tmp"
            ).exists()
        )

        self.assertFalse(
            (
                self.output_directory
                / "champion_icons.previous"
            ).exists()
        )


if __name__ == "__main__":
    unittest.main()