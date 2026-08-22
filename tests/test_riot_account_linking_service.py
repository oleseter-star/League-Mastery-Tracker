import unittest
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.database.models import (
    Person,
    RiotAccount,
)
from application.services.sync_service import SyncService


class FakeRiotAccountService:
    """
    Predictable Riot account lookup used by automated tests.
    """

    def __init__(
        self,
        account_data=None,
    ):
        self.account_data = account_data or {
            "puuid": "test-puuid",
            "gameName": "CanonicalName",
            "tagLine": "EUW",
        }

        self.account_calls = []
        self.mastery_calls = []

    def get_account_by_riot_id(
        self,
        game_name,
        tag_line,
        platform_region,
    ):
        self.account_calls.append(
            {
                "game_name": game_name,
                "tag_line": tag_line,
                "platform_region": platform_region,
            }
        )

        return dict(
            self.account_data
        )

    def get_champion_mastery(
        self,
        puuid,
        platform_region,
    ):
        self.mastery_calls.append(
            {
                "puuid": puuid,
                "platform_region": platform_region,
            }
        )

        raise AssertionError(
            "Mastery must not be requested while linking an account."
        )


class RiotAccountLinkingServiceTestCase(unittest.TestCase):
    """
    Tests account linking through SyncService.sync_account().
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
            display_name="Primary Person"
        )

        db.session.add(
            self.person
        )

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

    def create_person(
        self,
        display_name,
    ):
        person = Person(
            display_name=display_name
        )

        db.session.add(
            person
        )

        db.session.commit()

        return person

    def create_account(
        self,
        person,
        puuid="existing-puuid",
        game_name="ExistingName",
        tag_line="OLD",
        platform_region="EUW1",
    ):
        account = RiotAccount(
            person_id=person.id,
            game_name=game_name,
            tag_line=tag_line,
            puuid=puuid,
            platform_region=platform_region,
        )

        db.session.add(
            account
        )

        db.session.commit()

        return account

    def test_link_account_fetches_puuid_and_canonical_riot_id(self):
        """
        Linking should store Riot's canonical identity and PUUID.
        """

        fake_riot_service = FakeRiotAccountService(
            account_data={
                "puuid": "canonical-puuid",
                "gameName": "Canonical Name",
                "tagLine": "EUW",
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        account = service.sync_account(
            person_id=self.person.id,
            game_name=" entered name ",
            tag_line=" entered-tag ",
            platform_region="euw1",
        )

        self.assertIsNotNone(
            account.id
        )

        self.assertEqual(
            account.person_id,
            self.person.id,
        )

        self.assertEqual(
            account.puuid,
            "canonical-puuid",
        )

        self.assertEqual(
            account.game_name,
            "Canonical Name",
        )

        self.assertEqual(
            account.tag_line,
            "EUW",
        )

        self.assertEqual(
            account.platform_region,
            "EUW1",
        )

        self.assertIsNone(
            account.last_sync
        )

        self.assertEqual(
            RiotAccount.query.count(),
            1,
        )

        self.assertEqual(
            len(fake_riot_service.account_calls),
            1,
        )

        self.assertEqual(
            fake_riot_service.mastery_calls,
            [],
        )

    def test_link_account_uses_entered_identity_when_riot_omits_names(self):
        """
        Entered Riot ID values should be used if Riot only returns
        the account PUUID.
        """

        fake_riot_service = FakeRiotAccountService(
            account_data={
                "puuid": "fallback-puuid",
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        account = service.sync_account(
            person_id=self.person.id,
            game_name="Fallback Name",
            tag_line="TAG",
            platform_region="EUW1",
        )

        self.assertEqual(
            account.game_name,
            "Fallback Name",
        )

        self.assertEqual(
            account.tag_line,
            "TAG",
        )

    def test_link_account_rejects_unknown_person(self):
        """
        Account lookup must not run when the target Person does not
        exist.
        """

        fake_riot_service = FakeRiotAccountService()

        service = SyncService(
            riot_service=fake_riot_service
        )

        with self.assertRaisesRegex(
            ValueError,
            "Person with ID 999999 was not found.",
        ):
            service.sync_account(
                person_id=999999,
                game_name="Unknown",
                tag_line="TEST",
                platform_region="EUW1",
            )

        self.assertEqual(
            RiotAccount.query.count(),
            0,
        )

        self.assertEqual(
            fake_riot_service.account_calls,
            [],
        )

    def test_link_account_rejects_duplicate_puuid_owned_by_other_person(self):
        """
        One PUUID must never be connected to two Persons.
        """

        other_person = self.create_person(
            display_name="Other Person"
        )

        existing_account = self.create_account(
            person=other_person,
            puuid="duplicate-puuid",
        )

        fake_riot_service = FakeRiotAccountService(
            account_data={
                "puuid": "duplicate-puuid",
                "gameName": "Updated Name",
                "tagLine": "NEW",
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        with self.assertRaisesRegex(
            ValueError,
            (
                "This Riot Account is already connected "
                "to another Person."
            ),
        ):
            service.sync_account(
                person_id=self.person.id,
                game_name="Updated Name",
                tag_line="NEW",
                platform_region="EUW1",
            )

        stored_account = db.session.get(
            RiotAccount,
            existing_account.id,
        )

        self.assertEqual(
            RiotAccount.query.count(),
            1,
        )

        self.assertEqual(
            stored_account.person_id,
            other_person.id,
        )

        self.assertEqual(
            stored_account.game_name,
            "ExistingName",
        )

        self.assertEqual(
            stored_account.tag_line,
            "OLD",
        )

    def test_link_existing_account_for_same_person_updates_identity(self):
        """
        The same PUUID under the same Person should update its
        changeable Riot ID fields instead of creating a duplicate.
        """

        existing_account = self.create_account(
            person=self.person,
            puuid="same-person-puuid",
            game_name="Old Name",
            tag_line="OLD",
            platform_region="NA1",
        )

        fake_riot_service = FakeRiotAccountService(
            account_data={
                "puuid": "same-person-puuid",
                "gameName": "New Name",
                "tagLine": "NEW",
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        result = service.sync_account(
            person_id=self.person.id,
            game_name="New Name",
            tag_line="NEW",
            platform_region="EUW1",
        )

        self.assertEqual(
            result.id,
            existing_account.id,
        )

        self.assertEqual(
            RiotAccount.query.count(),
            1,
        )

        self.assertEqual(
            result.game_name,
            "New Name",
        )

        self.assertEqual(
            result.tag_line,
            "NEW",
        )

        self.assertEqual(
            result.platform_region,
            "EUW1",
        )

        self.assertEqual(
            fake_riot_service.mastery_calls,
            [],
        )

    def test_link_account_rejects_missing_puuid(self):
        """
        Invalid Riot account data must not create a local account.
        """

        fake_riot_service = FakeRiotAccountService(
            account_data={
                "gameName": "Missing",
                "tagLine": "PUUID",
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        with self.assertRaisesRegex(
            ValueError,
            "Riot account data did not contain a PUUID.",
        ):
            service.sync_account(
                person_id=self.person.id,
                game_name="Missing",
                tag_line="PUUID",
                platform_region="EUW1",
            )

        self.assertEqual(
            RiotAccount.query.count(),
            0,
        )

    def test_link_account_rejects_unsupported_platform(self):
        """
        Platform validation must happen before Riot is contacted.
        """

        fake_riot_service = FakeRiotAccountService()

        service = SyncService(
            riot_service=fake_riot_service
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported platform region: INVALID",
        ):
            service.sync_account(
                person_id=self.person.id,
                game_name="Test",
                tag_line="TEST",
                platform_region="invalid",
            )

        self.assertEqual(
            RiotAccount.query.count(),
            0,
        )

        self.assertEqual(
            fake_riot_service.account_calls,
            [],
        )

    def test_link_account_rolls_back_when_commit_fails(self):
        """
        A failed commit must not leave a pending Riot Account.
        """

        fake_riot_service = FakeRiotAccountService(
            account_data={
                "puuid": "rollback-puuid",
                "gameName": "Rollback",
                "tagLine": "TEST",
            }
        )

        service = SyncService(
            riot_service=fake_riot_service
        )

        with patch(
            (
                "application.services.sync_service."
                "db.session.commit"
            ),
            side_effect=RuntimeError(
                "Simulated commit failure"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Simulated commit failure",
            ):
                service.sync_account(
                    person_id=self.person.id,
                    game_name="Rollback",
                    tag_line="TEST",
                    platform_region="EUW1",
                )

        self.assertEqual(
            RiotAccount.query.count(),
            0,
        )


if __name__ == "__main__":
    unittest.main()