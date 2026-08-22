from html import escape

from application.services.application_tab_lifecycle_service import (
    ApplicationTabLifecycleService,
)


class ApplicationTabLifecycleClientService:
    """
    Injects the browser-tab lifecycle JavaScript client into HTML
    responses while tab lifecycle monitoring is active.

    Central response injection ensures all current and future HTML
    pages participate without requiring duplicate script tags in
    every template.
    """

    FLASK_EXTENSION_KEY = (
        "league_mastery_tracker_tab_lifecycle_client_service"
    )

    DEFAULT_SCRIPT_PATH = (
        "/static/application_tab_lifecycle.js"
    )

    DEFAULT_BOOTSTRAP_ELEMENT_ID = (
        "league-mastery-tracker-tab-lifecycle"
    )

    HEARTBEAT_URL = (
        "/application/tabs/heartbeat"
    )

    CLOSE_URL = (
        "/application/tabs/close"
    )

    def __init__(
        self,
        script_path=DEFAULT_SCRIPT_PATH,
        bootstrap_element_id=(
            DEFAULT_BOOTSTRAP_ELEMENT_ID
        ),
    ):
        self.script_path = (
            self._normalize_required_text(
                script_path,
                field_name="script path",
            )
        )

        self.bootstrap_element_id = (
            self._normalize_required_text(
                bootstrap_element_id,
                field_name=(
                    "bootstrap element identifier"
                ),
            )
        )

    def init_app(
        self,
        app,
    ):
        """
        Register lifecycle-client response injection on a Flask app.

        Repeated initialization is safe.
        """

        if app.extensions.get(
            self.FLASK_EXTENSION_KEY
        ):
            return

        app.extensions[
            self.FLASK_EXTENSION_KEY
        ] = True

        @app.after_request
        def inject_tab_lifecycle_client(
            response,
        ):
            return self._process_response(
                app=app,
                response=response,
            )

    def build_bootstrap_html(
        self,
        csrf_token,
    ):
        """
        Build the script element and lifecycle endpoint metadata.
        """

        normalized_csrf_token = (
            self._normalize_required_text(
                csrf_token,
                field_name="CSRF token",
            )
        )

        escaped_element_id = escape(
            self.bootstrap_element_id,
            quote=True,
        )

        escaped_csrf_token = escape(
            normalized_csrf_token,
            quote=True,
        )

        escaped_heartbeat_url = escape(
            self.HEARTBEAT_URL,
            quote=True,
        )

        escaped_close_url = escape(
            self.CLOSE_URL,
            quote=True,
        )

        escaped_script_path = escape(
            self.script_path,
            quote=True,
        )

        return (
            f'<script id="{escaped_element_id}" '
            f'data-csrf-token="{escaped_csrf_token}" '
            f'data-heartbeat-url="{escaped_heartbeat_url}" '
            f'data-close-url="{escaped_close_url}" '
            f'src="{escaped_script_path}" defer></script>'
        )

    def inject_into_html(
        self,
        html,
        csrf_token,
    ):
        """
        Inject the lifecycle bootstrap before the closing body tag.

        Existing injection is preserved without duplication.
        """

        normalized_html = str(
            html
        )

        bootstrap_marker = (
            f'id="{self.bootstrap_element_id}"'
        )

        if bootstrap_marker in normalized_html:
            return normalized_html

        bootstrap_html = (
            self.build_bootstrap_html(
                csrf_token=csrf_token,
            )
        )

        body_end_position = (
            normalized_html
            .lower()
            .rfind(
                "</body>"
            )
        )

        if body_end_position < 0:
            return (
                normalized_html
                + bootstrap_html
            )

        return (
            normalized_html[
                :body_end_position
            ]
            + bootstrap_html
            + normalized_html[
                body_end_position:
            ]
        )

    def _process_response(
        self,
        app,
        response,
    ):
        """
        Inject the client into eligible HTML responses.
        """

        if response.mimetype != "text/html":
            return response

        if (
            ApplicationTabLifecycleService
            .FLASK_EXTENSION_KEY
            not in app.extensions
        ):
            return response

        csrf_token_function = (
            app.jinja_env.globals.get(
                "csrf_token"
            )
        )

        if not callable(
            csrf_token_function
        ):
            return response

        try:
            csrf_token = (
                csrf_token_function()
            )

            injected_html = (
                self.inject_into_html(
                    html=response.get_data(
                        as_text=True
                    ),
                    csrf_token=csrf_token,
                )
            )

        except (
            LookupError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return response

        response.set_data(
            injected_html
        )

        return response

    @staticmethod
    def _normalize_required_text(
        value,
        field_name,
    ):
        """
        Normalize a required non-empty text value.
        """

        normalized_value = str(
            value or ""
        ).strip()

        if not normalized_value:
            raise ValueError(
                f"The {field_name} cannot be empty."
            )

        return normalized_value