from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from application.services.champion_service import ChampionService


champions_bp = Blueprint(
    "champions",
    __name__,
)


@champions_bp.route(
    "/champions/missing",
    methods=["GET"],
)
def get_missing_champions():
    """
    Display champions that are missing a reference name.
    """

    champions = (
        ChampionService.get_missing_reference_champions()
    )

    return render_template(
        "missing_champions.html",
        champions=champions,
    )


@champions_bp.route(
    "/champions/<int:champion_id>/name",
    methods=["POST"],
)
def update_champion_name(champion_id):
    """
    Assign a manual name to a champion missing reference data.
    """

    champion = ChampionService.get_champion_by_id(
        champion_id
    )

    if champion is None:
        abort(404)

    name = str(
        request.form.get("name") or ""
    ).strip()

    if not name:
        flash(
            "Champion name is required.",
            "error",
        )

        return redirect(
            url_for(
                "champions.get_missing_champions"
            )
        )

    if len(name) > 100:
        flash(
            "Champion name cannot be longer than "
            "100 characters.",
            "error",
        )

        return redirect(
            url_for(
                "champions.get_missing_champions"
            )
        )

    ChampionService.update_champion(
        champion=champion,
        name=name,
        source="manual",
    )

    flash(
        f'Champion {champion.riot_champion_id} '
        f'was saved as "{champion.name}".',
        "success",
    )

    return redirect(
        url_for(
            "champions.get_missing_champions"
        )
    )