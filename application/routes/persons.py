from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from requests import HTTPError, RequestException

from application.services.dashboard_service import DashboardService
from application.services.person_service import PersonService
from application.services.riot_account_service import RiotAccountService
from application.services.riot_service import RiotService
from application.services.sync_service import SyncService


persons_bp = Blueprint(
    "persons",
    __name__,
)

sync_service = SyncService()


def get_platform_regions():
    """
    Return supported Riot platform routing values.
    """

    return sorted(
        RiotService.PLATFORM_TO_REGIONAL.keys()
    )


def get_riot_error_message(error):
    """
    Convert Riot API errors into user-facing messages.
    """

    response = error.response

    if response is None:
        return (
            "Could not contact the Riot API. "
            "Check your network connection."
        )

    status_code = response.status_code

    if status_code in (401, 403):
        return (
            "The Riot API key is missing, invalid, or expired."
        )

    if status_code == 404:
        return (
            "The Riot account was not found. "
            "Check the Riot ID, tag, and platform."
        )

    if status_code == 429:
        return (
            "The Riot API rate limit has been reached. "
            "Try again later."
        )

    return (
        f"The Riot API returned error {status_code}."
    )


@persons_bp.route(
    "/persons",
    methods=["GET"],
)
def get_persons():
    """
    Display all locally created Persons.
    """

    persons = PersonService.get_all_persons()

    return render_template(
        "persons.html",
        persons=persons,
    )


@persons_bp.route(
    "/persons/<int:person_id>",
    methods=["GET"],
)
def get_person(person_id):
    """
    Display one Person and their combined mastery overview.
    """

    mastery_overview = (
        DashboardService.get_person_mastery_overview(
            person_id
        )
    )

    if mastery_overview is None:
        abort(404)

    move_target_persons = [
        candidate_person
        for candidate_person
        in PersonService.get_all_persons()
        if candidate_person.id != person_id
    ]

    return render_template(
        "person_detail.html",
        person=mastery_overview["person"],
        riot_accounts=mastery_overview["riot_accounts"],
        top_champions=mastery_overview["top_champions"],
        champions=mastery_overview["champions"],
        total_mastery=mastery_overview["total_mastery"],
        platform_regions=get_platform_regions(),
        move_target_persons=move_target_persons,
    )


@persons_bp.route(
    "/persons",
    methods=["POST"],
)
def create_person():
    """
    Create a new local Person from an HTML form or JSON request.
    """

    if request.is_json:
        request_data = request.get_json(
            silent=True
        ) or {}
    else:
        request_data = request.form

    display_name = request_data.get(
        "display_name"
    )

    try:
        person = PersonService.create_person(
            display_name=display_name
        )

    except ValueError as error:
        if request.is_json:
            return jsonify(
                {
                    "error": str(error),
                }
            ), 400

        persons = PersonService.get_all_persons()

        return render_template(
            "persons.html",
            persons=persons,
            error_message=str(error),
        ), 400

    if request.is_json:
        return jsonify(
            {
                "person": {
                    "id": person.id,
                    "display_name": person.display_name,
                    "riot_account_count": 0,
                },
            }
        ), 201

    flash(
        f'Person "{person.display_name}" was created.',
        "success",
    )

    return redirect(
        url_for(
            "persons.get_person",
            person_id=person.id,
        )
    )


@persons_bp.route(
    "/persons/<int:person_id>/edit",
    methods=["POST"],
)
def update_person(person_id):
    """
    Update a Person's display name.
    """

    person = PersonService.get_person_by_id(
        person_id
    )

    if person is None:
        abort(404)

    display_name = request.form.get(
        "display_name"
    )

    try:
        updated_person = PersonService.update_person(
            person=person,
            display_name=display_name,
        )

    except ValueError as error:
        flash(
            str(error),
            "error",
        )

    else:
        flash(
            "The display name was changed to "
            f'"{updated_person.display_name}".',
            "success",
        )

    return redirect(
        url_for(
            "persons.get_person",
            person_id=person.id,
        )
    )


@persons_bp.route(
    "/persons/<int:person_id>/delete",
    methods=["POST"],
)
def delete_person(person_id):
    """
    Delete a Person and all connected local data.
    """

    person = PersonService.get_person_by_id(
        person_id
    )

    if person is None:
        abort(404)

    display_name = person.display_name

    PersonService.delete_person(
        person
    )

    flash(
        f'Person "{display_name}" was deleted.',
        "success",
    )

    return redirect(
        url_for(
            "persons.get_persons"
        )
    )


@persons_bp.route(
    "/persons/<int:person_id>/riot-accounts",
    methods=["POST"],
)
def add_riot_account(person_id):
    """
    Look up and connect one Riot Account to a Person.

    This operation validates the Riot ID, retrieves its PUUID and
    stores the account. Champion Mastery is not synchronized here.
    """

    person = PersonService.get_person_by_id(
        person_id
    )

    if person is None:
        abort(404)

    game_name = request.form.get(
        "game_name"
    )

    tag_line = request.form.get(
        "tag_line"
    )

    platform_region = request.form.get(
        "platform_region"
    )

    try:
        riot_account = sync_service.sync_account(
            person_id=person.id,
            game_name=game_name,
            tag_line=tag_line,
            platform_region=platform_region,
        )

    except ValueError as error:
        flash(
            str(error),
            "error",
        )

    except RuntimeError as error:
        flash(
            str(error),
            "error",
        )

    except HTTPError as error:
        flash(
            get_riot_error_message(error),
            "error",
        )

    except RequestException:
        flash(
            "Could not contact the Riot API. "
            "Check your network connection.",
            "error",
        )

    else:
        riot_id = (
            f"{riot_account.game_name}"
            f"#{riot_account.tag_line}"
        )

        flash(
            f'Riot account "{riot_id}" was added. '
            "Champion Mastery can be synchronized from the "
            "dashboard.",
            "success",
        )

    return redirect(
        url_for(
            "persons.get_person",
            person_id=person.id,
        )
    )


@persons_bp.route(
    (
        "/persons/<int:person_id>/riot-accounts/"
        "<int:riot_account_id>/move"
    ),
    methods=["POST"],
)
def move_riot_account(
    person_id,
    riot_account_id,
):
    """
    Move one Riot Account from this Person to another Person.
    """

    person = PersonService.get_person_by_id(
        person_id
    )

    if person is None:
        abort(404)

    target_person_id = request.form.get(
        "target_person_id"
    )

    try:
        result = RiotAccountService.move_riot_account(
            source_person_id=person.id,
            riot_account_id=riot_account_id,
            target_person_id=target_person_id,
        )

    except ValueError as error:
        flash(
            str(error),
            "error",
        )

        return redirect(
            url_for(
                "persons.get_person",
                person_id=person.id,
            )
        )

    target_person = PersonService.get_person_by_id(
        result["target_person_id"]
    )

    flash(
        f'Riot account "{result["riot_id"]}" '
        f'was moved to "{target_person.display_name}".',
        "success",
    )

    return redirect(
        url_for(
            "persons.get_person",
            person_id=target_person.id,
        )
    )