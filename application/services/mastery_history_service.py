from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, select

from application.database.database import db
from application.database.models import (
    ChampionMastery,
    ChampionMasteryHistory,
)


class MasteryHistoryService:
    """
    Records Champion Mastery snapshots and answers questions about
    mastery over time.

    Timestamps are naive UTC, matching RiotAccount.last_sync. The
    value at a moment is the latest snapshot at or before it.
    """

    PERIOD_DAYS = {
        "week": 7,
        "month": 30,
        "6months": 182,
        "year": 365,
    }

    PERIOD_LABELS = {
        "week": "Last week",
        "month": "Last month",
        "6months": "Last 6 months",
        "year": "Last year",
        "custom": "Custom range",
        "all": "All time",
    }

    @classmethod
    def record_sync(
        cls,
        riot_account,
        previous_values,
        current_values,
        previous_sync,
        recorded_at,
    ):
        """
        Store a snapshot for every champion whose points or level
        differ from its latest snapshot.

        previous_values and current_values map champion IDs to
        (points, level) before and after this sync. A champion
        without history whose previous value is known also gets a
        baseline snapshot at the previous sync, so data stored before
        history was tracked still serves as a starting point.
        """

        latest_values = cls._values_at(
            riot_account.id
        )

        for champion_id, current in current_values.items():
            known = latest_values.get(
                champion_id
            )

            previous = previous_values.get(
                champion_id
            )

            if (
                known is None
                and previous is not None
                and previous_sync is not None
                and previous_sync < recorded_at
            ):
                cls._add_snapshot(
                    riot_account.id,
                    champion_id,
                    previous,
                    previous_sync,
                )

                known = previous

            if known != current:
                cls._add_snapshot(
                    riot_account.id,
                    champion_id,
                    current,
                    recorded_at,
                )

    @classmethod
    def resolve_period(
        cls,
        period,
        start_text=None,
        end_text=None,
        now=None,
    ):
        """
        Translate a period choice into a naive UTC range.

        Returns a mapping with key, label, start, end and the custom
        dates, or None for "all". Custom dates are local calendar
        days and both ends are inclusive. Raises ValueError for an
        unknown period or invalid custom dates.
        """

        period = period or "all"

        if period == "all":
            return None

        if now is None:
            now = datetime.now(
                timezone.utc
            ).replace(
                tzinfo=None
            )

        if period in cls.PERIOD_DAYS:
            return {
                "key": period,
                "label": cls.PERIOD_LABELS[period],
                "start": now - timedelta(
                    days=cls.PERIOD_DAYS[period]
                ),
                "end": now,
                "start_date": None,
                "end_date": None,
            }

        if period != "custom":
            raise ValueError(
                "Unknown time period."
            )

        try:
            start_date = date.fromisoformat(
                str(start_text or "")
            )

            end_date = date.fromisoformat(
                str(end_text or "")
            )

        except ValueError as error:
            raise ValueError(
                "Choose both a start date and an end date."
            ) from error

        if start_date > end_date:
            raise ValueError(
                "The start date must be on or before the end date."
            )

        return {
            "key": "custom",
            "label": cls.PERIOD_LABELS["custom"],
            "start": cls._local_midnight_as_utc(
                start_date
            ),
            "end": cls._local_midnight_as_utc(
                end_date + timedelta(days=1)
            ),
            "start_date": start_date,
            "end_date": end_date,
        }

    @classmethod
    def get_period_gains(
        cls,
        riot_account_ids,
        start,
        end,
    ):
        """
        Return the mastery gained by each account during a range.

        Each account maps to tracked_since (its first snapshot, or
        None without history), gains ({champion_id: points}) and
        levels ({champion_id: level at the end of the range}).

        A range starting before tracked_since is measured from
        tracked_since, because earlier values are unknown.
        """

        results = {}

        for riot_account_id in riot_account_ids:
            tracked_since = db.session.execute(
                select(
                    func.min(
                        ChampionMasteryHistory.recorded_at
                    )
                ).where(
                    ChampionMasteryHistory.riot_account_id
                    == riot_account_id
                )
            ).scalar()

            gains = {}
            levels = {}

            if tracked_since is not None:
                effective_start = max(
                    start,
                    tracked_since,
                )

                if end > effective_start:
                    start_values = cls._values_at(
                        riot_account_id,
                        effective_start,
                    )

                    end_values = cls._values_at(
                        riot_account_id,
                        end,
                    )

                    for champion_id, (
                        end_points,
                        end_level,
                    ) in end_values.items():
                        start_points = start_values.get(
                            champion_id,
                            (0, None),
                        )[0]

                        gains[champion_id] = max(
                            end_points - start_points,
                            0,
                        )

                        levels[champion_id] = end_level

            results[riot_account_id] = {
                "tracked_since": tracked_since,
                "gains": gains,
                "levels": levels,
            }

        return results

    @classmethod
    def get_champion_series(
        cls,
        riot_accounts,
        champion_id,
    ):
        """
        Return the full history of one champion for each account.

        Each point holds an ISO UTC timestamp, points, level and
        whether the level rose at that point. While the champion still
        has current mastery, the series is extended to the account's
        last sync, when the latest value was last confirmed.
        """

        series = []

        for riot_account in riot_accounts:
            snapshots = db.session.execute(
                select(
                    ChampionMasteryHistory
                ).where(
                    ChampionMasteryHistory.riot_account_id
                    == riot_account.id,
                    ChampionMasteryHistory.champion_id
                    == champion_id,
                ).order_by(
                    ChampionMasteryHistory.recorded_at,
                    ChampionMasteryHistory.id,
                )
            ).scalars().all()

            points = []
            previous_level = None

            for snapshot in snapshots:
                points.append(
                    {
                        "recorded_at": cls._to_iso(
                            snapshot.recorded_at
                        ),
                        "mastery_points": snapshot.mastery_points,
                        "mastery_level": snapshot.mastery_level,
                        "level_up": (
                            previous_level is not None
                            and snapshot.mastery_level is not None
                            and snapshot.mastery_level
                            > previous_level
                        ),
                    }
                )

                if snapshot.mastery_level is not None:
                    previous_level = snapshot.mastery_level

            still_current = db.session.execute(
                select(
                    ChampionMastery.id
                ).where(
                    ChampionMastery.riot_account_id
                    == riot_account.id,
                    ChampionMastery.champion_id
                    == champion_id,
                )
            ).first() is not None

            if (
                snapshots
                and still_current
                and riot_account.last_sync is not None
                and riot_account.last_sync
                > snapshots[-1].recorded_at
            ):
                points.append(
                    {
                        **points[-1],
                        "recorded_at": cls._to_iso(
                            riot_account.last_sync
                        ),
                        "level_up": False,
                    }
                )

            series.append(
                {
                    "riot_account_id": riot_account.id,
                    "riot_id": (
                        f"{riot_account.game_name}"
                        f"#{riot_account.tag_line}"
                    ),
                    "points": points,
                }
            )

        return series

    @staticmethod
    def _values_at(
        riot_account_id,
        moment=None,
    ):
        """
        Return {champion_id: (points, level)} from the latest
        snapshot of each champion at or before moment.
        """

        conditions = [
            ChampionMasteryHistory.riot_account_id
            == riot_account_id
        ]

        if moment is not None:
            conditions.append(
                ChampionMasteryHistory.recorded_at <= moment
            )

        latest = (
            select(
                ChampionMasteryHistory.champion_id,
                func.max(
                    ChampionMasteryHistory.recorded_at
                ).label("recorded_at"),
            )
            .where(*conditions)
            .group_by(
                ChampionMasteryHistory.champion_id
            )
            .subquery()
        )

        snapshots = db.session.execute(
            select(
                ChampionMasteryHistory
            )
            .join(
                latest,
                and_(
                    ChampionMasteryHistory.champion_id
                    == latest.c.champion_id,
                    ChampionMasteryHistory.recorded_at
                    == latest.c.recorded_at,
                ),
            )
            .where(
                ChampionMasteryHistory.riot_account_id
                == riot_account_id
            )
            .order_by(
                ChampionMasteryHistory.id
            )
        ).scalars()

        return {
            snapshot.champion_id: (
                snapshot.mastery_points,
                snapshot.mastery_level,
            )
            for snapshot in snapshots
        }

    @staticmethod
    def _add_snapshot(
        riot_account_id,
        champion_id,
        value,
        recorded_at,
    ):
        mastery_points, mastery_level = value

        db.session.add(
            ChampionMasteryHistory(
                riot_account_id=riot_account_id,
                champion_id=champion_id,
                recorded_at=recorded_at,
                mastery_points=mastery_points,
                mastery_level=mastery_level,
            )
        )

    @staticmethod
    def _local_midnight_as_utc(day):
        return (
            datetime(
                day.year,
                day.month,
                day.day,
            )
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

    @staticmethod
    def _to_iso(value):
        return (
            value.replace(
                tzinfo=timezone.utc
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )
