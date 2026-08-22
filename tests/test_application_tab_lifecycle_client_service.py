import unittest

from flask import Flask

from application.services.application_tab_lifecycle_client_service import (
    ApplicationTabLifecycleClientService,
)


class ApplicationTabLifecycleClientServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.service = (
            ApplicationTabLifecycleClientService()
        )

    def test_default_settings_are_defined(self):
        self.assertEqual(
            self.service.script_path,
            (
                "/static/"
                "application_tab_lifecycle.js"
            ),
        )

        self.assertEqual(
            self.service.bootstrap_element_id,
            (
                "league-mastery-tracker-"
                "tab-lifecycle"
            ),
        )

    def test_build_bootstrap_html_contains_required_data(
        self
    ):
        bootstrap_html = (
            self.service.build_bootstrap_html(
                csrf_token=(
                    "test-csrf-token"
                ),
            )
        )

        self.assertIn(
            (
                'id="league-mastery-tracker-'
                'tab-lifecycle"'
            ),
            bootstrap_html,
        )

        self.assertIn(
            (
                'src="/static/'
                'application_tab_lifecycle.js"'
            ),
            bootstrap_html,
        )

        self.assertIn(
            'data-csrf-token="test-csrf-token"',
            bootstrap_html,
        )

        self.assertIn(
            (
                'data-heartbeat-url="'
                '/application/tabs/heartbeat"'
            ),
            bootstrap_html,
        )

        self.assertIn(
            (
                'data-close-url="'
                '/application/tabs/close"'
            ),
            bootstrap_html,
        )

        self.assertIn(
            "defer",
            bootstrap_html,
        )

    def test_bootstrap_values_are_html_escaped(
        self
    ):
        bootstrap_html = (
            self.service.build_bootstrap_html(
                csrf_token=(
                    '"<unsafe>&'
                ),
            )
        )

        self.assertNotIn(
            '"<unsafe>&',
            bootstrap_html,
        )

        self.assertIn(
            (
                "&quot;&lt;unsafe&gt;&amp;"
            ),
            bootstrap_html,
        )

    def test_bootstrap_requires_csrf_token(
        self
    ):
        with self.assertRaises(
            ValueError
        ):
            self.service.build_bootstrap_html(
                csrf_token="",
            )

    def test_injection_occurs_before_body_end(
        self
    ):
        original_html = (
            "<!doctype html>"
            "<html>"
            "<body>"
            "<main>Content</main>"
            "</body>"
            "</html>"
        )

        injected_html = (
            self.service.inject_into_html(
                html=original_html,
                csrf_token=(
                    "test-csrf-token"
                ),
            )
        )

        bootstrap_position = (
            injected_html.index(
                (
                    'id="league-mastery-tracker-'
                    'tab-lifecycle"'
                )
            )
        )

        body_end_position = (
            injected_html.index(
                "</body>"
            )
        )

        self.assertLess(
            bootstrap_position,
            body_end_position,
        )

        self.assertIn(
            "<main>Content</main>",
            injected_html,
        )

    def test_injection_appends_when_body_end_is_missing(
        self
    ):
        original_html = (
            "<!doctype html>"
            "<html>"
            "<main>Content</main>"
            "</html>"
        )

        injected_html = (
            self.service.inject_into_html(
                html=original_html,
                csrf_token=(
                    "test-csrf-token"
                ),
            )
        )

        self.assertTrue(
            injected_html.endswith(
                (
                    'src="/static/'
                    'application_tab_lifecycle.js"'
                    " defer></script>"
                )
            )
        )

    def test_repeated_injection_is_idempotent(
        self
    ):
        original_html = (
            "<html>"
            "<body>"
            "Content"
            "</body>"
            "</html>"
        )

        first_result = (
            self.service.inject_into_html(
                html=original_html,
                csrf_token=(
                    "test-csrf-token"
                ),
            )
        )

        second_result = (
            self.service.inject_into_html(
                html=first_result,
                csrf_token=(
                    "test-csrf-token"
                ),
            )
        )

        self.assertEqual(
            first_result,
            second_result,
        )

        self.assertEqual(
            second_result.count(
                (
                    'id="league-mastery-tracker-'
                    'tab-lifecycle"'
                )
            ),
            1,
        )

    def test_non_html_response_is_not_modified(
        self
    ):
        app = Flask(
            __name__
        )

        self.service.init_app(
            app
        )

        @app.get("/data")
        def data():
            return (
                '{"status":"ok"}',
                200,
                {
                    "Content-Type": (
                        "application/json"
                    ),
                },
            )

        client = app.test_client()

        response = client.get(
            "/data"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotIn(
            (
                "application_tab_lifecycle.js"
            ),
            response.get_data(
                as_text=True
            ),
        )

    def test_html_response_is_not_modified_without_lifecycle_service(
        self
    ):
        app = Flask(
            __name__
        )

        app.config.update(
            SECRET_KEY=(
                "tab-client-test"
            ),
        )

        app.jinja_env.globals[
            "csrf_token"
        ] = lambda: (
            "test-csrf-token"
        )

        self.service.init_app(
            app
        )

        @app.get("/")
        def home():
            return (
                "<html><body>Home</body></html>"
            )

        client = app.test_client()

        response = client.get(
            "/"
        )

        self.assertNotIn(
            (
                "application_tab_lifecycle.js"
            ),
            response.get_data(
                as_text=True
            ),
        )

    def test_html_response_is_modified_when_lifecycle_service_exists(
        self
    ):
        app = Flask(
            __name__
        )

        app.config.update(
            SECRET_KEY=(
                "tab-client-test"
            ),
        )

        app.jinja_env.globals[
            "csrf_token"
        ] = lambda: (
            "test-csrf-token"
        )

        app.extensions[
            (
                "league_mastery_tracker_"
                "tab_lifecycle_service"
            )
        ] = object()

        self.service.init_app(
            app
        )

        @app.get("/")
        def home():
            return (
                "<html><body>Home</body></html>"
            )

        client = app.test_client()

        response = client.get(
            "/"
        )

        response_html = (
            response.get_data(
                as_text=True
            )
        )

        self.assertIn(
            (
                'src="/static/'
                'application_tab_lifecycle.js"'
            ),
            response_html,
        )

        self.assertIn(
            (
                'data-csrf-token="'
                'test-csrf-token"'
            ),
            response_html,
        )

    def test_repeated_initialization_is_safe(
        self
    ):
        app = Flask(
            __name__
        )

        self.service.init_app(
            app
        )

        self.service.init_app(
            app
        )

        self.assertTrue(
            app.extensions[
                self.service
                .FLASK_EXTENSION_KEY
            ]
        )


if __name__ == "__main__":
    unittest.main()