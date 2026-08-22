import os
from pathlib import Path

from application.services.application_data_service import (
    ApplicationDataService,
)


class Config:
    """
    Base configuration for League Mastery Tracker.

    Program files and mutable user data are kept separate.
    On Windows, user data is stored under LOCALAPPDATA. Existing
    project-local data is copied in a controlled manner on first startup.
    """

    PRODUCT_NAME = (
        "League Mastery Tracker"
    )

    RELEASE_NAME = (
        "League Mastery Tracker 2.0"
    )

    APPLICATION_VERSION = (
        "2.0.0"
    )

    WINDOWS_EXECUTABLE_NAME = (
        "LeagueMasteryTracker.exe"
    )

    PROJECT_ROOT = (
        Path(__file__)
        .resolve()
        .parent
        .parent
        .parent
    )

    LEGACY_DATA_DIR = (
        PROJECT_ROOT
        / "data"
    )

    DATA_DIR = (
        ApplicationDataService
        .get_data_directory(
            project_root=PROJECT_ROOT,
        )
    )

    DATABASE_DIR = (
        DATA_DIR
        / "database"
    )

    CONFIG_DIR = (
        DATA_DIR
        / "configuration"
    )

    REFERENCE_DIR = (
        DATA_DIR
        / "reference"
    )

    BACKUP_DIR = (
        DATA_DIR
        / "backups"
    )

    DATABASE_FILE = (
        DATABASE_DIR
        / "league_mastery_tracker.db"
    )

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "development-secret-key",
    )

    RIOT_API_KEY = os.environ.get(
        "RIOT_API_KEY"
    )

    SQLALCHEMY_DATABASE_URI = (
        f"sqlite:///{DATABASE_FILE.as_posix()}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEBUG = False
    TESTING = False

    STARTUP_APPLICATION_DATA_MIGRATION_RESULT = None

    @classmethod
    def ensure_directories(cls):
        """
        Prepare persistent application-data directories.

        Existing project-local data is copied before any target
        directory is created. This prevents an empty target from
        blocking the one-time legacy-data migration.
        """

        migration_result = (
            ApplicationDataService
            .migrate_legacy_data(
                legacy_data_directory=(
                    cls.LEGACY_DATA_DIR
                ),
                target_data_directory=(
                    cls.DATA_DIR
                ),
            )
        )

        cls.STARTUP_APPLICATION_DATA_MIGRATION_RESULT = (
            migration_result
        )

        directories = (
            cls.DATA_DIR,
            cls.DATABASE_DIR,
            cls.CONFIG_DIR,
            cls.REFERENCE_DIR,
            cls.BACKUP_DIR,
        )

        for directory in directories:
            Path(
                directory
            ).mkdir(
                parents=True,
                exist_ok=True,
            )


class DevelopmentConfig(Config):
    """
    Development configuration.
    """

    DEBUG = True


class TestingConfig(Config):
    """
    Testing configuration.
    """

    TESTING = True


class ProductionConfig(Config):
    """
    Production configuration.
    """

    DEBUG = False


configurations = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
