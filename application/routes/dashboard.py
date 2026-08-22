from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    url_for,
)

from application.services.champion_reference_status_service import (
    ChampionReferenceStatusService,
)
from application.services.champion_reference_update_service import (
    ChampionReferenceUpdateError,
    ChampionReferenceUpdateService,
)
from application.services.dashboard_service import DashboardService
from application.services.sync_service import SyncService


dashboard_bp = Blueprint(
    "dashboard",
    __name__,
)

dashboard_service = DashboardService()
sync_service = SyncService()


REFERENCE_UPDATE_ERROR_MESSAGE = (
    "Champion reference data could not be updated."
)


def _flash_sync_result(
    result,
    operation_name,
):
    """
    Show a concise summary after a batch mastery synchronization.
    """

    total_accounts = result["total_accounts"]
    selected_accounts = result["selected_accounts"]
    updated_count = result["updated"]
    skipped_count = result["skipped"]
    failed_count = result["failed"]

    if total_accounts == 0:
        flash(
            "No Riot accounts are registered.",
            "success",
        )
        return

    if selected_accounts == 0:
        flash(
            f"{operation_name}: No accounts needed synchronization. "
            f"{skipped_count} accounts were already synchronized "
            "within the last 24 hours.",
            "success",
        )
        return

    summary_parts = [
        f"{updated_count} synchronized",
    ]

    if skipped_count:
        summary_parts.append(
            f"{skipped_count} skipped"
        )

    if failed_count:
        summary_parts.append(
            f"{failed_count} failed"
        )

    if failed_count == 0:
        category = "success"

    elif updated_count > 0:
        category = "warning"

    else:
        category = "error"

    flash(
        f"{operation_name}: "
        + ", ".join(
            summary_parts
        )
        + ".",
        category,
    )

    if result["failures"]:
        failure_messages = [
            (
                f'{failure["riot_id"]}: '
                f'{failure["error"]}'
            )
            for failure in result[
                "failures"
            ]
        ]

        flash(
            "Accounts that could not be synchronized: "
            + "; ".join(
                failure_messages
            ),
            "error",
        )


def _flash_reference_update_result(
    result,
):
    """
    Show a controlled summary after a manual reference-data check.
    """

    if result["status"] == "current":
        flash(
            "Champion reference data is already "
            "up to date at version "
            f'{result["data_dragon_version"]}.',
            "success",
        )

        return

    merge_result = result[
        "merge"
    ]

    created_count = merge_result[
        "created"
    ]

    updated_count = merge_result[
        "updated"
    ]

    unchanged_count = merge_result[
        "unchanged"
    ]

    preserved_manual_count = (
        merge_result[
            "preserved_manual"
        ]
    )

    preserved_existing_count = (
        merge_result[
            "preserved_existing"
        ]
    )

    if preserved_manual_count == 1:
        manual_description = (
            "1 manual entry"
        )

    else:
        manual_description = (
            f"{preserved_manual_count} "
            "manual entries"
        )

    if preserved_existing_count == 1:
        existing_description = (
            "1 existing champion "
            "outside the dataset"
        )

    else:
        existing_description = (
            f"{preserved_existing_count} "
            "existing champions "
            "outside the dataset"
        )

    flash(
        "Champion reference data was updated "
        "to version "
        f'{result["data_dragon_version"]}. '
        f"{created_count} created, "
        f"{updated_count} updated, "
        f"and {unchanged_count} unchanged. "
        f"{manual_description} and "
        f"{existing_description} "
        "were preserved.",
        "success",
    )


def _record_reference_update_success(
    result,
):
    """
    Record safe status information after a successful update check.
    """

    current_app.config[
        "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
    ] = None

    if result.get(
        "status"
    ) != "updated":
        return

    dataset = result.get(
        "dataset"
    )

    if not isinstance(
        dataset,
        dict,
    ):
        return

    manifest = dataset.get(
        "manifest"
    )

    if not isinstance(
        manifest,
        dict,
    ):
        return

    generated_at = manifest.get(
        "generated_at"
    )

    if (
        not isinstance(
            generated_at,
            str,
        )
        or not generated_at.strip()
    ):
        return

    current_app.config[
        "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
    ] = generated_at.strip()


def _record_reference_update_failure():
    """
    Record only a controlled user-facing update error.
    """

    current_app.config[
        "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
    ] = REFERENCE_UPDATE_ERROR_MESSAGE


@dashboard_bp.route(
    "/dashboard"
)
def dashboard():
    """
    Return basic application statistics.
    """

    return jsonify(
        dashboard_service.get_statistics()
    )


@dashboard_bp.route(
    "/dashboard/reference-data/status",
    methods=[
        "GET",
    ],
)
def reference_data_status():
    """
    Return safe champion reference status information.
    """

    try:
        status = (
            ChampionReferenceStatusService()
            .get_status()
        )

    except Exception:
        return (
            jsonify(
                {
                    "status": "unavailable",
                    "message": (
                        "Champion reference status "
                        "could not be read."
                    ),
                }
            ),
            503,
        )

    return jsonify(
        status
    )


@dashboard_bp.route(
    "/dashboard/mastery/refresh-stale",
    methods=[
        "POST",
    ],
)
def refresh_stale_mastery():
    """
    Synchronize accounts that have never been synchronized or whose
    last successful synchronization is at least 24 hours old.
    """

    result = (
        sync_service.sync_stale_accounts(
            max_age_hours=24
        )
    )

    _flash_sync_result(
        result=result,
        operation_name=(
            "Stale account synchronization completed"
        ),
    )

    return redirect(
        url_for(
            "home.home"
        )
    )


@dashboard_bp.route(
    "/dashboard/mastery/refresh-all",
    methods=[
        "POST",
    ],
)
def refresh_all_mastery():
    """
    Force synchronization of every locally stored Riot account.
    """

    result = (
        sync_service.sync_all_accounts()
    )

    _flash_sync_result(
        result=result,
        operation_name=(
            "Full synchronization completed"
        ),
    )

    return redirect(
        url_for(
            "home.home"
        )
    )


@dashboard_bp.route(
    "/dashboard/reference-data/refresh",
    methods=[
        "POST",
    ],
)
def refresh_reference_data():
    """
    Explicitly check and update local champion reference data.
    """

    update_service = (
        ChampionReferenceUpdateService()
    )

    try:
        result = (
            update_service
            .update_reference_data()
        )

    except ChampionReferenceUpdateError:
        _record_reference_update_failure()

        flash(
            "Champion reference data could not be "
            "updated. Existing local data remains "
            "available.",
            "error",
        )

    else:
        _record_reference_update_success(
            result
        )

        _flash_reference_update_result(
            result
        )

    return redirect(
        url_for(
            "home.home"
        )
    )