from application.database.database import db
from application.database.models import Person


class PersonService:
    """
    Service layer for local Person management.
    """

    @staticmethod
    def get_all_persons():
        """
        Return all Persons ordered by display name.
        """

        return (
            Person.query
            .order_by(
                Person.display_name
            )
            .all()
        )

    @staticmethod
    def get_person_by_id(person_id):
        """
        Return a Person by internal database ID.
        """

        return db.session.get(
            Person,
            person_id,
        )

    @staticmethod
    def create_person(display_name):
        """
        Create a new local Person.
        """

        normalized_name = PersonService._normalize_display_name(
            display_name
        )

        person = Person(
            display_name=normalized_name
        )

        try:
            db.session.add(person)
            db.session.commit()

            return person

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def update_person(person, display_name):
        """
        Update a Person's display name.
        """

        if person is None:
            raise ValueError(
                "Person is required."
            )

        person.display_name = (
            PersonService._normalize_display_name(
                display_name
            )
        )

        try:
            db.session.commit()

            return person

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def delete_person(person):
        """
        Delete a Person and all connected Riot Accounts and mastery data.
        """

        if person is None:
            raise ValueError(
                "Person is required."
            )

        try:
            db.session.delete(person)
            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _normalize_display_name(display_name):
        """
        Validate and normalize a Person display name.
        """

        if display_name is None:
            raise ValueError(
                "Display name is required."
            )

        normalized_name = str(
            display_name
        ).strip()

        if not normalized_name:
            raise ValueError(
                "Display name is required."
            )

        if len(normalized_name) > 120:
            raise ValueError(
                "Display name cannot exceed 120 characters."
            )

        return normalized_name