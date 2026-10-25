import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from application.database.database import db
from application.database.models import Person
from application.services.database_migration_service import (
    DatabaseMigrationService,
)


class PersonOrderError(ValueError):
    """
    Raised when a requested Person order is invalid.
    """


class PersonOrderService:
    """
    Stores the user-chosen dashboard order of Persons.

    The order is kept as a JSON list of Person IDs in the existing
    application metadata table. This avoids a database schema
    change, so JSON exports and backups stay compatible.

    Persons missing from the stored order (for example, newly added
    or imported Persons) are placed after the ordered Persons in
    alphabetical order. Stale IDs are ignored.
    """

    ORDER_KEY = "dashboard_person_order"

    MOVE_DIRECTIONS = (
        "earlier",
        "later",
    )

    @classmethod
    def get_ordered_persons(cls):
        """
        Return all Persons in dashboard order.
        """

        persons = (
            Person.query
            .order_by(
                Person.display_name,
                Person.id,
            )
            .all()
        )

        stored_order = cls._read_stored_order()

        positions = {
            person_id: position
            for position, person_id in enumerate(
                stored_order
            )
        }

        unordered_position = len(
            stored_order
        )

        # sorted() is stable, so unordered Persons keep their
        # alphabetical order after the ordered Persons.
        return sorted(
            persons,
            key=lambda person: positions.get(
                person.id,
                unordered_position,
            ),
        )

    @classmethod
    def save_order(
        cls,
        person_ids,
    ):
        """
        Store a complete new Person order.

        The list must contain every existing Person exactly once.
        """

        try:
            requested_ids = [
                int(person_id)
                for person_id in person_ids
            ]

        except (TypeError, ValueError) as error:
            raise PersonOrderError(
                "The Person order is invalid."
            ) from error

        existing_ids = {
            person_id
            for (person_id,) in db.session.query(
                Person.id
            ).all()
        }

        if (
            len(requested_ids) != len(set(requested_ids))
            or set(requested_ids) != existing_ids
        ):
            raise PersonOrderError(
                "The Person order must contain every "
                "Person exactly once."
            )

        cls._write_stored_order(
            requested_ids
        )

    @classmethod
    def move_person(
        cls,
        person_id,
        direction,
    ):
        """
        Move one Person one position earlier or later.

        Returns False when the Person does not exist.
        """

        if direction not in cls.MOVE_DIRECTIONS:
            raise PersonOrderError(
                "The move direction is invalid."
            )

        ordered_ids = [
            person.id
            for person in cls.get_ordered_persons()
        ]

        if person_id not in ordered_ids:
            return False

        index = ordered_ids.index(
            person_id
        )

        target_index = (
            index - 1
            if direction == "earlier"
            else index + 1
        )

        if 0 <= target_index < len(ordered_ids):
            ordered_ids[index], ordered_ids[target_index] = (
                ordered_ids[target_index],
                ordered_ids[index],
            )

        cls._write_stored_order(
            ordered_ids
        )

        return True

    @classmethod
    def _read_stored_order(cls):
        try:
            row = db.session.execute(
                text(
                    f"""
                    SELECT value
                    FROM {DatabaseMigrationService.METADATA_TABLE}
                    WHERE key = :key
                    """
                ),
                {
                    "key": cls.ORDER_KEY,
                },
            ).fetchone()

        except SQLAlchemyError:
            db.session.rollback()
            return []

        if row is None:
            return []

        try:
            stored_ids = json.loads(
                row[0]
            )

        except (TypeError, ValueError):
            return []

        if not isinstance(
            stored_ids,
            list,
        ):
            return []

        return [
            person_id
            for person_id in stored_ids
            if isinstance(person_id, int)
            and not isinstance(person_id, bool)
        ]

    @classmethod
    def _write_stored_order(
        cls,
        person_ids,
    ):
        db.session.execute(
            text(
                f"""
                INSERT INTO {DatabaseMigrationService.METADATA_TABLE} (
                    key,
                    value
                )
                VALUES (
                    :key,
                    :value
                )
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value
                """
            ),
            {
                "key": cls.ORDER_KEY,
                "value": json.dumps(
                    list(person_ids)
                ),
            },
        )

        db.session.commit()
