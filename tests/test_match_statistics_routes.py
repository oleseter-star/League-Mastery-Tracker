import unittest
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, Flask

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
from application.routes.match_statistics import match_statistics_bp


KALISTA, THRESH, ZED, AHRI, SETT = 429, 412, 238, 103, 875
JAN_1 = datetime(2026, 1, 1, 12, 0)


home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def home():
    return "Test home"


class MatchStatisticsRouteTests(unittest.TestCase):
    """
    Ole plays Kalista bot, often with Friend on Thresh support.
    """

    def setUp(self):
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).resolve().parents[1] / "application" / "templates"),
        )
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="match-statistics-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(self.app)

        for blueprint in (home_bp, match_review_bp, match_statistics_bp, champion_images_bp):
            self.app.register_blueprint(blueprint)

        self.app.jinja_env.globals["csrf_token"] = lambda: "test-csrf-token"
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.ole = Person(display_name="Ole")
        self.friend = Person(display_name="Friend")
        self.main = RiotAccount(person=self.ole, game_name="Main", tag_line="EUW", puuid="p-main", platform_region="EUW1")
        self.friend_account = RiotAccount(person=self.friend, game_name="Friend", tag_line="EUW", puuid="p-friend", platform_region="EUW1")

        for riot_champion_id, name in ((KALISTA, "Kalista"), (THRESH, "Thresh"), (ZED, "Zed"), (AHRI, "Ahri"), (SETT, "Sett")):
            db.session.add(Champion(riot_champion_id=riot_champion_id, name=name, image=f"{name}.png", source="bundled"))

        db.session.add_all([self.ole, self.friend])
        db.session.commit()

        # Four Solo/Duo games on 16.20 and 16.21: Kalista + Thresh vs Zed mid
        # and Ahri bot. One Flex game on Sett top without Friend.
        for number, win in ((1, True), (2, True), (3, False), (4, True)):
            self.add_game(number, 420, "16.20" if number < 3 else "16.21", [
                (self.main, KALISTA, 100, "BOTTOM", win),
                (self.friend_account, THRESH, 100, "UTILITY", win),
                (None, ZED, 200, "MIDDLE", not win),
                (None, AHRI, 200, "BOTTOM", not win),
            ])

        self.add_game(5, 440, "16.21", [(self.main, SETT, 100, "TOP", False)])
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def add_game(self, number, queue_id, patch, participants):
        match = Match(
            riot_match_id=f"EUW1_{number}",
            platform_id="EUW1",
            queue_id=queue_id,
            patch=patch,
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

    def get_page(self, url):
        response = self.client.get(url)
        page = response.get_data(as_text=True)
        response.close()
        return response.status_code, page

    def test_champions_page_lists_champions_with_links_and_icons(self):
        status, page = self.get_page(f"/matches?person={self.ole.id}&min_games=1")

        self.assertEqual(status, 200)
        self.assertIn("/champions/images/Kalista.png", page)
        self.assertIn(f'/matches/champions/{KALISTA}?person={self.ole.id}&amp;min_games=1"', page)
        self.assertIn(">60%<", page)
        self.assertIn("Win rate (3–2)", page)
        self.assertIn("Games from 2026-01-02 to 2026-01-06.", " ".join(page.split()))

    def test_filters_narrow_the_champions(self):
        _, solo = self.get_page(f"/matches?person={self.ole.id}&mode=solo&min_games=1")
        _, flex = self.get_page(f"/matches?person={self.ole.id}&mode=flex&min_games=1")
        _, newest = self.get_page(f"/matches?person={self.ole.id}&patch_from=16.21&min_games=1")
        _, top = self.get_page(f"/matches?person={self.ole.id}&position=TOP&min_games=1")
        _, default_min = self.get_page(f"/matches?person={self.ole.id}")

        self.assertIn(">Kalista<", solo)
        self.assertNotIn(">Sett<", solo)
        self.assertIn(">Sett<", flex)
        self.assertNotIn(">Kalista<", flex)
        self.assertIn("50%", newest)
        self.assertIn(">Sett<", top)
        self.assertNotIn(">Kalista<", top)
        # Sett has one game, below the default minimum of 3.
        self.assertIn(">Kalista<", default_min)
        self.assertNotIn(">Sett<", default_min)

    def test_unknown_filter_values_are_ignored(self):
        status, page = self.get_page("/matches?person=999&mode=aram&patch_from=1.1&position=MID&min_games=7")

        self.assertEqual(status, 200)
        self.assertIn(">Kalista<", page)
        self.assertIn("Choose a person to see their overall win rate.", page)

    def test_champion_page_shows_allies_and_enemies_by_role_and_persons(self):
        status, page = self.get_page(f"/matches/champions/{KALISTA}?person={self.ole.id}&min_games=1")

        self.assertEqual(status, 200)
        self.assertIn("75%", page)
        self.assertIn("3–1 in 4 games", page)
        self.assertIn('aria-label="With Support"', page)
        self.assertIn('aria-label="Against Mid"', page)
        self.assertIn("Lane opponent", page)
        self.assertIn("/champions/images/Thresh.png", page)
        self.assertIn("/champions/images/Ahri.png", page)
        self.assertIn(f'href="/matches/with/{self.friend.id}?person={self.ole.id}&amp;min_games=1"', page)
        self.assertIn(">26.21<", page)
        self.assertIn(f'href="/matches?person={self.ole.id}&amp;min_games=1"', page)

    def test_champion_page_without_games_and_unknown_champion(self):
        status, page = self.get_page(f"/matches/champions/{ZED}?person={self.ole.id}")
        self.assertEqual(status, 200)
        self.assertIn("No games on Zed for these filters.", page)

        status, _ = self.get_page("/matches/champions/99999")
        self.assertEqual(status, 404)

    def test_persons_section_for_everyone_links_to_each_person(self):
        _, page = self.get_page("/matches?min_games=1")

        self.assertIn(f'href="/matches?person={self.ole.id}&amp;min_games=1"', page)
        self.assertIn(f'href="/matches?person={self.friend.id}&amp;min_games=1"', page)
        self.assertIn("Each person's own record.", page)

    def test_persons_section_for_one_person_links_to_the_with_page(self):
        _, page = self.get_page(f"/matches?person={self.ole.id}&min_games=1")

        self.assertIn("With persons", page)
        self.assertIn(f'href="/matches/with/{self.friend.id}?person={self.ole.id}&amp;min_games=1"', page)

    def test_with_page_shows_record_and_both_champion_pools(self):
        status, page = self.get_page(f"/matches/with/{self.friend.id}?person={self.ole.id}&min_games=1")
        text = " ".join(page.split())

        self.assertEqual(status, 200)
        self.assertIn("Ole with Friend", text)
        self.assertIn("Win rate (3–1)", text)
        self.assertIn(">4</span> <span class=\"count-label\">Games together", text)
        self.assertIn("Ole's champions", text)
        self.assertIn("Friend's champions", text)
        self.assertIn(f'/matches/champions/{KALISTA}?person={self.ole.id}&amp;min_games=1', page)
        self.assertIn("/champions/images/Thresh.png", page)
        # Ole's Sett game was without Friend.
        self.assertNotIn("/champions/images/Sett.png", page)

    def test_with_page_needs_a_different_person(self):
        _, without_person = self.get_page(f"/matches/with/{self.friend.id}")
        _, same_person = self.get_page(f"/matches/with/{self.friend.id}?person={self.friend.id}")
        status, _ = self.get_page("/matches/with/999")

        self.assertIn("Choose who plays with Friend.", without_person)
        self.assertIn("Choose who plays with Friend.", same_person)
        self.assertEqual(status, 404)

    def test_with_page_without_shared_games(self):
        self.add_game(6, 420, "16.21", [(self.friend_account, THRESH, 200, "UTILITY", True)])
        loner = Person(display_name="Loner")
        db.session.add(loner)
        db.session.commit()

        _, page = self.get_page(f"/matches/with/{loner.id}?person={self.ole.id}")

        self.assertIn("have no games on the same team for these filters.", " ".join(page.split()))

    def test_games_page_lists_cards_newest_first(self):
        status, page = self.get_page(f"/matches/games?person={self.ole.id}")
        text = " ".join(page.split())

        self.assertEqual(status, 200)
        self.assertIn("5 games", text)
        self.assertIn("· 3–2 · 60%", text)
        self.assertLess(page.index("EUW1_5"), page.index("EUW1_1"))
        self.assertIn("Ole · Main#EUW", text)
        self.assertIn("/champions/images/Thresh.png", page)

    def test_games_page_drill_down_by_champion_teammate_ally_and_enemy(self):
        base = f"/matches/games?person={self.ole.id}&champion={KALISTA}"

        _, on_kalista = self.get_page(base)
        _, with_friend = self.get_page(f"/matches/games?person={self.ole.id}&with={self.friend.id}")
        _, with_thresh = self.get_page(f"{base}&ally={THRESH}&ally_role=UTILITY")
        _, against_ahri_bot = self.get_page(f"{base}&enemy={AHRI}&enemy_role=BOTTOM")
        _, against_ahri_top = self.get_page(f"{base}&enemy={AHRI}&enemy_role=TOP")

        self.assertIn("4 games", " ".join(on_kalista.split()))
        self.assertIn("on Kalista", " ".join(on_kalista.split()))
        self.assertIn("with Friend", " ".join(with_friend.split()))
        self.assertIn("with Thresh (Support)", " ".join(with_thresh.split()))
        self.assertIn("against Ahri (Bot)", " ".join(against_ahri_bot.split()))
        self.assertEqual(against_ahri_bot.count("match-team__member--focus"), 4)
        self.assertIn("4 games", " ".join(against_ahri_bot.split()))
        self.assertIn("No games match.", against_ahri_top)
        # The filter form keeps the drill-down when filters change.
        self.assertIn(f'<input type="hidden" name="enemy" value="{AHRI}">', against_ahri_bot)

    def test_games_page_pages_through_games(self):
        for number in range(10, 35):
            self.add_game(number, 420, "16.21", [(self.main, SETT, 100, "TOP", True)])

        db.session.commit()

        _, first = self.get_page(f"/matches/games?person={self.ole.id}&mode=solo")
        _, second = self.get_page(f"/matches/games?person={self.ole.id}&mode=solo&page=2")

        self.assertIn("Page 1 of 2", first)
        self.assertIn(f'href="?person={self.ole.id}&amp;mode=solo&amp;page=2"', first)
        self.assertIn("EUW1_1", second)
        self.assertNotIn("EUW1_34", second)

    def test_statistics_link_their_games(self):
        _, overview = self.get_page(f"/matches?person={self.ole.id}&min_games=1")
        _, champion = self.get_page(f"/matches/champions/{KALISTA}?person={self.ole.id}&min_games=1")
        _, together = self.get_page(f"/matches/with/{self.friend.id}?person={self.ole.id}&min_games=1")

        self.assertIn(f"/matches/games?person={self.ole.id}&amp;min_games=1&amp;champion={KALISTA}", overview)
        self.assertIn(f"/matches/games?person={self.ole.id}&amp;min_games=1&amp;with={self.friend.id}", overview)
        self.assertIn(f"champion={KALISTA}&amp;ally={THRESH}&amp;ally_role=UTILITY", champion)
        self.assertIn(f"champion={KALISTA}&amp;enemy={AHRI}&amp;enemy_role=BOTTOM", champion)
        self.assertIn("Show 4 games", champion)
        self.assertIn("patch_from=16.21&amp;patch_to=16.21", champion)
        self.assertIn("Show 4 games together", together)
        self.assertIn(f"person={self.friend.id}&amp;min_games=1&amp;champion={THRESH}&amp;with={self.ole.id}", together)

    def test_patch_presets_select_the_newest_patches(self):
        _, latest = self.get_page(f"/matches?person={self.ole.id}&patches=latest&min_games=1")
        _, unknown = self.get_page(f"/matches?person={self.ole.id}&patches=forever&min_games=1")

        self.assertIn("Win rate (1–2)", latest)
        self.assertIn('<option value="latest" selected>Latest patch</option>', latest)
        self.assertIn("Win rate (3–2)", unknown)

    def test_empty_database_explains_how_to_start(self):
        for match in Match.query.all():
            db.session.delete(match)

        db.session.commit()

        status, page = self.get_page("/matches")

        self.assertEqual(status, 200)
        self.assertIn("No games are stored yet.", page)


if __name__ == "__main__":
    unittest.main()
