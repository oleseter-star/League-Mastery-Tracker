from datetime import datetime, timedelta, timezone

from application.database.database import db
from application.database.models import (
    Person,
    RiotAccount,
    Champion,
    ChampionMastery,
)
from application.services.riot_service import RiotService


class SyncService:
    """
    Coordinates Riot account and Champion Mastery synchronization.
    """

    def __init__(self, riot_service=None):
        self.riot_service = riot_service

    def _get_riot_service(self):
        """
        Create the Riot service lazily inside the Flask application
        context unless one was supplied explicitly.
        """

        if self.riot_service is None:
            self.riot_service = RiotService()

        return self.riot_service

    def sync_account(
        self,
        person_id,
        game_name,
        tag_line,
        platform_region,
    ):
        """
        Create or update a Riot Account belonging to a Person.
        """

        person = db.session.get(
            Person,
            person_id,
        )

        if person is None:
            raise ValueError(
                f"Person with ID {person_id} was not found."
            )

        normalized_platform = (
            RiotService.normalize_platform_region(
                platform_region
            )
        )

        riot_service = self._get_riot_service()

        account_data = riot_service.get_account_by_riot_id(
            game_name=game_name,
            tag_line=tag_line,
            platform_region=normalized_platform,
        )

        puuid = account_data.get("puuid")

        if not puuid:
            raise ValueError(
                "Riot account data did not contain a PUUID."
            )

        riot_account = RiotAccount.query.filter_by(
            puuid=puuid
        ).one_or_none()

        if (
            riot_account is not None
            and riot_account.person_id != person.id
        ):
            raise ValueError(
                "This Riot Account is already connected "
                "to another Person."
            )

        canonical_game_name = (
            account_data.get("gameName")
            or game_name.strip()
        )

        canonical_tag_line = (
            account_data.get("tagLine")
            or tag_line.strip()
        )

        try:
            if riot_account is None:
                riot_account = RiotAccount(
                    person_id=person.id,
                    game_name=canonical_game_name,
                    tag_line=canonical_tag_line,
                    puuid=puuid,
                    platform_region=normalized_platform,
                )

                db.session.add(
                    riot_account
                )
            else:
                riot_account.game_name = canonical_game_name
                riot_account.tag_line = canonical_tag_line
                riot_account.platform_region = (
                    normalized_platform
                )

            db.session.commit()

            return riot_account

        except Exception:
            db.session.rollback()
            raise

    def sync_mastery(
        self,
        riot_account_id,
    ):
        """
        Replace the locally cached Champion Mastery state for one
        Riot Account with the current state returned by Riot.
        """

        riot_account = db.session.get(
            RiotAccount,
            riot_account_id,
        )

        if riot_account is None:
            raise ValueError(
                f"Riot Account with ID "
                f"{riot_account_id} was not found."
            )

        riot_service = self._get_riot_service()

        mastery_records = riot_service.get_champion_mastery(
            puuid=riot_account.puuid,
            platform_region=riot_account.platform_region,
        )

        synchronized_champion_ids = set()

        try:
            for mastery_record in mastery_records:
                riot_champion_id = mastery_record.get(
                    "championId"
                )

                mastery_points = mastery_record.get(
                    "championPoints"
                )

                if riot_champion_id is None:
                    continue

                if mastery_points is None:
                    mastery_points = 0

                champion = Champion.query.filter_by(
                    riot_champion_id=riot_champion_id
                ).one_or_none()

                if champion is None:
                    champion = Champion(
                        riot_champion_id=riot_champion_id,
                        name=None,
                        image=None,
                        source="riot",
                    )

                    db.session.add(
                        champion
                    )

                    db.session.flush()

                synchronized_champion_ids.add(
                    champion.id
                )

                mastery = ChampionMastery.query.filter_by(
                    riot_account_id=riot_account.id,
                    champion_id=champion.id,
                ).one_or_none()

                if mastery is None:
                    mastery = ChampionMastery(
                        riot_account_id=riot_account.id,
                        champion_id=champion.id,
                        mastery_points=int(mastery_points),
                    )

                    db.session.add(
                        mastery
                    )
                else:
                    mastery.mastery_points = int(
                        mastery_points
                    )

            existing_masteries = (
                ChampionMastery.query.filter_by(
                    riot_account_id=riot_account.id
                ).all()
            )

            for existing_mastery in existing_masteries:
                if (
                    existing_mastery.champion_id
                    not in synchronized_champion_ids
                ):
                    db.session.delete(
                        existing_mastery
                    )

            riot_account.last_sync = datetime.now(
                timezone.utc
            ).replace(
                tzinfo=None
            )

            db.session.commit()

            return {
                "riot_account_id": riot_account.id,
                "mastery_records": len(
                    synchronized_champion_ids
                ),
                "last_sync": riot_account.last_sync,
            }

        except Exception:
            db.session.rollback()
            raise

    def sync_account_and_mastery(
        self,
        person_id,
        game_name,
        tag_line,
        platform_region,
    ):
        """
        Synchronize both Riot Account identity and mastery state.
        """

        riot_account = self.sync_account(
            person_id=person_id,
            game_name=game_name,
            tag_line=tag_line,
            platform_region=platform_region,
        )

        return self.sync_mastery(
            riot_account_id=riot_account.id
        )

    def sync_stale_accounts(
        self,
        max_age_hours=24,
    ):
        """
        Synchronize accounts that have never been synchronized or
        whose last successful synchronization is at least the
        configured number of hours old.
        """

        try:
            normalized_max_age = float(
                max_age_hours
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Maximum sync age must be a number."
            ) from error

        if normalized_max_age <= 0:
            raise ValueError(
                "Maximum sync age must be greater than zero."
            )

        all_accounts = (
            RiotAccount.query
            .order_by(
                RiotAccount.id
            )
            .all()
        )

        current_time = datetime.now(
            timezone.utc
        ).replace(
            tzinfo=None
        )

        stale_threshold = current_time - timedelta(
            hours=normalized_max_age
        )

        stale_accounts = [
            riot_account
            for riot_account in all_accounts
            if (
                riot_account.last_sync is None
                or riot_account.last_sync <= stale_threshold
            )
        ]

        skipped_count = (
            len(all_accounts)
            - len(stale_accounts)
        )

        return self._sync_accounts(
            riot_accounts=stale_accounts,
            total_account_count=len(all_accounts),
            skipped_count=skipped_count,
            mode="stale",
        )

    def sync_all_accounts(self):
        """
        Force synchronization of every locally stored Riot Account,
        regardless of its last successful synchronization time.
        """

        riot_accounts = (
            RiotAccount.query
            .order_by(
                RiotAccount.id
            )
            .all()
        )

        return self._sync_accounts(
            riot_accounts=riot_accounts,
            total_account_count=len(riot_accounts),
            skipped_count=0,
            mode="all",
        )

    def _sync_accounts(
        self,
        riot_accounts,
        total_account_count,
        skipped_count,
        mode,
    ):
        """
        Synchronize multiple accounts independently.

        Failure on one account does not stop synchronization of the
        remaining accounts.
        """

        updated_count = 0
        failures = []

        for riot_account in riot_accounts:
            riot_id = (
                f"{riot_account.game_name}"
                f"#{riot_account.tag_line}"
            )

            try:
                self.sync_mastery(
                    riot_account_id=riot_account.id
                )

            except Exception:
                db.session.rollback()

                failures.append(
                    {
                        "riot_account_id": riot_account.id,
                        "riot_id": riot_id,
                        "error": (
                            "Champion Mastery could not be "
                            "synchronized. Existing mastery data for "
                            "this Riot account is unchanged. Try again."
                        ),
                    }
                )

            else:
                updated_count += 1

        return {
            "mode": mode,
            "total_accounts": total_account_count,
            "selected_accounts": len(riot_accounts),
            "updated": updated_count,
            "skipped": skipped_count,
            "failed": len(failures),
            "failures": failures,
        }