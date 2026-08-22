import os
from pathlib import Path

from flask import current_app

from application.services.windows_dpapi_service import (
    WindowsDpapiService,
)


class RiotApiKeyStorageError(OSError):
    """
    Raised when the locally stored Riot API key cannot be safely
    read, encrypted, decrypted, verified, or migrated.
    """


class RiotApiKeyService:
    """
    Manages the locally configured Riot API key.

    Locally saved keys are protected with Windows DPAPI and tied to
    the current Windows user account.

    Priority:
    1. Locally encrypted key
    2. Legacy local plaintext key, migrated automatically
    3. Current RIOT_API_KEY environment variable
    4. Key loaded into Flask configuration at startup
    """

    ENCRYPTED_FILE_NAME = "riot_api_key.dpapi"
    LEGACY_FILE_NAME = "riot_api_key.txt"

    ENCRYPTED_FILE_HEADER = (
        b"LMT-RIOT-API-KEY\x00\x01"
    )

    @classmethod
    def get_api_key(cls):
        """
        Return the active Riot API key.

        A legacy plaintext key is migrated automatically before it
        is returned.
        """

        local_key = cls._get_local_key_with_migration()

        if local_key:
            return local_key

        environment_key = cls._normalize_optional_key(
            os.environ.get("RIOT_API_KEY")
        )

        if environment_key:
            return environment_key

        return cls._normalize_optional_key(
            current_app.config.get("RIOT_API_KEY")
        )

    @classmethod
    def get_status(cls):
        """
        Return non-sensitive information about the active key.

        Local storage errors are returned as display-safe status
        information instead of crashing the Settings page.
        """

        try:
            local_key = (
                cls._get_local_key_with_migration()
            )

        except RiotApiKeyStorageError as error:
            return {
                "configured": False,
                "source": "local",
                "masked_key": None,
                "error": str(error),
            }

        if local_key:
            return {
                "configured": True,
                "source": "local",
                "masked_key": cls._mask_key(
                    local_key
                ),
                "error": None,
            }

        environment_key = cls._normalize_optional_key(
            os.environ.get("RIOT_API_KEY")
        )

        if environment_key:
            return {
                "configured": True,
                "source": "environment",
                "masked_key": cls._mask_key(
                    environment_key
                ),
                "error": None,
            }

        configured_key = cls._normalize_optional_key(
            current_app.config.get("RIOT_API_KEY")
        )

        if configured_key:
            return {
                "configured": True,
                "source": "environment",
                "masked_key": cls._mask_key(
                    configured_key
                ),
                "error": None,
            }

        return {
            "configured": False,
            "source": None,
            "masked_key": None,
            "error": None,
        }

    @classmethod
    def save_api_key(cls, api_key):
        """
        Validate, encrypt, verify, and atomically save a Riot API key.

        A legacy plaintext file is removed only after the encrypted
        file has been written and successfully decrypted again.
        """

        normalized_key = cls._normalize_required_key(
            api_key
        )

        encrypted_file = (
            cls._get_encrypted_key_file()
        )

        legacy_file = (
            cls._get_legacy_key_file()
        )

        encrypted_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_file = encrypted_file.with_suffix(
            ".dpapi.tmp"
        )

        try:
            protected_data = (
                WindowsDpapiService.protect(
                    normalized_key.encode(
                        "utf-8"
                    )
                )
            )

            encrypted_payload = (
                cls.ENCRYPTED_FILE_HEADER
                + protected_data
            )

            temporary_file.write_bytes(
                encrypted_payload
            )

            cls._restrict_file_permissions(
                temporary_file
            )

            verified_key = (
                cls._decode_encrypted_payload(
                    temporary_file.read_bytes()
                )
            )

            if verified_key != normalized_key:
                raise RiotApiKeyStorageError(
                    "The encrypted Riot API key could not "
                    "be verified."
                )

            temporary_file.replace(
                encrypted_file
            )

            cls._restrict_file_permissions(
                encrypted_file
            )

            if legacy_file.exists():
                legacy_file.unlink()

        except RiotApiKeyStorageError:
            if temporary_file.exists():
                temporary_file.unlink()

            raise

        except (
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            if temporary_file.exists():
                temporary_file.unlink()

            raise RiotApiKeyStorageError(
                "The Riot API key could not be encrypted "
                "and saved safely."
            ) from error

        return {
            "configured": True,
            "source": "local",
            "masked_key": cls._mask_key(
                normalized_key
            ),
            "error": None,
        }

    @classmethod
    def delete_local_api_key(cls):
        """
        Delete locally saved encrypted and legacy key files.

        An environment-variable key, if present, is not modified.
        """

        deleted = False

        for key_file in (
            cls._get_encrypted_key_file(),
            cls._get_legacy_key_file(),
        ):
            if key_file.exists():
                key_file.unlink()
                deleted = True

        return deleted

    @classmethod
    def _get_local_key_with_migration(cls):
        """
        Return the local key and migrate legacy plaintext storage.

        An encrypted file takes precedence. A corrupted encrypted
        file is reported instead of silently falling back to a less
        secure source.
        """

        encrypted_file = (
            cls._get_encrypted_key_file()
        )

        if encrypted_file.exists():
            return cls._read_encrypted_key()

        legacy_key = cls._read_legacy_key()

        if not legacy_key:
            return None

        try:
            cls.save_api_key(
                legacy_key
            )

        except (
            OSError,
            ValueError,
        ) as error:
            raise RiotApiKeyStorageError(
                "The existing Riot API key could not be "
                "migrated to encrypted storage."
            ) from error

        return legacy_key

    @classmethod
    def _read_encrypted_key(cls):
        """
        Read, decrypt, and validate the locally encrypted key.
        """

        encrypted_file = (
            cls._get_encrypted_key_file()
        )

        try:
            encrypted_payload = (
                encrypted_file.read_bytes()
            )

            return cls._decode_encrypted_payload(
                encrypted_payload
            )

        except RiotApiKeyStorageError:
            raise

        except (
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            raise RiotApiKeyStorageError(
                "The locally stored Riot API key could not "
                "be read or decrypted. Save a new key in "
                "Settings."
            ) from error

    @classmethod
    def _decode_encrypted_payload(
        cls,
        encrypted_payload,
    ):
        """
        Validate the file format and decrypt its key value.
        """

        if not isinstance(
            encrypted_payload,
            bytes,
        ):
            raise RiotApiKeyStorageError(
                "The encrypted Riot API key file is invalid."
            )

        if not encrypted_payload.startswith(
            cls.ENCRYPTED_FILE_HEADER
        ):
            raise RiotApiKeyStorageError(
                "The encrypted Riot API key uses an "
                "unsupported file format."
            )

        protected_data = encrypted_payload[
            len(cls.ENCRYPTED_FILE_HEADER):
        ]

        if not protected_data:
            raise RiotApiKeyStorageError(
                "The encrypted Riot API key file is empty."
            )

        try:
            plaintext = (
                WindowsDpapiService.unprotect(
                    protected_data
                )
            )

            decoded_key = plaintext.decode(
                "utf-8"
            )

        except (
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            raise RiotApiKeyStorageError(
                "The locally stored Riot API key could not "
                "be decrypted. It may belong to another "
                "Windows user or may be damaged."
            ) from error

        return cls._normalize_required_key(
            decoded_key
        )

    @classmethod
    def _read_legacy_key(cls):
        """
        Read and validate the legacy plaintext key, if present.
        """

        legacy_file = (
            cls._get_legacy_key_file()
        )

        if not legacy_file.exists():
            return None

        try:
            key_value = legacy_file.read_text(
                encoding="utf-8"
            )

        except (
            OSError,
            UnicodeError,
        ) as error:
            raise RiotApiKeyStorageError(
                "The existing plaintext Riot API key "
                "could not be read for migration."
            ) from error

        normalized_key = cls._normalize_optional_key(
            key_value
        )

        if not normalized_key:
            return None

        try:
            return cls._normalize_required_key(
                normalized_key
            )

        except ValueError as error:
            raise RiotApiKeyStorageError(
                "The existing plaintext Riot API key is "
                "invalid and could not be migrated."
            ) from error

    @classmethod
    def _get_encrypted_key_file(cls):
        return (
            cls._get_configuration_directory()
            / cls.ENCRYPTED_FILE_NAME
        )

    @classmethod
    def _get_legacy_key_file(cls):
        return (
            cls._get_configuration_directory()
            / cls.LEGACY_FILE_NAME
        )

    @staticmethod
    def _get_configuration_directory():
        return Path(
            current_app.config["CONFIG_DIR"]
        )

    @staticmethod
    def _normalize_required_key(api_key):
        """
        Validate a required Riot API key.
        """

        normalized_key = (
            RiotApiKeyService._normalize_optional_key(
                api_key
            )
        )

        if not normalized_key:
            raise ValueError(
                "Riot API key is required."
            )

        if len(normalized_key) < 20:
            raise ValueError(
                "The Riot API key appears to be too short."
            )

        if len(normalized_key) > 512:
            raise ValueError(
                "The Riot API key is too long."
            )

        if any(
            character.isspace()
            for character in normalized_key
        ):
            raise ValueError(
                "The Riot API key cannot contain whitespace."
            )

        return normalized_key

    @staticmethod
    def _normalize_optional_key(api_key):
        """
        Normalize an optional Riot API key.
        """

        if api_key is None:
            return None

        normalized_key = str(
            api_key
        ).strip()

        return normalized_key or None

    @staticmethod
    def _mask_key(api_key):
        """
        Return a safe representation of a configured key.
        """

        if len(api_key) <= 4:
            return "••••"

        return (
            "••••••••"
            + api_key[-4:]
        )

    @staticmethod
    def _restrict_file_permissions(file_path):
        """
        Apply restrictive permissions where supported.

        DPAPI remains the primary protection on Windows.
        """

        try:
            os.chmod(
                file_path,
                0o600,
            )

        except OSError:
            pass