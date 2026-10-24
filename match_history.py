"""Import Riot match history and print statistics from the command line.

Uses the application's data directory and saved Riot API key until the
application has its own match history pages. Close League Mastery Tracker
before importing; statistics can be printed while it is open.

Only ranked games and Summoner's Rift Clash are imported. The import uses
the RIOT_API_KEY environment variable when it is set, otherwise the key
saved in Settings, or --ask-key.

Games played by someone else on your account can be moved to that Person:

    python match_history.py games --account "Main#EUW" --together-with "Alt#EUW"
    python match_history.py assign --account "Alt#EUW" --together-with "Main#EUW" --person Friend
    python match_history.py assign --account "Alt#EUW" --match EUW1_7212345678 --ignore

The same decisions can be made in the application under Matches.

    python match_history.py import
    python match_history.py import --account "Main#EUW" --max-games 200 --ask-key
    python match_history.py stats summary
    python match_history.py stats champions --person Ole --mode solo
    python match_history.py stats allies --person Ole --champion Lux --patch 26.12-26.18
    python match_history.py stats lanes --person Ole --champion Lux --position mid
    python match_history.py stats patches --person Ole --champion Lux
"""

import argparse
import getpass
import os
import sys
from datetime import datetime

from application.database.database import db
from application.database.models import Champion, Person, RiotAccount
from application.services.application_instance_service import (
    ApplicationInstanceService,
)
from application.services.match_assignment_service import (
    GameSelection,
    MatchAssignmentService,
)
from application.services.match_catalog import (
    MODE_QUEUE_IDS,
    display_patch,
    parse_patch_selection,
    position_label,
    queue_id_for_mode,
    queue_label,
)
from application.services.match_import_service import (
    MatchImportError,
    MatchImportService,
)
from application.services.match_statistics_service import (
    MatchStatisticsFilter,
    MatchStatisticsService,
)
from application.services.riot_service import RiotService


POSITIONS = {
    "top": "TOP",
    "jungle": "JUNGLE",
    "jg": "JUNGLE",
    "mid": "MIDDLE",
    "middle": "MIDDLE",
    "bot": "BOTTOM",
    "bottom": "BOTTOM",
    "adc": "BOTTOM",
    "support": "UTILITY",
    "sup": "UTILITY",
    "utility": "UTILITY",
}

# Statistics view name -> (service method, label columns, keyword arguments)
VIEWS = {
    "persons": ("person_overview", ("person_name",), {}),
    "champions": ("champion_overview", ("champion",), {}),
    "person-champions": ("person_champions", ("person_name", "champion"), {}),
    "positions": ("person_champion_positions", ("person_name", "champion", "team_position"), {}),
    "allies": ("ally_champions", ("champion",), {}),
    "enemies": ("enemy_champions", ("champion",), {}),
    "lanes": ("enemy_champions", ("champion",), {"lane_opponents_only": True}),
    "pairs": ("person_pairs", ("person_name", "other_person_name"), {}),
    "patches": ("patch_results", ("patch",), {}),
}

COLUMN_TITLES = {
    "person_name": "Person",
    "other_person_name": "With",
    "champion": "Champion",
    "team_position": "Position",
    "patch": "Patch",
}

# Riot development keys allow 100 requests per two minutes.
SECONDS_PER_GAME = 1.3


class CommandError(ValueError):
    """A problem with the command-line arguments."""


