import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch

from application.services.application_launcher_service import (
    ApplicationLauncherService,
)
from application.services.application_tray_service import (
    ApplicationTrayService,
    ApplicationTrayUnavailableError,
)


class ApplicationLauncherServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.instance_service = Mock()
        self.server_service = Mock()
        self.browser_service = Mock()
        self.shutdown_service = Mock()
        self.tray_service = Mock()
        self.tab_lifecycle_service = Mock()
        self.app_factory = Mock()
        self.flask_app = Mock()

        self.flask_app.extensions = {}

        self.server_service.application_url = (
            "http://127.0.0.1:5000/"
        )

        self.app_factory.return_value = (
            self.flask_app
        )

        self.launcher = (
            ApplicationLauncherService(
                instance_service=(
                    self.instance_service
                ),
                server_service=(
                    self.server_service
                ),
                browser_service=(
                    self.browser_service
                ),
                shutdown_service=(
                    self.shutdown_service
                ),
                tray_service=(
                    self.tray_service
                ),
                tab_lifecycle_service=(
                    self.tab_lifecycle_service
                ),
                app_factory=(
                    self.app_factory
                ),
            )
        )

    def test_default_configuration_is_production(
        self
    ):
        self.assertEqual(
            self.launcher.config_name,
            "production",
        )

    def test_first_instance_starts_application(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        result = self.launcher.run()

        self.assertEqual(
            result,
            {
                "started": True,
                "reason": "server_stopped",
            },
        )

        self.instance_service.acquire.assert_called_once_with()

        self.server_service.ensure_port_available.assert_called_once_with()

        self.app_factory.assert_called_once_with(
            "production"
        )

        self.server_service.create_server.assert_called_once_with(
            self.flask_app
        )

        self.shutdown_service.configure_shutdown_callback.assert_called_once_with(
            self.server_service.request_shutdown
        )

        self.tray_service.start.assert_called_once_with()

        self.tab_lifecycle_service.start.assert_called_once_with()

        self.browser_service.start_background_open.assert_called_once_with()

        self.server_service.run.assert_called_once_with()

    def test_second_instance_opens_existing_application(
        self
    ):
        self.instance_service.acquire.return_value = (
            False
        )

        result = self.launcher.run()

        self.assertEqual(
            result,
            {
                "started": False,
                "reason": "already_running",
            },
        )

        self.browser_service.wait_until_ready_and_open.assert_called_once_with()

        self.server_service.ensure_port_available.assert_not_called()
        self.app_factory.assert_not_called()
        self.server_service.create_server.assert_not_called()
        self.shutdown_service.configure_shutdown_callback.assert_not_called()
        self.tray_service.start.assert_not_called()
        self.tray_service.stop.assert_not_called()
        self.tab_lifecycle_service.start.assert_not_called()
        self.tab_lifecycle_service.stop.assert_not_called()
        self.server_service.run.assert_not_called()

    def test_server_is_closed_after_normal_shutdown(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.launcher.run()

        self.server_service.close.assert_called_once_with()

    def test_tray_icon_is_stopped_after_normal_shutdown(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.launcher.run()

        self.tray_service.stop.assert_called_once_with()

    def test_tab_monitor_is_stopped_after_normal_shutdown(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.launcher.run()

        self.tab_lifecycle_service.stop.assert_called_once_with()

    def test_instance_lock_is_released_after_normal_shutdown(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.launcher.run()

        self.instance_service.release.assert_called_once_with()

    def test_resources_are_released_when_app_creation_fails(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.app_factory.side_effect = RuntimeError(
            "application creation failed"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "application creation failed",
        ):
            self.launcher.run()

        self.tab_lifecycle_service.stop.assert_called_once_with()
        self.tray_service.stop.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

    def test_resources_are_released_when_server_fails(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.server_service.run.side_effect = (
            RuntimeError(
                "server failed"
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "server failed",
        ):
            self.launcher.run()

        self.tab_lifecycle_service.stop.assert_called_once_with()
        self.tray_service.stop.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

    def test_resources_are_released_when_tray_start_fails(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.tray_service.start.side_effect = (
            RuntimeError(
                "tray failed"
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "tray failed",
        ):
            self.launcher.run()

        self.tab_lifecycle_service.stop.assert_called_once_with()
        self.tray_service.stop.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

        self.tab_lifecycle_service.start.assert_not_called()
        self.browser_service.start_background_open.assert_not_called()
        self.server_service.run.assert_not_called()

    def test_linux_tray_unavailability_keeps_server_lifecycle_running(
        self
    ):
        self.instance_service.acquire.return_value = True
        self.server_service.shutdown_requested = False
        raw_failure = (
            "SYNTHETIC_X11_DISPLAY_SLICE4 "
            "SYNTHETIC_WAYLAND_SOCKET_SLICE4 "
            "SYNTHETIC_TRAY_BACKEND_SLICE4 "
            "/synthetic/tray/backend/socket "
            "DisplayConnectionError "
            "Traceback (most recent call last): "
            "SYNTHETIC_TRAY_TRACEBACK_FRAME_SLICE4"
        )
        unavailable_error = ApplicationTrayUnavailableError(
            "Notification-area support is unavailable."
        )
        unavailable_error.__cause__ = OSError(raw_failure)
        tray_service = ApplicationTrayService(
            application_url="http://127.0.0.1:5000/",
            open_application_callback=self.browser_service.open_browser,
            shutdown_callback=self.server_service.request_shutdown,
        )
        pystray_module = Mock()
        image_factory = Mock()
        menu_factory = pystray_module.Menu
        menu_item_factory = pystray_module.MenuItem
        icon_factory = pystray_module.Icon
        self.launcher.tray_service = tray_service
        self.server_service.run.side_effect = KeyboardInterrupt
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                tray_service,
                "_load_tray_dependencies",
                return_value=(pystray_module, Mock(), Mock()),
            ) as dependency_loader,
            patch.object(
                tray_service,
                "_create_icon_image",
                image_factory,
            ),
            patch.object(
                tray_service,
                "_raise_linux_tray_unavailable",
                side_effect=unavailable_error,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = self.launcher.run()

        self.assertEqual(
            result,
            {
                "started": True,
                "reason": "user_requested_shutdown",
            },
        )
        dependency_loader.assert_not_called()
        image_factory.assert_not_called()
        menu_factory.assert_not_called()
        menu_item_factory.assert_not_called()
        icon_factory.assert_not_called()
        self.tab_lifecycle_service.start.assert_called_once_with()
        self.browser_service.start_background_open.assert_called_once_with()
        self.server_service.run.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()
        self.assertFalse(self.server_service.shutdown_requested)
        for marker in (
            raw_failure,
            "SYNTHETIC_X11_DISPLAY_SLICE4",
            "SYNTHETIC_WAYLAND_SOCKET_SLICE4",
            "SYNTHETIC_TRAY_BACKEND_SLICE4",
            "/synthetic/tray/backend/socket",
            "DisplayConnectionError",
            "Traceback (most recent call last):",
            "SYNTHETIC_TRAY_TRACEBACK_FRAME_SLICE4",
        ):
            self.assertNotIn(marker, stdout.getvalue())
            self.assertNotIn(marker, stderr.getvalue())

    def test_windows_tray_unavailability_is_not_downgraded(self):
        self.instance_service.acquire.return_value = True
        self.tray_service.start.side_effect = (
            ApplicationTrayUnavailableError("synthetic unavailable")
        )

        with patch.object(sys, "platform", "win32"), self.assertRaises(
            ApplicationTrayUnavailableError
        ):
            self.launcher.run()

        self.tab_lifecycle_service.start.assert_not_called()
        self.browser_service.start_background_open.assert_not_called()
        self.server_service.run.assert_not_called()

    def test_early_shutdown_is_not_missed_in_trayless_mode(self):
        self.instance_service.acquire.return_value = True
        self.server_service.shutdown_requested = True
        self.tray_service.start.side_effect = (
            ApplicationTrayUnavailableError("synthetic unavailable")
        )
        self.server_service.run.side_effect = KeyboardInterrupt

        with patch.object(sys, "platform", "linux"):
            result = self.launcher.run()

        self.assertEqual(
            result,
            {
                "started": True,
                "reason": "application_requested_shutdown",
            },
        )
        self.browser_service.start_background_open.assert_called_once_with()
        self.server_service.run.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

    def test_shutdown_during_tray_failure_completes_trayless_lifecycle(
        self,
    ):
        self.instance_service.acquire.return_value = True
        self.server_service.shutdown_requested = False

        def unavailable_after_shutdown():
            self.server_service.shutdown_requested = True
            raise ApplicationTrayUnavailableError("synthetic unavailable")

        self.tray_service.start.side_effect = unavailable_after_shutdown
        self.server_service.run.side_effect = KeyboardInterrupt

        with patch.object(sys, "platform", "linux"):
            result = self.launcher.run()

        self.assertEqual(
            result,
            {
                "started": True,
                "reason": "application_requested_shutdown",
            },
        )
        self.browser_service.start_background_open.assert_called_once_with()
        self.server_service.run.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

    def test_keyboard_interrupt_is_clean_shutdown(
        self
    ):
        self.instance_service.acquire.return_value = (
            True
        )

        self.server_service.shutdown_requested = (
            False
        )

        self.server_service.run.side_effect = (
            KeyboardInterrupt
        )

        result = self.launcher.run()

        self.assertEqual(
            result,
            {
                "started": True,
                "reason": "user_requested_shutdown",
            },
        )

        self.tab_lifecycle_service.stop.assert_called_once_with()
        self.tray_service.stop.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

    def test_services_run_in_required_order(
        self
    ):
        operation_log = Mock()

        self.instance_service.acquire.side_effect = (
            lambda: (
                operation_log.acquire(),
                True,
            )[1]
        )

        self.server_service.ensure_port_available.side_effect = (
            operation_log.ensure_port_available
        )

        self.app_factory.side_effect = (
            lambda config_name: (
                operation_log.create_app(
                    config_name
                ),
                self.flask_app,
            )[1]
        )

        self.server_service.create_server.side_effect = (
            lambda app: (
                operation_log.create_server(
                    app
                ),
                Mock(),
            )[1]
        )

        self.shutdown_service.configure_shutdown_callback.side_effect = (
            lambda callback: (
                operation_log.configure_shutdown(
                    callback
                )
            )
        )

        self.tray_service.start.side_effect = (
            operation_log.start_tray
        )

        self.tab_lifecycle_service.start.side_effect = (
            operation_log.start_tab_monitor
        )

        self.browser_service.start_background_open.side_effect = (
            operation_log.start_browser
        )

        self.server_service.run.side_effect = (
            operation_log.run_server
        )

        self.tab_lifecycle_service.stop.side_effect = (
            operation_log.stop_tab_monitor
        )

        self.tray_service.stop.side_effect = (
            operation_log.stop_tray
        )

        self.server_service.close.side_effect = (
            operation_log.close_server
        )

        self.instance_service.release.side_effect = (
            operation_log.release_instance
        )

        self.launcher.run()

        self.assertEqual(
            operation_log.mock_calls,
            [
                call.acquire(),
                call.ensure_port_available(),
                call.create_app(
                    "production"
                ),
                call.create_server(
                    self.flask_app
                ),
                call.configure_shutdown(
                    self.server_service.request_shutdown
                ),
                call.start_tray(),
                call.start_tab_monitor(),
                call.start_browser(),
                call.run_server(),
                call.stop_tab_monitor(),
                call.stop_tray(),
                call.close_server(),
                call.release_instance(),
            ],
        )

    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationTabLifecycleService"
    )
    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationTrayService"
    )
    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationShutdownService"
    )
    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationBrowserService"
    )
    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationServerService"
    )
    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationInstanceService"
    )
    def test_default_services_are_created(
        self,
        instance_service_class,
        server_service_class,
        browser_service_class,
        shutdown_service_class,
        tray_service_class,
        tab_lifecycle_service_class,
    ):
        server_service = Mock()
        browser_service = Mock()
        shutdown_service = Mock()

        server_service.application_url = (
            "http://127.0.0.1:5000/"
        )

        server_service_class.return_value = (
            server_service
        )

        browser_service_class.return_value = (
            browser_service
        )

        shutdown_service_class.return_value = (
            shutdown_service
        )

        launcher = (
            ApplicationLauncherService(
                app_factory=Mock(),
            )
        )

        instance_service_class.assert_called_once_with()
        server_service_class.assert_called_once_with()

        browser_service_class.assert_called_once_with(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
        )

        shutdown_service_class.assert_called_once_with()

        tray_service_class.assert_called_once_with(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
            open_application_callback=(
                browser_service.open_browser
            ),
            shutdown_callback=(
                shutdown_service.request_shutdown
            ),
        )

        tab_lifecycle_service_class.assert_called_once_with(
            shutdown_callback=(
                shutdown_service.request_shutdown
            ),
        )

        self.assertIs(
            launcher.instance_service,
            instance_service_class.return_value,
        )

        self.assertIs(
            launcher.server_service,
            server_service,
        )

        self.assertIs(
            launcher.browser_service,
            browser_service,
        )

        self.assertIs(
            launcher.shutdown_service,
            shutdown_service,
        )

        self.assertIs(
            launcher.tray_service,
            tray_service_class.return_value,
        )

        self.assertIs(
            launcher.tab_lifecycle_service,
            tab_lifecycle_service_class.return_value,
        )


if __name__ == "__main__":
    unittest.main()