import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from application.config import Config
from pyinstaller_build_metadata import (
    ApplicationBuildMetadataError,
    derive_windows_executable_basename,
    load_application_build_metadata,
    parse_windows_version,
    write_pyinstaller_version_file,
)


class ApplicationBuildMetadataTests(
    unittest.TestCase
):
    def test_canonical_version_converts_to_windows_tuple(self):
        self.assertEqual(
            parse_windows_version(
                "2.0.0"
            ),
            (
                2,
                0,
                0,
                0,
            ),
        )

    def test_invalid_versions_fail_clearly(self):
        invalid_versions = (
            (
                "2.0",
                "exactly three",
            ),
            (
                "2.0.0.0",
                "exactly three",
            ),
            (
                "2.release.0",
                "decimal digits",
            ),
            (
                "2.-1.0",
                "decimal digits",
            ),
            (
                "2.0.65536",
                "between 0 and 65535",
            ),
        )

        for version, expected_message in (
            invalid_versions
        ):
            with self.subTest(
                version=version
            ):
                with self.assertRaisesRegex(
                    ApplicationBuildMetadataError,
                    expected_message,
                ):
                    parse_windows_version(
                        version
                    )

    def test_executable_basename_is_derived_from_exe_name(self):
        self.assertEqual(
            derive_windows_executable_basename(
                "LeagueMasteryTracker.exe"
            ),
            "LeagueMasteryTracker",
        )

    def test_invalid_executable_names_fail_clearly(self):
        invalid_names = (
            (
                "",
                "non-empty",
            ),
            (
                ".exe",
                "basename",
            ),
            (
                "LeagueMasteryTracker",
                r"\.exe suffix",
            ),
            (
                "LeagueMasteryTracker.com",
                r"\.exe suffix",
            ),
            (
                "output/LeagueMasteryTracker.exe",
                "plain filename",
            ),
            (
                "output\\LeagueMasteryTracker.exe",
                "plain filename",
            ),
            (
                "C:\\LeagueMasteryTracker.exe",
                "plain filename",
            ),
        )

        for file_name, expected_message in (
            invalid_names
        ):
            with self.subTest(
                file_name=file_name
            ):
                with self.assertRaisesRegex(
                    ApplicationBuildMetadataError,
                    expected_message,
                ):
                    derive_windows_executable_basename(
                        file_name
                    )

    def test_canonical_config_maps_to_windows_metadata(self):
        metadata = (
            load_application_build_metadata()
        )

        self.assertEqual(
            metadata.file_description,
            Config.RELEASE_NAME,
        )

        self.assertEqual(
            metadata.file_version,
            Config.APPLICATION_VERSION,
        )

        self.assertEqual(
            metadata.internal_name,
            "LeagueMasteryTracker",
        )

        self.assertEqual(
            metadata.original_filename,
            Config.WINDOWS_EXECUTABLE_NAME,
        )

        self.assertEqual(
            metadata.product_name,
            Config.PRODUCT_NAME,
        )

        self.assertEqual(
            metadata.product_version,
            Config.APPLICATION_VERSION,
        )

        self.assertEqual(
            metadata.file_version_tuple,
            (
                2,
                0,
                0,
                0,
            ),
        )

        self.assertEqual(
            metadata.product_version_tuple,
            (
                2,
                0,
                0,
                0,
            ),
        )

    def test_generated_resource_contains_only_intended_strings(self):
        metadata = (
            load_application_build_metadata()
        )

        with TemporaryDirectory() as directory:
            version_file = (
                Path(directory)
                / "metadata"
                / "application-version-info.txt"
            )

            generated_file = (
                write_pyinstaller_version_file(
                    metadata=metadata,
                    destination_file=version_file,
                )
            )

            content = generated_file.read_text(
                encoding="utf-8"
            )

        self.assertIn(
            "filevers=(2, 0, 0, 0)",
            content,
        )

        self.assertIn(
            "prodvers=(2, 0, 0, 0)",
            content,
        )

        self.assertIn(
            "fileType=0x1",
            content,
        )

        self.assertIn(
            "'040904B0'",
            content,
        )

        self.assertIn(
            "VarStruct('Translation', [1033, 1200])",
            content,
        )

        intended_strings = {
            "FileDescription": (
                Config.RELEASE_NAME
            ),
            "FileVersion": (
                Config.APPLICATION_VERSION
            ),
            "InternalName": (
                "LeagueMasteryTracker"
            ),
            "OriginalFilename": (
                Config.WINDOWS_EXECUTABLE_NAME
            ),
            "ProductName": (
                Config.PRODUCT_NAME
            ),
            "ProductVersion": (
                Config.APPLICATION_VERSION
            ),
        }

        for field_name, field_value in (
            intended_strings.items()
        ):
            with self.subTest(
                field_name=field_name
            ):
                self.assertIn(
                    repr(
                        field_name
                    ),
                    content,
                )

                self.assertIn(
                    repr(
                        field_value
                    ),
                    content,
                )

        for prohibited_field in (
            "CompanyName",
            "Publisher",
            "LegalCopyright",
            "LegalTrademarks",
            "Trademark",
            "Endorsement",
        ):
            with self.subTest(
                prohibited_field=(
                    prohibited_field
                )
            ):
                self.assertNotIn(
                    prohibited_field,
                    content,
                )

    def test_generation_is_explicit_and_confined_to_destination(self):
        metadata = (
            load_application_build_metadata()
        )

        with TemporaryDirectory() as directory:
            root_directory = Path(
                directory
            )

            destination_directory = (
                root_directory
                / "requested"
            )

            destination_file = (
                destination_directory
                / "application-version-info.txt"
            )

            self.assertFalse(
                destination_directory.exists()
            )

            generated_file = (
                write_pyinstaller_version_file(
                    metadata=metadata,
                    destination_file=(
                        destination_file
                    ),
                )
            )

            first_content = (
                generated_file.read_bytes()
            )

            repeated_file = (
                write_pyinstaller_version_file(
                    metadata=metadata,
                    destination_file=(
                        destination_file
                    ),
                )
            )

            self.assertEqual(
                generated_file,
                destination_file.resolve(),
            )

            self.assertEqual(
                repeated_file,
                generated_file,
            )

            self.assertEqual(
                repeated_file.read_bytes(),
                first_content,
            )

            self.assertEqual(
                list(
                    destination_directory.iterdir()
                ),
                [
                    destination_file,
                ],
            )

    def test_import_is_free_of_runtime_startup_and_filesystem_effects(self):
        with TemporaryDirectory() as directory:
            temporary_directory = Path(
                directory
            )

            data_directory = (
                temporary_directory
                / "user-data"
            )

            command = (
                "import pathlib, socket, sys; "
                "original_mkdir = pathlib.Path.mkdir; "
                "original_socket = socket.socket; "
                "pathlib.Path.mkdir = lambda *args, **kwargs: "
                "(_ for _ in ()).throw(AssertionError('mkdir called')); "
                "socket.socket = lambda *args, **kwargs: "
                "(_ for _ in ()).throw(AssertionError('socket called')); "
                "import pyinstaller_build_metadata; "
                "assert 'run' not in sys.modules; "
                "assert 'application' not in sys.modules; "
                "assert 'application.app' not in sys.modules; "
                "assert 'application.services.application_instance_service' "
                "not in sys.modules; "
                "assert 'application.services.application_server_service' "
                "not in sys.modules; "
                "assert 'application.services.application_tray_service' "
                "not in sys.modules; "
                "assert 'application.services.application_browser_service' "
                "not in sys.modules; "
                "pathlib.Path.mkdir = original_mkdir; "
                "socket.socket = original_socket"
            )

            environment = os.environ.copy()

            environment.update(
                {
                    "LEAGUE_MASTERY_TRACKER_DATA_DIR": (
                        str(
                            data_directory
                        )
                    ),
                    "SECRET_KEY": "unrelated-secret",
                    "RIOT_API_KEY": "unrelated-api-key",
                }
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    command,
                ],
                cwd=(
                    Path(__file__)
                    .resolve()
                    .parent
                    .parent
                ),
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=(
                    result.stderr
                    or result.stdout
                ),
            )

            self.assertFalse(
                data_directory.exists()
            )

    def test_unrelated_configuration_cannot_change_identity(self):
        class FirstConfig:
            PRODUCT_NAME = Config.PRODUCT_NAME
            RELEASE_NAME = Config.RELEASE_NAME
            APPLICATION_VERSION = (
                Config.APPLICATION_VERSION
            )
            WINDOWS_EXECUTABLE_NAME = (
                Config.WINDOWS_EXECUTABLE_NAME
            )
            DATA_DIR = "/first/data"
            SECRET_KEY = "first-secret"
            RIOT_API_KEY = "first-api-key"

        class SecondConfig:
            PRODUCT_NAME = Config.PRODUCT_NAME
            RELEASE_NAME = Config.RELEASE_NAME
            APPLICATION_VERSION = (
                Config.APPLICATION_VERSION
            )
            WINDOWS_EXECUTABLE_NAME = (
                Config.WINDOWS_EXECUTABLE_NAME
            )
            DATA_DIR = "/second/data"
            SECRET_KEY = "second-secret"
            RIOT_API_KEY = "second-api-key"

        self.assertEqual(
            load_application_build_metadata(
                config_class=FirstConfig
            ),
            load_application_build_metadata(
                config_class=SecondConfig
            ),
        )

    def test_installed_pyinstaller_can_parse_generated_resource(self):
        try:
            from PyInstaller.utils.win32.versioninfo import (
                VSVersionInfo,
                load_version_info_from_text_file,
            )

        except (
            ImportError,
            ModuleNotFoundError,
        ) as error:
            self.skipTest(
                "PyInstaller's Windows version-info parser "
                f"is unavailable: {error}"
            )

        metadata = (
            load_application_build_metadata()
        )

        with TemporaryDirectory() as directory:
            version_file = (
                write_pyinstaller_version_file(
                    metadata=metadata,
                    destination_file=(
                        Path(directory)
                        / "application-version-info.txt"
                    ),
                )
            )

            parsed_info = (
                load_version_info_from_text_file(
                    version_file
                )
            )

        self.assertIsInstance(
            parsed_info,
            VSVersionInfo,
        )


if __name__ == "__main__":
    unittest.main()
