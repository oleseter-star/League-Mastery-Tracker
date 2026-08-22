import hashlib
import json
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from application.services.backup_service import BackupService
from application.services.database_migration_service import (
    DatabaseMigrationService,
)


class DatabaseRestoreError(RuntimeError):
    """
    Raised when a database backup cannot be safely staged,
    validated, or restored.
    """


class DatabaseRestoreService:
    """
    Validates, stages, and restores internal database backups.

    Database replacement must only run before SQLAlchemy or another
    component has opened the live database.
    """

    BACKUP_FILE_PATTERN = re.compile(
        r"^league_mastery_tracker_"
        r"\d{8}T\d{6}(?:\d{6})?Z"
        r"\.db$"
    )

    STAGED_FILE_PATTERN = re.compile(
        r"^pending_restore_[0-9a-f]{32}\.db$"
    )

    SHA256_PATTERN = re.compile(
        r"^[0-9a-f]{64}$"
    )

    RESTORE_DIRECTORY_NAME = "database_restore"
    MARKER_FILE_NAME = "pending_restore.json"
    MARKER_FORMAT_VERSION = 1

    @classmethod
    def get_restore_candidates(cls):
        """
        Return internal backups with validation information.
        """

        candidates = []

        for backup_file in BackupService.get_backup_files():
            try:
                validation = cls.validate_backup(
                    backup_file.name
                )

            except DatabaseRestoreError as error:
                try:
                    file_stat = backup_file.stat()

                except OSError:
                    file_size = None
                    modified_at = None

                else:
                    file_size = file_stat.st_size
                    modified_at = datetime.fromtimestamp(
                        file_stat.st_mtime
                    ).astimezone()

                candidates.append(
                    {
                        "file_name": backup_file.name,
                        "file_path": backup_file,
                        "size_bytes": file_size,
                        "modified_at": modified_at,
                        "valid": False,
                        "schema_version": None,
                        "unversioned": False,
                        "error": str(error),
                    }
                )

            else:
                candidates.append(
                    validation
                )

        return candidates

    @classmethod
    def validate_backup(
        cls,
        backup_file_name,
    ):
        """
        Validate one backup inside the internal backup directory.
        """

        backup_file = cls._resolve_backup_file(
            backup_file_name
        )

        validation = cls._validate_database_file(
            backup_file
        )

        return {
            "file_name": backup_file.name,
            "file_path": backup_file,
            **validation,
        }

    @classmethod
    def stage_restore(
        cls,
        backup_file_name,
    ):
        """
        Copy and stage one validated internal backup.

        The source backup is no longer required after staging.
        """

        source_validation = cls.validate_backup(
            backup_file_name
        )

        restore_directory = (
            cls._get_restore_directory()
        )

        restore_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        staged_file_name = (
            "pending_restore_"
            f"{secrets.token_hex(16)}"
            ".db"
        )

        staged_file = (
            restore_directory
            / staged_file_name
        )

        temporary_staged_file = (
            restore_directory
            / f"{staged_file_name}.tmp"
        )

        marker_file = cls._get_marker_file()
        temporary_marker_file = (
            restore_directory
            / f"{cls.MARKER_FILE_NAME}.tmp"
        )

        try:
            shutil.copy2(
                source_validation["file_path"],
                temporary_staged_file,
            )

            staged_validation = (
                cls._validate_database_file(
                    temporary_staged_file
                )
            )

            if (
                staged_validation["schema_version"]
                != source_validation["schema_version"]
            ):
                raise DatabaseRestoreError(
                    "The staged database schema version does "
                    "not match the selected backup."
                )

            staged_sha256 = cls._calculate_sha256(
                temporary_staged_file
            )

            temporary_staged_file.replace(
                staged_file
            )

            marker_data = {
                "format_version": (
                    cls.MARKER_FORMAT_VERSION
                ),
                "staged_file_name": staged_file_name,
                "source_backup_file_name": (
                    source_validation["file_name"]
                ),
                "sha256": staged_sha256,
                "schema_version": (
                    staged_validation["schema_version"]
                ),
                "requested_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }

            temporary_marker_file.write_text(
                json.dumps(
                    marker_data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            temporary_marker_file.replace(
                marker_file
            )

            cls._remove_unused_staged_files(
                keep_file=staged_file
            )

        except DatabaseRestoreError:
            cls._delete_if_exists(
                temporary_staged_file
            )

            cls._delete_if_exists(
                temporary_marker_file
            )

            if (
                staged_file.exists()
                and not marker_file.exists()
            ):
                cls._delete_if_exists(
                    staged_file
                )

            raise

        except (
            OSError,
            sqlite3.Error,
            ValueError,
        ) as error:
            cls._delete_if_exists(
                temporary_staged_file
            )

            cls._delete_if_exists(
                temporary_marker_file
            )

            if (
                staged_file.exists()
                and not marker_file.exists()
            ):
                cls._delete_if_exists(
                    staged_file
                )

            raise DatabaseRestoreError(
                "The selected database backup could not be "
                "staged safely."
            ) from error

        return cls.get_pending_restore()

    @classmethod
    def get_pending_restore(cls):
        """
        Return and verify the currently staged restore request.
        """

        marker_file = cls._get_marker_file()

        if not marker_file.exists():
            return None

        try:
            marker_data = json.loads(
                marker_file.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
        ) as error:
            raise DatabaseRestoreError(
                "The pending database restore marker is "
                "invalid or unreadable."
            ) from error

        if not isinstance(marker_data, dict):
            raise DatabaseRestoreError(
                "The pending database restore marker has an "
                "invalid format."
            )

        if (
            marker_data.get("format_version")
            != cls.MARKER_FORMAT_VERSION
        ):
            raise DatabaseRestoreError(
                "The pending database restore marker uses an "
                "unsupported format version."
            )

        staged_file = cls._resolve_staged_file(
            marker_data.get(
                "staged_file_name"
            )
        )

        expected_sha256 = str(
            marker_data.get("sha256") or ""
        ).strip()

        if not cls.SHA256_PATTERN.fullmatch(
            expected_sha256
        ):
            raise DatabaseRestoreError(
                "The pending database restore contains an "
                "invalid checksum."
            )

        source_backup_file_name = str(
            marker_data.get(
                "source_backup_file_name"
            )
            or ""
        ).strip()

        if not cls.BACKUP_FILE_PATTERN.fullmatch(
            source_backup_file_name
        ):
            raise DatabaseRestoreError(
                "The pending database restore contains an "
                "invalid source backup filename."
            )

        expected_schema_version = marker_data.get(
            "schema_version"
        )

        if (
            expected_schema_version is not None
            and not isinstance(
                expected_schema_version,
                int,
            )
        ):
            raise DatabaseRestoreError(
                "The pending database restore contains an "
                "invalid schema version."
            )

        requested_at_raw = str(
            marker_data.get("requested_at") or ""
        ).strip()

        try:
            requested_at = datetime.fromisoformat(
                requested_at_raw
            )

        except ValueError as error:
            raise DatabaseRestoreError(
                "The pending database restore contains an "
                "invalid request timestamp."
            ) from error

        validation = cls._validate_database_file(
            staged_file
        )

        actual_sha256 = cls._calculate_sha256(
            staged_file
        )

        if not secrets.compare_digest(
            actual_sha256,
            expected_sha256,
        ):
            raise DatabaseRestoreError(
                "The staged database backup has changed since "
                "it was selected."
            )

        if (
            validation["schema_version"]
            != expected_schema_version
        ):
            raise DatabaseRestoreError(
                "The staged database schema version does not "
                "match the restore marker."
            )

        return {
            "source_backup_file_name": (
                source_backup_file_name
            ),
            "staged_file_name": staged_file.name,
            "staged_file_path": staged_file,
            "sha256": actual_sha256,
            "schema_version": (
                validation["schema_version"]
            ),
            "unversioned": validation["unversioned"],
            "size_bytes": validation["size_bytes"],
            "modified_at": validation["modified_at"],
            "requested_at": requested_at,
        }

    @classmethod
    def cancel_pending_restore(cls):
        """
        Remove the current pending restore without changing the
        live database.
        """

        marker_file = cls._get_marker_file()

        if not marker_file.exists():
            return False

        staged_file = None

        try:
            marker_data = json.loads(
                marker_file.read_text(
                    encoding="utf-8"
                )
            )

            if isinstance(marker_data, dict):
                staged_file_name = marker_data.get(
                    "staged_file_name"
                )

                if staged_file_name:
                    try:
                        staged_file = (
                            cls._resolve_staged_file(
                                staged_file_name
                            )
                        )

                    except DatabaseRestoreError:
                        staged_file = None

        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            staged_file = None

        cls._delete_if_exists(
            marker_file
        )

        if staged_file is not None:
            cls._delete_if_exists(
                staged_file
            )

        cls._remove_unused_staged_files(
            keep_file=None
        )

        return True

    @classmethod
    def apply_pending_restore(cls):
        """
        Apply the staged restore to the live database.

        This must run before SQLAlchemy opens the live database.

        A new backup of the current database is mandatory whenever
        the current database exists.
        """

        pending_restore = cls.get_pending_restore()

        if pending_restore is None:
            return {
                "applied": False,
                "reason": "no_pending_restore",
                "safety_backup_file": None,
                "source_backup_file_name": None,
            }

        database_file = cls._get_database_file()

        database_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_database_file = (
            database_file.parent
            / f"{database_file.name}.restore.tmp"
        )

        safety_backup_file = None

        try:
            if database_file.exists():
                safety_backup_result = (
                    BackupService.create_backup()
                )

                safety_backup_file = (
                    safety_backup_result[
                        "backup_file"
                    ]
                )

                cls.validate_backup(
                    safety_backup_file.name
                )

            shutil.copy2(
                pending_restore[
                    "staged_file_path"
                ],
                temporary_database_file,
            )

            temporary_validation = (
                cls._validate_database_file(
                    temporary_database_file
                )
            )

            temporary_sha256 = (
                cls._calculate_sha256(
                    temporary_database_file
                )
            )

            if not secrets.compare_digest(
                temporary_sha256,
                pending_restore["sha256"],
            ):
                raise DatabaseRestoreError(
                    "The temporary restore database does not "
                    "match the staged backup."
                )

            if (
                temporary_validation["schema_version"]
                != pending_restore["schema_version"]
            ):
                raise DatabaseRestoreError(
                    "The temporary restore database schema "
                    "version does not match the staged backup."
                )

            temporary_database_file.replace(
                database_file
            )

        except DatabaseRestoreError:
            cls._delete_if_exists(
                temporary_database_file
            )

            raise

        except (
            OSError,
            sqlite3.Error,
            ValueError,
        ) as error:
            cls._delete_if_exists(
                temporary_database_file
            )

            raise DatabaseRestoreError(
                "The pending database restore could not be "
                "applied safely. The current database was not "
                "replaced."
            ) from error

        cls._delete_if_exists(
            cls._get_marker_file()
        )

        cls._delete_if_exists(
            pending_restore[
                "staged_file_path"
            ]
        )

        cls._remove_unused_staged_files(
            keep_file=None
        )

        return {
            "applied": True,
            "reason": "restore_applied",
            "safety_backup_file": (
                safety_backup_file
            ),
            "source_backup_file_name": (
                pending_restore[
                    "source_backup_file_name"
                ]
            ),
        }

    @classmethod
    def _validate_database_file(
        cls,
        database_file,
    ):
        """
        Validate one SQLite database file without modifying it.
        """

        database_file = Path(
            database_file
        ).resolve()

        if not database_file.exists():
            raise DatabaseRestoreError(
                "The selected database backup does not exist."
            )

        if not database_file.is_file():
            raise DatabaseRestoreError(
                "The selected database backup is not a file."
            )

        try:
            file_stat = database_file.stat()

        except OSError as error:
            raise DatabaseRestoreError(
                "The selected database backup could not be read."
            ) from error

        if file_stat.st_size <= 0:
            raise DatabaseRestoreError(
                "The selected database backup is empty."
            )

        connection = None

        try:
            connection = sqlite3.connect(
                (
                    database_file.as_uri()
                    + "?mode=ro"
                ),
                uri=True,
                timeout=30.0,
            )

            integrity_rows = connection.execute(
                "PRAGMA integrity_check"
            ).fetchall()

            integrity_messages = [
                str(row[0])
                for row in integrity_rows
            ]

            if integrity_messages != ["ok"]:
                raise DatabaseRestoreError(
                    "The selected database backup failed "
                    "SQLite integrity_check."
                )

            schema_version = (
                cls._read_schema_version(
                    connection
                )
            )

            if (
                schema_version is not None
                and schema_version
                > DatabaseMigrationService
                .CURRENT_DATABASE_SCHEMA_VERSION
            ):
                raise DatabaseRestoreError(
                    "The selected database backup was created "
                    "by a newer version of League Mastery "
                    "Tracker. "
                    f"Backup schema version: {schema_version}. "
                    "Supported schema version: "
                    f"{DatabaseMigrationService.CURRENT_DATABASE_SCHEMA_VERSION}."
                )

        except DatabaseRestoreError:
            raise

        except (
            sqlite3.Error,
            OSError,
        ) as error:
            raise DatabaseRestoreError(
                "The selected database backup is not a valid "
                "or readable SQLite database."
            ) from error

        finally:
            if connection is not None:
                connection.close()

        return {
            "size_bytes": file_stat.st_size,
            "modified_at": datetime.fromtimestamp(
                file_stat.st_mtime
            ).astimezone(),
            "valid": True,
            "schema_version": schema_version,
            "unversioned": schema_version is None,
            "error": None,
        }

    @classmethod
    def _resolve_backup_file(
        cls,
        backup_file_name,
    ):
        """
        Resolve one internal backup while preventing traversal.
        """

        normalized_file_name = str(
            backup_file_name or ""
        ).strip()

        if not cls.BACKUP_FILE_PATTERN.fullmatch(
            normalized_file_name
        ):
            raise DatabaseRestoreError(
                "The selected database backup filename "
                "is invalid."
            )

        backup_directory = Path(
            current_app.config["BACKUP_DIR"]
        ).resolve()

        backup_file = (
            backup_directory
            / normalized_file_name
        ).resolve()

        if backup_file.parent != backup_directory:
            raise DatabaseRestoreError(
                "The selected database backup is outside "
                "the internal backup directory."
            )

        return backup_file

    @classmethod
    def _resolve_staged_file(
        cls,
        staged_file_name,
    ):
        """
        Resolve one staged database while preventing traversal.
        """

        normalized_file_name = str(
            staged_file_name or ""
        ).strip()

        if not cls.STAGED_FILE_PATTERN.fullmatch(
            normalized_file_name
        ):
            raise DatabaseRestoreError(
                "The staged database filename is invalid."
            )

        restore_directory = (
            cls._get_restore_directory()
            .resolve()
        )

        staged_file = (
            restore_directory
            / normalized_file_name
        ).resolve()

        if staged_file.parent != restore_directory:
            raise DatabaseRestoreError(
                "The staged database is outside the restore "
                "directory."
            )

        return staged_file

    @classmethod
    def _read_schema_version(
        cls,
        connection,
    ):
        """
        Read schema metadata from a database without modifying it.
        """

        metadata_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (
                DatabaseMigrationService.METADATA_TABLE,
            ),
        ).fetchone()

        if metadata_table is None:
            return None

        row = connection.execute(
            f"""
            SELECT value
            FROM {DatabaseMigrationService.METADATA_TABLE}
            WHERE key = ?
            """,
            (
                DatabaseMigrationService.SCHEMA_VERSION_KEY,
            ),
        ).fetchone()

        if row is None:
            return None

        raw_version = row[0]

        try:
            schema_version = int(
                raw_version
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise DatabaseRestoreError(
                "The selected database backup contains an "
                "invalid schema version."
            ) from error

        if schema_version <= 0:
            raise DatabaseRestoreError(
                "The selected database backup contains an "
                "invalid schema version."
            )

        return schema_version

    @staticmethod
    def _calculate_sha256(
        file_path,
    ):
        """
        Calculate a streaming SHA-256 checksum.
        """

        digest = hashlib.sha256()

        try:
            with Path(file_path).open(
                "rb"
            ) as file:
                for chunk in iter(
                    lambda: file.read(
                        1024 * 1024
                    ),
                    b"",
                ):
                    digest.update(
                        chunk
                    )

        except OSError as error:
            raise DatabaseRestoreError(
                "The database restore checksum could not "
                "be calculated."
            ) from error

        return digest.hexdigest()

    @classmethod
    def _remove_unused_staged_files(
        cls,
        keep_file,
    ):
        restore_directory = (
            cls._get_restore_directory()
        )

        if not restore_directory.exists():
            return

        keep_path = (
            Path(keep_file).resolve()
            if keep_file is not None
            else None
        )

        for staged_file in restore_directory.glob(
            "pending_restore_*.db"
        ):
            if (
                keep_path is not None
                and staged_file.resolve() == keep_path
            ):
                continue

            cls._delete_if_exists(
                staged_file
            )

        for temporary_file in restore_directory.glob(
            "*.tmp"
        ):
            cls._delete_if_exists(
                temporary_file
            )

    @staticmethod
    def _delete_if_exists(
        file_path,
    ):
        file_path = Path(
            file_path
        )

        try:
            file_path.unlink(
                missing_ok=True
            )

        except OSError:
            pass

    @staticmethod
    def _get_database_file():
        return Path(
            current_app.config["DATABASE_FILE"]
        )

    @staticmethod
    def _get_restore_directory():
        configuration_directory = Path(
            current_app.config["CONFIG_DIR"]
        )

        return (
            configuration_directory
            / DatabaseRestoreService
            .RESTORE_DIRECTORY_NAME
        )

    @classmethod
    def _get_marker_file(cls):
        return (
            cls._get_restore_directory()
            / cls.MARKER_FILE_NAME
        )