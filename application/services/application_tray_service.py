import threading

from PIL import (
    Image,
    ImageDraw,
)

import pystray


class ApplicationTrayService:
    """
    Controls the Windows notification-area icon.

    The tray icon provides reliable access to opening and shutting
    down League Mastery Tracker when no browser tab is visible.
    """

    DEFAULT_ICON_NAME = (
        "LeagueMasteryTracker"
    )

    DEFAULT_ICON_TITLE = (
        "League Mastery Tracker"
    )

    DEFAULT_OPEN_MENU_TEXT = (
        "Open League Mastery Tracker"
    )

    DEFAULT_SHUTDOWN_MENU_TEXT = (
        "Shut down League Mastery Tracker"
    )

    ICON_SIZE = 64

    XORG_ICON_MODULE = "pystray._xorg"

    ICON_RUNNER_THREAD_NAME = (
        "LeagueMasteryTrackerTrayIcon"
    )

    ICON_RUNNER_JOIN_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        application_url,
        open_application_callback,
        shutdown_callback,
        icon_name=DEFAULT_ICON_NAME,
        icon_title=DEFAULT_ICON_TITLE,
        open_menu_text=DEFAULT_OPEN_MENU_TEXT,
        shutdown_menu_text=DEFAULT_SHUTDOWN_MENU_TEXT,
    ):
        normalized_application_url = str(
            application_url or ""
        ).strip()

        if not normalized_application_url:
            raise ValueError(
                "The application URL cannot be empty."
            )

        if not callable(
            open_application_callback
        ):
            raise ValueError(
                "The open-application callback must be callable."
            )

        if not callable(
            shutdown_callback
        ):
            raise ValueError(
                "The shutdown callback must be callable."
            )

        self.application_url = (
            normalized_application_url
        )

        self.open_application_callback = (
            open_application_callback
        )

        self.shutdown_callback = (
            shutdown_callback
        )

        self.icon_name = self._normalize_text(
            icon_name,
            field_name="icon name",
        )

        self.icon_title = self._normalize_text(
            icon_title,
            field_name="icon title",
        )

        self.open_menu_text = self._normalize_text(
            open_menu_text,
            field_name="open menu text",
        )

        self.shutdown_menu_text = (
            self._normalize_text(
                shutdown_menu_text,
                field_name=(
                    "shutdown menu text"
                ),
            )
        )

        self._icon = None
        self._icon_runner_thread = None
        self._is_running = False
        self._background_error = None

    @property
    def icon(self):
        """
        Return the active pystray icon.
        """

        return self._icon

    @property
    def is_running(self):
        """
        Return whether the tray icon has been started.
        """

        return self._is_running

    @property
    def icon_runner_thread(self):
        """Return the explicitly owned Xorg icon runner, if any."""

        return self._icon_runner_thread

    @property
    def background_error(self):
        """
        Return the latest callback error from the tray thread.
        """

        return self._background_error

    def create_icon_image(self):
        """
        Generate the notification-area icon without external files.

        The icon uses simple geometric shapes so it remains available
        in both source and packaged application builds.
        """

        image = Image.new(
            "RGBA",
            (
                self.ICON_SIZE,
                self.ICON_SIZE,
            ),
            (
                0,
                0,
                0,
                0,
            ),
        )

        drawing = ImageDraw.Draw(
            image
        )

        drawing.rounded_rectangle(
            (
                2,
                2,
                self.ICON_SIZE - 3,
                self.ICON_SIZE - 3,
            ),
            radius=12,
            fill=(
                18,
                31,
                48,
                255,
            ),
            outline=(
                196,
                160,
                70,
                255,
            ),
            width=4,
        )

        drawing.polygon(
            (
                (
                    14,
                    46,
                ),
                (
                    20,
                    18,
                ),
                (
                    31,
                    38,
                ),
                (
                    42,
                    18,
                ),
                (
                    50,
                    46,
                ),
                (
                    42,
                    46,
                ),
                (
                    38,
                    31,
                ),
                (
                    31,
                    45,
                ),
                (
                    24,
                    31,
                ),
                (
                    21,
                    46,
                ),
            ),
            fill=(
                221,
                190,
                102,
                255,
            ),
        )

        return image

    def start(self):
        """
        Create and start the notification-area icon.

        Repeated calls return the already-running icon.
        """

        if self._icon is not None:
            return self._icon

        self._background_error = None

        open_menu_item = pystray.MenuItem(
            self.open_menu_text,
            self._handle_open_application,
            default=True,
        )

        shutdown_menu_item = (
            pystray.MenuItem(
                self.shutdown_menu_text,
                self._handle_shutdown,
            )
        )

        menu = pystray.Menu(
            open_menu_item,
            pystray.Menu.SEPARATOR,
            shutdown_menu_item,
        )

        icon = pystray.Icon(
            name=self.icon_name,
            icon=self.create_icon_image(),
            title=self.icon_title,
            menu=menu,
        )

        self._icon = icon

        try:
            if self._uses_owned_xorg_runner(icon):
                icon_runner_thread = threading.Thread(
                    target=self._run_xorg_icon,
                    args=(icon,),
                    name=self.ICON_RUNNER_THREAD_NAME,
                    daemon=False,
                )

                self._icon_runner_thread = (
                    icon_runner_thread
                )
                self._is_running = True

                icon_runner_thread.start()

            else:
                icon.run_detached()
                self._is_running = True

        except Exception:
            self._icon = None
            self._icon_runner_thread = None
            self._is_running = False
            raise

        return icon

    def stop(self):
        """
        Stop and remove the notification-area icon.

        Repeated calls are safe.
        """

        if (
            self._icon is None
            and self._icon_runner_thread is None
        ):
            self._is_running = False
            return False

        icon = self._icon
        icon_runner_thread = (
            self._icon_runner_thread
        )

        if icon is not None:
            icon.stop()

        if icon_runner_thread is None:
            self._icon = None
            self._is_running = False
            return True

        if (
            icon_runner_thread
            is threading.current_thread()
        ):
            return True

        icon_runner_thread.join(
            timeout=(
                self.ICON_RUNNER_JOIN_TIMEOUT_SECONDS
            )
        )

        if icon_runner_thread.is_alive():
            self._background_error = RuntimeError(
                "The Xorg tray icon runner did not stop within "
                f"{self.ICON_RUNNER_JOIN_TIMEOUT_SECONDS:g} "
                "seconds."
            )
            self._is_running = True
            return False

        self._icon = None
        self._icon_runner_thread = None
        self._is_running = False

        return True

    def _run_xorg_icon(self, icon):
        """Run the Xorg icon once in the owned runner thread."""

        try:
            icon.run()

        except Exception as error:
            self._background_error = error

        finally:
            self._is_running = False

    @classmethod
    def _uses_owned_xorg_runner(cls, icon):
        """Return whether the selected icon uses pystray's Xorg backend."""

        return (
            type(icon).__module__
            == cls.XORG_ICON_MODULE
        )

    def _handle_open_application(
        self,
        icon,
        menu_item,
    ):
        """
        Open the application from the tray menu.
        """

        del icon
        del menu_item

        self._background_error = None

        try:
            result = (
                self.open_application_callback()
            )

        except Exception as error:
            self._background_error = error
            return False

        return result is not False

    def _handle_shutdown(
        self,
        icon,
        menu_item,
    ):
        """
        Remove the tray icon and request controlled shutdown.
        """

        del icon
        del menu_item

        self._background_error = None

        try:
            self.stop()

            result = self.shutdown_callback()

        except Exception as error:
            self._background_error = error
            return False

        return result is not False

    @staticmethod
    def _normalize_text(
        value,
        field_name,
    ):
        """
        Normalize required tray display text.
        """

        normalized_value = str(
            value or ""
        ).strip()

        if not normalized_value:
            raise ValueError(
                f"The {field_name} cannot be empty."
            )

        return normalized_value
