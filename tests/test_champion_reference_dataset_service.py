import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from application.services.champion_reference_dataset_service import (
    ChampionReferenceDatasetError,
    ChampionReferenceDatasetService,
)


class ChampionReferenceDatasetServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.dataset_directory = Path(
            self.temporary_directory.name
        )

        self.icons_directory = (
            self.dataset_directory
            / "champion_icons"
        )

        self.icons_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.service = (
            ChampionReferenceDatasetService()
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _build_champions(
        self,
    ):
        return {
            "champions": [
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
            ],
        }

    def _write_dataset(
        self,
        champions=None,
        manifest_overrides=None,
        create_icons=True,
    ):
        if champions is None:
            champions = self._build_champions()

        champion_file = (
            self.dataset_directory
            / "champions.json"
        )

        champion_bytes = json.dumps(
            champions,
            ensure_ascii=False,
            indent=2,
        ).encode(
            "utf-8"
        )

        champion_file.write_bytes(
            champion_bytes
        )

        if create_icons:
            for champion in champions.get(
                "champions",
                [],
            ):
                image_filename = champion.get(
                    "image_filename"
                )

                if (
                    isinstance(
                        image_filename,
                        str,
                    )
                    and image_filename
                    and Path(
                        image_filename
                    ).name
                    == image_filename
                ):
                    (
                        self.icons_directory
                        / image_filename
                    ).write_bytes(
                        b"test-image"
                    )

        manifest = {
            "format": (
                "league_mastery_tracker_"
                "champion_reference"
            ),
            "format_version": 1,
            "data_dragon_version": "15.14.1",
            "locale": "en_US",
            "champion_count": len(
                champions.get(
                    "champions",
                    [],
                )
            ),
            "source": "riot_data_dragon",
            "generated_at": (
                "2026-07-23T00:00:00+00:00"
            ),
            "champions_sha256": (
                hashlib.sha256(
                    champion_bytes
                ).hexdigest()
            ),
        }

        if manifest_overrides:
            manifest.update(
                manifest_overrides
            )

        manifest_file = (
            self.dataset_directory
            / "manifest.json"
        )

        manifest_file.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "manifest": manifest,
            "champions": champions,
        }

    def test_valid_dataset_is_loaded(
        self
    ):
        expected = self._write_dataset()

        result = self.service.load_dataset(
            self.dataset_directory
        )

        self.assertEqual(
            result["manifest"],
            expected["manifest"],
        )

        self.assertEqual(
            result["champions"],
            expected["champions"][
                "champions"
            ],
        )

        self.assertEqual(
            result["dataset_directory"],
            self.dataset_directory.resolve(),
        )

        self.assertEqual(
            result["icons_directory"],
            self.icons_directory.resolve(),
        )

    def test_missing_manifest_is_rejected(
        self
    ):
        champions = self._build_champions()

        (
            self.dataset_directory
            / "champions.json"
        ).write_text(
            json.dumps(
                champions
            ),
            encoding="utf-8",
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_unsupported_format_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "format": "unsupported",
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_unsupported_format_version_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "format_version": 999,
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_invalid_data_dragon_version_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "data_dragon_version": (
                    "../15.14.1"
                ),
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_unsupported_locale_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "locale": "nb_NO",
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_invalid_generated_timestamp_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "generated_at": (
                    "not-a-timestamp"
                ),
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_checksum_mismatch_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "champions_sha256": (
                    "0" * 64
                ),
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_champion_count_mismatch_is_rejected(
        self
    ):
        self._write_dataset(
            manifest_overrides={
                "champion_count": 999,
            }
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_duplicate_champion_id_is_rejected(
        self
    ):
        champions = {
            "champions": [
                {
                    "riot_champion_id": 1,
                    "name": "Annie",
                    "image_filename": "Annie.png",
                },
                {
                    "riot_champion_id": 1,
                    "name": "Duplicate Annie",
                    "image_filename": (
                        "DuplicateAnnie.png"
                    ),
                },
            ],
        }

        self._write_dataset(
            champions=champions
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_non_positive_champion_id_is_rejected(
        self
    ):
        champions = self._build_champions()

        champions[
            "champions"
        ][0][
            "riot_champion_id"
        ] = 0

        self._write_dataset(
            champions=champions
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_empty_champion_name_is_rejected(
        self
    ):
        champions = self._build_champions()

        champions[
            "champions"
        ][0][
            "name"
        ] = "   "

        self._write_dataset(
            champions=champions
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_unsafe_image_filename_is_rejected(
        self
    ):
        champions = self._build_champions()

        champions[
            "champions"
        ][0][
            "image_filename"
        ] = "../Annie.png"

        self._write_dataset(
            champions=champions
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_missing_champion_icon_is_rejected(
        self
    ):
        self._write_dataset(
            create_icons=False
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_unsorted_champions_are_rejected(
        self
    ):
        champions = {
            "champions": [
                {
                    "riot_champion_id": 2,
                    "name": "Olaf",
                    "image_filename": "Olaf.png",
                },
                {
                    "riot_champion_id": 1,
                    "name": "Annie",
                    "image_filename": "Annie.png",
                },
            ],
        }

        self._write_dataset(
            champions=champions
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )

    def test_invalid_champion_json_is_rejected(
        self
    ):
        self._write_dataset()

        (
            self.dataset_directory
            / "champions.json"
        ).write_text(
            "{invalid-json",
            encoding="utf-8",
        )

        with self.assertRaises(
            ChampionReferenceDatasetError
        ):
            self.service.load_dataset(
                self.dataset_directory
            )


if __name__ == "__main__":
    unittest.main()