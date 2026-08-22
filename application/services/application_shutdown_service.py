import math
import threading
import time


class ApplicationShutdownNotConfiguredError(
    RuntimeError
):
    """
    Raised when application shutdown is requested before a shutdown
    callback has been configured.
    """


class ApplicationShutdownService:
    """
    Coordinates a delayed and controlled application shutdown.

    The shutdown callback runs in a daemon thread so an HTTP request
    can return its response before the local Waitress server closes.
    """

    FLASK_EXTENSION_KEY = (
        "league_mastery_tracker_shutdown_service"
    )

    DEFAULT_DELAY_SECONDS = 0.25

    SHUTDOWN_THREAD_NAME = (
        "LeagueMasteryTrackerShutdown"
    )

    def __init__(
        self,
        shutdown_callback=None,
        delay_seconds=DEFAULT_DELAY_SECONDS,
    ):
        self.delay_seconds = (
            self._normalize_delay_seconds(
                delay_seconds
            )
        )

        self._shutdown_callback = None
        self._shutdown_requested = False
        self._shutdown_thread = None
        self._background_error = None
        self._state_lock = threading.Lock()

        if shutdown_callback is not None:
            self.configure_shutdown_callback(
                shutdown_callback
            )

    @property
    def callback_configured(self):
        return (
            self._shutdown_callback
            is not None
        )

    @property
    def shutdown_requested(self):
        return self._shutdown_requested

    @property
    def shutdown_thread(self):
        return self._shutdown_thread

    @property
    def background_error(self):
        return self._background_error

    def configure_shutdown_callback(
        self,
        shutdown_callback,
    ):
        if not callable(
            shutdown_callback
        ):
            raise ValueError(
                "The application shutdown callback must be "
                "callable."
            )

        with self._state_lock:
            self._shutdown_callback = (
                shutdown_callback
            )

    def request_shutdown(self):
        with self._state_lock:
            if self._shutdown_callback is None:
                raise (
                    ApplicationShutdownNotConfiguredError(
                        "Application shutdown has not been "
                        "configured."
                    )
                )

            if self._shutdown_requested:
                return False

            self._background_error = None
            self._shutdown_requested = True

            try:
                shutdown_thread = threading.Thread(
                    target=self._run_shutdown,
                    name=self.SHUTDOWN_THREAD_NAME,
                    daemon=True,
                )

                self._shutdown_thread = (
                    shutdown_thread
                )

                shutdown_thread.start()

            except Exception:
                self._shutdown_requested = False
                self._shutdown_thread = None
                raise

        return True

    def _run_shutdown(self):
        try:
            if self.delay_seconds > 0:
                time.sleep(
                    self.delay_seconds
                )

            shutdown_callback = (
                self._shutdown_callback
            )

            if shutdown_callback is None:
                raise (
                    ApplicationShutdownNotConfiguredError(
                        "Application shutdown has not been "
                        "configured."
                    )
                )

            shutdown_callback()

        except Exception as error:
            self._background_error = error

    @staticmethod
    def _normalize_delay_seconds(
        value,
    ):
        if isinstance(
            value,
            bool,
        ):
            raise ValueError(
                "The application shutdown delay must be a "
                "number greater than or equal to zero."
            )

        try:
            normalized_value = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                "The application shutdown delay must be a "
                "number greater than or equal to zero."
            ) from error

        if (
            not math.isfinite(
                normalized_value
            )
            or normalized_value < 0
        ):
            raise ValueError(
                "The application shutdown delay must be a "
                "number greater than or equal to zero."
            )

        return normalized_value