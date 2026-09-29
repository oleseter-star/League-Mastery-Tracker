from collections.abc import MutableMapping
import sys

from application.app import create_app
from application.services.application_browser_service import (
    ApplicationBrowserService,
)
from application.services.application_instance_service import (
    ApplicationInstanceService,
)
from application.services.application_server_service import (
    ApplicationServerService,
)
from application.services.application_shutdown_service import (
    ApplicationShutdownService,
)
from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)
from application.services.application_tray_service import (
    ApplicationTrayService,
    ApplicationTrayUnavailableError,
)


class ApplicationLauncherService:
    """
    Coordinates single-instance locking, Flask initialization,
    Waitress startup, browser opening, notification-area control,
    browser-tab lifecycle monitoring, controlled shutdown, and
    resource cleanup.
    """

    DEFAULT_CONFIG_NAME = "production"

    def __init__(
        self,
        instance_service=None,
        server_service=None,
        browser_service=None,
        shutdown_service=None,
        tray_service=None,
        tab_lifecycle_service=None,
        app_factory=None,
        config_name=DEFAULT_CONFIG_NAME,
    ):
        normalized_config_name = str(
            config_name or ""
        ).strip()

        if not normalized_config_name:
            raise ValueError(
                "The application configuration name cannot be "
                "empty."
            )

        self.config_name = normalized_config_name

        if instance_service is None:
            instance_service = (
                ApplicationInstanceService()
            )

        if server_service is None:
            server_service = (
                ApplicationServerService()
            )

        if browser_service is None:
            browser_service = (
                ApplicationBrowserService(
                    application_url=(
                        server_service.application_url
                    ),
                )
            )

        if shutdown_service is None:
            shutdown_service = (
                ApplicationShutdownService()
            )

        if tray_service is None:
            tray_service = (
                ApplicationTrayService(
                    application_url=(
                        server_service.application_url
                    ),
                    open_application_callback=(
                        browser_service.open_browser
                    ),
                    shutdown_callback=(
                        shutdown_service.request_shutdown
                    ),
                )
            )

        if tab_lifecycle_service is None:
            tab_lifecycle_service = (
                ApplicationTabLifecycleService(
                    shutdown_callback=(
                        shutdown_service.request_shutdown
                    ),
                )
            )

        if app_factory is None:
            app_factory = create_app

        self.instance_service = (
            instance_service
        )

        self.server_service = (
            server_service
        )

        self.browser_service = (
            browser_service
        )

        self.shutdown_service = (
            shutdown_service
        )

        self.tray_service = (
            tray_service
        )

        self.tab_lifecycle_service = (
            tab_lifecycle_service
        )

        self.app_factory = (
            app_factory
        )

    def run(self):
        """
        Start the application or open the already-running instance.

        Returns a result dictionary describing why execution ended.
        """

        is_first_instance = (
            self.instance_service.acquire()
        )

        if not is_first_instance:
            self.browser_service.wait_until_ready_and_open()

            return {
                "started": False,
                "reason": "already_running",
            }

        shutdown_reason = "server_stopped"

        try:
            self.server_service.ensure_port_available()

            flask_app = self.app_factory(
                self.config_name
            )

            self.server_service.create_server(
                flask_app
            )

            self._configure_application_services(
                flask_app
            )

            try:
                self.tray_service.start()
            except ApplicationTrayUnavailableError:
                if not sys.platform.startswith("linux"):
                    raise

            self.tab_lifecycle_service.start()

            self.browser_service.start_background_open()

            try:
                self.server_service.run()

            except KeyboardInterrupt:
                if (
                    self.server_service
                    .shutdown_requested
                    is True
                ):
                    shutdown_reason = (
                        "application_requested_shutdown"
                    )

                else:
                    shutdown_reason = (
                        "user_requested_shutdown"
                    )

        finally:
            self.tab_lifecycle_service.stop()
            self.tray_service.stop()
            self.server_service.close()
            self.instance_service.release()

        return {
            "started": True,
            "reason": shutdown_reason,
        }

    def _configure_application_services(
        self,
        flask_app,
    ):
        """
        Connect application lifecycle services to the running server
        and expose them through Flask's extension registry.
        """

        self.shutdown_service.configure_shutdown_callback(
            self.server_service.request_shutdown
        )

        extensions = getattr(
            flask_app,
            "extensions",
            None,
        )

        if not isinstance(
            extensions,
            MutableMapping,
        ):
            extensions = {}

            flask_app.extensions = (
                extensions
            )

        extensions[
            ApplicationShutdownService
            .FLASK_EXTENSION_KEY
        ] = self.shutdown_service

        extensions[
            ApplicationTabLifecycleService
            .FLASK_EXTENSION_KEY
        ] = self.tab_lifecycle_service