import json
import unittest
import zlib
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, Flask
from sqlalchemy import inspect, text

from application.database.database import db
from application.database.models import (
    Champion,
    Match,
    MatchParticipant,
    Person,
    RiotAccount,
)
from application.routes.champion_images import champion_images_bp
from application.routes.match_review import match_review_bp
from application.services.match_assignment_service import (
    MatchAssignmentService,
)
from application.services.match_schema_service import MatchSchemaService
from application.services.match_statistics_service import (
    MatchStatisticsFilter,
    MatchStatisticsService,
)


KALISTA, ALISTAR, SETT = 429, 12, 875
JAN_1 = datetime(2026, 1, 1, 12, 0)


home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    return "Test home"


class MatchReviewTestCase(unittest.TestCase):
    """
    Ole owns Main and Shared. Per and Iver sometimes play on Shared while
    Ole plays on Main, which puts two of Ole's accounts in one game.
    """

    def setUp(self):
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).resolve().parents[1] / "application" / "templates"),
        )
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="match-review-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.app.register_blueprint(home_bp)
        self.app.register_blueprint(match_review_bp)
        self.app.register_blueprint(champion_images_bp)
        self.app.jinja_env.globals["csrf_token"] = lambda: "test-csrf-token"
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.ole = Person(display_name="Ole")
        self.per = Person(display_name="Per")
        self.iver = Person(display_name="Iver")
        self.main = RiotAccount(person=self.ole, game_name="Main", tag_line="EUW", puuid="p-main", platform_region="EUW1")
        self.shared = RiotAccount(person=self.ole, game_name="Shared", tag_line="EUW", puuid="p-shared", platform_region="EUW1")

        for riot_champion_id, name in ((KALISTA, "Kalista"), (ALISTAR, "Alistar"), (SETT, "Sett")):
            db.session.add(Champion(riot_champion_id=riot_champion_id, name=name, image=f"{name}.png", source="bundled"))

        db.session.add_all([self.ole, self.per, self.iver])
        db.session.commit()

        # Games 1 and 2: Shared on Alistar (Per). Game 3: Shared on Sett (Iver).
        # Game 4: Ole alone on Main.
        self.add_game(1, [(self.main, KALISTA, True), (self.shared, ALISTAR, True)])
        self.add_game(2, [(self.main, KALISTA, False), (self.shared, ALISTAR, False)])
        self.add_game(3, [(self.main, KALISTA, True), (self.shared, SETT, True)])
        self.add_game(4, [(self.main, KALISTA, True)])
        db.session.commit()

        self.service = MatchAssignmentService()
        self.statistics = MatchStatisticsService()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def add_game(self, number, participants):
        match = Match(
            riot_match_id=f"EUW1_{number}",
            platform_id="EUW1",
            queue_id=420,
            patch="16.21",
            game_creation=JAN_1 + timedelta(days=number),
            game_duration_seconds=1800,
            imported_at=JAN_1 + timedelta(days=30),
        )

        for slot, (account, champion_id, win) in enumerate(participants, start=1):
            match.participants.append(
                MatchParticipant(
                    participant_id=slot,
                    riot_champion_id=champion_id,
                    team_id=100,
                    team_position="BOTTOM" if champion_id == KALISTA else "UTILITY",
                    win=win,
                    riot_account=account,
                )
            )

        db.session.add(match)

    def match(self, number):
        return Match.query.filter_by(riot_match_id=f"EUW1_{number}").one()

    def shared_participant(self, number):
        return MatchParticipant.query.filter_by(
            match_id=self.match(number).id,
            riot_account_id=self.shared.id,
        ).one()

    def review_ids(self):
        return [game["riot_match_id"] for game in self.service.games_to_review()]

    def overview(self):
        return {row["person_name"]: (row["games"], row["wins"]) for row in self.statistics.person_overview()}

    def flashes(self):
        with self.client.session_transaction() as session:
            return [message for _category, message in session.get("_flashes", [])]


