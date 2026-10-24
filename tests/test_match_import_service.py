import unittest
from datetime import datetime
from unittest.mock import patch

import requests
from flask import Flask

from application.database.database import db
from application.database.models import (
    Match,
    MatchImportState,
    MatchParticipant,
    Person,
    RiotAccount,
)
from application.services.match_import_service import (
    MatchImportError,
    MatchImportService,
)
from application.services.riot_service import RiotService


JAN_2025_MS = 1_735_689_600_000
HOUR_MS = 3_600_000

# A ranked queue whose ID the app does not name, standing in for Ranked 5s.
UNNAMED_RANKED_QUEUE = 4242
RANKED_QUEUES = {420, 440, UNNAMED_RANKED_QUEUE}


class FakeHTTPResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def http_error(status_code):
    return requests.HTTPError(
        f"HTTP {status_code}",
        response=FakeHTTPResponse(status_code),
    )


class FakeRiotService:
    """
    Serves match history for named identities.

    PUUIDs depend on the API key project (key_era), as with Riot.
    """

    IDENTITIES = {
        "ole": ("Main", "EUW"),
        "alt": ("Alt", "EUW"),
        "friend": ("Friend", "EUW"),
        "stranger": ("Stranger", "EUW"),
    }

    def __init__(self):
        self.key_era = 1
        self.games = []
        self.gone = set()
        self.fail_on_match_call = None
        self.id_calls = []
        self.match_calls = []

    def puuid(self, identity):
        return f"{identity}-k{self.key_era}"

    def add_game(self, number, queue_id, players, legacy_duration=False, game_version="16.18.712.3456"):
        """players: (identity, champion_id, team_id, position, win)."""

        self.games.append({
            "id": f"EUW1_{number}",
            "number": number,
            "queue_id": queue_id,
            "match_type": "ranked" if queue_id in RANKED_QUEUES else "normal",
            "players": players,
            "legacy_duration": legacy_duration,
            "game_version": game_version,
        })

    def get_match_ids(self, puuid, platform_region, start=0, count=100, queue=None, match_type=None):
        self.id_calls.append((puuid, queue or match_type, start))
        identity = self._identity_for(puuid)

        ids = [
            game["id"]
            for game in sorted(self.games, key=lambda game: -game["number"])
            if any(entry[0] == identity for entry in game["players"])
            and (queue is None or game["queue_id"] == queue)
            and (match_type is None or game["match_type"] == match_type)
        ]

        return ids[start:start + count]

    def get_match(self, match_id, platform_region):
        self.match_calls.append(match_id)

        if self.fail_on_match_call == len(self.match_calls):
            raise http_error(503)

        if match_id in self.gone:
            return None

        game = next(game for game in self.games if game["id"] == match_id)
        created = JAN_2025_MS + game["number"] * HOUR_MS
        info = {
            "platformId": "EUW1",
            "queueId": game["queue_id"],
            "gameMode": "CLASSIC",
            "mapId": 11,
            "gameVersion": game["game_version"],
            "gameCreation": created,
            "gameDuration": 1_800_000 if game["legacy_duration"] else 1800,
            "participants": [
                {
                    "participantId": index + 1,
                    "puuid": self.puuid(identity),
                    "riotIdGameName": self.IDENTITIES[identity][0],
                    "riotIdTagline": self.IDENTITIES[identity][1],
                    "championId": champion_id,
                    "teamId": team_id,
                    "teamPosition": position,
                    "win": win,
                    "kills": 5,
                    "deaths": 2,
                    "assists": 7,
                }
                for index, (identity, champion_id, team_id, position, win) in enumerate(game["players"])
            ],
        }

        if not game["legacy_duration"]:
            info["gameEndTimestamp"] = created + 1_800_000

        return {"metadata": {"matchId": match_id}, "info": info}

    def get_account_by_riot_id(self, game_name, tag_line, platform_region):
        for identity, riot_id in self.IDENTITIES.items():
            if riot_id == (game_name, tag_line):
                return {"puuid": self.puuid(identity)}

        raise http_error(404)

    def _identity_for(self, puuid):
        identity, _, era = puuid.rpartition("-k")

        if era != str(self.key_era) or identity not in self.IDENTITIES:
            raise http_error(400)

        return identity


