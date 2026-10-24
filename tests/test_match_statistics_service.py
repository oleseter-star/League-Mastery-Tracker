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
from application.services.match_statistics_service import (
    MatchStatisticsFilter,
    MatchStatisticsService,
)
from application.services.person_service import PersonService


LUX, TWITCH, ZED, ZAC, ALISTAR, UNKNOWN = 99, 29, 238, 154, 12, 60099
JAN_1 = datetime(2025, 1, 1, 12, 0)


class MatchStatisticsServiceTests(unittest.TestCase):
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
        self.buddy = Person(display_name="Buddy")
        self.main = self.account(self.ole, "Main")
        self.alt = self.account(self.ole, "Alt")
        self.friend_account = self.account(self.friend, "Friend")
        self.buddy_account = self.account(self.buddy, "Buddy")

        for riot_champion_id, name in ((LUX, "Lux"), (TWITCH, "Twitch"), (ZED, "Zed"), (ZAC, "Zac"), (ALISTAR, "Alistar")):
            db.session.add(Champion(riot_champion_id=riot_champion_id, name=name, source="bundled"))

        db.session.add_all([self.ole, self.friend, self.buddy])
        db.session.commit()

        # G1 and G2: Ole (Main) with Friend. G3: Ole (Alt) with Buddy.
        # G4: Ole alone in ARAM. G5: a remake. G6: Friend against Buddy.
        # G1 is on patch 16.9, the rest on 16.18.
        self.add_game(1, 420, patch="16.9", participants=[
            (self.main, LUX, 100, "MIDDLE", True),
            (self.friend_account, TWITCH, 100, "BOTTOM", True),
            (None, ZED, 200, "MIDDLE", False),
            (None, ALISTAR, 200, "UTILITY", False),
        ])
        self.add_game(2, 420, [
            (self.main, LUX, 100, "MIDDLE", False),
            (self.friend_account, ZAC, 100, "JUNGLE", False),
            (None, ZED, 200, "MIDDLE", True),
        ])
        self.add_game(3, 400, [
            (self.alt, LUX, 100, "MIDDLE", True),
            (self.buddy_account, ALISTAR, 100, "UTILITY", True),
            (None, ZED, 200, "MIDDLE", False),
        ])
        self.add_game(4, 450, [(self.main, TWITCH, 100, "", True)])
        self.add_game(5, 420, [(self.main, LUX, 100, "MIDDLE", False)], duration=200)
        self.add_game(6, 420, [
            (self.friend_account, TWITCH, 100, "BOTTOM", True),
            (self.buddy_account, ZED, 200, "MIDDLE", False),
        ])
        db.session.commit()

        self.service = MatchStatisticsService()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def account(self, person, game_name):
        return RiotAccount(
            person=person,
            game_name=game_name,
            tag_line="EUW",
            puuid=f"puuid-{game_name}",
            platform_region="EUW1",
        )

    def add_game(self, number, queue_id, participants, duration=1800, patch="16.18"):
        match = Match(
            riot_match_id=f"EUW1_{number}",
            platform_id="EUW1",
            queue_id=queue_id,
            patch=patch,
            game_creation=JAN_1 + timedelta(days=number),
            game_duration_seconds=duration,
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

    @staticmethod
    def record(rows, **keys):
        matches = [row for row in rows if all(row[name] == value for name, value in keys.items())]
        assert len(matches) == 1, (keys, rows)
        return matches[0]

    def games_and_wins(self, rows, **keys):
        row = self.record(rows, **keys)
        return row["games"], row["wins"]

    def test_person_overview_counts_all_accounts_and_skips_remakes(self):
        rows = self.service.person_overview()

        self.assertEqual(self.games_and_wins(rows, person_name="Ole"), (4, 3))
        self.assertEqual(self.games_and_wins(rows, person_name="Friend"), (3, 2))
        self.assertEqual(self.games_and_wins(rows, person_name="Buddy"), (2, 1))

        with_remakes = self.service.person_overview(MatchStatisticsFilter(include_remakes=True))
        self.assertEqual(self.games_and_wins(with_remakes, person_name="Ole"), (5, 3))

    def test_person_champions_and_positions(self):
        filters = MatchStatisticsFilter(person_ids=(self.ole.id,))

        champions = self.service.person_champions(filters)
        positions = self.service.person_champion_positions(filters)

        self.assertEqual(self.games_and_wins(champions, champion_name="Lux"), (3, 2))
        self.assertEqual(self.games_and_wins(champions, champion_name="Twitch"), (1, 1))
        self.assertEqual(
            [(row["champion_name"], row["team_position"], row["games"]) for row in positions],
            [("Lux", "MIDDLE", 3)],
        )

    def test_champion_overview_across_persons_and_for_one_account(self):
        everyone = self.service.champion_overview()
        alt_only = self.service.champion_overview(MatchStatisticsFilter(riot_account_ids=(self.alt.id,)))

        self.assertEqual(self.games_and_wins(everyone, champion_name="Twitch"), (3, 3))
        self.assertEqual(self.games_and_wins(everyone, champion_name="Lux"), (3, 2))
        self.assertEqual(self.games_and_wins(everyone, champion_name="Zed"), (1, 0))
        self.assertEqual([(row["champion_name"], row["games"]) for row in alt_only], [("Lux", 1)])

    def test_ally_champions_for_a_person_on_a_champion(self):
        rows = self.service.ally_champions(
            MatchStatisticsFilter(person_ids=(self.ole.id,), riot_champion_id=LUX)
        )

        self.assertEqual(
            {row["champion_name"]: (row["games"], row["wins"]) for row in rows},
            {"Twitch": (1, 1), "Zac": (1, 0), "Alistar": (1, 1)},
        )

    def test_enemy_champions_and_lane_opponents(self):
        filters = MatchStatisticsFilter(person_ids=(self.ole.id,))

        enemies = self.service.enemy_champions(filters)
        lane = self.service.enemy_champions(filters, lane_opponents_only=True)

        self.assertEqual(self.games_and_wins(enemies, champion_name="Zed"), (3, 2))
        self.assertEqual(self.games_and_wins(enemies, champion_name="Alistar"), (1, 1))
        self.assertEqual([(row["champion_name"], row["games"]) for row in lane], [("Zed", 3)])

    def test_allies_and_enemies_grouped_by_their_role(self):
        filters = MatchStatisticsFilter(person_ids=(self.ole.id,), riot_champion_id=LUX)

        allies = self.service.ally_champions(filters, by_position=True)
        enemies = self.service.enemy_champions(filters, by_position=True)

        self.assertEqual(
            {(row["champion_name"], row["team_position"]): (row["games"], row["wins"]) for row in allies},
            {("Twitch", "BOTTOM"): (1, 1), ("Zac", "JUNGLE"): (1, 0), ("Alistar", "UTILITY"): (1, 1)},
        )
        self.assertEqual(
            {(row["champion_name"], row["team_position"]): (row["games"], row["wins"]) for row in enemies},
            {("Zed", "MIDDLE"): (3, 2), ("Alistar", "UTILITY"): (1, 1)},
        )

    def test_teammates_follow_the_champion_filter(self):
        on_lux = self.service.teammates(MatchStatisticsFilter(person_ids=(self.ole.id,), riot_champion_id=LUX))
        friend = self.service.teammates(MatchStatisticsFilter(person_ids=(self.friend.id,)))
        on_twitch = self.service.teammates(MatchStatisticsFilter(person_ids=(self.ole.id,), riot_champion_id=TWITCH))

        self.assertEqual({row["person_name"]: (row["games"], row["wins"]) for row in on_lux}, {"Friend": (2, 1), "Buddy": (1, 1)})
        # Game 6 had Buddy on the other team, so only Ole counts for Friend.
        self.assertEqual({row["person_name"]: (row["games"], row["wins"]) for row in friend}, {"Ole": (2, 1)})
        self.assertEqual(on_twitch, [])

    def test_with_person_filter_keeps_games_with_that_teammate(self):
        with_friend = MatchStatisticsFilter(person_ids=(self.ole.id,), with_person_id=self.friend.id)
        friend_with_ole = MatchStatisticsFilter(person_ids=(self.friend.id,), with_person_id=self.ole.id)

        self.assertEqual(self.games_and_wins(self.service.person_overview(with_friend), person_name="Ole"), (2, 1))
        self.assertEqual(
            {row["champion_name"]: row["games"] for row in self.service.champion_overview(friend_with_ole)},
            {"Twitch": 1, "Zac": 1},
        )
        self.assertEqual(self.service.summary(with_friend)["games"], 2)
        # Buddy was only an enemy of Friend (game 6) and a teammate of Ole's alt.
        self.assertEqual(
            self.service.person_overview(MatchStatisticsFilter(person_ids=(self.friend.id,), with_person_id=self.buddy.id)),
            [],
        )
        self.assertEqual(
            self.games_and_wins(
                self.service.person_overview(MatchStatisticsFilter(person_ids=(self.ole.id,), with_person_id=self.buddy.id)),
                person_name="Ole",
            ),
            (1, 1),
        )

    def test_positions_leave_out_games_without_a_role(self):
        rows = self.service.positions(MatchStatisticsFilter(person_ids=(self.ole.id,)))

        self.assertEqual([(row["team_position"], row["games"], row["wins"]) for row in rows], [("MIDDLE", 3, 2)])

    def test_champion_rows_include_images(self):
        self.ole_champion = Champion.query.filter_by(riot_champion_id=LUX).one()
        self.ole_champion.image = "Lux.png"
        db.session.commit()

        rows = self.service.champion_overview(MatchStatisticsFilter(person_ids=(self.ole.id,)))

        self.assertEqual(self.record(rows, champion_name="Lux")["champion_image"], "Lux.png")

    def test_person_pairs_count_same_team_games_only(self):
        rows = self.service.person_pairs()

        self.assertEqual(self.games_and_wins(rows, person_name="Ole", other_person_name="Friend"), (2, 1))
        self.assertEqual(self.games_and_wins(rows, person_name="Ole", other_person_name="Buddy"), (1, 1))
        self.assertEqual(len(rows), 2)

        buddy_pairs = self.service.person_pairs(MatchStatisticsFilter(person_ids=(self.buddy.id,)))
        self.assertEqual([(row["person_name"], row["other_person_name"]) for row in buddy_pairs], [("Ole", "Buddy")])

    def test_queue_date_and_minimum_game_filters(self):
        ranked = self.service.person_overview(MatchStatisticsFilter(person_ids=(self.ole.id,), queue_ids=(420,)))
        later = self.service.person_overview(
            MatchStatisticsFilter(person_ids=(self.ole.id,), start=JAN_1 + timedelta(days=2))
        )
        frequent = self.service.champion_overview(MatchStatisticsFilter(min_games=2))

        self.assertEqual(self.games_and_wins(ranked, person_name="Ole"), (2, 1))
        self.assertEqual(self.games_and_wins(later, person_name="Ole"), (3, 2))
        self.assertEqual({row["champion_name"] for row in frequent}, {"Twitch", "Lux"})

    def test_rows_are_sorted_by_wilson_lower_bound(self):
        rows = self.service.champion_overview()

        self.assertEqual(rows[0]["champion_name"], "Twitch")
        self.assertEqual([row["wilson_lower"] for row in rows], sorted((row["wilson_lower"] for row in rows), reverse=True))
        self.assertGreater(
            MatchStatisticsService.wilson_lower_bound(30, 45),
            MatchStatisticsService.wilson_lower_bound(3, 3),
        )
        self.assertEqual(MatchStatisticsService.wilson_lower_bound(0, 0), 0.0)

    def test_unknown_champions_have_no_name(self):
        self.add_game(7, 420, [(self.main, UNKNOWN, 100, "MIDDLE", True)])
        db.session.commit()

        rows = self.service.champion_overview(MatchStatisticsFilter(person_ids=(self.ole.id,)))

        self.assertIsNone(self.record(rows, riot_champion_id=UNKNOWN)["champion_name"])

    def test_summary_counts_distinct_games_per_queue(self):
        everyone = self.service.summary()
        ole = self.service.summary(MatchStatisticsFilter(person_ids=(self.ole.id,)))

        self.assertEqual(everyone["games"], 5)
        self.assertEqual(ole["games_per_queue"], {400: 1, 420: 2, 450: 1})
        self.assertEqual(ole["first_game"], JAN_1 + timedelta(days=1))
        self.assertEqual(ole["last_game"], JAN_1 + timedelta(days=4))

    def test_patch_filter_selects_one_or_several_patches(self):
        ole = (self.ole.id,)

        one = self.service.person_overview(MatchStatisticsFilter(person_ids=ole, patches=("16.9",)))
        both = self.service.person_overview(MatchStatisticsFilter(person_ids=ole, patches=("16.9", "16.18")))
        none = self.service.person_overview(MatchStatisticsFilter(person_ids=ole, patches=("15.1",)))

        self.assertEqual(self.games_and_wins(one, person_name="Ole"), (1, 1))
        self.assertEqual(self.games_and_wins(both, person_name="Ole"), (4, 3))
        self.assertEqual(none, [])

    def test_patch_results_are_newest_patch_first(self):
        rows = self.service.patch_results(MatchStatisticsFilter(person_ids=(self.ole.id,)))

        self.assertEqual([(row["patch"], row["games"], row["wins"]) for row in rows], [("16.18", 3, 2), ("16.9", 1, 1)])

    def test_summary_and_available_patches_sort_numerically(self):
        summary = self.service.summary()

        self.assertEqual(summary["games_per_patch"], {"16.18": 4, "16.9": 1})
        self.assertEqual(MatchStatisticsService.available_patches(), ["16.18", "16.9"])

    def test_deleted_person_no_longer_counts(self):
        PersonService.delete_person(self.friend)

        persons = {row["person_name"] for row in self.service.person_overview()}
        pairs = self.service.person_pairs()

        self.assertEqual(persons, {"Ole", "Buddy"})
        self.assertEqual([(row["person_name"], row["other_person_name"]) for row in pairs], [("Ole", "Buddy")])


if __name__ == "__main__":
    unittest.main()
