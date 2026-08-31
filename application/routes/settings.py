import sqlite3
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from application.services.application_shutdown_service import (
    ApplicationShutdownService,
)
from application.services.backup_service import BackupService
from application.services.riot_api_key_service import (
    RiotApiKeyService,
)
from application.services.riot_legal_notice_service import (
    RiotLegalNoticeService,
)


settings_bp = Blueprint(
    "settings",
    __name__,
)


@settings_bp.route(
    "/settings",
    methods=["GET"],
)
def get_settings():
    """
    Display local application settings.
    """

    api_key_status = (
        RiotApiKeyService.get_status()
    )

    backup_status = (
        _get_backup_status()
    )

    riot_legal_notice = (
        RiotLegalNoticeService
        .get_notice()
    )

    current_app.config[
        "APPLICATION_SHUTDOWN_AVAILABLE"
    ] = (
        ApplicationShutdownService
        .FLASK_EXTENSION_KEY
        in current_app.extensions
    )

    return render_template(
        "settings.html",
        api_key_status=api_key_status,
        backup_status=backup_status,
        startup_backup_error=(
            current_app.config.get(
                "STARTUP_BACKUP_ERROR"
            )
        ),
        riot_legal_notice=(
            riot_legal_notice
        ),
    )


@settings_bp.route(
    "/settings/riot-api-key",
    methods=["POST"],
)
def save_riot_api_key():
    """
    Save or replace the locally configured Riot API key.
    """

    api_key = request.form.get(
        "api_key"
    )

    try:
        status = (
            RiotApiKeyService
            .save_api_key(
                api_key
            )
        )

    except (
        OSError,
        ValueError,
    ) as error:
        flash(
            str(error),
            "error",
        )

    else:
        flash(
            "The Riot API key was saved. "
            f'Active key: {status["masked_key"]}',
            "success",
        )

    return redirect(
        url_for(
            "settings.get_settings"
        )
    )


@settings_bp.route(
    "/settings/riot-api-key/delete",
    methods=["POST"],
)
def delete_riot_api_key():
    """
    Remove the Riot API key saved through the application.
    """

    try:
        deleted = (
            RiotApiKeyService
            .delete_local_api_key()
        )

    except OSError:
        flash(
            "The stored Riot API key could not be removed. "
            "It may still be available to League Mastery Tracker. "
            "Try again.",
            "error",
        )

    else:
        active_status = (
            RiotApiKeyService
            .get_status()
        )

        if not deleted:
            flash(
                "There is no locally stored Riot API key.",
                "warning",
            )

        elif active_status[
            "configured"
        ]:
            flash(
                "The locally stored key was removed. "
                "A key from the environment variable "
                "remains active.",
                "success",
            )

        else:
            flash(
                "The locally stored Riot API key was removed.",
                "success",
            )

    return redirect(
        url_for(
            "settings.get_settings"
        )
    )


@settings_bp.route(
    "/settings/backups/create",
    methods=["POST"],
)
def create_manual_backup():
    """
    Create an internal database backup immediately.

    Manual backups do not use the automatic 24-hour age check.
    """

    try:
        result = (
            BackupService
            .create_backup()
        )

    except (
        FileNotFoundError,
        OSError,
        sqlite3.Error,
        ValueError,
    ):
        flash(
            "The database backup could not be created. "
            "Existing application data remains unchanged.",
            "error",
        )

    else:
        backup_file = result[
            "backup_file"
        ]

        message = (
            "Database backup created: "
            f"{backup_file.name}."
        )

        deleted_count = result[
            "deleted_old_backups"
        ]

        if deleted_count == 1:
            message += (
                " 1 older backup file was removed."
            )

        elif deleted_count > 1:
            message += (
                f" {deleted_count} older backup files "
                "were removed."
            )

        flash(
            message,
            "success",
        )

    return redirect(
        url_for(
            "settings.get_settings"
        )
    )


def _get_backup_status():
    """
    Return display-safe information about internal backups.
    """

    backup_files = (
        BackupService
        .get_backup_files()
    )

    if not backup_files:
        return {
            "exists": False,
            "count": 0,
            "latest_file_name": None,
            "latest_modified": None,
            "latest_size_kib": None,
        }

    latest_backup = (
        backup_files[0]
    )

    latest_modified = (
        datetime
        .fromtimestamp(
            latest_backup
            .stat()
            .st_mtime
        )
        .astimezone()
    )

    return {
        "exists": True,
        "count": len(
            backup_files
        ),
        "latest_file_name": (
            latest_backup.name
        ),
        "latest_modified": (
            latest_modified
        ),
        "latest_size_kib": round(
            (
                latest_backup
                .stat()
                .st_size
            )
            / 1024,
            1,
        ),
    }