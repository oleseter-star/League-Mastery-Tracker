import unittest

from flask import Flask, session

from application.services.csrf_service import (
    CsrfService,
    CsrfValidationError,
)


class CsrfServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SECRET_KEY="csrf-service-test-secret",
        )

    def test_token_is_created_and_reused_in_same_session(self):
        with self.app.test_request_context("/"):
            first_token = (
                CsrfService.get_or_create_token()
            )

            second_token = (
                CsrfService.get_or_create_token()
            )

            self.assertEqual(
                second_token,
                first_token,
            )

            self.assertEqual(
                session[CsrfService.SESSION_KEY],
                first_token,
            )

            self.assertGreaterEqual(
                len(first_token),
                40,
            )

    def test_separate_sessions_receive_different_tokens(self):
        with self.app.test_request_context("/"):
            first_token = (
                CsrfService.get_or_create_token()
            )

        with self.app.test_request_context("/"):
            second_token = (
                CsrfService.get_or_create_token()
            )

        self.assertNotEqual(
            second_token,
            first_token,
        )

    def test_valid_form_token_is_accepted(self):
        token = "valid-form-token"

        with self.app.test_request_context(
            "/submit",
            method="POST",
            data={
                "_csrf_token": token,
            },
        ):
            session[
                CsrfService.SESSION_KEY
            ] = token

            CsrfService.validate_request()

    def test_valid_header_token_is_accepted(self):
        token = "valid-header-token"

        with self.app.test_request_context(
            "/submit",
            method="POST",
            headers={
                "X-CSRF-Token": token,
            },
        ):
            session[
                CsrfService.SESSION_KEY
            ] = token

            CsrfService.validate_request()

    def test_missing_or_invalid_tokens_are_rejected(self):
        with self.app.test_request_context(
            "/submit",
            method="POST",
        ):
            session[
                CsrfService.SESSION_KEY
            ] = "expected-token"

            with self.assertRaises(
                CsrfValidationError
            ):
                CsrfService.validate_request()

        with self.app.test_request_context(
            "/submit",
            method="POST",
            data={
                "_csrf_token": "wrong-token",
            },
        ):
            session[
                CsrfService.SESSION_KEY
            ] = "expected-token"

            with self.assertRaises(
                CsrfValidationError
            ):
                CsrfService.validate_request()

    def test_rotating_token_invalidates_previous_token(self):
        with self.app.test_request_context("/"):
            previous_token = (
                CsrfService.get_or_create_token()
            )

            replacement_token = (
                CsrfService.rotate_token()
            )

            self.assertNotEqual(
                replacement_token,
                previous_token,
            )

            with self.assertRaises(
                CsrfValidationError
            ):
                CsrfService.validate_token(
                    previous_token
                )

            CsrfService.validate_token(
                replacement_token
            )


if __name__ == "__main__":
    unittest.main()