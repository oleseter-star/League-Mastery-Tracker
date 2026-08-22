import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from application.services.champion_reference_update_service import (
    ChampionReferenceUpdateError,
    ChampionReferenceUpdateService,
)


class ChampionReferenceUpdateMergeServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.cache_directory = (
            self.root_directory
            / "reference"
            / "data_dragon"
        )

        self.data_dragon_service = Mock()
        self.build_service = Mock()
        self.source_service = Mock()
        self.merge_service = Mock()

        self.service = (
            ChampionReferenceUpdateService(
                data_dragon_service=(
                    self.data_dragon_service
                ),
                build_service=(
                    self.build_service
                ),
                source_service=(
                    self.source_service
                ),
                merge_service=(
                    self.merge_service
                ),
                local_cache_directory=(
                    self.cache_directory
                ),
            )
        )

        self.champion_data = {
            "version": "15.15.1",
            "data": {
                "Annie": {
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
            },
        }

        self.build_result = {
            "dataset_directory": (
                self.cache_directory.resolve()
            ),
            "icons_directory": (
                self.cache_directory
                / "champion_icons"
            ).resolve(),
            "manifest": {
                "data_dragon_version": (
                    "15.15.1"
                ),
                "locale": "en_US",
                "champion_count": 1,
            },
            "champions": [
                {
                    "riot_champion_id": 1,
                    "name": "Annie",
                    "image_filename": (
                        "Annie.png"
                    ),
                },
            ],
        }

        self.merge_result = {
            "created": 1,
            "updated": 0,
            "unchanged": 0,
            "preserved_manual": 0,
            "preserved_existing": 0,
            "active_source": "local_cache",
            "data_dragon_version": (
                "15.15.1"
            ),
            "locale": "en_US",
            "dataset_count": 1,
            "database_count": 1,
        }

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _configure_update(
        self,
        current_version="15.14.1",
        latest_version="15.15.1",
    ):
        self.source_service.select_source.return_value = {
            "active_source": "bundled",
            "dataset": {
                "manifest": {
                    "data_dragon_version": (
                        current_version
                    ),
                },
            },
            "data_dragon_version": (
                current_version
            ),
            "locale": "en_US",
            "dataset_directory": (
                self.root_directory
                / "bundled"
            ),
            "icons_directory": (
                self.root_directory
                / "bundled"
                / "champion_icons"
            ),
            "warnings": [],
        }

        self.data_dragon_service.get_latest_version.return_value = (
            latest_version
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        self.merge_service.merge_dataset.return_value = (
            self.merge_result
        )

    def test_updated_dataset_is_merged_into_database(
        self
    ):
        self._configure_update()

        self.service.update_reference_data()

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )

    def test_merge_result_is_returned(
        self
    ):
        self._configure_update()

        result = (
            self.service.update_reference_data()
        )

        self.assertEqual(
            result["merge"],
            self.merge_result,
        )

        self.assertEqual(
            result["dataset"],
            self.build_result,
        )

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

    def test_current_version_skips_database_merge(
        self
    ):
        self._configure_update(
            current_version="15.15.1",
            latest_version="15.15.1",
        )

        result = (
            self.service.update_reference_data()
        )

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["status"],
            "current",
        )

        self.assertIsNone(
            result["merge"]
        )

    def test_forced_equal_version_is_merged(
        self
    ):
        self._configure_update(
            current_version="15.15.1",
            latest_version="15.15.1",
        )

        result = (
            self.service.update_reference_data(
                force=True
            )
        )

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )

        self.assertEqual(
            result["status"],
            "updated",
        )

        self.assertTrue(
            result["forced"]
        )

    def test_build_failure_skips_database_merge(
        self
    ):
        self._configure_update()

        self.build_service.build_dataset.side_effect = (
            RuntimeError(
                "build failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceUpdateError
        ):
            self.service.update_reference_data()

        self.merge_service.merge_dataset.assert_not_called()

    def test_database_merge_failure_is_controlled(
        self
    ):
        self._configure_update()

        self.merge_service.merge_dataset.side_effect = (
            RuntimeError(
                "database merge failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceUpdateError
        ):
            self.service.update_reference_data()

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )


if __name__ == "__main__":
    unittest.main()