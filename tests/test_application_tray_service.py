import builtins
import importlib.util
import os
import sys
import threading
import unittest
import application.services.application_tray_service as tray_module
from unittest.mock import (
    ANY,
    Mock,
    call,
    patch,
)

from PIL import Image, ImageDraw

from application.services.application_tray_service import (
    ApplicationTrayService,
    ApplicationTrayUnavailableError,
)


class EventBackedXorgIcon:
    __module__ = "pystray._xorg"

    def __init__(
        self,
        run_error=None,
        stop_finishes_run=True,
        on_run=None,
    ):
        self.run_error = run_error
        self.stop_finishes_run = stop_finishes_run
        self.on_run = on_run
        self.run_started = threading.Event()
        self.run_finished = threading.Event()
        self.allow_run_to_finish = threading.Event()
        self.run_call_count = 0
        self.stop_call_count = 0
        self.run_detached = Mock()

    def run(self):
        self.run_call_count += 1
        self.run_started.set()

        try:
            if self.on_run is not None:
                self.on_run()

            if self.run_error is not None:
                raise self.run_error

            self.allow_run_to_finish.wait(5.0)

        finally:
            self.run_finished.set()

    def stop(self):
        self.stop_call_count += 1

        if self.stop_finishes_run:
            self.allow_run_to_finish.set()


class ApplicationTrayServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.open_application_callback = Mock(
            return_value=True
        )

        self.shutdown_callback = Mock(
            return_value=True
        )

        self.service = ApplicationTrayService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
            open_application_callback=(
                self.open_application_callback
            ),
            shutdown_callback=(
                self.shutdown_callback
            ),
        )

    def test_module_defers_tray_dependencies_until_tray_use(self):
        self.assertNotIn("pystray", vars(tray_module))
        self.assertNotIn("ImageDraw", vars(tray_module))

    def test_missing_pystray_is_deferred_until_tray_use(self):
        module_name = "isolated_application_tray_service"
        module_path = tray_module.__file__
        attempted_imports = []
        original_import = builtins.__import__

        def controlled_import(name, *args, **kwargs):
            if name in {"pystray", "PIL"}:
                attempted_imports.append(name)
                if name == "pystray":
                    raise ModuleNotFoundError("synthetic pystray missing")
            return original_import(name, *args, **kwargs)

        module_spec = importlib.util.spec_from_file_location(
            module_name,
            module_path,
        )
        isolated_module = importlib.util.module_from_spec(module_spec)

        with patch.object(
            builtins,
            "__import__",
            side_effect=controlled_import,
        ), patch.dict(
            os.environ,
            {"PYSTRAY_BACKEND": "dummy"},
            clear=True,
        ), patch.object(sys, "platform", "linux"):
            module_spec.loader.exec_module(isolated_module)
            self.assertEqual(attempted_imports, [])

            isolated_service = isolated_module.ApplicationTrayService(
                application_url="http://127.0.0.1:5000/",
                open_application_callback=Mock(),
                shutdown_callback=Mock(),
            )

            with self.assertRaises(
                isolated_module.ApplicationTrayUnavailableError
            ):
                isolated_service.start()

        self.assertEqual(attempted_imports, ["PIL", "pystray"])

    def test_headless_linux_skips_tray_dependencies(self):
        raw_marker = "DISPLAY=/synthetic/headless Traceback marker"

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.service, "_load_tray_dependencies") as loader,
            self.assertRaises(
                ApplicationTrayUnavailableError
            ) as context,
        ):
            self.service.start()

        loader.assert_not_called()
        self.assertNotIn(raw_marker, str(context.exception))
        self.assertIsNone(self.service.icon)
        self.assertFalse(self.service.is_running)
        self.open_application_callback.assert_not_called()
        self.shutdown_callback.assert_not_called()

    def test_pure_wayland_linux_skips_tray_dependencies(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                os.environ,
                {"WAYLAND_DISPLAY": "wayland-synthetic"},
                clear=True,
            ),
            patch.object(self.service, "_load_tray_dependencies") as loader,
            self.assertRaises(ApplicationTrayUnavailableError),
        ):
            self.service.start()

        loader.assert_not_called()
        self.assertIsNone(self.service.icon)
        self.assertFalse(self.service.is_running)

    def test_linux_missing_pillow_is_controlled_unavailability(self):
        original_import = builtins.__import__

        def missing_pillow(name, *args, **kwargs):
            if name == "PIL":
                raise ModuleNotFoundError("synthetic Pillow missing")
            return original_import(name, *args, **kwargs)

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                os.environ,
                {"PYSTRAY_BACKEND": "dummy"},
                clear=True,
            ),
            patch.object(
                builtins,
                "__import__",
                side_effect=missing_pillow,
            ),
            self.assertRaises(
                ApplicationTrayUnavailableError
            ) as context,
        ):
            self.service.start()

        self.assertNotIn("synthetic Pillow missing", str(context.exception))

    def test_linux_x11_display_failure_is_controlled_unavailability(self):
        fake_xlib_module = type(sys)("Xlib")
        fake_xlib_error_module = type(sys)("Xlib.error")
        display_connection_error = type(
            "DisplayConnectionError",
            (Exception,),
            {},
        )
        fake_xlib_error_module.DisplayConnectionError = (
            display_connection_error
        )
        fake_xlib_module.error = fake_xlib_error_module

        original_import = builtins.__import__

        def display_failure(name, *args, **kwargs):
            if name == "pystray":
                raise display_connection_error(
                    ":synthetic",
                    "synthetic display failure",
                )
            return original_import(name, *args, **kwargs)

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                os.environ,
                {"DISPLAY": ":99"},
                clear=True,
            ),
            patch.dict(
                sys.modules,
                {
                    "Xlib": fake_xlib_module,
                    "Xlib.error": fake_xlib_error_module,
                },
            ),
            patch.object(
                builtins,
                "__import__",
                side_effect=display_failure,
            ),
            self.assertRaises(
                ApplicationTrayUnavailableError
            ) as context,
        ):
            self.service.start()

        self.assertNotIn(":synthetic", str(context.exception))

    def test_linux_x11_display_name_failure_is_controlled_unavailability(
        self,
    ):
        fake_xlib_module = type(sys)("Xlib")
        fake_xlib_error_module = type(sys)("Xlib.error")
        display_name_error = type(
            "DisplayNameError",
            (Exception,),
            {},
        )
        fake_xlib_error_module.DisplayNameError = display_name_error
        fake_xlib_module.error = fake_xlib_error_module

        raw_marker = (
            "SYNTHETIC_X11_DISPLAY_NAME "
            "/synthetic/x11/backend "
            "SyntheticBackendError "
            "Traceback (most recent call last):"
        )
        original_import = builtins.__import__

        def display_failure(name, *args, **kwargs):
            if name == "pystray":
                raise display_name_error(raw_marker)
            return original_import(name, *args, **kwargs)

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                os.environ,
                {"DISPLAY": ":99"},
                clear=True,
            ),
            patch.dict(
                sys.modules,
                {
                    "Xlib": fake_xlib_module,
                    "Xlib.error": fake_xlib_error_module,
                },
            ),
            patch.object(
                builtins,
                "__import__",
                side_effect=display_failure,
            ),
            self.assertRaises(
                ApplicationTrayUnavailableError
            ) as context,
        ):
            self.service.start()

        self.assertEqual(
            str(context.exception),
            "Notification-area support is unavailable.",
        )
        self.assertNotIn(raw_marker, str(context.exception))
        for marker in (
            "SYNTHETIC_X11_DISPLAY_NAME",
            "/synthetic/x11/backend",
            "SyntheticBackendError",
            "Traceback (most recent call last):",
        ):
            self.assertNotIn(marker, str(context.exception))

    def test_linux_display_attempts_existing_tray_path(self):
        pystray_module = Mock()
        pystray_module.MenuItem.side_effect = (object(), object())
        pystray_module.Menu.return_value = object()
        pystray_module.Menu.SEPARATOR = object()
        pystray_module.Icon.return_value = Mock()

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                os.environ,
                {"DISPLAY": ":99"},
                clear=True,
            ),
            patch.object(
                self.service,
                "_load_tray_dependencies",
                return_value=(pystray_module, Image, ImageDraw),
            ) as loader,
        ):
            self.service.start()

        loader.assert_called_once_with()

    def test_linux_image_failure_is_controlled_unavailability(self):
        raw_error = (
            "DISPLAY=:99 /synthetic/x11/socket "
            "org.example.WaylandBackend Traceback marker"
        )
        pystray_module = Mock()

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(
                os.environ,
                {"DISPLAY": ":99"},
                clear=True,
            ),
            patch.object(
                self.service,
                "_load_tray_dependencies",
                return_value=(pystray_module, Image, ImageDraw),
            ),
            patch.object(
                self.service,
                "_create_icon_image",
                side_effect=OSError(raw_error),
            ),
            self.assertRaises(
                ApplicationTrayUnavailableError
            ) as context,
        ):
            self.service.start()

        self.assertEqual(
            str(context.exception),
            "Notification-area support is unavailable.",
        )
        self.assertNotIn(raw_error, str(context.exception))
        self.assertIsNone(self.service.icon)
        self.assertFalse(self.service.is_running)

    def test_windows_image_failure_is_not_unavailable(self):
        pystray_module = Mock()

        with (
            patch.object(sys, "platform", "win32"),
            patch.object(
                self.service,
                "_load_tray_dependencies",
                return_value=(pystray_module, Image, ImageDraw),
            ),
            patch.object(
                self.service,
                "_create_icon_image",
                side_effect=OSError("synthetic image failure"),
            ),
            self.assertRaises(OSError),
        ):
            self.service.start()

    def test_unexpected_tray_errors_are_not_unavailable(self):
        for error in (
            RuntimeError("DISPLAY=/synthetic but unrelated"),
            TypeError("DISPLAY=/synthetic but unrelated"),
            AssertionError("DISPLAY=/synthetic but unrelated"),
        ):
            with self.subTest(error=type(error).__name__), \
                patch.object(sys, "platform", "linux"), \
                patch.dict(
                    os.environ,
                    {"DISPLAY": ":99"},
                    clear=True,
                ), \
                patch.object(
                    self.service,
                    "_load_tray_dependencies",
                    side_effect=error,
                ), \
                self.assertRaises(type(error)):
                self.service.start()

    def test_default_settings_are_defined(self):
        self.assertEqual(
            self.service.application_url,
            "http://127.0.0.1:5000/",
        )

        self.assertEqual(
            self.service.icon_name,
            "LeagueMasteryTracker",
        )

        self.assertEqual(
            self.service.icon_title,
            "League Mastery Tracker",
        )

        self.assertEqual(
            self.service.open_menu_text,
            "Open League Mastery Tracker",
        )

        self.assertEqual(
            self.service.shutdown_menu_text,
            "Shut down League Mastery Tracker",
        )

        self.assertIsNone(
            self.service.icon
        )

        self.assertFalse(
            self.service.is_running
        )

        self.assertIsNone(
            self.service.background_error
        )

        self.assertIsNone(
            self.service.icon_runner_thread
        )

    def test_empty_application_url_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            ApplicationTrayService(
                application_url="",
                open_application_callback=(
                    self.open_application_callback
                ),
                shutdown_callback=(
                    self.shutdown_callback
                ),
            )

    def test_non_callable_open_callback_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            ApplicationTrayService(
                application_url=(
                    "http://127.0.0.1:5000/"
                ),
                open_application_callback=(
                    "not-callable"
                ),
                shutdown_callback=(
                    self.shutdown_callback
                ),
            )

    def test_non_callable_shutdown_callback_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            ApplicationTrayService(
                application_url=(
                    "http://127.0.0.1:5000/"
                ),
                open_application_callback=(
                    self.open_application_callback
                ),
                shutdown_callback=(
                    "not-callable"
                ),
            )

    def test_icon_image_is_generated(self):
        icon_image = (
            self.service
            .create_icon_image()
        )

        self.assertIsInstance(
            icon_image,
            Image.Image,
        )

        self.assertEqual(
            icon_image.size,
            (
                64,
                64,
            ),
        )

        self.assertEqual(
            icon_image.mode,
            "RGBA",
        )

    def test_start_creates_and_runs_tray_icon(self):
        open_menu_item = object()
        shutdown_menu_item = object()
        menu = object()
        icon = Mock()
        separator = object()

        pystray_module = Mock()
        pystray_module.MenuItem.side_effect = (
            open_menu_item,
            shutdown_menu_item,
        )
        pystray_module.Menu.return_value = menu
        pystray_module.Menu.SEPARATOR = separator
        pystray_module.Icon.return_value = icon

        with patch.object(
            self.service,
            "_load_tray_dependencies",
            return_value=(pystray_module, Image, ImageDraw),
        ):
            result = self.service.start()

        self.assertIs(
            result,
            icon,
        )

        self.assertIs(
            self.service.icon,
            icon,
        )

        self.assertTrue(
            self.service.is_running
        )

        pystray_module.MenuItem.assert_has_calls(
            [
                call(
                    "Open League Mastery Tracker",
                    self.service
                    ._handle_open_application,
                    default=True,
                ),
                call(
                    "Shut down League Mastery Tracker",
                    self.service
                    ._handle_shutdown,
                ),
            ]
        )

        pystray_module.Menu.assert_called_once_with(
            open_menu_item,
            separator,
            shutdown_menu_item,
        )

        pystray_module.Icon.assert_called_once_with(
            name="LeagueMasteryTracker",
            icon=ANY,
            title="League Mastery Tracker",
            menu=menu,
        )

        icon.run_detached.assert_called_once_with()

    def test_repeated_start_reuses_existing_icon(self):
        icon = Mock()
        pystray_module = Mock()

        pystray_module.MenuItem.side_effect = (
            object(),
            object(),
        )
        pystray_module.Menu.return_value = object()
        pystray_module.Menu.SEPARATOR = object()
        pystray_module.Icon.return_value = icon

        with patch.object(
            self.service,
            "_load_tray_dependencies",
            return_value=(pystray_module, Image, ImageDraw),
        ):
            first_result = self.service.start()
            second_result = self.service.start()

        self.assertIs(
            first_result,
            icon,
        )

        self.assertIs(
            second_result,
            icon,
        )

        pystray_module.Icon.assert_called_once()

        icon.run_detached.assert_called_once_with()

    def test_open_menu_calls_open_callback(
        self,
    ):
        result = (
            self.service
            ._handle_open_application(
                Mock(),
                Mock(),
            )
        )

        self.assertTrue(
            result
        )

        self.open_application_callback.assert_called_once_with()

        self.shutdown_callback.assert_not_called()

        self.assertIsNone(
            self.service.background_error
        )

    def test_shutdown_menu_stops_icon_before_callback(
        self,
    ):
        operation_log = Mock()

        self.service.stop = Mock(
            side_effect=(
                operation_log.stop_icon
            )
        )

        self.shutdown_callback.side_effect = (
            operation_log.shutdown
        )

        result = (
            self.service
            ._handle_shutdown(
                Mock(),
                Mock(),
            )
        )

        self.assertTrue(
            result
        )

        self.assertEqual(
            operation_log.mock_calls,
            [
                call.stop_icon(),
                call.shutdown(),
            ],
        )

        self.open_application_callback.assert_not_called()

        self.assertIsNone(
            self.service.background_error
        )

    def test_stop_without_icon_is_safe(self):
        result = self.service.stop()

        self.assertFalse(
            result
        )

        self.assertIsNone(
            self.service.icon
        )

        self.assertFalse(
            self.service.is_running
        )

    def test_stop_delegates_to_tray_icon(
        self,
    ):
        icon = Mock()

        self.service._icon = icon

        result = self.service.stop()

        self.assertTrue(
            result
        )

        icon.stop.assert_called_once_with()

        self.assertIsNone(
            self.service.icon
        )

        self.assertFalse(
            self.service.is_running
        )

    def test_repeated_stop_is_safe(self):
        icon = Mock()

        self.service._icon = icon

        first_result = self.service.stop()
        second_result = self.service.stop()

        self.assertTrue(
            first_result
        )

        self.assertFalse(
            second_result
        )

        icon.stop.assert_called_once_with()

    def test_open_callback_error_is_recorded(
        self,
    ):
        self.open_application_callback.side_effect = (
            RuntimeError(
                "browser open failed"
            )
        )

        result = (
            self.service
            ._handle_open_application(
                Mock(),
                Mock(),
            )
        )

        self.assertFalse(
            result
        )

        self.assertIsInstance(
            self.service.background_error,
            RuntimeError,
        )

        self.assertEqual(
            str(
                self.service.background_error
            ),
            "browser open failed",
        )

    def test_shutdown_callback_error_is_recorded(
        self,
    ):
        self.service.stop = Mock()

        self.shutdown_callback.side_effect = (
            RuntimeError(
                "shutdown failed"
            )
        )

        result = (
            self.service
            ._handle_shutdown(
                Mock(),
                Mock(),
            )
        )

        self.assertFalse(
            result
        )

        self.service.stop.assert_called_once_with()

        self.assertIsInstance(
            self.service.background_error,
            RuntimeError,
        )

        self.assertEqual(
            str(
                self.service.background_error
            ),
            "shutdown failed",
        )


