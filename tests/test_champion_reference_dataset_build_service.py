import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call

from application.services.champion_reference_dataset_build_service import (
    ChampionReferenceDatasetBuildError,
    ChampionReferenceDatasetBuildService,
)


class ChampionReferenceDatasetBuildServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.output_directory = (
            self.root_directory
            / "data_dragon"
        )

        self.staging_directory = (
            self.root_directory
            / "data_dragon.tmp"
        )

        self.previous_directory = (
            self.root_directory
            / "data_dragon.previous"
        )

        self.generator_service = Mock()
        self.icon_download_service = Mock()
        self.dataset_service = Mock()

        self.service = (
            ChampionReferenceDatasetBuildService(
                generator_service=(
                    self.generator_service
                ),
                icon_download_service=(
                    self.icon_download_service
                ),
                dataset_service=(
                    self.dataset_service
                ),
            )
        )

        self.champion_data = {
            "data": {
                "Annie": {
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
                "Olaf": {
                    "key": "2",
                    "name": "Olaf",
                    "image": {
                        "full": "Olaf.png",
                    },
                },
            },
        }

        self.generated_champions = [
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

        self.version = "15.14.1"
        self.generated_at = object()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _configure_successful_generator(
        self
    ):
        def generate_dataset(
            champion_data,
            data_dragon_version,
            output_directory,
            generated_at,
        ):
            output_path = Path(
                output_directory
            )

            output_path.mkdir(
                parents=True,
                exist_ok=True,
            )

            (
                output_path
                / "new-dataset.txt"
            ).write_text(
                "new",
                encoding="utf-8",
            )

            return {
                "champions": (
                    self.generated_champions
                ),
                "output_directory": (
                    output_path.resolve()
                ),
            }

        self.generator_service.generate_dataset.side_effect = (
            generate_dataset
        )

    def _configure_successful_validation(
        self
    ):
        def load_dataset(
            dataset_directory,
        ):
            resolved_directory = Path(
                dataset_directory
            ).resolve()

            return {
                "dataset_directory": (
                    resolved_directory
                ),
                "manifest": {
                    "data_dragon_version": (
                        self.version
                    ),
                },
                "champions": (
                    self.generated_champions
                ),
            }

        self.dataset_service.load_dataset.side_effect = (
            load_dataset
        )

    def _create_existing_dataset(
        self,
    ):
        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        marker_file = (
            self.output_directory
            / "existing-dataset.txt"
        )

        marker_file.write_text(
            "existing",
            encoding="utf-8",
        )

        return marker_file

    def test_successful_build_uses_staging_and_returns_final_dataset(
        self
    ):
        self._configure_successful_generator()
        self._configure_successful_validation()

        result = self.service.build_dataset(
            champion_data=self.champion_data,
            data_dragon_version=self.version,
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        self.assertEqual(
            self.dataset_service.load_dataset.call_args_list,
            [
                call(
                    self.staging_directory
                ),
                call(
                    self.output_directory
                ),
            ],
        )

        self.assertEqual(
            result["dataset_directory"],
            self.output_directory.resolve(),
        )

        self.assertEqual(
            result["manifest"][
                "data_dragon_version"
            ],
            self.version,
        )

        self.assertTrue(
            (
                self.output_directory
                / "new-dataset.txt"
            ).is_file()
        )

    def test_generator_receives_build_inputs(
        self
    ):
        self._configure_successful_generator()
        self._configure_successful_validation()

        self.service.build_dataset(
            champion_data=self.champion_data,
            data_dragon_version=self.version,
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        self.generator_service.generate_dataset.assert_called_once_with(
            champion_data=self.champion_data,
            data_dragon_version=self.version,
            output_directory=(
                self.staging_directory
            ),
            generated_at=self.generated_at,
        )

    def test_icon_downloader_receives_generated_champions(
        self
    ):
        self._configure_successful_generator()
        self._configure_successful_validation()

        self.service.build_dataset(
            champion_data=self.champion_data,
            data_dragon_version=self.version,
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        self.icon_download_service.download_icons.assert_called_once_with(
            champions=self.generated_champions,
            data_dragon_version=self.version,
            output_directory=(
                self.staging_directory
            ),
        )

    def test_existing_dataset_remains_until_staging_validation_succeeds(
        self
    ):
        existing_marker = (
            self._create_existing_dataset()
        )

        self._configure_successful_generator()

        validation_count = 0

        def load_dataset(
            dataset_directory,
        ):
            nonlocal validation_count

            validation_count += 1

            resolved_directory = Path(
                dataset_directory
            ).resolve()

            if validation_count == 1:
                self.assertEqual(
                    resolved_directory,
                    self.staging_directory.resolve(),
                )

                self.assertTrue(
                    existing_marker.is_file()
                )

                self.assertTrue(
                    (
                        self.staging_directory
                        / "new-dataset.txt"
                    ).is_file()
                )

            return {
                "dataset_directory": (
                    resolved_directory
                ),
                "manifest": {},
                "champions": (
                    self.generated_champions
                ),
            }

        self.dataset_service.load_dataset.side_effect = (
            load_dataset
        )

        self.service.build_dataset(
            champion_data=self.champion_data,
            data_dragon_version=self.version,
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        self.assertFalse(
            existing_marker.exists()
        )

        self.assertTrue(
            (
                self.output_directory
                / "new-dataset.txt"
            ).is_file()
        )

    def test_generator_failure_preserves_existing_dataset(
        self
    ):
        existing_marker = (
            self._create_existing_dataset()
        )

        self.generator_service.generate_dataset.side_effect = (
            RuntimeError(
                "generator failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceDatasetBuildError
        ):
            self.service.build_dataset(
                champion_data=(
                    self.champion_data
                ),
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=(
                    self.generated_at
                ),
            )

        self.assertTrue(
            existing_marker.is_file()
        )

    def test_icon_failure_preserves_existing_dataset(
        self
    ):
        existing_marker = (
            self._create_existing_dataset()
        )

        self._configure_successful_generator()

        self.icon_download_service.download_icons.side_effect = (
            RuntimeError(
                "icon download failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceDatasetBuildError
        ):
            self.service.build_dataset(
                champion_data=(
                    self.champion_data
                ),
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=(
                    self.generated_at
                ),
            )

        self.assertTrue(
            existing_marker.is_file()
        )

    def test_staging_validation_failure_preserves_existing_dataset(
        self
    ):
        existing_marker = (
            self._create_existing_dataset()
        )

        self._configure_successful_generator()

        self.dataset_service.load_dataset.side_effect = (
            RuntimeError(
                "staging validation failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceDatasetBuildError
        ):
            self.service.build_dataset(
                champion_data=(
                    self.champion_data
                ),
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=(
                    self.generated_at
                ),
            )

        self.assertTrue(
            existing_marker.is_file()
        )

    def test_final_validation_failure_restores_existing_dataset(
        self
    ):
        existing_marker = (
            self._create_existing_dataset()
        )

        self._configure_successful_generator()

        self.dataset_service.load_dataset.side_effect = [
            {
                "dataset_directory": (
                    self.staging_directory.resolve()
                ),
                "manifest": {},
                "champions": (
                    self.generated_champions
                ),
            },
            RuntimeError(
                "final validation failed"
            ),
        ]

        with self.assertRaises(
            ChampionReferenceDatasetBuildError
        ):
            self.service.build_dataset(
                champion_data=(
                    self.champion_data
                ),
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=(
                    self.generated_at
                ),
            )

        self.assertTrue(
            existing_marker.is_file()
        )

        self.assertFalse(
            (
                self.output_directory
                / "new-dataset.txt"
            ).exists()
        )

    def test_interrupted_previous_dataset_is_recovered_before_build(
        self
    ):
        self.previous_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        previous_marker = (
            self.previous_directory
            / "previous-dataset.txt"
        )

        previous_marker.write_text(
            "previous",
            encoding="utf-8",
        )

        self.generator_service.generate_dataset.side_effect = (
            RuntimeError(
                "generator failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceDatasetBuildError
        ):
            self.service.build_dataset(
                champion_data=(
                    self.champion_data
                ),
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=(
                    self.generated_at
                ),
            )

        self.assertTrue(
            (
                self.output_directory
                / "previous-dataset.txt"
            ).is_file()
        )

        self.assertFalse(
            self.previous_directory.exists()
        )

    def test_temporary_directories_are_removed_after_success(
        self
    ):
        self._configure_successful_generator()
        self._configure_successful_validation()

        self.service.build_dataset(
            champion_data=self.champion_data,
            data_dragon_version=self.version,
            output_directory=(
                self.output_directory
            ),
            generated_at=self.generated_at,
        )

        self.assertFalse(
            self.staging_directory.exists()
        )

        self.assertFalse(
            self.previous_directory.exists()
        )

    def test_temporary_directories_are_removed_after_failure(
        self
    ):
        self._create_existing_dataset()
        self._configure_successful_generator()

        self.icon_download_service.download_icons.side_effect = (
            RuntimeError(
                "icon download failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceDatasetBuildError
        ):
            self.service.build_dataset(
                champion_data=(
                    self.champion_data
                ),
                data_dragon_version=(
                    self.version
                ),
                output_directory=(
                    self.output_directory
                ),
                generated_at=(
                    self.generated_at
                ),
            )

        self.assertFalse(
            self.staging_directory.exists()
        )

        self.assertFalse(
            self.previous_directory.exists()
        )


if __name__ == "__main__":
    unittest.main()