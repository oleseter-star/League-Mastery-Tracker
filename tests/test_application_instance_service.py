import errno
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from application.services.application_instance_service import (
    ApplicationInstanceError,
    ApplicationInstanceService,
)


@unittest.skipUnless(
    os.name == "nt",
    "Application instance locking requires Windows.",
)
class WindowsApplicationInstanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.mutex_name = (
            "Local\\LeagueMasteryTracker."
            f"Test.{uuid.uuid4().hex}"
        )

        self.instances = []

    def tearDown(self):
        for instance in reversed(
            self.instances
        ):
            instance.release()

    def _create_instance(self):
        instance = (
            ApplicationInstanceService(
                mutex_name=self.mutex_name,
            )
        )

        self.instances.append(
            instance
        )

        return instance

    def test_first_instance_acquires_lock(self):
        instance = self._create_instance()

        acquired = instance.acquire()

        self.assertTrue(
            acquired
        )

        self.assertTrue(
            instance.is_acquired
        )

    def test_second_instance_is_rejected(self):
        first_instance = (
            self._create_instance()
        )

        second_instance = (
            self._create_instance()
        )

        self.assertTrue(
            first_instance.acquire()
        )

        self.assertFalse(
            second_instance.acquire()
        )

        self.assertTrue(
            first_instance.is_acquired
        )

        self.assertFalse(
            second_instance.is_acquired
        )

    def test_releasing_lock_allows_new_instance(self):
        first_instance = (
            self._create_instance()
        )

        second_instance = (
            self._create_instance()
        )

        self.assertTrue(
            first_instance.acquire()
        )

        first_instance.release()

        self.assertFalse(
            first_instance.is_acquired
        )

        self.assertTrue(
            second_instance.acquire()
        )

        self.assertTrue(
            second_instance.is_acquired
        )

    def test_repeated_acquire_on_same_instance_is_safe(
        self
    ):
        instance = self._create_instance()

        first_result = instance.acquire()
        second_result = instance.acquire()

        self.assertTrue(
            first_result
        )

        self.assertTrue(
            second_result
        )

        self.assertTrue(
            instance.is_acquired
        )

    def test_repeated_release_is_safe(self):
        instance = self._create_instance()

        self.assertTrue(
            instance.acquire()
        )

        instance.release()
        instance.release()

        self.assertFalse(
            instance.is_acquired
        )


@unittest.skipUnless(
    os.name == "posix",
    "POSIX application instance locking requires POSIX.",
)
class PosixApplicationInstanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.runtime_directory = Path(
            self.temporary_directory.name
        )
        self.mutex_name = (
            "LeagueMasteryTracker."
            f"Test.{uuid.uuid4().hex}"
        )
        self.runtime_directory_patch = patch.object(
            ApplicationInstanceService,
            "_get_posix_runtime_directory",
            return_value=self.runtime_directory,
        )
        self.runtime_directory_patch.start()
        self.instances = []

    def tearDown(self):
        for instance in reversed(self.instances):
            instance.release()

        self.runtime_directory_patch.stop()
        self.temporary_directory.cleanup()

    def _create_instance(self):
        instance = ApplicationInstanceService(
            mutex_name=self.mutex_name,
        )
        self.instances.append(instance)
        return instance

    def test_first_instance_acquires_lock(self):
        instance = self._create_instance()

        self.assertTrue(instance.acquire())
        self.assertTrue(instance.is_acquired)

    def test_competing_process_is_rejected(self):
        instance = self._create_instance()
        self.assertTrue(instance.acquire())

        script = (
            "from pathlib import Path; "
            "from unittest.mock import patch; "
            "from application.services.application_instance_service "
            "import ApplicationInstanceService; "
            f"runtime_directory = Path({str(self.runtime_directory)!r}); "
            "patcher = patch.object(ApplicationInstanceService, "
            "'_get_posix_runtime_directory', "
            "return_value=runtime_directory); "
            "patcher.start(); "
            f"instance = ApplicationInstanceService({self.mutex_name!r}); "
            "raise SystemExit(0 if not instance.acquire() else 1)"
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parent.parent,
            check=False,
        )

        self.assertEqual(result.returncode, 0)

    def test_acquisition_succeeds_after_release(self):
        first_instance = self._create_instance()
        second_instance = self._create_instance()

        self.assertTrue(first_instance.acquire())
        first_instance.release()
        self.assertTrue(second_instance.acquire())

    def test_stale_lock_file_does_not_block_acquisition(self):
        instance = self._create_instance()
        lock_file_path = instance._get_posix_lock_file_path()
        lock_file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        lock_file_path.write_text("stale", encoding="utf-8")

        self.assertTrue(instance.acquire())

    def test_repeated_release_is_harmless(self):
        instance = self._create_instance()
        self.assertTrue(instance.acquire())

        instance.release()
        instance.release()

        self.assertFalse(instance.is_acquired)

    def test_contention_errors_return_false(self):
        for error_number in (errno.EAGAIN, errno.EACCES):
            with self.subTest(error_number=error_number):
                instance = self._create_instance()

                with patch(
                    "fcntl.flock",
                    side_effect=OSError(error_number, "busy"),
                ):
                    self.assertFalse(instance.acquire())

                self.assertFalse(instance.is_acquired)

    def test_close_failure_after_flock_failure_is_wrapped(self):
        instance = self._create_instance()
        lock_file = Mock()
        lock_file.fileno.return_value = 123
        lock_file.close.side_effect = OSError(
            errno.EIO,
            "close failed",
        )

        with (
            patch("builtins.open", return_value=lock_file),
            patch(
                "fcntl.flock",
                side_effect=OSError(errno.EAGAIN, "busy"),
            ),
            self.assertRaises(ApplicationInstanceError) as context,
        ):
            instance.acquire()

        self.assertIsInstance(
            context.exception.__cause__,
            OSError,
        )
        self.assertFalse(instance.is_acquired)


