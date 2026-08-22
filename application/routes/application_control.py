from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
)

from application.services.application_shutdown_service import (
    ApplicationShutdownNotConfiguredError,
    ApplicationShutdownService,
)
from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)


application_control_bp = Blueprint(
    "application_control",
    __name__,
    template_folder="../templates",
)


@application_control_bp.post(
    "/application/shutdown"
)
def shutdown_application():
    """
    Request a controlled shutdown of the local application.
    """

    shutdown_service = (
        current_app.extensions.get(
            ApplicationShutdownService
            .FLASK_EXTENSION_KEY
        )
    )

    if shutdown_service is None:
        return (
            render_template(
                "application_shutdown.html",
                page_title=(
                    "Shutdown is unavailable"
                ),
                heading=(
                    "Shutdown is unavailable"
                ),
                message=(
                    "The application cannot be shut down from "
                    "the browser in this startup mode."
                ),
            ),
            503,
        )

    try:
        shutdown_started = (
            shutdown_service
            .request_shutdown()
        )

    except (
        ApplicationShutdownNotConfiguredError
    ):
        return (
            render_template(
                "application_shutdown.html",
                page_title=(
                    "Shutdown is unavailable"
                ),
                heading=(
                    "Shutdown is unavailable"
                ),
                message=(
                    "The application cannot be shut down from "
                    "the browser in this startup mode."
                ),
            ),
            503,
        )

    if shutdown_started:
        return (
            render_template(
                "application_shutdown.html",
                page_title=(
                    "Application is shutting down"
                ),
                heading=(
                    "Application is shutting down"
                ),
                message=(
                    "You can close this browser window."
                ),
            ),
            202,
        )

    return (
        render_template(
            "application_shutdown.html",
            page_title=(
                "Shutdown has already started"
            ),
            heading=(
                "Shutdown has already started"
            ),
            message=(
                "You can close this browser window."
            ),
        ),
        200,
    )


@application_control_bp.post(
    "/application/tabs/heartbeat"
)
def register_tab_heartbeat():
    """
    Register or refresh the heartbeat for one browser tab.
    """

    lifecycle_service = (
        current_app.extensions.get(
            ApplicationTabLifecycleService
            .FLASK_EXTENSION_KEY
        )
    )

    if lifecycle_service is None:
        return (
            "",
            503,
        )

    tab_identifier = str(
        request.form.get(
            "tab_id",
            "",
        )
        or ""
    ).strip()

    if not tab_identifier:
        return (
            "",
            400,
        )

    try:
        lifecycle_service.touch_tab(
            tab_identifier
        )

    except ValueError:
        return (
            "",
            400,
        )

    return (
        "",
        204,
    )


@application_control_bp.post(
    "/application/tabs/close"
)
def close_browser_tab():
    """
    Remove one browser tab from lifecycle tracking.
    """

    lifecycle_service = (
        current_app.extensions.get(
            ApplicationTabLifecycleService
            .FLASK_EXTENSION_KEY
        )
    )

    if lifecycle_service is None:
        return (
            "",
            503,
        )

    tab_identifier = str(
        request.form.get(
            "tab_id",
            "",
        )
        or ""
    ).strip()

    if not tab_identifier:
        return (
            "",
            400,
        )

    try:
        lifecycle_service.close_tab(
            tab_identifier
        )

    except ValueError:
        return (
            "",
            400,
        )

    return (
        "",
        204,
    )