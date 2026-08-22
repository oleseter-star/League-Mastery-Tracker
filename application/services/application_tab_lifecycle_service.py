import math
import threading
import time


class ApplicationTabLifecycleService:
    """
    Tracks active browser tabs and requests application shutdown
    after the final tab has disappeared.

    Explicit close signals normally start shutdown after the short
    grace period. Heartbeat expiry is only a long fallback for
    browser crashes or close signals that were never delivered.
    """

    FLASK_EXTENSION_KEY = (
        "league_mastery_tracker_tab_lifecycle_service"
    )

    DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 300.0
    DEFAULT_EMPTY_GRACE_SECONDS = 5.0
    DEFAULT_MONITOR_INTERVAL_SECONDS = 1.0

    MONITOR_THREAD_NAME = (
        "LeagueMasteryTrackerTabMonitor"
    )

    def __init__(
        self,
        shutdown_callback,
        heartbeat_timeout_seconds=(
            DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
        ),
        empty_grace_seconds=(
            DEFAULT_EMPTY_GRACE_SECONDS
        ),
        monitor_interval_seconds=(
            DEFAULT_MONITOR_INTERVAL_SECONDS
        ),
        clock=None,
    ):
        if not callable(
            shutdown_callback
        ):
            raise ValueError(
                "The tab lifecycle shutdown callback must be "
                "callable."
            )

        self.heartbeat_timeout_seconds = (
            self._normalize_positive_number(
                heartbeat_timeout_seconds,
                field_name=(
                    "heartbeat timeout"
                ),
            )
        )

        self.empty_grace_seconds = (
            self._normalize_positive_number(
                empty_grace_seconds,
                field_name=(
                    "empty-tab grace period"
                ),
            )
        )

        self.monitor_interval_seconds = (
            self._normalize_positive_number(
                monitor_interval_seconds,
                field_name=(
                    "monitor interval"
                ),
            )
        )

        if clock is None:
            clock = time.monotonic

        if not callable(
            clock
        ):
            raise ValueError(
                "The tab lifecycle clock must be callable."
            )

        self.shutdown_callback = (
            shutdown_callback
        )

        self.clock = clock

        self._active_tabs = {}
        self._has_registered_tab = False
        self._empty_since = None
        self._shutdown_requested = False

        self._monitor_thread = None
        self._is_running = False
        self._background_error = None

        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def active_tab_count(self):
        """
        Return the number of currently registered active tabs.
        """

        with self._state_lock:
            return len(
                self._active_tabs
            )

    @property
    def has_registered_tab(self):
        """
        Return whether at least one tab has ever registered.
        """

        with self._state_lock:
            return self._has_registered_tab

    @property
    def shutdown_requested(self):
        """
        Return whether automatic shutdown has been requested.
        """

        with self._state_lock:
            return self._shutdown_requested

    @property
    def monitor_thread(self):
        """
        Return the background monitor thread.
        """

        return self._monitor_thread

    @property
    def is_running(self):
        """
        Return whether the background monitor is running.
        """

        return self._is_running

    @property
    def background_error(self):
        """
        Return an error raised by the monitor or shutdown callback.
        """

        return self._background_error

    def get_active_tab_ids(self):
        """
        Return active tab identifiers in deterministic order.
        """

        with self._state_lock:
            return tuple(
                sorted(
                    self._active_tabs
                )
            )

    def touch_tab(
        self,
        tab_identifier,
    ):
        """
        Register or refresh a browser-tab heartbeat.

        Returns True when a new tab was registered and False when an
        existing tab was refreshed.
        """

        normalized_tab_identifier = (
            self._normalize_tab_identifier(
                tab_identifier
            )
        )

        current_time = self.clock()

        with self._state_lock:
            is_new_tab = (
                normalized_tab_identifier
                not in self._active_tabs
            )

            self._active_tabs[
                normalized_tab_identifier
            ] = current_time

            self._has_registered_tab = True
            self._empty_since = None

        return is_new_tab

    def close_tab(
        self,
        tab_identifier,
    ):
        """
        Remove a browser tab explicitly.

        Returns True when the tab existed and False when it was
        already absent.
        """

        normalized_tab_identifier = (
            self._normalize_tab_identifier(
                tab_identifier
            )
        )

        current_time = self.clock()

        with self._state_lock:
            removed_timestamp = (
                self._active_tabs.pop(
                    normalized_tab_identifier,
                    None,
                )
            )

            if removed_timestamp is None:
                return False

            if not self._active_tabs:
                self._empty_since = (
                    current_time
                )

        return True

    def evaluate_once(self):
        """
        Remove expired tabs and request shutdown when the empty grace
        period has elapsed.

        Returns True only when this evaluation initiated shutdown.
        """

        current_time = self.clock()

        should_request_shutdown = False

        with self._state_lock:
            if self._shutdown_requested:
                return False

            stale_tab_identifiers = [
                tab_identifier
                for (
                    tab_identifier,
                    last_heartbeat,
                ) in self._active_tabs.items()
                if (
                    current_time
                    - last_heartbeat
                    >= self.heartbeat_timeout_seconds
                )
            ]

            for tab_identifier in (
                stale_tab_identifiers
            ):
                self._active_tabs.pop(
                    tab_identifier,
                    None,
                )

            if self._active_tabs:
                self._empty_since = None
                return False

            if not self._has_registered_tab:
                self._empty_since = None
                return False

            if self._empty_since is None:
                self._empty_since = (
                    current_time
                )

                return False

            empty_duration = (
                current_time
                - self._empty_since
            )

            if (
                empty_duration
                < self.empty_grace_seconds
            ):
                return False

            self._shutdown_requested = True
            should_request_shutdown = True

        if not should_request_shutdown:
            return False

        try:
            self.shutdown_callback()

        except Exception as error:
            self._background_error = error
            return False

        return True

    def start(self):
        """
        Start the background tab monitor.

        Repeated calls return the existing monitor thread.
        """

        if self._monitor_thread is not None:
            return self._monitor_thread

        self._background_error = None
        self._stop_event.clear()

        monitor_thread = threading.Thread(
            target=self._run_monitor,
            name=self.MONITOR_THREAD_NAME,
            daemon=True,
        )

        self._monitor_thread = (
            monitor_thread
        )

        self._is_running = True

        try:
            monitor_thread.start()

        except Exception:
            self._monitor_thread = None
            self._is_running = False
            raise

        return monitor_thread

    def stop(self):
        """
        Stop the background monitor.

        Repeated calls are safe.
        """

        monitor_thread = (
            self._monitor_thread
        )

        if monitor_thread is None:
            self._is_running = False
            return False

        self._monitor_thread = None
        self._is_running = False

        self._stop_event.set()

        if (
            monitor_thread is not threading.current_thread()
            and monitor_thread.is_alive()
        ):
            monitor_thread.join(
                timeout=(
                    self.monitor_interval_seconds
                    + 1.0
                )
            )

        return True

    def _run_monitor(self):
        """
        Evaluate tab activity until stopped or shutdown is requested.
        """

        try:
            while not self._stop_event.wait(
                self.monitor_interval_seconds
            ):
                shutdown_started = (
                    self.evaluate_once()
                )

                if shutdown_started:
                    break

        except Exception as error:
            self._background_error = error

        finally:
            self._is_running = False

    @staticmethod
    def _normalize_tab_identifier(
        tab_identifier,
    ):
        """
        Normalize a required browser-tab identifier.
        """

        normalized_tab_identifier = str(
            tab_identifier or ""
        ).strip()

        if not normalized_tab_identifier:
            raise ValueError(
                "The browser tab identifier cannot be empty."
            )

        return normalized_tab_identifier

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
                f"The {field_name} must be a positive number."
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
                f"The {field_name} must be a positive number."
            ) from error

        if (
            not math.isfinite(
                normalized_value
            )
            or normalized_value <= 0
        ):
            raise ValueError(
                f"The {field_name} must be a positive number."
            )

        return normalized_value