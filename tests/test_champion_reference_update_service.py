import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from flask import Flask

from application.services.champion_reference_update_service import (
    ChampionReferenceUpdateError,
    ChampionReferenceUpdateService,
)


class ChampionReferenceUpdateServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.reference_directory = (
            self.root_directory
            / "reference"
        )

        self.cache_directory = (
            self.reference_directory
            / "data_dragon"
        )

        self.data_dragon_service = Mock()
        self.build_service = Mock()
        self.source_service = Mock()
        self.merge_service = Mock()

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

        self.merge_service.merge_dataset.return_value = (
            self.merge_result
        )

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

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _configure_current_source(
        self,
        version="15.14.1",
        active_source="bundled",
    ):
        self.source_service.select_source.return_value = {
            "active_source": active_source,
            "dataset": {
                "manifest": {
                    "data_dragon_version": (
                        version
                    ),
                },
            },
            "data_dragon_version": version,
            "locale": "en_US",
            "dataset_directory": (
                self.root_directory
                / active_source
            ),
            "icons_directory": (
                self.root_directory
                / active_source
                / "champion_icons"
            ),
            "warnings": [],
        }

    def test_newer_version_is_downloaded_and_built(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        result = (
            self.service.update_reference_data()
        )

        self.data_dragon_service.get_latest_version.assert_called_once_with()

        self.data_dragon_service.download_champion_data.assert_called_once_with(
            "15.15.1"
        )

        self.assertEqual(
            self.build_service
            .build_dataset
            .call_count,
            1,
        )

        build_call = (
            self.build_service
            .build_dataset
            .call_args
        )

        self.assertEqual(
            build_call.kwargs[
                "champion_data"
            ],
            self.champion_data,
        )

        self.assertEqual(
            build_call.kwargs[
                "data_dragon_version"
            ],
            "15.15.1",
        )

        self.assertEqual(
            build_call.kwargs[
                "output_directory"
            ],
            self.cache_directory,
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
            result["updated"]
        )

        self.assertEqual(
            result["previous_version"],
            "15.14.1",
        )

        self.assertEqual(
            result["data_dragon_version"],
            "15.15.1",
        )

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["dataset"],
            self.build_result,
        )

        self.assertEqual(
            result["merge"],
            self.merge_result,
        )

    def test_current_version_skips_download_and_build(
        self
    ):
        self._configure_current_source(
            version="15.15.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        result = (
            self.service.update_reference_data()
        )

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["status"],
            "current",
        )

        self.assertFalse(
            result["updated"]
        )

        self.assertEqual(
            result["previous_version"],
            "15.15.1",
        )

        self.assertEqual(
            result["data_dragon_version"],
            "15.15.1",
        )

        self.assertIsNone(
            result["dataset"]
        )

        self.assertIsNone(
            result["merge"]
        )

    def test_newer_comparison_is_numeric(
        self
    ):
        self._configure_current_source(
            version="15.9.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.10.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        result = (
            self.service.update_reference_data()
        )

        self.assertEqual(
            result["status"],
            "updated",
        )

        self.data_dragon_service.download_champion_data.assert_called_once_with(
            "15.10.1"
        )

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )

    def test_older_remote_version_does_not_replace_current_data(
        self
    ):
        self._configure_current_source(
            version="15.15.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.14.1"
        )

        result = (
            self.service.update_reference_data()
        )

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["status"],
            "current",
        )

        self.assertEqual(
            result["data_dragon_version"],
            "15.15.1",
        )

    def test_force_update_downloads_equal_version(
        self
    ):
        self._configure_current_source(
            version="15.15.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        result = (
            self.service.update_reference_data(
                force=True
            )
        )

        self.data_dragon_service.download_champion_data.assert_called_once_with(
            "15.15.1"
        )

        self.build_service.build_dataset.assert_called_once()

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )

        self.assertEqual(
            result["status"],
            "updated",
        )

        self.assertTrue(
            result["updated"]
        )

        self.assertTrue(
            result["forced"]
        )

    def test_database_fallback_downloads_latest_dataset(
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

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        result = (
            self.service.update_reference_data()
        )

        self.assertIsNone(
            result["previous_version"]
        )

        self.assertEqual(
            result["status"],
            "updated",
        )

        self.build_service.build_dataset.assert_called_once()

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )

    def test_build_receives_aware_utc_timestamp(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        self.service.update_reference_data()

        generated_at = (
            self.build_service
            .build_dataset
            .call_args
            .kwargs[
                "generated_at"
            ]
        )

        self.assertIsInstance(
            generated_at,
            datetime,
        )

        self.assertIsNotNone(
            generated_at.tzinfo
        )

        self.assertEqual(
            generated_at.utcoffset(),
            timezone.utc.utcoffset(
                generated_at
            ),
        )

    def test_invalid_latest_version_is_rejected_before_download(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "../15.15.1"
        )

        with self.assertRaises(
            ChampionReferenceUpdateError
        ):
            self.service.update_reference_data()

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

    def test_source_selection_failure_is_controlled(
        self
    ):
        self.source_service.select_source.side_effect = (
            RuntimeError(
                "source selection failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceUpdateError
        ):
            self.service.update_reference_data()

        self.data_dragon_service.get_latest_version.assert_not_called()

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

    def test_latest_version_failure_is_controlled(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.side_effect = (
            RuntimeError(
                "network failure"
            )
        )

        with self.assertRaises(
            ChampionReferenceUpdateError
        ):
            self.service.update_reference_data()

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

    def test_champion_download_failure_is_controlled(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.side_effect = (
            RuntimeError(
                "download failed"
            )
        )

        with self.assertRaises(
            ChampionReferenceUpdateError
        ):
            self.service.update_reference_data()

        self.build_service.build_dataset.assert_not_called()

        self.merge_service.merge_dataset.assert_not_called()

    def test_build_failure_is_controlled(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

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

    def test_default_cache_directory_uses_reference_configuration(
        self
    ):
        app = Flask(
            __name__
        )

        app.config[
            "REFERENCE_DIR"
        ] = str(
            self.reference_directory
        )

        service = (
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
            )
        )

        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        with app.app_context():
            service.update_reference_data()

        self.assertEqual(
            self.build_service
            .build_dataset
            .call_args
            .kwargs[
                "output_directory"
            ],
            self.cache_directory,
        )

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.build_result,
            active_source="local_cache",
        )

    def test_generated_timestamp_can_be_injected(
        self
    ):
        self._configure_current_source(
            version="15.14.1"
        )

        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.build_service.build_dataset.return_value = (
            self.build_result
        )

        expected_timestamp = datetime(
            2026,
            7,
            23,
            14,
            15,
            16,
            tzinfo=timezone.utc,
        )

        with patch(
            "application.services."
            "champion_reference_update_service."
            "datetime"
        ) as datetime_mock:
            datetime_mock.now.return_value = (
                expected_timestamp
            )

            datetime_mock.side_effect = (
                lambda *args, **kwargs: datetime(
                    *args,
                    **kwargs
                )
            )

            self.service.update_reference_data()

        self.assertEqual(
            self.build_service
            .build_dataset
            .call_args
            .kwargs[
                "generated_at"
            ],
            expected_timestamp,
        )


if __name__ == "__main__":
    unittest.main()