import unittest
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.database.models import Person
from application.services.person_service import PersonService


class PersonServiceTestCase(unittest.TestCase):
    """
    Tests PersonService against an isolated in-memory database.
    """

    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(
            self.app
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

    def create_person(
        self,
        display_name,
    ):
        """
        Create and persist one Person for test setup.
        """

        person = Person(
            display_name=display_name
        )

        db.session.add(
            person
        )

        db.session.commit()

        return person

    def test_create_person_normalizes_display_name(self):
        """
        Leading and trailing whitespace should be removed before
        the Person is stored.
        """

        person = PersonService.create_person(
            display_name="  Test Person  "
        )

        self.assertIsNotNone(
            person.id
        )

        self.assertEqual(
            person.display_name,
            "Test Person",
        )

        stored_person = db.session.get(
            Person,
            person.id,
        )

        self.assertEqual(
            stored_person.display_name,
            "Test Person",
        )

    def test_create_person_rejects_missing_or_blank_name(self):
        """
        Missing and whitespace-only names should be rejected.
        """

        invalid_names = [
            None,
            "",
            " ",
            "\t",
            "\n",
        ]

        for invalid_name in invalid_names:
            with self.subTest(
                invalid_name=invalid_name
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Display name is required.",
                ):
                    PersonService.create_person(
                        display_name=invalid_name
                    )

        self.assertEqual(
            Person.query.count(),
            0,
        )

    def test_create_person_rejects_name_longer_than_120_characters(self):
        """
        Person display names must respect the database field limit.
        """

        with self.assertRaisesRegex(
            ValueError,
            "Display name cannot exceed 120 characters.",
        ):
            PersonService.create_person(
                display_name="A" * 121
            )

        self.assertEqual(
            Person.query.count(),
            0,
        )

    def test_create_person_accepts_name_with_exactly_120_characters(self):
        """
        A display name equal to the field limit should be accepted.
        """

        display_name = "A" * 120

        person = PersonService.create_person(
            display_name=display_name
        )

        self.assertEqual(
            person.display_name,
            display_name,
        )

    def test_get_person_by_id_returns_persisted_person(self):
        """
        A persisted Person should be retrievable by internal ID.
        """

        person = self.create_person(
            display_name="Stored Person"
        )

        result = PersonService.get_person_by_id(
            person.id
        )

        self.assertIsNotNone(
            result
        )

        self.assertEqual(
            result.id,
            person.id,
        )

        self.assertEqual(
            result.display_name,
            "Stored Person",
        )

    def test_get_person_by_id_returns_none_for_unknown_id(self):
        """
        An unknown internal ID should return None.
        """

        result = PersonService.get_person_by_id(
            999999
        )

        self.assertIsNone(
            result
        )

    def test_get_all_persons_orders_by_display_name(self):
        """
        Persons should be returned in display-name order.
        """

        self.create_person(
            display_name="Charlie"
        )

        self.create_person(
            display_name="Alpha"
        )

        self.create_person(
            display_name="Bravo"
        )

        persons = PersonService.get_all_persons()

        self.assertEqual(
            [
                person.display_name
                for person in persons
            ],
            [
                "Alpha",
                "Bravo",
                "Charlie",
            ],
        )

    def test_update_person_normalizes_display_name(self):
        """
        Updating a Person should apply the same normalization as
        creation.
        """

        person = self.create_person(
            display_name="Old Name"
        )

        updated_person = PersonService.update_person(
            person=person,
            display_name="  New Name  ",
        )

        self.assertEqual(
            updated_person.id,
            person.id,
        )

        self.assertEqual(
            updated_person.display_name,
            "New Name",
        )

        stored_person = db.session.get(
            Person,
            person.id,
        )

        self.assertEqual(
            stored_person.display_name,
            "New Name",
        )

    def test_update_person_rejects_missing_person(self):
        """
        Updating without a Person instance should be rejected.
        """

        with self.assertRaisesRegex(
            ValueError,
            "Person is required.",
        ):
            PersonService.update_person(
                person=None,
                display_name="New Name",
            )

    def test_update_person_rejects_invalid_name_without_changing_person(self):
        """
        Invalid update input must preserve the existing display name.
        """

        person = self.create_person(
            display_name="Original Name"
        )

        with self.assertRaisesRegex(
            ValueError,
            "Display name is required.",
        ):
            PersonService.update_person(
                person=person,
                display_name="   ",
            )

        stored_person = db.session.get(
            Person,
            person.id,
        )

        self.assertEqual(
            stored_person.display_name,
            "Original Name",
        )

    def test_create_person_rolls_back_when_commit_fails(self):
        """
        A failed database commit must not leave a pending Person in
        the database.
        """

        with patch(
            (
                "application.services.person_service."
                "db.session.commit"
            ),
            side_effect=RuntimeError(
                "Simulated commit failure"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Simulated commit failure",
            ):
                PersonService.create_person(
                    display_name="Rollback Person"
                )

        self.assertEqual(
            Person.query.count(),
            0,
        )


if __name__ == "__main__":
    unittest.main()