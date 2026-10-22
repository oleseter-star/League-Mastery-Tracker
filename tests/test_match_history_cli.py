import io
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import requests
from flask import Flask

import match_history
from application.database.database import db
from application.database.models import (
    Champion,
    Match,
    MatchParticipant,
    Person,
    RiotAccount,
)


JAN_2025_MS = 1_735_689_600_000


class FakeHTTPResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeRiotService:
    """
    Two Solo/Duo games for Main, one shared with Friend.

    Game 1 is on patch 16.17 (26.17), game 2 on 16.18 (26.18).
    """

    def __init__(self, reject_key=False):
        self.reject_key = reject_key
        self.calls = 0

    def get_match_ids(self, puuid, platform_region, start=0, count=100, queue=None, match_type=None):
        self.calls += 1
        self.listings = getattr(self, "listings", []) + [queue or match_type]

        if self.reject_key:
            raise requests.HTTPError("HTTP 403", response=FakeHTTPResponse(403))

        if match_type != "ranked" or start:
            return []

        return {"main-puuid": ["EUW1_2", "EUW1_1"], "friend-puuid": ["EUW1_1"]}.get(puuid, [])

    def get_match(self, match_id, platform_region):
        number = int(match_id.split("_")[1])
        participants = [{"participantId": 1, "puuid": "main-puuid", "championId": 99, "teamId": 100, "teamPosition": "MIDDLE", "win": True}]

        if number == 1:
            participants.append({"participantId": 2, "puuid": "friend-puuid", "championId": 29, "teamId": 100, "teamPosition": "BOTTOM", "win": True})

        return {
            "metadata": {"matchId": match_id},
            "info": {
                "platformId": "EUW1",
                "queueId": 420,
                "gameCreation": JAN_2025_MS + number * 86_400_000,
                "gameVersion": f"16.{16 + number}.712.3456",
                "gameDuration": 1800,
                "gameEndTimestamp": JAN_2025_MS,
                "participants": participants,
            },
        }


class FakeInstanceService:
    def __init__(self, available=True):
        self.available = available
        self.released = False

    def acquire(self):
        return self.available

    def release(self):
        self.released = True


class MatchHistoryCliTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()
            ole = Person(display_name="Ole")
            friend = Person(display_name="Friend")
            db.session.add_all([
                ole,
                friend,
                RiotAccount(person=ole, game_name="Main", tag_line="EUW", puuid="main-puuid", platform_region="EUW1"),
                RiotAccount(person=friend, game_name="Friend", tag_line="EUW", puuid="friend-puuid", platform_region="EUW1"),
                Champion(riot_champion_id=99, name="Lux", source="bundled"),
                Champion(riot_champion_id=29, name="Twitch", source="bundled"),
            ])
            db.session.commit()

        self.stdout = io.StringIO()
        self.instance = FakeInstanceService()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def run_cli(self, *argv, riot_service=None):
        return match_history.main(
            argv=list(argv),
            app=self.app,
            riot_service=riot_service or FakeRiotService(),
            stdout=self.stdout,
            read_key=lambda prompt: "RGAPI-entered-key",
            instance_service=self.instance,
        )

    def output(self):
        return self.stdout.getvalue()

    def test_import_downloads_games_and_releases_the_lock(self):
        self.assertEqual(self.run_cli("import"), 0)

        self.assertIn("Main#EUW: 2 new games. History is complete.", self.output())
        self.assertIn("Friend#EUW: 0 new games", self.output())
        self.assertTrue(self.instance.released)

        with self.app.app_context():
            self.assertEqual(Match.query.count(), 2)
            self.assertEqual(MatchParticipant.query.filter(MatchParticipant.riot_account_id.isnot(None)).count(), 3)

    def test_import_refuses_while_the_application_is_running(self):
        self.instance.available = False
        riot = FakeRiotService()

        self.assertEqual(self.run_cli("import", riot_service=riot), 2)
        self.assertIn("League Mastery Tracker is running", self.output())
        self.assertEqual(riot.calls, 0)

    def test_import_of_one_account_with_a_budget(self):
        self.assertEqual(self.run_cli("import", "--account", "main#euw", "--max-games", "1"), 0)

        self.assertIn("1 older games remain", self.output())
        self.assertNotIn("Friend#EUW", self.output())

    def test_rejected_key_stops_every_account(self):
        self.assertEqual(self.run_cli("import", riot_service=FakeRiotService(reject_key=True)), 1)

        self.assertIn("Main#EUW: stopped. Riot rejected the API key", self.output())
        self.assertNotIn("Friend#EUW", self.output())

    def test_ask_key_uses_the_entered_key_for_this_run(self):
        created = []

        def build(api_key):
            created.append(api_key)
            return FakeRiotService()

        with patch.object(match_history, "KeyOverrideRiotService", side_effect=build):
            self.assertEqual(self.run_cli("import", "--ask-key"), 0)

        self.assertEqual(created, ["RGAPI-entered-key"])
        self.assertEqual(
            match_history.KeyOverrideRiotService("RGAPI-entered-key")._headers()["X-Riot-Token"],
            "RGAPI-entered-key",
        )

    def test_stats_print_tables_and_summary(self):
        self.run_cli("import")
        self.stdout.truncate(0)
        self.stdout.seek(0)

        self.assertEqual(self.run_cli("stats", "champions", "--person", "ole", "--min-games", "1"), 0)
        champions = self.output()
        self.assertIn("Champion  Games  W-L  Win%  Score", champions)
        self.assertIn("Lux           2  2-0  100%", champions)

        self.run_cli("stats", "pairs", "--min-games", "1")
        self.assertIn("Ole     Friend      1  1-0", self.output())

        self.run_cli("stats", "allies", "--person", "Ole", "--champion", "lux", "--min-games", "1")
        self.assertIn("Twitch", self.output())

        self.run_cli("stats", "summary")
        self.assertIn("Games: 2", self.output())
        self.assertIn("Ranked Solo/Duo        2", self.output())
        self.assertIn("26.18                  1", self.output())
        self.assertIn("26.17                  1", self.output())

    def test_import_lists_ranked_games_and_clash_by_default(self):
        riot = FakeRiotService()

        self.run_cli("import", "--account", "Main#EUW", riot_service=riot)

        self.assertEqual(riot.listings, [700, "ranked"])

        explicit = FakeRiotService()
        self.run_cli("import", "--account", "Main#EUW", "--queue", "440", riot_service=explicit)
        self.assertEqual(explicit.listings, [440])

    def test_stats_filter_by_mode_and_patches(self):
        self.run_cli("import")
        self.stdout.truncate(0)
        self.stdout.seek(0)

        self.run_cli("stats", "champions", "--person", "Ole", "--mode", "solo", "--min-games", "1")
        self.assertIn("Lux           2  2-0", self.output())

        self.run_cli("stats", "champions", "--person", "Ole", "--mode", "flex", "--min-games", "1")
        self.assertIn("No results", self.output())

        self.stdout.truncate(0)
        self.stdout.seek(0)
        self.run_cli("stats", "champions", "--person", "Ole", "--patch", "26.18", "--min-games", "1")
        self.assertIn("Lux           1  1-0", self.output())

        self.stdout.truncate(0)
        self.stdout.seek(0)
        self.run_cli("stats", "champions", "--person", "Ole", "--patch", "26.17-26.18", "--min-games", "1")
        self.assertIn("Lux           2  2-0", self.output())

    def test_patches_view_lists_newest_patch_first(self):
        self.run_cli("import")
        self.stdout.truncate(0)
        self.stdout.seek(0)

        self.run_cli("stats", "patches", "--person", "Ole", "--champion", "Lux", "--min-games", "1")
        output = self.output()

        self.assertLess(output.index("26.18"), output.index("26.17"))
        self.assertIn("Patch  Games  W-L", output)

    def test_unknown_mode_patch_and_ranked_5s_are_explained(self):
        self.run_cli("import")

        self.assertEqual(self.run_cli("stats", "persons", "--mode", "5s"), 2)
        self.assertIn("Ranked 5s queue ID is not known yet", self.output())

        self.assertEqual(self.run_cli("stats", "persons", "--patch", "latest"), 2)
        self.assertIn("Expected a patch such as 26.18", self.output())

        self.assertEqual(self.run_cli("stats", "persons", "--patch", "24.1"), 2)
        self.assertIn("No stored games are on the selected patches", self.output())

    def test_stats_hide_small_samples_and_explain_unknown_names(self):
        self.run_cli("import")

        self.assertEqual(self.run_cli("stats", "champions"), 0)
        self.assertIn("No results. Try a lower --min-games", self.output())

        self.assertEqual(self.run_cli("stats", "persons", "--person", "Nobody"), 2)
        self.assertIn("No Person named 'Nobody'", self.output())

        self.assertEqual(self.run_cli("stats", "allies", "--champion", "Teemo"), 2)
        self.assertIn("No champion named 'Teemo'", self.output())

    def test_stats_position_aliases_map_to_riot_values(self):
        self.run_cli("import")

        self.run_cli("stats", "positions", "--position", "mid", "--min-games", "1")

        self.assertIn("MIDDLE", self.output())
        self.assertNotIn("BOTTOM", self.output())


if __name__ == "__main__":
    unittest.main()
