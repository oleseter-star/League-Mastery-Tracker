import hashlib
import io
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlparse

import probe_match_history as probe


API_KEY = "RGAPI-synthetic-probe-key"

# A ranked queue the app does not name.
UNNAMED_RANKED_QUEUE = 4242
RANKED_QUEUE_IDS = {420, 440, UNNAMED_RANKED_QUEUE}


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        return self.payload


class FakeRiot:
    """Serves Account-V1 and Match-V5 responses from in-memory data."""

    def __init__(self, accounts, matches):
        self.accounts = accounts
        self.matches = matches
        self.requests = []
        self.queued_responses = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append((url, dict(params or {}), dict(headers or {})))

        if self.queued_responses:
            return self.queued_responses.pop(0)

        path = unquote(urlparse(url).path)

        if "/riot/account/v1/accounts/by-riot-id/" in path:
            game_name, tag_line = path.rsplit("/", 2)[-2:]
            puuid = self.accounts.get((game_name, tag_line))

            if puuid is None:
                return FakeResponse(404)

            return FakeResponse(200, {"puuid": puuid, "gameName": game_name, "tagLine": tag_line})

        if path.endswith("/ids"):
            puuid = path.split("/by-puuid/")[1].split("/")[0]
            queue = params.get("queue")
            ranked_only = params.get("type") == "ranked"
            ids = [
                match["metadata"]["matchId"]
                for match in self._newest_first()
                if puuid in match["metadata"]["participants"]
                and (queue is None or match["info"]["queueId"] == queue)
                and (not ranked_only or match["info"]["queueId"] in RANKED_QUEUE_IDS)
            ]
            start = params["start"]
            return FakeResponse(200, ids[start:start + params["count"]])

        match_id = path.rsplit("/", 1)[-1]
        match = next((m for m in self.matches if m["metadata"]["matchId"] == match_id), None)
        return FakeResponse(200, match) if match else FakeResponse(404)

    def _newest_first(self):
        return sorted(self.matches, key=lambda match: -match["info"]["gameCreation"])


class NoWait:
    def wait(self):
        pass


def build_match(number, queue_id, created_ms, players):
    """players: (puuid, championName, teamPosition, win) tuples."""

    return {
        "metadata": {
            "matchId": f"EUW1_{number}",
            "participants": [puuid for puuid, *_ in players],
        },
        "info": {
            "queueId": queue_id,
            "gameCreation": created_ms,
            "gameVersion": "16.18.712.3456",
            "participants": [
                {
                    "puuid": puuid,
                    "championName": champion,
                    "championId": index + 1,
                    "teamPosition": position,
                    "win": win,
                }
                for index, (puuid, champion, position, win) in enumerate(players)
            ],
        },
    }


DAY_MS = 86_400_000
JAN_2025_MS = 1_735_689_600_000


def build_world():
    matches = [
        # Main and Friend together in ranked, three times.
        build_match(1, 420, JAN_2025_MS, [("p-main", "Lux", "MIDDLE", True), ("p-friend", "Twitch", "BOTTOM", True)]),
        build_match(2, 420, JAN_2025_MS + DAY_MS, [("p-main", "Lux", "MIDDLE", False), ("p-friend", "Zac", "JUNGLE", False)]),
        build_match(3, 400, JAN_2025_MS + 2 * DAY_MS, [("p-main", "Twitch", "BOTTOM", True), ("p-friend", "Lux", "UTILITY", True)]),
        # Main alone in ARAM, which has no positions.
        build_match(4, 450, JAN_2025_MS + 3 * DAY_MS, [("p-main", "Lux", "", True), ("p-other", "Zed", "", False)]),
        # Alt alone in a League Classic style queue.
        build_match(5, 2400, JAN_2025_MS + 4 * DAY_MS, [("p-alt", "Lux", "MIDDLE", False)]),
        # Alt in a ranked queue the app does not name yet.
        build_match(6, UNNAMED_RANKED_QUEUE, JAN_2025_MS + 5 * DAY_MS, [("p-alt", "Lux", "MIDDLE", True)]),
    ]
    accounts = {("Main", "EUW"): "p-main", ("Alt", "EUW"): "p-alt", ("Friend", "EUW"): "p-friend"}
    return FakeRiot(accounts, matches)