class MatchReviewServiceTests(MatchReviewTestCase):
    def test_games_with_two_accounts_of_one_person_need_review(self):
        games = self.service.games_to_review()

        self.assertEqual([game["riot_match_id"] for game in games], ["EUW1_3", "EUW1_2", "EUW1_1"])
        self.assertEqual(
            [(account["riot_id"], account["champion_name"], account["owner_name"]) for account in games[0]["accounts"]],
            [("Main#EUW", "Kalista", "Ole"), ("Shared#EUW", "Sett", "Ole")],
        )

    def test_choosing_who_played_resolves_a_game(self):
        self.service.set_played_by(self.shared_participant(1).id, self.per.id)
        self.service.set_played_by(self.shared_participant(3).id, self.iver.id)

        self.assertEqual(self.review_ids(), ["EUW1_2"])
        self.assertEqual(self.overview(), {"Ole": (4, 3), "Per": (1, 1), "Iver": (1, 1)})

        self.service.set_played_by(self.shared_participant(1).id, self.ole.id)
        self.assertIsNone(self.shared_participant(1).played_by_person_id)
        self.assertEqual(self.review_ids(), ["EUW1_2", "EUW1_1"])

    def test_ignoring_a_game_removes_it_from_review_and_statistics(self):
        self.assertEqual(self.service.ignore_review_game(self.match(2).id), 2)

        self.assertEqual(self.review_ids(), ["EUW1_3", "EUW1_1"])
        self.assertEqual(self.overview(), {"Ole": (3, 3)})
        self.assertEqual([game["riot_match_id"] for game in self.service.ignored_games()], ["EUW1_2"])

        # A game that no longer needs review is left alone.
        self.assertEqual(self.service.ignore_review_game(self.match(4).id), 0)

    def test_ignore_all_and_restore(self):
        self.service.set_played_by(self.shared_participant(1).id, self.per.id)

        self.assertEqual(self.service.ignore_all_review_games(), 2)
        self.assertEqual(self.review_ids(), [])
        self.assertEqual(self.overview(), {"Ole": (2, 2), "Per": (1, 1)})

        self.assertEqual(self.service.restore_game(self.match(3).id), 2)
        self.assertEqual(self.review_ids(), ["EUW1_3"])
        self.assertEqual(self.service.restore_game(self.match(3).id), 0)

    def test_ignored_accounts_leave_pairs_and_champion_views(self):
        self.service.set_played_by(self.shared_participant(1).id, self.per.id)
        self.service.set_played_by(self.shared_participant(2).id, self.per.id)
        self.shared_participant(2).ignored = True
        db.session.commit()

        pairs = self.statistics.person_pairs()
        champions = self.statistics.person_champions(MatchStatisticsFilter(person_ids=(self.per.id,)))

        self.assertEqual([(row["person_name"], row["other_person_name"], row["games"]) for row in pairs], [("Ole", "Per", 1)])
        self.assertEqual([(row["champion_name"], row["games"]) for row in champions], [("Alistar", 1)])

    def test_set_played_by_rejects_untracked_participants_and_unknown_persons(self):
        stranger = MatchParticipant(match_id=self.match(4).id, participant_id=9, riot_champion_id=SETT, team_id=200, win=False)
        db.session.add(stranger)
        db.session.commit()

        with self.assertRaises(ValueError):
            self.service.set_played_by(stranger.id, self.per.id)

        with self.assertRaises(ValueError):
            self.service.set_played_by(self.shared_participant(1).id, 999)


    def test_review_games_describe_both_teams_and_account_stats(self):
        match = self.match(3)
        match.participants.append(
            MatchParticipant(participant_id=6, riot_champion_id=SETT, team_id=200, team_position="TOP", win=False)
        )
        match.raw_data = zlib.compress(json.dumps({
            "info": {
                "participants": [
                    {"participantId": 1, "totalMinionsKilled": 200, "neutralMinionsKilled": 10, "totalDamageDealtToChampions": 25000},
                    {"participantId": 2, "totalMinionsKilled": 30, "neutralMinionsKilled": 0, "totalDamageDealtToChampions": 9000},
                ]
            }
        }).encode("utf-8"))
        db.session.commit()

        game = next(game for game in self.service.games_to_review() if game["riot_match_id"] == "EUW1_3")
        main, shared = game["accounts"]

        self.assertTrue(game["win"])
        self.assertEqual([(team["team_id"], team["win"]) for team in game["teams"]], [(100, True), (200, False)])
        self.assertEqual(
            [(member["champion_name"], member["tracked"], member["selected"]) for member in game["teams"][0]["participants"]],
            [("Kalista", True, True), ("Sett", True, True)],
        )
        self.assertEqual(game["teams"][1]["participants"][0]["champion_image"], "Sett.png")
        self.assertFalse(game["teams"][1]["participants"][0]["tracked"])
        self.assertEqual((main["creep_score"], round(main["creep_score_per_minute"], 1), main["damage_to_champions"]), (210, 7.0, 25000))
        self.assertEqual(shared["champion_image"], "Sett.png")

    def test_missing_match_data_leaves_stats_empty(self):
        game = self.service.games_to_review()[0]

        self.assertIsNone(game["accounts"][0]["creep_score"])
        self.assertIsNone(game["accounts"][0]["damage_to_champions"])
        self.assertIsNone(game["accounts"][0]["kda"])


