import ast
import unittest
from pathlib import Path


class PyInstallerLinuxConfigurationTests(
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
        cls.spec_file = (
            cls.project_root
            / "LeagueMasteryTracker-linux-onefile.spec"
        )

    def test_linux_onefile_spec_exists_and_parses(self):
        self.assertTrue(
            self.spec_file.is_file(),
            msg="Missing Linux onefile PyInstaller spec.",
        )
        ast.parse(self._read_spec())

    def test_analysis_uses_run_entry_point_and_project_root(self):
        analysis_call = self._call_named("Analysis")
        self.assertEqual(
            ast.literal_eval(analysis_call.args[0]),
            ["run.py"],
        )
        self.assertIn(
            "PROJECT_ROOT",
            ast.unparse(self._keyword(analysis_call, "pathex")),
        )

    def test_plain_linux_onefile_executable_contract(self):
        executable_call = self._call_named("EXE")
        self.assertEqual(
            ast.literal_eval(self._keyword(executable_call, "name")),
            "LeagueMasteryTracker",
        )
        self.assertFalse(
            ast.literal_eval(
                self._keyword(executable_call, "console")
            )
        )
        self.assertNotIn("COLLECT", self._call_names())
        for prohibited_keyword in ("icon", "version"):
            self.assertNotIn(
                prohibited_keyword,
                {
                    keyword.arg
                    for keyword in executable_call.keywords
                },
            )

    def test_runtime_resource_mappings_preserve_application_layout(self):
        mappings = self._literal_assignment("DATA_DIRECTORIES")
        self.assertEqual(
            [destination for _, destination in mappings],
            [
                "application/templates",
                "application/static",
                "application/bundled_reference_data",
            ],
        )
        self.assertEqual(
            [source for source, _ in mappings],
            ["templates", "static", "bundled_reference_data"],
        )
        self.assertTrue(
            (
                self.project_root
                / "application"
                / "static"
                / "application.ico"
            ).is_file()
        )
        datas_assignment = self._assignment("datas")
        self.assertIn(
            "PROJECT_ROOT / 'application' / source_directory",
            ast.unparse(datas_assignment.value),
        )

    def test_hidden_imports_cover_only_lazy_linux_boundaries(self):
        hidden_imports = set(
            self._literal_assignment("LINUX_HIDDEN_IMPORTS")
        )
        self.assertEqual(
            hidden_imports,
            {
                "PIL.Image",
                "PIL.ImageDraw",
                "pystray._xorg",
                "Xlib.error",
                "secretstorage",
                "secretstorage.collection",
                "secretstorage.item",
                "jeepney",
                "jeepney.bus",
                "jeepney.io.blocking",
            },
        )
        self.assertFalse(
            any("win32" in name.lower() for name in hidden_imports)
        )

    def test_spec_has_no_platform_metadata_or_external_runtime_claims(self):
        spec_content = self._read_spec()
        for prohibited_text in (
            ".exe",
            "BUNDLE",
            "entitlements",
            "AppImage",
            "Flatpak",
            "Snap",
            "/home/",
            "://",
            "download",
            "glibc",
            "portability",
        ):
            self.assertNotIn(prohibited_text, spec_content)

    def test_spec_source_has_no_runtime_service_or_display_access(self):
        spec_content = self._read_spec()
        for prohibited_text in (
            "dbus_init",
            "get_default_collection",
            "Display(",
            "socket.",
            "webbrowser.",
            "run_detached",
        ):
            self.assertNotIn(prohibited_text, spec_content)

    def test_windows_specs_retain_windows_metadata(self):
        for file_name in (
            "LeagueMasteryTracker.spec",
            "LeagueMasteryTracker-onefile.spec",
        ):
            content = (
                self.project_root
                / file_name
            ).read_text(encoding="utf-8")
            self.assertIn("version=str(", content)
            self.assertIn("icon=str(", content)

    def _read_spec(self):
        self.assertTrue(
            self.spec_file.is_file(),
            msg="Missing Linux onefile PyInstaller spec.",
        )
        return self.spec_file.read_text(encoding="utf-8")

    def _tree(self):
        return ast.parse(self._read_spec())

    def _call_named(self, name):
        return next(
            node
            for node in ast.walk(self._tree())
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            )
        )

    @staticmethod
    def _keyword(call, name):
        return next(
            keyword.value
            for keyword in call.keywords
            if keyword.arg == name
        )

    def _call_names(self):
        return {
            node.func.id
            for node in ast.walk(self._tree())
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
            )
        }

    def _literal_assignment(self, name):
        assignment = self._assignment(name)
        value = assignment.value
        if name == "DATA_DIRECTORIES":
            return [ast.literal_eval(entry) for entry in value.elts]
        return ast.literal_eval(value)

    def _assignment(self, name):
        return next(
            node
            for node in ast.walk(self._tree())
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == name
                    for target in node.targets
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
