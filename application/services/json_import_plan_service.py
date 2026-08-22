import copy
import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType

from application.services.json_export_validation_service import (
    JsonExportValidationError,
    JsonExportValidationService,
)
from application.services.json_import_preview_service import (
    JsonImportPreviewError,
    JsonImportPreviewService,
)


class JsonImportPlanError(RuntimeError):
    """
    Raised when a safe and internally consistent import plan cannot
    be created or verified.
    """


class JsonImportPlanService:
    """
    Builds a deterministic and deeply immutable import plan.

    The plan contains no database primary keys. It records only
    portable identities and the actions that a later transactional
    executor must perform.

    Building or verifying a plan does not modify the database.
    """

    PLAN_FORMAT_IDENTIFIER = (
        "league-mastery-tracker-import-plan"
    )

    PLAN_FORMAT_VERSION = 1

    PLAN_TOP_LEVEL_KEYS = {
        "plan_format",
        "plan_version",
        "source",
        "summary",
        "champions",
        "persons",
        "warnings",
        "plan_sha256",
    }

    @classmethod
    def build_plan(
        cls,
        import_read_result,
        import_preview,
    ):
        """
        Build an immutable plan from a validated import document and
        its current database preview.

        The preview is rebuilt before planning. This detects:

        - database changes since preview generation
        - modified preview data
        - changed source document data
        - newly introduced PUUID conflicts
        """

        if not isinstance(
            import_preview,
            Mapping,
        ):
            raise JsonImportPlanError(
                "The import preview must be a mapping."
            )

        try:
            current_preview = (
                JsonImportPreviewService
                .build_preview(
                    import_read_result
                )
            )

        except JsonImportPreviewError as error:
            raise JsonImportPlanError(
                "The import preview could not be rebuilt before "
                "plan generation."
            ) from error

        provided_preview = cls._to_plain_value(
            import_preview
        )

        if provided_preview != current_preview:
            raise JsonImportPlanError(
                "The import preview is stale or does not match "
                "the current database and source document."
            )

        if (
            not current_preview["can_import"]
            or current_preview["blockers"]
        ):
            raise JsonImportPlanError(
                "The import preview contains blocking conflicts "
                "and cannot be converted into an import plan."
            )

        document = import_read_result.get(
            "document"
        )

        try:
            validated_counts = (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

        except JsonExportValidationError as error:
            raise JsonImportPlanError(
                "The import document failed validation before "
                "plan generation."
            ) from error

        champion_actions = (
            cls._build_champion_actions(
                document=document,
                preview=current_preview,
            )
        )

        person_actions = (
            cls._build_person_actions(
                document=document,
                preview=current_preview,
            )
        )

        summary = cls._build_summary(
            validated_counts=validated_counts,
            champion_actions=champion_actions,
            person_actions=person_actions,
            warnings=current_preview[
                "warnings"
            ],
        )

        payload = {
            "plan_format": (
                cls.PLAN_FORMAT_IDENTIFIER
            ),
            "plan_version": (
                cls.PLAN_FORMAT_VERSION
            ),
            "source": {
                "file_name": import_read_result[
                    "file_name"
                ],
                "file_size_bytes": import_read_result[
                    "file_size_bytes"
                ],
                "file_sha256": import_read_result[
                    "sha256"
                ],
                "format": document[
                    "format"
                ],
                "format_version": document[
                    "format_version"
                ],
                "database_schema_version": document[
                    "database_schema_version"
                ],
                "exported_at": document[
                    "exported_at"
                ],
            },
            "summary": summary,
            "champions": champion_actions,
            "persons": person_actions,
            "warnings": copy.deepcopy(
                current_preview[
                    "warnings"
                ]
            ),
        }

        plan_sha256 = cls._calculate_payload_sha256(
            payload
        )

        complete_plan = {
            **payload,
            "plan_sha256": plan_sha256,
        }

        cls.verify_plan(
            complete_plan
        )

        return cls._deep_freeze(
            complete_plan
        )

    @classmethod
    def verify_plan(
        cls,
        plan,
    ):
        """
        Verify the plan envelope and deterministic SHA-256.

        Returns True when the plan is internally consistent.

        The hash is an integrity check, not a cryptographic
        signature or authentication mechanism.
        """

        if not isinstance(
            plan,
            Mapping,
        ):
            raise JsonImportPlanError(
                "The import plan must be a mapping."
            )

        plain_plan = cls._to_plain_value(
            plan
        )

        actual_keys = set(
            plain_plan.keys()
        )

        if actual_keys != cls.PLAN_TOP_LEVEL_KEYS:
            missing_keys = (
                cls.PLAN_TOP_LEVEL_KEYS
                - actual_keys
            )

            extra_keys = (
                actual_keys
                - cls.PLAN_TOP_LEVEL_KEYS
            )

            details = []

            if missing_keys:
                details.append(
                    "missing fields: "
                    + ", ".join(
                        sorted(
                            missing_keys
                        )
                    )
                )

            if extra_keys:
                details.append(
                    "unexpected fields: "
                    + ", ".join(
                        sorted(
                            extra_keys
                        )
                    )
                )

            raise JsonImportPlanError(
                "The import plan has an invalid top-level "
                "structure"
                + (
                    ": "
                    + "; ".join(
                        details
                    )
                    if details
                    else "."
                )
            )

        if (
            plain_plan["plan_format"]
            != cls.PLAN_FORMAT_IDENTIFIER
        ):
            raise JsonImportPlanError(
                "The import plan format identifier is invalid."
            )

        plan_version = plain_plan[
            "plan_version"
        ]

        if (
            isinstance(
                plan_version,
                bool,
            )
            or not isinstance(
                plan_version,
                int,
            )
            or plan_version
            != cls.PLAN_FORMAT_VERSION
        ):
            raise JsonImportPlanError(
                "The import plan version is unsupported."
            )

        stored_sha256 = plain_plan[
            "plan_sha256"
        ]

        if not cls._is_valid_sha256(
            stored_sha256
        ):
            raise JsonImportPlanError(
                "The import plan contains an invalid SHA-256 "
                "value."
            )

        payload = dict(
            plain_plan
        )

        payload.pop(
            "plan_sha256"
        )

        calculated_sha256 = (
            cls._calculate_payload_sha256(
                payload
            )
        )

        if stored_sha256 != calculated_sha256:
            raise JsonImportPlanError(
                "The import plan failed its SHA-256 integrity "
                "check."
            )

        cls._validate_plan_summary(
            plain_plan
        )

        return True

    @classmethod
    def to_plain_dict(
        cls,
        plan,
    ):
        """
        Return a detached mutable copy of an immutable plan.

        This is intended for display, serialization, and tests.
        Modifying the returned copy does not modify the original
        plan.
        """

        if not isinstance(
            plan,
            Mapping,
        ):
            raise JsonImportPlanError(
                "The import plan must be a mapping."
            )

        return cls._to_plain_value(
            plan
        )

    @classmethod
    def _build_champion_actions(
        cls,
        document,
        preview,
    ):
        preview_by_riot_id = {
            champion[
                "riot_champion_id"
            ]: champion
            for champion in preview[
                "champions"
            ]
        }

        actions = []

        for imported_champion in document[
            "data"
        ]["champions"]:
            riot_champion_id = (
                imported_champion[
                    "riot_champion_id"
                ]
            )

            champion_preview = (
                preview_by_riot_id.get(
                    riot_champion_id
                )
            )

            if champion_preview is None:
                raise JsonImportPlanError(
                    "The import preview is missing Riot champion "
                    f"ID {riot_champion_id}."
                )

            status = champion_preview[
                "status"
            ]

            if status == "new":
                action = "create"
                expected_local_metadata = None

            elif status == "existing":
                action = "reuse"

                expected_local_metadata = copy.deepcopy(
                    champion_preview.get(
                        "local"
                    )
                )

            else:
                raise JsonImportPlanError(
                    "The import preview contains an unsupported "
                    "champion status."
                )

            actions.append(
                {
                    "action": action,
                    "riot_champion_id": (
                        riot_champion_id
                    ),
                    "name": imported_champion[
                        "name"
                    ],
                    "image": imported_champion[
                        "image"
                    ],
                    "source": imported_champion[
                        "source"
                    ],
                    "metadata_differs": (
                        champion_preview[
                            "metadata_differs"
                        ]
                    ),
                    "expected_local_metadata": (
                        expected_local_metadata
                    ),
                }
            )

        return actions

    @classmethod
    def _build_person_actions(
        cls,
        document,
        preview,
    ):
        preview_by_person_index = {
            person[
                "person_index"
            ]: person
            for person in preview[
                "persons"
            ]
        }

        person_actions = []

        for (
            person_index,
            imported_person,
        ) in enumerate(
            document["data"]["persons"]
        ):
            person_preview = (
                preview_by_person_index.get(
                    person_index
                )
            )

            if person_preview is None:
                raise JsonImportPlanError(
                    "The import preview is missing person index "
                    f"{person_index}."
                )

            if person_preview[
                "status"
            ] != "ready":
                raise JsonImportPlanError(
                    "A blocked person cannot be included in an "
                    "import plan."
                )

            preview_accounts_by_index = {
                account[
                    "account_index"
                ]: account
                for account in person_preview[
                    "riot_accounts"
                ]
            }

            account_actions = []

            for (
                account_index,
                imported_account,
            ) in enumerate(
                imported_person[
                    "riot_accounts"
                ]
            ):
                account_preview = (
                    preview_accounts_by_index.get(
                        account_index
                    )
                )

                if account_preview is None:
                    raise JsonImportPlanError(
                        "The import preview is missing Riot "
                        f"account index {account_index} for "
                        f"person index {person_index}."
                    )

                if account_preview[
                    "status"
                ] != "new":
                    raise JsonImportPlanError(
                        "Only new Riot accounts can be included "
                        "in the current import plan format."
                    )

                mastery_actions = [
                    {
                        "action": "create",
                        "riot_champion_id": (
                            mastery_record[
                                "riot_champion_id"
                            ]
                        ),
                        "mastery_points": (
                            mastery_record[
                                "mastery_points"
                            ]
                        ),
                    }
                    for mastery_record in imported_account[
                        "champion_mastery"
                    ]
                ]

                account_actions.append(
                    {
                        "action": "create",
                        "account_index": (
                            account_index
                        ),
                        "game_name": imported_account[
                            "game_name"
                        ],
                        "tag_line": imported_account[
                            "tag_line"
                        ],
                        "puuid": imported_account[
                            "puuid"
                        ],
                        "platform_region": (
                            imported_account[
                                "platform_region"
                            ]
                        ),
                        "last_sync": imported_account[
                            "last_sync"
                        ],
                        "champion_mastery": (
                            mastery_actions
                        ),
                    }
                )

            person_actions.append(
                {
                    "action": "create",
                    "person_index": person_index,
                    "display_name": imported_person[
                        "display_name"
                    ],
                    "local_display_name_match_count": (
                        person_preview[
                            "local_display_name_match_count"
                        ]
                    ),
                    "riot_accounts": account_actions,
                }
            )

        return person_actions

    @classmethod
    def _build_summary(
        cls,
        validated_counts,
        champion_actions,
        person_actions,
        warnings,
    ):
        champions_to_create = sum(
            1
            for champion in champion_actions
            if champion["action"] == "create"
        )

        champions_to_reuse = sum(
            1
            for champion in champion_actions
            if champion["action"] == "reuse"
        )

        riot_accounts_to_create = sum(
            len(
                person[
                    "riot_accounts"
                ]
            )
            for person in person_actions
        )

        mastery_records_to_create = sum(
            len(
                account[
                    "champion_mastery"
                ]
            )
            for person in person_actions
            for account in person[
                "riot_accounts"
            ]
        )

        summary = {
            "persons_in_file": validated_counts[
                "persons"
            ],
            "persons_to_create": len(
                person_actions
            ),
            "riot_accounts_in_file": validated_counts[
                "riot_accounts"
            ],
            "riot_accounts_to_create": (
                riot_accounts_to_create
            ),
            "champions_in_file": validated_counts[
                "champions"
            ],
            "champions_to_create": (
                champions_to_create
            ),
            "champions_to_reuse": (
                champions_to_reuse
            ),
            "mastery_records_in_file": (
                validated_counts[
                    "mastery_records"
                ]
            ),
            "mastery_records_to_create": (
                mastery_records_to_create
            ),
            "warning_count": len(
                warnings
            ),
        }

        if (
            summary["persons_in_file"]
            != summary["persons_to_create"]
        ):
            raise JsonImportPlanError(
                "The import plan person count is inconsistent."
            )

        if (
            summary["riot_accounts_in_file"]
            != summary[
                "riot_accounts_to_create"
            ]
        ):
            raise JsonImportPlanError(
                "The import plan Riot account count is "
                "inconsistent."
            )

        if (
            summary["champions_in_file"]
            != (
                summary["champions_to_create"]
                + summary["champions_to_reuse"]
            )
        ):
            raise JsonImportPlanError(
                "The import plan champion count is inconsistent."
            )

        if (
            summary["mastery_records_in_file"]
            != summary[
                "mastery_records_to_create"
            ]
        ):
            raise JsonImportPlanError(
                "The import plan mastery count is inconsistent."
            )

        return summary

    @classmethod
    def _validate_plan_summary(
        cls,
        plan,
    ):
        summary = plan[
            "summary"
        ]

        champions = plan[
            "champions"
        ]

        persons = plan[
            "persons"
        ]

        warnings = plan[
            "warnings"
        ]

        if not isinstance(
            summary,
            Mapping,
        ):
            raise JsonImportPlanError(
                "The import plan summary is invalid."
            )

        if not isinstance(
            champions,
            list,
        ):
            raise JsonImportPlanError(
                "The import plan champion actions are invalid."
            )

        if not isinstance(
            persons,
            list,
        ):
            raise JsonImportPlanError(
                "The import plan person actions are invalid."
            )

        if not isinstance(
            warnings,
            list,
        ):
            raise JsonImportPlanError(
                "The import plan warnings are invalid."
            )

        expected_champions_to_create = sum(
            1
            for champion in champions
            if champion.get(
                "action"
            ) == "create"
        )

        expected_champions_to_reuse = sum(
            1
            for champion in champions
            if champion.get(
                "action"
            ) == "reuse"
        )

        expected_accounts_to_create = sum(
            len(
                person.get(
                    "riot_accounts",
                    [],
                )
            )
            for person in persons
        )

        expected_mastery_to_create = sum(
            len(
                account.get(
                    "champion_mastery",
                    [],
                )
            )
            for person in persons
            for account in person.get(
                "riot_accounts",
                [],
            )
        )

        expected_values = {
            "persons_to_create": len(
                persons
            ),
            "riot_accounts_to_create": (
                expected_accounts_to_create
            ),
            "champions_to_create": (
                expected_champions_to_create
            ),
            "champions_to_reuse": (
                expected_champions_to_reuse
            ),
            "mastery_records_to_create": (
                expected_mastery_to_create
            ),
            "warning_count": len(
                warnings
            ),
        }

        for key, expected_value in (
            expected_values.items()
        ):
            if summary.get(
                key
            ) != expected_value:
                raise JsonImportPlanError(
                    "The import plan summary is inconsistent "
                    f"for {key}."
                )

    @classmethod
    def _calculate_payload_sha256(
        cls,
        payload,
    ):
        try:
            canonical_json = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
                allow_nan=False,
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise JsonImportPlanError(
                "The import plan could not be serialized "
                "deterministically."
            ) from error

        return hashlib.sha256(
            canonical_json.encode(
                "utf-8"
            )
        ).hexdigest()

    @classmethod
    def _deep_freeze(
        cls,
        value,
    ):
        if isinstance(
            value,
            Mapping,
        ):
            return MappingProxyType(
                {
                    key: cls._deep_freeze(
                        nested_value
                    )
                    for key, nested_value
                    in value.items()
                }
            )

        if isinstance(
            value,
            (
                list,
                tuple,
            ),
        ):
            return tuple(
                cls._deep_freeze(
                    nested_value
                )
                for nested_value in value
            )

        return value

    @classmethod
    def _to_plain_value(
        cls,
        value,
    ):
        if isinstance(
            value,
            Mapping,
        ):
            return {
                key: cls._to_plain_value(
                    nested_value
                )
                for key, nested_value
                in value.items()
            }

        if isinstance(
            value,
            (
                list,
                tuple,
            ),
        ):
            return [
                cls._to_plain_value(
                    nested_value
                )
                for nested_value in value
            ]

        return value

    @staticmethod
    def _is_valid_sha256(
        value,
    ):
        return (
            isinstance(
                value,
                str,
            )
            and len(
                value
            ) == 64
            and all(
                character
                in "0123456789abcdef"
                for character in value
            )
        )