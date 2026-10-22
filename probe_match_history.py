"""Probe Riot match history before building composition statistics.

The probe answers how much match data exists for the tracked accounts: how
far back history reaches, how many games each queue has, which fields a
match carries, and how often tracked accounts appear in the same game.

It never changes application data. Accounts come from the application
database, opened read-only, or from --riot-id arguments. Results go to a
separate output folder. The Riot API key is read from RIOT_API_KEY or a
hidden prompt and is never printed or written to disk.

    python probe_match_history.py
    python probe_match_history.py --riot-id "Ole=Name#TAG@EUW1" --riot-id "Friend#EUW"
"""

import argparse
import getpass
import itertools
import json
import os
import sqlite3
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from application.services.application_data_service import (
    ApplicationDataService,
)
from application.services.riot_service import RiotService


QUEUE_NAMES = {
    400: "Normal Draft",
    420: "Ranked Solo/Duo",
    430: "Normal Blind",
    440: "Ranked Flex",
    450: "ARAM",
    490: "Quickplay",
}

MATCH_ID_PAGE_SIZE = 100
DEFAULT_MAX_MATCH_IDS = 2000
DEFAULT_DETAIL_COUNT = 20
DEFAULT_PLATFORM = "EUW1"

# Kept below the development-key limits of 20 per second and 100 per 2 minutes.
RATE_LIMITS = ((18, 1.0), (95, 120.0))


class ProbeError(RuntimeError):
    """A failure that stops the probe with a readable message."""


class RateLimiter:
    """Delay requests so every (count, window) limit is respected."""

    def __init__(self, limits=RATE_LIMITS, clock=time.monotonic, sleep=time.sleep):
        self.limits = limits
        self.clock = clock
        self.sleep = sleep
        self.history = deque()
        self.longest_window = max(window for _, window in limits)

    def wait(self):
        while True:
            now = self.clock()

            while self.history and now - self.history[0] >= self.longest_window:
                self.history.popleft()

            delay = 0.0

            for count, window in self.limits:
                recent = [moment for moment in self.history if now - moment < window]

                if len(recent) >= count:
                    delay = max(delay, window - (now - recent[-count]))

            if delay <= 0:
                self.history.append(now)
                return

            self.sleep(delay)


class RiotClient:
    """Minimal rate-limited Riot API client for the probe."""

    def __init__(
        self,
        api_key,
        session=None,
        rate_limiter=None,
        sleep=time.sleep,
        timeout_seconds=15,
        max_attempts=5,
    ):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.sleep = sleep
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.request_count = 0

    def get_json(self, url, params=None, description="Riot data"):
        """Return decoded JSON, or None when Riot reports 404."""

        for attempt in range(1, self.max_attempts + 1):
            self.rate_limiter.wait()
            self.request_count += 1

            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={
                        "X-Riot-Token": self.api_key,
                        "Accept": "application/json",
                    },
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as error:
                if attempt == self.max_attempts:
                    raise ProbeError(
                        f"Network error while requesting {description}: "
                        f"{type(error).__name__}."
                    ) from None

                self.sleep(2 ** attempt)
                continue

            status = response.status_code

            if status == 200:
                return response.json()

            if status == 404:
                return None

            if status in (401, 403):
                raise ProbeError(
                    f"Riot rejected the API key (HTTP {status}). Development "
                    "keys expire after 24 hours; generate a new key and retry."
                )

            if status == 429:
                self.sleep(_retry_after_seconds(response))
                continue

            if status >= 500 and attempt < self.max_attempts:
                self.sleep(2 ** attempt)
                continue

            raise ProbeError(
                f"Riot returned HTTP {status} while requesting {description}."
            )

        raise ProbeError(
            f"Riot did not answer the request for {description} after "
            f"{self.max_attempts} attempts."
        )


def _retry_after_seconds(response):
    try:
        return max(1, int(response.headers.get("Retry-After", "10")))
    except ValueError:
        return 10


def account_region(platform):
    """Return the Account-V1 route; Account-V1 has no "sea" route."""

    region = RiotService.get_regional_route(platform)
    return "asia" if region == "sea" else region


def match_region(platform):
    """Return the Match-V5 route for a platform."""

    return RiotService.get_regional_route(platform)


