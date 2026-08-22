import unittest
from pathlib import Path

from flask import Blueprint, Flask

from application.database.database import db
from application.database.models import (
    Person,
    RiotAccount,
)
from application.routes.persons import persons_bp


home_bp = Blueprint(
    "home",
    __name__,
)


@home_bp.route("/")
def home():
    """
    Minimal home endpoint required when rendering person templates.
    """

    return "Test home"


class PersonRouteTestCase(unittest.TestCase):
    """
    Tests Person and Riot Account administration routes.
    """

    def setUp(self):
        template_folder = (
            Path(__file__).resolve().parents[1]
            / "application"
            / "templates"
        )

        self.app = Flask(
            __name__,
            template_folder=str(template_folder),
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY="person-route-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(
            self.app
        )

        self.app.register_blueprint(
            home_bp
        )

        self.app.register_blueprint(
            persons_bp
        )

        self.app.jinja_env.globals[
            "csrf_token"
        ] = lambda: "test-csrf-token"

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

        self.source_person = Person(
            display_name="Source Person"
        )

        self.target_person = Person(
            display_name="Target Person"
        )

        self.unrelated_person = Person(
            display_name="Unrelated Person"
        )

        db.session.add_all(
            [
                self.source_person,
                self.target_person,
                self.unrelated_person,
            ]
        )

        db.session.flush()

        self.riot_account = RiotAccount(
            person_id=self.source_person.id,
            game_name="Move Account",
            tag_line="MOVE",
            puuid="move-route-puuid",
            platform_region="EUW1",
        )

        db.session.add(
            self.riot_account
        )

        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

    def get_flashed_messages(self):
        """
        Return pending flash messages from the test session.
        """

        with self.client.session_transaction() as session:
            return list(
                session.get(
                    "_flashes",
                    [],
                )
            )

    @staticmethod
    def normalize_html_whitespace(html):
        """
        Collapse HTML whitespace so visible text can be tested
        independently of template indentation and line breaks.
        """

        return " ".join(
            html.split()
        )

    def test_person_page_shows_explicit_move_form_for_other_persons(
        self,
    ):
        """
        Each Riot Account should offer all other Persons as explicit
        move targets, but never its current owner.
        """

        response = self.client.get(
            f"/persons/{self.source_person.id}"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        html = response.get_data(
            as_text=True
        )

        move_action = (
            f"/persons/{self.source_person.id}"
            f"/riot-accounts/{self.riot_account.id}"
            "/move"
        )

        self.assertIn(
            move_action,
            html,
        )

        self.assertIn(
            'name="target_person_id"',
            html,
        )

        self.assertIn(
            f'value="{self.target_person.id}"',
            html,
        )

        self.assertIn(
            "Target Person",
            html,
        )

        self.assertIn(
            f'value="{self.unrelated_person.id}"',
            html,
        )

        self.assertIn(
            "Unrelated Person",
            html,
        )

        self.assertNotIn(
            f'value="{self.source_person.id}"',
            html,
        )

        target_position = html.index(
            "Target Person"
        )

        unrelated_position = html.index(
            "Unrelated Person"
        )

        self.assertLess(
            target_position,
            unrelated_position,
        )

    def test_person_page_explains_when_no_move_target_exists(
        self,
    ):
        """
        The UI should explain why moving is unavailable when there
        is no other Person.
        """

        db.session.delete(
            self.target_person
        )

        db.session.delete(
            self.unrelated_person
        )

        db.session.commit()

        response = self.client.get(
            f"/persons/{self.source_person.id}"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        html = response.get_data(
            as_text=True
        )

        normalized_html = (
            self.normalize_html_whitespace(
                html
            )
        )

        move_action = (
            f"/persons/{self.source_person.id}"
            f"/riot-accounts/{self.riot_account.id}"
            "/move"
        )

        self.assertNotIn(
            move_action,
            html,
        )

        self.assertIn(
    (
        "Create at least one other person "
        "before moving the Riot account."
    ),
    normalized_html,
)

    def test_move_riot_account_moves_account_and_redirects_to_target(
        self,
    ):
        """
        A successful move should redirect to the target Person.
        """

        response = self.client.post(
            (
                f"/persons/{self.source_person.id}"
                f"/riot-accounts/{self.riot_account.id}"
                "/move"
            ),
            data={
                "target_person_id": (
                    str(self.target_person.id)
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                f"/persons/{self.target_person.id}"
            )
        )

        moved_account = db.session.get(
            RiotAccount,
            self.riot_account.id,
        )

        self.assertEqual(
            moved_account.person_id,
            self.target_person.id,
        )

        self.assertEqual(
            moved_account.puuid,
            "move-route-puuid",
        )

        self.assertIn(
            (
                "success",
                (
                    'Riot account "Move Account#MOVE" '
                    'was moved to "Target Person".'
                ),
            ),
            self.get_flashed_messages(),
        )

    def test_move_riot_account_returns_404_for_unknown_source_person(
        self,
    ):
        """
        An unknown source Person should return HTTP 404.
        """

        response = self.client.post(
            (
                "/persons/999999"
                f"/riot-accounts/{self.riot_account.id}"
                "/move"
            ),
            data={
                "target_person_id": (
                    str(self.target_person.id)
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

    def test_move_riot_account_rejects_account_owned_by_another_person(
        self,
    ):
        """
        The route must not move an account through the wrong source
        Person.
        """

        response = self.client.post(
            (
                f"/persons/{self.unrelated_person.id}"
                f"/riot-accounts/{self.riot_account.id}"
                "/move"
            ),
            data={
                "target_person_id": (
                    str(self.target_person.id)
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                f"/persons/{self.unrelated_person.id}"
            )
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

        self.assertIn(
            (
                "error",
                (
                    "The Riot account was not found "
                    "for this person."
                ),
            ),
            self.get_flashed_messages(),
        )

    def test_move_riot_account_rejects_missing_target_person(
        self,
    ):
        """
        A missing target Person selection should preserve ownership.
        """

        response = self.client.post(
            (
                f"/persons/{self.source_person.id}"
                f"/riot-accounts/{self.riot_account.id}"
                "/move"
            ),
            data={},
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                f"/persons/{self.source_person.id}"
            )
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

        self.assertIn(
            (
                "error",
                "A target person is required.",
            ),
            self.get_flashed_messages(),
        )

    def test_move_riot_account_rejects_unknown_target_person(
        self,
    ):
        """
        An unknown target Person should preserve the current owner.
        """

        response = self.client.post(
            (
                f"/persons/{self.source_person.id}"
                f"/riot-accounts/{self.riot_account.id}"
                "/move"
            ),
            data={
                "target_person_id": "999999",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                f"/persons/{self.source_person.id}"
            )
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

        self.assertIn(
            (
                "error",
                "The target person was not found.",
            ),
            self.get_flashed_messages(),
        )

    def test_move_riot_account_rejects_current_person_as_target(
        self,
    ):
        """
        Selecting the current owner should not perform a move.
        """

        response = self.client.post(
            (
                f"/persons/{self.source_person.id}"
                f"/riot-accounts/{self.riot_account.id}"
                "/move"
            ),
            data={
                "target_person_id": (
                    str(self.source_person.id)
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                f"/persons/{self.source_person.id}"
            )
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account.id,
        )

        self.assertEqual(
            stored_account.person_id,
            self.source_person.id,
        )

        self.assertIn(
            (
                "error",
                (
                    "The Riot account already belongs "
                    "to the selected person."
                ),
            ),
            self.get_flashed_messages(),
        )


if __name__ == "__main__":
    unittest.main()