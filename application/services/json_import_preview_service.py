from collections.abc import Mapping

from sqlalchemy.exc import SQLAlchemyError

from application.database.database import db
from application.database.models import (
    Champion,
    Person,
    RiotAccount,
)
from application.services.json_export_validation_service import (
    JsonExportValidationError,
    JsonExportValidationService,
)


class JsonImportPreviewError(RuntimeError):
    """
    Raised when a validated import document cannot be compared
    safely with the current application database.
    """


class JsonImportPreviewService:
    """
    Builds a read-only preview of a validated JSON import.

    The preview does not add, update, delete, merge, or commit any
    database records.

    Existing PUUIDs are deliberately treated as blockers until the
    later merge and conflict-resolution workflow is implemented.
    """

    REQUIRED_READ_RESULT_KEYS = {
        "file_name",
        "file_size_bytes",
        "sha256",
        "document",
    }

    @classmethod
    def build_preview(
        cls,
        import_read_result,
    ):
        """
        Compare one validated import result with the local database.

        Returns a deterministic preview containing:

        - file and format metadata
        - champion reuse and creation information
        - incoming persons and Riot accounts
        - blocking existing-PUUID conflicts
        - non-blocking warnings
        - summary counts

        No database writes are performed.
        """

        cls._validate_import_read_result(
            import_read_result
        )

        document = import_read_result[
            "document"
        ]

        try:
            validated_counts = (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

        except JsonExportValidationError as error:
            raise JsonImportPreviewError(
                "The import document failed validation before "
                "preview generation."
            ) from error

        try:
            local_persons = list(
                db.session.execute(
                    db.select(
                        Person
                    )
                )
                .scalars()
                .all()
            )

            local_accounts = list(
                db.session.execute(
                    db.select(
                        RiotAccount
                    )
                )
                .scalars()
                .all()
            )

            local_champions = list(
                db.session.execute(
                    db.select(
                        Champion
                    )
                )
                .scalars()
                .all()
            )

        except SQLAlchemyError as error:
            raise JsonImportPreviewError(
                "The local database could not be read for import "
                "preview."
            ) from error

        local_person_by_id = {
            person.id: person
            for person in local_persons
        }

        local_persons_by_display_name = {}

        for person in local_persons:
            local_persons_by_display_name.setdefault(
                person.display_name,
                [],
            ).append(
                person
            )

        local_account_by_puuid = {
            account.puuid: account
            for account in local_accounts
        }

        local_champion_by_riot_id = {
            champion.riot_champion_id: champion
            for champion in local_champions
        }

        blockers = []
        warnings = []

        champion_preview = (
            cls._build_champion_preview(
                imported_champions=(
                    document["data"]["champions"]
                ),
                local_champion_by_riot_id=(
                    local_champion_by_riot_id
                ),
                warnings=warnings,
            )
        )

        person_preview = (
            cls._build_person_preview(
                imported_persons=(
                    document["data"]["persons"]
                ),
                local_persons_by_display_name=(
                    local_persons_by_display_name
                ),
                local_account_by_puuid=(
                    local_account_by_puuid
                ),
                local_person_by_id=(
                    local_person_by_id
                ),
                blockers=blockers,
                warnings=warnings,
            )
        )

        summary = cls._build_summary(
            validated_counts=validated_counts,
            champion_preview=champion_preview,
            person_preview=person_preview,
            blockers=blockers,
            warnings=warnings,
        )

        return {
            "file": {
                "file_name": import_read_result[
                    "file_name"
                ],
                "file_size_bytes": import_read_result[
                    "file_size_bytes"
                ],
                "sha256": import_read_result[
                    "sha256"
                ],
            },
            "format": {
                "identifier": document[
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
            "can_import": not blockers,
            "summary": summary,
            "champions": champion_preview,
            "persons": person_preview,
            "blockers": blockers,
            "warnings": warnings,
        }

    @classmethod
    def _build_champion_preview(
        cls,
        imported_champions,
        local_champion_by_riot_id,
        warnings,
    ):
        preview = []

        for champion in imported_champions:
            riot_champion_id = champion[
                "riot_champion_id"
            ]

            local_champion = (
                local_champion_by_riot_id.get(
                    riot_champion_id
                )
            )

            if local_champion is None:
                preview.append(
                    {
                        "riot_champion_id": (
                            riot_champion_id
                        ),
                        "name": champion[
                            "name"
                        ],
                        "image": champion[
                            "image"
                        ],
                        "source": champion[
                            "source"
                        ],
                        "status": "new",
                        "metadata_differs": False,
                    }
                )

                continue

            metadata_differs = (
                cls._champion_metadata_differs(
                    imported_champion=champion,
                    local_champion=local_champion,
                )
            )

            if metadata_differs:
                warnings.append(
                    {
                        "code": (
                            "champion_metadata_differs"
                        ),
                        "message": (
                            "Imported champion metadata differs "
                            "from the existing local champion for "
                            "Riot champion ID "
                            f"{riot_champion_id}. The local "
                            "champion will be reused without being "
                            "overwritten."
                        ),
                        "riot_champion_id": (
                            riot_champion_id
                        ),
                    }
                )

            preview.append(
                {
                    "riot_champion_id": (
                        riot_champion_id
                    ),
                    "name": champion[
                        "name"
                    ],
                    "image": champion[
                        "image"
                    ],
                    "source": champion[
                        "source"
                    ],
                    "status": "existing",
                    "metadata_differs": (
                        metadata_differs
                    ),
                    "local": {
                        "name": local_champion.name,
                        "image": local_champion.image,
                        "source": local_champion.source,
                    },
                }
            )

        return preview

    @classmethod
    def _build_person_preview(
        cls,
        imported_persons,
        local_persons_by_display_name,
        local_account_by_puuid,
        local_person_by_id,
        blockers,
        warnings,
    ):
        preview = []

        for person_index, imported_person in enumerate(
            imported_persons
        ):
            display_name = imported_person[
                "display_name"
            ]

            local_name_matches = (
                local_persons_by_display_name.get(
                    display_name,
                    [],
                )
            )

            person_warnings = []

            if local_name_matches:
                warning = {
                    "code": (
                        "duplicate_display_name"
                    ),
                    "message": (
                        "The imported display name "
                        f'"{display_name}" already exists locally. '
                        "Display names are not stable identities, "
                        "so this does not block the import."
                    ),
                    "person_index": person_index,
                    "display_name": display_name,
                    "local_match_count": len(
                        local_name_matches
                    ),
                }

                warnings.append(
                    warning
                )

                person_warnings.append(
                    warning
                )

            account_preview = []
            person_blocked = False

            for (
                account_index,
                imported_account,
            ) in enumerate(
                imported_person[
                    "riot_accounts"
                ]
            ):
                puuid = imported_account[
                    "puuid"
                ]

                local_account = (
                    local_account_by_puuid.get(
                        puuid
                    )
                )

                mastery_record_count = len(
                    imported_account[
                        "champion_mastery"
                    ]
                )

                if local_account is None:
                    account_preview.append(
                        {
                            "account_index": (
                                account_index
                            ),
                            "game_name": imported_account[
                                "game_name"
                            ],
                            "tag_line": imported_account[
                                "tag_line"
                            ],
                            "puuid": puuid,
                            "platform_region": (
                                imported_account[
                                    "platform_region"
                                ]
                            ),
                            "last_sync": imported_account[
                                "last_sync"
                            ],
                            "mastery_record_count": (
                                mastery_record_count
                            ),
                            "status": "new",
                        }
                    )

                    continue

                person_blocked = True

                local_person = (
                    local_person_by_id.get(
                        local_account.person_id
                    )
                )

                local_person_display_name = None

                if local_person is not None:
                    local_person_display_name = (
                        local_person.display_name
                    )

                blocker = {
                    "code": (
                        "existing_puuid"
                    ),
                    "message": (
                        "The imported Riot account "
                        f'{imported_account["game_name"]}'
                        f'#{imported_account["tag_line"]} '
                        "already exists locally with the same "
                        "PUUID. Automatic merge handling is not "
                        "enabled yet."
                    ),
                    "person_index": person_index,
                    "account_index": account_index,
                    "display_name": display_name,
                    "game_name": imported_account[
                        "game_name"
                    ],
                    "tag_line": imported_account[
                        "tag_line"
                    ],
                    "puuid": puuid,
                    "local_person_display_name": (
                        local_person_display_name
                    ),
                    "local_game_name": (
                        local_account.game_name
                    ),
                    "local_tag_line": (
                        local_account.tag_line
                    ),
                }

                blockers.append(
                    blocker
                )

                account_preview.append(
                    {
                        "account_index": (
                            account_index
                        ),
                        "game_name": imported_account[
                            "game_name"
                        ],
                        "tag_line": imported_account[
                            "tag_line"
                        ],
                        "puuid": puuid,
                        "platform_region": (
                            imported_account[
                                "platform_region"
                            ]
                        ),
                        "last_sync": imported_account[
                            "last_sync"
                        ],
                        "mastery_record_count": (
                            mastery_record_count
                        ),
                        "status": (
                            "blocked_existing_puuid"
                        ),
                        "local": {
                            "person_display_name": (
                                local_person_display_name
                            ),
                            "game_name": (
                                local_account.game_name
                            ),
                            "tag_line": (
                                local_account.tag_line
                            ),
                            "platform_region": (
                                local_account.platform_region
                            ),
                        },
                    }
                )

            preview.append(
                {
                    "person_index": person_index,
                    "display_name": display_name,
                    "status": (
                        "blocked"
                        if person_blocked
                        else "ready"
                    ),
                    "local_display_name_match_count": len(
                        local_name_matches
                    ),
                    "warnings": person_warnings,
                    "riot_accounts": account_preview,
                }
            )

        return preview

    @classmethod
    def _build_summary(
        cls,
        validated_counts,
        champion_preview,
        person_preview,
        blockers,
        warnings,
    ):
        new_champion_count = sum(
            1
            for champion in champion_preview
            if champion["status"] == "new"
        )

        existing_champion_count = sum(
            1
            for champion in champion_preview
            if champion["status"] == "existing"
        )

        champion_metadata_warning_count = sum(
            1
            for champion in champion_preview
            if champion["metadata_differs"]
        )

        ready_person_count = sum(
            1
            for person in person_preview
            if person["status"] == "ready"
        )

        blocked_person_count = sum(
            1
            for person in person_preview
            if person["status"] == "blocked"
        )

        new_account_count = 0
        blocked_account_count = 0
        new_account_mastery_count = 0
        blocked_account_mastery_count = 0

        for person in person_preview:
            for account in person[
                "riot_accounts"
            ]:
                if account["status"] == "new":
                    new_account_count += 1
                    new_account_mastery_count += (
                        account[
                            "mastery_record_count"
                        ]
                    )

                else:
                    blocked_account_count += 1
                    blocked_account_mastery_count += (
                        account[
                            "mastery_record_count"
                        ]
                    )

        duplicate_display_name_warning_count = sum(
            1
            for warning in warnings
            if warning["code"]
            == "duplicate_display_name"
        )

        return {
            "persons_in_file": validated_counts[
                "persons"
            ],
            "ready_persons": ready_person_count,
            "blocked_persons": blocked_person_count,
            "riot_accounts_in_file": validated_counts[
                "riot_accounts"
            ],
            "new_riot_accounts": new_account_count,
            "blocked_riot_accounts": (
                blocked_account_count
            ),
            "champions_in_file": validated_counts[
                "champions"
            ],
            "new_champions": new_champion_count,
            "existing_champions": (
                existing_champion_count
            ),
            "champion_metadata_warnings": (
                champion_metadata_warning_count
            ),
            "mastery_records_in_file": validated_counts[
                "mastery_records"
            ],
            "mastery_records_on_new_accounts": (
                new_account_mastery_count
            ),
            "mastery_records_on_blocked_accounts": (
                blocked_account_mastery_count
            ),
            "duplicate_display_name_warnings": (
                duplicate_display_name_warning_count
            ),
            "blocker_count": len(
                blockers
            ),
            "warning_count": len(
                warnings
            ),
        }

    @staticmethod
    def _champion_metadata_differs(
        imported_champion,
        local_champion,
    ):
        return any(
            (
                imported_champion[
                    field_name
                ]
                != getattr(
                    local_champion,
                    field_name,
                )
            )
            for field_name in (
                "name",
                "image",
                "source",
            )
        )

    @classmethod
    def _validate_import_read_result(
        cls,
        import_read_result,
    ):
        if not isinstance(
            import_read_result,
            Mapping,
        ):
            raise JsonImportPreviewError(
                "The import read result must be a mapping."
            )

        missing_keys = (
            cls.REQUIRED_READ_RESULT_KEYS
            - set(
                import_read_result.keys()
            )
        )

        if missing_keys:
            missing_key_list = ", ".join(
                sorted(
                    missing_keys
                )
            )

            raise JsonImportPreviewError(
                "The import read result is missing required "
                f"fields: {missing_key_list}."
            )

        file_name = import_read_result[
            "file_name"
        ]

        if (
            not isinstance(
                file_name,
                str,
            )
            or not file_name.strip()
        ):
            raise JsonImportPreviewError(
                "The import read result contains an invalid "
                "file name."
            )

        file_size_bytes = import_read_result[
            "file_size_bytes"
        ]

        if (
            isinstance(
                file_size_bytes,
                bool,
            )
            or not isinstance(
                file_size_bytes,
                int,
            )
            or file_size_bytes < 0
        ):
            raise JsonImportPreviewError(
                "The import read result contains an invalid "
                "file size."
            )

        sha256 = import_read_result[
            "sha256"
        ]

        if (
            not isinstance(
                sha256,
                str,
            )
            or len(
                sha256
            ) != 64
            or any(
                character
                not in "0123456789abcdef"
                for character in sha256
            )
        ):
            raise JsonImportPreviewError(
                "The import read result contains an invalid "
                "SHA-256 value."
            )

        if not isinstance(
            import_read_result[
                "document"
            ],
            Mapping,
        ):
            raise JsonImportPreviewError(
                "The import read result contains no valid "
                "document."
            )