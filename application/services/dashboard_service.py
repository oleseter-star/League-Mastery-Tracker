from application.database.database import db
from application.database.models import (
    Person,
    RiotAccount,
    Champion,
    ChampionMastery,
)
from application.services.mastery_history_service import (
    MasteryHistoryService,
)
from application.services.person_order_service import (
    PersonOrderService,
)


class DashboardService:
    """
    Provides application dashboard and Person mastery overview data.
    """

    @staticmethod
    def get_statistics():
        """
        Return basic application statistics.
        """

        return {
            "persons": Person.query.count(),
            "riot_accounts": RiotAccount.query.count(),
            "champions": Champion.query.count(),
            "masteries": ChampionMastery.query.count(),
        }

    @staticmethod
    def get_home_dashboard():
        """
        Build the main dashboard with one row per Person.
        """

        persons = (
            PersonOrderService.get_ordered_persons()
        )

        person_rows = []

        for person in persons:
            riot_accounts = list(
                person.riot_accounts
            )

            total_mastery = 0
            last_successful_sync = None
            champion_totals = {}

            for riot_account in riot_accounts:
                if (
                    riot_account.last_sync is not None
                    and (
                        last_successful_sync is None
                        or riot_account.last_sync
                        > last_successful_sync
                    )
                ):
                    last_successful_sync = (
                        riot_account.last_sync
                    )

                for mastery in riot_account.mastery_data:
                    mastery_points = max(
                        int(mastery.mastery_points or 0),
                        0,
                    )

                    total_mastery += mastery_points

                    champion = mastery.champion

                    if champion is None:
                        continue

                    champion_row = champion_totals.setdefault(
                        champion.id,
                        {
                            "champion_id": champion.id,
                            "riot_champion_id": (
                                champion.riot_champion_id
                            ),
                            "champion_name": (
                                champion.name
                                or (
                                    "Champion "
                                    f"{champion.riot_champion_id}"
                                )
                            ),
                            "image": champion.image,
                            "total_mastery": 0,
                        },
                    )

                    champion_row["total_mastery"] += (
                        mastery_points
                    )

            ranked_champions = sorted(
                champion_totals.values(),
                key=lambda champion_row: (
                    -champion_row["total_mastery"],
                    champion_row[
                        "champion_name"
                    ].casefold(),
                    champion_row[
                        "riot_champion_id"
                    ],
                ),
            )

            highest_mastery_champion = (
                ranked_champions[0]
                if ranked_champions
                else None
            )

            person_rows.append(
                {
                    "id": person.id,
                    "display_name": person.display_name,
                    "riot_account_count": len(
                        riot_accounts
                    ),
                    "total_mastery": total_mastery,
                    "highest_mastery_champion": (
                        highest_mastery_champion
                    ),
                    "top_champions": (
                        ranked_champions[:3]
                    ),
                    "last_successful_sync": (
                        last_successful_sync
                    ),
                }
            )

        return {
            "persons": person_rows,
            "person_count": len(person_rows),
        }

    @staticmethod
    def get_person_mastery_overview(
        person_id,
        period=None,
    ):
        """
        Build the current combined Champion Mastery overview for one Person.

        The result contains:
        - all connected Riot Accounts
        - combined mastery per champion
        - one points value per Riot Account

        With a period from MasteryHistoryService.resolve_period, the
        points are those gained during the period, champions without
        gains are left out, and history_notes explains accounts whose
        history does not cover the whole period.
        """

        person = db.session.get(
            Person,
            person_id,
        )

        if person is None:
            return None

        riot_accounts = sorted(
            person.riot_accounts,
            key=lambda account: (
                account.game_name.casefold(),
                account.tag_line.casefold(),
                account.id,
            ),
        )

        account_rows = [
            {
                "id": account.id,
                "game_name": account.game_name,
                "tag_line": account.tag_line,
                "riot_id": (
                    f"{account.game_name}#{account.tag_line}"
                ),
                "platform_region": account.platform_region,
                "last_sync": account.last_sync,
            }
            for account in riot_accounts
        ]

        history_notes = []

        if period is None:
            entries = [
                (
                    riot_account.id,
                    mastery.champion,
                    mastery.mastery_points,
                    mastery.mastery_level,
                )
                for riot_account in riot_accounts
                for mastery in riot_account.mastery_data
            ]

        else:
            entries, history_notes = (
                DashboardService._get_period_entries(
                    riot_accounts,
                    period,
                )
            )

        champion_rows_by_id = {}

        for (
            riot_account_id,
            champion,
            mastery_points,
            mastery_level,
        ) in entries:
            if champion is None:
                continue

            champion_row = champion_rows_by_id.setdefault(
                champion.id,
                {
                    "champion_id": champion.id,
                    "riot_champion_id": (
                        champion.riot_champion_id
                    ),
                    "champion_name": (
                        champion.name
                        or (
                            "Champion "
                            f"{champion.riot_champion_id}"
                        )
                    ),
                    "image": champion.image,
                    "total_mastery": 0,
                    "points_by_account": {},
                    "levels_by_account": {},
                },
            )

            champion_row["points_by_account"][
                riot_account_id
            ] = max(
                int(mastery_points or 0),
                0,
            )

            champion_row["levels_by_account"][
                riot_account_id
            ] = mastery_level

        champion_rows = list(
            champion_rows_by_id.values()
        )

        for champion_row in champion_rows:
            for riot_account in riot_accounts:
                champion_row["points_by_account"].setdefault(
                    riot_account.id,
                    0,
                )

                champion_row["levels_by_account"].setdefault(
                    riot_account.id,
                    None,
                )

            champion_row["total_mastery"] = sum(
                champion_row["points_by_account"].values()
            )

        if period is not None:
            champion_rows = [
                champion_row
                for champion_row in champion_rows
                if champion_row["total_mastery"] > 0
            ]

        champion_rows.sort(
            key=lambda champion_row: (
                -champion_row["total_mastery"],
                champion_row["champion_name"].casefold(),
                champion_row["riot_champion_id"],
            )
        )

        total_mastery = sum(
            champion_row["total_mastery"]
            for champion_row in champion_rows
        )

        return {
            "person": person,
            "riot_accounts": account_rows,
            "champions": champion_rows,
            "total_mastery": total_mastery,
            "history_notes": history_notes,
        }

    @staticmethod
    def _get_period_entries(
        riot_accounts,
        period,
    ):
        """
        Return (account ID, champion, points gained, level) entries
        for a period, plus notes for accounts whose history starts
        after the period does.
        """

        period_gains = (
            MasteryHistoryService.get_period_gains(
                riot_account_ids=[
                    riot_account.id
                    for riot_account in riot_accounts
                ],
                start=period["start"],
                end=period["end"],
            )
        )

        champion_ids = {
            champion_id
            for account_gains in period_gains.values()
            for champion_id in account_gains["gains"]
        }

        champion_by_id = {
            champion.id: champion
            for champion in (
                Champion.query.filter(
                    Champion.id.in_(champion_ids)
                ).all()
                if champion_ids
                else []
            )
        }

        entries = []
        history_notes = []

        for riot_account in riot_accounts:
            account_gains = period_gains[
                riot_account.id
            ]

            riot_id = (
                f"{riot_account.game_name}"
                f"#{riot_account.tag_line}"
            )

            tracked_since = account_gains[
                "tracked_since"
            ]

            if tracked_since is None:
                history_notes.append(
                    {
                        "riot_id": riot_id,
                        "tracked_since": None,
                    }
                )

            elif tracked_since > period["start"]:
                history_notes.append(
                    {
                        "riot_id": riot_id,
                        "tracked_since": tracked_since,
                    }
                )

            for champion_id, points in account_gains[
                "gains"
            ].items():
                entries.append(
                    (
                        riot_account.id,
                        champion_by_id.get(
                            champion_id
                        ),
                        points,
                        account_gains["levels"].get(
                            champion_id
                        ),
                    )
                )

        return entries, history_notes