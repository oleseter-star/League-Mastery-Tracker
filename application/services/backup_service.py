import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app


class BackupService:
    """
    Creates and maintains internal SQLite database backups.

    Backups are stored inside the application's private backup
    directory. The user is never prompted for a location.
    """

    FILE_PREFIX = "league_mastery_tracker"
    FILE_SUFFIX = ".db"

    DEFAULT_MAX_AGE_HOURS = 24
    DEFAULT_RETENTION_COUNT = 10

    @classmethod
    def create_backup_if_due(
        cls,
        max_age_hours=DEFAULT_MAX_AGE_HOURS,
        retention_count=DEFAULT_RETENTION_COUNT,
    ):
        """
        Create a backup when no backup exists or the latest backup
        is at least the configured number of hours old.
        """

        normalized_max_age = cls._normalize_max_age(
            max_age_hours
        )

        latest_backup = cls.get_latest_backup()

        if latest_backup is not None:
            latest_modified = datetime.fromtimestamp(
                latest_backup.stat().st_mtime,
                timezone.utc,
            )

            current_time = datetime.now(
                timezone.utc
            )

            backup_age = (
                current_time
                - latest_modified
            )

            if backup_age < timedelta(
                hours=normalized_max_age
            ):
                return {
                    "created": False,
                    "backup_file": latest_backup,
                    "reason": "recent_backup_exists",
                    "deleted_old_backups": 0,
                }

        return cls.create_backup(
            retention_count=retention_count
        )

    @classmethod
    def create_backup(
        cls,
        retention_count=DEFAULT_RETENTION_COUNT,
    ):
        """
        Create a consistent SQLite backup and remove backups beyond
        the configured retention count.
        """

        normalized_retention = (
            cls._normalize_retention_count(
                retention_count
            )
        )

        database_file = cls._get_database_file()
        backup_directory = cls._get_backup_directory()

        if not database_file.exists():
            raise FileNotFoundError(
                f"Database file was not found: {database_file}"
            )

        backup_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        backup_file = cls._build_backup_file(
            backup_directory
        )

        temporary_file = backup_file.with_suffix(
            f"{cls.FILE_SUFFIX}.tmp"
        )

        source_connection = None
        backup_connection = None

        try:
            source_connection = sqlite3.connect(
                str(database_file)
            )

            backup_connection = sqlite3.connect(
                str(temporary_file)
            )

            source_connection.backup(
                backup_connection
            )

            backup_connection.commit()

        except Exception:
            if temporary_file.exists():
                temporary_file.unlink()

            raise

        finally:
            if backup_connection is not None:
                backup_connection.close()

            if source_connection is not None:
                source_connection.close()

        temporary_file.replace(
            backup_file
        )

        deleted_old_backups = cls._prune_old_backups(
            retention_count=normalized_retention
        )

        return {
            "created": True,
            "backup_file": backup_file,
            "reason": "backup_created",
            "deleted_old_backups": deleted_old_backups,
        }

    @classmethod
    def get_latest_backup(cls):
        """
        Return the newest internal backup, if one exists.
        """

        backup_files = cls.get_backup_files()

        if not backup_files:
            return None

        return backup_files[0]

    @classmethod
    def get_backup_files(cls):
        """
        Return internal backups ordered from newest to oldest.
        """

        backup_directory = cls._get_backup_directory()

        if not backup_directory.exists():
            return []

        backup_files = list(
            backup_directory.glob(
                f"{cls.FILE_PREFIX}_*{cls.FILE_SUFFIX}"
            )
        )

        return sorted(
            backup_files,
            key=lambda backup_file: (
                backup_file.stat().st_mtime,
                backup_file.name,
            ),
            reverse=True,
        )

    @classmethod
    def _build_backup_file(
        cls,
        backup_directory,
    ):
        """
        Build a unique backup filename.

        Microseconds prevent two manual backups created during the
        same second from overwriting one another.
        """

        timestamp = datetime.now(
            timezone.utc
        ).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )

        return (
            backup_directory
            / (
                f"{cls.FILE_PREFIX}_"
                f"{timestamp}"
                f"{cls.FILE_SUFFIX}"
            )
        )

    @classmethod
    def _prune_old_backups(
        cls,
        retention_count,
    ):
        """
        Keep only the newest configured number of backups.
        """

        backup_files = cls.get_backup_files()

        expired_backups = backup_files[
            retention_count:
        ]

        deleted_count = 0

        for backup_file in expired_backups:
            backup_file.unlink()
            deleted_count += 1

        return deleted_count

    @classmethod
    def _get_database_file(cls):
        return Path(
            current_app.config["DATABASE_FILE"]
        )

    @classmethod
    def _get_backup_directory(cls):
        return Path(
            current_app.config["BACKUP_DIR"]
        )

    @staticmethod
    def _normalize_max_age(max_age_hours):
        try:
            normalized_age = float(
                max_age_hours
            )

        except (TypeError, ValueError) as error:
            raise ValueError(
                "Backup maximum age must be a number."
            ) from error

        if normalized_age <= 0:
            raise ValueError(
                "Backup maximum age must be greater than zero."
            )

        return normalized_age

    @staticmethod
    def _normalize_retention_count(
        retention_count
    ):
        try:
            normalized_count = int(
                retention_count
            )

        except (TypeError, ValueError) as error:
            raise ValueError(
                "Backup retention count must be an integer."
            ) from error

        if normalized_count <= 0:
            raise ValueError(
                "Backup retention count must be greater than zero."
            )

        return normalized_count