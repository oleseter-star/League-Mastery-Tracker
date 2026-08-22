import socket
import unittest
from unittest.mock import Mock, patch

from application.services.application_server_service import (
    ApplicationPortInUseError,
    ApplicationServerService,
)


class ApplicationServerServiceTests(
    unittest.TestCase
):
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

    def test_available_port_passes_validation(
        self
    ):
        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        ) as occupied_socket:
            occupied_socket.bind(
                (
                    "127.0.0.1",
                    0,
                )
            )

            available_port = (
                occupied_socket
                .getsockname()[1]
            )

        service = ApplicationServerService(
            port=available_port,
        )

        service.ensure_port_available()

    def test_occupied_port_is_rejected(self):
        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        ) as occupied_socket:
            occupied_socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )

            occupied_socket.bind(
                (
                    "127.0.0.1",
                    0,
                )
            )

            occupied_socket.listen(
                1
            )

            occupied_port = (
                occupied_socket
                .getsockname()[1]
            )

            service = ApplicationServerService(
                port=occupied_port,
            )

            with self.assertRaises(
                ApplicationPortInUseError
            ):
                service.ensure_port_available()

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