from flask import current_app

from application.database.models import Champion


class ChampionReferenceStatusService:
    """
    Builds a safe, user-facing status summary for champion
    reference data.

    Internal dataset paths are deliberately excluded.
    """

    ACTIVE_SOURCE_LABELS = {
        "bundled": "Bundled dataset",
        "local_cache": "Local cache",
        "database": "Database-only fallback",
        "database_only": "Database-only fallback",
    }

    def get_status(
        self,
    ):
        """
        Return current champion reference and metadata status.
        """

        startup_result = (
            current_app.config.get(
                "STARTUP_CHAMPION_REFERENCE_RESULT"
            )
        )

        normalized_startup = (
            self._normalize_startup_result(
                startup_result
            )
        )

        champions = (
            Champion.query.all()
        )

        metadata_counts = (
            self._count_missing_metadata(
                champions
            )
        )

        manual_update_timestamp = (
            current_app.config.get(
                "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
            )
        )

        last_successful_update = (
            manual_update_timestamp
            or normalized_startup[
                "generated_at"
            ]
        )

        last_update_error = (
            current_app.config.get(
                "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
            )
        )

        active_source = (
            normalized_startup[
                "active_source"
            ]
        )

        return {
            "active_source": active_source,
            "active_source_label": (
                self.ACTIVE_SOURCE_LABELS[
                    active_source
                ]
            ),
            "reference_data_available": (
                normalized_startup[
                    "reference_data_available"
                ]
            ),
            "uses_bundled_fallback": (
                active_source
                == "bundled"
            ),
            "uses_local_cache": (
                active_source
                == "local_cache"
            ),
            "database_only": (
                active_source
                == "database_only"
            ),
            "data_dragon_version": (
                normalized_startup[
                    "data_dragon_version"
                ]
            ),
            "locale": (
                normalized_startup[
                    "locale"
                ]
            ),
            "dataset_champion_count": (
                normalized_startup[
                    "dataset_champion_count"
                ]
            ),
            "database_champion_count": len(
                champions
            ),
            "missing_name_count": (
                metadata_counts[
                    "missing_name_count"
                ]
            ),
            "missing_image_count": (
                metadata_counts[
                    "missing_image_count"
                ]
            ),
            "missing_metadata_count": (
                metadata_counts[
                    "missing_metadata_count"
                ]
            ),
            "has_missing_metadata": (
                metadata_counts[
                    "missing_metadata_count"
                ]
                > 0
            ),
            "last_successful_update": (
                last_successful_update
            ),
            "last_update_error": (
                last_update_error
            ),
            "warnings": (
                normalized_startup[
                    "warnings"
                ]
            ),
        }

    def _normalize_startup_result(
        self,
        startup_result,
    ):
        """
        Normalize the stored startup result into safe status data.
        """

        if not isinstance(
            startup_result,
            dict,
        ):
            return self._build_database_only_status()

        raw_active_source = (
            startup_result.get(
                "active_source"
            )
        )

        reference_data_available = bool(
            startup_result.get(
                "reference_data_available",
                False,
            )
        )

        database_fallback = bool(
            startup_result.get(
                "database_fallback",
                False,
            )
        )

        if (
            raw_active_source
            in {
                "bundled",
                "local_cache",
            }
            and reference_data_available
            and not database_fallback
        ):
            active_source = (
                raw_active_source
            )

        else:
            active_source = (
                "database_only"
            )

        merge_result = (
            startup_result.get(
                "merge"
            )
        )

        if (
            active_source
            == "database_only"
            or not isinstance(
                merge_result,
                dict,
            )
        ):
            dataset_champion_count = None

        else:
            raw_dataset_count = (
                merge_result.get(
                    "dataset_count"
                )
            )

            if (
                isinstance(
                    raw_dataset_count,
                    bool,
                )
                or not isinstance(
                    raw_dataset_count,
                    int,
                )
                or raw_dataset_count < 0
            ):
                dataset_champion_count = None

            else:
                dataset_champion_count = (
                    raw_dataset_count
                )

        warnings = (
            self._normalize_warnings(
                startup_result.get(
                    "warnings"
                )
            )
        )

        if active_source == "database_only":
            data_dragon_version = None
            locale = None
            generated_at = None
            reference_data_available = False

        else:
            data_dragon_version = (
                self._normalize_optional_text(
                    startup_result.get(
                        "data_dragon_version"
                    )
                )
            )

            locale = (
                self._normalize_optional_text(
                    startup_result.get(
                        "locale"
                    )
                )
            )

            generated_at = (
                self._normalize_optional_text(
                    startup_result.get(
                        "generated_at"
                    )
                )
            )

        return {
            "active_source": (
                active_source
            ),
            "reference_data_available": (
                reference_data_available
            ),
            "data_dragon_version": (
                data_dragon_version
            ),
            "locale": locale,
            "dataset_champion_count": (
                dataset_champion_count
            ),
            "generated_at": (
                generated_at
            ),
            "warnings": warnings,
        }

    @staticmethod
    def _count_missing_metadata(
        champions,
    ):
        """
        Count missing names, images, and their combined union.
        """

        missing_name_count = 0
        missing_image_count = 0
        missing_metadata_count = 0

        for champion in champions:
            name_missing = (
                not isinstance(
                    champion.name,
                    str,
                )
                or not champion.name.strip()
            )

            image_missing = (
                not isinstance(
                    champion.image,
                    str,
                )
                or not champion.image.strip()
            )

            if name_missing:
                missing_name_count += 1

            if image_missing:
                missing_image_count += 1

            if (
                name_missing
                or image_missing
            ):
                missing_metadata_count += 1

        return {
            "missing_name_count": (
                missing_name_count
            ),
            "missing_image_count": (
                missing_image_count
            ),
            "missing_metadata_count": (
                missing_metadata_count
            ),
        }

    @staticmethod
    def _normalize_warnings(
        warnings,
    ):
        """
        Return only non-empty controlled warning strings.
        """

        if not isinstance(
            warnings,
            list,
        ):
            return []

        return [
            warning.strip()
            for warning in warnings
            if (
                isinstance(
                    warning,
                    str,
                )
                and warning.strip()
            )
        ]

    @staticmethod
    def _normalize_optional_text(
        value,
    ):
        """
        Normalize optional user-facing text.
        """

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            return None

        return value.strip()

    @staticmethod
    def _build_database_only_status():
        """
        Return safe defaults when no valid startup result exists.
        """

        return {
            "active_source": (
                "database_only"
            ),
            "reference_data_available": (
                False
            ),
            "data_dragon_version": None,
            "locale": None,
            "dataset_champion_count": None,
            "generated_at": None,
            "warnings": [],
        }