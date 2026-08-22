from flask import (
    Blueprint,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from application.services.json_import_read_service import (
    JsonImportReadService,
)
from application.services.json_import_staging_service import (
    JsonImportStagingService,
)
from application.services.json_import_workflow_service import (
    JsonImportWorkflowError,
    JsonImportWorkflowService,
)


json_import_bp = Blueprint(
    "json_import",
    __name__,
)


SESSION_STAGING_TOKEN_KEY = (
    "json_import_staging_token"
)

UPLOAD_FIELD_NAME = "import_file"

DEFAULT_MAX_FILE_SIZE_BYTES = (
    JsonImportReadService
    .DEFAULT_MAX_FILE_SIZE_BYTES
)

DEFAULT_EXPIRATION_MINUTES = (
    JsonImportStagingService
    .DEFAULT_EXPIRATION_MINUTES
)


@json_import_bp.app_errorhandler(
    RequestEntityTooLarge
)
def handle_request_entity_too_large(
    error,
):
    """
    Return a controlled response when Flask rejects an oversized
    request before the route can process the uploaded file.

    The handler is registered application-wide because the request
    body may be rejected during CSRF validation, before normal route
    execution begins.
    """

    if request.path.startswith(
        "/settings/data-import"
    ):
        flash(
            "The selected import file is too large. "
            "Select a JSON file within the allowed file size.",
            "error",
        )

        return _redirect_to_import_page()

    response = make_response(
        "Request Entity Too Large",
        413,
    )

    response.headers[
        "Content-Type"
    ] = "text/plain; charset=utf-8"

    return _apply_no_store_headers(
        response
    )


@json_import_bp.route(
    "/settings/data-import",
    methods=["GET"],
)
def get_json_import():
    """
    Display the JSON import upload page or the active staged
    import preview.

    The staging token is stored in the signed Flask session rather
    than exposed in the URL or HTML form.
    """

    prepared_import = None

    staging_token = session.get(
        SESSION_STAGING_TOKEN_KEY
    )

    if staging_token is not None:
        try:
            prepared_import = (
                JsonImportWorkflowService
                .inspect_staged(
                    staging_token
                )
            )

        except JsonImportWorkflowError as error:
            session.pop(
                SESSION_STAGING_TOKEN_KEY,
                None,
            )

            flash(
                _get_workflow_error_message(
                    error
                ),
                "error",
            )

    response = make_response(
        render_template(
            "json_import.html",
            prepared_import=prepared_import,
            confirmation_text=(
                JsonImportWorkflowService
                .EXECUTION_CONFIRMATION_TEXT
            ),
            max_file_size_mib=round(
                _get_max_file_size_bytes()
                / 1024
                / 1024,
                1,
            ),
        )
    )

    return _apply_no_store_headers(
        response
    )


@json_import_bp.route(
    "/settings/data-import/stage",
    methods=["POST"],
)
def stage_json_import():
    """
    Validate and privately stage one uploaded JSON export.

    Staging and preview generation do not modify the database.
    """

    uploaded_file = request.files.get(
        UPLOAD_FIELD_NAME
    )

    if (
        uploaded_file is None
        or not uploaded_file.filename
        or not uploaded_file.filename.strip()
    ):
        flash(
            "Select a JSON export file before continuing.",
            "warning",
        )

        return _redirect_to_import_page()

    try:
        prepared_import = (
            JsonImportWorkflowService
            .stage_stream(
                stream=uploaded_file.stream,
                file_name=uploaded_file.filename,
                max_file_size_bytes=(
                    _get_max_file_size_bytes()
                ),
                expiration_minutes=(
                    _get_expiration_minutes()
                ),
            )
        )

    except JsonImportWorkflowError as error:
        staging = error.staging

        if (
            isinstance(
                staging,
                dict,
            )
            and staging.get(
                "staging_token"
            )
        ):
            session[
                SESSION_STAGING_TOKEN_KEY
            ] = staging[
                "staging_token"
            ]

        flash(
            _get_workflow_error_message(
                error
            ),
            "error",
        )

        return _redirect_to_import_page()

    session[
        SESSION_STAGING_TOKEN_KEY
    ] = prepared_import[
        "staging"
    ][
        "staging_token"
    ]

    preview = prepared_import[
        "preview"
    ]

    if preview[
        "can_import"
    ]:
        flash(
            "The JSON file was validated and stored temporarily. "
            "Review the preview before confirming the import.",
            "success",
        )

    else:
        blocker_count = preview[
            "summary"
        ][
            "blocker_count"
        ]

        flash(
            "The JSON file was validated, but the import is "
            f"blocked by {blocker_count} conflict(s).",
            "warning",
        )

    return _redirect_to_import_page()


@json_import_bp.route(
    "/settings/data-import/execute",
    methods=["POST"],
)
def execute_json_import():
    """
    Execute the active staged import after exact confirmation.

    The workflow revalidates the staged source, rebuilds preview and
    plan, creates a mandatory backup, and applies all changes in one
    transaction.
    """

    staging_token = session.get(
        SESSION_STAGING_TOKEN_KEY
    )

    if staging_token is None:
        flash(
            "There is no active JSON import to execute.",
            "warning",
        )

        return _redirect_to_import_page()

    confirmation_text = request.form.get(
        "confirmation_text"
    )

    try:
        workflow_result = (
            JsonImportWorkflowService
            .execute_staged(
                staging_token=staging_token,
                confirmation_text=(
                    confirmation_text
                ),
            )
        )

    except JsonImportWorkflowError as error:
        if error.stage == "staging":
            session.pop(
                SESSION_STAGING_TOKEN_KEY,
                None,
            )

        flash(
            _get_workflow_error_message(
                error
            ),
            "error",
        )

        return _redirect_to_import_page()

    session.pop(
        SESSION_STAGING_TOKEN_KEY,
        None,
    )

    execution_result = workflow_result[
        "execution"
    ]

    if execution_result[
        "applied"
    ]:
        created = execution_result[
            "created"
        ]

        backup_file = execution_result[
            "backup_file"
        ]

        flash(
            "The JSON import was completed. "
            f'{created["persons"]} person(s), '
            f'{created["riot_accounts"]} Riot account(s), '
            f'{created["champions"]} champion(s), and '
            f'{created["mastery_records"]} mastery record(s) '
            "were created. "
            f"Safety backup: {backup_file.name}.",
            "success",
        )

    else:
        flash(
            "The JSON file was valid but contained no new "
            "database changes.",
            "success",
        )

    staging_cleanup = workflow_result[
        "staging_cleanup"
    ]

    if not staging_cleanup[
        "cleared"
    ]:
        flash(
            "The import was saved to the database, but the "
            "temporary import file could not be removed "
            "automatically. It will be removed during a later "
            "staging operation.",
            "warning",
        )

    return _redirect_to_import_page()


@json_import_bp.route(
    "/settings/data-import/cancel",
    methods=["POST"],
)
def cancel_json_import():
    """
    Cancel the active staged import without changing the database.
    """

    staging_token = session.get(
        SESSION_STAGING_TOKEN_KEY
    )

    if staging_token is None:
        flash(
            "There is no active JSON import to cancel.",
            "warning",
        )

        return _redirect_to_import_page()

    try:
        result = (
            JsonImportWorkflowService
            .cancel_staged(
                staging_token
            )
        )

    except JsonImportWorkflowError as error:
        flash(
            _get_workflow_error_message(
                error
            ),
            "error",
        )

    else:
        flash(
            "The temporary JSON import was cancelled, and "
            f'the file "{result["original_file_name"]}" was '
            "removed.",
            "success",
        )

    finally:
        session.pop(
            SESSION_STAGING_TOKEN_KEY,
            None,
        )

    return _redirect_to_import_page()


def _get_max_file_size_bytes():
    """
    Return the configured hard import-file limit.

    The service validates the final value.
    """

    return current_app.config.get(
        "JSON_IMPORT_MAX_FILE_SIZE_BYTES",
        DEFAULT_MAX_FILE_SIZE_BYTES,
    )


def _get_expiration_minutes():
    """
    Return the configured staged-import lifetime.
    """

    return current_app.config.get(
        "JSON_IMPORT_STAGING_EXPIRATION_MINUTES",
        DEFAULT_EXPIRATION_MINUTES,
    )


def _redirect_to_import_page():
    response = make_response(
        redirect(
            url_for(
                "json_import.get_json_import"
            )
        )
    )

    return _apply_no_store_headers(
        response
    )


def _apply_no_store_headers(
    response,
):
    response.headers[
        "Cache-Control"
    ] = (
        "no-store, no-cache, must-revalidate, "
        "max-age=0"
    )

    response.headers[
        "Pragma"
    ] = "no-cache"

    response.headers[
        "Expires"
    ] = "0"

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    return response


def _get_workflow_error_message(
    error,
):
    """
    Convert internal workflow stages into user-safe messages.

    Causes and local filesystem paths are deliberately not exposed
    through the web interface.
    """

    messages = {
        "staging": (
            "The temporary JSON import could not be saved or "
            "verified safely."
        ),
        "read": (
            "The JSON file could not be read or validated. "
            "Confirm that it is a valid export from "
            "League Mastery Tracker."
        ),
        "preview": (
            "The preview could not be built, or the import "
            "contains conflicts that must be resolved first."
        ),
        "plan": (
            "A safe import plan could not be built from the file."
        ),
        "confirmation": (
            "The import was not confirmed. Type IMPORT exactly "
            "as shown."
        ),
        "execution": (
            "The JSON import could not be completed safely. "
            "Any database changes that had started were rolled "
            "back."
        ),
    }

    return messages.get(
        error.stage,
        "The JSON import could not be completed.",
    )