def create_database(path, rows):
    """rows: (person, game_name, tag_line, platform, puuid)."""

    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE persons (id INTEGER PRIMARY KEY, display_name TEXT)")
    connection.execute(
        "CREATE TABLE riot_accounts (id INTEGER PRIMARY KEY, person_id INTEGER, "
        "game_name TEXT, tag_line TEXT, puuid TEXT, platform_region TEXT, last_sync TEXT)"
    )
    person_ids = {}

    for person, game_name, tag_line, platform, puuid in rows:
        if person not in person_ids:
            person_ids[person] = connection.execute(
                "INSERT INTO persons (display_name) VALUES (?)", (person,)
            ).lastrowid

        connection.execute(
            "INSERT INTO riot_accounts (person_id, game_name, tag_line, puuid, platform_region) "
            "VALUES (?, ?, ?, ?, ?)",
            (person_ids[person], game_name, tag_line, puuid, platform),
        )

    connection.commit()
    connection.close()


class ParseRiotIdTests(unittest.TestCase):
    def test_full_argument_with_person_and_platform(self):
        account = probe.parse_riot_id_argument("Ole = Some Name#EUW @ na1")

        self.assertEqual(account["person"], "Ole")
        self.assertEqual(account["game_name"], "Some Name")
        self.assertEqual(account["tag_line"], "EUW")
        self.assertEqual(account["platform"], "NA1")

    def test_defaults_person_to_riot_id_and_platform_to_default(self):
        account = probe.parse_riot_id_argument("Friend#EUW", default_platform="EUW1")

        self.assertEqual(account["person"], "Friend#EUW")
        self.assertEqual(account["platform"], "EUW1")

    def test_rejects_missing_tag_and_unknown_platform(self):
        for value in ("NoTag", "Name#", "#TAG", "Name#TAG@MOON1"):
            with self.assertRaises(ValueError, msg=value):
                probe.parse_riot_id_argument(value)

    def test_account_route_has_no_sea_but_match_route_does(self):
        self.assertEqual(probe.account_region("OC1"), "asia")
        self.assertEqual(probe.match_region("OC1"), "sea")
        self.assertEqual(probe.account_region("EUW1"), "europe")


