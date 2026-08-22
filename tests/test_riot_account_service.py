import unittest
from datetime import datetime
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.riot_account_service import (
    RiotAccountService,
)


class RiotAccountServiceTestCase(unittest.TestCase):
    """
    Tests RiotAccountService against an isolated in-memory database.
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

        self.source_person = Person(
            display_name="Source Person"
        )

        self.target_person = Person(
            display_name="Target Person"
        )

        db.session.add_all(
            [
                self.source_person,
                self.target_person,
            ]
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
        """
        Create and persist one Person.
        """

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
        person=None,
        puuid="test-puuid",
        game_name="Test Account",
        tag_line="TEST",
        platform_region="EUW1",
        last_sync=None,
    ):
        """
        Create and persist one Riot Account.
        """

        owner = (
            person
            or self.source_person
        )

        account = RiotAccount(
            person_id=owner.id,
            game_name=game_name,
            tag_line=tag_line,
            puuid=puuid,
            platform_region=platform_region,
            last_sync=last_sync,
        )

        db.session.add(
            account
        )

        db.session.commit()

        return account

    def test_get_riot_account_by_id_returns_account(self):
        """
        A stored Riot Account should be retrievable by internal ID.
        """

        account = self.create_account()

        result = (
            RiotAccountService
            .get_riot_account_by_id(
                account.id
            )
        )

        self.assertIsNotNone(
            result
        )

        self.assertEqual(
            result.id,
            account.id,
        )

        self.assertEqual(
            result.puuid,
            "test-puuid",
        )

    def test_get_riot_account_by_id_returns_none_for_unknown_id(self):
        """
        An unknown internal ID should return None.
        """

        result = (
            RiotAccountService
            .get_riot_account_by_id(
                999999
            )
        )

        self.assertIsNone(
            result
        )

    def test_move_riot_account_changes_only_person_relationship(self):
        """
        Moving an account should preserve its Riot identity and
        synchronization metadata.
        """

        last_sync = datetime(
            2026,
            7,
            17,
            12,
            30,
        )

        account = self.create_account(
            puuid="move-puuid",
            game_name="Move Account",
            tag_line="MOVE",
            platform_region="NA1",
            last_sync=last_sync,
        )

        result = (
            RiotAccountService
            .move_riot_account(
                source_person_id=(
                    self.source_person.id
                ),
                riot_account_id=account.id,
                target_person_id=(
                    self.target_person.id
                ),
            )
        )

        moved_account = db.session.get(
            RiotAccount,
            account.id,
        )

        self.assertEqual(
            result["riot_account_id"],
            account.id,
        )

        self.assertEqual(
            result["source_person_id"],
            self.source_person.id,
        )

        self.assertEqual(
            result["target_person_id"],
            self.target_person.id,
        )

        self.assertEqual(
            result["riot_id"],
            "Move Account#MOVE",
        )

        self.assertEqual(
            moved_account.person_id,
            self.target_person.id,
        )

        self.assertEqual(
            moved_account.puuid,
            "move-puuid",
        )

        self.assertEqual(
            moved_account.game_name,
            "Move Account",
        )

        self.assertEqual(
            moved_account.tag_line,
            "MOVE",
        )

        self.assertEqual(
            moved_account.platform_region,
            "NA1",
        )

        self.assertEqual(
            moved_account.last_sync,
            last_sync,
        )

    def test_move_riot_account_preserves_mastery_data(self):
        """
        Moving an account must not recreate or delete its mastery
        records.
        """

        account = self.create_account(
            puuid="mastery-puuid"
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
            mastery_points=54321,
        )

        db.session.add(
            mastery
        )

        db.session.commit()

        mastery_id = mastery.id

        RiotAccountService.move_riot_account(
            source_person_id=(
                self.source_person.id
            ),
            riot_account_id=account.id,
            target_person_id=(
                self.target_person.id
            ),
        )

        moved_account = db.session.get(
            RiotAccount,
            account.id,
        )

        preserved_mastery = db.session.get(
            ChampionMastery,
            mastery_id,
        )

        self.assertEqual(
            moved_account.person_id,
            self.target_person.id,
        )

        self.assertIsNotNone(
            preserved_mastery
        )

        self.assertEqual(
            preserved_mastery.riot_account_id,
            account.id,
        )

        self.assertEqual(
            preserved_mastery.champion_id,
            champion.id,
        )

        self.assertEqual(
            preserved_mastery.mastery_points,
            54321,
        )

        self.assertEqual(
            ChampionMastery.query.count(),
            1,
        )

    def test_move_riot_account_rejects_unknown_account(self):
        """
        An unknown Riot Account must not produce a relationship
        change.
        """

        with self.assertRaisesRegex(
            ValueError,
            (
                "The Riot account was not found "
                "for this person."
            ),
        ):
            RiotAccountService.move_riot_account(
                source_person_id=(
                    self.source_person.id
                ),
                riot_account_id=999999,
                target_person_id=(
                    self.target_person.id
                ),
            )

    def test_move_riot_account_rejects_wrong_source_person(self):
        """
        A route or caller must not move an account through a Person
        who does not own it.
        """

        account = self.create_account()

        unrelated_person = self.create_person(
            display_name="Unrelated Person"
        )

        with self.assertRaisesRegex(
            ValueError,
            (
                "The Riot account was not found "
                "for this person."
            ),
        ):
            RiotAccountService.move_riot_account(
                source_person_id=(
                    unrelated_person.id
                ),
                riot_account_id=account.id,
                target_person_id=(
                    self.target_person.id
                ),
            )

        stored_account = db.session.get(
            RiotAccount,
            account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

    def test_move_riot_account_rejects_unknown_target_person(self):
        """
        The target Person must exist before an account can be moved.
        """

        account = self.create_account()

        with self.assertRaisesRegex(
            ValueError,
            "The target person was not found.",
        ):
            RiotAccountService.move_riot_account(
                source_person_id=(
                    self.source_person.id
                ),
                riot_account_id=account.id,
                target_person_id=999999,
            )

        stored_account = db.session.get(
            RiotAccount,
            account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

    def test_move_riot_account_rejects_same_person(self):
        """
        Moving an account to its current owner should be rejected.
        """

        account = self.create_account()

        with self.assertRaisesRegex(
            ValueError,
            (
                "The Riot account already belongs "
                "to the selected person."
            ),
        ):
            RiotAccountService.move_riot_account(
                source_person_id=(
                    self.source_person.id
                ),
                riot_account_id=account.id,
                target_person_id=(
                    self.source_person.id
                ),
            )

        stored_account = db.session.get(
            RiotAccount,
            account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

    def test_move_riot_account_rejects_missing_target_person_id(self):
        """
        A target Person ID is required.
        """

        account = self.create_account()

        with self.assertRaisesRegex(
            ValueError,
            "A target person is required.",
        ):
            RiotAccountService.move_riot_account(
                source_person_id=(
                    self.source_person.id
                ),
                riot_account_id=account.id,
                target_person_id=None,
            )

        stored_account = db.session.get(
            RiotAccount,
            account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

    def test_move_riot_account_rolls_back_when_commit_fails(self):
        """
        A failed commit must preserve the original owner.
        """

        account = self.create_account(
            puuid="rollback-move-puuid"
        )

        with patch(
            (
                "application.services."
                "riot_account_service."
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
                RiotAccountService.move_riot_account(
                    source_person_id=(
                        self.source_person.id
                    ),
                    riot_account_id=account.id,
                    target_person_id=(
                        self.target_person.id
                    ),
                )

        stored_account = db.session.get(
            RiotAccount,
            account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )


if __name__ == "__main__":
    unittest.main()