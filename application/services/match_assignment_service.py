from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import exists
from sqlalchemy.orm import aliased

from application.database.database import db
from application.database.models import (
    Champion,
    Match,
    MatchParticipant,
    Person,
    RiotAccount,
)


@dataclass(frozen=True)
class GameSelection:
    """
    Selects games of one Riot Account. Empty fields select everything.

    together_with_account_id keeps games where that other tracked Riot
    Account was in the same game, on either team.
    """

    riot_match_ids: tuple = ()
    together_with_account_id: Optional[int] = None
    riot_champion_id: Optional[int] = None
    queue_ids: tuple = ()
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    def is_empty(self):
        return not (
            self.riot_match_ids
            or self.together_with_account_id is not None
            or self.riot_champion_id is not None
            or self.queue_ids
            or self.start is not None
            or self.end is not None
        )


class MatchAssignmentService:
    """
    Lists a Riot Account's stored games and records who played them.

    An account belongs to one Person, but a game played on it by someone
    else can be assigned to that other Person. Statistics then count the
    game for them. Assigning a game back to the account's owner clears the
    assignment.
    """

    def list_games(self, riot_account_id, selection=GameSelection(), limit=None):
        account = self._get_account(riot_account_id)

        query = self._selected_participants(account, selection).order_by(
            Match.game_creation.desc()
        )

        if limit is not None:
            query = query.limit(limit)

        participants = query.all()
        champion_names = dict(
            db.session.query(Champion.riot_champion_id, Champion.name).all()
        )
        others_by_match = self._other_tracked_accounts(
            account,
            [participant.match_id for participant in participants],
        )

        return [
            {
                "riot_match_id": participant.match.riot_match_id,
                "game_creation": participant.match.game_creation,
                "queue_id": participant.match.queue_id,
                "patch": participant.match.patch,
                "riot_champion_id": participant.riot_champion_id,
                "champion_name": champion_names.get(participant.riot_champion_id),
                "team_position": participant.team_position,
                "win": participant.win,
                "played_by": (
                    participant.played_by_person.display_name
                    if participant.played_by_person is not None
                    else account.person.display_name
                ),
                "assigned": participant.played_by_person_id is not None,
                "with_accounts": others_by_match.get(participant.match_id, []),
            }
            for participant in participants
        ]

    def assign(
        self,
        riot_account_id,
        person_id,
        selection=GameSelection(),
        all_games=False,
    ):
        """
        Record that person_id played the selected games; None or the
        account's owner returns them to the owner.

        Returns how many games changed.
        """

        account = self._get_account(riot_account_id)

        if selection.is_empty() and not all_games:
            raise ValueError(
                "Select games by ID, champion, mode, date, or another "
                "account, or choose every game explicitly."
            )

        if person_id is not None and db.session.get(Person, person_id) is None:
            raise ValueError(f"Person with ID {person_id} was not found.")

        played_by = None if person_id in (None, account.person_id) else person_id
        changed = 0

        for participant in self._selected_participants(account, selection):
            if participant.played_by_person_id != played_by:
                participant.played_by_person_id = played_by
                changed += 1

        db.session.commit()

        return changed

    @staticmethod
    def _get_account(riot_account_id):
        account = db.session.get(RiotAccount, riot_account_id)

        if account is None:
            raise ValueError(
                f"Riot Account with ID {riot_account_id} was not found."
            )

        return account

    @staticmethod
    def _selected_participants(account, selection):
        query = (
            MatchParticipant.query
            .join(Match, MatchParticipant.match_id == Match.id)
            .filter(MatchParticipant.riot_account_id == account.id)
        )

        if selection.riot_match_ids:
            query = query.filter(Match.riot_match_id.in_(selection.riot_match_ids))

        if selection.riot_champion_id is not None:
            query = query.filter(
                MatchParticipant.riot_champion_id == selection.riot_champion_id
            )

        if selection.queue_ids:
            query = query.filter(Match.queue_id.in_(selection.queue_ids))

        if selection.start is not None:
            query = query.filter(Match.game_creation >= selection.start)

        if selection.end is not None:
            query = query.filter(Match.game_creation < selection.end)

        if selection.together_with_account_id is not None:
            other = aliased(MatchParticipant)
            query = query.filter(
                exists().where(
                    (other.match_id == MatchParticipant.match_id)
                    & (other.riot_account_id == selection.together_with_account_id)
                )
            )

        return query

    @staticmethod
    def _other_tracked_accounts(account, match_ids):
        if not match_ids:
            return {}

        rows = (
            db.session.query(
                MatchParticipant.match_id,
                RiotAccount.game_name,
                RiotAccount.tag_line,
            )
            .join(RiotAccount, MatchParticipant.riot_account_id == RiotAccount.id)
            .filter(MatchParticipant.match_id.in_(match_ids))
            .filter(MatchParticipant.riot_account_id != account.id)
            .order_by(RiotAccount.game_name)
            .all()
        )

        others = {}

        for match_id, game_name, tag_line in rows:
            others.setdefault(match_id, []).append(f"{game_name}#{tag_line}")

        return others
