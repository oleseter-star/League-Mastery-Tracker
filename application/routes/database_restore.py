from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from application.services.database_restore_service import (
    DatabaseRestoreError,
    DatabaseRestoreService,
)


database_restore_bp = Blueprint(
    "database_restore",
    __name__,
)


@database_restore_bp.get(
    "/settings/database-restore"
)
def get_database_restore():
    restore_candidates = []
    restore_candidates_error = None

    pending_restore = None
    pending_restore_error = None

    try:
        restore_candidates = (
            DatabaseRestoreService
            .get_restore_candidates()
        )

    except (
        DatabaseRestoreError,
        OSError,
    ) as error:
        restore_candidates_error = str(
            error
        )

    try:
        pending_restore = (
            DatabaseRestoreService
            .get_pending_restore()
        )

    except DatabaseRestoreError as error:
        pending_restore_error = str(
            error
        )

    startup_restore_result = current_app.config.get(
        "STARTUP_DATABASE_RESTORE_RESULT"
    )

    return render_template(
        "database_restore.html",
        restore_candidates=restore_candidates,
        restore_candidates_error=(
            restore_candidates_error
        ),
        pending_restore=pending_restore,
        pending_restore_error=(
            pending_restore_error
        ),
        startup_restore_result=(
            startup_restore_result
        ),
    )


@database_restore_bp.post(
    "/settings/database-restore/stage"
)
def stage_database_restore():
    backup_file_name = str(
        request.form.get(
            "backup_file_name",
            "",
        )
    ).strip()

    confirmation = str(
        request.form.get(
            "confirmation",
            "",
        )
    ).strip()

    if confirmation != "RESTORE":
        flash(
            "Type RESTORE exactly to confirm the "
            "database restore.",
            "error",
        )

        return redirect(
            url_for(
                "database_restore."
                "get_database_restore"
            )
        )

    try:
        pending_restore = (
            DatabaseRestoreService
            .stage_restore(
                backup_file_name
            )
        )

    except DatabaseRestoreError as error:
        flash(
            str(error),
            "error",
        )

    else:
        flash(
            "Database restore staged from "
            f"{pending_restore['source_backup_file_name']}. "
            "Restart the application to apply it.",
            "success",
        )

    return redirect(
        url_for(
            "database_restore."
            "get_database_restore"
        )
    )


@database_restore_bp.post(
    "/settings/database-restore/cancel"
)
def cancel_database_restore():
    cancelled = (
        DatabaseRestoreService
        .cancel_pending_restore()
    )

    if cancelled:
        flash(
            "The pending database restore was cancelled.",
            "success",
        )

    else:
        flash(
            "There is no pending database restore "
            "to cancel.",
            "info",
        )

    return redirect(
        url_for(
            "database_restore."
            "get_database_restore"
        )
    )