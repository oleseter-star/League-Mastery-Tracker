import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call

from application.services.champion_reference_dataset_service import (
    ChampionReferenceDatasetError,
)
from application.services.champion_reference_source_service import (
    ChampionReferenceSourceService,
)


class ChampionReferenceSourceServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        root_directory = Path(
            self.temporary_directory.name
        )

        self.bundled_directory = (
            root_directory
            / "bundled"
            / "data_dragon"
        )

        self.cache_directory = (
            root_directory
            / "reference"
            / "data_dragon"
        )

        self.dataset_service = Mock()

        self.service = (
            ChampionReferenceSourceService(
                dataset_service=(
                    self.dataset_service
                ),
                bundled_dataset_directory=(
                    self.bundled_directory
                ),
                local_cache_directory=(
                    self.cache_directory
                ),
            )
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _build_dataset(
        self,
        version,
        dataset_directory,
    ):
        return {
            "manifest": {
                "data_dragon_version": (
                    version
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
            "dataset_directory": (
                Path(
                    dataset_directory
                ).resolve()
            ),
            "icons_directory": (
                Path(
                    dataset_directory
                )
                / "champion_icons"
            ).resolve(),
        }

    def _configure_datasets(
        self,
        bundled_version="15.14.1",
        cache_version="15.15.1",
    ):
        bundled_dataset = (
            self._build_dataset(
                version=bundled_version,
                dataset_directory=(
                    self.bundled_directory
                ),
            )
        )

        cache_dataset = (
            self._build_dataset(
                version=cache_version,
                dataset_directory=(
                    self.cache_directory
                ),
            )
        )

        def load_dataset(
            dataset_directory,
        ):
            resolved_directory = Path(
                dataset_directory
            ).resolve()

            if (
                resolved_directory
                == self.bundled_directory.resolve()
            ):
                return bundled_dataset

            if (
                resolved_directory
                == self.cache_directory.resolve()
            ):
                return cache_dataset

            raise AssertionError(
                "Unexpected dataset directory."
            )

        self.dataset_service.load_dataset.side_effect = (
            load_dataset
        )

        return (
            bundled_dataset,
            cache_dataset,
        )

    def test_newer_valid_local_cache_is_selected(
        self
    ):
        _, cache_dataset = (
            self._configure_datasets(
                bundled_version="15.14.1",
                cache_version="15.15.1",
            )
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["dataset"],
            cache_dataset,
        )

        self.assertEqual(
            result["data_dragon_version"],
            "15.15.1",
        )

    def test_older_local_cache_does_not_replace_bundled_data(
        self
    ):
        bundled_dataset, _ = (
            self._configure_datasets(
                bundled_version="15.14.1",
                cache_version="15.13.9",
            )
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertEqual(
            result["dataset"],
            bundled_dataset,
        )

    def test_equal_local_cache_does_not_replace_bundled_data(
        self
    ):
        bundled_dataset, _ = (
            self._configure_datasets(
                bundled_version="15.14.1",
                cache_version="15.14.1",
            )
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertEqual(
            result["dataset"],
            bundled_dataset,
        )

    def test_version_comparison_is_numeric(
        self
    ):
        _, cache_dataset = (
            self._configure_datasets(
                bundled_version="15.9.1",
                cache_version="15.10.1",
            )
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["dataset"],
            cache_dataset,
        )

    def test_invalid_local_cache_falls_back_to_bundled_data(
        self
    ):
        bundled_dataset = (
            self._build_dataset(
                version="15.14.1",
                dataset_directory=(
                    self.bundled_directory
                ),
            )
        )

        def load_dataset(
            dataset_directory,
        ):
            resolved_directory = Path(
                dataset_directory
            ).resolve()

            if (
                resolved_directory
                == self.cache_directory.resolve()
            ):
                raise (
                    ChampionReferenceDatasetError(
                        "Invalid local cache."
                    )
                )

            return bundled_dataset

        self.dataset_service.load_dataset.side_effect = (
            load_dataset
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertEqual(
            result["dataset"],
            bundled_dataset,
        )

        self.assertEqual(
            result["warnings"],
            [
                (
                    "The local champion reference "
                    "cache is unavailable or invalid."
                ),
            ],
        )

    def test_missing_local_cache_falls_back_to_bundled_data(
        self
    ):
        bundled_dataset = (
            self._build_dataset(
                version="15.14.1",
                dataset_directory=(
                    self.bundled_directory
                ),
            )
        )

        def load_dataset(
            dataset_directory,
        ):
            resolved_directory = Path(
                dataset_directory
            ).resolve()

            if (
                resolved_directory
                == self.cache_directory.resolve()
            ):
                raise (
                    ChampionReferenceDatasetError(
                        "Cache directory missing."
                    )
                )

            return bundled_dataset

        self.dataset_service.load_dataset.side_effect = (
            load_dataset
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertEqual(
            result["dataset"],
            bundled_dataset,
        )

    def test_valid_cache_is_used_when_bundled_data_is_missing(
        self
    ):
        cache_dataset = (
            self._build_dataset(
                version="15.12.1",
                dataset_directory=(
                    self.cache_directory
                ),
            )
        )

        def load_dataset(
            dataset_directory,
        ):
            resolved_directory = Path(
                dataset_directory
            ).resolve()

            if (
                resolved_directory
                == self.bundled_directory.resolve()
            ):
                raise (
                    ChampionReferenceDatasetError(
                        "Bundled dataset missing."
                    )
                )

            return cache_dataset

        self.dataset_service.load_dataset.side_effect = (
            load_dataset
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["dataset"],
            cache_dataset,
        )

        self.assertEqual(
            result["warnings"],
            [
                (
                    "The bundled champion reference "
                    "dataset is unavailable or invalid."
                ),
            ],
        )

    def test_valid_cache_is_used_when_bundled_data_is_invalid(
        self
    ):
        cache_dataset = (
            self._build_dataset(
                version="15.12.1",
                dataset_directory=(
                    self.cache_directory
                ),
            )
        )

        self.dataset_service.load_dataset.side_effect = [
            ChampionReferenceDatasetError(
                "Invalid bundled dataset."
            ),
            cache_dataset,
        ]

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["dataset"],
            cache_dataset,
        )

    def test_database_fallback_is_returned_when_both_sources_fail(
        self
    ):
        self.dataset_service.load_dataset.side_effect = (
            ChampionReferenceDatasetError(
                "Dataset unavailable."
            )
        )

        result = self.service.select_source()

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertIsNone(
            result["dataset"]
        )

        self.assertIsNone(
            result["data_dragon_version"]
        )

        self.assertIsNone(
            result["locale"]
        )

        self.assertIsNone(
            result["dataset_directory"]
        )

        self.assertEqual(
            len(
                result["warnings"]
            ),
            2,
        )

    def test_bundled_and_cache_are_both_validated(
        self
    ):
        self._configure_datasets()

        self.service.select_source()

        self.assertEqual(
            self.dataset_service
            .load_dataset
            .call_args_list,
            [
                call(
                    self.bundled_directory
                ),
                call(
                    self.cache_directory
                ),
            ],
        )

    def test_selected_source_metadata_is_returned(
        self
    ):
        bundled_dataset, _ = (
            self._configure_datasets(
                bundled_version="15.14.1",
                cache_version="15.13.1",
            )
        )

        result = self.service.select_source()

        self.assertEqual(
            result,
            {
                "active_source": "bundled",
                "dataset": bundled_dataset,
                "data_dragon_version": (
                    "15.14.1"
                ),
                "locale": "en_US",
                "dataset_directory": (
                    self.bundled_directory.resolve()
                ),
                "icons_directory": (
                    self.bundled_directory
                    / "champion_icons"
                ).resolve(),
                "warnings": [],
            },
        )


if __name__ == "__main__":
    unittest.main()