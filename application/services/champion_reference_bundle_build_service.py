from datetime import datetime, timezone
from pathlib import Path

from application.services.champion_reference_dataset_build_service import (
    ChampionReferenceDatasetBuildService,
)
from application.services.champion_reference_resource_service import (
    ChampionReferenceResourceService,
)
from application.services.data_dragon_service import (
    DataDragonService,
)


class ChampionReferenceBundleBuildError(
    RuntimeError
):
    """
    Raised when the bundled champion reference dataset cannot be
    downloaded, built, validated, or installed safely.
    """


class ChampionReferenceBundleBuildService:
    """
    Builds the immutable champion reference dataset distributed
    with the application.

    This is an explicit development and packaging operation. It is
    not used during normal application startup and never writes to
    the user's local champion reference data.
    """

    def __init__(
        self,
        data_dragon_service=None,
        dataset_build_service=None,
        resource_service=None,
    ):
        self.data_dragon_service = (
            data_dragon_service
            or DataDragonService()
        )

        self.dataset_build_service = (
            dataset_build_service
            or ChampionReferenceDatasetBuildService()
        )

        self.resource_service = (
            resource_service
            or ChampionReferenceResourceService
        )

    def build_bundled_dataset(
        self,
    ):
        """
        Download the latest Data Dragon data and build the complete
        bundled champion reference dataset.
        """

        try:
            latest_version = (
                self._normalize_version(
                    self.data_dragon_service
                    .get_latest_version()
                )
            )

            champion_data = (
                self.data_dragon_service
                .download_champion_data(
                    latest_version
                )
            )

            output_directory = (
                self._resolve_output_directory(
                    self.resource_service
                    .get_dataset_directory()
                )
            )

            generated_at = datetime.now(
                timezone.utc
            )

            build_result = (
                self.dataset_build_service
                .build_dataset(
                    champion_data=(
                        champion_data
                    ),
                    data_dragon_version=(
                        latest_version
                    ),
                    output_directory=(
                        output_directory
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
                raise (
                    ChampionReferenceBundleBuildError(
                        "The bundled champion reference "
                        "builder returned an invalid result."
                    )
                )

            return {
                "status": "built",
                "data_dragon_version": (
                    latest_version
                ),
                "dataset_directory": (
                    output_directory
                ),
                "dataset": build_result,
            }

        except ChampionReferenceBundleBuildError:
            raise

        except Exception as error:
            raise (
                ChampionReferenceBundleBuildError(
                    "The bundled champion reference "
                    "dataset could not be built safely."
                )
            ) from error

    @staticmethod
    def _normalize_version(
        version,
    ):
        """
        Validate and normalize a dotted numeric Data Dragon version.
        """

        if not isinstance(
            version,
            str,
        ):
            raise (
                ChampionReferenceBundleBuildError(
                    "The Data Dragon version is invalid."
                )
            )

        normalized_version = (
            version.strip()
        )

        version_parts = (
            normalized_version.split(
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
            raise (
                ChampionReferenceBundleBuildError(
                    "The Data Dragon version is invalid."
                )
            )

        return normalized_version

    @staticmethod
    def _resolve_output_directory(
        output_directory,
    ):
        """
        Resolve the bundled dataset output directory.
        """

        try:
            return Path(
                output_directory
            ).resolve()

        except (
            TypeError,
            OSError,
        ) as error:
            raise (
                ChampionReferenceBundleBuildError(
                    "The bundled dataset output "
                    "directory is invalid."
                )
            ) from error