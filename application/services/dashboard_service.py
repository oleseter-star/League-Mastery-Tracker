from application.database.database import db
from application.database.models import (
    Person,
    RiotAccount,
    Champion,
    ChampionMastery,
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
            Person.query
            .order_by(
                Person.display_name,
                Person.id,
            )
            .all()
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

            highest_mastery_champion = None

            if champion_totals:
                highest_mastery_champion = sorted(
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
                )[0]

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
    def get_person_mastery_overview(person_id):
        """
        Build the current combined Champion Mastery overview for one Person.

        The result contains:
        - all connected Riot Accounts
        - combined mastery per champion
        - one points value per Riot Account
        - the ten champions with the highest combined mastery
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

        champion_rows_by_id = {}

        for riot_account in riot_accounts:
            for mastery in riot_account.mastery_data:
                champion = mastery.champion

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
                    },
                )

                mastery_points = max(
                    int(mastery.mastery_points or 0),
                    0,
                )

                champion_row["points_by_account"][
                    riot_account.id
                ] = mastery_points

        champion_rows = list(
            champion_rows_by_id.values()
        )

        for champion_row in champion_rows:
            for riot_account in riot_accounts:
                champion_row["points_by_account"].setdefault(
                    riot_account.id,
                    0,
                )

            champion_row["total_mastery"] = sum(
                champion_row["points_by_account"].values()
            )

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
            "top_champions": champion_rows[:10],
            "champions": champion_rows,
            "total_mastery": total_mastery,
        }