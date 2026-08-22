import unittest
from unittest.mock import Mock

from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)


class FakeClock:
    def __init__(self):
        self.current_time = 0.0

    def __call__(self):
        return self.current_time

    def advance(
        self,
        seconds,
    ):
        self.current_time += seconds


class ApplicationTabLifecycleBackgroundTabTests(
    unittest.TestCase
):
    def setUp(self):
        self.clock = FakeClock()

        self.shutdown_callback = Mock(
            return_value=True
        )

        self.service = (
            ApplicationTabLifecycleService(
                shutdown_callback=(
                    self.shutdown_callback
                ),
                clock=self.clock,
            )
        )

    def test_default_heartbeat_timeout_tolerates_background_tabs(
        self
    ):
        self.assertEqual(
            self.service.heartbeat_timeout_seconds,
            300.0,
        )

    def test_background_tab_is_not_expired_after_one_minute(
        self
    ):
        self.service.touch_tab(
            "background-tab"
        )

        self.clock.advance(
            60
        )

        result = self.service.evaluate_once()

        self.assertFalse(
            result
        )

        self.assertEqual(
            self.service.active_tab_count,
            1,
        )

        self.assertEqual(
            self.service.get_active_tab_ids(),
            (
                "background-tab",
            ),
        )

        self.assertFalse(
            self.service.shutdown_requested
        )

        self.shutdown_callback.assert_not_called()

    def test_missing_heartbeat_uses_long_fallback_timeout(
        self
    ):
        self.service.touch_tab(
            "abandoned-tab"
        )

        self.clock.advance(
            299.9
        )

        first_result = (
            self.service.evaluate_once()
        )

        self.assertFalse(
            first_result
        )

        self.assertEqual(
            self.service.active_tab_count,
            1,
        )

        self.shutdown_callback.assert_not_called()

        self.clock.advance(
            0.1
        )

        second_result = (
            self.service.evaluate_once()
        )

        self.assertFalse(
            second_result
        )

        self.assertEqual(
            self.service.active_tab_count,
            0,
        )

        self.shutdown_callback.assert_not_called()

        self.clock.advance(
            5
        )

        third_result = (
            self.service.evaluate_once()
        )

        self.assertTrue(
            third_result
        )

        self.assertTrue(
            self.service.shutdown_requested
        )

        self.shutdown_callback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()