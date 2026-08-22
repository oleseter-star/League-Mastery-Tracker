import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from application.services.champion_reference_bundle_build_service import (
    ChampionReferenceBundleBuildError,
    ChampionReferenceBundleBuildService,
)


class ChampionReferenceBundleBuildServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.bundled_directory = (
            self.root_directory
            / "application"
            / "bundled_reference_data"
            / "data_dragon"
        )

        self.data_dragon_service = Mock()
        self.dataset_build_service = Mock()
        self.resource_service = Mock()

        self.resource_service.get_dataset_directory.return_value = (
            self.bundled_directory
        )

        self.service = (
            ChampionReferenceBundleBuildService(
                data_dragon_service=(
                    self.data_dragon_service
                ),
                dataset_build_service=(
                    self.dataset_build_service
                ),
                resource_service=(
                    self.resource_service
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
                self.bundled_directory.resolve()
            ),
            "icons_directory": (
                self.bundled_directory
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

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _configure_success(
        self,
        version="15.15.1",
    ):
        self.data_dragon_service.get_latest_version.return_value = (
            version
        )

        self.data_dragon_service.download_champion_data.return_value = (
            self.champion_data
        )

        self.dataset_build_service.build_dataset.return_value = (
            self.build_result
        )

    def test_latest_data_dragon_version_is_downloaded(
        self
    ):
        self._configure_success()

        self.service.build_bundled_dataset()

        self.data_dragon_service.get_latest_version.assert_called_once_with()

        self.data_dragon_service.download_champion_data.assert_called_once_with(
            "15.15.1"
        )

    def test_resource_service_supplies_output_directory(
        self
    ):
        self._configure_success()

        self.service.build_bundled_dataset()

        self.resource_service.get_dataset_directory.assert_called_once_with()

        self.assertEqual(
            self.dataset_build_service
            .build_dataset
            .call_args
            .kwargs[
                "output_directory"
            ],
            self.bundled_directory,
        )

    def test_dataset_builder_receives_downloaded_data(
        self
    ):
        self._configure_success()

        self.service.build_bundled_dataset()

        build_call = (
            self.dataset_build_service
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

    def test_builder_receives_aware_utc_timestamp(
        self
    ):
        self._configure_success()

        self.service.build_bundled_dataset()

        generated_at = (
            self.dataset_build_service
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

    def test_successful_result_contains_build_metadata(
        self
    ):
        self._configure_success()

        result = (
            self.service.build_bundled_dataset()
        )

        self.assertEqual(
            result,
            {
                "status": "built",
                "data_dragon_version": (
                    "15.15.1"
                ),
                "dataset_directory": (
                    self.bundled_directory.resolve()
                ),
                "dataset": self.build_result,
            },
        )

    def test_generated_timestamp_can_be_injected(
        self
    ):
        self._configure_success()

        expected_timestamp = datetime(
            2026,
            7,
            23,
            18,
            30,
            45,
            tzinfo=timezone.utc,
        )

        with patch(
            "application.services."
            "champion_reference_bundle_build_service."
            "datetime"
        ) as datetime_mock:
            datetime_mock.now.return_value = (
                expected_timestamp
            )

            self.service.build_bundled_dataset()

        self.assertEqual(
            self.dataset_build_service
            .build_dataset
            .call_args
            .kwargs[
                "generated_at"
            ],
            expected_timestamp,
        )

    def test_invalid_latest_version_is_rejected_before_download(
        self
    ):
        self.data_dragon_service.get_latest_version.return_value = (
            "../15.15.1"
        )

        with self.assertRaises(
            ChampionReferenceBundleBuildError
        ):
            self.service.build_bundled_dataset()

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.dataset_build_service.build_dataset.assert_not_called()

    def test_latest_version_failure_is_controlled(
        self
    ):
        self.data_dragon_service.get_latest_version.side_effect = (
            RuntimeError(
                "network failure"
            )
        )

        with self.assertRaises(
            ChampionReferenceBundleBuildError
        ):
            self.service.build_bundled_dataset()

        self.data_dragon_service.download_champion_data.assert_not_called()

        self.dataset_build_service.build_dataset.assert_not_called()

    def test_download_failure_is_controlled(
        self
    ):
        self.data_dragon_service.get_latest_version.return_value = (
            "15.15.1"
        )

        self.data_dragon_service.download_champion_data.side_effect = (
            RuntimeError(
                "download failure"
            )
        )

        with self.assertRaises(
            ChampionReferenceBundleBuildError
        ):
            self.service.build_bundled_dataset()

        self.dataset_build_service.build_dataset.assert_not_called()

    def test_build_failure_is_controlled(
        self
    ):
        self._configure_success()

        self.dataset_build_service.build_dataset.side_effect = (
            RuntimeError(
                "build failure"
            )
        )

        with self.assertRaises(
            ChampionReferenceBundleBuildError
        ):
            self.service.build_bundled_dataset()

    def test_invalid_build_result_is_rejected(
        self
    ):
        self._configure_success()

        self.dataset_build_service.build_dataset.return_value = (
            None
        )

        with self.assertRaises(
            ChampionReferenceBundleBuildError
        ):
            self.service.build_bundled_dataset()


if __name__ == "__main__":
    unittest.main()