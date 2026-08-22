import unittest
from unittest.mock import Mock

from flask import Flask

from application.routes.application_control import (
    application_control_bp,
)
from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)


class ApplicationTabLifecycleRouteTests(
    unittest.TestCase
):
    EXTENSION_KEY = (
        "league_mastery_tracker_tab_lifecycle_service"
    )

    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "application-tab-lifecycle-route-test"
            ),
        )

        self.app.register_blueprint(
            application_control_bp
        )

        self.client = (
            self.app.test_client()
        )

    def _configure_service(
        self,
        lifecycle_service,
    ):
        self.app.extensions[
            self.EXTENSION_KEY
        ] = lifecycle_service

    def test_service_defines_flask_extension_key(
        self
    ):
        self.assertEqual(
            ApplicationTabLifecycleService
            .FLASK_EXTENSION_KEY,
            self.EXTENSION_KEY,
        )

    def test_heartbeat_endpoint_rejects_get(
        self
    ):
        response = self.client.get(
            "/application/tabs/heartbeat"
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_close_endpoint_rejects_get(
        self
    ):
        response = self.client.get(
            "/application/tabs/close"
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_heartbeat_requires_configured_service(
        self
    ):
        response = self.client.post(
            "/application/tabs/heartbeat",
            data={
                "tab_id": "tab-one",
            },
        )

        self.assertEqual(
            response.status_code,
            503,
        )

    def test_close_requires_configured_service(
        self
    ):
        response = self.client.post(
            "/application/tabs/close",
            data={
                "tab_id": "tab-one",
            },
        )

        self.assertEqual(
            response.status_code,
            503,
        )

    def test_heartbeat_requires_tab_identifier(
        self
    ):
        lifecycle_service = Mock()

        self._configure_service(
            lifecycle_service
        )

        response = self.client.post(
            "/application/tabs/heartbeat",
            data={
                "tab_id": "",
            },
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        lifecycle_service.touch_tab.assert_not_called()

    def test_close_requires_tab_identifier(
        self
    ):
        lifecycle_service = Mock()

        self._configure_service(
            lifecycle_service
        )

        response = self.client.post(
            "/application/tabs/close",
            data={
                "tab_id": "",
            },
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        lifecycle_service.close_tab.assert_not_called()

    def test_heartbeat_touches_tab(
        self
    ):
        lifecycle_service = Mock()

        lifecycle_service.touch_tab.return_value = (
            True
        )

        self._configure_service(
            lifecycle_service
        )

        response = self.client.post(
            "/application/tabs/heartbeat",
            data={
                "tab_id": "tab-one",
            },
        )

        self.assertEqual(
            response.status_code,
            204,
        )

        lifecycle_service.touch_tab.assert_called_once_with(
            "tab-one"
        )

    def test_existing_tab_heartbeat_is_accepted(
        self
    ):
        lifecycle_service = Mock()

        lifecycle_service.touch_tab.return_value = (
            False
        )

        self._configure_service(
            lifecycle_service
        )

        response = self.client.post(
            "/application/tabs/heartbeat",
            data={
                "tab_id": "tab-one",
            },
        )

        self.assertEqual(
            response.status_code,
            204,
        )

        lifecycle_service.touch_tab.assert_called_once_with(
            "tab-one"
        )

    def test_close_removes_tab(
        self
    ):
        lifecycle_service = Mock()

        lifecycle_service.close_tab.return_value = (
            True
        )

        self._configure_service(
            lifecycle_service
        )

        response = self.client.post(
            "/application/tabs/close",
            data={
                "tab_id": "tab-one",
            },
        )

        self.assertEqual(
            response.status_code,
            204,
        )

        lifecycle_service.close_tab.assert_called_once_with(
            "tab-one"
        )

    def test_closing_unknown_tab_is_accepted(
        self
    ):
        lifecycle_service = Mock()

        lifecycle_service.close_tab.return_value = (
            False
        )

        self._configure_service(
            lifecycle_service
        )

        response = self.client.post(
            "/application/tabs/close",
            data={
                "tab_id": "unknown-tab",
            },
        )

        self.assertEqual(
            response.status_code,
            204,
        )

        lifecycle_service.close_tab.assert_called_once_with(
            "unknown-tab"
        )


if __name__ == "__main__":
    unittest.main()