class ApplicationTrayServiceXorgRunnerTests(
    unittest.TestCase
):
    def setUp(self):
        self.service = ApplicationTrayService(
            application_url="http://127.0.0.1:5000/",
            open_application_callback=Mock(
                return_value=True
            ),
            shutdown_callback=Mock(
                return_value=True
            ),
        )

    def tearDown(self):
        icon = self.service.icon

        if icon is not None:
            icon.allow_run_to_finish.set()

        runner = self.service.icon_runner_thread

        if (
            runner is not None
            and runner is not threading.current_thread()
        ):
            runner.join(timeout=2.0)

        self.service.stop()

    def _start_with_icon(self, icon):
        pystray_module = Mock()
        pystray_module.Icon.return_value = icon
        pystray_module.MenuItem.side_effect = (
            object(),
            object(),
        )
        pystray_module.Menu.return_value = object()
        pystray_module.Menu.SEPARATOR = object()

        with patch.object(
            self.service,
            "_load_tray_dependencies",
            return_value=(pystray_module, Image, ImageDraw),
        ):
            return self.service.start()

    def test_xorg_start_uses_one_owned_non_daemon_runner(self):
        icon = EventBackedXorgIcon()

        self.assertIs(
            self._start_with_icon(icon),
            icon,
        )
        self.assertTrue(icon.run_started.wait(1.0))

        runner = self.service.icon_runner_thread

        self.assertIsNotNone(runner)
        self.assertEqual(
            runner.name,
            "LeagueMasteryTrackerTrayIcon",
        )
        self.assertFalse(runner.daemon)
        self.assertEqual(icon.run_call_count, 1)
        icon.run_detached.assert_not_called()

    def test_stop_signals_and_joins_owned_runner(self):
        icon = EventBackedXorgIcon()
        self._start_with_icon(icon)
        self.assertTrue(icon.run_started.wait(1.0))
        runner = self.service.icon_runner_thread

        self.assertTrue(self.service.stop())

        self.assertEqual(icon.stop_call_count, 1)
        self.assertTrue(icon.run_finished.is_set())
        self.assertFalse(runner.is_alive())
        self.assertIsNone(self.service.icon_runner_thread)
        self.assertIsNone(self.service.icon)

    def test_runner_thread_stop_defers_ownership_cleanup(self):
        icon = EventBackedXorgIcon()
        same_thread_stop_result = []
        icon.on_run = lambda: same_thread_stop_result.append(
            self.service.stop()
        )

        self._start_with_icon(icon)
        self.assertTrue(icon.run_finished.wait(1.0))
        runner = self.service.icon_runner_thread

        self.assertEqual(same_thread_stop_result, [True])
        self.assertEqual(icon.stop_call_count, 1)
        self.assertIs(self.service.icon_runner_thread, runner)
        self.assertIs(self.service.icon, icon)
        self.assertFalse(runner.is_alive())

        self.assertTrue(self.service.stop())
        self.assertEqual(icon.stop_call_count, 2)
        self.assertIsNone(self.service.icon_runner_thread)
        self.assertIsNone(self.service.icon)

    def test_repeated_stop_remains_idempotent(self):
        icon = EventBackedXorgIcon()
        self._start_with_icon(icon)
        self.assertTrue(icon.run_started.wait(1.0))

        self.assertTrue(self.service.stop())
        self.assertFalse(self.service.stop())
        self.assertEqual(icon.stop_call_count, 1)

    def test_icon_run_failure_is_observable(self):
        icon = EventBackedXorgIcon(
            run_error=RuntimeError("icon run failed")
        )
        self._start_with_icon(icon)

        self.assertTrue(icon.run_finished.wait(1.0))
        self.assertIsInstance(
            self.service.background_error,
            RuntimeError,
        )
        self.assertEqual(
            str(self.service.background_error),
            "icon run failed",
        )

    def test_stop_timeout_retains_runner_and_reports_error(self):
        icon = EventBackedXorgIcon(
            stop_finishes_run=False
        )
        self.service.ICON_RUNNER_JOIN_TIMEOUT_SECONDS = 0.01
        self._start_with_icon(icon)
        self.assertTrue(icon.run_started.wait(1.0))
        runner = self.service.icon_runner_thread

        self.assertFalse(self.service.stop())

        self.assertTrue(runner.is_alive())
        self.assertIs(self.service.icon_runner_thread, runner)
        self.assertIs(self.service.icon, icon)
        self.assertIsInstance(
            self.service.background_error,
            RuntimeError,
        )

        icon.allow_run_to_finish.set()
        self.assertTrue(icon.run_finished.wait(1.0))
        self.assertTrue(self.service.stop())
        self.assertIsNone(self.service.icon_runner_thread)

    def test_non_xorg_backend_preserves_run_detached(self):
        icon = Mock()

        self._start_with_icon(icon)

        icon.run_detached.assert_called_once_with()
        icon.run.assert_not_called()
        self.assertIsNone(self.service.icon_runner_thread)


if __name__ == "__main__":
    unittest.main()