@unittest.skipUnless(
    os.name == "posix",
    "POSIX runtime path resolution requires POSIX.",
)
class PosixRuntimeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temporary_path = Path(self.temporary_directory.name)
        self.safe_fallback = self.temporary_path / "fallback"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _resolve_with_environment(self, xdg_runtime_directory):
        with (
            patch.dict(
                os.environ,
                {"XDG_RUNTIME_DIR": xdg_runtime_directory},
            ),
            patch(
                "application.services."
                "application_instance_service.tempfile.gettempdir",
                return_value=str(self.safe_fallback),
            ),
        ):
            return (
                ApplicationInstanceService
                ._get_posix_runtime_directory()
            )

    def _expected_fallback(self):
        return (
            self.safe_fallback
            / f"league-mastery-tracker-{os.getuid()}"
            / ApplicationInstanceService
            .POSIX_RUNTIME_DIRECTORY_NAME
        ).resolve(strict=False)

    def test_relative_xdg_runtime_directory_uses_fallback(self):
        resolved_directory = self._resolve_with_environment(
            "relative-runtime"
        )

        self.assertEqual(
            resolved_directory,
            self._expected_fallback(),
        )

    def test_xdg_inside_source_tree_uses_fallback(self):
        source_root = Path(__file__).resolve().parent.parent

        resolved_directory = self._resolve_with_environment(
            str(source_root / "runtime")
        )

        self.assertEqual(
            resolved_directory,
            self._expected_fallback(),
        )

    def test_xdg_inside_pyinstaller_directory_uses_fallback(self):
        pyinstaller_directory = (
            self.temporary_path
            / "pyinstaller-extraction"
        )

        with patch.object(
            sys,
            "_MEIPASS",
            str(pyinstaller_directory),
            create=True,
        ):
            resolved_directory = self._resolve_with_environment(
                str(pyinstaller_directory / "runtime")
            )

        self.assertEqual(
            resolved_directory,
            self._expected_fallback(),
        )

    def test_symlink_cannot_bypass_forbidden_root(self):
        pyinstaller_directory = (
            self.temporary_path
            / "pyinstaller-extraction"
        )
        pyinstaller_directory.mkdir()
        symlink_path = self.temporary_path / "runtime-link"

        try:
            symlink_path.symlink_to(
                pyinstaller_directory,
                target_is_directory=True,
            )
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Symlinks are unavailable: {error}")

        with patch.object(
            sys,
            "_MEIPASS",
            str(pyinstaller_directory),
            create=True,
        ):
            resolved_directory = self._resolve_with_environment(
                str(symlink_path)
            )

        self.assertEqual(
            resolved_directory,
            self._expected_fallback(),
        )

    def test_unsafe_fallback_raises_instance_error(self):
        source_root = Path(__file__).resolve().parent.parent

        with (
            patch.dict(
                os.environ,
                {"XDG_RUNTIME_DIR": "relative-runtime"},
            ),
            patch(
                "application.services."
                "application_instance_service.tempfile.gettempdir",
                return_value=str(source_root),
            ),
            self.assertRaises(ApplicationInstanceError),
        ):
            (
                ApplicationInstanceService
                ._get_posix_runtime_directory()
            )


if __name__ == "__main__":
    unittest.main()
