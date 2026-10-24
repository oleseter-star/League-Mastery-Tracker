from urllib.parse import urlencode

from flask import (
    Blueprint,
    abort,
    render_template,
    request,
    url_for,
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

# Quick patch ranges: name -> (label, number of newest stored patches).
PATCH_PRESETS = {
    "latest": ("Latest patch", 1),
    "last3": ("Last 3 patches", 3),
    "last10": ("Last 10 patches", 10),
}

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
    patch_preset = request.args.get("patches", "")
    patches = ()

    if patch_preset in PATCH_PRESETS and available_patches:
        patches = tuple(available_patches[:PATCH_PRESETS[patch_preset][1]])
        patch_from = patch_to = ""

    elif patch_from in available_patches or patch_to in available_patches:
        patch_preset = ""
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
        "patches": patch_preset if patch_preset in PATCH_PRESETS else "",
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

    for name in ("patches", "patch_from", "patch_to", "position"):
        if values.get(name):
            parts.append((name, values[name]))

    if values.get("min_games") not in (None, DEFAULT_MIN_GAMES):
        parts.append(("min_games", values["min_games"]))

    return "&".join(f"{name}={value}" for name, value in parts)


FILTER_NAMES = ("person", "modes", "patches", "patch_from", "patch_to", "position", "min_games")

# Games page drill-down parameters, by their keyword in templates.
DRILL_DOWN_NAMES = {
    "champion": "champion",
    "teammate": "with",
    "ally": "ally",
    "ally_role": "ally_role",
    "enemy": "enemy",
    "enemy_role": "enemy_role",
}


def _games_url(selected, **parameters):
    """
    Link to the games page with the current filters, filter changes, and
    drill-down parameters such as champion=, teammate=, or enemy=.
    """

    filter_changes = {
        name: value
        for name, value in parameters.items()
        if name in FILTER_NAMES
    }
    drill_down = [
        (DRILL_DOWN_NAMES[name], value)
        for name, value in parameters.items()
        if name in DRILL_DOWN_NAMES and value not in (None, "")
    ]
    query = "&".join(
        part
        for part in (_query_string(selected, **filter_changes), urlencode(drill_down))
        if part
    )

    return url_for("match_statistics.get_games") + (f"?{query}" if query else "")


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
        "patch_presets": [(name, label) for name, (label, _count) in PATCH_PRESETS.items()],
        "position_choices": list(POSITION_NAMES.items()),
        "min_game_choices": MIN_GAME_CHOICES,
        "query_string": _query_string(selected),
        "query_with": lambda **changes: _query_string(selected, **changes),
        "games_url": lambda **parameters: _games_url(selected, **parameters),
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

    if selected["person"]:
        person_rows = service.teammates(statistics_filter)
    else:
        person_rows = service.person_overview(statistics_filter)

    return render_template(
        "match_statistics.html",
        person_rows=person_rows,
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


@match_statistics_bp.route(
    "/matches/with/<int:mate_id>",
    methods=["GET"],
)
def get_with_person(mate_id):
    """
    Show results when the selected Person and another tracked Person
    were on the same team.
    """

    mate = db.session.get(Person, mate_id)

    if mate is None:
        abort(404)

    statistics_filter, selected, available_patches = _read_filters()
    context = _filter_context(selected, available_patches)
    person = db.session.get(Person, selected["person"]) if selected["person"] else None

    if person is None or person.id == mate.id:
        return render_template(
            "match_with_person.html",
            person=None,
            mate=mate,
            **context,
        )

    service = MatchStatisticsService()
    together = MatchStatisticsFilter(
        **{**statistics_filter.__dict__, "with_person_id": mate.id}
    )
    mate_side = MatchStatisticsFilter(
        **{
            **statistics_filter.__dict__,
            "person_ids": (mate.id,),
            "with_person_id": person.id,
            "team_position": None,
        }
    )
    record = service.person_overview(_every_row(together))

    def own_games_url(riot_champion_id):
        return _games_url(selected, champion=riot_champion_id, teammate=mate.id)

    def mate_games_url(riot_champion_id):
        return _games_url(
            selected,
            person=mate.id,
            position="",
            champion=riot_champion_id,
            teammate=person.id,
        )

    return render_template(
        "match_with_person.html",
        own_games_url=own_games_url,
        mate_games_url=mate_games_url,
        person=person,
        mate=mate,
        record=record[0] if record else None,
        summary=service.summary(together),
        roles=service.positions(_every_row(together)),
        mate_roles=service.positions(_every_row(mate_side)),
        champions=service.champion_overview(together),
        mate_champions=service.champion_overview(mate_side),
        **context,
    )


GAMES_PER_PAGE = 20


def _read_drill_down():
    """
    Read the games page's extra selection: the tracked side's champion,
    a teammate, and an allied or enemy champion with optional roles.
    """

    def champion(name):
        riot_champion_id = request.args.get(name, type=int)

        if riot_champion_id is None:
            return None

        return Champion.query.filter_by(riot_champion_id=riot_champion_id).one_or_none()

    def role(name):
        value = request.args.get(name, "")
        return value if value in POSITION_NAMES else ""

    teammate_id = request.args.get("with", type=int)
    teammate = db.session.get(Person, teammate_id) if teammate_id else None

    return {
        "champion": champion("champion"),
        "teammate": teammate,
        "ally": champion("ally"),
        "ally_role": role("ally_role"),
        "enemy": champion("enemy"),
        "enemy_role": role("enemy_role"),
    }


def _drill_down_parameters(drill_down):
    parameters = {}

    if drill_down["champion"]:
        parameters["champion"] = drill_down["champion"].riot_champion_id

    if drill_down["teammate"]:
        parameters["with"] = drill_down["teammate"].id

    for side in ("ally", "enemy"):
        if drill_down[side]:
            parameters[side] = drill_down[side].riot_champion_id

            if drill_down[f"{side}_role"]:
                parameters[f"{side}_role"] = drill_down[f"{side}_role"]

    return parameters


@match_statistics_bp.route(
    "/matches/games",
    methods=["GET"],
)
def get_games():
    """
    Show the games behind a statistic as match cards.
    """

    statistics_filter, selected, available_patches = _read_filters()
    drill_down = _read_drill_down()
    page = max(1, request.args.get("page", 1, type=int))

    games_filter = MatchStatisticsFilter(
        **{
            **statistics_filter.__dict__,
            "riot_champion_id": (
                drill_down["champion"].riot_champion_id
                if drill_down["champion"] else None
            ),
            "with_person_id": (
                drill_down["teammate"].id if drill_down["teammate"] else None
            ),
            "min_games": 1,
        }
    )

    result = MatchStatisticsService().games(
        games_filter,
        ally_champion_id=drill_down["ally"].riot_champion_id if drill_down["ally"] else None,
        ally_position=drill_down["ally_role"] or None,
        enemy_champion_id=drill_down["enemy"].riot_champion_id if drill_down["enemy"] else None,
        enemy_position=drill_down["enemy_role"] or None,
        limit=GAMES_PER_PAGE,
        offset=(page - 1) * GAMES_PER_PAGE,
    )

    assignment_service = MatchAssignmentService()
    games = [
        assignment_service.describe_game(match, [participant])
        for match, participant in result["games"]
    ]
    page_count = max(1, -(-result["total"] // GAMES_PER_PAGE))
    drill_parameters = _drill_down_parameters(drill_down)
    context = _filter_context(selected, available_patches)
    base_query = "&".join(
        part for part in (
            context["query_string"],
            "&".join(f"{name}={value}" for name, value in drill_parameters.items()),
        )
        if part
    )

    focus_champion_ids = [
        drill_down[side].riot_champion_id
        for side in ("ally", "enemy")
        if drill_down[side]
    ]

    return render_template(
        "match_games.html",
        focus_champion_ids=focus_champion_ids,
        games=games,
        total=result["total"],
        wins=result["wins"],
        page=page,
        page_count=page_count,
        drill_down=drill_down,
        drill_parameters=drill_parameters,
        base_query=base_query,
        person=db.session.get(Person, selected["person"]) if selected["person"] else None,
        **context,
    )
