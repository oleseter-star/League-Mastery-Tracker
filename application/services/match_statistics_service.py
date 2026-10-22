import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import case, func
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
    example "16.18".
    """

    person_ids: tuple = ()
    riot_account_ids: tuple = ()
    queue_ids: tuple = ()
    patches: tuple = ()
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    team_position: Optional[str] = None
    riot_champion_id: Optional[int] = None
    min_games: int = 1
    include_remakes: bool = False


class MatchStatisticsService:
    """
    Aggregates stored match history into win rates.

    Every result counts games from a tracked Person's side, with games,
    wins, losses, win rate, and the lower bound of the 95% Wilson score
    interval. Results are sorted by that lower bound, so a large sample
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

    def ally_champions(self, filters=MatchStatisticsFilter()):
        """
        Results with each champion on the tracked Person's team.
        """

        tracked = aliased(MatchParticipant, name="tracked")
        ally = aliased(MatchParticipant, name="ally")

        query = (
            self._tracked_query(tracked, filters, ally.riot_champion_id)
            .join(
                ally,
                (ally.match_id == tracked.match_id)
                & (ally.team_id == tracked.team_id)
                & (ally.id != tracked.id),
            )
            .group_by(ally.riot_champion_id)
        )

        return self._with_champion_names(
            self._rows(query, filters, ("riot_champion_id",))
        )

    def enemy_champions(
        self,
        filters=MatchStatisticsFilter(),
        lane_opponents_only=False,
    ):
        """
        Results against each champion on the other team.

        lane_opponents_only keeps only the enemy in the same position.
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

        query = (
            self._tracked_query(tracked, filters, enemy.riot_champion_id)
            .join(enemy, condition)
            .group_by(enemy.riot_champion_id)
        )

        return self._with_champion_names(
            self._rows(query, filters, ("riot_champion_id",))
        )

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
                func.count(first.id),
                self._wins_column(first),
            )
            .select_from(first)
            .join(Match, first.match_id == Match.id)
            .join(first_account, first.riot_account_id == first_account.id)
            .join(first_person, first_account.person_id == first_person.id)
            .join(
                second,
                (second.match_id == first.match_id)
                & (second.team_id == first.team_id)
                & (second.id != first.id),
            )
            .join(second_account, second.riot_account_id == second_account.id)
            .join(second_person, second_account.person_id == second_person.id)
            .filter(first_person.id < second_person.id)
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
                func.count(tracked.id),
                self._wins_column(tracked),
            )
            .select_from(tracked)
            .join(Match, tracked.match_id == Match.id)
            .join(RiotAccount, tracked.riot_account_id == RiotAccount.id)
            .join(Person, RiotAccount.person_id == Person.id)
        )

        return self._apply_filters(query, tracked, filters)

    def _apply_filters(self, query, tracked, filters):
        query = self._apply_match_filters(query, filters)

        if filters.person_ids:
            query = query.filter(RiotAccount.person_id.in_(filters.person_ids))

        if filters.riot_account_ids:
            query = query.filter(tracked.riot_account_id.in_(filters.riot_account_ids))

        if filters.team_position:
            query = query.filter(tracked.team_position == filters.team_position)

        if filters.riot_champion_id is not None:
            query = query.filter(tracked.riot_champion_id == filters.riot_champion_id)

        return query

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
    def _wins_column(participant):
        return func.sum(case((participant.win.is_(True), 1), else_=0))

    def _rows(self, query, filters, key_names):
        if filters.min_games > 1:
            query = query.having(func.count() >= filters.min_games)

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
        names = dict(
            db.session.query(Champion.riot_champion_id, Champion.name).all()
        )

        for row in rows:
            row["champion_name"] = names.get(row["riot_champion_id"])

        return rows
