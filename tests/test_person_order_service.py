import unittest

from flask import Flask
from sqlalchemy import text

from application.database.database import db
from application.database.models import Person
from application.routes.dashboard import dashboard_bp
from application.services.person_order_service import (
    PersonOrderError,
    PersonOrderService,
)


class PersonOrderServiceTestCase(unittest.TestCase):
    """
    Tests the stored dashboard order of Persons and its routes.
    """

    def setUp(self):
        self.app = Flask(__name__)

        self.app.config.update(
            TESTING=True,
            SECRET_KEY="person-order-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(
            self.app
        )

        self.app.register_blueprint(
            dashboard_bp
        )

        self.app.add_url_rule(
            "/",
            "home.home",
            lambda: "Test home",
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

        # The real application creates this table through the
        # database migration service.
        db.session.execute(
            text(
                """
                CREATE TABLE application_metadata (
                    key TEXT PRIMARY KEY NOT NULL,
                    value TEXT NOT NULL
                )
                """
            )
        )

        self.charlie = Person(display_name="Charlie")
        self.alice = Person(display_name="Alice")
        self.bob = Person(display_name="Bob")

        db.session.add_all(
            [
                self.charlie,
                self.alice,
                self.bob,
            ]
        )

        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _ordered_names(self):
        return [
            person.display_name
            for person in PersonOrderService.get_ordered_persons()
        ]

    def test_default_order_is_alphabetical(self):
        self.assertEqual(
            self._ordered_names(),
            ["Alice", "Bob", "Charlie"],
        )

    def test_saved_order_is_used(self):
        PersonOrderService.save_order(
            [
                self.charlie.id,
                self.alice.id,
                self.bob.id,
            ]
        )

        self.assertEqual(
            self._ordered_names(),
            ["Charlie", "Alice", "Bob"],
        )

    def test_new_persons_are_appended_alphabetically(self):
        PersonOrderService.save_order(
            [
                self.charlie.id,
                self.bob.id,
                self.alice.id,
            ]
        )

        db.session.add_all(
            [
                Person(display_name="Zed"),
                Person(display_name="Anna"),
            ]
        )
        db.session.commit()

        self.assertEqual(
            self._ordered_names(),
            ["Charlie", "Bob", "Alice", "Anna", "Zed"],
        )

    def test_deleted_persons_are_ignored(self):
        PersonOrderService.save_order(
            [
                self.charlie.id,
                self.bob.id,
                self.alice.id,
            ]
        )

        db.session.delete(self.bob)
        db.session.commit()

        self.assertEqual(
            self._ordered_names(),
            ["Charlie", "Alice"],
        )

    def test_save_order_rejects_incomplete_or_duplicate_ids(self):
        invalid_orders = [
            [self.alice.id, self.bob.id],
            [self.alice.id, self.bob.id, self.bob.id],
            [self.alice.id, self.bob.id, self.charlie.id, 999],
            ["not-a-number"],
        ]

        for invalid_order in invalid_orders:
            with self.subTest(order=invalid_order):
                with self.assertRaises(PersonOrderError):
                    PersonOrderService.save_order(
                        invalid_order
                    )

    def test_corrupt_stored_order_falls_back_to_alphabetical(self):
        db.session.execute(
            text(
                """
                INSERT INTO application_metadata (key, value)
                VALUES (:key, 'not json')
                """
            ),
            {
                "key": PersonOrderService.ORDER_KEY,
            },
        )
        db.session.commit()

        self.assertEqual(
            self._ordered_names(),
            ["Alice", "Bob", "Charlie"],
        )

    def test_move_person_swaps_with_neighbor(self):
        PersonOrderService.move_person(
            self.charlie.id,
            "earlier",
        )

        self.assertEqual(
            self._ordered_names(),
            ["Alice", "Charlie", "Bob"],
        )

        PersonOrderService.move_person(
            self.alice.id,
            "later",
        )

        self.assertEqual(
            self._ordered_names(),
            ["Charlie", "Alice", "Bob"],
        )

    def test_move_past_the_edge_keeps_order(self):
        PersonOrderService.move_person(
            self.alice.id,
            "earlier",
        )

        self.assertEqual(
            self._ordered_names(),
            ["Alice", "Bob", "Charlie"],
        )

    def test_move_unknown_person_returns_false(self):
        self.assertFalse(
            PersonOrderService.move_person(
                999,
                "later",
            )
        )

    def test_move_rejects_invalid_direction(self):
        with self.assertRaises(PersonOrderError):
            PersonOrderService.move_person(
                self.alice.id,
                "sideways",
            )

    def test_order_route_saves_order(self):
        response = self.client.post(
            "/dashboard/persons/order",
            data={
                "person_ids": (
                    f"{self.bob.id},{self.charlie.id},{self.alice.id}"
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            self._ordered_names(),
            ["Bob", "Charlie", "Alice"],
        )

    def test_order_route_rejects_invalid_order(self):
        response = self.client.post(
            "/dashboard/persons/order",
            data={
                "person_ids": f"{self.bob.id}",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            self._ordered_names(),
            ["Alice", "Bob", "Charlie"],
        )

    def test_move_route_moves_person(self):
        response = self.client.post(
            f"/dashboard/persons/{self.bob.id}/move",
            data={
                "direction": "earlier",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                f"#person-{self.bob.id}"
            )
        )

        self.assertEqual(
            self._ordered_names(),
            ["Bob", "Alice", "Charlie"],
        )


if __name__ == "__main__":
    unittest.main()