class MatchReviewRouteTests(MatchReviewTestCase):
    def test_review_page_lists_games_with_choices(self):
        response = self.client.get("/matches/review")
        page = response.get_data(as_text=True)
        response.close()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Games to review", page)
        self.assertIn("Ignore all (3)", page)
        self.assertEqual(page.count("Ignore game"), 3)
        self.assertEqual(page.count('/played-by"'), 6)
        self.assertIn("Ole (owner)", page)
        self.assertIn("/champions/images/Alistar.png", page)
        self.assertIn("Victory", page)
        self.assertIn("Defeat", page)
        self.assertIn('aria-label="Bottom"', page)
        self.assertIn("Ranked Solo/Duo", page)
        self.assertIn("Patch 26.21", page)
        self.assertIn("No games are ignored.", page)

    def test_saving_who_played_moves_the_game(self):
        participant_id = self.shared_participant(1).id

        response = self.client.post(f"/matches/participants/{participant_id}/played-by", data={"person_id": str(self.per.id)})
        response.close()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.shared_participant(1).played_by_person_id, self.per.id)
        self.assertIn("Saved who played the game.", self.flashes())

    def test_saving_rejects_a_missing_person(self):
        participant_id = self.shared_participant(1).id

        for value in ("", "999"):
            response = self.client.post(f"/matches/participants/{participant_id}/played-by", data={"person_id": value})
            response.close()

        self.assertIsNone(self.shared_participant(1).played_by_person_id)
        self.assertIn("Choose who played this game.", self.flashes())

    def test_ignore_game_ignore_all_and_restore(self):
        response = self.client.post(f"/matches/{self.match(1).id}/ignore")
        response.close()
        self.assertEqual(self.review_ids(), ["EUW1_3", "EUW1_2"])

        response = self.client.post("/matches/review/ignore-all")
        response.close()
        self.assertEqual(self.review_ids(), [])
        self.assertIn("2 games are ignored and no longer count in statistics.", self.flashes())

        page_response = self.client.get("/matches/review")
        page = page_response.get_data(as_text=True)
        page_response.close()
        self.assertIn("No games need review.", page)
        self.assertEqual(page.count('/restore"'), 3)

        response = self.client.post(f"/matches/{self.match(1).id}/restore")
        response.close()
        self.assertEqual(self.review_ids(), ["EUW1_1"])


class MatchSchemaServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.app_context.pop()

    def test_missing_columns_are_added_to_existing_match_tables(self):
        with db.engine.begin() as connection:
            connection.execute(text("CREATE TABLE persons (id INTEGER PRIMARY KEY, display_name VARCHAR(120) NOT NULL)"))
            connection.execute(text(
                "CREATE TABLE match_participants (id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, "
                "participant_id INTEGER NOT NULL, riot_champion_id INTEGER NOT NULL, team_id INTEGER NOT NULL, "
                "win BOOLEAN NOT NULL, riot_account_id INTEGER)"
            ))
            connection.execute(text(
                "INSERT INTO match_participants (match_id, participant_id, riot_champion_id, team_id, win) "
                "VALUES (1, 1, 99, 100, 1)"
            ))

        self.assertEqual(
            MatchSchemaService.add_missing_columns(),
            ["match_participants.played_by_person_id", "match_participants.ignored"],
        )
        self.assertEqual(MatchSchemaService.add_missing_columns(), [])

        columns = {column["name"] for column in inspect(db.engine).get_columns("match_participants")}
        self.assertTrue({"played_by_person_id", "ignored"}.issubset(columns))

        with db.engine.connect() as connection:
            row = connection.execute(text("SELECT played_by_person_id, ignored FROM match_participants")).one()

        self.assertEqual(tuple(row), (None, 0))

    def test_databases_without_match_tables_are_left_alone(self):
        self.assertEqual(MatchSchemaService.add_missing_columns(), [])
        self.assertNotIn("match_participants", inspect(db.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
