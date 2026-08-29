from datetime import datetime, timedelta

from application.services.database_migration_service import (
    DatabaseMigrationService,
)


class JsonExportValidationError(RuntimeError):
    """
    Raised when a JSON export document violates the supported
    portable data format.
    """


class JsonExportValidationService:
    """
    Validates the complete League Mastery Tracker export format.

    This validator is used after export generation and will later
    form part of the read-only import validation workflow.
    """

    EXPORT_FORMAT_IDENTIFIER = (
        "league-mastery-tracker-export"
    )

    TOP_LEVEL_KEYS = {
        "format",
        "format_version",
        "database_schema_version",
        "exported_at",
        "record_counts",
        "data",
    }

    RECORD_COUNT_KEYS = {
        "persons",
        "riot_accounts",
        "champions",
        "mastery_records",
    }

    DATA_KEYS = {
        "champions",
        "persons",
    }

    CHAMPION_KEYS = {
        "riot_champion_id",
        "name",
        "image",
        "source",
    }

    PERSON_KEYS = {
        "display_name",
        "riot_accounts",
    }

    RIOT_ACCOUNT_KEYS = {
        "game_name",
        "tag_line",
        "puuid",
        "platform_region",
        "last_sync",
        "champion_mastery",
    }

    MASTERY_KEYS = {
        "riot_champion_id",
        "mastery_points",
    }

    @classmethod
    def validate_document(
        cls,
        document,
    ):
        """
        Validate one complete parsed export document.

        Returns the independently calculated record counts when the
        document is valid.
        """

        cls._require_mapping(
            document,
            "The export document",
        )

        cls._require_exact_keys(
            document,
            cls.TOP_LEVEL_KEYS,
            "The export document",
        )

        if (
            document["format"]
            != cls.EXPORT_FORMAT_IDENTIFIER
        ):
            raise JsonExportValidationError(
                "The export format identifier is invalid."
            )

        format_version = (
            cls._require_positive_integer(
                document["format_version"],
                "The export format version",
            )
        )

        current_format_version = (
            DatabaseMigrationService
            .get_export_format_version()
        )

        if format_version != current_format_version:
            raise JsonExportValidationError(
                "The export format version is unsupported. "
                f"Document version: {format_version}. "
                "Supported version: "
                f"{current_format_version}."
            )

        database_schema_version = (
            cls._require_positive_integer(
                document[
                    "database_schema_version"
                ],
                "The database schema version",
            )
        )

        current_database_schema_version = (
            DatabaseMigrationService
            .CURRENT_DATABASE_SCHEMA_VERSION
        )

        if (
            database_schema_version
            != current_database_schema_version
        ):
            raise JsonExportValidationError(
                "The export database schema version is "
                "unsupported. "
                f"Document version: {database_schema_version}. "
                "Supported version: "
                f"{current_database_schema_version}."
            )

        cls._validate_utc_timestamp(
            document["exported_at"],
            "The export timestamp",
            allow_none=False,
        )

        expected_counts = (
            cls._validate_record_counts(
                document["record_counts"]
            )
        )

        data = document["data"]

        cls._require_mapping(
            data,
            "The export data section",
        )

        cls._require_exact_keys(
            data,
            cls.DATA_KEYS,
            "The export data section",
        )

        champions = data["champions"]
        persons = data["persons"]

        cls._require_list(
            champions,
            "The champions collection",
        )

        cls._require_list(
            persons,
            "The persons collection",
        )

        champion_ids = (
            cls._validate_champions(
                champions
            )
        )

        actual_counts = (
            cls._validate_persons(
                persons=persons,
                champion_ids=champion_ids,
            )
        )

        actual_counts["champions"] = len(
            champions
        )

        for count_name in sorted(
            cls.RECORD_COUNT_KEYS
        ):
            expected_value = expected_counts[
                count_name
            ]

            actual_value = actual_counts[
                count_name
            ]

            if expected_value != actual_value:
                raise JsonExportValidationError(
                    "The export record count for "
                    f"{count_name} is inconsistent. "
                    f"Declared count: {expected_value}. "
                    f"Actual count: {actual_value}."
                )

        return actual_counts

    @classmethod
    def _validate_record_counts(
        cls,
        record_counts,
    ):
        cls._require_mapping(
            record_counts,
            "The record counts section",
        )

        cls._require_exact_keys(
            record_counts,
            cls.RECORD_COUNT_KEYS,
            "The record counts section",
        )

        return {
            key: cls._require_nonnegative_integer(
                record_counts[key],
                (
                    "The record count for "
                    f"{key}"
                ),
            )
            for key in cls.RECORD_COUNT_KEYS
        }

    @classmethod
    def _validate_champions(
        cls,
        champions,
    ):
        champion_ids = set()

        for index, champion in enumerate(
            champions
        ):
            context = (
                "Champion at index "
                f"{index}"
            )

            cls._require_mapping(
                champion,
                context,
            )

            cls._require_exact_keys(
                champion,
                cls.CHAMPION_KEYS,
                context,
            )

            riot_champion_id = (
                cls._require_positive_integer(
                    champion[
                        "riot_champion_id"
                    ],
                    (
                        f"{context} Riot "
                        "champion ID"
                    ),
                )
            )

            if riot_champion_id in champion_ids:
                raise JsonExportValidationError(
                    "The export contains duplicate Riot "
                    "champion ID "
                    f"{riot_champion_id}."
                )

            champion_ids.add(
                riot_champion_id
            )

            cls._require_optional_nonempty_string(
                champion["name"],
                f"{context} name",
            )

            cls._require_optional_nonempty_string(
                champion["image"],
                f"{context} image",
            )

            cls._require_nonempty_string(
                champion["source"],
                f"{context} source",
            )

        return champion_ids

    @classmethod
    def _validate_persons(
        cls,
        persons,
        champion_ids,
    ):
        riot_account_count = 0
        mastery_record_count = 0

        puuids = set()

        for person_index, person in enumerate(
            persons
        ):
            person_context = (
                "Person at index "
                f"{person_index}"
            )

            cls._require_mapping(
                person,
                person_context,
            )

            cls._require_exact_keys(
                person,
                cls.PERSON_KEYS,
                person_context,
            )

            cls._require_nonempty_string(
                person["display_name"],
                f"{person_context} display name",
            )

            riot_accounts = person[
                "riot_accounts"
            ]

            cls._require_list(
                riot_accounts,
                (
                    f"{person_context} Riot "
                    "accounts"
                ),
            )

            for account_index, account in enumerate(
                riot_accounts
            ):
                account_context = (
                    f"{person_context}, Riot account "
                    f"at index {account_index}"
                )

                cls._require_mapping(
                    account,
                    account_context,
                )

                cls._require_exact_keys(
                    account,
                    cls.RIOT_ACCOUNT_KEYS,
                    account_context,
                )

                cls._require_nonempty_string(
                    account["game_name"],
                    f"{account_context} game name",
                )

                cls._require_nonempty_string(
                    account["tag_line"],
                    f"{account_context} tag line",
                )

                puuid = cls._require_nonempty_string(
                    account["puuid"],
                    f"{account_context} PUUID",
                )

                if puuid in puuids:
                    raise JsonExportValidationError(
                        "The export contains duplicate PUUID "
                        f"{puuid}."
                    )

                puuids.add(
                    puuid
                )

                cls._require_nonempty_string(
                    account[
                        "platform_region"
                    ],
                    (
                        f"{account_context} "
                        "platform region"
                    ),
                )

                cls._validate_utc_timestamp(
                    account["last_sync"],
                    (
                        f"{account_context} "
                        "last-synchronized timestamp"
                    ),
                    allow_none=True,
                )

                mastery_records = account[
                    "champion_mastery"
                ]

                cls._require_list(
                    mastery_records,
                    (
                        f"{account_context} "
                        "champion mastery"
                    ),
                )

                mastery_champion_ids = set()

                for (
                    mastery_index,
                    mastery_record,
                ) in enumerate(
                    mastery_records
                ):
                    mastery_context = (
                        f"{account_context}, mastery "
                        f"record at index {mastery_index}"
                    )

                    cls._require_mapping(
                        mastery_record,
                        mastery_context,
                    )

                    cls._require_exact_keys(
                        mastery_record,
                        cls.MASTERY_KEYS,
                        mastery_context,
                    )

                    riot_champion_id = (
                        cls._require_positive_integer(
                            mastery_record[
                                "riot_champion_id"
                            ],
                            (
                                f"{mastery_context} "
                                "Riot champion ID"
                            ),
                        )
                    )

                    if (
                        riot_champion_id
                        not in champion_ids
                    ):
                        raise JsonExportValidationError(
                            f"{mastery_context} references "
                            "missing Riot champion ID "
                            f"{riot_champion_id}."
                        )

                    if (
                        riot_champion_id
                        in mastery_champion_ids
                    ):
                        raise JsonExportValidationError(
                            f"{account_context} contains "
                            "duplicate mastery for Riot "
                            "champion ID "
                            f"{riot_champion_id}."
                        )

                    mastery_champion_ids.add(
                        riot_champion_id
                    )

                    cls._require_nonnegative_integer(
                        mastery_record[
                            "mastery_points"
                        ],
                        (
                            f"{mastery_context} "
                            "mastery points"
                        ),
                    )

                    mastery_record_count += 1

                riot_account_count += 1

        return {
            "persons": len(
                persons
            ),
            "riot_accounts": (
                riot_account_count
            ),
            "mastery_records": (
                mastery_record_count
            ),
        }

    @staticmethod
    def _require_mapping(
        value,
        context,
    ):
        if not isinstance(
            value,
            dict,
        ):
            raise JsonExportValidationError(
                f"{context} must be an object."
            )

        return value

    @staticmethod
    def _require_list(
        value,
        context,
    ):
        if not isinstance(
            value,
            list,
        ):
            raise JsonExportValidationError(
                f"{context} must be an array."
            )

        return value

    @staticmethod
    def _require_exact_keys(
        value,
        expected_keys,
        context,
    ):
        actual_keys = set(
            value.keys()
        )

        if actual_keys == expected_keys:
            return

        missing_keys = sorted(
            expected_keys - actual_keys
        )

        unexpected_keys = sorted(
            actual_keys - expected_keys
        )

        details = []

        if missing_keys:
            details.append(
                "missing keys: "
                + ", ".join(
                    missing_keys
                )
            )

        if unexpected_keys:
            details.append(
                "unexpected keys: "
                + ", ".join(
                    unexpected_keys
                )
            )

        raise JsonExportValidationError(
            f"{context} has an invalid structure ("
            + "; ".join(
                details
            )
            + ")."
        )

    @staticmethod
    def _require_nonempty_string(
        value,
        context,
    ):
        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise JsonExportValidationError(
                f"{context} must be a non-empty string."
            )

        return value

    @classmethod
    def _require_optional_nonempty_string(
        cls,
        value,
        context,
    ):
        if value is None:
            return None

        return cls._require_nonempty_string(
            value,
            context,
        )

    @staticmethod
    def _require_positive_integer(
        value,
        context,
    ):
        if (
            not isinstance(
                value,
                int,
            )
            or isinstance(
                value,
                bool,
            )
            or value <= 0
        ):
            raise JsonExportValidationError(
                f"{context} must be a positive integer."
            )

        return value

    @staticmethod
    def _require_nonnegative_integer(
        value,
        context,
    ):
        if (
            not isinstance(
                value,
                int,
            )
            or isinstance(
                value,
                bool,
            )
            or value < 0
        ):
            raise JsonExportValidationError(
                f"{context} must be a non-negative integer."
            )

        return value

    @staticmethod
    def _validate_utc_timestamp(
        value,
        context,
        allow_none,
    ):
        if value is None:
            if allow_none:
                return None

            raise JsonExportValidationError(
                f"{context} is required."
            )

        if (
            not isinstance(
                value,
                str,
            )
            or not value.endswith(
                "Z"
            )
        ):
            raise JsonExportValidationError(
                f"{context} must be a UTC ISO-8601 "
                "timestamp ending in Z."
            )

        try:
            parsed_value = datetime.fromisoformat(
                value[:-1]
                + "+00:00"
            )

        except ValueError as error:
            raise JsonExportValidationError(
                f"{context} is not a valid timestamp."
            ) from error

        if (
            parsed_value.utcoffset()
            != timedelta(0)
        ):
            raise JsonExportValidationError(
                f"{context} must use UTC."
            )

        return parsed_value