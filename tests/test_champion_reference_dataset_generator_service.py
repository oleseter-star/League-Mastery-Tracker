import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from application.services.champion_reference_dataset_generator_service import (
    ChampionReferenceDatasetGeneratorError,
    ChampionReferenceDatasetGeneratorService,
)


class ChampionReferenceDatasetGeneratorServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.output_directory = Path(
            self.temporary_directory.name
        )

        self.service = (
            ChampionReferenceDatasetGeneratorService()
        )

        self.generated_at = datetime(
            2026,
            7,
            23,
            12,
            30,
            45,
            tzinfo=timezone.utc,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _build_data_dragon_document():
        return {
            "type": "champion",
            "format": "standAloneComplex",
            "version": "15.14.1",
            "data": {
                "Olaf": {
                    "id": "Olaf",
                    "key": "2",
                    "name": "Olaf",
                    "image": {
                        "full": "Olaf.png",
                    },
                },
                "Annie": {
                    "id": "Annie",
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
            },
        }

    def test_dataset_files_are_generated(
        self
    ):
        result = self.service.generate_dataset(
            champion_data=(
                self._build_data_dragon_document()
            ),
            data_dragon_version="15.14.1",
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        manifest_file = (
            self.output_directory
            / "manifest.json"
        )

        champions_file = (
            self.output_directory
            / "champions.json"
        )

        icons_directory = (
            self.output_directory
            / "champion_icons"
        )

        self.assertTrue(
            manifest_file.is_file()
        )

        self.assertTrue(
            champions_file.is_file()
        )

        self.assertTrue(
            icons_directory.is_dir()
        )

        self.assertEqual(
            result["manifest_file"],
            manifest_file.resolve(),
        )

        self.assertEqual(
            result["champions_file"],
            champions_file.resolve(),
        )

        self.assertEqual(
            result["icons_directory"],
            icons_directory.resolve(),
        )

    def test_champions_are_sorted_by_riot_id(
        self
    ):
        self.service.generate_dataset(
            champion_data=(
                self._build_data_dragon_document()
            ),
            data_dragon_version="15.14.1",
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        champions_document = json.loads(
            (
                self.output_directory
                / "champions.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            champions_document,
            {
                "champions": [
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                    {
                        "riot_champion_id": 2,
                        "name": "Olaf",
                        "image_filename": (
                            "Olaf.png"
                        ),
                    },
                ],
            },
        )

    def test_manifest_contains_dataset_metadata(
        self
    ):
        self.service.generate_dataset(
            champion_data=(
                self._build_data_dragon_document()
            ),
            data_dragon_version="15.14.1",
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        manifest = json.loads(
            (
                self.output_directory
                / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            manifest["format"],
            (
                "league_mastery_tracker_"
                "champion_reference"
            ),
        )

        self.assertEqual(
            manifest["format_version"],
            1,
        )

        self.assertEqual(
            manifest["data_dragon_version"],
            "15.14.1",
        )

        self.assertEqual(
            manifest["locale"],
            "en_US",
        )

        self.assertEqual(
            manifest["champion_count"],
            2,
        )

        self.assertEqual(
            manifest["source"],
            "riot_data_dragon",
        )

        self.assertEqual(
            manifest["generated_at"],
            "2026-07-23T12:30:45+00:00",
        )

    def test_manifest_checksum_matches_champion_file(
        self
    ):
        self.service.generate_dataset(
            champion_data=(
                self._build_data_dragon_document()
            ),
            data_dragon_version="15.14.1",
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        champion_bytes = (
            self.output_directory
            / "champions.json"
        ).read_bytes()

        manifest = json.loads(
            (
                self.output_directory
                / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        expected_checksum = hashlib.sha256(
            champion_bytes
        ).hexdigest()

        self.assertEqual(
            manifest["champions_sha256"],
            expected_checksum,
        )

    def test_generation_is_deterministic(
        self
    ):
        first_directory = (
            self.output_directory
            / "first"
        )

        second_directory = (
            self.output_directory
            / "second"
        )

        champion_data = (
            self._build_data_dragon_document()
        )

        self.service.generate_dataset(
            champion_data=champion_data,
            data_dragon_version="15.14.1",
            output_directory=first_directory,
            generated_at=self.generated_at,
        )

        self.service.generate_dataset(
            champion_data=champion_data,
            data_dragon_version="15.14.1",
            output_directory=second_directory,
            generated_at=self.generated_at,
        )

        self.assertEqual(
            (
                first_directory
                / "champions.json"
            ).read_bytes(),
            (
                second_directory
                / "champions.json"
            ).read_bytes(),
        )

        self.assertEqual(
            (
                first_directory
                / "manifest.json"
            ).read_bytes(),
            (
                second_directory
                / "manifest.json"
            ).read_bytes(),
        )

    def test_existing_generated_files_are_replaced(
        self
    ):
        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        (
            self.output_directory
            / "champions.json"
        ).write_text(
            "old champions",
            encoding="utf-8",
        )

        (
            self.output_directory
            / "manifest.json"
        ).write_text(
            "old manifest",
            encoding="utf-8",
        )

        self.service.generate_dataset(
            champion_data=(
                self._build_data_dragon_document()
            ),
            data_dragon_version="15.14.1",
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        champions_document = json.loads(
            (
                self.output_directory
                / "champions.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        manifest = json.loads(
            (
                self.output_directory
                / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            len(
                champions_document[
                    "champions"
                ]
            ),
            2,
        )

        self.assertEqual(
            manifest["champion_count"],
            2,
        )

    def test_temporary_files_are_removed_after_success(
        self
    ):
        self.service.generate_dataset(
            champion_data=(
                self._build_data_dragon_document()
            ),
            data_dragon_version="15.14.1",
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        self.assertFalse(
            (
                self.output_directory
                / "champions.json.tmp"
            ).exists()
        )

        self.assertFalse(
            (
                self.output_directory
                / "manifest.json.tmp"
            ).exists()
        )

    def test_missing_data_collection_is_rejected(
        self
    ):
        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data={
                    "version": "15.14.1",
                },
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_empty_data_collection_is_rejected(
        self
    ):
        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data={
                    "data": {},
                },
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_duplicate_champion_id_is_rejected(
        self
    ):
        champion_data = (
            self._build_data_dragon_document()
        )

        champion_data["data"]["Duplicate"] = {
            "id": "Duplicate",
            "key": "1",
            "name": "Duplicate Annie",
            "image": {
                "full": "DuplicateAnnie.png",
            },
        }

        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data=champion_data,
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_invalid_champion_id_is_rejected(
        self
    ):
        champion_data = (
            self._build_data_dragon_document()
        )

        champion_data[
            "data"
        ][
            "Annie"
        ][
            "key"
        ] = "invalid"

        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data=champion_data,
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_empty_champion_name_is_rejected(
        self
    ):
        champion_data = (
            self._build_data_dragon_document()
        )

        champion_data[
            "data"
        ][
            "Annie"
        ][
            "name"
        ] = "   "

        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data=champion_data,
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_unsafe_image_filename_is_rejected(
        self
    ):
        champion_data = (
            self._build_data_dragon_document()
        )

        champion_data[
            "data"
        ][
            "Annie"
        ][
            "image"
        ][
            "full"
        ] = "../Annie.png"

        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data=champion_data,
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_invalid_data_dragon_version_is_rejected(
        self
    ):
        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data=(
                    self._build_data_dragon_document()
                ),
                data_dragon_version=(
                    "../15.14.1"
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=self.generated_at,
            )

    def test_naive_generated_timestamp_is_rejected(
        self
    ):
        with self.assertRaises(
            ChampionReferenceDatasetGeneratorError
        ):
            self.service.generate_dataset(
                champion_data=(
                    self._build_data_dragon_document()
                ),
                data_dragon_version="15.14.1",
                output_directory=(
                    self.output_directory
                ),
                generated_at=datetime(
                    2026,
                    7,
                    23,
                    12,
                    30,
                    45,
                ),
            )


if __name__ == "__main__":
    unittest.main()