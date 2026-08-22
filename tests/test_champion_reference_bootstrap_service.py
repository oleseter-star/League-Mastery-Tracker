import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from application.services.champion_reference_bootstrap_service import (
    ChampionReferenceBootstrapService,
)


class ChampionReferenceBootstrapServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        root_directory = Path(
            self.temporary_directory.name
        )

        self.dataset_directory = (
            root_directory
            / "data_dragon"
        )

        self.icons_directory = (
            self.dataset_directory
            / "champion_icons"
        )

        self.source_service = Mock()
        self.merge_service = Mock()

        self.service = (
            ChampionReferenceBootstrapService(
                source_service=(
                    self.source_service
                ),
                merge_service=(
                    self.merge_service
                ),
            )
        )

        self.dataset = {
            "manifest": {
                "data_dragon_version": (
                    "15.14.1"
                ),
                "locale": "en_US",
                "champion_count": 2,
            },
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
            "dataset_directory": (
                self.dataset_directory
            ),
            "icons_directory": (
                self.icons_directory
            ),
        }

        self.merge_result = {
            "created": 2,
            "updated": 0,
            "unchanged": 0,
            "preserved_manual": 0,
            "preserved_existing": 0,
            "active_source": "bundled",
            "data_dragon_version": (
                "15.14.1"
            ),
            "locale": "en_US",
            "dataset_count": 2,
            "database_count": 2,
        }

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _configure_source(
        self,
        active_source="bundled",
        warnings=None,
    ):
        self.source_service.select_source.return_value = {
            "active_source": active_source,
            "dataset": self.dataset,
            "data_dragon_version": (
                "15.14.1"
            ),
            "locale": "en_US",
            "dataset_directory": (
                self.dataset_directory
            ),
            "icons_directory": (
                self.icons_directory
            ),
            "warnings": (
                list(
                    warnings
                    or []
                )
            ),
        }

    def test_bundled_dataset_is_merged(
        self
    ):
        self._configure_source(
            active_source="bundled"
        )

        self.merge_service.merge_dataset.return_value = (
            self.merge_result
        )

        result = self.service.bootstrap()

        self.source_service.select_source.assert_called_once_with()

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.dataset,
            active_source="bundled",
        )

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertTrue(
            result["reference_data_available"]
        )

        self.assertFalse(
            result["database_fallback"]
        )

        self.assertEqual(
            result["merge"],
            self.merge_result,
        )

    def test_local_cache_dataset_is_merged(
        self
    ):
        self._configure_source(
            active_source="local_cache"
        )

        merge_result = dict(
            self.merge_result
        )

        merge_result[
            "active_source"
        ] = "local_cache"

        self.merge_service.merge_dataset.return_value = (
            merge_result
        )

        result = self.service.bootstrap()

        self.merge_service.merge_dataset.assert_called_once_with(
            dataset=self.dataset,
            active_source="local_cache",
        )

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["merge"],
            merge_result,
        )

    def test_selected_source_metadata_is_returned(
        self
    ):
        self._configure_source(
            active_source="bundled"
        )

        self.merge_service.merge_dataset.return_value = (
            self.merge_result
        )

        result = self.service.bootstrap()

        self.assertEqual(
            result["data_dragon_version"],
            "15.14.1",
        )

        self.assertEqual(
            result["locale"],
            "en_US",
        )

        self.assertEqual(
            result["dataset_directory"],
            self.dataset_directory,
        )

        self.assertEqual(
            result["icons_directory"],
            self.icons_directory,
        )

    def test_source_warnings_are_preserved(
        self
    ):
        self._configure_source(
            active_source="bundled",
            warnings=[
                (
                    "The local champion reference "
                    "cache is unavailable or invalid."
                ),
            ],
        )

        self.merge_service.merge_dataset.return_value = (
            self.merge_result
        )

        result = self.service.bootstrap()

        self.assertEqual(
            result["warnings"],
            [
                (
                    "The local champion reference "
                    "cache is unavailable or invalid."
                ),
            ],
        )

    def test_database_fallback_skips_merge(
        self
    ):
        self.source_service.select_source.return_value = {
            "active_source": "database",
            "dataset": None,
            "data_dragon_version": None,
            "locale": None,
            "dataset_directory": None,
            "icons_directory": None,
            "warnings": [
                (
                    "The bundled champion reference "
                    "dataset is unavailable or invalid."
                ),
                (
                    "The local champion reference "
                    "cache is unavailable or invalid."
                ),
            ],
        }

        result = self.service.bootstrap()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertFalse(
            result["reference_data_available"]
        )

        self.assertTrue(
            result["database_fallback"]
        )

        self.assertIsNone(
            result["merge"]
        )

        self.assertEqual(
            len(
                result["warnings"]
            ),
            2,
        )

    def test_missing_dataset_for_file_source_uses_database_fallback(
        self
    ):
        self.source_service.select_source.return_value = {
            "active_source": "bundled",
            "dataset": None,
            "data_dragon_version": (
                "15.14.1"
            ),
            "locale": "en_US",
            "dataset_directory": (
                self.dataset_directory
            ),
            "icons_directory": (
                self.icons_directory
            ),
            "warnings": [],
        }

        result = self.service.bootstrap()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertTrue(
            result["database_fallback"]
        )

        self.assertIn(
            (
                "Champion reference data could not "
                "be initialized. Existing database "
                "data remains available."
            ),
            result["warnings"],
        )

    def test_invalid_active_source_uses_database_fallback(
        self
    ):
        self._configure_source(
            active_source="internet"
        )

        result = self.service.bootstrap()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertTrue(
            result["database_fallback"]
        )

    def test_source_selection_failure_uses_database_fallback(
        self
    ):
        self.source_service.select_source.side_effect = (
            RuntimeError(
                "source selection failed"
            )
        )

        result = self.service.bootstrap()

        self.merge_service.merge_dataset.assert_not_called()

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertFalse(
            result["reference_data_available"]
        )

        self.assertTrue(
            result["database_fallback"]
        )

        self.assertIsNone(
            result["merge"]
        )

        self.assertEqual(
            result["warnings"],
            [
                (
                    "Champion reference data could not "
                    "be initialized. Existing database "
                    "data remains available."
                ),
            ],
        )

    def test_merge_failure_uses_database_fallback(
        self
    ):
        self._configure_source(
            active_source="bundled"
        )

        self.merge_service.merge_dataset.side_effect = (
            RuntimeError(
                "merge failed"
            )
        )

        result = self.service.bootstrap()

        self.assertEqual(
            result["active_source"],
            "database",
        )

        self.assertFalse(
            result["reference_data_available"]
        )

        self.assertTrue(
            result["database_fallback"]
        )

        self.assertIsNone(
            result["merge"]
        )

        self.assertEqual(
            result["warnings"],
            [
                (
                    "Champion reference data could not "
                    "be initialized. Existing database "
                    "data remains available."
                ),
            ],
        )

    def test_source_warnings_are_preserved_when_merge_fails(
        self
    ):
        source_warning = (
            "The local champion reference "
            "cache is unavailable or invalid."
        )

        self._configure_source(
            active_source="bundled",
            warnings=[
                source_warning,
            ],
        )

        self.merge_service.merge_dataset.side_effect = (
            RuntimeError(
                "merge failed"
            )
        )

        result = self.service.bootstrap()

        self.assertEqual(
            result["warnings"],
            [
                source_warning,
                (
                    "Champion reference data could not "
                    "be initialized. Existing database "
                    "data remains available."
                ),
            ],
        )

    def test_bootstrap_does_not_call_network_update_methods(
        self
    ):
        self._configure_source(
            active_source="bundled"
        )

        self.merge_service.merge_dataset.return_value = (
            self.merge_result
        )

        self.service.bootstrap()

        self.assertFalse(
            hasattr(
                self.source_service,
                "refresh_reference_data",
            )
            and self.source_service
            .refresh_reference_data.called
        )

        self.assertFalse(
            hasattr(
                self.source_service,
                "get_latest_version",
            )
            and self.source_service
            .get_latest_version.called
        )


if __name__ == "__main__":
    unittest.main()