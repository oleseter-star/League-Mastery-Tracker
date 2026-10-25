import unittest
from datetime import date, datetime, timedelta

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    ChampionMasteryHistory,
    Person,
    RiotAccount,
)
from application.services.mastery_history_service import (
    MasteryHistoryService,
)
from application.services.sync_service import SyncService


class FakeRiotService:
    """
    Returns whatever mastery the test sets for each PUUID.
    """

    def __init__(self):
        self.mastery_by_puuid = {}

    def get_champion_mastery(
        self,
        puuid,
        platform_region,
    ):
        return self.mastery_by_puuid.get(
            puuid,
            [],
        )


class MasteryHistoryServiceTestCase(unittest.TestCase):
    """
    Tests Mastery history recording and period calculations against
    an isolated in-memory database.
    """

    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(
            self.app
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

        self.person = Person(
            display_name="History Person"
        )

        self.champion = Champion(
            riot_champion_id=103,
            name="Ahri",
            source="manual",
        )

        db.session.add_all(
            [
                self.person,
                self.champion,
            ]
        )

        db.session.flush()

        self.account = RiotAccount(
            person_id=self.person.id,
            game_name="History",
            tag_line="TEST",
            puuid="puuid-history",
            platform_region="EUW1",
        )

        db.session.add(
            self.account
        )

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

    def add_snapshot(
        self,
        recorded_at,
        mastery_points,
        mastery_level=None,
        champion=None,
        account=None,
    ):
        db.session.add(
            ChampionMasteryHistory(
                riot_account_id=(account or self.account).id,
                champion_id=(champion or self.champion).id,
                recorded_at=recorded_at,
                mastery_points=mastery_points,
                mastery_level=mastery_level,
            )
        )

        db.session.commit()

    def history_values(self):
        return [
            (
                snapshot.recorded_at,
                snapshot.mastery_points,
                snapshot.mastery_level,
            )
            for snapshot in (
                ChampionMasteryHistory.query
                .order_by(
                    ChampionMasteryHistory.recorded_at,
                    ChampionMasteryHistory.id,
                )
                .all()
            )
        ]

    def test_sync_records_only_changes(self):
        """
        The first sync records every champion, an unchanged sync
        records nothing, and a changed value records one snapshot.
        """

        fake_riot_service = FakeRiotService()

        service = SyncService(
            riot_service=fake_riot_service
        )

        fake_riot_service.mastery_by_puuid[
            "puuid-history"
        ] = [
            {
                "championId": 103,
                "championPoints": 1000,
                "championLevel": 2,
            }
        ]

        service.sync_mastery(
            riot_account_id=self.account.id
        )

        service.sync_mastery(
            riot_account_id=self.account.id
        )

        self.assertEqual(
            len(self.history_values()),
            1,
        )

        fake_riot_service.mastery_by_puuid[
            "puuid-history"
        ][0]["championPoints"] = 2500

        service.sync_mastery(
            riot_account_id=self.account.id
        )

        self.assertEqual(
            [
                (points, level)
                for _, points, level in self.history_values()
            ],
            [
                (1000, 2),
                (2500, 2),
            ],
        )

    def test_first_sync_keeps_existing_data_as_baseline(self):
        """
        Mastery stored before history existed is recorded at the
        previous sync time before the new value.
        """

        previous_sync = datetime(2026, 9, 1, 12, 0)

        self.account.last_sync = previous_sync

        db.session.add(
            ChampionMastery(
                riot_account_id=self.account.id,
                champion_id=self.champion.id,
                mastery_points=40000,
                mastery_level=6,
            )
        )

        db.session.commit()

        fake_riot_service = FakeRiotService()

        fake_riot_service.mastery_by_puuid[
            "puuid-history"
        ] = [
            {
                "championId": 103,
                "championPoints": 45000,
                "championLevel": 7,
            }
        ]

        SyncService(
            riot_service=fake_riot_service
        ).sync_mastery(
            riot_account_id=self.account.id
        )

        history = self.history_values()

        self.assertEqual(
            history[0],
            (
                previous_sync,
                40000,
                6,
            ),
        )

        self.assertEqual(
            history[1][1:],
            (
                45000,
                7,
            ),
        )

    def test_period_gains_use_values_at_both_ends(self):
        """
        Gains are the difference between the latest snapshots at the
        start and end of the period.
        """

        start = datetime(2026, 10, 1)

        self.add_snapshot(
            start - timedelta(days=10),
            1000,
        )

        self.add_snapshot(
            start + timedelta(days=2),
            1800,
        )

        self.add_snapshot(
            start + timedelta(days=5),
            2600,
        )

        gains = MasteryHistoryService.get_period_gains(
            riot_account_ids=[self.account.id],
            start=start,
            end=start + timedelta(days=4),
        )[self.account.id]

        self.assertEqual(
            gains["gains"],
            {self.champion.id: 800},
        )

        self.assertEqual(
            gains["tracked_since"],
            start - timedelta(days=10),
        )

    def test_period_before_tracking_counts_from_first_snapshot(self):
        """
        A period starting before history began is measured from the
        first snapshot, and a champion first seen later counts from 0.
        """

        tracking_start = datetime(2026, 10, 10)

        other_champion = Champion(
            riot_champion_id=266,
            name="Aatrox",
            source="manual",
        )

        db.session.add(
            other_champion
        )

        db.session.commit()

        self.add_snapshot(
            tracking_start,
            50000,
        )

        self.add_snapshot(
            tracking_start + timedelta(days=3),
            51000,
        )

        self.add_snapshot(
            tracking_start + timedelta(days=3),
            700,
            champion=other_champion,
        )

        gains = MasteryHistoryService.get_period_gains(
            riot_account_ids=[self.account.id],
            start=datetime(2026, 1, 1),
            end=datetime(2026, 11, 1),
        )[self.account.id]

        self.assertEqual(
            gains["gains"],
            {
                self.champion.id: 1000,
                other_champion.id: 700,
            },
        )

    def test_account_without_history_has_no_gains(self):
        gains = MasteryHistoryService.get_period_gains(
            riot_account_ids=[self.account.id],
            start=datetime(2026, 1, 1),
            end=datetime(2026, 11, 1),
        )[self.account.id]

        self.assertIsNone(
            gains["tracked_since"]
        )

        self.assertEqual(
            gains["gains"],
            {},
        )

    def test_resolve_period_presets_and_custom_dates(self):
        now = datetime(2026, 10, 25, 12, 0)

        week = MasteryHistoryService.resolve_period(
            "week",
            now=now,
        )

        self.assertEqual(
            (week["start"], week["end"]),
            (now - timedelta(days=7), now),
        )

        self.assertIsNone(
            MasteryHistoryService.resolve_period("all")
        )

        custom = MasteryHistoryService.resolve_period(
            "custom",
            start_text="2026-10-01",
            end_text="2026-10-01",
        )

        self.assertEqual(
            custom["start_date"],
            date(2026, 10, 1),
        )

        # The end date is inclusive: the range covers one whole day.
        self.assertEqual(
            custom["end"] - custom["start"],
            timedelta(days=1),
        )

    def test_resolve_period_rejects_invalid_input(self):
        for arguments in [
            {"period": "decade"},
            {"period": "custom"},
            {
                "period": "custom",
                "start_text": "2026-10-05",
                "end_text": "2026-10-01",
            },
        ]:
            with self.assertRaises(ValueError):
                MasteryHistoryService.resolve_period(
                    **arguments
                )

    def test_champion_series_marks_level_ups_and_extends_to_last_sync(
        self,
    ):
        self.add_snapshot(
            datetime(2026, 10, 1),
            1000,
            mastery_level=2,
        )

        self.add_snapshot(
            datetime(2026, 10, 5),
            1500,
            mastery_level=2,
        )

        self.add_snapshot(
            datetime(2026, 10, 9),
            2200,
            mastery_level=3,
        )

        self.account.last_sync = datetime(2026, 10, 20)

        db.session.add(
            ChampionMastery(
                riot_account_id=self.account.id,
                champion_id=self.champion.id,
                mastery_points=2200,
                mastery_level=3,
            )
        )

        db.session.commit()

        series = MasteryHistoryService.get_champion_series(
            riot_accounts=[self.account],
            champion_id=self.champion.id,
        )

        points = series[0]["points"]

        self.assertEqual(
            [point["level_up"] for point in points],
            [False, False, True, False],
        )

        self.assertEqual(
            points[-1]["recorded_at"],
            "2026-10-20T00:00:00Z",
        )

        self.assertEqual(
            points[-1]["mastery_points"],
            2200,
        )

    def test_champion_series_is_not_extended_without_current_mastery(
        self,
    ):
        """
        A champion the latest sync no longer returned keeps its last
        recorded point instead of a line to the last sync.
        """

        self.add_snapshot(
            datetime(2026, 10, 1),
            1000,
        )

        self.account.last_sync = datetime(2026, 10, 20)

        db.session.commit()

        points = MasteryHistoryService.get_champion_series(
            riot_accounts=[self.account],
            champion_id=self.champion.id,
        )[0]["points"]

        self.assertEqual(
            [point["recorded_at"] for point in points],
            ["2026-10-01T00:00:00Z"],
        )

    def test_sync_removes_history_of_unused_classic_champion(self):
        """
        Classic history is removed together with its unused champion,
        so no snapshot points at a deleted champion.
        """

        classic_champion = Champion(
            riot_champion_id=60103,
            name=None,
            source="riot",
        )

        db.session.add(
            classic_champion
        )

        db.session.commit()

        self.add_snapshot(
            datetime(2026, 10, 1),
            900,
            champion=classic_champion,
        )

        SyncService(
            riot_service=FakeRiotService()
        ).sync_mastery(
            riot_account_id=self.account.id
        )

        self.assertIsNone(
            db.session.get(
                Champion,
                classic_champion.id,
            )
        )

        self.assertEqual(
            ChampionMasteryHistory.query.count(),
            0,
        )

    def test_deleting_account_removes_its_history(self):
        self.add_snapshot(
            datetime(2026, 10, 1),
            1000,
        )

        db.session.delete(
            self.account
        )

        db.session.commit()

        self.assertEqual(
            ChampionMasteryHistory.query.count(),
            0,
        )


if __name__ == "__main__":
    unittest.main()
