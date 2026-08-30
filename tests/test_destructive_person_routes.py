import json
import re
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
    Minimal home endpoint required by person_detail.html.
    """

    return "Test home"


class DestructivePersonRoutesTestCase(
    unittest.TestCase
):
    """
    Verifies restored Person deletion while unresolved Riot account
    deletion remains unavailable.
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
            SECRET_KEY="destructive-route-test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(self.app)

        self.app.register_blueprint(home_bp)
        self.app.register_blueprint(persons_bp)

        self.app.jinja_env.globals[
            "csrf_token"
        ] = lambda: "test-csrf-token"

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        self.person = Person(
            display_name="Protected Person"
        )

        db.session.add(self.person)
        db.session.flush()

        self.riot_account = RiotAccount(
            person_id=self.person.id,
            game_name="Protected Account",
            tag_line="SAFE",
            puuid="protected-route-puuid",
            platform_region="EUW1",
        )

        db.session.add(self.riot_account)
        db.session.commit()

        self.person_id = self.person.id
        self.riot_account_id = self.riot_account.id

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

        self.app_context.pop()

    def get_person_page_html(self):
        """
        Return the rendered Person detail page.
        """

        response = self.client.get(
            f"/persons/{self.person_id}"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        return response.get_data(
            as_text=True
        )

    def get_delete_form(
        self,
        html,
    ):
        """
        Return the rendered form for this Person's delete endpoint.
        """

        delete_action = (
            f"/persons/{self.person_id}/delete"
        )

        action_index = html.find(
            delete_action
        )

        self.assertNotEqual(
            action_index,
            -1,
        )

        form_start = html.rfind(
            "<form",
            0,
            action_index,
        )

        form_end = html.find(
            "</form>",
            action_index,
        )

        self.assertNotEqual(
            form_start,
            -1,
        )

        self.assertNotEqual(
            form_end,
            -1,
        )

        return html[
            form_start:form_end
        ]

    def get_delete_confirmation(
        self,
        delete_form,
    ):
        """
        Decode the JSON string passed to the delete confirmation.
        """

        confirmation_match = re.search(
            r"return\s+confirm\(\s*"
            r'(?P<message>"(?:\\.|[^"\\])*")'
            r"\s*\);",
            delete_form,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(
            confirmation_match,
        )

        return json.loads(
            confirmation_match.group(
                "message"
            )
        )

    def test_person_page_shows_confirmed_delete_person_action(
        self,
    ):
        """
        The Person page must offer protected Person deletion.
        """

        html = self.get_person_page_html()

        delete_form = self.get_delete_form(
            html
        )

        self.assertIn(
            'method="post"',
            delete_form.lower(),
        )

        self.assertIn(
            'name="_csrf_token"',
            delete_form,
        )

        self.assertIn(
            "test-csrf-token",
            delete_form,
        )

        self.assertIn(
            "Delete person",
            delete_form,
        )

        self.assertIn(
            "and all connected Riot accounts and Champion "
            "Mastery data? This cannot be undone.",
            self.get_delete_confirmation(
                delete_form
            ),
        )

    def test_delete_confirmation_names_person_and_safely_encodes_display_name(
        self,
    ):
        """
        The rendered delete form must name and safely encode its Person.
        """

        self.person.display_name = (
            'Riot "O\'Connor" <Admin> & \u5317'
        )

        db.session.commit()

        delete_form = self.get_delete_form(
            self.get_person_page_html()
        )

        self.assertIn(
            'method="post"',
            delete_form.lower(),
        )

        self.assertIn(
            'name="_csrf_token"',
            delete_form,
        )

        self.assertIn(
            "test-csrf-token",
            delete_form,
        )

        self.assertIn(
            "Delete person",
            delete_form,
        )

        confirmation = self.get_delete_confirmation(
            delete_form
        )

        self.assertIn(
            self.person.display_name,
            confirmation,
        )

        self.assertNotIn(
            "delete this person",
            confirmation,
        )

        self.assertIn(
            "and all connected Riot accounts and Champion "
            "Mastery data? This cannot be undone.",
            confirmation,
        )

        self.assertIn(
            "\\u003cAdmin\\u003e",
            delete_form,
        )

        self.assertNotIn(
            "<Admin>",
            delete_form,
        )

        self.assertNotIn(
            self.riot_account.puuid,
            confirmation,
        )

    def test_delete_person_endpoint_deletes_connected_data(
        self,
    ):
        """
        A confirmed POST must delete the Person and connected account.
        """

        response = self.client.post(
            f"/persons/{self.person_id}/delete",
            data={
                "_csrf_token": "test-csrf-token",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            response.headers["Location"].endswith(
                "/persons"
            )
        )

        stored_person = db.session.get(
            Person,
            self.person_id,
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account_id,
        )

        self.assertIsNone(
            stored_person
        )

        self.assertIsNone(
            stored_account
        )

        with self.client.session_transaction() as session:
            flashes = session.get(
                "_flashes",
                [],
            )

        self.assertIn(
            (
                "success",
                'Person "Protected Person" was deleted.',
            ),
            flashes,
        )

    def test_delete_person_endpoint_rejects_get_requests(
        self,
    ):
        """
        Person deletion must only accept POST requests.
        """

        response = self.client.get(
            f"/persons/{self.person_id}/delete"
        )

        self.assertEqual(
            response.status_code,
            405,
        )

        self.assertIsNotNone(
            db.session.get(
                Person,
                self.person_id,
            )
        )

        self.assertIsNotNone(
            db.session.get(
                RiotAccount,
                self.riot_account_id,
            )
        )

    def test_delete_missing_person_returns_not_found(
        self,
    ):
        """
        Deleting an unknown Person must return 404 without data loss.
        """

        response = self.client.post(
            "/persons/999999/delete",
            data={
                "_csrf_token": "test-csrf-token",
            },
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        self.assertIsNotNone(
            db.session.get(
                Person,
                self.person_id,
            )
        )

        self.assertIsNotNone(
            db.session.get(
                RiotAccount,
                self.riot_account_id,
            )
        )

    def test_person_page_does_not_show_delete_account_action(
        self,
    ):
        """
        Riot account deletion remains unavailable.
        """

        html = self.get_person_page_html()

        delete_action = (
            f"/persons/{self.person_id}"
            f"/riot-accounts/{self.riot_account_id}"
            "/delete"
        )

        self.assertNotIn(
            delete_action,
            html,
        )

        self.assertNotIn(
            "Remove account",
            html,
        )

    def test_delete_account_endpoint_is_unavailable_and_preserves_data(
        self,
    ):
        """
        Direct POST requests cannot delete a Riot account.
        """

        response = self.client.post(
            (
                f"/persons/{self.person_id}"
                f"/riot-accounts/{self.riot_account_id}"
                "/delete"
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        stored_person = db.session.get(
            Person,
            self.person_id,
        )

        stored_account = db.session.get(
            RiotAccount,
            self.riot_account_id,
        )

        self.assertIsNotNone(
            stored_person
        )

        self.assertIsNotNone(
            stored_account
        )

        self.assertEqual(
            stored_account.person_id,
            self.person_id,
        )


if __name__ == "__main__":
    unittest.main()