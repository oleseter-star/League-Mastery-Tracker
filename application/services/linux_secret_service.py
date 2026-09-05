import os
import sys


class LinuxSecretServiceStorageError(OSError):
    """
    Raised when Secret Service storage cannot be used safely.
    """


class LinuxSecretService:
    """
    Store the Riot API key in the unlocked default collection.

    The SecretStorage dependency is imported only while an operation
    is requested so importing the application never opens D-Bus.
    """

    ITEM_LABEL = "League Mastery Tracker Riot API key"

    ITEM_ATTRIBUTES = {
        "application": "LeagueMasteryTracker",
        "secret": "RiotApiKey",
    }

    DIAGNOSTIC_ENVIRONMENT_VARIABLE = (
        "LEAGUE_MASTERY_TRACKER_SECRET_SERVICE_DIAGNOSTICS"
    )

    DIAGNOSTIC_PREFIX = "Linux Secret Service diagnostic:"

    DIAGNOSTIC_MAXIMUM_LENGTH = 256

    @classmethod
    def is_available(cls):
        cls._get_default_collection()
        return True

    @classmethod
    def read_api_key(cls):
        diagnostic_phase = {"name": "dbus-init"}
        collection = cls._get_default_collection(
            read_diagnostic_phase=diagnostic_phase,
        )

        try:
            diagnostic_phase["name"] = "search-items"
            items = collection.search_items(
                cls.ITEM_ATTRIBUTES
            )

            if not items:
                return None

            diagnostic_phase["name"] = "get-secret"
            secret = items[0].get_secret()

            if not isinstance(secret, bytes) or not secret:
                raise ValueError(
                    "Secret Service returned invalid data."
                )

            diagnostic_phase["name"] = "decode-secret"
            return secret.decode("utf-8")

        except (KeyboardInterrupt, SystemExit, AssertionError):
            raise

        except Exception as error:
            cls._emit_read_diagnostic(
                diagnostic_phase["name"],
                error,
            )
            raise LinuxSecretServiceStorageError(
                "The stored Riot API key could not be read safely."
            ) from error

    @classmethod
    def save_api_key(cls, api_key):
        collection = cls._get_default_collection()

        try:
            collection.create_item(
                cls.ITEM_LABEL,
                cls.ITEM_ATTRIBUTES,
                api_key.encode("utf-8"),
                replace=True,
            )

        except (KeyboardInterrupt, SystemExit, AssertionError):
            raise

        except Exception as error:
            raise LinuxSecretServiceStorageError(
                "The Riot API key could not be saved safely."
            ) from error

    @classmethod
    def delete_api_key(cls):
        collection = cls._get_default_collection()

        try:
            items = collection.search_items(
                cls.ITEM_ATTRIBUTES
            )

            for item in items:
                item.delete()

        except (KeyboardInterrupt, SystemExit, AssertionError):
            raise

        except Exception as error:
            raise LinuxSecretServiceStorageError(
                "The stored Riot API key could not be removed safely."
            ) from error

        return bool(items)

    @classmethod
    def _get_default_collection(cls, read_diagnostic_phase=None):
        try:
            import secretstorage

            cls._set_read_diagnostic_phase(
                read_diagnostic_phase,
                "dbus-init",
            )
            connection = secretstorage.dbus_init()
            cls._set_read_diagnostic_phase(
                read_diagnostic_phase,
                "default-collection",
            )
            collection = secretstorage.get_default_collection(
                connection
            )

            cls._set_read_diagnostic_phase(
                read_diagnostic_phase,
                "item-lock-check",
            )
            if collection is None or collection.is_locked():
                raise LinuxSecretServiceStorageError(
                    "Persistent Riot API key storage is unavailable."
                )

            return collection

        except LinuxSecretServiceStorageError:
            raise

        except (KeyboardInterrupt, SystemExit, AssertionError):
            raise

        except Exception as error:
            if read_diagnostic_phase is not None:
                cls._emit_read_diagnostic(
                    read_diagnostic_phase["name"],
                    error,
                )
            raise LinuxSecretServiceStorageError(
                "Persistent Riot API key storage is unavailable."
            ) from error

    @staticmethod
    def _set_read_diagnostic_phase(
        read_diagnostic_phase,
        phase,
    ):
        if read_diagnostic_phase is not None:
            read_diagnostic_phase["name"] = phase

    @classmethod
    def _emit_read_diagnostic(cls, phase, error):
        if os.environ.get(
            cls.DIAGNOSTIC_ENVIRONMENT_VARIABLE
        ) != "1":
            return

        try:
            exception_class = type(error)
            exception_name = ".".join(
                (
                    exception_class.__module__,
                    exception_class.__qualname__,
                )
            )
            safe_exception_name = "".join(
                character
                if (
                    character.isascii()
                    and (
                        character.isalnum()
                        or character in "_."
                    )
                )
                else "_"
                for character in exception_name
            )
            line = (
                f"{cls.DIAGNOSTIC_PREFIX} "
                f"operation=read phase={phase} "
                f"exception={safe_exception_name}"
            )
            sys.stderr.write(
                line[: cls.DIAGNOSTIC_MAXIMUM_LENGTH - 1]
                + "\n"
            )
        except Exception:
            pass
