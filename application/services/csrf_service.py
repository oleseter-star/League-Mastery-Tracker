import secrets

from flask import request, session


class CsrfValidationError(ValueError):
    """
    Raised when a state-changing request does not contain a valid
    CSRF token.
    """


class CsrfService:
    """
    Creates and validates session-bound CSRF tokens.

    The Flask session is signed by the persistent local SECRET_KEY.
    """

    SESSION_KEY = "_csrf_token"
    FORM_FIELD_NAME = "_csrf_token"
    HEADER_NAME = "X-CSRF-Token"

    TOKEN_BYTES = 32
    MAX_TOKEN_LENGTH = 256

    PROTECTED_METHODS = {
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    }

    @classmethod
    def init_app(cls, app):
        """
        Register CSRF validation with one Flask application.

        Calling this method more than once for the same application
        has no additional effect.
        """

        app.extensions.setdefault(
            "league_mastery_tracker",
            {},
        )

        extension_state = app.extensions[
            "league_mastery_tracker"
        ]

        if extension_state.get(
            "csrf_initialized"
        ):
            return

        app.config.setdefault(
            "CSRF_ENABLED",
            True,
        )

        app.jinja_env.globals[
            "csrf_token"
        ] = cls.get_or_create_token

        @app.before_request
        def validate_csrf_request():
            if not app.config.get(
                "CSRF_ENABLED",
                True,
            ):
                return None

            if request.method not in cls.PROTECTED_METHODS:
                return None

            cls.validate_request()

            return None

        @app.errorhandler(CsrfValidationError)
        def handle_csrf_error(_error):
            return (
                "Bad Request: invalid or missing CSRF token.",
                400,
                {
                    "Content-Type": (
                        "text/plain; charset=utf-8"
                    ),
                },
            )

        extension_state[
            "csrf_initialized"
        ] = True

    @classmethod
    def get_or_create_token(cls):
        """
        Return the current session's CSRF token.

        A cryptographically random token is generated when the
        session does not already contain a valid token.
        """

        existing_token = cls._normalize_token(
            session.get(cls.SESSION_KEY)
        )

        if existing_token:
            return existing_token

        token = secrets.token_urlsafe(
            cls.TOKEN_BYTES
        )

        session[cls.SESSION_KEY] = token

        return token

    @classmethod
    def rotate_token(cls):
        """
        Replace the current session's CSRF token.
        """

        token = secrets.token_urlsafe(
            cls.TOKEN_BYTES
        )

        session[cls.SESSION_KEY] = token

        return token

    @classmethod
    def validate_request(cls):
        """
        Validate the CSRF token supplied with the current request.

        HTML forms use the hidden _csrf_token field. Future JSON or
        JavaScript requests may use the X-CSRF-Token header.
        """

        provided_token = cls._normalize_token(
            request.form.get(
                cls.FORM_FIELD_NAME
            )
        )

        if not provided_token:
            provided_token = cls._normalize_token(
                request.headers.get(
                    cls.HEADER_NAME
                )
            )

        cls.validate_token(
            provided_token
        )

    @classmethod
    def validate_token(cls, provided_token):
        """
        Validate one token against the token stored in the session.
        """

        normalized_provided_token = (
            cls._normalize_token(
                provided_token
            )
        )

        expected_token = cls._normalize_token(
            session.get(cls.SESSION_KEY)
        )

        if not normalized_provided_token:
            raise CsrfValidationError(
                "CSRF token is missing."
            )

        if not expected_token:
            raise CsrfValidationError(
                "CSRF session token is missing."
            )

        if not secrets.compare_digest(
            normalized_provided_token,
            expected_token,
        ):
            raise CsrfValidationError(
                "CSRF token is invalid."
            )

    @classmethod
    def _normalize_token(cls, token):
        """
        Normalize an optional CSRF token.
        """

        if token is None:
            return None

        normalized_token = str(
            token
        ).strip()

        if not normalized_token:
            return None

        if len(normalized_token) > cls.MAX_TOKEN_LENGTH:
            return None

        return normalized_token