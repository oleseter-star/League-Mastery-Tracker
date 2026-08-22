import json
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.database_migration_service import (
    DatabaseMigrationService,
    DatabaseVersionError,
)
from application.services.json_export_validation_service import (
    JsonExportValidationError,
    JsonExportValidationService,
)


class JsonExportError(RuntimeError):
    """
    Raised when application data cannot be exported safely.
    """


class JsonExportService:
    """
    Builds the portable League Mastery Tracker JSON format.

    Internal database primary keys are deliberately excluded.
    Relationships are represented by nesting and Riot champion IDs.
    """

    EXPORT_FORMAT_IDENTIFIER = (
        JsonExportValidationService
        .EXPORT_FORMAT_IDENTIFIER
    )

    @classmethod
    def build_export_document(
        cls,
        exported_at=None,
    ):
        """
        Build and internally validate one complete export document.
        """

        export_timestamp = cls._normalize_datetime(
            exported_at
            or datetime.now(
                timezone.utc
            )
        )

        try:
            database_schema_version = (
                DatabaseMigrationService
                .get_database_schema_version()
            )

        except DatabaseVersionError as error:
            raise JsonExportError(
                "The database schema version could not be read "
                "before export."
            ) from error

        if database_schema_version is None:
            raise JsonExportError(
                "The database has not been assigned a schema "
                "version and cannot be exported safely."
            )

        try:
            persons = list(
                db.session.execute(
                    db.select(
                        Person
                    )
                )
                .scalars()
                .all()
            )

            riot_accounts = list(
                db.session.execute(
                    db.select(
                        RiotAccount
                    )
                )
                .scalars()
                .all()
            )

            champions = list(
                db.session.execute(
                    db.select(
                        Champion
                    )
                )
                .scalars()
                .all()
            )

            mastery_records = list(
                db.session.execute(
                    db.select(
                        ChampionMastery
                    )
                )
                .scalars()
                .all()
            )

        except SQLAlchemyError as error:
            raise JsonExportError(
                "The application database could not be read "
                "for JSON export."
            ) from error

        cls._validate_relationships(
            persons=persons,
            riot_accounts=riot_accounts,
            champions=champions,
            mastery_records=mastery_records,
        )

        champion_by_id = {
            champion.id: champion
            for champion in champions
        }

        accounts_by_person_id = {}

        for account in riot_accounts:
            accounts_by_person_id.setdefault(
                account.person_id,
                [],
            ).append(
                account
            )

        mastery_by_account_id = {}

        for mastery_record in mastery_records:
            mastery_by_account_id.setdefault(
                mastery_record.riot_account_id,
                [],
            ).append(
                mastery_record
            )

        exported_champions = [
            cls._serialize_champion(
                champion
            )
            for champion in sorted(
                champions,
                key=cls._champion_sort_key,
            )
        ]

        exported_persons = []

        for person in sorted(
            persons,
            key=cls._person_sort_key,
        ):
            exported_accounts = []

            person_accounts = sorted(
                accounts_by_person_id.get(
                    person.id,
                    [],
                ),
                key=cls._account_sort_key,
            )

            for account in person_accounts:
                account_mastery = sorted(
                    mastery_by_account_id.get(
                        account.id,
                        [],
                    ),
                    key=lambda mastery_record: (
                        cls._mastery_sort_key(
                            mastery_record,
                            champion_by_id,
                        )
                    ),
                )

                exported_accounts.append(
                    cls._serialize_account(
                        account=account,
                        mastery_records=(
                            account_mastery
                        ),
                        champion_by_id=(
                            champion_by_id
                        ),
                    )
                )

            exported_persons.append(
                {
                    "display_name": (
                        person.display_name
                    ),
                    "riot_accounts": (
                        exported_accounts
                    ),
                }
            )

        document = {
            "format": (
                cls.EXPORT_FORMAT_IDENTIFIER
            ),
            "format_version": (
                DatabaseMigrationService
                .get_export_format_version()
            ),
            "database_schema_version": (
                database_schema_version
            ),
            "exported_at": export_timestamp,
            "record_counts": {
                "persons": len(
                    persons
                ),
                "riot_accounts": len(
                    riot_accounts
                ),
                "champions": len(
                    champions
                ),
                "mastery_records": len(
                    mastery_records
                ),
            },
            "data": {
                "champions": (
                    exported_champions
                ),
                "persons": (
                    exported_persons
                ),
            },
        }

        try:
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

        except JsonExportValidationError as error:
            raise JsonExportError(
                "The generated JSON export failed internal "
                "validation."
            ) from error

        return document

    @classmethod
    def build_export_json(
        cls,
        exported_at=None,
    ):
        """
        Build a formatted UTF-8-compatible JSON string.

        A final newline is included so the file behaves like a
        normal text document in editors and command-line tools.
        """

        document = cls.build_export_document(
            exported_at=exported_at
        )

        try:
            serialized_document = json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise JsonExportError(
                "The application data could not be serialized "
                "as JSON."
            ) from error

        return (
            serialized_document
            + "\n"
        )

    @classmethod
    def build_export_bytes(
        cls,
        exported_at=None,
    ):
        """
        Build the export as UTF-8 bytes for HTTP download.
        """

        return cls.build_export_json(
            exported_at=exported_at
        ).encode(
            "utf-8"
        )

    @classmethod
    def build_export_file_name(
        cls,
        exported_at=None,
    ):
        """
        Create a filesystem-safe UTC export filename.
        """

        timestamp = (
            exported_at
            or datetime.now(
                timezone.utc
            )
        )

        if not isinstance(
            timestamp,
            datetime,
        ):
            raise JsonExportError(
                "The export timestamp must be a datetime."
            )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=timezone.utc
            )

        timestamp = timestamp.astimezone(
            timezone.utc
        )

        return (
            "league_mastery_tracker_export_"
            + timestamp.strftime(
                "%Y%m%dT%H%M%SZ"
            )
            + ".json"
        )

    @classmethod
    def _serialize_champion(
        cls,
        champion,
    ):
        return {
            "riot_champion_id": (
                champion.riot_champion_id
            ),
            "name": champion.name,
            "image": champion.image,
            "source": champion.source,
        }

    @classmethod
    def _serialize_account(
        cls,
        account,
        mastery_records,
        champion_by_id,
    ):
        exported_mastery = []

        for mastery_record in mastery_records:
            champion = champion_by_id[
                mastery_record.champion_id
            ]

            exported_mastery.append(
                {
                    "riot_champion_id": (
                        champion.riot_champion_id
                    ),
                    "mastery_points": (
                        mastery_record.mastery_points
                    ),
                }
            )

        return {
            "game_name": account.game_name,
            "tag_line": account.tag_line,
            "puuid": account.puuid,
            "platform_region": (
                account.platform_region
            ),
            "last_sync": cls._normalize_datetime(
                account.last_sync
            ),
            "champion_mastery": (
                exported_mastery
            ),
        }

    @classmethod
    def _validate_relationships(
        cls,
        persons,
        riot_accounts,
        champions,
        mastery_records,
    ):
        person_ids = {
            person.id
            for person in persons
        }

        account_ids = {
            account.id
            for account in riot_accounts
        }

        champion_ids = {
            champion.id
            for champion in champions
        }

        for account in riot_accounts:
            if account.person_id not in person_ids:
                raise JsonExportError(
                    "A Riot account references a person that "
                    "does not exist. Export was cancelled."
                )

        for mastery_record in mastery_records:
            if (
                mastery_record.riot_account_id
                not in account_ids
            ):
                raise JsonExportError(
                    "A mastery record references a Riot account "
                    "that does not exist. Export was cancelled."
                )

            if (
                mastery_record.champion_id
                not in champion_ids
            ):
                raise JsonExportError(
                    "A mastery record references a champion "
                    "that does not exist. Export was cancelled."
                )

    @staticmethod
    def _normalize_datetime(
        value,
    ):
        if value is None:
            return None

        if not isinstance(
            value,
            datetime,
        ):
            raise JsonExportError(
                "An exported timestamp is not a valid datetime."
            )

        if value.tzinfo is None:
            value = value.replace(
                tzinfo=timezone.utc
            )

        value = value.astimezone(
            timezone.utc
        )

        return value.isoformat().replace(
            "+00:00",
            "Z",
        )

    @staticmethod
    def _person_sort_key(
        person,
    ):
        display_name = str(
            person.display_name or ""
        )

        return (
            display_name.casefold(),
            person.id,
        )

    @staticmethod
    def _account_sort_key(
        account,
    ):
        game_name = str(
            account.game_name or ""
        )

        tag_line = str(
            account.tag_line or ""
        )

        puuid = str(
            account.puuid or ""
        )

        return (
            game_name.casefold(),
            tag_line.casefold(),
            puuid,
            account.id,
        )

    @staticmethod
    def _champion_sort_key(
        champion,
    ):
        return (
            int(
                champion.riot_champion_id
            ),
            champion.id,
        )

    @staticmethod
    def _mastery_sort_key(
        mastery_record,
        champion_by_id,
    ):
        champion = champion_by_id[
            mastery_record.champion_id
        ]

        return (
            int(
                champion.riot_champion_id
            ),
            mastery_record.id,
        )