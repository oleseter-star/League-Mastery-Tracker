import os
import secrets
from pathlib import Path

from flask import current_app


class LocalSecretKeyError(OSError):
    """
    Raised when the local Flask secret key cannot be created,
    validated, or read safely.
    """


class LocalSecretKeyService:
    """
    Creates and reads the persistent local Flask secret key.

    The key signs session data and will later protect CSRF tokens.
    It is stored separately from both the database and Riot API key.
    """

    FILE_NAME = "flask_secret_key.bin"
    KEY_LENGTH_BYTES = 64

    @classmethod
    def get_or_create_secret_key(cls):
        """
        Return the existing secret key or create it once.

        Exclusive file creation prevents an existing key from being
        overwritten if two application processes start concurrently.
        """

        key_file = cls._get_key_file()

        if key_file.exists():
            return cls._read_secret_key(
                key_file
            )

        key_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        secret_key = secrets.token_bytes(
            cls.KEY_LENGTH_BYTES
        )

        file_descriptor = None
        created_file = False

        try:
            file_descriptor = os.open(
                str(key_file),
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                ),
                0o600,
            )

            created_file = True

            with os.fdopen(
                file_descriptor,
                "wb",
            ) as file:
                file_descriptor = None

                file.write(
                    secret_key
                )

                file.flush()
                os.fsync(
                    file.fileno()
                )

            cls._restrict_file_permissions(
                key_file
            )

        except FileExistsError:
            return cls._read_secret_key(
                key_file
            )

        except OSError as error:
            if file_descriptor is not None:
                os.close(
                    file_descriptor
                )

            if created_file and key_file.exists():
                try:
                    key_file.unlink()
                except OSError:
                    pass

            raise LocalSecretKeyError(
                "The local Flask secret key could not be "
                "created safely."
            ) from error

        return cls._validate_secret_key(
            secret_key
        )

    @classmethod
    def _read_secret_key(
        cls,
        key_file,
    ):
        """
        Read and validate the existing local secret key.
        """

        try:
            secret_key = key_file.read_bytes()

        except OSError as error:
            raise LocalSecretKeyError(
                "The local Flask secret key could not be read."
            ) from error

        return cls._validate_secret_key(
            secret_key
        )

    @classmethod
    def _validate_secret_key(
        cls,
        secret_key,
    ):
        """
        Validate the persistent binary secret-key format.
        """

        if not isinstance(
            secret_key,
            bytes,
        ):
            raise LocalSecretKeyError(
                "The local Flask secret key has an invalid format."
            )

        if len(secret_key) != cls.KEY_LENGTH_BYTES:
            raise LocalSecretKeyError(
                "The local Flask secret key has an invalid length. "
                "Delete flask_secret_key.bin to generate a new key."
            )

        return secret_key

    @classmethod
    def _get_key_file(cls):
        configuration_directory = Path(
            current_app.config["CONFIG_DIR"]
        )

        return (
            configuration_directory
            / cls.FILE_NAME
        )

    @staticmethod
    def _restrict_file_permissions(
        file_path,
    ):
        """
        Apply restrictive permissions where supported.
        """

        try:
            os.chmod(
                file_path,
                0o600,
            )

        except OSError:
            pass