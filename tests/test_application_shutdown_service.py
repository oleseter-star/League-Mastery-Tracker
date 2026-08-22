import unittest
from unittest.mock import Mock, patch

from application.services.application_shutdown_service import (
    ApplicationShutdownNotConfiguredError,
    ApplicationShutdownService,
)


class ApplicationShutdownServiceTests(
    unittest.TestCase
):
    def test_default_settings_are_defined(self):
        service = ApplicationShutdownService()

        self.assertEqual(
            service.delay_seconds,
            0.25,
        )

        self.assertFalse(
            service.callback_configured
        )

        self.assertFalse(
            service.shutdown_requested
        )

        self.assertIsNone(
            service.background_error
        )

    def test_invalid_delay_is_rejected(self):
        invalid_values = (
            -1,
            "invalid",
            True,
        )

        for invalid_value in invalid_values:
            with self.subTest(
                invalid_value=invalid_value
            ):
                with self.assertRaises(
                    ValueError
                ):
                    ApplicationShutdownService(
                        delay_seconds=(
                            invalid_value
                        ),
                    )

    def test_shutdown_callback_can_be_configured(
        self
    ):
        callback = Mock()

        service = ApplicationShutdownService()

        service.configure_shutdown_callback(
            callback
        )

        self.assertTrue(
            service.callback_configured
        )

    def test_non_callable_callback_is_rejected(
        self
    ):
        service = ApplicationShutdownService()

        with self.assertRaises(
            ValueError
        ):
            service.configure_shutdown_callback(
                "not-callable"
            )

    def test_shutdown_requires_configured_callback(
        self
    ):
        service = ApplicationShutdownService()

        with self.assertRaises(
            ApplicationShutdownNotConfiguredError
        ):
            service.request_shutdown()

        self.assertFalse(
            service.shutdown_requested
        )

    @patch(
        "application.services."
        "application_shutdown_service."
        "threading.Thread"
    )
    def test_shutdown_starts_background_thread(
        self,
        thread_class,
    ):
        callback = Mock()
        shutdown_thread = Mock()

        thread_class.return_value = (
            shutdown_thread
        )

        service = ApplicationShutdownService(
            shutdown_callback=callback,
        )

        result = service.request_shutdown()

        self.assertTrue(
            result
        )

        self.assertTrue(
            service.shutdown_requested
        )

        self.assertIs(
            service.shutdown_thread,
            shutdown_thread,
        )

        thread_class.assert_called_once_with(
            target=service._run_shutdown,
            name=(
                "LeagueMasteryTrackerShutdown"
            ),
            daemon=True,
        )

        shutdown_thread.start.assert_called_once_with()

    @patch(
        "application.services."
        "application_shutdown_service."
        "threading.Thread"
    )
    def test_repeated_shutdown_request_is_ignored(
        self,
        thread_class,
    ):
        callback = Mock()
        shutdown_thread = Mock()

        thread_class.return_value = (
            shutdown_thread
        )

        service = ApplicationShutdownService(
            shutdown_callback=callback,
        )

        first_result = (
            service.request_shutdown()
        )

        second_result = (
            service.request_shutdown()
        )

        self.assertTrue(
            first_result
        )

        self.assertFalse(
            second_result
        )

        thread_class.assert_called_once_with(
            target=service._run_shutdown,
            name=(
                "LeagueMasteryTrackerShutdown"
            ),
            daemon=True,
        )

        shutdown_thread.start.assert_called_once_with()

    @patch(
        "application.services."
        "application_shutdown_service."
        "time.sleep"
    )
    def test_background_shutdown_waits_and_calls_callback(
        self,
        sleep_mock,
    ):
        callback = Mock()

        service = ApplicationShutdownService(
            shutdown_callback=callback,
            delay_seconds=0.5,
        )

        service._run_shutdown()

        sleep_mock.assert_called_once_with(
            0.5
        )

        callback.assert_called_once_with()

        self.assertIsNone(
            service.background_error
        )

    @patch(
        "application.services."
        "application_shutdown_service."
        "time.sleep"
    )
    def test_background_shutdown_error_is_recorded(
        self,
        sleep_mock,
    ):
        callback = Mock(
            side_effect=RuntimeError(
                "shutdown failed"
            )
        )

        service = ApplicationShutdownService(
            shutdown_callback=callback,
            delay_seconds=0,
        )

        service._run_shutdown()

        sleep_mock.assert_not_called()

        self.assertIsInstance(
            service.background_error,
            RuntimeError,
        )

        self.assertEqual(
            str(
                service.background_error
            ),
            "shutdown failed",
        )


if __name__ == "__main__":
    unittest.main()