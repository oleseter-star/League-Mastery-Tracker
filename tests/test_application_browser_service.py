import unittest
from urllib.error import URLError
from unittest.mock import MagicMock, patch

from application.services.application_browser_service import (
    ApplicationBrowserOpenError,
    ApplicationBrowserService,
    ApplicationReadinessTimeoutError,
)


class ApplicationBrowserServiceTests(unittest.TestCase):
    def test_default_settings_are_defined(self):
        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
        )

        self.assertEqual(
            service.application_url,
            "http://127.0.0.1:5000/",
        )

        self.assertEqual(
            service.startup_timeout_seconds,
            15.0,
        )

        self.assertEqual(
            service.poll_interval_seconds,
            0.1,
        )

        self.assertEqual(
            service.request_timeout_seconds,
            1.0,
        )

    def test_empty_application_url_is_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            ApplicationBrowserService(
                application_url="",
            )

    def test_invalid_timing_values_are_rejected(self):
        invalid_values = (
            0,
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
                    ApplicationBrowserService(
                        application_url=(
                            "http://127.0.0.1:5000/"
                        ),
                        startup_timeout_seconds=(
                            invalid_value
                        ),
                    )

                with self.assertRaises(
                    ValueError
                ):
                    ApplicationBrowserService(
                        application_url=(
                            "http://127.0.0.1:5000/"
                        ),
                        poll_interval_seconds=(
                            invalid_value
                        ),
                    )

                with self.assertRaises(
                    ValueError
                ):
                    ApplicationBrowserService(
                        application_url=(
                            "http://127.0.0.1:5000/"
                        ),
                        request_timeout_seconds=(
                            invalid_value
                        ),
                    )

    @patch(
        "application.services."
        "application_browser_service."
        "urllib.request.urlopen"
    )
    def test_ready_server_is_detected_immediately(
        self,
        urlopen_mock,
    ):
        response = MagicMock()
        response.status = 200

        response_context = MagicMock()
        response_context.__enter__.return_value = (
            response
        )

        urlopen_mock.return_value = (
            response_context
        )

        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
        )

        result = service.wait_until_ready()

        self.assertTrue(
            result
        )

        urlopen_mock.assert_called_once_with(
            "http://127.0.0.1:5000/",
            timeout=1.0,
        )

    @patch(
        "application.services."
        "application_browser_service."
        "time.sleep"
    )
    @patch(
        "application.services."
        "application_browser_service."
        "time.monotonic"
    )
    @patch(
        "application.services."
        "application_browser_service."
        "urllib.request.urlopen"
    )
    def test_server_check_retries_until_ready(
        self,
        urlopen_mock,
        monotonic_mock,
        sleep_mock,
    ):
        response = MagicMock()
        response.status = 200

        response_context = MagicMock()
        response_context.__enter__.return_value = (
            response
        )

        urlopen_mock.side_effect = [
            URLError(
                "server not ready"
            ),
            response_context,
        ]

        monotonic_mock.side_effect = [
            0.0,
            0.1,
        ]

        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
            startup_timeout_seconds=5.0,
            poll_interval_seconds=0.25,
        )

        result = service.wait_until_ready()

        self.assertTrue(
            result
        )

        self.assertEqual(
            urlopen_mock.call_count,
            2,
        )

        sleep_mock.assert_called_once_with(
            0.25
        )

    @patch(
        "application.services."
        "application_browser_service."
        "time.sleep"
    )
    @patch(
        "application.services."
        "application_browser_service."
        "time.monotonic"
    )
    @patch(
        "application.services."
        "application_browser_service."
        "urllib.request.urlopen"
    )
    def test_readiness_timeout_is_reported(
        self,
        urlopen_mock,
        monotonic_mock,
        sleep_mock,
    ):
        urlopen_mock.side_effect = URLError(
            "server unavailable"
        )

        monotonic_mock.side_effect = [
            0.0,
            0.1,
            1.1,
        ]

        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
            startup_timeout_seconds=1.0,
            poll_interval_seconds=0.25,
        )

        with self.assertRaises(
            ApplicationReadinessTimeoutError
        ):
            service.wait_until_ready()

        self.assertEqual(
            urlopen_mock.call_count,
            2,
        )

        sleep_mock.assert_called_once_with(
            0.25
        )

    @patch(
        "application.services."
        "application_browser_service."
        "webbrowser.open"
    )
    def test_application_opens_in_default_browser(
        self,
        browser_open_mock,
    ):
        browser_open_mock.return_value = True

        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
        )

        result = service.open_browser()

        self.assertTrue(
            result
        )

        browser_open_mock.assert_called_once_with(
            "http://127.0.0.1:5000/",
            new=2,
            autoraise=True,
        )

    @patch(
        "application.services."
        "application_browser_service."
        "webbrowser.open"
    )
    def test_browser_open_failure_is_reported(
        self,
        browser_open_mock,
    ):
        browser_open_mock.return_value = False

        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
        )

        with self.assertRaises(
            ApplicationBrowserOpenError
        ):
            service.open_browser()

    @patch.object(
        ApplicationBrowserService,
        "open_browser",
        return_value=True,
    )
    @patch.object(
        ApplicationBrowserService,
        "wait_until_ready",
        return_value=True,
    )
    def test_wait_and_open_runs_in_correct_order(
        self,
        wait_until_ready_mock,
        open_browser_mock,
    ):
        service = ApplicationBrowserService(
            application_url=(
                "http://127.0.0.1:5000/"
            ),
        )

        result = (
            service
            .wait_until_ready_and_open()
        )

        self.assertTrue(
            result
        )

        wait_until_ready_mock.assert_called_once_with()
        open_browser_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()