class RateLimiterTests(unittest.TestCase):
    def test_waits_until_the_oldest_request_leaves_the_window(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        limiter = probe.RateLimiter(limits=((2, 1.0),), clock=lambda: now[0], sleep=sleep)

        limiter.wait()
        now[0] = 0.25
        limiter.wait()
        limiter.wait()

        self.assertEqual(sleeps, [0.75])

    def test_every_limit_is_respected(self):
        now = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        limiter = probe.RateLimiter(limits=((5, 1.0), (3, 10.0)), clock=lambda: now[0], sleep=sleep)

        for _ in range(4):
            limiter.wait()

        self.assertEqual(sleeps, [10.0])


class RiotClientTests(unittest.TestCase):
    def setUp(self):
        self.riot = build_world()
        self.sleeps = []
        self.client = probe.RiotClient(
            API_KEY, session=self.riot, rate_limiter=NoWait(), sleep=self.sleeps.append
        )

    def test_rate_limited_response_is_retried_after_retry_after(self):
        self.riot.queued_responses = [
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(200, ["EUW1_1"]),
        ]

        self.assertEqual(self.client.get_json("https://europe.api.riotgames.com/x"), ["EUW1_1"])
        self.assertEqual(self.sleeps, [7])
        self.assertEqual(self.client.request_count, 2)

    def test_rejected_key_stops_with_expiry_hint_and_without_the_key(self):
        self.riot.queued_responses = [FakeResponse(403)]

        with self.assertRaises(probe.ProbeError) as raised:
            self.client.get_json("https://europe.api.riotgames.com/x")

        self.assertIn("expire", str(raised.exception))
        self.assertNotIn(API_KEY, str(raised.exception))

    def test_not_found_returns_none(self):
        self.riot.queued_responses = [FakeResponse(404)]

        self.assertIsNone(self.client.get_json("https://europe.api.riotgames.com/x"))

    def test_key_is_sent_as_header_only(self):
        self.client.get_json("https://europe.api.riotgames.com/x", params={"start": 0})
        url, params, headers = self.riot.requests[0]

        self.assertEqual(headers["X-Riot-Token"], API_KEY)
        self.assertNotIn(API_KEY, url)
        self.assertNotIn(API_KEY, json.dumps(params))


class ListMatchIdsTests(unittest.TestCase):
    def test_pages_until_a_short_page_and_respects_the_maximum(self):
        riot = FakeRiot({}, [build_match(n, 420, JAN_2025_MS + n, [("p", "Lux", "MIDDLE", True)]) for n in range(250)])
        client = probe.RiotClient(API_KEY, session=riot, rate_limiter=NoWait())

        everything = probe.list_match_ids(client, "europe", "p", max_ids=1000)
        capped = probe.list_match_ids(client, "europe", "p", max_ids=150)

        self.assertEqual(len(everything), 250)
        self.assertEqual(everything[0], "EUW1_249")
        self.assertEqual(len(capped), 150)
        self.assertEqual([params["count"] for _, params, _ in riot.requests], [100, 100, 100, 100, 50])


class ProbeRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "league_mastery_tracker.db"
        self.output = self.root / "probe-output"
        create_database(
            self.database,
            [
                ("Ole", "Main", "EUW", "EUW1", "p-main"),
                ("Ole", "Alt", "EUW", "EUW1", "p-alt-from-another-key"),
                ("Friend", "Friend", "EUW", "EUW1", "p-friend"),
                ("Friend", "Gone", "EUW", "EUW1", "p-gone"),
            ],
        )
        self.riot = build_world()
        self.stdout = io.StringIO()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_probe(self, *extra_arguments):
        return probe.main(
            argv=["--database", str(self.database), "--output", str(self.output), "--details", "5", *extra_arguments],
            session=self.riot,
            environment={"RIOT_API_KEY": API_KEY},
            read_key=lambda prompt: self.fail("the key must come from RIOT_API_KEY"),
            stdout=self.stdout,
            rate_limiter=NoWait(),
        )

    def summary(self):
        return json.loads((self.output / "summary.json").read_text(encoding="utf-8"))

    def test_probe_reports_history_queues_and_sample_per_account(self):
        self.assertEqual(self.run_probe(), 0)
        accounts = {result["riot_id"]: result for result in self.summary()["accounts"]}
        main = accounts["Main#EUW"]

        self.assertEqual(main["match_ids"], 4)
        self.assertFalse(main["capped"])
        self.assertEqual(main["oldest_game"], "2025-01-01")
        self.assertEqual(main["newest_game"], "2025-01-04")
        self.assertEqual(main["queues"]["Ranked Solo/Duo"], {"games": 2, "capped": False, "oldest_game": "2025-01-01"})
        self.assertEqual(main["ranked_games"], 2)
        self.assertEqual(main["games_not_imported"], 2)
        self.assertEqual(main["other_ranked"], {"games": 0, "sampled_queue_ids": {}})
        self.assertEqual(main["sample"]["champions"], {"Lux": 3, "Twitch": 1})
        self.assertEqual(main["sample"]["patches"], {"26.18": 4})
        self.assertEqual(main["sample"]["positions"]["(none)"], 1)
        self.assertEqual(main["sample"]["position_coverage"]["Queue 450"], "0/2")
        self.assertEqual(accounts["Alt#EUW"]["sample"]["queues"], {"Queue 4242": 1, "Queue 2400": 1})
        self.assertEqual(accounts["Alt#EUW"]["games_not_imported"], 1)
        self.assertEqual(accounts["Gone#EUW"]["status"], "not_found")

    def test_probe_finds_the_queue_id_of_other_ranked_games(self):
        self.run_probe()
        accounts = {result["riot_id"]: result for result in self.summary()["accounts"]}

        self.assertEqual(accounts["Alt#EUW"]["ranked_games"], 1)
        self.assertEqual(accounts["Alt#EUW"]["other_ranked"], {"games": 1, "sampled_queue_ids": {"4242": 1}})
        self.assertIn(
            "Other ranked games: 1 (queue ID 4242; a ranked queue League Mastery Tracker does not name yet)",
            (self.output / "report.txt").read_text(encoding="utf-8"),
        )

    def test_probe_groups_accounts_by_person_and_counts_shared_games(self):
        self.run_probe()
        summary = self.summary()
        together = {frozenset(pair["accounts"]): pair for pair in summary["games_together"]}
        main_and_friend = together[frozenset({"Main#EUW", "Friend#EUW"})]
        main_and_alt = together[frozenset({"Main#EUW", "Alt#EUW"})]

        self.assertEqual(summary["games_per_person"], {"Friend": 3, "Ole": 6})
        self.assertEqual(main_and_friend["games"], 3)
        self.assertFalse(main_and_friend["same_person"])
        self.assertTrue(main_and_alt["same_person"])
        self.assertEqual(main_and_alt["games"], 0)

    def test_probe_reports_whether_stored_puuids_still_match(self):
        self.run_probe()
        accounts = {result["riot_id"]: result for result in self.summary()["accounts"]}

        self.assertTrue(accounts["Main#EUW"]["stored_puuid_matches"])
        self.assertFalse(accounts["Alt#EUW"]["stored_puuid_matches"])
        self.assertIn("NO, the stored PUUID differs", (self.output / "report.txt").read_text(encoding="utf-8"))

    def test_probe_saves_each_match_once_and_never_writes_the_key(self):
        self.run_probe()
        match_files = sorted(path.name for path in (self.output / "matches").iterdir())

        self.assertEqual(match_files, [f"EUW1_{n}.json" for n in range(1, 7)])

        match_requests = [url for url, _, _ in self.riot.requests if "/matches/EUW1_" in url]
        self.assertEqual(len(match_requests), len(set(match_requests)))

        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(API_KEY, path.read_text(encoding="utf-8"), path.name)

        self.assertNotIn(API_KEY, self.stdout.getvalue())

    def test_application_database_is_not_modified(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()

        self.run_probe()

        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)

    def test_riot_id_arguments_replace_the_database(self):
        self.assertEqual(
            probe.main(
                argv=["--riot-id", "Me=Main#EUW", "--output", str(self.output), "--details", "1"],
                session=self.riot,
                environment={"RIOT_API_KEY": API_KEY},
                stdout=self.stdout,
                rate_limiter=NoWait(),
            ),
            0,
        )

        self.assertEqual([result["person"] for result in self.summary()["accounts"]], ["Me"])
        self.assertIsNone(self.summary()["accounts"][0]["stored_puuid_matches"])

    def test_missing_database_and_rejected_key_fail_with_messages(self):
        missing = probe.main(
            argv=["--database", str(self.root / "missing.db")],
            environment={"RIOT_API_KEY": API_KEY},
            stdout=self.stdout,
        )
        self.riot.queued_responses = [FakeResponse(403)]
        rejected = self.run_probe()

        self.assertEqual((missing, rejected), (2, 1))
        self.assertIn("No application database found", self.stdout.getvalue())
        self.assertIn("Development keys expire", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
