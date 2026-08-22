import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.services import (
    champion_reference_resource_service
    as resource_module,
)
from application.services.champion_reference_resource_service import (
    ChampionReferenceResourceService,
)


class ChampionReferenceResourceServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _build_fake_module_file(
        self,
    ):
        module_file = (
            self.root_directory
            / "project"
            / "application"
            / "services"
            / "champion_reference_resource_service.py"
        )

        module_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        module_file.write_text(
            "",
            encoding="utf-8",
        )

        return module_file

    def test_source_environment_uses_project_root(
        self
    ):
        module_file = (
            self._build_fake_module_file()
        )

        expected_directory = (
            self.root_directory
            / "project"
            / "application"
            / "bundled_reference_data"
            / "data_dragon"
        ).resolve()

        with patch.object(
            resource_module,
            "__file__",
            str(module_file),
        ), patch.object(
            sys,
            "_MEIPASS",
            None,
            create=True,
        ):
            result = (
                ChampionReferenceResourceService
                .get_dataset_directory()
            )

        self.assertEqual(
            result,
            expected_directory,
        )

    def test_pyinstaller_environment_uses_meipass(
        self
    ):
        bundle_root = (
            self.root_directory
            / "pyinstaller_bundle"
        )

        expected_directory = (
            bundle_root
            / "application"
            / "bundled_reference_data"
            / "data_dragon"
        ).resolve()

        with patch.object(
            sys,
            "_MEIPASS",
            str(bundle_root),
            create=True,
        ):
            result = (
                ChampionReferenceResourceService
                .get_dataset_directory()
            )

        self.assertEqual(
            result,
            expected_directory,
        )

    def test_empty_meipass_uses_source_environment(
        self
    ):
        module_file = (
            self._build_fake_module_file()
        )

        expected_directory = (
            self.root_directory
            / "project"
            / "application"
            / "bundled_reference_data"
            / "data_dragon"
        ).resolve()

        with patch.object(
            resource_module,
            "__file__",
            str(module_file),
        ), patch.object(
            sys,
            "_MEIPASS",
            "",
            create=True,
        ):
            result = (
                ChampionReferenceResourceService
                .get_dataset_directory()
            )

        self.assertEqual(
            result,
            expected_directory,
        )

    def test_manifest_file_is_inside_dataset(
        self
    ):
        dataset_directory = (
            self.root_directory
            / "dataset"
        )

        with patch.object(
            ChampionReferenceResourceService,
            "get_dataset_directory",
            return_value=dataset_directory,
        ):
            result = (
                ChampionReferenceResourceService
                .get_manifest_file()
            )

        self.assertEqual(
            result,
            dataset_directory
            / "manifest.json",
        )

    def test_champions_file_is_inside_dataset(
        self
    ):
        dataset_directory = (
            self.root_directory
            / "dataset"
        )

        with patch.object(
            ChampionReferenceResourceService,
            "get_dataset_directory",
            return_value=dataset_directory,
        ):
            result = (
                ChampionReferenceResourceService
                .get_champions_file()
            )

        self.assertEqual(
            result,
            dataset_directory
            / "champions.json",
        )

    def test_icons_directory_is_inside_dataset(
        self
    ):
        dataset_directory = (
            self.root_directory
            / "dataset"
        )

        with patch.object(
            ChampionReferenceResourceService,
            "get_dataset_directory",
            return_value=dataset_directory,
        ):
            result = (
                ChampionReferenceResourceService
                .get_icons_directory()
            )

        self.assertEqual(
            result,
            dataset_directory
            / "champion_icons",
        )

    def test_resource_lookup_does_not_create_directories(
        self
    ):
        bundle_root = (
            self.root_directory
            / "missing_bundle"
        )

        with patch.object(
            sys,
            "_MEIPASS",
            str(bundle_root),
            create=True,
        ):
            dataset_directory = (
                ChampionReferenceResourceService
                .get_dataset_directory()
            )

        self.assertFalse(
            bundle_root.exists()
        )

        self.assertFalse(
            dataset_directory.exists()
        )

    def test_resource_lookup_is_independent_of_working_directory(
        self
    ):
        module_file = (
            self._build_fake_module_file()
        )

        unrelated_directory = (
            self.root_directory
            / "unrelated"
        )

        unrelated_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        expected_directory = (
            self.root_directory
            / "project"
            / "application"
            / "bundled_reference_data"
            / "data_dragon"
        ).resolve()

        original_working_directory = Path.cwd()

        try:
            os.chdir(
                unrelated_directory
            )

            with patch.object(
                resource_module,
                "__file__",
                str(module_file),
            ), patch.object(
                sys,
                "_MEIPASS",
                None,
                create=True,
            ):
                result = (
                    ChampionReferenceResourceService
                    .get_dataset_directory()
                )

        finally:
            os.chdir(
                original_working_directory
            )

        self.assertEqual(
            result,
            expected_directory,
        )


if __name__ == "__main__":
    unittest.main()