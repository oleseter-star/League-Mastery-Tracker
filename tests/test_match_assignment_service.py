import unittest
from datetime import datetime, timedelta

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    Match,
    MatchParticipant,
    Person,
    RiotAccount,
)
from application.services.match_assignment_service import (
    GameSelection,
    MatchAssignmentService,
)
from application.services.match_statistics_service import (
    MatchStatisticsFilter,
    MatchStatisticsService,
)
from application.services.person_service import PersonService


KALISTA, ALISTAR, SETT, LUX = 429, 12, 875, 99
JAN_1 = datetime(2026, 1, 1, 12, 0)


class MatchAssignmentTests(unittest.TestCase):
    """
    Ole owns Main and Shared. Friend sometimes plays on Shared, and in
    those games Ole duos with Friend on Main.
    """

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

        self.ole = Person(display_name="Ole")
        self.friend = Person(display_name="Friend")
        self.main = RiotAccount(person=self.ole, game_name="Main", tag_line="EUW", puuid="p-main", platform_region="EUW1")
        self.shared = RiotAccount(person=self.ole, game_name="Shared", tag_line="EUW", puuid="p-shared", platform_region="EUW1")

        for riot_champion_id, name in ((KALISTA, "Kalista"), (ALISTAR, "Alistar"), (SETT, "Sett"), (LUX, "Lux")):
            db.session.add(Champion(riot_champion_id=riot_champion_id, name=name, source="bundled"))

        db.session.add_all([self.ole, self.friend])
        db.session.commit()

        # Games 1-3: Main (Kalista bot) with Shared (Alistar support), same team.
        for number, win in ((1, True), (2, True), (3, False)):
            self.add_game(number, [(self.main, KALISTA, 100, "BOTTOM", win), (self.shared, ALISTAR, 100, "UTILITY", win)])

        # Game 4: Ole alone on Shared. Game 5: Ole alone on Main.
        self.add_game(4, [(self.shared, SETT, 100, "TOP", True)])
        self.add_game(5, [(self.main, KALISTA, 100, "BOTTOM", False)])
        db.session.commit()

        self.assignments = MatchAssignmentService()
        self.statistics = MatchStatisticsService()

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

        for slot, (account, champion_id, team_id, position, win) in enumerate(participants, start=1):
            match.participants.append(
                MatchParticipant(
                    participant_id=slot,
                    riot_champion_id=champion_id,
                    team_id=team_id,
                    team_position=position,
                    win=win,
                    riot_account=account,
                )
            )

        db.session.add(match)

    def overview(self):
        return {row["person_name"]: (row["games"], row["wins"]) for row in self.statistics.person_overview()}

    def assign_duo_games_to_friend(self):
        return self.assignments.assign(
            self.shared.id,
            self.friend.id,
            GameSelection(together_with_account_id=self.main.id),
        )

    def test_without_assignments_a_game_counts_once_for_its_owner(self):
        # Games 1-3 have two of Ole's accounts in them but count once each.
        self.assertEqual(self.overview(), {"Ole": (5, 3)})
        self.assertEqual(self.statistics.person_pairs(), [])

    def test_assigned_games_count_for_the_person_who_played_them(self):
        self.assertEqual(self.assign_duo_games_to_friend(), 3)

        self.assertEqual(self.overview(), {"Ole": (5, 3), "Friend": (3, 2)})

        pairs = self.statistics.person_pairs()
        self.assertEqual([(row["person_name"], row["other_person_name"], row["games"]) for row in pairs], [("Ole", "Friend", 3)])

        friend_champions = self.statistics.person_champions(MatchStatisticsFilter(person_ids=(self.friend.id,)))
        self.assertEqual([(row["champion_name"], row["games"]) for row in friend_champions], [("Alistar", 3)])

        ole_champions = self.statistics.person_champions(MatchStatisticsFilter(person_ids=(self.ole.id,)))
        self.assertEqual({row["champion_name"]: row["games"] for row in ole_champions}, {"Kalista": 4, "Sett": 1})

    def test_account_filter_still_shows_every_game_on_the_account(self):
        self.assign_duo_games_to_friend()

        rows = self.statistics.person_overview(MatchStatisticsFilter(riot_account_ids=(self.shared.id,)))

        self.assertEqual({row["person_name"]: row["games"] for row in rows}, {"Friend": 3, "Ole": 1})

    def test_selection_by_match_champion_and_date(self):
        self.assertEqual(self.assignments.assign(self.shared.id, self.friend.id, GameSelection(riot_match_ids=("EUW1_4",))), 1)
        self.assertEqual(self.assignments.assign(self.shared.id, self.friend.id, GameSelection(riot_champion_id=ALISTAR, end=JAN_1 + timedelta(days=2, hours=1))), 2)

        self.assertEqual(
            {game["riot_match_id"]: game["played_by"] for game in self.assignments.list_games(self.shared.id)},
            {"EUW1_4": "Friend", "EUW1_3": "Ole", "EUW1_2": "Friend", "EUW1_1": "Friend"},
        )

    def test_assigning_to_the_owner_clears_and_repeats_change_nothing(self):
        self.assign_duo_games_to_friend()

        self.assertEqual(self.assign_duo_games_to_friend(), 0)
        self.assertEqual(self.assignments.assign(self.shared.id, self.ole.id, GameSelection(riot_match_ids=("EUW1_1",))), 1)
        self.assertEqual(self.assignments.assign(self.shared.id, None, GameSelection(together_with_account_id=self.main.id)), 2)
        self.assertEqual(MatchParticipant.query.filter(MatchParticipant.played_by_person_id.isnot(None)).count(), 0)

    def test_an_empty_selection_needs_all_games(self):
        with self.assertRaises(ValueError):
            self.assignments.assign(self.shared.id, self.friend.id)

        self.assertEqual(self.assignments.assign(self.shared.id, self.friend.id, all_games=True), 4)

        with self.assertRaises(ValueError):
            self.assignments.assign(self.shared.id, 999, all_games=True)

    def test_list_games_shows_other_tracked_accounts_and_assignment(self):
        self.assign_duo_games_to_friend()

        games = self.assignments.list_games(self.shared.id, limit=2)

        self.assertEqual([game["riot_match_id"] for game in games], ["EUW1_4", "EUW1_3"])
        self.assertEqual((games[0]["played_by"], games[0]["assigned"], games[0]["with_accounts"]), ("Ole", False, []))
        self.assertEqual((games[1]["played_by"], games[1]["assigned"], games[1]["with_accounts"]), ("Friend", True, ["Main#EUW"]))
        self.assertEqual(games[1]["champion_name"], "Alistar")

    def test_deleting_the_assigned_person_returns_games_to_the_owner(self):
        self.assign_duo_games_to_friend()

        PersonService.delete_person(self.friend)

        self.assertEqual(MatchParticipant.query.filter(MatchParticipant.played_by_person_id.isnot(None)).count(), 0)
        self.assertEqual(self.overview(), {"Ole": (5, 3)})


if __name__ == "__main__":
    unittest.main()