def ranked_game(number, *players):
    return number, 420, list(players)


class MatchImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.riot = FakeRiotService()
        ole = Person(display_name="Ole")
        friend = Person(display_name="Friend")
        self.main = RiotAccount(person=ole, game_name="Main", tag_line="EUW", puuid="ole-k1", platform_region="EUW1")
        self.alt = RiotAccount(person=ole, game_name="Alt", tag_line="EUW", puuid="alt-k1", platform_region="EUW1")
        self.friend = RiotAccount(person=friend, game_name="Friend", tag_line="EUW", puuid="friend-k1", platform_region="EUW1")
        db.session.add_all([ole, friend])
        db.session.commit()

        self.now = datetime(2026, 10, 22, 12, 0)
        self.service = MatchImportService(riot_service=self.riot, clock=lambda: self.now)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def add_default_games(self):
        # Main and Friend together twice (Solo/Duo, Flex), Main alone in
        # Clash, Friend alone in Solo/Duo.
        self.riot.add_game(1, 420, [("ole", 99, 100, "MIDDLE", True), ("friend", 29, 100, "BOTTOM", True), ("stranger", 238, 200, "MIDDLE", False)])
        self.riot.add_game(2, 440, [("ole", 99, 100, "MIDDLE", False), ("friend", 154, 100, "JUNGLE", False)])
        self.riot.add_game(3, 700, [("ole", 29, 200, "UTILITY", True)])
        self.riot.add_game(4, 420, [("friend", 29, 100, "BOTTOM", True)])

    def linked_match_ids(self, account):
        return sorted(
            participant.match.riot_match_id
            for participant in MatchParticipant.query.filter_by(riot_account_id=account.id)
        )

    def test_first_import_stores_games_links_tracked_accounts_and_completes_history(self):
        self.add_default_games()

        result = self.service.import_account(self.main.id)

        self.assertEqual(result["imported"], 3)
        self.assertTrue(result["history_complete"])
        self.assertEqual(self.linked_match_ids(self.main), ["EUW1_1", "EUW1_2", "EUW1_3"])
        # Friend's participant rows are linked while importing Main.
        self.assertEqual(self.linked_match_ids(self.friend), ["EUW1_1", "EUW1_2"])

        match = Match.query.filter_by(riot_match_id="EUW1_1").one()
        self.assertEqual(match.queue_id, 420)
        self.assertEqual(match.game_duration_seconds, 1800)
        self.assertEqual(match.game_creation, datetime(2025, 1, 1, 1, 0))
        self.assertEqual(match.imported_at, self.now)
        self.assertEqual(len(match.participants), 3)
        stranger = match.participants[2]
        self.assertIsNone(stranger.riot_account_id)
        self.assertEqual((stranger.riot_id_game_name, stranger.riot_champion_id, stranger.team_id), ("Stranger", 238, 200))

        state = MatchImportState.query.filter_by(riot_account_id=self.main.id).one()
        self.assertTrue(state.history_complete)
        self.assertEqual(state.last_import_at, self.now)

    def test_budget_limits_downloads_and_the_next_run_backfills(self):
        self.add_default_games()

        first = self.service.import_account(self.main.id, max_new_matches=2)

        self.assertEqual((first["imported"], first["remaining"]), (2, 1))
        self.assertFalse(first["history_complete"])
        self.assertEqual(self.linked_match_ids(self.main), ["EUW1_2", "EUW1_3"])

        second = self.service.import_account(self.main.id)

        self.assertEqual((second["imported"], second["remaining"]), (1, 0))
        self.assertTrue(second["history_complete"])
        self.assertEqual(self.riot.match_calls, ["EUW1_3", "EUW1_2", "EUW1_1"])

    def test_complete_history_stops_listing_at_known_games(self):
        for number in range(1, 8):
            self.riot.add_game(number, 420, [("ole", 99, 100, "MIDDLE", True)])

        with patch.object(RiotService, "MATCH_ID_PAGE_SIZE", 2):
            self.service.import_account(self.main.id, queue_ids=(420,), match_types=())
            self.riot.add_game(8, 420, [("ole", 99, 100, "MIDDLE", True)])
            self.riot.id_calls.clear()
            self.riot.match_calls.clear()

            result = self.service.import_account(self.main.id, queue_ids=(420,), match_types=())

        self.assertEqual(result["imported"], 1)
        self.assertEqual(self.riot.match_calls, ["EUW1_8"])
        self.assertEqual([start for _, _, start in self.riot.id_calls], [0])

    def test_incomplete_history_keeps_paging_past_known_games(self):
        for number in range(1, 6):
            self.riot.add_game(number, 420, [("ole", 99, 100, "MIDDLE", True)])

        with patch.object(RiotService, "MATCH_ID_PAGE_SIZE", 2):
            self.service.import_account(self.main.id, max_new_matches=2, queue_ids=(420,), match_types=())
            result = self.service.import_account(self.main.id, queue_ids=(420,), match_types=())

        self.assertEqual(result["imported"], 3)
        self.assertEqual(Match.query.count(), 5)

    def test_game_stored_through_a_friend_is_linked_without_downloading_again(self):
        self.add_default_games()
        self.service.import_account(self.friend.id)
        self.riot.match_calls.clear()

        result = self.service.import_account(self.main.id)

        self.assertEqual((result["imported"], result["linked_existing"]), (1, 0))
        self.assertEqual(self.riot.match_calls, ["EUW1_3"])
        self.assertEqual(self.linked_match_ids(self.main), ["EUW1_1", "EUW1_2", "EUW1_3"])

    def test_alt_account_shares_games_with_nobody_but_its_own(self):
        self.add_default_games()
        self.riot.add_game(5, 440, [("alt", 99, 100, "MIDDLE", True), ("friend", 29, 100, "BOTTOM", False)])

        self.service.import_account(self.alt.id)

        self.assertEqual(self.linked_match_ids(self.alt), ["EUW1_5"])
        self.assertEqual(self.linked_match_ids(self.friend), ["EUW1_5"])

    def test_rejected_puuid_is_refreshed_from_the_riot_id(self):
        self.add_default_games()
        self.riot.key_era = 2

        result = self.service.import_account(self.main.id)

        self.assertTrue(result["puuid_refreshed"])
        self.assertEqual(db.session.get(RiotAccount, self.main.id).puuid, "ole-k2")
        self.assertEqual(result["imported"], 3)
        self.assertEqual(self.linked_match_ids(self.main), ["EUW1_1", "EUW1_2", "EUW1_3"])

    def test_games_stored_under_an_older_key_are_linked_by_participant_slot(self):
        # Main was added under the new key, Friend's games were stored under the old one.
        self.add_default_games()
        self.main.puuid = "ole-k2"
        db.session.commit()
        self.service.import_account(self.friend.id)
        self.assertEqual(self.linked_match_ids(self.main), [])

        self.riot.key_era = 2
        self.riot.match_calls.clear()

        result = self.service.import_account(self.main.id)

        self.assertFalse(result["puuid_refreshed"])
        self.assertEqual((result["imported"], result["linked_existing"]), (1, 2))
        # Each shared game is fetched once to find Main's participant slot.
        self.assertEqual(sorted(self.riot.match_calls), ["EUW1_1", "EUW1_2", "EUW1_3"])
        self.assertEqual(self.linked_match_ids(self.main), ["EUW1_1", "EUW1_2", "EUW1_3"])

        slot = MatchParticipant.query.filter_by(riot_account_id=self.main.id).join(Match).filter(Match.riot_match_id == "EUW1_1").one()
        self.assertEqual((slot.participant_id, slot.puuid), (1, "ole-k1"))

    def test_renamed_riot_id_explains_the_problem(self):
        self.add_default_games()
        self.riot.key_era = 2
        self.main.game_name = "Renamed"
        db.session.commit()

        with self.assertRaises(MatchImportError) as raised:
            self.service.import_account(self.main.id)

        self.assertIn("could not find this Riot ID", str(raised.exception))

    def test_only_ranked_games_and_clash_are_imported(self):
        self.riot.add_game(1, 2400, [("ole", 99, 100, "MIDDLE", True)])
        self.riot.add_game(2, 400, [("ole", 99, 100, "MIDDLE", True)])
        self.riot.add_game(3, 450, [("ole", 99, 100, "", True)])
        self.riot.add_game(4, 420, [("ole", 99, 100, "MIDDLE", True)])
        self.riot.add_game(5, 440, [("ole", 99, 100, "MIDDLE", True)])
        self.riot.add_game(6, 700, [("ole", 99, 100, "MIDDLE", True)])
        self.riot.add_game(7, UNNAMED_RANKED_QUEUE, [("ole", 99, 100, "MIDDLE", True)])

        result = self.service.import_account(self.main.id)

        self.assertEqual(result["imported"], 4)
        self.assertEqual(sorted(self.riot.match_calls), ["EUW1_4", "EUW1_5", "EUW1_6", "EUW1_7"])
        self.assertEqual({listing for _, listing, _ in self.riot.id_calls}, {700, "ranked"})
        self.assertEqual(
            sorted(match.queue_id for match in Match.query),
            [420, 440, 700, UNNAMED_RANKED_QUEUE],
        )

    def test_patch_is_stored_from_the_game_version(self):
        self.riot.add_game(1, 420, [("ole", 99, 100, "MIDDLE", True)], game_version="16.18.712.3456")
        self.riot.add_game(2, 420, [("ole", 99, 100, "MIDDLE", True)], game_version="15.21.715.5926")
        self.riot.add_game(3, 420, [("ole", 99, 100, "MIDDLE", True)], game_version="")

        self.service.import_account(self.main.id)

        self.assertEqual(
            {match.riot_match_id: match.patch for match in Match.query},
            {"EUW1_1": "16.18", "EUW1_2": "15.21", "EUW1_3": None},
        )

    def test_unavailable_games_are_counted_and_skipped(self):
        self.add_default_games()
        self.riot.gone.add("EUW1_2")

        result = self.service.import_account(self.main.id)

        self.assertEqual((result["imported"], result["unavailable"]), (2, 1))
        self.assertIsNone(Match.query.filter_by(riot_match_id="EUW1_2").one_or_none())

    def test_legacy_duration_and_raw_data_round_trip(self):
        self.riot.add_game(1, 420, [("ole", 99, 100, "MIDDLE", True)], legacy_duration=True)

        self.service.import_account(self.main.id)
        match = Match.query.one()

        self.assertEqual(match.game_duration_seconds, 1800)
        self.assertEqual(
            MatchImportService.decode_raw_data(match),
            self.riot.get_match("EUW1_1", "EUW1"),
        )

    def test_failure_keeps_imported_games_and_explains(self):
        self.add_default_games()
        self.riot.fail_on_match_call = 2

        with self.assertRaises(MatchImportError) as raised:
            self.service.import_account(self.main.id)

        self.assertIn("HTTP 503", str(raised.exception))
        self.assertEqual(self.linked_match_ids(self.main), ["EUW1_3"])
        self.assertFalse(MatchImportState.query.filter_by(riot_account_id=self.main.id).one().history_complete)

    def test_progress_is_reported_per_game(self):
        self.add_default_games()
        calls = []

        self.service.import_account(self.main.id, progress=lambda done, total: calls.append((done, total)))

        self.assertEqual(calls, [(1, 3), (2, 3), (3, 3)])

    def test_import_all_accounts_continues_after_one_failure(self):
        self.add_default_games()
        self.alt.game_name = "Renamed"
        self.alt.puuid = "alt-k0"
        db.session.commit()

        results = self.service.import_all_accounts()

        self.assertEqual([result["riot_id"] for result in results], ["Main#EUW", "Renamed#EUW", "Friend#EUW"])
        self.assertIn("error", results[1])
        self.assertEqual(results[2]["imported"], 1)

    def test_import_all_accounts_stops_when_the_key_is_rejected(self):
        self.add_default_games()

        def reject(*args, **kwargs):
            raise http_error(403)

        self.riot.get_match_ids = reject

        results = self.service.import_all_accounts()

        self.assertEqual(len(results), 1)
        self.assertIn("rejected the API key", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
