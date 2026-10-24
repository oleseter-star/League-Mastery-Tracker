from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from application.database.models import Person
from application.services.match_assignment_service import (
    MatchAssignmentService,
)
from application.services.match_catalog import (
    display_patch,
    queue_label,
)


match_review_bp = Blueprint(
    "match_review",
    __name__,
)


@match_review_bp.app_template_filter("queue_label")
def queue_label_filter(queue_id):
    return queue_label(queue_id)


@match_review_bp.app_template_filter("patch_label")
def patch_label_filter(patch):
    return display_patch(patch)


def _back_to_review():
    return redirect(
        url_for(
            "match_review.get_review"
        )
    )


@match_review_bp.route(
    "/matches/review",
    methods=["GET"],
)
def get_review():
    """
    Show games that need a decision about who played them.
    """

    service = MatchAssignmentService()

    return render_template(
        "match_review.html",
        review_games=service.games_to_review(),
        ignored_games=service.ignored_games(),
        persons=Person.query.order_by(
            Person.display_name
        ).all(),
    )


@match_review_bp.route(
    "/matches/participants/<int:participant_id>/played-by",
    methods=["POST"],
)
def set_played_by(participant_id):
    """
    Record which Person played one account's side of a game.
    """

    person_value = request.form.get(
        "person_id",
        "",
    ).strip()

    try:
        person_id = int(person_value)
    except ValueError:
        flash(
            "Choose who played this game.",
            "error",
        )
        return _back_to_review()

    try:
        MatchAssignmentService().set_played_by(
            participant_id,
            person_id,
        )
    except ValueError as error:
        flash(
            str(error),
            "error",
        )
        return _back_to_review()

    flash(
        "Saved who played the game.",
        "success",
    )

    return _back_to_review()


@match_review_bp.route(
    "/matches/<int:match_id>/ignore",
    methods=["POST"],
)
def ignore_game(match_id):
    """
    Stop counting one game under review.
    """

    if MatchAssignmentService().ignore_review_game(match_id):
        flash(
            "The game is ignored and no longer counts in statistics.",
            "success",
        )
    else:
        flash(
            "That game no longer needs review.",
            "warning",
        )

    return _back_to_review()


@match_review_bp.route(
    "/matches/review/ignore-all",
    methods=["POST"],
)
def ignore_all_games():
    """
    Stop counting every game under review.
    """

    ignored = MatchAssignmentService().ignore_all_review_games()

    flash(
        f"{ignored} games are ignored and no longer count in statistics.",
        "success",
    )

    return _back_to_review()


@match_review_bp.route(
    "/matches/<int:match_id>/restore",
    methods=["POST"],
)
def restore_game(match_id):
    """
    Count an ignored game again.
    """

    if MatchAssignmentService().restore_game(match_id):
        flash(
            "The game counts in statistics again.",
            "success",
        )

    return _back_to_review()
