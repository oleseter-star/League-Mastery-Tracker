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

    @classmethod
    def is_available(cls):
        cls._get_default_collection()
        return True

    @classmethod
    def read_api_key(cls):
        collection = cls._get_default_collection()

        try:
            items = collection.search_items(
                cls.ITEM_ATTRIBUTES
            )

            if not items:
                return None

            secret = items[0].get_secret()

            if not isinstance(secret, bytes) or not secret:
                raise ValueError(
                    "Secret Service returned invalid data."
                )

            return secret.decode("utf-8")

        except (KeyboardInterrupt, SystemExit, AssertionError):
            raise

        except Exception as error:
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
    def _get_default_collection(cls):
        try:
            import secretstorage

            connection = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(
                connection
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
            raise LinuxSecretServiceStorageError(
                "Persistent Riot API key storage is unavailable."
            ) from error