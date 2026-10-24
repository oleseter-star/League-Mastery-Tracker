import sqlite3
from pathlib import Path

from flask import Flask

from application.config import configurations
from application.database.database import db
from application.services.application_tab_lifecycle_client_service import (
    ApplicationTabLifecycleClientService,
)
from application.services.backup_service import BackupService
from application.services.champion_reference_bootstrap_service import (
    ChampionReferenceBootstrapService,
)
from application.services.csrf_service import CsrfService
from application.services.database_migration_service import (
    DatabaseMigrationService,
)
from application.services.database_restore_service import (
    DatabaseRestoreService,
)
from application.services.json_import_read_service import (
    JsonImportReadService,
)
from application.services.json_import_staging_service import (
    JsonImportStagingService,
)
from application.services.local_secret_key_service import (
    LocalSecretKeyService,
)


JSON_IMPORT_REQUEST_OVERHEAD_BYTES = (
    1024
    * 1024
)


def create_app(config_name="default"):
    app = Flask(__name__)

    config = configurations.get(
        config_name,
        configurations["default"],
    )

    config.ensure_directories()

    app.config.from_object(config)

    json_import_max_file_size = (
        JsonImportReadService
        .DEFAULT_MAX_FILE_SIZE_BYTES
    )

    json_import_expiration_minutes = (
        JsonImportStagingService
        .DEFAULT_EXPIRATION_MINUTES
    )

    app.config.update(
        SESSION_COOKIE_NAME=(
            "league_mastery_tracker_session"
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        CSRF_ENABLED=True,
        JSON_IMPORT_MAX_FILE_SIZE_BYTES=(
            json_import_max_file_size
        ),
        JSON_IMPORT_STAGING_EXPIRATION_MINUTES=(
            json_import_expiration_minutes
        ),
        MAX_CONTENT_LENGTH=(
            json_import_max_file_size
            + JSON_IMPORT_REQUEST_OVERHEAD_BYTES
        ),
    )

    with app.app_context():
        app.config["SECRET_KEY"] = (
            LocalSecretKeyService
            .get_or_create_secret_key()
        )

    CsrfService.init_app(
        app
    )

    tab_lifecycle_client_service = (
        ApplicationTabLifecycleClientService()
    )

    tab_lifecycle_client_service.init_app(
        app
    )

    app.config[
        "STARTUP_DATABASE_RESTORE_RESULT"
    ] = None

    app.config[
        "STARTUP_BACKUP_RESULT"
    ] = None

    app.config[
        "STARTUP_BACKUP_ERROR"
    ] = None

    app.config[
        "STARTUP_DATABASE_MIGRATION_RESULT"
    ] = None

    app.config[
        "STARTUP_CHAMPION_REFERENCE_RESULT"
    ] = None

    app.config[
        "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
    ] = None

    app.config[
        "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
    ] = None

    # A pending restore must be applied before SQLAlchemy opens
    # the live database file.
    with app.app_context():
        restore_result = (
            DatabaseRestoreService
            .apply_pending_restore()
        )

        app.config[
            "STARTUP_DATABASE_RESTORE_RESULT"
        ] = restore_result

    database_file = Path(
        app.config[
            "DATABASE_FILE"
        ]
    )

    database_existed_before_initialization = (
        database_file.exists()
    )

    db.init_app(
        app
    )

    with app.app_context():
        # This runs after a pending restore. An old or unversioned
        # restored database therefore receives its own mandatory
        # pre-migration backup.
        _run_startup_backup(
            app=app,
            database_existed=(
                database_existed_before_initialization
            ),
        )

        migration_result = (
            DatabaseMigrationService
            .initialize_or_migrate()
        )

        app.config[
            "STARTUP_DATABASE_MIGRATION_RESULT"
        ] = migration_result

        from application.database import models

        db.create_all()

        from application.services.match_schema_service import (
            MatchSchemaService,
        )

        MatchSchemaService.add_missing_columns()

        champion_reference_result = (
            ChampionReferenceBootstrapService()
            .bootstrap()
        )

        app.config[
            "STARTUP_CHAMPION_REFERENCE_RESULT"
        ] = champion_reference_result

    from application.routes.application_control import (
        application_control_bp,
    )
    from application.routes.champion_images import (
        champion_images_bp,
    )
    from application.routes.champions import (
        champions_bp,
    )
    from application.routes.dashboard import (
        dashboard_bp,
    )
    from application.routes.database_restore import (
        database_restore_bp,
    )
    from application.routes.home import (
        home_bp,
    )
    from application.routes.json_export import (
        json_export_bp,
    )
    from application.routes.json_import import (
        json_import_bp,
    )
    from application.routes.match_review import (
        match_review_bp,
    )
    from application.routes.persons import (
        persons_bp,
    )
    from application.routes.settings import (
        settings_bp,
    )

    app.register_blueprint(
        home_bp
    )

    app.register_blueprint(
        dashboard_bp
    )

    app.register_blueprint(
        persons_bp
    )

    app.register_blueprint(
        champions_bp
    )

    app.register_blueprint(
        champion_images_bp
    )

    app.register_blueprint(
        match_review_bp
    )

    app.register_blueprint(
        settings_bp
    )

    app.register_blueprint(
        database_restore_bp
    )

    app.register_blueprint(
        json_export_bp
    )

    app.register_blueprint(
        json_import_bp
    )

    app.register_blueprint(
        application_control_bp
    )

    return app


def _run_startup_backup(
    app,
    database_existed,
):
    """
    Create the appropriate startup backup.

    A schema migration or first-time baseline always requires a new
    backup. A current database follows the normal 24-hour rule.
    """

    if (
        not database_existed
        or app.config.get(
            "TESTING",
            False,
        )
    ):
        return

    stored_version = (
        DatabaseMigrationService
        .get_database_schema_version()
    )

    current_version = (
        DatabaseMigrationService
        .CURRENT_DATABASE_SCHEMA_VERSION
    )

    migration_required = (
        stored_version is None
        or stored_version
        < current_version
    )

    if migration_required:
        try:
            backup_result = (
                BackupService
                .create_backup()
            )

        except (
            OSError,
            sqlite3.Error,
            ValueError,
        ) as error:
            app.config[
                "STARTUP_BACKUP_ERROR"
            ] = str(
                error
            )

            raise RuntimeError(
                "A required database backup could not be "
                "created before schema migration."
            ) from error

        app.config[
            "STARTUP_BACKUP_RESULT"
        ] = backup_result

        return

    if stored_version != current_version:
        return

    try:
        backup_result = (
            BackupService
            .create_backup_if_due()
        )

    except (
        OSError,
        sqlite3.Error,
        ValueError,
    ):
        app.config[
            "STARTUP_BACKUP_ERROR"
        ] = (
            "The automatic startup database backup could not be "
            "completed. League Mastery Tracker continued without "
            "a confirmed new startup backup. Try creating a manual "
            "database backup."
        )

    else:
        app.config[
            "STARTUP_BACKUP_RESULT"
        ] = backup_result