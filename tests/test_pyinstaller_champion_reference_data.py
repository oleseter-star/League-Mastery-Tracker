import ast
import unittest
from pathlib import Path


class PyInstallerChampionReferenceDataTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.project_root = (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )

        cls.bundled_directory = (
            cls.project_root
            / "application"
            / "bundled_reference_data"
            / "data_dragon"
        )

        cls.static_directory = (
            cls.project_root
            / "application"
            / "static"
        )

        cls.base_template = (
            cls.project_root
            / "application"
            / "templates"
            / "base.html"
        )

        cls.spec_files = {
            "onedir": (
                cls.project_root
                / "LeagueMasteryTracker.spec"
            ),
            "onefile": (
                cls.project_root
                / "LeagueMasteryTracker-onefile.spec"
            ),
        }

    def test_bundled_dataset_files_exist(
        self
    ):
        self.assertTrue(
            (
                self.bundled_directory
                / "manifest.json"
            ).is_file()
        )

        self.assertTrue(
            (
                self.bundled_directory
                / "champions.json"
            ).is_file()
        )

        self.assertTrue(
            (
                self.bundled_directory
                / "champion_icons"
            ).is_dir()
        )

    def test_bundled_dataset_contains_icons(
        self
    ):
        icon_files = list(
            (
                self.bundled_directory
                / "champion_icons"
            ).glob(
                "*.png"
            )
        )

        self.assertGreater(
            len(icon_files),
            0,
        )

    def test_local_branding_assets_exist(
        self
    ):
        favicon_file = (
            self.static_directory
            / "favicon.svg"
        )

        application_icon_file = (
            self.static_directory
            / "application.ico"
        )

        self.assertTrue(
            favicon_file.is_file()
        )

        self.assertGreater(
            favicon_file.stat().st_size,
            0,
        )

        self.assertTrue(
            application_icon_file.is_file()
        )

        self.assertGreater(
            application_icon_file.stat().st_size,
            0,
        )

    def test_base_template_uses_local_favicon(
        self
    ):
        self.assertTrue(
            self.base_template.is_file()
        )

        template_content = (
            self.base_template.read_text(
                encoding="utf-8"
            )
        )

        self.assertIn(
            'rel="icon"',
            template_content,
        )

        self.assertIn(
            "favicon.svg",
            template_content,
        )

    def test_onedir_spec_includes_bundled_reference_data(
        self
    ):
        spec_content = (
            self._read_spec(
                "onedir"
            )
        )

        self._assert_bundled_data_configuration(
            spec_content
        )

    def test_onefile_spec_includes_bundled_reference_data(
        self
    ):
        spec_content = (
            self._read_spec(
                "onefile"
            )
        )

        self._assert_bundled_data_configuration(
            spec_content
        )

    def test_onedir_spec_includes_local_branding_assets(
        self
    ):
        spec_content = (
            self._read_spec(
                "onedir"
            )
        )

        self._assert_local_branding_configuration(
            spec_content
        )

    def test_onefile_spec_includes_local_branding_assets(
        self
    ):
        spec_content = (
            self._read_spec(
                "onefile"
            )
        )

        self._assert_local_branding_configuration(
            spec_content
        )

    def test_onedir_build_remains_console_free(
        self
    ):
        spec_content = (
            self._read_spec(
                "onedir"
            )
        )

        self.assertIn(
            "console=False",
            spec_content,
        )

    def test_onefile_build_remains_console_free(
        self
    ):
        spec_content = (
            self._read_spec(
                "onefile"
            )
        )

        self.assertIn(
            "console=False",
            spec_content,
        )

    def test_onedir_spec_uses_shared_build_metadata(
        self
    ):
        self._assert_shared_build_metadata(
            self._read_spec(
                "onedir"
            )
        )

    def test_onefile_spec_uses_shared_build_metadata(
        self
    ):
        self._assert_shared_build_metadata(
            self._read_spec(
                "onefile"
            )
        )

    def test_onedir_spec_preserves_hidden_imports_and_architecture(
        self
    ):
        self._assert_hidden_imports_and_architecture(
            self._read_spec(
                "onedir"
            )
        )

    def test_onefile_spec_preserves_hidden_imports_and_architecture(
        self
    ):
        self._assert_hidden_imports_and_architecture(
            self._read_spec(
                "onefile"
            )
        )

    def _read_spec(
        self,
        spec_name,
    ):
        spec_file = self.spec_files[
            spec_name
        ]

        self.assertTrue(
            spec_file.is_file(),
            msg=(
                f"Missing PyInstaller spec: "
                f"{spec_file.name}"
            ),
        )

        return spec_file.read_text(
            encoding="utf-8"
        )

    def _assert_bundled_data_configuration(
        self,
        spec_content,
    ):
        self.assertIn(
            '"bundled_reference_data"',
            spec_content,
        )

        self.assertIn(
            (
                '"application/'
                'bundled_reference_data"'
            ),
            spec_content,
        )

        self.assertIn(
            '"application"',
            spec_content,
        )

    def _assert_local_branding_configuration(
        self,
        spec_content,
    ):
        self.assertIn(
            '"static"',
            spec_content,
        )

        self.assertIn(
            '"application/static"',
            spec_content,
        )

        self.assertIn(
            '"application.ico"',
            spec_content,
        )

        self.assertIn(
            "APPLICATION_ICON",
            spec_content,
        )

        self.assertIn(
            "icon=str(",
            spec_content,
        )

    def _assert_shared_build_metadata(
        self,
        spec_content,
    ):
        parsed_spec = ast.parse(
            spec_content
        )

        imported_names = set()

        for node in ast.walk(
            parsed_spec
        ):
            if (
                isinstance(
                    node,
                    ast.ImportFrom,
                )
                and node.module
                == "pyinstaller_build_metadata"
            ):
                imported_names.update(
                    imported_name.name
                    for imported_name in node.names
                )

        self.assertEqual(
            imported_names,
            {
                "load_application_build_metadata",
                "write_pyinstaller_version_file",
            },
        )

        assigned_names = {
            target.id
            for node in ast.walk(
                parsed_spec
            )
            if isinstance(
                node,
                ast.Assign,
            )
            for target in node.targets
            if isinstance(
                target,
                ast.Name,
            )
        }

        self.assertNotIn(
            "APPLICATION_NAME",
            assigned_names,
        )

        self.assertNotIn(
            "2.0.0",
            spec_content,
        )

        executable_call = next(
            node
            for node in ast.walk(
                parsed_spec
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and isinstance(
                    node.func,
                    ast.Name,
                )
                and node.func.id == "EXE"
            )
        )

        executable_keywords = {
            keyword.arg: keyword.value
            for keyword in executable_call.keywords
        }

        self.assertEqual(
            ast.unparse(
                executable_keywords[
                    "name"
                ]
            ),
            (
                "APPLICATION_BUILD_METADATA."
                "executable_basename"
            ),
        )

        self.assertEqual(
            ast.unparse(
                executable_keywords[
                    "version"
                ]
            ),
            "str(APPLICATION_VERSION_FILE)",
        )

        self.assertIn(
            '"build"',
            spec_content,
        )

        self.assertIn(
            '"pyinstaller"',
            spec_content,
        )

        self.assertIn(
            '"application-version-info.txt"',
            spec_content,
        )

    def _assert_hidden_imports_and_architecture(
        self,
        spec_content,
    ):
        self.assertIn(
            "collect_submodules(",
            spec_content,
        )

        self.assertIn(
            '"pystray"',
            spec_content,
        )

        self.assertIn(
            "hiddenimports=hiddenimports",
            spec_content,
        )

        self.assertNotIn(
            "COLLECT(",
            spec_content,
        )


if __name__ == "__main__":
    unittest.main()
