import unittest
from unittest.mock import Mock, patch

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


class ApplicationTabLifecycleServiceTests(
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

    def test_default_settings_are_defined(self):
        self.assertEqual(
            self.service.heartbeat_timeout_seconds,
            300.0,
        )

        self.assertEqual(
            self.service.empty_grace_seconds,
            5.0,
        )

        self.assertEqual(
            self.service.monitor_interval_seconds,
            1.0,
        )

        self.assertEqual(
            self.service.active_tab_count,
            0,
        )

        self.assertFalse(
            self.service.has_registered_tab
        )

        self.assertFalse(
            self.service.shutdown_requested
        )

        self.assertFalse(
            self.service.is_running
        )

        self.assertIsNone(
            self.service.monitor_thread
        )

        self.assertIsNone(
            self.service.background_error
        )

    def test_invalid_timing_values_are_rejected(
        self
    ):
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
                    ApplicationTabLifecycleService(
                        shutdown_callback=(
                            self.shutdown_callback
                        ),
                        heartbeat_timeout_seconds=(
                            invalid_value
                        ),
                    )

                with self.assertRaises(
                    ValueError
                ):
                    ApplicationTabLifecycleService(
                        shutdown_callback=(
                            self.shutdown_callback
                        ),
                        empty_grace_seconds=(
                            invalid_value
                        ),
                    )

                with self.assertRaises(
                    ValueError
                ):
                    ApplicationTabLifecycleService(
                        shutdown_callback=(
                            self.shutdown_callback
                        ),
                        monitor_interval_seconds=(
                            invalid_value
                        ),
                    )

    def test_non_callable_shutdown_callback_is_rejected(
        self
    ):
        with self.assertRaises(
            ValueError
        ):
            ApplicationTabLifecycleService(
                shutdown_callback=(
                    "not-callable"
                ),
            )

    def test_empty_tab_identifier_is_rejected(
        self
    ):
        with self.assertRaises(
            ValueError
        ):
            self.service.touch_tab(
                ""
            )

    def test_touch_registers_new_tab(self):
        result = self.service.touch_tab(
            "tab-one"
        )

        self.assertTrue(
            result
        )

        self.assertEqual(
            self.service.active_tab_count,
            1,
        )

        self.assertTrue(
            self.service.has_registered_tab
        )

        self.assertEqual(
            self.service.get_active_tab_ids(),
            (
                "tab-one",
            ),
        )

        self.shutdown_callback.assert_not_called()

    def test_touch_refreshes_existing_tab(self):
        self.service.touch_tab(
            "tab-one"
        )

        self.clock.advance(
            200
        )

        result = self.service.touch_tab(
            "tab-one"
        )

        self.assertFalse(
            result
        )

        self.clock.advance(
            101
        )

        self.service.evaluate_once()

        self.assertEqual(
            self.service.active_tab_count,
            1,
        )

        self.shutdown_callback.assert_not_called()

    def test_close_removes_tab(self):
        self.service.touch_tab(
            "tab-one"
        )

        result = self.service.close_tab(
            "tab-one"
        )

        self.assertTrue(
            result
        )

        self.assertEqual(
            self.service.active_tab_count,
            0,
        )

        self.assertTrue(
            self.service.has_registered_tab
        )

        self.shutdown_callback.assert_not_called()

    def test_close_unknown_tab_is_safe(self):
        result = self.service.close_tab(
            "unknown-tab"
        )

        self.assertFalse(
            result
        )

        self.assertEqual(
            self.service.active_tab_count,
            0,
        )

    def test_service_does_not_shutdown_before_first_tab(
        self
    ):
        self.clock.advance(
            600
        )

        result = self.service.evaluate_once()

        self.assertFalse(
            result
        )

        self.assertFalse(
            self.service.shutdown_requested
        )

        self.shutdown_callback.assert_not_called()

    def test_stale_tab_is_removed_after_timeout(
        self
    ):
        self.service.touch_tab(
            "tab-one"
        )

        self.clock.advance(
            300
        )

        result = self.service.evaluate_once()

        self.assertFalse(
            result
        )

        self.assertEqual(
            self.service.active_tab_count,
            0,
        )

        self.assertFalse(
            self.service.shutdown_requested
        )

        self.shutdown_callback.assert_not_called()

    def test_shutdown_occurs_after_empty_grace_period(
        self
    ):
        self.service.touch_tab(
            "tab-one"
        )

        self.service.close_tab(
            "tab-one"
        )

        self.clock.advance(
            4.9
        )

        first_result = (
            self.service.evaluate_once()
        )

        self.assertFalse(
            first_result
        )

        self.shutdown_callback.assert_not_called()

        self.clock.advance(
            0.1
        )

        second_result = (
            self.service.evaluate_once()
        )

        self.assertTrue(
            second_result
        )

        self.assertTrue(
            self.service.shutdown_requested
        )

        self.shutdown_callback.assert_called_once_with()

    def test_new_tab_cancels_empty_grace_period(
        self
    ):
        self.service.touch_tab(
            "tab-one"
        )

        self.service.close_tab(
            "tab-one"
        )

        self.clock.advance(
            4
        )

        self.service.touch_tab(
            "tab-two"
        )

        self.clock.advance(
            2
        )

        result = self.service.evaluate_once()

        self.assertFalse(
            result
        )

        self.assertEqual(
            self.service.active_tab_count,
            1,
        )

        self.shutdown_callback.assert_not_called()

    def test_repeated_evaluation_does_not_repeat_shutdown(
        self
    ):
        self.service.touch_tab(
            "tab-one"
        )

        self.service.close_tab(
            "tab-one"
        )

        self.clock.advance(
            5
        )

        first_result = (
            self.service.evaluate_once()
        )

        second_result = (
            self.service.evaluate_once()
        )

        self.assertTrue(
            first_result
        )

        self.assertFalse(
            second_result
        )

        self.shutdown_callback.assert_called_once_with()

    @patch(
        "application.services."
        "application_tab_lifecycle_service."
        "threading.Thread"
    )
    def test_start_creates_monitor_thread(
        self,
        thread_class,
    ):
        monitor_thread = Mock()

        thread_class.return_value = (
            monitor_thread
        )

        result = self.service.start()

        self.assertIs(
            result,
            monitor_thread,
        )

        self.assertIs(
            self.service.monitor_thread,
            monitor_thread,
        )

        self.assertTrue(
            self.service.is_running
        )

        thread_class.assert_called_once_with(
            target=self.service._run_monitor,
            name=(
                "LeagueMasteryTrackerTabMonitor"
            ),
            daemon=True,
        )

        monitor_thread.start.assert_called_once_with()

    @patch(
        "application.services."
        "application_tab_lifecycle_service."
        "threading.Thread"
    )
    def test_repeated_start_reuses_monitor_thread(
        self,
        thread_class,
    ):
        monitor_thread = Mock()

        thread_class.return_value = (
            monitor_thread
        )

        first_result = self.service.start()
        second_result = self.service.start()

        self.assertIs(
            first_result,
            monitor_thread,
        )

        self.assertIs(
            second_result,
            monitor_thread,
        )

        thread_class.assert_called_once()
        monitor_thread.start.assert_called_once_with()

    def test_stop_without_monitor_is_safe(self):
        result = self.service.stop()

        self.assertFalse(
            result
        )

        self.assertFalse(
            self.service.is_running
        )

        self.assertIsNone(
            self.service.monitor_thread
        )


if __name__ == "__main__":
    unittest.main()