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
    Minimal dashboard endpoint required by the templates.
    """

    return "Test dashboard"


class PersonNavigationTestCase(unittest.TestCase):
    """
    Tests navigation between the dashboard, Person list and Person
    administration pages.
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
            SECRET_KEY="person-navigation-test-secret",
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

        self.alpha_person = Person(
            display_name="Alpha Person"
        )

        self.bravo_person = Person(
            display_name="Bravo Person"
        )

        db.session.add_all(
            [
                self.bravo_person,
                self.alpha_person,
            ]
        )

        db.session.flush()

        self.riot_account = RiotAccount(
            person_id=self.alpha_person.id,
            game_name="Navigation Account",
            tag_line="NAV",
            puuid="navigation-test-puuid",
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

    @staticmethod
    def normalize_html_whitespace(html):
        """
        Collapse template whitespace without changing visible text.
        """

        return " ".join(
            html.split()
        )

    def get_primary_navigation_links(
        self,
        html,
    ):
        """
        Return the actual anchors inside the primary navigation.
        """

        navigation_match = re.search(
            r'<nav\b[^>]*aria-label="Main navigation"[^>]*>'
            r'(?P<content>.*?)</nav>',
            html,
            flags=re.DOTALL,
        )

        self.assertIsNotNone(
            navigation_match
        )

        links = []

        for match in re.finditer(
                r'<a\b(?P<attributes>[^>]*)>'
                r'(?P<content>.*?)</a>',
                navigation_match.group(
                    "content"
                ),
                flags=re.DOTALL,
        ):
            attributes = match.group(
                "attributes"
            )

            def attribute_value(name):
                attribute_match = re.search(
                    rf'\b{re.escape(name)}\s*=\s*'
                    r'(?P<quote>["\'])'
                    r'(?P<value>.*?)'
                    r'(?P=quote)',
                    attributes,
                    flags=re.DOTALL,
                )

                if attribute_match is None:
                    if re.search(
                        rf'\b{re.escape(name)}\b',
                        attributes,
                    ):
                        return ""

                    return None

                return attribute_match.group(
                    "value"
                )

            links.append(
                {
                    "attributes": attributes,
                    "label": " ".join(
                        match.group(
                            "content"
                        ).split()
                    ),
                    "href": attribute_value(
                        "href"
                    ),
                    "aria_current": attribute_value(
                        "aria-current"
                    ),
                }
            )

        return links

    def assert_persons_navigation_is_current(
        self,
        html,
    ):
        links = self.get_primary_navigation_links(
            html
        )

        current_links = [
            link
            for link in links
            if re.search(
                r'\baria-current\s*=\s*"page"',
                link["attributes"],
            )
        ]

        self.assertEqual(
            len(current_links),
            1,
        )

        self.assertEqual(
            current_links[0]["label"],
            "Persons",
        )

        for link in links:
            if link["label"] != "Persons":
                self.assertNotRegex(
                    link["attributes"],
                    r"\baria-current\b",
                )

        self.assertEqual(
            [
                {
                    "label": link["label"],
                    "href": link["href"],
                    "aria_current": link[
                        "aria_current"
                    ],
                }
                for link in links
            ],
            [
                {
                    "label": "Dashboard",
                    "href": "/",
                    "aria_current": None,
                },
                {
                    "label": "Persons",
                    "href": "/persons",
                    "aria_current": "page",
                },
                {
                    "label": "Settings",
                    "href": "/settings",
                    "aria_current": None,
                },
            ],
        )

    def test_person_list_has_dashboard_navigation_and_sorted_person_links(
        self,
    ):
        """
        The Person list should link to the dashboard and each Person
        detail page using the existing display-name ordering.
        """

        response = self.client.get(
            "/persons"
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

        self.assertIn(
            'href="/"',
            html,
        )

        self.assertIn(
            "> Dashboard </a>",
            normalized_html,
        )

        self.assertIn(
            (
                f'href="/persons/'
                f'{self.alpha_person.id}"'
            ),
            html,
        )

        self.assertIn(
            (
                f'href="/persons/'
                f'{self.bravo_person.id}"'
            ),
            html,
        )

        alpha_position = html.index(
            "Alpha Person"
        )

        bravo_position = html.index(
            "Bravo Person"
        )

        self.assertLess(
            alpha_position,
            bravo_position,
        )

        self.assertIn(
            "Alpha Person",
            html,
        )

        self.assertIn(
            "Bravo Person",
            html,
        )

    def test_person_detail_links_to_dashboard_and_person_list(
        self,
    ):
        """
        A Person detail page should provide direct navigation both
        to daily use and to Person administration.
        """

        response = self.client.get(
            f"/persons/{self.alpha_person.id}"
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

        self.assertIn(
            'href="/"',
            html,
        )

        self.assertIn(
            "> Dashboard </a>",
            normalized_html,
        )

        self.assertIn(
            'href="/persons"',
            html,
        )

        self.assertIn(
            "> All persons </a>",
            normalized_html,
        )

    def test_person_list_and_detail_mark_persons_navigation_current(
        self,
    ):
        """
        Both Persons pages should identify Persons as the section.
        """

        list_response = self.client.get(
            "/persons"
        )

        self.assertEqual(
            list_response.status_code,
            200,
        )

        self.assert_persons_navigation_is_current(
            list_response.get_data(
                as_text=True
            )
        )

        detail_response = self.client.get(
            f"/persons/{self.alpha_person.id}"
        )

        self.assertEqual(
            detail_response.status_code,
            200,
        )

        self.assert_persons_navigation_is_current(
            detail_response.get_data(
                as_text=True
            )
        )

    def test_person_administration_forms_remain_person_scoped_and_csrf_protected(
        self,
    ):
        """
        Person creation, account connection, account movement and
        name editing should remain explicit Person-scoped actions.
        """

        list_response = self.client.get(
            "/persons"
        )

        self.assertEqual(
            list_response.status_code,
            200,
        )

        list_html = list_response.get_data(
            as_text=True
        )

        self.assertIn(
            'action="/persons"',
            list_html,
        )

        self.assertIn(
            'name="_csrf_token"',
            list_html,
        )

        self.assertIn(
            'value="test-csrf-token"',
            list_html,
        )

        detail_response = self.client.get(
            f"/persons/{self.alpha_person.id}"
        )

        self.assertEqual(
            detail_response.status_code,
            200,
        )

        detail_html = detail_response.get_data(
            as_text=True
        )

        self.assertIn(
            (
                f'action="/persons/'
                f'{self.alpha_person.id}/edit"'
            ),
            detail_html,
        )

        self.assertIn(
            (
                f'action="/persons/'
                f'{self.alpha_person.id}/riot-accounts"'
            ),
            detail_html,
        )

        self.assertIn(
            (
                f'action="/persons/'
                f'{self.alpha_person.id}'
                f'/riot-accounts/'
                f'{self.riot_account.id}/move"'
            ),
            detail_html,
        )

        self.assertGreaterEqual(
            detail_html.count(
                'name="_csrf_token"'
            ),
            3,
        )

        self.assertNotRegex(
            detail_html,
            r"/persons/\d+/riot-accounts/\d+/delete",
        )


if __name__ == "__main__":
    unittest.main()