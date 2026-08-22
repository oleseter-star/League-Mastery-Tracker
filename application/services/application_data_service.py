import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path


class ApplicationDataMigrationError(RuntimeError):
    """
    Raised when existing application data cannot be copied safely
    to the persistent user-data directory.
    """


class ApplicationDataService:
    """
    Resolves the persistent application-data directory and safely
    copies data from the legacy project-local data directory.

    Existing legacy data is copied, never moved or deleted.
    Existing target data is never overwritten.
    """

    APPLICATION_DIRECTORY_NAME = (
        "LeagueMasteryTracker"
    )

    DATA_DIRECTORY_ENVIRONMENT_VARIABLE = (
        "LEAGUE_MASTERY_TRACKER_DATA_DIR"
    )

    MIGRATION_MARKER_FILE_NAME = (
        ".legacy_data_migration_completed.json"
    )

    MIGRATION_MARKER_FORMAT_VERSION = 1

    @classmethod
    def get_data_directory(
        cls,
        project_root,
        environment=None,
        os_name=None,
        home_directory=None,
    ):
        """
        Return the directory used for mutable application data.

        Priority:

        1. Explicit LEAGUE_MASTERY_TRACKER_DATA_DIR override
        2. Windows LOCALAPPDATA
        3. Windows user-profile fallback
        4. Project-local data directory on non-Windows systems
        """

        project_root = Path(
            project_root
        ).expanduser().resolve()

        if environment is None:
            environment = os.environ

        if os_name is None:
            os_name = os.name

        if home_directory is None:
            home_directory = Path.home()

        home_directory = Path(
            home_directory
        ).expanduser().resolve()

        override_value = str(
            environment.get(
                cls.DATA_DIRECTORY_ENVIRONMENT_VARIABLE,
                "",
            )
            or ""
        ).strip()

        if override_value:
            return Path(
                override_value
            ).expanduser().resolve()

        if os_name == "nt":
            local_appdata_value = str(
                environment.get(
                    "LOCALAPPDATA",
                    "",
                )
                or ""
            ).strip()

            if local_appdata_value:
                local_appdata_directory = Path(
                    local_appdata_value
                ).expanduser()

            else:
                local_appdata_directory = (
                    home_directory
                    / "AppData"
                    / "Local"
                )

            return (
                local_appdata_directory
                / cls.APPLICATION_DIRECTORY_NAME
            ).resolve()

        return (
            project_root
            / "data"
        ).resolve()

    @classmethod
    def migrate_legacy_data(
        cls,
        legacy_data_directory,
        target_data_directory,
    ):
        """
        Copy legacy project-local data to a fresh persistent target.

        The copy is first written to a temporary staging directory.
        Only after the complete copy and migration marker have been
        written is the staging directory renamed to the target.

        The source directory is never modified or deleted.
        """

        legacy_data_directory = Path(
            legacy_data_directory
        ).expanduser().resolve()

        target_data_directory = Path(
            target_data_directory
        ).expanduser().resolve()

        if (
            legacy_data_directory
            == target_data_directory
        ):
            return cls._build_skipped_result(
                reason="same_data_directory",
                legacy_data_directory=(
                    legacy_data_directory
                ),
                target_data_directory=(
                    target_data_directory
                ),
            )

        migration_marker_file = (
            target_data_directory
            / cls.MIGRATION_MARKER_FILE_NAME
        )

        if migration_marker_file.is_file():
            return cls._build_skipped_result(
                reason=(
                    "migration_already_completed"
                ),
                legacy_data_directory=(
                    legacy_data_directory
                ),
                target_data_directory=(
                    target_data_directory
                ),
            )

        if target_data_directory.exists():
            return cls._build_skipped_result(
                reason="target_data_already_exists",
                legacy_data_directory=(
                    legacy_data_directory
                ),
                target_data_directory=(
                    target_data_directory
                ),
            )

        if not legacy_data_directory.exists():
            return cls._build_skipped_result(
                reason="legacy_data_not_found",
                legacy_data_directory=(
                    legacy_data_directory
                ),
                target_data_directory=(
                    target_data_directory
                ),
            )

        if not legacy_data_directory.is_dir():
            raise ApplicationDataMigrationError(
                "The legacy application-data path is not "
                "a directory."
            )

        target_parent_directory = (
            target_data_directory.parent
        )

        staging_directory = (
            target_parent_directory
            / (
                f".{cls.APPLICATION_DIRECTORY_NAME}"
                ".migration-"
                f"{secrets.token_hex(16)}"
            )
        )

        try:
            target_parent_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copytree(
                legacy_data_directory,
                staging_directory,
            )

            copied_file_count = (
                cls._count_files(
                    staging_directory
                )
            )

            cls._write_migration_marker(
                staging_directory=(
                    staging_directory
                ),
                legacy_data_directory=(
                    legacy_data_directory
                ),
                target_data_directory=(
                    target_data_directory
                ),
                copied_file_count=(
                    copied_file_count
                ),
            )

            if target_data_directory.exists():
                raise ApplicationDataMigrationError(
                    "The target application-data directory "
                    "was created while legacy data was being "
                    "copied. Existing target data was not "
                    "overwritten."
                )

            staging_directory.replace(
                target_data_directory
            )

        except ApplicationDataMigrationError:
            cls._remove_directory_if_exists(
                staging_directory
            )

            raise

        except (
            OSError,
            shutil.Error,
            ValueError,
            TypeError,
        ) as error:
            cls._remove_directory_if_exists(
                staging_directory
            )

            raise ApplicationDataMigrationError(
                "Existing application data could not be "
                "copied safely to the persistent data "
                "directory. The original data was not "
                "modified."
            ) from error

        return {
            "migrated": True,
            "reason": "legacy_data_copied",
            "legacy_data_directory": (
                legacy_data_directory
            ),
            "target_data_directory": (
                target_data_directory
            ),
            "copied_file_count": (
                copied_file_count
            ),
            "migration_marker_file": (
                target_data_directory
                / cls.MIGRATION_MARKER_FILE_NAME
            ),
        }

    @classmethod
    def _write_migration_marker(
        cls,
        staging_directory,
        legacy_data_directory,
        target_data_directory,
        copied_file_count,
    ):
        """
        Write the completed migration marker inside the staging copy.
        """

        marker_file = (
            staging_directory
            / cls.MIGRATION_MARKER_FILE_NAME
        )

        temporary_marker_file = (
            staging_directory
            / (
                cls.MIGRATION_MARKER_FILE_NAME
                + ".tmp"
            )
        )

        marker_data = {
            "format_version": (
                cls.MIGRATION_MARKER_FORMAT_VERSION
            ),
            "completed_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "legacy_data_directory": str(
                legacy_data_directory
            ),
            "target_data_directory": str(
                target_data_directory
            ),
            "copied_file_count": (
                copied_file_count
            ),
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

    @staticmethod
    def _count_files(
        directory,
    ):
        """
        Count regular files inside a directory recursively.
        """

        return sum(
            1
            for path in directory.rglob("*")
            if path.is_file()
        )

    @staticmethod
    def _remove_directory_if_exists(
        directory,
    ):
        """
        Remove an incomplete staging directory without masking the
        original migration error.
        """

        if not directory.exists():
            return

        try:
            shutil.rmtree(
                directory
            )

        except OSError:
            pass

    @staticmethod
    def _build_skipped_result(
        reason,
        legacy_data_directory,
        target_data_directory,
    ):
        return {
            "migrated": False,
            "reason": reason,
            "legacy_data_directory": (
                legacy_data_directory
            ),
            "target_data_directory": (
                target_data_directory
            ),
            "copied_file_count": 0,
            "migration_marker_file": None,
        }