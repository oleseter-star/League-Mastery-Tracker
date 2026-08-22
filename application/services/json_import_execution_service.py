from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.backup_service import BackupService
from application.services.json_import_plan_service import (
    JsonImportPlanError,
    JsonImportPlanService,
)


class JsonImportExecutionError(RuntimeError):
    """
    Raised when an import plan cannot be applied safely.
    """


class JsonImportExecutionService:
    """
    Applies one validated import plan inside a single transaction.

    A mandatory SQLite backup is created before any database write.
    The database is checked both before and after the backup.

    The second check runs while an SQLite BEGIN IMMEDIATE
    transaction is active. This prevents another writer from
    changing the database between final validation and commit.
    """

    @classmethod
    def apply_plan(
        cls,
        plan,
    ):
        """
        Apply one immutable or plain import plan.

        Returns a result describing the created and reused records.

        No backup is created for a plan that performs no writes.
        """

        try:
            JsonImportPlanService.verify_plan(
                plan
            )

            plain_plan = (
                JsonImportPlanService
                .to_plain_dict(
                    plan
                )
            )

        except JsonImportPlanError as error:
            raise JsonImportExecutionError(
                "The import plan failed validation before "
                "execution."
            ) from error

        cls._validate_supported_actions(
            plain_plan
        )

        cls._ensure_scoped_session_is_clean()

        # Preview and plan generation may have opened a read-only
        # transaction on Flask-SQLAlchemy's scoped session.
        db.session.rollback()

        cls._run_preflight_check(
            plain_plan
        )

        if not cls._plan_has_database_changes(
            plain_plan
        ):
            return {
                "applied": False,
                "reason": "no_database_changes",
                "plan_sha256": plain_plan[
                    "plan_sha256"
                ],
                "source_file_name": plain_plan[
                    "source"
                ]["file_name"],
                "backup_file": None,
                "created": {
                    "persons": 0,
                    "riot_accounts": 0,
                    "champions": 0,
                    "mastery_records": 0,
                },
                "reused": {
                    "champions": plain_plan[
                        "summary"
                    ]["champions_to_reuse"],
                },
            }

        backup_file = (
            cls._create_required_backup()
        )

        connection = None
        transaction_session = None

        try:
            connection = db.engine.connect()

            # This is deliberately the first SQL statement on the
            # dedicated connection.
            connection.exec_driver_sql(
                "BEGIN IMMEDIATE"
            )

            transaction_session = Session(
                bind=connection,
                expire_on_commit=False,
            )

            # The database may have changed while the backup was
            # being created. Check it again while holding the
            # SQLite write reservation.
            cls._assert_database_matches_plan(
                session=transaction_session,
                plan=plain_plan,
            )

            execution_counts = cls._apply_actions(
                session=transaction_session,
                plan=plain_plan,
            )

            transaction_session.flush()

            connection.commit()

        except JsonImportExecutionError:
            if connection is not None:
                connection.rollback()

            raise

        except Exception as error:
            if connection is not None:
                connection.rollback()

            raise JsonImportExecutionError(
                "The JSON import failed. All database changes "
                "were rolled back."
            ) from error

        finally:
            if transaction_session is not None:
                transaction_session.close()

            if connection is not None:
                connection.close()

        # Ensure later requests do not retain objects read before
        # the dedicated transaction committed.
        db.session.expire_all()

        return {
            "applied": True,
            "reason": "import_applied",
            "plan_sha256": plain_plan[
                "plan_sha256"
            ],
            "source_file_name": plain_plan[
                "source"
            ]["file_name"],
            "backup_file": backup_file,
            "created": execution_counts[
                "created"
            ],
            "reused": execution_counts[
                "reused"
            ],
        }

    @classmethod
    def _run_preflight_check(
        cls,
        plan,
    ):
        try:
            with Session(
                bind=db.engine
            ) as session:
                cls._assert_database_matches_plan(
                    session=session,
                    plan=plan,
                )

        except JsonImportExecutionError:
            raise

        except SQLAlchemyError as error:
            raise JsonImportExecutionError(
                "The local database could not be checked before "
                "JSON import."
            ) from error

    @classmethod
    def _assert_database_matches_plan(
        cls,
        session,
        plan,
    ):
        champion_actions = plan[
            "champions"
        ]

        champion_ids = [
            champion[
                "riot_champion_id"
            ]
            for champion in champion_actions
        ]

        local_champions = []

        if champion_ids:
            local_champions = list(
                session.execute(
                    select(
                        Champion
                    ).where(
                        Champion.riot_champion_id.in_(
                            champion_ids
                        )
                    )
                )
                .scalars()
                .all()
            )

        local_champion_by_riot_id = {
            champion.riot_champion_id: champion
            for champion in local_champions
        }

        for champion_action in champion_actions:
            riot_champion_id = champion_action[
                "riot_champion_id"
            ]

            local_champion = (
                local_champion_by_riot_id.get(
                    riot_champion_id
                )
            )

            if (
                champion_action["action"]
                == "create"
            ):
                if local_champion is not None:
                    raise JsonImportExecutionError(
                        "The database no longer matches the "
                        "import plan. Riot champion ID "
                        f"{riot_champion_id} now exists locally."
                    )

                continue

            if local_champion is None:
                raise JsonImportExecutionError(
                    "The database no longer matches the import "
                    "plan. Riot champion ID "
                    f"{riot_champion_id} is no longer available "
                    "for reuse."
                )

            expected_metadata = (
                champion_action[
                    "expected_local_metadata"
                ]
            )

            actual_metadata = {
                "name": local_champion.name,
                "image": local_champion.image,
                "source": local_champion.source,
            }

            if actual_metadata != expected_metadata:
                raise JsonImportExecutionError(
                    "The database no longer matches the import "
                    "plan. Local metadata changed for Riot "
                    f"champion ID {riot_champion_id}."
                )

        imported_puuids = [
            account["puuid"]
            for person in plan["persons"]
            for account in person[
                "riot_accounts"
            ]
        ]

        if imported_puuids:
            existing_puuids = set(
                session.execute(
                    select(
                        RiotAccount.puuid
                    ).where(
                        RiotAccount.puuid.in_(
                            imported_puuids
                        )
                    )
                )
                .scalars()
                .all()
            )

            if existing_puuids:
                raise JsonImportExecutionError(
                    "The database no longer matches the import "
                    "plan. One or more imported PUUIDs now "
                    "exist locally."
                )

        display_names = {
            person["display_name"]
            for person in plan[
                "persons"
            ]
        }

        local_name_counts = {
            display_name: 0
            for display_name in display_names
        }

        if display_names:
            local_people = list(
                session.execute(
                    select(
                        Person
                    ).where(
                        Person.display_name.in_(
                            display_names
                        )
                    )
                )
                .scalars()
                .all()
            )

            for local_person in local_people:
                local_name_counts[
                    local_person.display_name
                ] += 1

        for person_action in plan[
            "persons"
        ]:
            display_name = person_action[
                "display_name"
            ]

            expected_match_count = (
                person_action[
                    "local_display_name_match_count"
                ]
            )

            actual_match_count = (
                local_name_counts.get(
                    display_name,
                    0,
                )
            )

            if (
                actual_match_count
                != expected_match_count
            ):
                raise JsonImportExecutionError(
                    "The database no longer matches the import "
                    "plan. The local display-name match count "
                    f'changed for "{display_name}".'
                )

    @classmethod
    def _apply_actions(
        cls,
        session,
        plan,
    ):
        champion_by_riot_id = {}

        reused_champion_count = 0
        created_champion_count = 0

        for champion_action in plan[
            "champions"
        ]:
            riot_champion_id = champion_action[
                "riot_champion_id"
            ]

            if (
                champion_action["action"]
                == "reuse"
            ):
                champion = session.execute(
                    select(
                        Champion
                    ).where(
                        Champion.riot_champion_id
                        == riot_champion_id
                    )
                ).scalar_one()

                champion_by_riot_id[
                    riot_champion_id
                ] = champion

                reused_champion_count += 1

                continue

            champion = Champion(
                riot_champion_id=(
                    riot_champion_id
                ),
                name=champion_action[
                    "name"
                ],
                image=champion_action[
                    "image"
                ],
                source=champion_action[
                    "source"
                ],
            )

            session.add(
                champion
            )

            champion_by_riot_id[
                riot_champion_id
            ] = champion

            created_champion_count += 1

        session.flush()

        created_person_count = 0
        created_account_count = 0
        created_mastery_count = 0

        for person_action in plan[
            "persons"
        ]:
            person = Person(
                display_name=person_action[
                    "display_name"
                ]
            )

            session.add(
                person
            )

            session.flush()

            created_person_count += 1

            for account_action in person_action[
                "riot_accounts"
            ]:
                account = RiotAccount(
                    person_id=person.id,
                    game_name=account_action[
                        "game_name"
                    ],
                    tag_line=account_action[
                        "tag_line"
                    ],
                    puuid=account_action[
                        "puuid"
                    ],
                    platform_region=(
                        account_action[
                            "platform_region"
                        ]
                    ),
                    last_sync=(
                        cls._parse_utc_timestamp(
                            account_action[
                                "last_sync"
                            ]
                        )
                    ),
                )

                session.add(
                    account
                )

                session.flush()

                created_account_count += 1

                for mastery_action in account_action[
                    "champion_mastery"
                ]:
                    riot_champion_id = (
                        mastery_action[
                            "riot_champion_id"
                        ]
                    )

                    champion = (
                        champion_by_riot_id.get(
                            riot_champion_id
                        )
                    )

                    if champion is None:
                        raise JsonImportExecutionError(
                            "The import plan references Riot "
                            "champion ID "
                            f"{riot_champion_id}, but no matching "
                            "champion action exists."
                        )

                    cls._create_mastery_record(
                        session=session,
                        account=account,
                        champion=champion,
                        mastery_points=(
                            mastery_action[
                                "mastery_points"
                            ]
                        ),
                    )

                    created_mastery_count += 1

        session.flush()

        return {
            "created": {
                "persons": created_person_count,
                "riot_accounts": (
                    created_account_count
                ),
                "champions": (
                    created_champion_count
                ),
                "mastery_records": (
                    created_mastery_count
                ),
            },
            "reused": {
                "champions": (
                    reused_champion_count
                ),
            },
        }

    @staticmethod
    def _create_mastery_record(
        session,
        account,
        champion,
        mastery_points,
    ):
        session.add(
            ChampionMastery(
                riot_account_id=account.id,
                champion_id=champion.id,
                mastery_points=mastery_points,
            )
        )

    @classmethod
    def _create_required_backup(
        cls,
    ):
        try:
            backup_result = (
                BackupService.create_backup()
            )

        except Exception as error:
            raise JsonImportExecutionError(
                "A required database backup could not be "
                "created before JSON import."
            ) from error

        if not isinstance(
            backup_result,
            Mapping,
        ):
            raise JsonImportExecutionError(
                "The required database backup returned an "
                "invalid result."
            )

        if (
            backup_result.get(
                "created"
            )
            is not True
        ):
            raise JsonImportExecutionError(
                "A new database backup was not created before "
                "JSON import."
            )

        raw_backup_file = backup_result.get(
            "backup_file"
        )

        try:
            backup_file = Path(
                raw_backup_file
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise JsonImportExecutionError(
                "The required database backup returned an "
                "invalid file path."
            ) from error

        if (
            not backup_file.exists()
            or not backup_file.is_file()
        ):
            raise JsonImportExecutionError(
                "The required database backup could not be "
                "verified on disk."
            )

        return backup_file

    @classmethod
    def _validate_supported_actions(
        cls,
        plan,
    ):
        champion_ids = set()

        for champion in plan[
            "champions"
        ]:
            action = champion.get(
                "action"
            )

            if action not in {
                "create",
                "reuse",
            }:
                raise JsonImportExecutionError(
                    "The import plan contains an unsupported "
                    "champion action."
                )

            riot_champion_id = (
                cls._require_positive_integer(
                    champion.get(
                        "riot_champion_id"
                    ),
                    "Riot champion ID",
                )
            )

            if riot_champion_id in champion_ids:
                raise JsonImportExecutionError(
                    "The import plan contains duplicate Riot "
                    f"champion ID {riot_champion_id}."
                )

            champion_ids.add(
                riot_champion_id
            )

            cls._require_optional_nonempty_string(
                champion.get(
                    "name"
                ),
                "Champion name",
            )

            cls._require_optional_nonempty_string(
                champion.get(
                    "image"
                ),
                "Champion image",
            )

            cls._require_nonempty_string(
                champion.get(
                    "source"
                ),
                "Champion source",
            )

            expected_local_metadata = (
                champion.get(
                    "expected_local_metadata"
                )
            )

            if action == "create":
                if (
                    expected_local_metadata
                    is not None
                ):
                    raise JsonImportExecutionError(
                        "A create-champion action cannot contain "
                        "expected local metadata."
                    )

            else:
                if not isinstance(
                    expected_local_metadata,
                    Mapping,
                ):
                    raise JsonImportExecutionError(
                        "A reuse-champion action must contain "
                        "expected local metadata."
                    )

                if set(
                    expected_local_metadata.keys()
                ) != {
                    "name",
                    "image",
                    "source",
                }:
                    raise JsonImportExecutionError(
                        "Expected local champion metadata has an "
                        "invalid structure."
                    )

        puuids = set()

        for person_index, person in enumerate(
            plan["persons"]
        ):
            if person.get(
                "action"
            ) != "create":
                raise JsonImportExecutionError(
                    "The import plan contains an unsupported "
                    "person action."
                )

            if (
                person.get(
                    "person_index"
                )
                != person_index
            ):
                raise JsonImportExecutionError(
                    "The import plan contains an invalid person "
                    "index."
                )

            cls._require_nonempty_string(
                person.get(
                    "display_name"
                ),
                "Person display name",
            )

            cls._require_nonnegative_integer(
                person.get(
                    "local_display_name_match_count"
                ),
                "Local display-name match count",
            )

            accounts = person.get(
                "riot_accounts"
            )

            if not isinstance(
                accounts,
                list,
            ):
                raise JsonImportExecutionError(
                    "The import plan Riot accounts must be a "
                    "list."
                )

            for account_index, account in enumerate(
                accounts
            ):
                if account.get(
                    "action"
                ) != "create":
                    raise JsonImportExecutionError(
                        "The import plan contains an unsupported "
                        "Riot account action."
                    )

                if (
                    account.get(
                        "account_index"
                    )
                    != account_index
                ):
                    raise JsonImportExecutionError(
                        "The import plan contains an invalid "
                        "Riot account index."
                    )

                for field_name, label in (
                    (
                        "game_name",
                        "Riot game name",
                    ),
                    (
                        "tag_line",
                        "Riot tag line",
                    ),
                    (
                        "puuid",
                        "Riot PUUID",
                    ),
                    (
                        "platform_region",
                        "Riot platform region",
                    ),
                ):
                    cls._require_nonempty_string(
                        account.get(
                            field_name
                        ),
                        label,
                    )

                puuid = account[
                    "puuid"
                ]

                if puuid in puuids:
                    raise JsonImportExecutionError(
                        "The import plan contains duplicate "
                        f"PUUID {puuid}."
                    )

                puuids.add(
                    puuid
                )

                cls._parse_utc_timestamp(
                    account.get(
                        "last_sync"
                    )
                )

                mastery_records = account.get(
                    "champion_mastery"
                )

                if not isinstance(
                    mastery_records,
                    list,
                ):
                    raise JsonImportExecutionError(
                        "The import plan mastery records must "
                        "be a list."
                    )

                mastery_champion_ids = set()

                for mastery in mastery_records:
                    if mastery.get(
                        "action"
                    ) != "create":
                        raise JsonImportExecutionError(
                            "The import plan contains an "
                            "unsupported mastery action."
                        )

                    riot_champion_id = (
                        cls._require_positive_integer(
                            mastery.get(
                                "riot_champion_id"
                            ),
                            "Mastery Riot champion ID",
                        )
                    )

                    if (
                        riot_champion_id
                        not in champion_ids
                    ):
                        raise JsonImportExecutionError(
                            "The import plan mastery data "
                            "references a missing Riot champion "
                            f"ID {riot_champion_id}."
                        )

                    if (
                        riot_champion_id
                        in mastery_champion_ids
                    ):
                        raise JsonImportExecutionError(
                            "The import plan contains duplicate "
                            "mastery for Riot champion ID "
                            f"{riot_champion_id}."
                        )

                    mastery_champion_ids.add(
                        riot_champion_id
                    )

                    cls._require_nonnegative_integer(
                        mastery.get(
                            "mastery_points"
                        ),
                        "Mastery points",
                    )

    @staticmethod
    def _ensure_scoped_session_is_clean():
        if (
            db.session.new
            or db.session.dirty
            or db.session.deleted
        ):
            raise JsonImportExecutionError(
                "The current database session contains "
                "uncommitted changes. JSON import was cancelled."
            )

    @staticmethod
    def _plan_has_database_changes(
        plan,
    ):
        summary = plan[
            "summary"
        ]

        return any(
            summary[
                field_name
            ] > 0
            for field_name in (
                "persons_to_create",
                "riot_accounts_to_create",
                "champions_to_create",
                "mastery_records_to_create",
            )
        )

    @staticmethod
    def _parse_utc_timestamp(
        value,
    ):
        if value is None:
            return None

        if (
            not isinstance(
                value,
                str,
            )
            or not value.endswith(
                "Z"
            )
        ):
            raise JsonImportExecutionError(
                "An imported timestamp is not a valid UTC "
                "timestamp."
            )

        try:
            parsed_value = datetime.fromisoformat(
                value[
                    :-1
                ]
                + "+00:00"
            )

        except ValueError as error:
            raise JsonImportExecutionError(
                "An imported timestamp is not a valid UTC "
                "timestamp."
            ) from error

        return (
            parsed_value
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

    @staticmethod
    def _require_nonempty_string(
        value,
        label,
    ):
        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise JsonImportExecutionError(
                f"{label} must be a non-empty string."
            )

        return value

    @classmethod
    def _require_optional_nonempty_string(
        cls,
        value,
        label,
    ):
        if value is None:
            return None

        return cls._require_nonempty_string(
            value,
            label,
        )

    @staticmethod
    def _require_positive_integer(
        value,
        label,
    ):
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
            or value <= 0
        ):
            raise JsonImportExecutionError(
                f"{label} must be a positive integer."
            )

        return value

    @staticmethod
    def _require_nonnegative_integer(
        value,
        label,
    ):
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
            or value < 0
        ):
            raise JsonImportExecutionError(
                f"{label} must be a non-negative integer."
            )

        return value