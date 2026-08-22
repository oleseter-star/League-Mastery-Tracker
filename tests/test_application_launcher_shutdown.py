import threading
import unittest
from unittest.mock import Mock, call, patch

from application.services.application_launcher_service import (
    ApplicationLauncherService,
)
from application.services.application_shutdown_service import (
    ApplicationShutdownService,
)
from application.services.application_tray_service import (
    ApplicationTrayService,
)


class LauncherEventBackedXorgIcon:
    __module__ = "pystray._xorg"

    def __init__(self):
        self.run_started = threading.Event()
        self.run_finished = threading.Event()
        self.stop_requested = threading.Event()

    def run(self):
        self.run_started.set()

        try:
            self.stop_requested.wait(5.0)
        finally:
            self.run_finished.set()

    def stop(self):
        self.stop_requested.set()


class ApplicationLauncherShutdownTests(
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

        self.instance_service.acquire.return_value = (
            True
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

    def test_shutdown_callback_is_configured(
        self
    ):
        self.launcher.run()

        self.shutdown_service.configure_shutdown_callback.assert_called_once_with(
            self.server_service.request_shutdown
        )

    def test_shutdown_service_is_registered_in_flask_extensions(
        self
    ):
        self.launcher.run()

        extension_key = (
            ApplicationShutdownService
            .FLASK_EXTENSION_KEY
        )

        self.assertIn(
            extension_key,
            self.flask_app.extensions,
        )

        self.assertIs(
            self.flask_app.extensions[
                extension_key
            ],
            self.shutdown_service,
        )

    def test_shutdown_is_configured_after_server_creation(
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

    def test_second_instance_does_not_configure_shutdown(
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

        self.shutdown_service.configure_shutdown_callback.assert_not_called()

        self.tray_service.start.assert_not_called()
        self.tray_service.stop.assert_not_called()

        self.tab_lifecycle_service.start.assert_not_called()
        self.tab_lifecycle_service.stop.assert_not_called()

        self.assertEqual(
            self.flask_app.extensions,
            {},
        )

    def test_shutdown_configuration_failure_releases_resources(
        self
    ):
        self.shutdown_service.configure_shutdown_callback.side_effect = (
            RuntimeError(
                "shutdown configuration failed"
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "shutdown configuration failed",
        ):
            self.launcher.run()

        self.tab_lifecycle_service.stop.assert_called_once_with()
        self.tray_service.stop.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

    def test_instance_lock_releases_after_tray_runner_stops(self):
        icon = LauncherEventBackedXorgIcon()
        tray_service = ApplicationTrayService(
            application_url="http://127.0.0.1:5000/",
            open_application_callback=Mock(
                return_value=True
            ),
            shutdown_callback=Mock(
                return_value=True
            ),
        )
        launcher = ApplicationLauncherService(
            instance_service=self.instance_service,
            server_service=self.server_service,
            browser_service=self.browser_service,
            shutdown_service=self.shutdown_service,
            tray_service=tray_service,
            tab_lifecycle_service=(
                self.tab_lifecycle_service
            ),
            app_factory=self.app_factory,
        )

        def verify_tray_stopped_before_release():
            self.assertTrue(icon.run_finished.is_set())
            self.assertIsNone(
                tray_service.icon_runner_thread
            )

        self.instance_service.release.side_effect = (
            verify_tray_stopped_before_release
        )

        try:
            with (
                patch(
                    "application.services."
                    "application_tray_service.pystray.Icon",
                    return_value=icon,
                ),
                patch(
                    "application.services."
                    "application_tray_service.pystray.MenuItem",
                    side_effect=(object(), object()),
                ),
                patch(
                    "application.services."
                    "application_tray_service.pystray.Menu",
                    return_value=object(),
                ) as menu_class,
            ):
                menu_class.SEPARATOR = object()
                launcher.run()

        finally:
            icon.stop_requested.set()
            runner = tray_service.icon_runner_thread

            if runner is not None:
                runner.join(timeout=2.0)

        self.assertFalse(
            any(
                thread.name
                == "LeagueMasteryTrackerTrayIcon"
                and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationShutdownService"
    )
    def test_default_shutdown_service_is_created(
        self,
        shutdown_service_class,
    ):
        launcher = ApplicationLauncherService(
            instance_service=Mock(),
            server_service=Mock(),
            browser_service=Mock(),
            tray_service=Mock(),
            tab_lifecycle_service=Mock(),
            app_factory=Mock(),
        )

        shutdown_service_class.assert_called_once_with()

        self.assertIs(
            launcher.shutdown_service,
            shutdown_service_class.return_value,
        )


if __name__ == "__main__":
    unittest.main()
