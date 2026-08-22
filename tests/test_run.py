import unittest
from unittest.mock import Mock, patch

import run


class RunEntrypointTests(
    unittest.TestCase
):
    @patch(
        "run.ApplicationLauncherService"
    )
    def test_main_creates_and_runs_launcher(
        self,
        launcher_service_class,
    ):
        launcher = Mock()

        launcher.run.return_value = {
            "started": True,
            "reason": "server_stopped",
        }

        launcher_service_class.return_value = (
            launcher
        )

        result = run.main()

        launcher_service_class.assert_called_once_with()
        launcher.run.assert_called_once_with()

        self.assertEqual(
            result,
            {
                "started": True,
                "reason": "server_stopped",
            },
        )

    @patch(
        "run.ApplicationLauncherService"
    )
    def test_main_returns_already_running_result(
        self,
        launcher_service_class,
    ):
        launcher = Mock()

        launcher.run.return_value = {
            "started": False,
            "reason": "already_running",
        }

        launcher_service_class.return_value = (
            launcher
        )

        result = run.main()

        self.assertEqual(
            result,
            {
                "started": False,
                "reason": "already_running",
            },
        )

    @patch(
        "run.ApplicationLauncherService"
    )
    def test_launcher_error_is_not_hidden(
        self,
        launcher_service_class,
    ):
        launcher = Mock()

        launcher.run.side_effect = RuntimeError(
            "launcher failed"
        )

        launcher_service_class.return_value = (
            launcher
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "launcher failed",
        ):
            run.main()


if __name__ == "__main__":
    unittest.main()