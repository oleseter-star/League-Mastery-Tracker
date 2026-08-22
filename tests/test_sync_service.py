import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.sync_service import SyncService


class FakeRiotService:
    """
    Predictable replacement for RiotService used by automated tests.
    """

    def __init__(
        self,
        mastery_by_puuid=None,
        failing_puuids=None,
    ):
        self.mastery_by_puuid = mastery_by_puuid or {}
        self.failing_puuids = set(
            failing_puuids or []
        )
        self.calls = []

    def get_champion_mastery(
        self,
        puuid,
        platform_region,
    ):
        self.calls.append(
            {
                "puuid": puuid,
                "platform_region": platform_region,
            }
        )

        if puuid in self.failing_puuids:
            raise RuntimeError(
                f"Simulated Riot failure for {puuid}"
            )

        return self.mastery_by_puuid.get(
            puuid,
            [],
        )


class SyncServiceTestCase(unittest.TestCase):
    """
    Tests SyncService against an isolated in-memory database.
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
            display_name="Test Person"
        )

        db.session.add(
            self.person
        )

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

    def create_account(
        self,
        puuid,
        game_name,
        last_sync=None,
    ):
        """
        Create and persist one test Riot Account.
        """

        account = RiotAccount(
            person_id=self.person.id,
            game_name=game_name,
            tag_line="TEST",
            puuid=puuid,
            platform_region="EUW1",
            last_sync=last_sync,
        )

        db.session.add(
            account
        )

        db.session.commit()

        return account

    def test_stale_sync_selects_never_and_old_accounts(self):
        """
        Never-synced and 25-hour-old accounts should be updated,
        while a one-hour-old account should be skipped.
        """

        current_time = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        never_account = self.create_account(
            puuid="puuid-never",
            game_name="Never",
            last_sync=None,
        )

        stale_account = self.create_account(
            puuid="puuid-stale",
            game_name="Stale",
            last_sync=(
                current_time
                - timedelta(hours=25)
            ),
        )

        fresh_sync_time = (
            current_time
            - timedelta(hours=1)
        )

        fresh_account = self.create_account(
            puuid="puuid-fresh",
            game_name="Fresh",
            last_sync=fresh_sync_time,
        )

        fake_riot_service = FakeRiotService(
            mastery_by_puuid={
                "puuid-never": [],
                "puuid-stale": [],
                "puuid-fresh": [],
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        result = service.sync_stale_accounts(
            max_age_hours=24
        )

        called_puuids = {
            call["puuid"]
            for call in fake_riot_service.calls
        }

        self.assertEqual(
            result["total_accounts"],
            3,
        )

        self.assertEqual(
            result["selected_accounts"],
            2,
        )

        self.assertEqual(
            result["updated"],
            2,
        )

        self.assertEqual(
            result["skipped"],
            1,
        )

        self.assertEqual(
            result["failed"],
            0,
        )

        self.assertEqual(
            called_puuids,
            {
                never_account.puuid,
                stale_account.puuid,
            },
        )

        refreshed_fresh_account = db.session.get(
            RiotAccount,
            fresh_account.id,
        )

        self.assertEqual(
            refreshed_fresh_account.last_sync,
            fresh_sync_time,
        )

    def test_force_sync_selects_all_accounts(self):
        """
        Force synchronization should update every account,
        including recently synchronized accounts.
        """

        current_time = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        first_account = self.create_account(
            puuid="puuid-first",
            game_name="First",
            last_sync=current_time,
        )

        second_account = self.create_account(
            puuid="puuid-second",
            game_name="Second",
            last_sync=current_time,
        )

        fake_riot_service = FakeRiotService(
            mastery_by_puuid={
                "puuid-first": [],
                "puuid-second": [],
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        result = service.sync_all_accounts()

        called_puuids = {
            call["puuid"]
            for call in fake_riot_service.calls
        }

        self.assertEqual(
            result["total_accounts"],
            2,
        )

        self.assertEqual(
            result["selected_accounts"],
            2,
        )

        self.assertEqual(
            result["updated"],
            2,
        )

        self.assertEqual(
            result["skipped"],
            0,
        )

        self.assertEqual(
            result["failed"],
            0,
        )

        self.assertEqual(
            called_puuids,
            {
                first_account.puuid,
                second_account.puuid,
            },
        )

    def test_one_failure_does_not_stop_other_accounts(self):
        """
        A failed Riot request for one account must not stop
        synchronization of the following accounts.
        """

        failing_account = self.create_account(
            puuid="puuid-failing",
            game_name="Failing",
        )

        successful_account = self.create_account(
            puuid="puuid-successful",
            game_name="Successful",
        )

        fake_riot_service = FakeRiotService(
            mastery_by_puuid={
                "puuid-successful": [
                    {
                        "championId": 266,
                        "championPoints": 12345,
                    }
                ]
            },
            failing_puuids={
                "puuid-failing"
            },
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        result = service.sync_all_accounts()

        self.assertEqual(
            result["updated"],
            1,
        )

        self.assertEqual(
            result["failed"],
            1,
        )

        self.assertEqual(
            len(fake_riot_service.calls),
            2,
        )

        refreshed_failing_account = db.session.get(
            RiotAccount,
            failing_account.id,
        )

        refreshed_successful_account = db.session.get(
            RiotAccount,
            successful_account.id,
        )

        self.assertIsNone(
            refreshed_failing_account.last_sync
        )

        self.assertIsNotNone(
            refreshed_successful_account.last_sync
        )

        self.assertEqual(
            result["failures"][0]["riot_account_id"],
            failing_account.id,
        )

    def test_failed_sync_preserves_existing_mastery(self):
        """
        Existing cached mastery and last_sync must remain unchanged
        when Riot cannot provide new data.
        """

        old_sync_time = (
            datetime.now(timezone.utc)
            - timedelta(days=2)
        ).replace(
            tzinfo=None
        )

        account = self.create_account(
            puuid="puuid-preserve",
            game_name="Preserve",
            last_sync=old_sync_time,
        )

        champion = Champion(
            riot_champion_id=103,
            name="Ahri",
            image=None,
            source="manual",
        )

        db.session.add(
            champion
        )

        db.session.flush()

        mastery = ChampionMastery(
            riot_account_id=account.id,
            champion_id=champion.id,
            mastery_points=50000,
        )

        db.session.add(
            mastery
        )

        db.session.commit()

        fake_riot_service = FakeRiotService(
            failing_puuids={
                "puuid-preserve"
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        result = service.sync_all_accounts()

        preserved_account = db.session.get(
            RiotAccount,
            account.id,
        )

        preserved_mastery = (
            ChampionMastery.query.filter_by(
                riot_account_id=account.id,
                champion_id=champion.id,
            ).one()
        )

        self.assertEqual(
            result["failed"],
            1,
        )

        self.assertEqual(
            preserved_mastery.mastery_points,
            50000,
        )

        self.assertEqual(
            preserved_account.last_sync,
            old_sync_time,
        )

    def test_unknown_champion_is_created(self):
        """
        A champion missing from local reference data must still be
        stored together with its mastery points.
        """

        account = self.create_account(
            puuid="puuid-unknown",
            game_name="Unknown",
        )

        fake_riot_service = FakeRiotService(
            mastery_by_puuid={
                "puuid-unknown": [
                    {
                        "championId": 999999,
                        "championPoints": 43210,
                    }
                ]
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        result = service.sync_mastery(
            riot_account_id=account.id
        )

        champion = Champion.query.filter_by(
            riot_champion_id=999999
        ).one()

        mastery = ChampionMastery.query.filter_by(
            riot_account_id=account.id,
            champion_id=champion.id,
        ).one()

        self.assertEqual(
            result["mastery_records"],
            1,
        )

        self.assertIsNone(
            champion.name
        )

        self.assertIsNone(
            champion.image
        )

        self.assertEqual(
            champion.source,
            "riot",
        )

        self.assertEqual(
            mastery.mastery_points,
            43210,
        )

    def test_successful_sync_replaces_current_mastery_cache(self):
        """
        Mastery records absent from Riot's latest response should be
        removed from the account's current-state cache.
        """

        account = self.create_account(
            puuid="puuid-replace",
            game_name="Replace",
        )

        first_champion = Champion(
            riot_champion_id=1,
            name="Annie",
            source="manual",
        )

        second_champion = Champion(
            riot_champion_id=2,
            name="Olaf",
            source="manual",
        )

        db.session.add_all(
            [
                first_champion,
                second_champion,
            ]
        )

        db.session.flush()

        db.session.add_all(
            [
                ChampionMastery(
                    riot_account_id=account.id,
                    champion_id=first_champion.id,
                    mastery_points=100,
                ),
                ChampionMastery(
                    riot_account_id=account.id,
                    champion_id=second_champion.id,
                    mastery_points=200,
                ),
            ]
        )

        db.session.commit()

        fake_riot_service = FakeRiotService(
            mastery_by_puuid={
                "puuid-replace": [
                    {
                        "championId": 1,
                        "championPoints": 999,
                    }
                ]
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        service.sync_mastery(
            riot_account_id=account.id
        )

        remaining_masteries = (
            ChampionMastery.query.filter_by(
                riot_account_id=account.id
            )
            .order_by(
                ChampionMastery.id
            )
            .all()
        )

        self.assertEqual(
            len(remaining_masteries),
            1,
        )

        self.assertEqual(
            remaining_masteries[0].champion_id,
            first_champion.id,
        )

        self.assertEqual(
            remaining_masteries[0].mastery_points,
            999,
        )


if __name__ == "__main__":
    unittest.main()