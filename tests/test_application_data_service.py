import os
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from application.services.application_data_service import (
    ApplicationDataMigrationError,
    ApplicationDataService,
)


class ApplicationDataServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.project_root = (
            self.root_directory
            / "project"
        )

        self.project_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.legacy_data_directory = (
            self.project_root
            / "data"
        )

        self.local_appdata_directory = (
            self.root_directory
            / "LocalAppData"
        )

        self.target_data_directory = (
            self.local_appdata_directory
            / "LeagueMasteryTracker"
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_environment_override_has_highest_priority(self):
        override_directory = (
            self.root_directory
            / "override-data"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "LEAGUE_MASTERY_TRACKER_DATA_DIR": str(
                        override_directory
                    ),
                    "LOCALAPPDATA": str(
                        self.local_appdata_directory
                    ),
                },
                os_name="nt",
                home_directory=(
                    self.root_directory
                    / "home"
                ),
            )
        )

        self.assertEqual(
            result,
            override_directory.resolve(),
        )

    def test_environment_override_wins_over_linux_xdg_data_home(self):
        override_directory = (
            self.root_directory
            / "override-data"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "LEAGUE_MASTERY_TRACKER_DATA_DIR": str(
                        override_directory
                    ),
                    "XDG_DATA_HOME": str(
                        self.root_directory
                        / "xdg-data"
                    ),
                },
                os_name="linux",
                home_directory=(
                    self.root_directory
                    / "home"
                ),
            )
        )

        self.assertEqual(
            result,
            override_directory.resolve(),
        )

    def test_windows_uses_local_appdata(self):
        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "LOCALAPPDATA": str(
                        self.local_appdata_directory
                    ),
                },
                os_name="nt",
                home_directory=(
                    self.root_directory
                    / "home"
                ),
            )
        )

        self.assertEqual(
            result,
            self.target_data_directory.resolve(),
        )

    def test_windows_falls_back_to_user_profile(self):
        home_directory = (
            self.root_directory
            / "home"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={},
                os_name="nt",
                home_directory=home_directory,
            )
        )

        self.assertEqual(
            result,
            (
                home_directory
                / "AppData"
                / "Local"
                / "LeagueMasteryTracker"
            ).resolve(),
        )

    def test_non_linux_development_uses_project_data(self):
        with patch.object(
            sys,
            "platform",
            "darwin",
        ):
            result = (
                ApplicationDataService
                .get_data_directory(
                    project_root=self.project_root,
                    environment={},
                    os_name="posix",
                    home_directory=(
                        self.root_directory
                        / "home"
                    ),
                )
            )

        self.assertEqual(
            result,
            self.legacy_data_directory.resolve(),
        )

    def test_linux_uses_absolute_xdg_data_home(self):
        xdg_data_directory = (
            self.root_directory
            / "xdg-data"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "XDG_DATA_HOME": str(
                        xdg_data_directory
                    ),
                },
                os_name="linux",
                home_directory=(
                    self.root_directory
                    / "home"
                ),
            )
        )

        self.assertEqual(
            result,
            (
                xdg_data_directory
                / ApplicationDataService
                .APPLICATION_DIRECTORY_NAME
            ).resolve(),
        )

        self.assertFalse(
            xdg_data_directory.exists()
        )

    def test_linux_absolute_xdg_data_home_is_not_normalized(self):
        xdg_data_directory = (
            self.root_directory
            / "xdg-data"
            / "lexical-component"
            / ".."
            / "data-home"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "XDG_DATA_HOME": str(
                        xdg_data_directory
                    ),
                },
                os_name="linux",
                home_directory=(
                    self.root_directory
                    / "home"
                ),
            )
        )

        self.assertEqual(
            result,
            xdg_data_directory
            / ApplicationDataService
            .APPLICATION_DIRECTORY_NAME,
        )

        self.assertFalse(
            xdg_data_directory.exists()
        )

    def test_linux_missing_xdg_data_home_uses_home_default(self):
        home_directory = (
            self.root_directory
            / "home"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={},
                os_name="linux",
                home_directory=home_directory,
            )
        )

        self.assertEqual(
            result,
            (
                home_directory
                / ".local"
                / "share"
                / ApplicationDataService
                .APPLICATION_DIRECTORY_NAME
            ).resolve(),
        )

        self.assertFalse(
            home_directory.exists()
        )

    def test_linux_empty_xdg_data_home_uses_home_default(self):
        home_directory = (
            self.root_directory
            / "home"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "XDG_DATA_HOME": "",
                },
                os_name="linux",
                home_directory=home_directory,
            )
        )

        self.assertEqual(
            result,
            (
                home_directory
                / ".local"
                / "share"
                / ApplicationDataService
                .APPLICATION_DIRECTORY_NAME
            ).resolve(),
        )

        self.assertFalse(
            home_directory.exists()
        )

    def test_linux_relative_xdg_data_home_uses_home_default(self):
        home_directory = (
            self.root_directory
            / "home"
        )

        result = (
            ApplicationDataService
            .get_data_directory(
                project_root=self.project_root,
                environment={
                    "XDG_DATA_HOME": "relative-xdg-data",
                },
                os_name="linux",
                home_directory=home_directory,
            )
        )

        self.assertEqual(
            result,
            (
                home_directory
                / ".local"
                / "share"
                / ApplicationDataService
                .APPLICATION_DIRECTORY_NAME
            ).resolve(),
        )

        self.assertFalse(
            home_directory.exists()
        )

    def test_frozen_linux_uses_xdg_data_outside_meipass(self):
        meipass_directory = (
            self.root_directory
            / "pyinstaller-extraction"
        )

        xdg_data_directory = (
            self.root_directory
            / "xdg-data"
        )

        with patch.object(
            sys,
            "_MEIPASS",
            str(meipass_directory),
            create=True,
        ):
            result = (
                ApplicationDataService
                .get_data_directory(
                    project_root=meipass_directory,
                    environment={
                        "XDG_DATA_HOME": str(
                            xdg_data_directory
                        ),
                    },
                    os_name="linux",
                    home_directory=(
                        self.root_directory
                        / "home"
                    ),
                )
            )

        expected_directory = (
            xdg_data_directory
            / ApplicationDataService
            .APPLICATION_DIRECTORY_NAME
        ).resolve()

        self.assertEqual(
            result,
            expected_directory,
        )

        self.assertNotEqual(
            result,
            (
                meipass_directory
                / "data"
            ).resolve(),
        )

        self.assertFalse(
            meipass_directory.exists()
        )

        self.assertFalse(
            xdg_data_directory.exists()
        )

    def test_missing_legacy_directory_is_skipped(self):
        result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    self.legacy_data_directory
                ),
                target_data_directory=(
                    self.target_data_directory
                ),
            )
        )

        self.assertFalse(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "legacy_data_not_found",
        )

        self.assertFalse(
            self.target_data_directory.exists()
        )

    def test_frozen_legacy_data_is_not_copied(self):
        meipass_directory = (
            self.root_directory
            / "pyinstaller-extraction"
        )

        legacy_data_directory = (
            meipass_directory
            / "data"
        )

        legacy_marker_file = (
            legacy_data_directory
            / "frozen-legacy-marker.bin"
        )

        target_data_directory = (
            self.root_directory
            / "persistent-data"
            / ApplicationDataService
            .APPLICATION_DIRECTORY_NAME
        )

        legacy_marker_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_marker_file.write_bytes(
            b"frozen-legacy-data"
        )

        with patch.object(
            sys,
            "frozen",
            True,
            create=True,
        ), patch.object(
            sys,
            "_MEIPASS",
            str(meipass_directory),
            create=True,
        ), patch(
            "application.services."
            "application_data_service."
            "shutil.copytree",
            wraps=shutil.copytree,
        ) as copytree:
            result = (
                ApplicationDataService
                .migrate_legacy_data(
                    legacy_data_directory=(
                        legacy_data_directory
                    ),
                    target_data_directory=(
                        target_data_directory
                    ),
                )
            )

        self.assertFalse(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "legacy_data_not_found",
        )

        copytree.assert_not_called()

        self.assertTrue(
            legacy_marker_file.exists()
        )

        self.assertFalse(
            target_data_directory.exists()
        )

    def test_frozen_bundle_root_is_not_copied(self):
        meipass_directory = (
            self.root_directory
            / "pyinstaller-extraction"
        )

        legacy_marker_file = (
            meipass_directory
            / "frozen-bundle-root-marker.bin"
        )

        target_data_directory = (
            self.root_directory
            / "persistent-data"
            / ApplicationDataService
            .APPLICATION_DIRECTORY_NAME
        )

        legacy_marker_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_marker_file.write_bytes(
            b"frozen-bundle-root-data"
        )

        with patch.object(
            sys,
            "frozen",
            True,
            create=True,
        ), patch.object(
            sys,
            "_MEIPASS",
            str(meipass_directory),
            create=True,
        ), patch(
            "application.services."
            "application_data_service."
            "shutil.copytree",
            wraps=shutil.copytree,
        ) as copytree:
            result = (
                ApplicationDataService
                .migrate_legacy_data(
                    legacy_data_directory=(
                        meipass_directory
                    ),
                    target_data_directory=(
                        target_data_directory
                    ),
                )
            )

        self.assertFalse(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "legacy_data_not_found",
        )

        copytree.assert_not_called()

        self.assertTrue(
            legacy_marker_file.exists()
        )

        self.assertFalse(
            target_data_directory.exists()
        )

    def test_frozen_prefixed_sibling_legacy_data_is_copied(self):
        meipass_directory = (
            self.root_directory
            / "_MEIPASS"
        )

        legacy_data_directory = (
            self.root_directory
            / "_MEIPASS-old"
            / "data"
        )

        legacy_marker_file = (
            legacy_data_directory
            / "sibling-legacy-marker.bin"
        )

        target_data_directory = (
            self.root_directory
            / "persistent-data"
            / ApplicationDataService
            .APPLICATION_DIRECTORY_NAME
        )

        legacy_marker_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_marker_file.write_bytes(
            b"prefixed-sibling-legacy-data"
        )

        self.assertFalse(
            target_data_directory.exists()
        )

        with patch.object(
            sys,
            "frozen",
            True,
            create=True,
        ), patch.object(
            sys,
            "_MEIPASS",
            str(meipass_directory),
            create=True,
        ), patch(
            "application.services."
            "application_data_service."
            "shutil.copytree",
            wraps=shutil.copytree,
        ) as copytree:
            result = (
                ApplicationDataService
                .migrate_legacy_data(
                    legacy_data_directory=(
                        legacy_data_directory
                    ),
                    target_data_directory=(
                        target_data_directory
                    ),
                )
            )

        self.assertTrue(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "legacy_data_copied",
        )

        copytree.assert_called_once()

        self.assertEqual(
            (
                target_data_directory
                / legacy_marker_file.name
            ).read_bytes(),
            b"prefixed-sibling-legacy-data",
        )

        self.assertTrue(
            legacy_marker_file.exists()
        )

    def test_frozen_malformed_meipass_skips_legacy_data(self):
        legacy_marker_file = (
            self.legacy_data_directory
            / "malformed-meipass-marker.bin"
        )

        target_data_directory = (
            self.root_directory
            / "persistent-data"
            / ApplicationDataService
            .APPLICATION_DIRECTORY_NAME
        )

        legacy_marker_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_marker_file.write_bytes(
            b"malformed-meipass-legacy-data"
        )

        with patch.object(
            sys,
            "frozen",
            True,
            create=True,
        ), patch.object(
            sys,
            "_MEIPASS",
            12345,
            create=True,
        ), patch(
            "application.services."
            "application_data_service."
            "shutil.copytree",
            wraps=shutil.copytree,
        ) as copytree:
            result = (
                ApplicationDataService
                .migrate_legacy_data(
                    legacy_data_directory=(
                        self.legacy_data_directory
                    ),
                    target_data_directory=(
                        target_data_directory
                    ),
                )
            )

        self.assertFalse(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "legacy_data_not_found",
        )

        copytree.assert_not_called()

        self.assertTrue(
            legacy_marker_file.exists()
        )

        self.assertFalse(
            target_data_directory.exists()
        )

    def test_legacy_data_is_copied_to_fresh_target(self):
        database_file = (
            self.legacy_data_directory
            / "database"
            / "league_mastery_tracker.db"
        )

        secret_key_file = (
            self.legacy_data_directory
            / "configuration"
            / "flask_secret_key.bin"
        )

        riot_key_file = (
            self.legacy_data_directory
            / "configuration"
            / "riot_api_key.dpapi"
        )

        backup_file = (
            self.legacy_data_directory
            / "backups"
            / (
                "league_mastery_tracker_"
                "20260722T120000000000Z.db"
            )
        )

        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        secret_key_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        database_bytes = (
            b"sqlite-database-test-data"
        )

        secret_key_bytes = bytes(
            range(64)
        )

        riot_key_bytes = (
            b"LMT-RIOT-API-KEY\x00\x01"
            b"encrypted-test-data"
        )

        backup_bytes = (
            b"sqlite-backup-test-data"
        )

        database_file.write_bytes(
            database_bytes
        )

        secret_key_file.write_bytes(
            secret_key_bytes
        )

        riot_key_file.write_bytes(
            riot_key_bytes
        )

        backup_file.write_bytes(
            backup_bytes
        )

        result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    self.legacy_data_directory
                ),
                target_data_directory=(
                    self.target_data_directory
                ),
            )
        )

        self.assertTrue(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "legacy_data_copied",
        )

        self.assertEqual(
            result["copied_file_count"],
            4,
        )

        self.assertEqual(
            (
                self.target_data_directory
                / "database"
                / "league_mastery_tracker.db"
            ).read_bytes(),
            database_bytes,
        )

        self.assertEqual(
            (
                self.target_data_directory
                / "configuration"
                / "flask_secret_key.bin"
            ).read_bytes(),
            secret_key_bytes,
        )

        self.assertEqual(
            (
                self.target_data_directory
                / "configuration"
                / "riot_api_key.dpapi"
            ).read_bytes(),
            riot_key_bytes,
        )

        self.assertEqual(
            (
                self.target_data_directory
                / "backups"
                / backup_file.name
            ).read_bytes(),
            backup_bytes,
        )

        self.assertTrue(
            (
                self.target_data_directory
                / ApplicationDataService
                .MIGRATION_MARKER_FILE_NAME
            ).exists()
        )

        self.assertTrue(
            database_file.exists()
        )

        self.assertTrue(
            secret_key_file.exists()
        )

        self.assertTrue(
            riot_key_file.exists()
        )

        self.assertTrue(
            backup_file.exists()
        )

    def test_completed_migration_is_not_repeated(self):
        self.legacy_data_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_file = (
            self.legacy_data_directory
            / "database"
            / "league_mastery_tracker.db"
        )

        legacy_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_file.write_bytes(
            b"original-database"
        )

        first_result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    self.legacy_data_directory
                ),
                target_data_directory=(
                    self.target_data_directory
                ),
            )
        )

        legacy_file.write_bytes(
            b"changed-after-migration"
        )

        second_result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    self.legacy_data_directory
                ),
                target_data_directory=(
                    self.target_data_directory
                ),
            )
        )

        self.assertTrue(
            first_result["migrated"]
        )

        self.assertFalse(
            second_result["migrated"]
        )

        self.assertEqual(
            second_result["reason"],
            "migration_already_completed",
        )

        self.assertEqual(
            (
                self.target_data_directory
                / "database"
                / "league_mastery_tracker.db"
            ).read_bytes(),
            b"original-database",
        )

    def test_existing_target_data_is_never_overwritten(self):
        legacy_database_file = (
            self.legacy_data_directory
            / "database"
            / "league_mastery_tracker.db"
        )

        target_database_file = (
            self.target_data_directory
            / "database"
            / "league_mastery_tracker.db"
        )

        legacy_database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target_database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        legacy_database_file.write_bytes(
            b"legacy-database"
        )

        target_database_file.write_bytes(
            b"existing-target-database"
        )

        result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    self.legacy_data_directory
                ),
                target_data_directory=(
                    self.target_data_directory
                ),
            )
        )

        self.assertFalse(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "target_data_already_exists",
        )

        self.assertEqual(
            target_database_file.read_bytes(),
            b"existing-target-database",
        )

        self.assertEqual(
            legacy_database_file.read_bytes(),
            b"legacy-database",
        )

    def test_same_source_and_target_is_skipped(self):
        self.legacy_data_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    self.legacy_data_directory
                ),
                target_data_directory=(
                    self.legacy_data_directory
                ),
            )
        )

        self.assertFalse(
            result["migrated"]
        )

        self.assertEqual(
            result["reason"],
            "same_data_directory",
        )

    def test_failed_copy_does_not_leave_partial_target(self):
        database_file = (
            self.legacy_data_directory
            / "database"
            / "league_mastery_tracker.db"
        )

        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        database_file.write_bytes(
            b"preserve-source"
        )

        original_copytree = shutil.copytree

        def failing_copytree(
            source,
            destination,
            *args,
            **kwargs,
        ):
            destination = Path(
                destination
            )

            destination.mkdir(
                parents=True,
                exist_ok=True,
            )

            (
                destination
                / "partial-file.tmp"
            ).write_bytes(
                b"partial"
            )

            raise OSError(
                "simulated copy failure"
            )

        with patch(
            "application.services."
            "application_data_service."
            "shutil.copytree",
            side_effect=failing_copytree,
        ):
            with self.assertRaises(
                ApplicationDataMigrationError
            ):
                (
                    ApplicationDataService
                    .migrate_legacy_data(
                        legacy_data_directory=(
                            self.legacy_data_directory
                        ),
                        target_data_directory=(
                            self.target_data_directory
                        ),
                    )
                )

        self.assertFalse(
            self.target_data_directory.exists()
        )

        self.assertEqual(
            database_file.read_bytes(),
            b"preserve-source",
        )

        staging_directories = list(
            self.local_appdata_directory.glob(
                ".LeagueMasteryTracker."
                "migration-*"
            )
        )

        self.assertEqual(
            staging_directories,
            [],
        )

        self.assertIsNotNone(
            original_copytree
        )


if __name__ == "__main__":
    unittest.main()