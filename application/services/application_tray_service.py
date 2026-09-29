import os
import sys
import threading


class _LazyPystrayModule:
    """Delay the optional pystray import until an attribute is used."""

    def __init__(self):
        object.__setattr__(self, "_overrides", {})

    def __getattr__(self, name):
        overrides = object.__getattribute__(
            self,
            "_overrides",
        )

        if name in overrides:
            return overrides[name]

        import pystray

        return getattr(pystray, name)

    def __setattr__(self, name, value):
        object.__getattribute__(
            self,
            "_overrides",
        )[name] = value

    def __delattr__(self, name):
        del object.__getattribute__(
            self,
            "_overrides",
        )[name]

    def has_overrides(self):
        return bool(
            object.__getattribute__(
                self,
                "_overrides",
            )
        )


_lazy_pystray = _LazyPystrayModule()


def __getattr__(name):
    if name == "pystray":
        return _lazy_pystray

    raise AttributeError(name)


class ApplicationTrayUnavailableError(RuntimeError):
    """
    Raised when optional Linux notification-area support is unavailable.
    """


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

    DIAGNOSTIC_ENVIRONMENT_VARIABLE = (
        "LEAGUE_MASTERY_TRACKER_TRAY_DIAGNOSTICS"
    )

    DIAGNOSTIC_PREFIX = "Linux tray diagnostic:"

    DIAGNOSTIC_MAXIMUM_LENGTH = 256

    DIAGNOSTIC_BACKEND_LABELS = {
        "pystray._appindicator": "appindicator",
        "pystray._darwin": "darwin",
        "pystray._dummy": "dummy",
        "pystray._gtk": "gtk",
        "pystray._win32": "win32",
        XORG_ICON_MODULE: "xorg",
    }

    DIAGNOSTIC_RUNNER_LABELS = frozenset(
        (
            "detached",
            "owned-xorg",
        )
    )

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

        _, image_module, image_draw_module = (
            self._load_tray_dependencies()
        )

        return self._create_icon_image(
            image_module,
            image_draw_module,
        )

    def _create_icon_image(
        self,
        image_module,
        image_draw_module,
    ):
        image = image_module.new(
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

        drawing = image_draw_module.Draw(
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

        if (
            self._is_linux()
            and not self._is_linux_tray_eligible()
        ):
            self._raise_linux_tray_unavailable()

        self._background_error = None
        pystray_module, image_module, image_draw_module = (
            self._load_tray_dependencies()
        )

        try:
            image = self._create_icon_image(
                image_module,
                image_draw_module,
            )
        except OSError as error:
            if self._is_linux():
                self._raise_linux_tray_unavailable(error)
            raise

        open_menu_item = pystray_module.MenuItem(
            self.open_menu_text,
            self._handle_open_application,
            default=True,
        )

        shutdown_menu_item = pystray_module.MenuItem(
            self.shutdown_menu_text,
            self._handle_shutdown,
        )

        menu = pystray_module.Menu(
            open_menu_item,
            pystray_module.Menu.SEPARATOR,
            shutdown_menu_item,
        )

        try:
            icon = pystray_module.Icon(
                name=self.icon_name,
                icon=image,
                title=self.icon_title,
                menu=menu,
            )

            self._icon = icon

            uses_owned_xorg_runner = (
                self._uses_owned_xorg_runner(icon)
            )
            self._emit_selection_diagnostic(
                icon,
                uses_owned_xorg_runner,
            )

            if uses_owned_xorg_runner:
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

        except self._xorg_backend_error_types(
            pystray_module
        ) as error:
            if self._is_linux():
                self._raise_linux_tray_unavailable(error)
            raise

        return icon

    @staticmethod
    def _is_linux():
        return sys.platform.startswith("linux")

    @staticmethod
    def _is_linux_tray_eligible():
        backend = os.environ.get(
            "PYSTRAY_BACKEND",
            "",
        ).strip()

        if backend == "dummy":
            return True

        return bool(
            os.environ.get(
                "DISPLAY",
                "",
            ).strip()
        )

    def _load_tray_dependencies(self):
        """
        Import optional tray dependencies only when a tray is requested.
        """

        try:
            from PIL import Image, ImageDraw
        except ImportError as error:
            if self._is_linux():
                self._raise_linux_tray_unavailable(error)
            raise

        if _lazy_pystray.has_overrides():
            return _lazy_pystray, Image, ImageDraw

        if self._is_linux() and not self._uses_dummy_backend():
            try:
                from Xlib.error import (
                    DisplayConnectionError,
                    DisplayNameError,
                )
            except ImportError as error:
                self._raise_linux_tray_unavailable(error)

            try:
                import pystray
            except (
                ImportError,
                DisplayConnectionError,
                DisplayNameError,
            ) as error:
                self._raise_linux_tray_unavailable(error)
        else:
            try:
                import pystray
            except ImportError as error:
                if self._is_linux():
                    self._raise_linux_tray_unavailable(error)
                raise

        return pystray, Image, ImageDraw

    @staticmethod
    def _uses_dummy_backend():
        return (
            os.environ.get(
                "PYSTRAY_BACKEND",
                "",
            ).strip()
            == "dummy"
        )

    def _xorg_backend_error_types(self, pystray_module):
        if (
            self._uses_dummy_backend()
            or not self._uses_owned_xorg_runner(
                pystray_module.Icon
            )
        ):
            return ()

        from Xlib.error import (
            DisplayConnectionError,
            DisplayNameError,
        )

        return (
            DisplayConnectionError,
            DisplayNameError,
        )

    def _raise_linux_tray_unavailable(self, error=None):
        self._emit_unavailable_diagnostic()
        self._reset_unavailable_tray()

        unavailable_error = ApplicationTrayUnavailableError(
            "Notification-area support is unavailable."
        )

        if error is None:
            raise unavailable_error

        raise unavailable_error from error

    @classmethod
    def _emit_selection_diagnostic(
        cls,
        icon,
        uses_owned_xorg_runner,
    ):
        if not cls._diagnostics_enabled():
            return

        try:
            icon_class = type(icon)
            backend_label = cls.DIAGNOSTIC_BACKEND_LABELS.get(
                icon_class.__module__,
                "unknown",
            )
            runner_label = (
                "owned-xorg"
                if uses_owned_xorg_runner is True
                else (
                    "detached"
                    if uses_owned_xorg_runner is False
                    else "unknown"
                )
            )
            safe_runner_label = (
                runner_label
                if runner_label in cls.DIAGNOSTIC_RUNNER_LABELS
                else "unknown"
            )
            has_menu_label = cls._capability_label(
                icon_class,
                "HAS_MENU",
            )
            has_default_action_label = (
                cls._capability_label(
                    icon_class,
                    "HAS_DEFAULT_ACTION",
                )
            )

            cls._emit_diagnostic(
                " ".join(
                    (
                        "phase=runner-selection",
                        "status=selected",
                        f"backend={backend_label}",
                        f"has-menu={has_menu_label}",
                        "has-default-action="
                        f"{has_default_action_label}",
                        f"runner={safe_runner_label}",
                    )
                )
            )
        except Exception:
            pass

    @classmethod
    def _emit_unavailable_diagnostic(cls):
        cls._emit_diagnostic(
            "phase=initialization status=unavailable"
        )

    @classmethod
    def _emit_diagnostic(cls, record):
        try:
            if not cls._diagnostics_enabled():
                return

            line = f"{cls.DIAGNOSTIC_PREFIX} {record}"
            sys.stderr.write(
                line[: cls.DIAGNOSTIC_MAXIMUM_LENGTH - 1]
                + "\n"
            )
        except Exception:
            pass

    @classmethod
    def _diagnostics_enabled(cls):
        try:
            return (
                cls._is_linux()
                and os.environ.get(
                    cls.DIAGNOSTIC_ENVIRONMENT_VARIABLE
                ) == "1"
            )
        except Exception:
            return False

    @staticmethod
    def _capability_label(icon_class, attribute_name):
        try:
            value = getattr(
                icon_class,
                attribute_name,
            )
        except Exception:
            return "unknown"

        if value is True:
            return "1"

        if value is False:
            return "0"

        return "unknown"

    def _reset_unavailable_tray(self):
        self._icon = None
        self._icon_runner_thread = None
        self._is_running = False

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
