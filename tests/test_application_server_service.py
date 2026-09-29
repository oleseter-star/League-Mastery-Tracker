import errno
import socket
import sys
import time
import unittest
from unittest.mock import Mock, call, patch

from application.services.application_server_service import (
    ApplicationPortInUseError,
    ApplicationServerService,
)


class ApplicationServerServiceTests(
    unittest.TestCase
):
    SOCKET_TIMEOUT_SECONDS = 2.0

    @staticmethod
    def _linux_tcp_state_present(
        port,
        state,
    ):
        expected_address = (
            f"0100007F:{port:04X}"
        )

        with open(
            "/proc/net/tcp",
            encoding="ascii",
        ) as tcp_table:
            next(tcp_table)

            return any(
                fields[1] == expected_address
                and fields[3] == state
                for fields in (
                    line.split()
                    for line in tcp_table
                )
            )

    @classmethod
    def _wait_for_linux_tcp_state(
        cls,
        port,
        state,
    ):
        deadline = (
            time.monotonic()
            + cls.SOCKET_TIMEOUT_SECONDS
        )

        while time.monotonic() < deadline:
            if cls._linux_tcp_state_present(
                port,
                state,
            ):
                return True

            time.sleep(0.01)

        return cls._linux_tcp_state_present(
            port,
            state,
        )

    def test_default_server_address_is_local_only(
        self
    ):
        service = ApplicationServerService()

        self.assertEqual(
            service.host,
            "127.0.0.1",
        )

        self.assertEqual(
            service.port,
            5000,
        )

        self.assertEqual(
            service.application_url,
            "http://127.0.0.1:5000/",
        )

        self.assertFalse(
            service.shutdown_requested
        )

    def test_custom_server_address_is_supported(
        self
    ):
        service = ApplicationServerService(
            host="127.0.0.1",
            port=5123,
        )

        self.assertEqual(
            service.application_url,
            "http://127.0.0.1:5123/",
        )

    def test_empty_host_is_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            ApplicationServerService(
                host="",
            )

    def test_invalid_port_is_rejected(self):
        invalid_ports = (
            0,
            -1,
            65536,
            "not-a-port",
        )

        for invalid_port in invalid_ports:
            with self.subTest(
                invalid_port=invalid_port
            ):
                with self.assertRaises(
                    ValueError
                ):
                    ApplicationServerService(
                        port=invalid_port,
                    )

    @patch(
        "application.services."
        "application_server_service."
        "sys.platform",
        "linux",
    )
    @patch(
        "application.services."
        "application_server_service."
        "socket.socket"
    )
    def test_available_port_passes_validation(
        self,
        socket_constructor,
    ):
        test_socket = Mock(
            spec=(
                "setsockopt",
                "bind",
                "close",
            )
        )
        socket_constructor.return_value = test_socket

        service = ApplicationServerService(
            port=5125,
        )

        service.ensure_port_available()

        socket_constructor.assert_called_once_with(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
        self.assertEqual(
            test_socket.mock_calls,
            [
                call.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_REUSEADDR,
                    1,
                ),
                call.bind(
                    ("127.0.0.1", 5125),
                ),
                call.close(),
            ],
        )

    @patch(
        "application.services."
        "application_server_service."
        "socket.socket"
    )
    def test_non_linux_port_check_remains_option_free(
        self,
        socket_constructor,
    ):
        for platform_name in (
            "win32",
            "darwin",
        ):
            with self.subTest(
                platform_name=platform_name
            ):
                test_socket = Mock(
                    spec=(
                        "setsockopt",
                        "bind",
                        "close",
                    )
                )
                socket_constructor.return_value = (
                    test_socket
                )

                with patch(
                    "application.services."
                    "application_server_service."
                    "sys.platform",
                    platform_name,
                ):
                    ApplicationServerService(
                        port=5125,
                    ).ensure_port_available()

                test_socket.setsockopt.assert_not_called()
                self.assertEqual(
                    test_socket.mock_calls,
                    [
                        call.bind(
                            ("127.0.0.1", 5125),
                        ),
                        call.close(),
                    ],
                )

        self.assertEqual(
            socket_constructor.call_count,
            2,
        )

    @patch(
        "application.services."
        "application_server_service."
        "sys.platform",
        "linux",
    )
    @patch(
        "application.services."
        "application_server_service."
        "socket.socket"
    )
    def test_occupied_port_is_rejected(
        self,
        socket_constructor,
    ):
        raw_error = OSError(
            errno.EADDRINUSE,
            "Address already in use.",
        )
        test_socket = Mock(
            spec=(
                "setsockopt",
                "bind",
                "close",
            )
        )
        test_socket.bind.side_effect = raw_error
        socket_constructor.return_value = test_socket

        service = ApplicationServerService(
            port=5125,
        )

        with self.assertRaises(
            ApplicationPortInUseError
        ) as raised:
            service.ensure_port_available()

        self.assertEqual(
            str(raised.exception),
            "League Mastery Tracker could not start because "
            "local port 5125 is already in use.",
        )
        self.assertIs(
            raised.exception.__cause__,
            raw_error,
        )
        self.assertEqual(
            test_socket.mock_calls,
            [
                call.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_REUSEADDR,
                    1,
                ),
                call.bind(
                    ("127.0.0.1", 5125),
                ),
                call.close(),
            ],
        )

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux TCP state behavior is required.",
    )
    def test_linux_time_wait_address_is_available(
        self
    ):
        listener = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
        client = None
        accepted = None
        plain_probe = None

        try:
            listener.settimeout(
                self.SOCKET_TIMEOUT_SECONDS
            )
            listener.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            self.assertNotEqual(port, 5000)
            listener.listen(1)

            client = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
            client.settimeout(
                self.SOCKET_TIMEOUT_SECONDS
            )
            client.connect(("127.0.0.1", port))

            accepted, _address = listener.accept()
            accepted.settimeout(
                self.SOCKET_TIMEOUT_SECONDS
            )
            accepted.shutdown(socket.SHUT_WR)
            self.assertEqual(client.recv(1), b"")
            client.close()
            client = None
            self.assertEqual(accepted.recv(1), b"")
            accepted.close()
            accepted = None
            listener.close()

            self.assertTrue(
                self._wait_for_linux_tcp_state(
                    port,
                    "06",
                ),
                "Server-side TIME-WAIT was not established.",
            )

            plain_probe = socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
            with self.assertRaises(OSError) as old_behavior:
                plain_probe.bind(("127.0.0.1", port))
            self.assertEqual(
                old_behavior.exception.errno,
                errno.EADDRINUSE,
            )
            plain_probe.close()
            plain_probe = None

            ApplicationServerService(
                port=port,
            ).ensure_port_available()

        finally:
            if plain_probe is not None:
                plain_probe.close()
            if accepted is not None:
                accepted.close()
            if client is not None:
                client.close()
            listener.close()

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "Linux TCP binding behavior is required.",
    )
    def test_linux_live_reusable_listener_is_rejected(
        self
    ):
        listener = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        try:
            listener.settimeout(
                self.SOCKET_TIMEOUT_SECONDS
            )
            listener.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            self.assertNotEqual(port, 5000)
            listener.listen(1)

            with self.assertRaises(
                ApplicationPortInUseError
            ) as raised:
                ApplicationServerService(
                    port=port,
                ).ensure_port_available()

            self.assertEqual(
                str(raised.exception),
                "League Mastery Tracker could not start because "
                f"local port {port} is already in use.",
            )
            self.assertIsInstance(
                raised.exception.__cause__,
                OSError,
            )
            self.assertEqual(
                raised.exception.__cause__.errno,
                errno.EADDRINUSE,
            )

        finally:
            listener.close()

    @patch(
        "application.services."
        "application_server_service."
        "waitress.create_server"
    )
    def test_server_is_created_with_local_binding(
        self,
        create_server_mock,
    ):
        flask_app = Mock()
        waitress_server = Mock()

        create_server_mock.return_value = (
            waitress_server
        )

        service = ApplicationServerService(
            port=5124,
        )

        result = service.create_server(
            flask_app
        )

        self.assertIs(
            result,
            waitress_server,
        )

        self.assertIs(
            service.server,
            waitress_server,
        )

        self.assertFalse(
            service.shutdown_requested
        )

        create_server_mock.assert_called_once_with(
            flask_app,
            host="127.0.0.1",
            port=5124,
            threads=4,
            clear_untrusted_proxy_headers=True,
        )

    def test_server_cannot_be_created_twice(
        self
    ):
        service = ApplicationServerService()

        service._server = Mock()

        with self.assertRaises(
            RuntimeError
        ):
            service.create_server(
                Mock()
            )

    def test_run_requires_created_server(self):
        service = ApplicationServerService()

        with self.assertRaises(
            RuntimeError
        ):
            service.run()

    def test_run_delegates_to_waitress_server(
        self
    ):
        waitress_server = Mock()

        service = ApplicationServerService()
        service._server = waitress_server

        service.run()

        waitress_server.run.assert_called_once_with()

    def test_shutdown_requires_created_server(
        self
    ):
        service = ApplicationServerService()

        with self.assertRaises(
            RuntimeError
        ):
            service.request_shutdown()

        self.assertFalse(
            service.shutdown_requested
        )

    @patch(
        "application.services."
        "application_server_service."
        "_thread.interrupt_main"
    )
    def test_shutdown_interrupts_main_thread(
        self,
        interrupt_main_mock,
    ):
        service = ApplicationServerService()
        service._server = Mock()

        result = service.request_shutdown()

        self.assertTrue(
            result
        )

        self.assertTrue(
            service.shutdown_requested
        )

        interrupt_main_mock.assert_called_once_with()

    @patch(
        "application.services."
        "application_server_service."
        "_thread.interrupt_main"
    )
    def test_repeated_shutdown_request_is_ignored(
        self,
        interrupt_main_mock,
    ):
        service = ApplicationServerService()
        service._server = Mock()

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

        self.assertTrue(
            service.shutdown_requested
        )

        interrupt_main_mock.assert_called_once_with()

    def test_close_without_server_is_safe(self):
        service = ApplicationServerService()

        service.close()

        self.assertIsNone(
            service.server
        )

        self.assertFalse(
            service.shutdown_requested
        )

    def test_close_delegates_to_waitress_server(
        self
    ):
        waitress_server = Mock()

        service = ApplicationServerService()
        service._server = waitress_server
        service._shutdown_requested = True

        service.close()

        waitress_server.close.assert_called_once_with()

        self.assertIsNone(
            service.server
        )

        self.assertFalse(
            service.shutdown_requested
        )

    def test_repeated_close_is_safe(self):
        waitress_server = Mock()

        service = ApplicationServerService()
        service._server = waitress_server

        service.close()
        service.close()

        waitress_server.close.assert_called_once_with()

        self.assertIsNone(
            service.server
        )


if __name__ == "__main__":
    unittest.main()
