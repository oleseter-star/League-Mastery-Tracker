from application.database.database import db
from application.database.models import (
    Person,
    RiotAccount,
)


class RiotAccountService:
    """
    Service layer for locally stored Riot Accounts.
    """

    @staticmethod
    def get_riot_account_by_id(riot_account_id):
        """
        Return a Riot Account by its internal database ID.
        """

        return db.session.get(
            RiotAccount,
            riot_account_id,
        )

    @staticmethod
    def move_riot_account(
        source_person_id,
        riot_account_id,
        target_person_id,
    ):
        """
        Move one Riot Account from one Person to another.

        The Riot Account itself is preserved. Its PUUID, Riot ID,
        platform, synchronization metadata and Champion Mastery
        records remain unchanged.
        """

        riot_account = db.session.get(
            RiotAccount,
            riot_account_id,
        )

        if (
            riot_account is None
            or riot_account.person_id
            != source_person_id
        ):
            raise ValueError(
                "The Riot account was not found "
                "for this person."
            )

        if target_person_id is None:
            raise ValueError(
                "A target person is required."
            )

        try:
            normalized_target_person_id = int(
                target_person_id
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                "A target person is required."
            ) from error

        target_person = db.session.get(
            Person,
            normalized_target_person_id,
        )

        if target_person is None:
            raise ValueError(
                "The target person was not found."
            )

        if (
            riot_account.person_id
            == target_person.id
        ):
            raise ValueError(
                "The Riot account already belongs "
                "to the selected person."
            )

        source_person_id = (
            riot_account.person_id
        )

        riot_id = (
            f"{riot_account.game_name}"
            f"#{riot_account.tag_line}"
        )

        try:
            riot_account.person_id = (
                target_person.id
            )

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

        return {
            "riot_account_id": riot_account.id,
            "riot_id": riot_id,
            "source_person_id": source_person_id,
            "target_person_id": target_person.id,
        }

    @staticmethod
    def delete_riot_account(
        person_id,
        riot_account_id,
    ):
        """
        Delete one Riot Account belonging to the specified Person.

        Connected Champion Mastery records are removed through the
        database relationship's delete cascade. Champion reference
        records are preserved.

        This method is retained for compatibility with existing
        code, but destructive account removal is outside the current
        Step 7 scope.
        """

        riot_account = db.session.get(
            RiotAccount,
            riot_account_id,
        )

        if (
            riot_account is None
            or riot_account.person_id != person_id
        ):
            raise ValueError(
                "The Riot account was not found for this person."
            )

        riot_id = (
            f"{riot_account.game_name}"
            f"#{riot_account.tag_line}"
        )

        try:
            db.session.delete(
                riot_account
            )

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

        return {
            "riot_account_id": riot_account_id,
            "riot_id": riot_id,
        }