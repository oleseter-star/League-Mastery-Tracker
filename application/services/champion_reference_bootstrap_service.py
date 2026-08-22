from application.services.champion_reference_merge_service import (
    ChampionReferenceMergeService,
)
from application.services.champion_reference_source_service import (
    ChampionReferenceSourceService,
)


class ChampionReferenceBootstrapService:
    """
    Initializes local champion reference data during application
    startup without performing any network requests.

    A validated bundled dataset or newer local cache is merged into
    the database. Any source-selection or merge failure falls back
    to the existing database without preventing application startup.
    """

    SUPPORTED_FILE_SOURCES = {
        "bundled",
        "local_cache",
    }

    FALLBACK_WARNING = (
        "Champion reference data could not "
        "be initialized. Existing database "
        "data remains available."
    )

    def __init__(
        self,
        source_service=None,
        merge_service=None,
    ):
        self.source_service = (
            source_service
            or ChampionReferenceSourceService()
        )

        self.merge_service = (
            merge_service
            or ChampionReferenceMergeService()
        )

    def bootstrap(
        self,
    ):
        """
        Select, merge, and report the active champion reference source.

        This method deliberately uses only local services. It does not
        query Data Dragon or invoke any update method.
        """

        try:
            selected_source = (
                self.source_service.select_source()
            )

        except Exception:
            return self._build_database_fallback(
                warnings=[
                    self.FALLBACK_WARNING,
                ]
            )

        if not isinstance(
            selected_source,
            dict,
        ):
            return self._build_database_fallback(
                warnings=[
                    self.FALLBACK_WARNING,
                ]
            )

        warnings = self._normalize_warnings(
            selected_source.get(
                "warnings"
            )
        )

        active_source = selected_source.get(
            "active_source"
        )

        dataset = selected_source.get(
            "dataset"
        )

        if active_source == "database":
            return self._build_database_fallback(
                warnings=warnings,
            )

        if (
            active_source
            not in self.SUPPORTED_FILE_SOURCES
            or not isinstance(
                dataset,
                dict,
            )
        ):
            self._append_warning_once(
                warnings,
                self.FALLBACK_WARNING,
            )

            return self._build_database_fallback(
                warnings=warnings,
            )

        try:
            merge_result = (
                self.merge_service.merge_dataset(
                    dataset=dataset,
                    active_source=active_source,
                )
            )

        except Exception:
            self._append_warning_once(
                warnings,
                self.FALLBACK_WARNING,
            )

            return self._build_database_fallback(
                warnings=warnings,
            )

        return {
            "active_source": active_source,
            "reference_data_available": True,
            "database_fallback": False,
            "data_dragon_version": (
                selected_source.get(
                    "data_dragon_version"
                )
            ),
            "locale": selected_source.get(
                "locale"
            ),
            "dataset_directory": (
                selected_source.get(
                    "dataset_directory"
                )
            ),
            "icons_directory": (
                selected_source.get(
                    "icons_directory"
                )
            ),
            "warnings": warnings,
            "merge": merge_result,
        }

    @staticmethod
    def _build_database_fallback(
        warnings,
    ):
        """
        Return a controlled database-only startup result.
        """

        return {
            "active_source": "database",
            "reference_data_available": False,
            "database_fallback": True,
            "data_dragon_version": None,
            "locale": None,
            "dataset_directory": None,
            "icons_directory": None,
            "warnings": list(
                warnings
            ),
            "merge": None,
        }

    @staticmethod
    def _normalize_warnings(
        warnings,
    ):
        """
        Normalize source warnings into a separate mutable list.
        """

        if not isinstance(
            warnings,
            list,
        ):
            return []

        return [
            warning
            for warning in warnings
            if (
                isinstance(
                    warning,
                    str,
                )
                and warning
            )
        ]

    @staticmethod
    def _append_warning_once(
        warnings,
        warning,
    ):
        """
        Add one warning without creating duplicates.
        """

        if warning not in warnings:
            warnings.append(
                warning
            )