import unittest
from unittest.mock import Mock, call, patch

from application.services.application_launcher_service import (
    ApplicationLauncherService,
)
from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)


class ApplicationLauncherTabLifecycleTests(
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

    def test_tab_lifecycle_service_is_registered_in_flask_extensions(
        self
    ):
        self.launcher.run()

        extension_key = (
            ApplicationTabLifecycleService
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
            self.tab_lifecycle_service,
        )

    def test_tab_monitor_starts_before_browser_open(
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

    def test_tab_monitor_is_stopped_after_normal_shutdown(
        self
    ):
        self.launcher.run()

        self.tab_lifecycle_service.start.assert_called_once_with()

        self.tab_lifecycle_service.stop.assert_called_once_with()

    def test_second_instance_does_not_start_tab_monitor(
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

        self.tab_lifecycle_service.start.assert_not_called()
        self.tab_lifecycle_service.stop.assert_not_called()

        self.assertEqual(
            self.flask_app.extensions,
            {},
        )

    def test_tab_monitor_start_failure_releases_resources(
        self
    ):
        self.tab_lifecycle_service.start.side_effect = (
            RuntimeError(
                "tab monitor failed"
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "tab monitor failed",
        ):
            self.launcher.run()

        self.tab_lifecycle_service.stop.assert_called_once_with()
        self.tray_service.stop.assert_called_once_with()
        self.server_service.close.assert_called_once_with()
        self.instance_service.release.assert_called_once_with()

        self.browser_service.start_background_open.assert_not_called()
        self.server_service.run.assert_not_called()

    @patch(
        "application.services."
        "application_launcher_service."
        "ApplicationTabLifecycleService"
    )
    def test_default_tab_lifecycle_service_is_created(
        self,
        tab_lifecycle_service_class,
    ):
        shutdown_service = Mock()

        launcher = ApplicationLauncherService(
            instance_service=Mock(),
            server_service=Mock(),
            browser_service=Mock(),
            shutdown_service=(
                shutdown_service
            ),
            tray_service=Mock(),
            app_factory=Mock(),
        )

        tab_lifecycle_service_class.assert_called_once_with(
            shutdown_callback=(
                shutdown_service.request_shutdown
            ),
        )

        self.assertIs(
            launcher.tab_lifecycle_service,
            tab_lifecycle_service_class.return_value,
        )


if __name__ == "__main__":
    unittest.main()