def parse_riot_id_argument(value, default_platform=DEFAULT_PLATFORM):
    """Parse "[Person=]GameName#TAG[@PLATFORM]" into an account record."""

    text = value.strip()
    person = None

    if "=" in text:
        person, text = (part.strip() for part in text.split("=", 1))

    platform = default_platform

    if "@" in text:
        text, platform = (part.strip() for part in text.rsplit("@", 1))

    if "#" not in text:
        raise ValueError(f"Expected GameName#TAG, got {value!r}.")

    game_name, tag_line = (part.strip() for part in text.rsplit("#", 1))

    if not game_name or not tag_line:
        raise ValueError(f"Expected GameName#TAG, got {value!r}.")

    return {
        "person": person or f"{game_name}#{tag_line}",
        "game_name": game_name,
        "tag_line": tag_line,
        "platform": RiotService.normalize_platform_region(platform),
        "stored_puuid": None,
    }


def default_database_path(environment=None):
    data_directory = ApplicationDataService.get_data_directory(
        project_root=Path(__file__).resolve().parent,
        environment=environment,
    )
    return data_directory / "database" / "league_mastery_tracker.db"


def read_accounts_from_database(database_path):
    """Read Persons and their Riot accounts without allowing writes."""

    database_path = Path(database_path).resolve()

    if not database_path.is_file():
        raise ProbeError(f"No application database found at {database_path}.")

    connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)

    try:
        rows = connection.execute(
            "SELECT persons.display_name, riot_accounts.game_name, "
            "riot_accounts.tag_line, riot_accounts.platform_region, "
            "riot_accounts.puuid "
            "FROM riot_accounts JOIN persons "
            "ON persons.id = riot_accounts.person_id "
            "ORDER BY persons.display_name, riot_accounts.game_name, "
            "riot_accounts.tag_line"
        ).fetchall()
    finally:
        connection.close()

    return [
        {
            "person": display_name,
            "game_name": game_name,
            "tag_line": tag_line,
            "platform": RiotService.normalize_platform_region(platform),
            "stored_puuid": puuid,
        }
        for display_name, game_name, tag_line, platform, puuid in rows
    ]


def list_match_ids(client, region, puuid, max_ids, queue=None):
    """Return match IDs newest first, following pages up to max_ids."""

    match_ids = []

    while len(match_ids) < max_ids:
        count = min(MATCH_ID_PAGE_SIZE, max_ids - len(match_ids))
        params = {"start": len(match_ids), "count": count}

        if queue is not None:
            params["queue"] = queue

        page = client.get_json(
            f"https://{region}.api.riotgames.com/lol/match/v5/matches/"
            f"by-puuid/{puuid}/ids",
            params=params,
            description="match IDs",
        ) or []

        match_ids.extend(page)

        if len(page) < count:
            break

    return match_ids


def fetch_match(client, region, match_id, match_cache):
    if match_id not in match_cache:
        match_cache[match_id] = client.get_json(
            f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}",
            description=f"match {match_id}",
        )

    return match_cache[match_id]


def game_date(match):
    if not match:
        return None

    created = match.get("info", {}).get("gameCreation")

    if not created:
        return None

    return datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()


def queue_label(queue_id):
    return QUEUE_NAMES.get(queue_id, f"queue {queue_id}")


def summarize_sample(matches, puuid):
    """Describe the tracked Riot account's games in a sample of match details."""

    queues = Counter()
    positions = Counter()
    champions = Counter()
    wins = 0
    games = 0
    position_coverage = {}

    for match in matches:
        info = (match or {}).get("info", {})
        participants = info.get("participants", [])
        tracked_participant = next((p for p in participants if p.get("puuid") == puuid), None)

        if tracked_participant is None:
            continue

        games += 1
        queue = queue_label(info.get("queueId"))
        queues[queue] += 1
        positions[tracked_participant.get("teamPosition") or "(none)"] += 1
        champions[tracked_participant.get("championName") or str(tracked_participant.get("championId"))] += 1
        wins += bool(tracked_participant.get("win"))

        with_position = sum(1 for p in participants if p.get("teamPosition"))
        covered, total = position_coverage.get(queue, (0, 0))
        position_coverage[queue] = (
            covered + with_position,
            total + len(participants),
        )

    return {
        "games": games,
        "wins": wins,
        "queues": dict(queues.most_common()),
        "positions": dict(positions.most_common()),
        "champions": dict(champions.most_common()),
        "position_coverage": {
            queue: f"{covered}/{total}"
            for queue, (covered, total) in position_coverage.items()
        },
    }


