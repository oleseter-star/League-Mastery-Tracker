import sqlite3
from pathlib import Path

from flask import current_app


class DatabaseVersionError(RuntimeError):
    """
    Raised when a database version is invalid, unsupported, or
    newer than the application understands.
    """


class DatabaseMigrationService:
    """
    Maintains the internal database schema version.

    Existing pre-versioning databases are treated as schema
    version 1. Completely new databases begin at the application's
    current schema version.
    """

    CURRENT_DATABASE_SCHEMA_VERSION = 1
    CURRENT_EXPORT_FORMAT_VERSION = 1

    METADATA_TABLE = "application_metadata"
    SCHEMA_VERSION_KEY = "database_schema_version"

    MIGRATIONS = {}

    @classmethod
    def initialize_or_migrate(cls):
        """
        Initialize database metadata or apply required migrations.

        The complete initialization or migration sequence runs
        inside one explicit SQLite transaction. This includes DDL
        statements such as CREATE TABLE.

        If any migration fails, all schema changes, data changes,
        and metadata changes are rolled back.
        """

        database_file = cls._get_database_file()

        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        database_existed = database_file.exists()
        migrated_versions = []

        connection = sqlite3.connect(
            str(database_file),
            timeout=30.0,
        )

        try:
            connection.execute(
                "PRAGMA foreign_keys = ON"
            )

            connection.execute(
                "BEGIN IMMEDIATE"
            )

            try:
                cls._create_metadata_table(
                    connection
                )

                stored_version = (
                    cls._read_schema_version(
                        connection
                    )
                )

                initialized = False
                baselined_existing_database = False

                if stored_version is None:
                    has_application_tables = (
                        cls._database_has_application_tables(
                            connection
                        )
                    )

                    initialized = True

                    if has_application_tables:
                        stored_version = 1

                        baselined_existing_database = (
                            database_existed
                        )

                    else:
                        stored_version = (
                            cls.CURRENT_DATABASE_SCHEMA_VERSION
                        )

                    cls._write_schema_version(
                        connection,
                        stored_version,
                    )

                if (
                    stored_version
                    > cls.CURRENT_DATABASE_SCHEMA_VERSION
                ):
                    raise DatabaseVersionError(
                        "The database was created by a newer "
                        "version of League Mastery Tracker. "
                        f"Database schema version: {stored_version}. "
                        "Supported schema version: "
                        f"{cls.CURRENT_DATABASE_SCHEMA_VERSION}."
                    )

                current_version = stored_version

                while (
                    current_version
                    < cls.CURRENT_DATABASE_SCHEMA_VERSION
                ):
                    target_version = (
                        current_version + 1
                    )

                    migration = cls.MIGRATIONS.get(
                        target_version
                    )

                    if migration is None:
                        raise DatabaseVersionError(
                            "No database migration is available "
                            f"from schema version {current_version} "
                            f"to version {target_version}."
                        )

                    migration(
                        connection
                    )

                    cls._write_schema_version(
                        connection,
                        target_version,
                    )

                    migrated_versions.append(
                        target_version
                    )

                    current_version = target_version

            except Exception:
                connection.rollback()
                raise

            else:
                connection.commit()

            return {
                "database_file": database_file,
                "schema_version": current_version,
                "initialized": initialized,
                "baselined_existing_database": (
                    baselined_existing_database
                ),
                "migrated_versions": migrated_versions,
            }

        except DatabaseVersionError:
            raise

        except sqlite3.Error as error:
            raise DatabaseVersionError(
                "The database schema version could not be "
                "initialized or migrated."
            ) from error

        except Exception as error:
            raise DatabaseVersionError(
                "A database migration failed. All migration "
                "changes were rolled back."
            ) from error

        finally:
            connection.close()

    @classmethod
    def get_database_schema_version(cls):
        """
        Read the stored schema version without modifying the
        database.
        """

        database_file = cls._get_database_file()

        if not database_file.exists():
            return None

        connection = sqlite3.connect(
            str(database_file),
            timeout=30.0,
        )

        try:
            if not cls._metadata_table_exists(
                connection
            ):
                return None

            return cls._read_schema_version(
                connection
            )

        except DatabaseVersionError:
            raise

        except sqlite3.Error as error:
            raise DatabaseVersionError(
                "The database schema version could not be read."
            ) from error

        finally:
            connection.close()

    @classmethod
    def get_export_format_version(cls):
        """
        Return the JSON export format version written by this app.
        """

        return cls.CURRENT_EXPORT_FORMAT_VERSION

    @classmethod
    def _create_metadata_table(
        cls,
        connection,
    ):
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {cls.METADATA_TABLE} (
                key TEXT PRIMARY KEY NOT NULL,
                value TEXT NOT NULL
            )
            """
        )

    @classmethod
    def _read_schema_version(
        cls,
        connection,
    ):
        row = connection.execute(
            f"""
            SELECT value
            FROM {cls.METADATA_TABLE}
            WHERE key = ?
            """,
            (
                cls.SCHEMA_VERSION_KEY,
            ),
        ).fetchone()

        if row is None:
            return None

        raw_version = row[0]

        try:
            version = int(
                raw_version
            )

        except (TypeError, ValueError) as error:
            raise DatabaseVersionError(
                "The stored database schema version is invalid."
            ) from error

        if version <= 0:
            raise DatabaseVersionError(
                "The stored database schema version must be "
                "greater than zero."
            )

        return version

    @classmethod
    def _write_schema_version(
        cls,
        connection,
        version,
    ):
        connection.execute(
            f"""
            INSERT INTO {cls.METADATA_TABLE} (
                key,
                value
            )
            VALUES (
                ?,
                ?
            )
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
            """,
            (
                cls.SCHEMA_VERSION_KEY,
                str(version),
            ),
        )

    @classmethod
    def _database_has_application_tables(
        cls,
        connection,
    ):
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

        table_names = {
            row[0]
            for row in rows
        }

        table_names.discard(
            cls.METADATA_TABLE
        )

        return bool(
            table_names
        )

    @classmethod
    def _metadata_table_exists(
        cls,
        connection,
    ):
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (
                cls.METADATA_TABLE,
            ),
        ).fetchone()

        return row is not None

    @staticmethod
    def _get_database_file():
        return Path(
            current_app.config["DATABASE_FILE"]
        )