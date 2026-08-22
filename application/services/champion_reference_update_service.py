from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from application.services.champion_reference_dataset_build_service import (
    ChampionReferenceDatasetBuildService,
)
from application.services.champion_reference_merge_service import (
    ChampionReferenceMergeService,
)
from application.services.champion_reference_source_service import (
    ChampionReferenceSourceService,
)
from application.services.data_dragon_service import (
    DataDragonService,
)


class ChampionReferenceUpdateError(
    RuntimeError
):
    """
    Raised when a manual champion reference update cannot be
    checked, downloaded, built, merged, or installed safely.
    """


class ChampionReferenceUpdateService:
    """
    Performs an explicit manual champion reference update.

    Network access occurs only when update_reference_data() is
    explicitly invoked. A successfully built local cache is merged
    into the existing database without replacing champion rows or
    their mastery relationships.
    """

    def __init__(
        self,
        data_dragon_service=None,
        build_service=None,
        source_service=None,
        merge_service=None,
        local_cache_directory=None,
    ):
        self.data_dragon_service = (
            data_dragon_service
            or DataDragonService()
        )

        self.build_service = (
            build_service
            or ChampionReferenceDatasetBuildService()
        )

        self.source_service = (
            source_service
            or ChampionReferenceSourceService()
        )

        self.merge_service = (
            merge_service
            or ChampionReferenceMergeService()
        )

        self.local_cache_directory = (
            local_cache_directory
        )

    def update_reference_data(
        self,
        force=False,
    ):
        """
        Check Data Dragon and install a newer local dataset.

        An equal version is downloaded only when force=True.
        An older remote version never replaces newer local data.
        A successfully built dataset is merged into the database
        before the update result is returned.
        """

        try:
            selected_source = (
                self.source_service.select_source()
            )

            current_version = (
                self._get_current_version(
                    selected_source
                )
            )

            latest_version = (
                self._normalize_version(
                    self.data_dragon_service
                    .get_latest_version()
                )
            )

            should_update = (
                self._should_update(
                    current_version=(
                        current_version
                    ),
                    latest_version=(
                        latest_version
                    ),
                    force=force,
                )
            )

            if not should_update:
                return {
                    "status": "current",
                    "updated": False,
                    "forced": bool(
                        force
                    ),
                    "previous_version": (
                        current_version
                    ),
                    "data_dragon_version": (
                        current_version
                    ),
                    "active_source": (
                        selected_source.get(
                            "active_source"
                        )
                    ),
                    "dataset": None,
                    "merge": None,
                }

            champion_data = (
                self.data_dragon_service
                .download_champion_data(
                    latest_version
                )
            )

            generated_at = datetime.now(
                timezone.utc
            )

            build_result = (
                self.build_service
                .build_dataset(
                    champion_data=(
                        champion_data
                    ),
                    data_dragon_version=(
                        latest_version
                    ),
                    output_directory=(
                        self
                        ._get_local_cache_directory()
                    ),
                    generated_at=(
                        generated_at
                    ),
                )
            )

            if not isinstance(
                build_result,
                dict,
            ):
                raise ChampionReferenceUpdateError(
                    "The champion reference dataset "
                    "builder returned an invalid result."
                )

            merge_result = (
                self.merge_service.merge_dataset(
                    dataset=build_result,
                    active_source="local_cache",
                )
            )

            if not isinstance(
                merge_result,
                dict,
            ):
                raise ChampionReferenceUpdateError(
                    "The champion reference database "
                    "merge returned an invalid result."
                )

            return {
                "status": "updated",
                "updated": True,
                "forced": bool(
                    force
                ),
                "previous_version": (
                    current_version
                ),
                "data_dragon_version": (
                    latest_version
                ),
                "active_source": (
                    "local_cache"
                ),
                "dataset": build_result,
                "merge": merge_result,
            }

        except ChampionReferenceUpdateError:
            raise

        except Exception as error:
            raise ChampionReferenceUpdateError(
                "Champion reference data could not "
                "be updated safely."
            ) from error

    def _get_current_version(
        self,
        selected_source,
    ):
        """
        Read and validate the active local reference version.
        """

        if not isinstance(
            selected_source,
            dict,
        ):
            raise ChampionReferenceUpdateError(
                "The active champion reference "
                "source is invalid."
            )

        current_version = (
            selected_source.get(
                "data_dragon_version"
            )
        )

        if current_version is None:
            return None

        return self._normalize_version(
            current_version
        )

    def _should_update(
        self,
        current_version,
        latest_version,
        force,
    ):
        """
        Decide whether the remote dataset should be downloaded.
        """

        if current_version is None:
            return True

        current_version_tuple = (
            self._parse_version(
                current_version
            )
        )

        latest_version_tuple = (
            self._parse_version(
                latest_version
            )
        )

        if latest_version_tuple > current_version_tuple:
            return True

        if (
            force
            and latest_version_tuple
            == current_version_tuple
        ):
            return True

        return False

    def _get_local_cache_directory(
        self,
    ):
        """
        Resolve the mutable per-user champion reference cache.
        """

        if (
            self.local_cache_directory
            is not None
        ):
            return Path(
                self.local_cache_directory
            )

        reference_directory = Path(
            current_app.config[
                "REFERENCE_DIR"
            ]
        )

        return (
            reference_directory
            / "data_dragon"
        )

    @classmethod
    def _normalize_version(
        cls,
        version,
    ):
        """
        Validate and normalize a dotted numeric version string.
        """

        if not isinstance(
            version,
            str,
        ):
            raise ChampionReferenceUpdateError(
                "The Data Dragon version is invalid."
            )

        normalized_version = (
            version.strip()
        )

        cls._parse_version(
            normalized_version
        )

        return normalized_version

    @staticmethod
    def _parse_version(
        version,
    ):
        """
        Convert a dotted numeric version to a comparable tuple.
        """

        if not isinstance(
            version,
            str,
        ):
            raise ChampionReferenceUpdateError(
                "The Data Dragon version is invalid."
            )

        version_parts = (
            version.split(
                "."
            )
        )

        if (
            len(version_parts) < 2
            or any(
                not part.isdigit()
                for part in version_parts
            )
        ):
            raise ChampionReferenceUpdateError(
                "The Data Dragon version is invalid."
            )

        return tuple(
            int(
                part
            )
            for part in version_parts
        )