def probe_account(client, account, max_match_ids, detail_count, match_cache, log):
    label = f"{account['game_name']}#{account['tag_line']} ({account['platform']})"
    result = {
        "person": account["person"],
        "riot_id": f"{account['game_name']}#{account['tag_line']}",
        "platform": account["platform"],
    }

    log(f"{label}: resolving account")
    account_data = client.get_json(
        f"https://{account_region(account['platform'])}.api.riotgames.com"
        f"/riot/account/v1/accounts/by-riot-id/"
        f"{quote(account['game_name'], safe='')}/{quote(account['tag_line'], safe='')}",
        description="account",
    )

    if not account_data or not account_data.get("puuid"):
        result["status"] = "not_found"
        log(f"{label}: Riot ID not found")
        return result, []

    puuid = account_data["puuid"]
    result["status"] = "found"
    result["stored_puuid_matches"] = (
        None if account["stored_puuid"] is None
        else account["stored_puuid"] == puuid
    )

    region = match_region(account["platform"])

    log(f"{label}: listing match IDs (up to {max_match_ids})")
    all_ids = list_match_ids(client, region, puuid, max_match_ids)
    result["match_ids"] = len(all_ids)
    result["capped"] = len(all_ids) >= max_match_ids

    queue_ids = {}

    for queue in QUEUE_NAMES:
        log(f"{label}: listing {QUEUE_NAMES[queue]} match IDs")
        queue_ids[queue] = list_match_ids(client, region, puuid, max_match_ids, queue)

    recent_ids = all_ids[:detail_count]
    log(f"{label}: fetching {len(recent_ids)} recent matches and the oldest of each queue")
    recent_matches = [fetch_match(client, region, match_id, match_cache) for match_id in recent_ids]

    newest = recent_matches[0] if recent_matches else None
    oldest = fetch_match(client, region, all_ids[-1], match_cache) if all_ids else None
    result["newest_game"] = game_date(newest)
    result["oldest_game"] = game_date(oldest)

    result["queues"] = {}

    for queue, ids in queue_ids.items():
        oldest_in_queue = fetch_match(client, region, ids[-1], match_cache) if ids else None
        result["queues"][QUEUE_NAMES[queue]] = {
            "games": len(ids),
            "capped": len(ids) >= max_match_ids,
            "oldest_game": game_date(oldest_in_queue),
        }

    if not result["capped"]:
        result["other_queue_games"] = len(all_ids) - sum(len(ids) for ids in queue_ids.values())

    result["sample"] = summarize_sample(recent_matches, puuid)

    return result, all_ids


def games_together(account_results, match_ids_by_account):
    """Count matches shared by every pair of found accounts."""

    pairs = []
    found = [r for r in account_results if r.get("status") == "found"]

    for first, second in itertools.combinations(found, 2):
        shared = (
            set(match_ids_by_account[first["riot_id"]])
            & set(match_ids_by_account[second["riot_id"]])
        )
        pairs.append({
            "accounts": [first["riot_id"], second["riot_id"]],
            "same_person": first["person"] == second["person"],
            "games": len(shared),
        })

    return sorted(pairs, key=lambda pair: -pair["games"])


def games_per_person(account_results, match_ids_by_account):
    """Count distinct matches per Person across all of their accounts."""

    by_person = {}

    for result in account_results:
        if result.get("status") == "found":
            by_person.setdefault(result["person"], set()).update(
                match_ids_by_account[result["riot_id"]]
            )

    return {person: len(ids) for person, ids in sorted(by_person.items())}


def format_report(summary):
    lines = [
        f"Match history probe, {summary['generated_at']}",
        f"Requests sent: {summary['request_count']}",
        "",
    ]

    for result in summary["accounts"]:
        lines.append(f"{result['person']}: {result['riot_id']} ({result['platform']})")

        if result["status"] != "found":
            lines += ["  Riot ID not found.", ""]
            continue

        cap_note = "limit reached, history may go further back" if result["capped"] else "complete"
        lines.append(f"  Match IDs found: {result['match_ids']} ({cap_note})")
        lines.append(f"  Games from {result['oldest_game']} to {result['newest_game']}")
        lines.append("  By queue (games, oldest game):")

        for queue, details in result["queues"].items():
            lines.append(f"    {queue:<17} {details['games']:>6}  {details['oldest_game'] or '-'}")

        if "other_queue_games" in result:
            lines.append(f"    {'Other queues':<17} {result['other_queue_games']:>6}")

        sample = result["sample"]
        lines.append(f"  Recent sample: {sample['games']} games, {sample['wins']} wins")

        for title, key in (("Queues", "queues"), ("Positions", "positions"), ("Champions", "champions")):
            values = ", ".join(f"{name} {count}" for name, count in list(sample[key].items())[:8])
            lines.append(f"    {title}: {values or '-'}")

        coverage = ", ".join(f"{queue} {value}" for queue, value in sample["position_coverage"].items())
        lines.append(f"    Players with a position: {coverage or '-'}")

        if result["stored_puuid_matches"] is not None:
            answer = "yes" if result["stored_puuid_matches"] else "NO, the stored PUUID differs"
            lines.append(f"  Stored PUUID matches this key: {answer}")

        lines.append("")

    lines.append("Distinct games per person:")

    for person, count in summary["games_per_person"].items():
        lines.append(f"  {person}: {count}")

    lines += ["", "Games played together (tracked accounts in the same match):"]
    together = [pair for pair in summary["games_together"] if pair["games"]]

    for pair in together:
        note = " (same person)" if pair["same_person"] else ""
        lines.append(f"  {' + '.join(pair['accounts'])}: {pair['games']}{note}")

    if not together:
        lines.append("  none")

    return "\n".join(lines) + "\n"


