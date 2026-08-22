from flask import Blueprint, render_template

from application.services.champion_reference_status_service import (
    ChampionReferenceStatusService,
)
from application.services.dashboard_service import DashboardService


home_bp = Blueprint(
    "home",
    __name__,
)


def _get_champion_reference_status():
    """
    Return safe champion reference status for the home page.

    A status failure must not prevent the main dashboard from loading
    or expose internal exception details.
    """

    try:
        return (
            ChampionReferenceStatusService()
            .get_status()
        )

    except Exception:
        return {
            "active_source": "database_only",
            "active_source_label": (
                "Database-only fallback"
            ),
            "reference_data_available": False,
            "uses_bundled_fallback": False,
            "uses_local_cache": False,
            "database_only": True,
            "data_dragon_version": None,
            "locale": None,
            "dataset_champion_count": None,
            "database_champion_count": None,
            "missing_name_count": None,
            "missing_image_count": None,
            "missing_metadata_count": None,
            "has_missing_metadata": False,
            "last_successful_update": None,
            "last_update_error": None,
            "warnings": [
                (
                    "Champion reference status "
                    "could not be read."
                ),
            ],
        }


@home_bp.route("/")
def home():
    """
    Display the main Person dashboard.
    """

    dashboard = (
        DashboardService.get_home_dashboard()
    )

    champion_reference_status = (
        _get_champion_reference_status()
    )

    return render_template(
        "home.html",
        persons=dashboard["persons"],
        person_count=dashboard["person_count"],
        champion_reference_status=(
            champion_reference_status
        ),
    )