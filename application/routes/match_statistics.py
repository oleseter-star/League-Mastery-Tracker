from flask import (
    Blueprint,
    abort,
    render_template,
    request,
)

from application.database.database import db
from application.database.models import (
    Champion,
    Match,
    MatchParticipant,
    Person,
    RiotAccount,
)
from application.services.match_assignment_service import (
    MatchAssignmentService,
)
from application.services.match_catalog import (
    MODE_QUEUE_IDS,
    POSITION_NAMES,
    display_patch,
    patch_sort_key,
    position_label,
    queue_label,
)
from application.services.match_statistics_service import (
    MatchStatisticsFilter,
    MatchStatisticsService,
)


match_statistics_bp = Blueprint(
    "match_statistics",
    __name__,
)

MODE_ORDER = ("solo", "flex", "5s", "clash")

MIN_GAME_CHOICES = (1, 2, 3, 5, 10, 20)

DEFAULT_MIN_GAMES = 3


@match_statistics_bp.app_template_filter("position_label")
def position_label_filter(team_position):
    return position_label(team_position)


def _read_filters():
    """
    Read statistics filters from the query string.

    Unknown values are ignored, so an outdated link still shows a page.
    """

    service = MatchStatisticsService()
    available_patches = service.available_patches()

    person_id = request.args.get("person", type=int)

    if person_id is not None and db.session.get(Person, person_id) is None:
        person_id = None

    modes = [
        mode
        for mode in request.args.getlist("mode")
        if mode in MODE_QUEUE_IDS
    ]

    patch_from = request.args.get("patch_from", "")
    patch_to = request.args.get("patch_to", "")
    patches = ()

    if patch_from in available_patches or patch_to in available_patches:
        low = patch_sort_key(patch_from if patch_from in available_patches else available_patches[-1])
        high = patch_sort_key(patch_to if patch_to in available_patches else available_patches[0])

        if low > high:
            low, high = high, low

        patches = tuple(
            patch
            for patch in available_patches
            if low <= patch_sort_key(patch) <= high
        )

    position = request.args.get("position", "")

    if position not in POSITION_NAMES:
        position = ""

    min_games = request.args.get("min_games", DEFAULT_MIN_GAMES, type=int)

    if min_games not in MIN_GAME_CHOICES:
        min_games = DEFAULT_MIN_GAMES

    statistics_filter = MatchStatisticsFilter(
        person_ids=(person_id,) if person_id else (),
        queue_ids=tuple(MODE_QUEUE_IDS[mode] for mode in modes),
        patches=patches,
        team_position=position or None,
        min_games=min_games,
    )

    selected = {
        "person": person_id,
        "modes": modes,
        "patch_from": patch_from if patch_from in available_patches else "",
        "patch_to": patch_to if patch_to in available_patches else "",
        "position": position,
        "min_games": min_games,
    }

    return statistics_filter, selected, available_patches


def _query_string(selected, **changes):
    """
    Rebuild the query string so links keep the current filters.
    """

    values = dict(selected, **changes)
    parts = []

    if values.get("person"):
        parts.append(("person", values["person"]))

    for mode in values.get("modes", []):
        parts.append(("mode", mode))

    for name in ("patch_from", "patch_to", "position"):
        if values.get(name):
            parts.append((name, values[name]))

    if values.get("min_games") not in (None, DEFAULT_MIN_GAMES):
        parts.append(("min_games", values["min_games"]))

    return "&".join(f"{name}={value}" for name, value in parts)


def _filter_context(selected, available_patches):
    persons_with_games = (
        Person.query
        .join(RiotAccount, RiotAccount.person_id == Person.id)
        .join(MatchParticipant, MatchParticipant.riot_account_id == RiotAccount.id)
        .distinct()
        .order_by(Person.display_name)
        .all()
    )

    return {
        "selected": selected,
        "persons": persons_with_games,
        "mode_choices": [(mode, queue_label(MODE_QUEUE_IDS[mode])) for mode in MODE_ORDER],
        "patch_choices": [(patch, display_patch(patch)) for patch in available_patches],
        "position_choices": list(POSITION_NAMES.items()),
        "min_game_choices": MIN_GAME_CHOICES,
        "query_string": _query_string(selected),
        "review_count": len(MatchAssignmentService().games_to_review()),
        "has_games": Match.query.first() is not None,
    }


def _overall_record(service, statistics_filter):
    """
    Games for the current filters, and the win rate when one Person is
    selected. Across several Persons a game can be a win for one and a
    loss for another, so no combined win rate is shown.
    """

    summary = service.summary(statistics_filter)
    record = {
        "games": summary["games"],
        "wins": None,
        "losses": None,
        "win_rate": None,
        "first_game": summary["first_game"],
        "last_game": summary["last_game"],
    }

    if statistics_filter.person_ids:
        rows = service.person_overview(_every_row(statistics_filter))

        if rows:
            record.update(
                wins=rows[0]["wins"],
                losses=rows[0]["losses"],
                win_rate=rows[0]["win_rate"],
            )

    return record


def _every_row(statistics_filter, **changes):
    """
    The same filters without the minimum game count.
    """

    return MatchStatisticsFilter(
        **{**statistics_filter.__dict__, "min_games": 1, **changes}
    )


@match_statistics_bp.route(
    "/matches",
    methods=["GET"],
)
def get_statistics():
    """
    Show win rates per champion for the selected filters.
    """

    statistics_filter, selected, available_patches = _read_filters()
    service = MatchStatisticsService()

    return render_template(
        "match_statistics.html",
        champions=service.champion_overview(statistics_filter),
        record=_overall_record(service, statistics_filter),
        roles=service.positions(_every_row(statistics_filter)),
        **_filter_context(selected, available_patches),
    )


@match_statistics_bp.route(
    "/matches/champions/<int:riot_champion_id>",
    methods=["GET"],
)
def get_champion(riot_champion_id):
    """
    Show one champion's results with and against other champions and
    with tracked persons.
    """

    champion = Champion.query.filter_by(
        riot_champion_id=riot_champion_id
    ).one_or_none()

    if champion is None:
        abort(404)

    statistics_filter, selected, available_patches = _read_filters()
    champion_filter = MatchStatisticsFilter(
        **{**statistics_filter.__dict__, "riot_champion_id": riot_champion_id}
    )
    every_row = _every_row(champion_filter)
    service = MatchStatisticsService()

    overview = service.champion_overview(every_row)
    roles = service.positions(every_row)
    main_role = roles[0]["team_position"] if roles else None

    return render_template(
        "match_champion.html",
        champion=champion,
        record=overview[0] if overview else None,
        roles=roles,
        main_role=main_role,
        allies_by_role=_group_by_role(service.ally_champions(champion_filter, by_position=True)),
        enemies_by_role=_group_by_role(service.enemy_champions(champion_filter, by_position=True)),
        teammates=service.teammates(champion_filter),
        patches=service.patch_results(every_row),
        **_filter_context(selected, available_patches),
    )


def _group_by_role(rows):
    groups = {position: [] for position in POSITION_NAMES}

    for row in rows:
        if row["team_position"] in groups:
            groups[row["team_position"]].append(row)

    return groups
