import math
import threading
import time
import urllib.request
import webbrowser
from urllib.error import URLError


class ApplicationReadinessTimeoutError(
    TimeoutError
):
    """
    Raised when the local application server does not become ready
    within the configured startup period.
    """


class ApplicationBrowserOpenError(
    RuntimeError
):
    """
    Raised when the operating system cannot open the application URL
    in the default browser.
    """


class ApplicationBrowserService:
    """
    Waits until the local application server responds and then opens
    the application in the user's default browser.
    """

    DEFAULT_STARTUP_TIMEOUT_SECONDS = 15.0
    DEFAULT_POLL_INTERVAL_SECONDS = 0.1
    DEFAULT_REQUEST_TIMEOUT_SECONDS = 1.0

    BACKGROUND_THREAD_NAME = (
        "LeagueMasteryTrackerBrowserOpen"
    )

    def __init__(
        self,
        application_url,
        startup_timeout_seconds=(
            DEFAULT_STARTUP_TIMEOUT_SECONDS
        ),
        poll_interval_seconds=(
            DEFAULT_POLL_INTERVAL_SECONDS
        ),
        request_timeout_seconds=(
            DEFAULT_REQUEST_TIMEOUT_SECONDS
        ),
    ):
        normalized_application_url = str(
            application_url or ""
        ).strip()

        if not normalized_application_url:
            raise ValueError(
                "The application URL cannot be empty."
            )

        self.application_url = (
            normalized_application_url
        )

        self.startup_timeout_seconds = (
            self._normalize_positive_number(
                startup_timeout_seconds,
                field_name=(
                    "startup timeout"
                ),
            )
        )

        self.poll_interval_seconds = (
            self._normalize_positive_number(
                poll_interval_seconds,
                field_name=(
                    "poll interval"
                ),
            )
        )

        self.request_timeout_seconds = (
            self._normalize_positive_number(
                request_timeout_seconds,
                field_name=(
                    "request timeout"
                ),
            )
        )

        self._background_thread = None
        self._background_error = None

    @property
    def background_thread(self):
        """
        Return the current browser-opening background thread.
        """

        return self._background_thread

    @property
    def background_error(self):
        """
        Return an error raised by the background browser operation.
        """

        return self._background_error

    def wait_until_ready(self):
        """
        Poll the local application URL until the server responds.

        HTTP responses below status 500 are treated as proof that the
        local WSGI server and Flask application are available.
        """

        deadline = (
            time.monotonic()
            + self.startup_timeout_seconds
        )

        while True:
            try:
                with urllib.request.urlopen(
                    self.application_url,
                    timeout=(
                        self.request_timeout_seconds
                    ),
                ) as response:
                    response_status = getattr(
                        response,
                        "status",
                        200,
                    )

                    if (
                        100
                        <= response_status
                        < 500
                    ):
                        return True

            except (
                URLError,
                OSError,
                TimeoutError,
                ValueError,
            ):
                pass

            if time.monotonic() >= deadline:
                raise (
                    ApplicationReadinessTimeoutError(
                        "League Mastery Tracker did not "
                        "become available within "
                        f"{self.startup_timeout_seconds:g} "
                        "seconds."
                    )
                )

            time.sleep(
                self.poll_interval_seconds
            )

    def open_browser(self):
        """
        Open the application URL in the user's default browser.
        """

        opened = webbrowser.open(
            self.application_url,
            new=2,
            autoraise=True,
        )

        if not opened:
            raise ApplicationBrowserOpenError(
                "The default browser could not open "
                "League Mastery Tracker."
            )

        return True

    def wait_until_ready_and_open(self):
        """
        Wait for the server and then open the browser.
        """

        self.wait_until_ready()

        return self.open_browser()

    def start_background_open(self):
        """
        Start readiness polling and browser opening in a daemon thread.

        The Waitress server can then run on the launcher's main thread.
        """

        if (
            self._background_thread is not None
            and self._background_thread.is_alive()
        ):
            return self._background_thread

        self._background_error = None

        self._background_thread = threading.Thread(
            target=self._run_background_open,
            name=self.BACKGROUND_THREAD_NAME,
            daemon=True,
        )

        self._background_thread.start()

        return self._background_thread

    def _run_background_open(self):
        """
        Run the browser operation without leaking thread exceptions.
        """

        try:
            self.wait_until_ready_and_open()

        except (
            ApplicationReadinessTimeoutError,
            ApplicationBrowserOpenError,
            OSError,
            RuntimeError,
        ) as error:
            self._background_error = error

    @staticmethod
    def _normalize_positive_number(
        value,
        field_name,
    ):
        """
        Normalize a finite number greater than zero.
        """

        if isinstance(
            value,
            bool,
        ):
            raise ValueError(
                f"The {field_name} must be a "
                "positive number."
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
                f"The {field_name} must be a "
                "positive number."
            ) from error

        if (
            not math.isfinite(
                normalized_value
            )
            or normalized_value <= 0
        ):
            raise ValueError(
                f"The {field_name} must be a "
                "positive number."
            )

        return normalized_value