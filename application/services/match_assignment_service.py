import zlib
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
    assignment. A game can also be ignored, so it counts for nobody.

    A game needs review when two tracked accounts in it would count for
    the same Person, which happens when someone else played on one of
    that Person's accounts in a game with them.
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
                "ignored": participant.ignored,
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

    def set_ignored(
        self,
        riot_account_id,
        ignored,
        selection=GameSelection(),
        all_games=False,
    ):
        """
        Ignore or restore the selected games. Returns how many changed.
        """

        account = self._get_account(riot_account_id)

        if selection.is_empty() and not all_games:
            raise ValueError(
                "Select games by ID, champion, mode, date, or another "
                "account, or choose every game explicitly."
            )

        changed = 0

        for participant in self._selected_participants(account, selection):
            if participant.ignored != ignored:
                participant.ignored = ignored
                changed += 1

        db.session.commit()

        return changed

    def set_played_by(self, participant_id, person_id):
        """
        Record who played one tracked game; None means the owner.
        """

        participant = db.session.get(MatchParticipant, participant_id)

        if participant is None or participant.riot_account is None:
            raise ValueError("That game is not on a tracked Riot account.")

        if person_id is not None and db.session.get(Person, person_id) is None:
            raise ValueError(f"Person with ID {person_id} was not found.")

        owner_id = participant.riot_account.person_id
        participant.played_by_person_id = (
            None if person_id in (None, owner_id) else person_id
        )
        db.session.commit()

    def games_to_review(self):
        """
        Return games where two tracked accounts count for the same Person,
        newest first.
        """

        return [
            self._describe_game(match, participants)
            for match, participants in self._review_groups()
        ]

    def ignore_review_game(self, match_id):
        """
        Ignore the conflicting accounts in one game under review.
        """

        changed = 0

        for match, participants in self._review_groups(match_id=match_id):
            for participant in participants:
                participant.ignored = True
                changed += 1

        db.session.commit()

        return changed

    def ignore_all_review_games(self):
        """
        Ignore every game under review. Returns how many games changed.
        """

        groups = self._review_groups()

        for _match, participants in groups:
            for participant in participants:
                participant.ignored = True

        db.session.commit()

        return len({match.id for match, _participants in groups})

    def ignored_games(self):
        """
        Return games with ignored tracked accounts, newest first.
        """

        participants = (
            MatchParticipant.query
            .join(Match, MatchParticipant.match_id == Match.id)
            .filter(MatchParticipant.riot_account_id.isnot(None))
            .filter(MatchParticipant.ignored.is_(True))
            .order_by(Match.game_creation.desc(), MatchParticipant.participant_id)
            .all()
        )

        by_match = {}

        for participant in participants:
            by_match.setdefault(participant.match, []).append(participant)

        return [
            self._describe_game(match, rows)
            for match, rows in by_match.items()
        ]

    def restore_game(self, match_id):
        """
        Count an ignored game again. Returns how many accounts changed.
        """

        participants = MatchParticipant.query.filter_by(
            match_id=match_id,
            ignored=True,
        ).all()

        for participant in participants:
            participant.ignored = False

        db.session.commit()

        return len(participants)

    def _review_groups(self, match_id=None):
        """
        Return (match, participants) for every game where two or more
        counted, tracked participants resolve to the same Person.
        """

        query = (
            MatchParticipant.query
            .join(Match, MatchParticipant.match_id == Match.id)
            .filter(MatchParticipant.riot_account_id.isnot(None))
            .filter(MatchParticipant.ignored.is_(False))
            .order_by(Match.game_creation.desc(), MatchParticipant.participant_id)
        )

        if match_id is not None:
            query = query.filter(MatchParticipant.match_id == match_id)

        by_match_and_person = {}

        for participant in query.all():
            person_id = (
                participant.played_by_person_id
                or participant.riot_account.person_id
            )
            by_match_and_person.setdefault(
                (participant.match, person_id),
                [],
            ).append(participant)

        groups = {}

        for (match, _person_id), participants in by_match_and_person.items():
            if len(participants) > 1:
                groups.setdefault(match, []).extend(participants)

        return sorted(
            groups.items(),
            key=lambda item: item[0].game_creation,
            reverse=True,
        )

    POSITION_ORDER = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

    @classmethod
    def _describe_game(cls, match, participants):
        """
        Describe a game for display: both teams with champions, and the
        given tracked accounts with their stats from the stored match data.
        """

        champions = {
            riot_champion_id: (name, image)
            for riot_champion_id, name, image in db.session.query(
                Champion.riot_champion_id,
                Champion.name,
                Champion.image,
            )
        }
        stats_by_slot = cls._stats_by_participant_slot(match)
        minutes = max(match.game_duration_seconds / 60, 1)
        selected_ids = {participant.id for participant in participants}

        def champion(riot_champion_id):
            name, image = champions.get(riot_champion_id, (None, None))
            return name or f"Champion {riot_champion_id}", image

        teams = {}

        for participant in match.participants:
            name, image = champion(participant.riot_champion_id)
            teams.setdefault(participant.team_id, []).append({
                "champion_name": name,
                "champion_image": image,
                "riot_id_game_name": participant.riot_id_game_name,
                "team_position": participant.team_position,
                "tracked": participant.riot_account_id is not None,
                "selected": participant.id in selected_ids,
                "win": participant.win,
            })

        accounts = []

        for participant in participants:
            name, image = champion(participant.riot_champion_id)
            stats = stats_by_slot.get(participant.participant_id, {})
            creep_score = (
                int(stats.get("totalMinionsKilled") or 0)
                + int(stats.get("neutralMinionsKilled") or 0)
            )
            deaths = participant.deaths

            accounts.append({
                "participant_id": participant.id,
                "riot_id": (
                    f"{participant.riot_account.game_name}"
                    f"#{participant.riot_account.tag_line}"
                ),
                "owner_id": participant.riot_account.person_id,
                "owner_name": participant.riot_account.person.display_name,
                "played_by_id": (
                    participant.played_by_person_id
                    or participant.riot_account.person_id
                ),
                "champion_name": name,
                "champion_image": image,
                "team_position": participant.team_position,
                "team_id": participant.team_id,
                "win": participant.win,
                "kills": participant.kills,
                "deaths": deaths,
                "assists": participant.assists,
                "kda": (
                    (participant.kills + participant.assists) / deaths
                    if deaths else None
                ),
                "creep_score": creep_score if stats else None,
                "creep_score_per_minute": creep_score / minutes if stats else None,
                "damage_to_champions": stats.get("totalDamageDealtToChampions"),
            })

        win = any(account["win"] for account in accounts)

        return {
            "match_id": match.id,
            "riot_match_id": match.riot_match_id,
            "game_creation": match.game_creation,
            "queue_id": match.queue_id,
            "patch": match.patch,
            "game_duration_seconds": match.game_duration_seconds,
            "win": win,
            "teams": [
                {
                    "team_id": team_id,
                    "win": any(member["win"] for member in members),
                    "participants": sorted(members, key=cls._position_sort_key),
                }
                for team_id, members in sorted(teams.items())
            ],
            "accounts": accounts,
        }

    @classmethod
    def _position_sort_key(cls, member):
        position = member["team_position"]

        if position in cls.POSITION_ORDER:
            return cls.POSITION_ORDER.index(position)

        return len(cls.POSITION_ORDER)

    @staticmethod
    def _stats_by_participant_slot(match):
        """
        Return Riot's per-participant stats from the stored match data,
        keyed by participant slot. Empty when no match data is stored.
        """

        from application.services.match_import_service import (
            MatchImportService,
        )

        try:
            match_data = MatchImportService.decode_raw_data(match) or {}
        except (ValueError, OSError, zlib.error):
            return {}

        return {
            int(stats.get("participantId") or index + 1): stats
            for index, stats in enumerate(
                match_data.get("info", {}).get("participants", [])
            )
        }

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