class KeyOverrideRiotService(RiotService):
    """RiotService that uses a key entered for this run only."""

    def __init__(self, api_key, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def _headers(self):
        return {
            "X-Riot-Token": self.api_key,
            "Accept": "application/json",
        }


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Import Riot match history and print win rate statistics."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    import_parser = commands.add_parser("import", help="Download new games from Riot.")
    import_parser.add_argument("--account", action="append", default=[], metavar="NAME#TAG", help="Riot account to import; repeat for several. Default: every account.")
    import_parser.add_argument("--max-games", type=int, help="Most new games to download per account in this run.")
    import_parser.add_argument("--queue", type=int, action="append", default=[], metavar="QUEUE_ID", help="Import only this queue; repeat for several. Default: every ranked queue and Summoner's Rift Clash.")
    import_parser.add_argument("--ask-key", action="store_true", help="Enter a Riot API key for this run instead of the saved key.")

    stats_parser = commands.add_parser("stats", help="Print statistics from stored games.")
    stats_parser.add_argument("view", choices=["summary", *VIEWS], help="What to show.")
    stats_parser.add_argument("--person", action="append", default=[], help="Person to include; repeat for several. Default: everyone.")
    stats_parser.add_argument("--account", action="append", default=[], metavar="NAME#TAG", help="Limit to Riot accounts.")
    stats_parser.add_argument("--champion", help="Only games where the Person played this champion.")
    stats_parser.add_argument("--position", choices=sorted(POSITIONS), help="Only games in this position.")
    stats_parser.add_argument("--mode", action="append", default=[], metavar="MODE", help=f"Only this mode: {', '.join(sorted(MODE_QUEUE_IDS))}; repeat to combine. Default: all.")
    stats_parser.add_argument("--queue", type=int, action="append", default=[], metavar="QUEUE_ID", help="Only this queue ID, for queues without a mode name.")
    stats_parser.add_argument("--patch", action="append", default=[], metavar="PATCH", help="Only these patches: 26.18, a list (26.17,26.18), or a range (26.12-26.18); repeat to combine.")
    stats_parser.add_argument("--since", type=parse_date, help="Only games on or after this date (YYYY-MM-DD).")
    stats_parser.add_argument("--until", type=parse_date, help="Only games before this date (YYYY-MM-DD).")
    stats_parser.add_argument("--min-games", type=int, default=3, help="Hide rows with fewer games (default 3).")
    stats_parser.add_argument("--limit", type=int, default=25, help="Most rows to print (default 25).")
    stats_parser.add_argument("--include-remakes", action="store_true", help="Count games shorter than five minutes.")

    games_parser = commands.add_parser("games", help="List one account's stored games and who played them.")
    add_game_selection_arguments(games_parser)
    games_parser.add_argument("--limit", type=int, default=50, help="Most games to print, newest first (default 50).")

    assign_parser = commands.add_parser("assign", help="Record which Person played games on an account.")
    add_game_selection_arguments(assign_parser)
    target = assign_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--person", help="The Person who played the selected games.")
    target.add_argument("--to-owner", action="store_true", help="Give the selected games back to the account's owner.")
    target.add_argument("--ignore", action="store_true", help="Stop counting the selected games in statistics.")
    target.add_argument("--restore", action="store_true", help="Count ignored games in statistics again.")
    assign_parser.add_argument("--all-games", action="store_true", help="Select every game on the account.")

    return parser


def add_game_selection_arguments(parser):
    parser.add_argument("--account", required=True, metavar="NAME#TAG", help="The Riot account the games were played on.")
    parser.add_argument("--match", action="append", default=[], metavar="MATCH_ID", help="Only this game, for example EUW1_7212345678; repeat for several.")
    parser.add_argument("--together-with", metavar="NAME#TAG", help="Only games where this other tracked account was also in the game.")
    parser.add_argument("--champion", help="Only games on this champion.")
    parser.add_argument("--mode", action="append", default=[], metavar="MODE", help=f"Only this mode: {', '.join(sorted(MODE_QUEUE_IDS))}.")
    parser.add_argument("--since", type=parse_date, help="Only games on or after this date (YYYY-MM-DD).")
    parser.add_argument("--until", type=parse_date, help="Only games before this date (YYYY-MM-DD).")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD, got {value!r}.") from None


def find_accounts(riot_ids):
    accounts = []

    for riot_id in riot_ids:
        game_name, separator, tag_line = riot_id.rpartition("#")

        if not separator:
            raise CommandError(f"Expected NAME#TAG, got {riot_id!r}.")

        account = RiotAccount.query.filter(
            db.func.lower(RiotAccount.game_name) == game_name.strip().lower(),
            db.func.lower(RiotAccount.tag_line) == tag_line.strip().lower(),
        ).one_or_none()

        if account is None:
            raise CommandError(f"No Riot account {riot_id!r} in League Mastery Tracker.")

        accounts.append(account)

    return accounts


def find_persons(names):
    persons = []

    for name in names:
        person = Person.query.filter(
            db.func.lower(Person.display_name) == name.strip().lower()
        ).first()

        if person is None:
            raise CommandError(f"No Person named {name!r}.")

        persons.append(person)

    return persons


def find_champion_id(name):
    champion = Champion.query.filter(
        db.func.lower(Champion.name) == name.strip().lower()
    ).one_or_none()

    if champion is None:
        raise CommandError(f"No champion named {name!r}.")

    return champion.riot_champion_id


def run_import(arguments, log, riot_service, read_key, instance_service):
    if not instance_service.acquire():
        raise CommandError(
            "League Mastery Tracker is running. Close it before importing, "
            "so only one program writes to its database."
        )

    try:
        if arguments.ask_key:
            api_key = read_key("Riot API key (input hidden): ").strip()

            if not api_key:
                raise CommandError("A Riot API key is required.")

            riot_service = KeyOverrideRiotService(api_key)

        elif riot_service is None and os.environ.get("RIOT_API_KEY", "").strip():
            riot_service = KeyOverrideRiotService(os.environ["RIOT_API_KEY"].strip())

        accounts = find_accounts(arguments.account) or RiotAccount.query.order_by(RiotAccount.id).all()

        if not accounts:
            raise CommandError("No Riot accounts to import. Add accounts in League Mastery Tracker first.")

        service = MatchImportService(riot_service=riot_service)

        if arguments.queue:
            queue_ids, match_types = tuple(arguments.queue), ()
        else:
            queue_ids = MatchImportService.DEFAULT_QUEUE_IDS
            match_types = MatchImportService.DEFAULT_MATCH_TYPES

        failed = False

        for account in accounts:
            label = f"{account.game_name}#{account.tag_line}"
            log(f"{label}: checking for new games")

            def progress(done, total, label=label):
                if done == 1:
                    minutes = max(1, round(total * SECONDS_PER_GAME / 60))
                    log(f"{label}: downloading {total} games (about {minutes} min)")

                if done % 25 == 0 or done == total:
                    log(f"{label}: {done}/{total}")

            try:
                result = service.import_account(
                    account.id,
                    max_new_matches=arguments.max_games,
                    queue_ids=queue_ids,
                    match_types=match_types,
                    progress=progress,
                )
            except MatchImportError as error:
                log(f"{label}: stopped. {error}")
                failed = True

                if error.key_rejected:
                    break

                continue

            log(describe_import_result(label, result))

        return 1 if failed else 0

    finally:
        instance_service.release()


def describe_import_result(label, result):
    parts = [f"{result['imported']} new games"]

    if result["linked_existing"]:
        parts.append(f"{result['linked_existing']} linked from games already stored")

    if result["unavailable"]:
        parts.append(f"{result['unavailable']} no longer available")

    text = f"{label}: {', '.join(parts)}."

    if result["puuid_refreshed"]:
        text += " The account's PUUID was refreshed for the current API key."

    if result["remaining"]:
        text += f" {result['remaining']} older games remain; run the import again to continue."
    elif result["history_complete"]:
        text += " History is complete."

    return text


def run_stats(arguments, log):
    service = MatchStatisticsService()

    try:
        queue_ids = tuple(
            dict.fromkeys(
                [queue_id_for_mode(mode) for mode in arguments.mode]
                + list(arguments.queue)
            )
        )
        available_patches = service.available_patches()
        patches = parse_patch_selection(arguments.patch, available_patches)
    except ValueError as error:
        raise CommandError(str(error)) from None

    if arguments.patch and not set(patches) & set(available_patches):
        stored = ", ".join(display_patch(patch) for patch in available_patches[:8]) or "none"
        raise CommandError(
            f"No stored games are on the selected patches. Newest stored patches: {stored}."
        )

    filters = MatchStatisticsFilter(
        person_ids=tuple(person.id for person in find_persons(arguments.person)),
        riot_account_ids=tuple(account.id for account in find_accounts(arguments.account)),
        queue_ids=queue_ids,
        patches=patches,
        start=arguments.since,
        end=arguments.until,
        team_position=POSITIONS.get(arguments.position) if arguments.position else None,
        riot_champion_id=find_champion_id(arguments.champion) if arguments.champion else None,
        min_games=max(1, arguments.min_games),
        include_remakes=arguments.include_remakes,
    )

    if arguments.view == "summary":
        log(format_summary(service.summary(filters)))
        return 0

    method_name, label_columns, keyword_arguments = VIEWS[arguments.view]
    rows = getattr(service, method_name)(filters, **keyword_arguments)
    log(format_table(rows[:max(0, arguments.limit)], label_columns))

    if len(rows) > arguments.limit:
        log(f"{len(rows) - arguments.limit} more rows; use --limit to show them.")

    return 0


def format_summary(summary):
    if not summary["games"]:
        return "No stored games match. Run: python match_history.py import"

    lines = [
        f"Games: {summary['games']}",
        f"From {summary['first_game']:%Y-%m-%d} to {summary['last_game']:%Y-%m-%d}",
    ]

    lines.append("By mode:")

    for queue_id, games in summary["games_per_queue"].items():
        lines.append(f"  {queue_label(queue_id):<17} {games:>6}")

    lines.append("By patch:")

    for patch, games in summary["games_per_patch"].items():
        lines.append(f"  {display_patch(patch):<17} {games:>6}")

    return "\n".join(lines)


def format_table(rows, label_columns):
    if not rows:
        return "No results. Try a lower --min-games or fewer filters."

    def label(row, column):
        if column == "champion":
            return row["champion_name"] or f"Champion {row['riot_champion_id']}"

        if column == "patch":
            return display_patch(row["patch"])

        if column == "team_position":
            return position_label(row["team_position"])

        return str(row[column])

    titles = [COLUMN_TITLES[column] for column in label_columns]
    table = [
        [label(row, column) for column in label_columns]
        + [
            str(row["games"]),
            f"{row['wins']}-{row['losses']}",
            f"{row['win_rate']:.0%}",
            f"{row['wilson_lower'] * 100:.0f}",
        ]
        for row in rows
    ]
    header = titles + ["Games", "W-L", "Win%", "Score"]
    widths = [max(len(cells[index]) for cells in [header, *table]) for index in range(len(header))]
    label_count = len(label_columns)

    def line(cells):
        return "  ".join(
            cell.ljust(width) if index < label_count else cell.rjust(width)
            for index, (cell, width) in enumerate(zip(cells, widths))
        )

    output = [line(header), line(["-" * width for width in widths])]
    output += [line(cells) for cells in table]
    output.append("Score: lower bound of the 95% confidence interval for the win rate; sorts by reliability.")

    return "\n".join(output)


def build_game_selection(arguments):
    try:
        queue_ids = tuple(queue_id_for_mode(mode) for mode in arguments.mode)
    except ValueError as error:
        raise CommandError(str(error)) from None

    together_with = None

    if arguments.together_with:
        together_with = find_accounts([arguments.together_with])[0].id

    return GameSelection(
        riot_match_ids=tuple(match_id.strip().upper() for match_id in arguments.match),
        together_with_account_id=together_with,
        riot_champion_id=find_champion_id(arguments.champion) if arguments.champion else None,
        queue_ids=queue_ids,
        start=arguments.since,
        end=arguments.until,
    )


def run_games(arguments, log):
    account = find_accounts([arguments.account])[0]
    games = MatchAssignmentService().list_games(
        account.id,
        build_game_selection(arguments),
        limit=max(0, arguments.limit),
    )

    if not games:
        log("No stored games match. Run the import first, or loosen the filters.")
        return 0

    header = ["Match", "Date", "Mode", "Patch", "Champion", "Position", "Result", "Played by", "With"]
    table = [
        [
            game["riot_match_id"],
            f"{game['game_creation']:%Y-%m-%d %H:%M}",
            queue_label(game["queue_id"]),
            display_patch(game["patch"]),
            game["champion_name"] or f"Champion {game['riot_champion_id']}",
            position_label(game["team_position"]),
            "Win" if game["win"] else "Loss",
            "(ignored)" if game["ignored"] else game["played_by"] + (" *" if game["assigned"] else ""),
            ", ".join(game["with_accounts"]) or "-",
        ]
        for game in games
    ]
    widths = [max(len(row[index]) for row in [header, *table]) for index in range(len(header))]

    for row in [header, ["-" * width for width in widths], *table]:
        log("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())

    log("* assigned to someone other than the account's owner (UTC times).")
    return 0


def run_assign(arguments, log, instance_service):
    if not instance_service.acquire():
        raise CommandError(
            "League Mastery Tracker is running. Close it before assigning games, "
            "so only one program writes to its database."
        )

    try:
        account = find_accounts([arguments.account])[0]
        label = f"{account.game_name}#{account.tag_line}"

        if arguments.ignore or arguments.restore:
            try:
                changed = MatchAssignmentService().set_ignored(
                    account.id,
                    arguments.ignore,
                    build_game_selection(arguments),
                    all_games=arguments.all_games,
                )
            except ValueError as error:
                raise CommandError(str(error)) from None

            state = "ignored" if arguments.ignore else "counted again"
            log(f"{changed} games on {label} are now {state}.")
            return 0

        person = None if arguments.to_owner else find_persons([arguments.person])[0]

        try:
            changed = MatchAssignmentService().assign(
                account.id,
                person.id if person else None,
                build_game_selection(arguments),
                all_games=arguments.all_games,
            )
        except ValueError as error:
            raise CommandError(str(error)) from None

        who = person.display_name if person and person.id != account.person_id else f"{account.person.display_name} (the owner)"
        log(f"{changed} games on {account.game_name}#{account.tag_line} now count for {who}.")
        return 0

    finally:
        instance_service.release()


def main(
    argv=None,
    app=None,
    riot_service=None,
    stdout=None,
    read_key=getpass.getpass,
    instance_service=None,
):
    stdout = stdout or sys.stdout
    arguments = build_argument_parser().parse_args(argv)

    def log(message):
        print(message, file=stdout, flush=True)

    if app is None:
        from application.app import create_app

        app = create_app()

    with app.app_context():
        try:
            if arguments.command == "import":
                return run_import(
                    arguments,
                    log,
                    riot_service,
                    read_key,
                    instance_service or ApplicationInstanceService(),
                )

            if arguments.command == "games":
                return run_games(arguments, log)

            if arguments.command == "assign":
                return run_assign(
                    arguments,
                    log,
                    instance_service or ApplicationInstanceService(),
                )

            return run_stats(arguments, log)

        except CommandError as error:
            log(f"Error: {error}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