def run_probe(client, accounts, max_match_ids, detail_count, output_directory, log):
    match_cache = {}
    account_results = []
    match_ids_by_account = {}

    for account in accounts:
        result, match_ids = probe_account(
            client, account, max_match_ids, detail_count, match_cache, log
        )
        account_results.append(result)
        match_ids_by_account[result["riot_id"]] = match_ids

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "request_count": client.request_count,
        "settings": {"max_match_ids": max_match_ids, "detail_count": detail_count},
        "accounts": account_results,
        "games_per_person": games_per_person(account_results, match_ids_by_account),
        "games_together": games_together(account_results, match_ids_by_account),
    }

    matches_directory = output_directory / "matches"
    matches_directory.mkdir(parents=True, exist_ok=True)

    for match_id, match in match_cache.items():
        if match is not None:
            (matches_directory / f"{match_id}.json").write_text(
                json.dumps(match, indent=2), encoding="utf-8"
            )

    report = format_report(summary)
    (output_directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_directory / "report.txt").write_text(report, encoding="utf-8")

    return summary, report


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description="Measure available Riot match history without changing application data."
    )
    parser.add_argument(
        "--riot-id",
        action="append",
        default=[],
        metavar="[PERSON=]NAME#TAG[@PLATFORM]",
        help="Account to probe; repeat for several. Without it, accounts are read from the app database.",
    )
    parser.add_argument("--database", help="Application database to read accounts from (opened read-only).")
    parser.add_argument("--platform", default=DEFAULT_PLATFORM, help="Platform for --riot-id values without @PLATFORM.")
    parser.add_argument("--max-match-ids", type=int, default=DEFAULT_MAX_MATCH_IDS, help="Most match IDs to list per account and queue.")
    parser.add_argument("--details", type=int, default=DEFAULT_DETAIL_COUNT, help="Recent matches to download per account.")
    parser.add_argument("--output", help="Folder for results (default: a new folder in your home directory).")
    return parser


def main(
    argv=None,
    session=None,
    environment=None,
    read_key=getpass.getpass,
    stdout=None,
    rate_limiter=None,
):
    stdout = stdout or sys.stdout
    environment = os.environ if environment is None else environment
    arguments = build_argument_parser().parse_args(argv)

    def log(message):
        print(message, file=stdout, flush=True)

    try:
        if arguments.riot_id:
            accounts = [parse_riot_id_argument(value, arguments.platform) for value in arguments.riot_id]
        else:
            database_path = arguments.database or default_database_path(environment)
            log(f"Reading accounts from {database_path} (read-only)")
            accounts = read_accounts_from_database(database_path)
    except (ValueError, ProbeError, sqlite3.Error) as error:
        log(f"Error: {error}")
        return 2

    if not accounts:
        log("No accounts to probe. Add accounts in the app or pass --riot-id.")
        return 2

    api_key = (environment.get("RIOT_API_KEY") or "").strip() or read_key("Riot API key (input hidden): ").strip()

    if not api_key:
        log("Error: a Riot API key is required.")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_directory = (
        Path(arguments.output) if arguments.output
        else Path.home() / "LeagueMasteryTracker-match-probe" / stamp
    ).resolve()

    log(
        f"Probing {len(accounts)} account(s). Development keys allow 100 requests "
        "per 2 minutes, so large histories take a few minutes per account."
    )

    try:
        summary, report = run_probe(
            RiotClient(api_key, session=session, rate_limiter=rate_limiter),
            accounts,
            arguments.max_match_ids,
            arguments.details,
            output_directory,
            log,
        )
    except ProbeError as error:
        log(f"Error: {error}")
        return 1

    log("")
    log(report)
    log(f"Results saved in {output_directory}")
    log("The match files include other players' Riot IDs; keep them private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
