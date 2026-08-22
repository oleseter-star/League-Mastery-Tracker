import unittest

from flask import Flask

from application.services.csrf_service import (
    CsrfService,
)


class CsrfIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY="csrf-integration-test-secret",
            CSRF_ENABLED=True,
        )

        CsrfService.init_app(
            self.app
        )

        @self.app.get("/token")
        def get_token():
            return CsrfService.get_or_create_token()

        @self.app.post("/submit")
        def submit():
            return "Submitted"

        self.client = self.app.test_client()

    def _get_token(self):
        response = self.client.get(
            "/token"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        return response.get_data(
            as_text=True
        )

    def test_post_without_token_is_rejected(self):
        self._get_token()

        response = self.client.post(
            "/submit"
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertEqual(
            response.get_data(
                as_text=True
            ),
            "Bad Request: invalid or missing CSRF token.",
        )

    def test_post_with_invalid_token_is_rejected(self):
        self._get_token()

        response = self.client.post(
            "/submit",
            data={
                "_csrf_token": "incorrect-token",
            },
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    def test_post_with_valid_form_token_is_accepted(self):
        token = self._get_token()

        response = self.client.post(
            "/submit",
            data={
                "_csrf_token": token,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.get_data(
                as_text=True
            ),
            "Submitted",
        )

    def test_post_with_valid_header_token_is_accepted(self):
        token = self._get_token()

        response = self.client.post(
            "/submit",
            headers={
                "X-CSRF-Token": token,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_disabled_csrf_allows_post_without_token(self):
        self.app.config[
            "CSRF_ENABLED"
        ] = False

        response = self.client.post(
            "/submit"
        )

        self.assertEqual(
            response.status_code,
            200,
        )


if __name__ == "__main__":
    unittest.main()