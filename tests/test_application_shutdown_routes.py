import unittest
from unittest.mock import Mock

from flask import Flask

from application.routes.application_control import (
    application_control_bp,
)
from application.services.application_shutdown_service import (
    ApplicationShutdownNotConfiguredError,
    ApplicationShutdownService,
)


class ApplicationShutdownRouteTests(
    unittest.TestCase
):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY=(
                "application-shutdown-route-test"
            ),
        )

        self.app.register_blueprint(
            application_control_bp
        )

        self.client = (
            self.app.test_client()
        )

    def _configure_shutdown_service(
        self,
        shutdown_service,
    ):
        self.app.extensions[
            ApplicationShutdownService
            .FLASK_EXTENSION_KEY
        ] = shutdown_service

    def test_shutdown_endpoint_rejects_get(
        self
    ):
        response = self.client.get(
            "/application/shutdown"
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_shutdown_requires_configured_service(
        self
    ):
        response = self.client.post(
            "/application/shutdown"
        )

        self.assertEqual(
            response.status_code,
            503,
        )

        self.assertIn(
            "Shutdown is unavailable",
            response.get_data(
                as_text=True
            ),
        )

    def test_shutdown_request_is_accepted(
        self
    ):
        shutdown_service = Mock()

        shutdown_service.request_shutdown.return_value = (
            True
        )

        self._configure_shutdown_service(
            shutdown_service
        )

        response = self.client.post(
            "/application/shutdown"
        )

        self.assertEqual(
            response.status_code,
            202,
        )

        shutdown_service.request_shutdown.assert_called_once_with()

        response_text = response.get_data(
            as_text=True
        )

        self.assertIn(
            "Application is shutting down",
            response_text,
        )

        self.assertIn(
            "You can close this browser window.",
            response_text,
        )

    def test_repeated_shutdown_request_is_safe(
        self
    ):
        shutdown_service = Mock()

        shutdown_service.request_shutdown.return_value = (
            False
        )

        self._configure_shutdown_service(
            shutdown_service
        )

        response = self.client.post(
            "/application/shutdown"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        shutdown_service.request_shutdown.assert_called_once_with()

        self.assertIn(
            "Shutdown has already started",
            response.get_data(
                as_text=True
            ),
        )

    def test_unconfigured_callback_returns_service_unavailable(
        self
    ):
        shutdown_service = Mock()

        shutdown_service.request_shutdown.side_effect = (
            ApplicationShutdownNotConfiguredError(
                "shutdown callback missing"
            )
        )

        self._configure_shutdown_service(
            shutdown_service
        )

        response = self.client.post(
            "/application/shutdown"
        )

        self.assertEqual(
            response.status_code,
            503,
        )

        self.assertIn(
            "Shutdown is unavailable",
            response.get_data(
                as_text=True
            ),
        )


if __name__ == "__main__":
    unittest.main()