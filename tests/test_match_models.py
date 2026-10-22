import unittest
from datetime import datetime

from flask import Flask
from sqlalchemy.exc import IntegrityError

from application.database.database import db
from application.database.models import (
    Match,
    MatchImportState,
    MatchParticipant,
    Person,
    RiotAccount,
)
from application.services.person_service import PersonService


def build_match(riot_match_id="EUW1_1"):
    return Match(
        riot_match_id=riot_match_id,
        platform_id="EUW1",
        queue_id=420,
        game_creation=datetime(2025, 1, 1, 12, 0),
        game_duration_seconds=1800,
        imported_at=datetime(2025, 1, 2, 12, 0),
    )


def build_participant(participant_id, riot_account=None, team_id=100):
    return MatchParticipant(
        participant_id=participant_id,
        puuid=f"puuid-{participant_id}",
        riot_champion_id=participant_id,
        team_id=team_id,
        team_position="MIDDLE",
        win=team_id == 100,
        riot_account=riot_account,
    )


class MatchModelTests(unittest.TestCase):
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

        self.person = Person(display_name="Ole")
        self.friend = Person(display_name="Friend")
        self.account = RiotAccount(
            person=self.person,
            game_name="Main",
            tag_line="EUW",
            puuid="puuid-1",
            platform_region="EUW1",
        )
        self.friend_account = RiotAccount(
            person=self.friend,
            game_name="Friend",
            tag_line="EUW",
            puuid="puuid-2",
            platform_region="EUW1",
        )
        self.match = build_match()
        self.match.participants = [
            build_participant(1, self.account),
            build_participant(2, self.friend_account),
            build_participant(6, team_id=200),
        ]
        self.account.match_import_state = MatchImportState(history_complete=True)
        db.session.add_all([self.person, self.friend, self.match])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_participants_are_ordered_and_linked(self):
        match = Match.query.one()

        self.assertEqual([p.participant_id for p in match.participants], [1, 2, 6])
        self.assertEqual(match.participants[0].riot_account.person.display_name, "Ole")
        self.assertIsNone(match.participants[2].riot_account)

    def test_deleting_a_person_keeps_shared_games_and_clears_links(self):
        PersonService.delete_person(self.person)

        self.assertEqual(Match.query.count(), 1)
        self.assertEqual(MatchParticipant.query.count(), 3)
        links = {p.participant_id: p.riot_account_id for p in MatchParticipant.query}

        self.assertIsNone(links[1])
        self.assertEqual(links[2], self.friend_account.id)
        self.assertEqual(MatchImportState.query.count(), 0)

    def test_deleting_a_match_deletes_its_participants(self):
        db.session.delete(self.match)
        db.session.commit()

        self.assertEqual(MatchParticipant.query.count(), 0)
        self.assertEqual(RiotAccount.query.count(), 2)

    def test_riot_match_id_and_participant_slot_are_unique(self):
        db.session.add(build_match())

        with self.assertRaises(IntegrityError):
            db.session.commit()

        db.session.rollback()
        self.match.participants.append(build_participant(1))

        with self.assertRaises(IntegrityError):
            db.session.commit()

        db.session.rollback()

    def test_one_import_state_per_riot_account(self):
        db.session.add(MatchImportState(riot_account_id=self.account.id))

        with self.assertRaises(IntegrityError):
            db.session.commit()

        db.session.rollback()


if __name__ == "__main__":
    unittest.main()
