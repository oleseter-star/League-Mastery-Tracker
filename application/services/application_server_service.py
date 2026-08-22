import _thread
import socket

import waitress


class ApplicationPortInUseError(OSError):
    """
    Raised when the configured local application port is already
    occupied.
    """


class ApplicationServerService:
    """
    Creates and controls the local Waitress WSGI server.

    The application binds only to the IPv4 loopback interface.

    Browser-requested shutdown is signalled to the launcher's main
    thread with KeyboardInterrupt. The launcher then performs the
    actual Waitress cleanup after server.run() returns.
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 5000
    DEFAULT_THREAD_COUNT = 4

    def __init__(
        self,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
    ):
        normalized_host = str(
            host or ""
        ).strip()

        if not normalized_host:
            raise ValueError(
                "The application server host cannot be empty."
            )

        if normalized_host != self.DEFAULT_HOST:
            raise ValueError(
                "The application server may only bind to "
                "127.0.0.1."
            )

        normalized_port = self._normalize_port(
            port
        )

        self.host = normalized_host
        self.port = normalized_port

        self._server = None
        self._shutdown_requested = False

    @property
    def server(self):
        """
        Return the currently created Waitress server.
        """

        return self._server

    @property
    def shutdown_requested(self):
        """
        Return whether a controlled shutdown has been requested.
        """

        return self._shutdown_requested

    @property
    def application_url(self):
        """
        Return the browser URL for the local application.
        """

        return (
            f"http://{self.host}:{self.port}/"
        )

    def ensure_port_available(self):
        """
        Verify that the configured loopback port can be bound.
        """

        test_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        try:
            test_socket.bind(
                (
                    self.host,
                    self.port,
                )
            )

        except OSError as error:
            raise ApplicationPortInUseError(
                "League Mastery Tracker could not start because "
                f"local port {self.port} is already in use."
            ) from error

        finally:
            test_socket.close()

    def create_server(
        self,
        flask_app,
    ):
        """
        Create the Waitress server for the supplied Flask app.

        A service instance can own only one server at a time.
        """

        if self._server is not None:
            raise RuntimeError(
                "The application server has already been created."
            )

        if flask_app is None:
            raise ValueError(
                "A Flask application is required."
            )

        self._shutdown_requested = False

        self._server = waitress.create_server(
            flask_app,
            host=self.host,
            port=self.port,
            threads=self.DEFAULT_THREAD_COUNT,
            clear_untrusted_proxy_headers=True,
        )

        return self._server

    def run(self):
        """
        Run the created Waitress server until shutdown.
        """

        if self._server is None:
            raise RuntimeError(
                "The application server has not been created."
            )

        self._server.run()

    def request_shutdown(self):
        """
        Signal a controlled shutdown to the launcher's main thread.

        Returns True for the first accepted request and False when
        shutdown has already been requested.
        """

        if self._server is None:
            raise RuntimeError(
                "The application server has not been created."
            )

        if self._shutdown_requested:
            return False

        self._shutdown_requested = True

        try:
            _thread.interrupt_main()

        except Exception:
            self._shutdown_requested = False
            raise

        return True

    def close(self):
        """
        Close the Waitress server after its run loop has stopped.

        Calling close repeatedly is safe.
        """

        if self._server is None:
            self._shutdown_requested = False
            return

        server = self._server
        self._server = None

        try:
            server.close()

        finally:
            self._shutdown_requested = False

    @staticmethod
    def _normalize_port(
        port,
    ):
        """
        Normalize and validate a TCP port number.
        """

        if isinstance(
            port,
            bool,
        ):
            raise ValueError(
                "The application server port must be an integer "
                "between 1 and 65535."
            )

        try:
            normalized_port = int(
                port
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                "The application server port must be an integer "
                "between 1 and 65535."
            ) from error

        if not (
            1
            <= normalized_port
            <= 65535
        ):
            raise ValueError(
                "The application server port must be an integer "
                "between 1 and 65535."
            )

        return normalized_port