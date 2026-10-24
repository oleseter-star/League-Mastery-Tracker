import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import case, distinct, exists, func, literal_column
from sqlalchemy.orm import aliased

from application.database.database import db
from application.database.models import (
    Champion,
    Match,
    MatchParticipant,
    Person,
    RiotAccount,
)
from application.services.match_catalog import patch_sort_key


@dataclass(frozen=True)
class MatchStatisticsFilter:
    """
    Selects the games that statistics count.

    Empty tuples mean "all". Champion and position filters apply to the
    tracked Person's side of each game. Patches use the stored form, for
    example "16.18". with_person_id keeps games where that tracked Person
    was on the same team.
    """

    person_ids: tuple = ()
    riot_account_ids: tuple = ()
    queue_ids: tuple = ()
    patches: tuple = ()
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    team_position: Optional[str] = None
    riot_champion_id: Optional[int] = None
    with_person_id: Optional[int] = None
    min_games: int = 1
    include_remakes: bool = False


class MatchStatisticsService:
    """
    Aggregates stored match history into win rates.

    Every result counts games from a tracked Person's side, with games,
    wins, losses, win rate, and the lower bound of the 95% Wilson score
    interval. A game belongs to the Person who played it: the participant's
    played-by Person when set, otherwise the Riot Account's owner. Each
    game counts at most once per result row. Results are sorted by that lower bound, so a large sample
    with a good win rate ranks above a short winning streak.
    """

    # Games shorter than this are remakes and say nothing about a matchup.
    REMAKE_MAX_SECONDS = 300

    WILSON_Z = 1.96

    def person_overview(self, filters=MatchStatisticsFilter()):
        tracked = aliased(MatchParticipant, name="tracked")

        query = self._tracked_query(
            tracked,
            filters,
            Person.id,
            Person.display_name,
        ).group_by(Person.id, Person.display_name)

        return self._rows(
            query,
            filters,
            ("person_id", "person_name"),
        )

    def champion_overview(self, filters=MatchStatisticsFilter()):
        tracked = aliased(MatchParticipant, name="tracked")

        query = self._tracked_query(
            tracked,
            filters,
            tracked.riot_champion_id,
        ).group_by(tracked.riot_champion_id)

        return self._with_champion_names(
            self._rows(query, filters, ("riot_champion_id",))
        )

    def person_champions(self, filters=MatchStatisticsFilter()):
        tracked = aliased(MatchParticipant, name="tracked")

        query = self._tracked_query(
            tracked,
            filters,
            Person.id,
            Person.display_name,
            tracked.riot_champion_id,
        ).group_by(Person.id, Person.display_name, tracked.riot_champion_id)

        return self._with_champion_names(
            self._rows(
                query,
                filters,
                ("person_id", "person_name", "riot_champion_id"),
            )
        )

    def person_champion_positions(self, filters=MatchStatisticsFilter()):
        """
        Results per Person, champion, and position.

        Games without a position, such as ARAM, are left out.
        """

        tracked = aliased(MatchParticipant, name="tracked")

        query = (
            self._tracked_query(
                tracked,
                filters,
                Person.id,
                Person.display_name,
                tracked.riot_champion_id,
                tracked.team_position,
            )
            .filter(tracked.team_position != "")
            .group_by(
                Person.id,
                Person.display_name,
                tracked.riot_champion_id,
                tracked.team_position,
            )
        )

        return self._with_champion_names(
            self._rows(
                query,
                filters,
                ("person_id", "person_name", "riot_champion_id", "team_position"),
            )
        )

    def patch_results(self, filters=MatchStatisticsFilter()):
        """
        Results per patch, newest patch first.
        """

        tracked = aliased(MatchParticipant, name="tracked")

        query = self._tracked_query(
            tracked,
            filters,
            Match.patch,
        ).group_by(Match.patch)

        rows = self._rows(query, filters, ("patch",))

        return sorted(
            rows,
            key=lambda row: patch_sort_key(row["patch"] or "0.0"),
            reverse=True,
        )

    def ally_champions(
        self,
        filters=MatchStatisticsFilter(),
        by_position=False,
    ):
        """
        Results with each champion on the tracked Person's team.

        by_position groups by the ally's position as well, so the same
        champion in two roles gives two rows.
        """

        tracked = aliased(MatchParticipant, name="tracked")
        ally = aliased(MatchParticipant, name="ally")

        return self._other_champion_rows(
            tracked,
            ally,
            filters,
            (ally.match_id == tracked.match_id)
            & (ally.team_id == tracked.team_id)
            & (ally.id != tracked.id),
            by_position,
        )

    def enemy_champions(
        self,
        filters=MatchStatisticsFilter(),
        lane_opponents_only=False,
        by_position=False,
    ):
        """
        Results against each champion on the other team.

        lane_opponents_only keeps only the enemy in the same position;
        by_position groups by the enemy's position as well.
        """

        tracked = aliased(MatchParticipant, name="tracked")
        enemy = aliased(MatchParticipant, name="enemy")

        condition = (
            (enemy.match_id == tracked.match_id)
            & (enemy.team_id != tracked.team_id)
        )

        if lane_opponents_only:
            condition = (
                condition
                & (enemy.team_position == tracked.team_position)
                & (tracked.team_position != "")
            )

        return self._other_champion_rows(
            tracked,
            enemy,
            filters,
            condition,
            by_position,
        )

    def _other_champion_rows(self, tracked, other, filters, condition, by_position):
        columns = [other.riot_champion_id]
        key_names = ["riot_champion_id"]

        if by_position:
            columns.append(other.team_position)
            key_names.append("team_position")

        query = (
            self._tracked_query(tracked, filters, *columns)
            .join(other, condition)
            .group_by(*columns)
        )

        return self._with_champion_names(
            self._rows(query, filters, tuple(key_names))
        )

    def teammates(self, filters=MatchStatisticsFilter()):
        """
        Results with each other tracked Person on the same team.

        Unlike person_pairs, every filter applies to the selected
        Persons' side, so a champion filter gives "on this champion,
        with whom do I win".
        """

        tracked = aliased(MatchParticipant, name="tracked")
        mate = aliased(MatchParticipant, name="mate")
        mate_account = aliased(RiotAccount, name="mate_account")
        mate_person = aliased(Person, name="mate_person")

        query = (
            self._tracked_query(
                tracked,
                filters,
                mate_person.id,
                mate_person.display_name,
            )
            .join(
                mate,
                (mate.match_id == tracked.match_id)
                & (mate.team_id == tracked.team_id)
                & (mate.id != tracked.id),
            )
            .join(mate_account, mate.riot_account_id == mate_account.id)
            .join(mate_person, self._played_by(mate, mate_account) == mate_person.id)
            .filter(mate.ignored.is_(False))
            .filter(mate_person.id != self._played_by(tracked, RiotAccount))
            .group_by(mate_person.id, mate_person.display_name)
        )

        return self._rows(query, filters, ("person_id", "person_name"))

    def positions(self, filters=MatchStatisticsFilter()):
        """
        Results per position of the tracked side, games without a
        position left out.
        """

        tracked = aliased(MatchParticipant, name="tracked")

        query = (
            self._tracked_query(tracked, filters, tracked.team_position)
            .filter(tracked.team_position != "")
            .group_by(tracked.team_position)
        )

        return self._rows(query, filters, ("team_position",))

    def person_pairs(self, filters=MatchStatisticsFilter()):
        """
        Results when two tracked Persons play on the same team.

        With person_ids set, a pair is included when either Person is
        selected. Champion and position filters do not apply here.
        """

        first = aliased(MatchParticipant, name="first_tracked")
        second = aliased(MatchParticipant, name="second_tracked")
        first_account = aliased(RiotAccount, name="first_account")
        second_account = aliased(RiotAccount, name="second_account")
        first_person = aliased(Person, name="first_person")
        second_person = aliased(Person, name="second_person")
        query = (
            db.session.query(
                first_person.id,
                first_person.display_name,
                second_person.id,
                second_person.display_name,
                self._games_column(first),
                self._wins_column(first),
            )
            .select_from(first)
            .join(Match, first.match_id == Match.id)
            .join(first_account, first.riot_account_id == first_account.id)
            .join(first_person, self._played_by(first, first_account) == first_person.id)
            .join(
                second,
                (second.match_id == first.match_id)
                & (second.team_id == first.team_id)
                & (second.id != first.id),
            )
            .join(second_account, second.riot_account_id == second_account.id)
            .join(second_person, self._played_by(second, second_account) == second_person.id)
            .filter(first_person.id < second_person.id)
            .filter(first.ignored.is_(False))
            .filter(second.ignored.is_(False))
            .group_by(
                first_person.id,
                first_person.display_name,
                second_person.id,
                second_person.display_name,
            )
        )

        query = self._apply_match_filters(query, filters)

        if filters.person_ids:
            query = query.filter(
                first_person.id.in_(filters.person_ids)
                | second_person.id.in_(filters.person_ids)
            )

        return self._rows(
            query,
            filters,
            ("person_id", "person_name", "other_person_id", "other_person_name"),
        )

    def games(
        self,
        filters=MatchStatisticsFilter(),
        ally_champion_id=None,
        ally_position=None,
        enemy_champion_id=None,
        enemy_position=None,
        limit=25,
        offset=0,
    ):
        """
        Return the games behind a statistic, newest first.

        Every filter applies as in the other views. ally_* and enemy_*
        keep games with that champion, optionally in that position, on
        the same or the other team. Each game appears once, seen from one
        tracked participant. Returns total, wins, and one page of
        (match, participant) pairs.
        """

        tracked = aliased(MatchParticipant, name="tracked")

        query = (
            db.session.query(
                Match.id,
                Match.game_creation,
                func.min(tracked.id),
                func.max(case((tracked.win.is_(True), 1), else_=0)),
            )
            .select_from(tracked)
            .join(Match, tracked.match_id == Match.id)
            .join(RiotAccount, tracked.riot_account_id == RiotAccount.id)
        )
        query = self._apply_filters(query, tracked, filters)

        if ally_champion_id is not None:
            query = query.filter(
                self._has_other(tracked, True, ally_champion_id, ally_position)
            )

        if enemy_champion_id is not None:
            query = query.filter(
                self._has_other(tracked, False, enemy_champion_id, enemy_position)
            )

        rows = (
            query
            .group_by(Match.id, Match.game_creation)
            .order_by(Match.game_creation.desc(), Match.id.desc())
            .all()
        )

        page = rows[max(0, offset):max(0, offset) + max(0, limit)]
        participants = {
            participant.id: participant
            for participant in MatchParticipant.query.filter(
                MatchParticipant.id.in_([row[2] for row in page])
            )
        }

        return {
            "total": len(rows),
            "wins": sum(row[3] for row in rows),
            "games": [
                (participants[row[2]].match, participants[row[2]])
                for row in page
            ],
        }

    @staticmethod
    def _has_other(tracked, same_team, riot_champion_id, team_position):
        other = aliased(MatchParticipant, name="other_side")
        condition = (
            (other.match_id == tracked.match_id)
            & (other.id != tracked.id)
            & (other.riot_champion_id == riot_champion_id)
        )

        if same_team:
            condition = condition & (other.team_id == tracked.team_id)
        else:
            condition = condition & (other.team_id != tracked.team_id)

        if team_position:
            condition = condition & (other.team_position == team_position)

        return exists().where(condition)

    def summary(self, filters=MatchStatisticsFilter()):
        """
        Count stored games matching the filters, per queue and in total.
        """

        tracked = aliased(MatchParticipant, name="tracked")

        base = self._apply_filters(
            db.session.query(Match.id, Match.queue_id, Match.patch, Match.game_creation)
            .select_from(tracked)
            .join(Match, tracked.match_id == Match.id)
            .join(RiotAccount, tracked.riot_account_id == RiotAccount.id),
            tracked,
            filters,
        ).distinct().subquery()

        games_per_queue = dict(
            db.session.query(base.c.queue_id, func.count())
            .group_by(base.c.queue_id)
            .all()
        )

        games_per_patch = dict(
            db.session.query(base.c.patch, func.count())
            .group_by(base.c.patch)
            .all()
        )

        first_game, last_game = db.session.query(
            func.min(base.c.game_creation),
            func.max(base.c.game_creation),
        ).one()

        return {
            "games": sum(games_per_queue.values()),
            "games_per_queue": dict(sorted(games_per_queue.items())),
            "games_per_patch": dict(
                sorted(
                    games_per_patch.items(),
                    key=lambda item: patch_sort_key(item[0] or "0.0"),
                    reverse=True,
                )
            ),
            "first_game": first_game,
            "last_game": last_game,
        }

    @staticmethod
    def available_patches():
        """
        Return every patch with stored games, newest first.
        """

        patches = [
            patch
            for (patch,) in db.session.query(Match.patch).distinct()
            if patch is not None
        ]

        return sorted(patches, key=patch_sort_key, reverse=True)

    @classmethod
    def wilson_lower_bound(cls, wins, games):
        if games <= 0:
            return 0.0

        z = cls.WILSON_Z
        rate = wins / games
        denominator = 1 + z * z / games
        centre = rate + z * z / (2 * games)
        margin = z * math.sqrt(rate * (1 - rate) / games + z * z / (4 * games * games))

        return (centre - margin) / denominator

    def _tracked_query(self, tracked, filters, *columns):
        query = (
            db.session.query(
                *columns,
                self._games_column(tracked),
                self._wins_column(tracked),
            )
            .select_from(tracked)
            .join(Match, tracked.match_id == Match.id)
            .join(RiotAccount, tracked.riot_account_id == RiotAccount.id)
            .join(Person, self._played_by(tracked, RiotAccount) == Person.id)
        )

        return self._apply_filters(query, tracked, filters)

    @staticmethod
    def _played_by(participant, account):
        """
        The Person who played a tracked participant's game.
        """

        return func.coalesce(
            participant.played_by_person_id,
            account.person_id,
        )

    def _apply_filters(self, query, tracked, filters):
        query = self._apply_match_filters(query, filters)
        query = query.filter(tracked.ignored.is_(False))

        if filters.person_ids:
            query = query.filter(
                self._played_by(tracked, RiotAccount).in_(filters.person_ids)
            )

        if filters.riot_account_ids:
            query = query.filter(tracked.riot_account_id.in_(filters.riot_account_ids))

        if filters.team_position:
            query = query.filter(tracked.team_position == filters.team_position)

        if filters.riot_champion_id is not None:
            query = query.filter(tracked.riot_champion_id == filters.riot_champion_id)

        if filters.with_person_id is not None:
            query = query.filter(
                self._has_teammate(tracked, filters.with_person_id)
            )

        return query

    def _has_teammate(self, tracked, person_id):
        """
        True when another counted, tracked participant on the same team
        was played by person_id.
        """

        mate = aliased(MatchParticipant, name="filter_mate")
        mate_account = aliased(RiotAccount, name="filter_mate_account")

        return exists().where(
            (mate.match_id == tracked.match_id)
            & (mate.team_id == tracked.team_id)
            & (mate.id != tracked.id)
            & (mate.ignored.is_(False))
            & (mate.riot_account_id == mate_account.id)
            & (self._played_by(mate, mate_account) == person_id)
        )

    def _apply_match_filters(self, query, filters):
        if filters.queue_ids:
            query = query.filter(Match.queue_id.in_(filters.queue_ids))

        if filters.patches:
            query = query.filter(Match.patch.in_(filters.patches))

        if filters.start is not None:
            query = query.filter(Match.game_creation >= filters.start)

        if filters.end is not None:
            query = query.filter(Match.game_creation < filters.end)

        if not filters.include_remakes:
            query = query.filter(Match.game_duration_seconds >= self.REMAKE_MAX_SECONDS)

        return query

    @staticmethod
    def _games_column(participant):
        return func.count(distinct(participant.match_id)).label("games")

    @staticmethod
    def _wins_column(participant):
        return func.count(
            distinct(case((participant.win.is_(True), participant.match_id)))
        )

    def _rows(self, query, filters, key_names):
        if filters.min_games > 1:
            query = query.having(
                literal_column("games") >= filters.min_games
            )

        rows = []

        for values in query.all():
            *keys, games, wins = values
            wins = int(wins or 0)
            row = dict(zip(key_names, keys))
            row.update({
                "games": games,
                "wins": wins,
                "losses": games - wins,
                "win_rate": wins / games if games else 0.0,
                "wilson_lower": self.wilson_lower_bound(wins, games),
            })
            rows.append(row)

        return sorted(rows, key=lambda row: (-row["wilson_lower"], -row["games"]))

    @staticmethod
    def _with_champion_names(rows):
        champions = {
            riot_champion_id: (name, image)
            for riot_champion_id, name, image in db.session.query(
                Champion.riot_champion_id,
                Champion.name,
                Champion.image,
            )
        }

        for row in rows:
            name, image = champions.get(row["riot_champion_id"], (None, None))
            row["champion_name"] = name
            row["champion_image"] = image

        return rows
