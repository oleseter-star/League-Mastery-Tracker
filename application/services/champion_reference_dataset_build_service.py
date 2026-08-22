import shutil
from pathlib import Path

from application.services.champion_reference_dataset_generator_service import (
    ChampionReferenceDatasetGeneratorService,
)
from application.services.champion_reference_dataset_service import (
    ChampionReferenceDatasetService,
)
from application.services.champion_reference_icon_download_service import (
    ChampionReferenceIconDownloadService,
)


class ChampionReferenceDatasetBuildError(
    RuntimeError
):
    """
    Raised when a complete champion reference dataset cannot be
    generated, validated, or installed transactionally.
    """


class ChampionReferenceDatasetBuildService:
    """
    Builds and installs a complete champion reference dataset.

    Generation, icon download, and initial validation happen in a
    staging directory. An existing dataset is replaced only after
    the complete staging dataset has passed validation.
    """

    TEMPORARY_SUFFIX = ".tmp"
    PREVIOUS_SUFFIX = ".previous"

    def __init__(
        self,
        generator_service=None,
        icon_download_service=None,
        dataset_service=None,
    ):
        self.generator_service = (
            generator_service
            or ChampionReferenceDatasetGeneratorService()
        )

        self.icon_download_service = (
            icon_download_service
            or ChampionReferenceIconDownloadService()
        )

        self.dataset_service = (
            dataset_service
            or ChampionReferenceDatasetService()
        )

    def build_dataset(
        self,
        champion_data,
        data_dragon_version,
        output_directory,
        generated_at,
    ):
        """
        Build, validate, and transactionally install one dataset.
        """

        resolved_output_directory = (
            self._resolve_output_directory(
                output_directory
            )
        )

        staging_directory = (
            resolved_output_directory.parent
            / (
                resolved_output_directory.name
                + self.TEMPORARY_SUFFIX
            )
        )

        previous_directory = (
            resolved_output_directory.parent
            / (
                resolved_output_directory.name
                + self.PREVIOUS_SUFFIX
            )
        )

        existing_dataset_moved = False
        staging_dataset_installed = False

        try:
            self._recover_interrupted_dataset(
                output_directory=(
                    resolved_output_directory
                ),
                previous_directory=(
                    previous_directory
                ),
            )

            self._remove_directory(
                staging_directory
            )

            generated_result = (
                self.generator_service.generate_dataset(
                    champion_data=champion_data,
                    data_dragon_version=(
                        data_dragon_version
                    ),
                    output_directory=(
                        staging_directory
                    ),
                    generated_at=generated_at,
                )
            )

            if not isinstance(
                generated_result,
                dict,
            ):
                raise ChampionReferenceDatasetBuildError(
                    "The dataset generator returned an "
                    "invalid result."
                )

            champions = generated_result.get(
                "champions"
            )

            self.icon_download_service.download_icons(
                champions=champions,
                data_dragon_version=(
                    data_dragon_version
                ),
                output_directory=(
                    staging_directory
                ),
            )

            self.dataset_service.load_dataset(
                staging_directory
            )

            if resolved_output_directory.exists():
                self._remove_directory(
                    previous_directory
                )

                resolved_output_directory.replace(
                    previous_directory
                )

                existing_dataset_moved = True

            staging_directory.replace(
                resolved_output_directory
            )

            staging_dataset_installed = True

            final_dataset = (
                self.dataset_service.load_dataset(
                    resolved_output_directory
                )
            )

            self._remove_directory(
                previous_directory
            )

            existing_dataset_moved = False

            return final_dataset

        except Exception as error:
            self._restore_previous_dataset(
                output_directory=(
                    resolved_output_directory
                ),
                previous_directory=(
                    previous_directory
                ),
                existing_dataset_moved=(
                    existing_dataset_moved
                ),
                staging_dataset_installed=(
                    staging_dataset_installed
                ),
            )

            self._remove_directory(
                staging_directory
            )

            if (
                previous_directory.exists()
                and resolved_output_directory.exists()
            ):
                self._remove_directory(
                    previous_directory
                )

            if isinstance(
                error,
                ChampionReferenceDatasetBuildError,
            ):
                raise

            raise ChampionReferenceDatasetBuildError(
                "The champion reference dataset could not "
                "be built and installed safely."
            ) from error

        finally:
            self._remove_directory(
                staging_directory
            )

            if (
                previous_directory.exists()
                and resolved_output_directory.exists()
            ):
                self._remove_directory(
                    previous_directory
                )

    @classmethod
    def _recover_interrupted_dataset(
        cls,
        output_directory,
        previous_directory,
    ):
        """
        Recover or discard an interrupted previous-dataset directory.
        """

        if not previous_directory.exists():
            return

        if output_directory.exists():
            cls._remove_directory(
                previous_directory
            )

            return

        previous_directory.replace(
            output_directory
        )

    @classmethod
    def _restore_previous_dataset(
        cls,
        output_directory,
        previous_directory,
        existing_dataset_moved,
        staging_dataset_installed,
    ):
        """
        Restore the previous dataset after a failed installation.
        """

        if staging_dataset_installed:
            cls._remove_directory(
                output_directory
            )

        if (
            existing_dataset_moved
            and previous_directory.exists()
            and not output_directory.exists()
        ):
            previous_directory.replace(
                output_directory
            )

    @staticmethod
    def _resolve_output_directory(
        output_directory,
    ):
        """
        Resolve the final dataset directory.
        """

        try:
            return Path(
                output_directory
            ).resolve()

        except (
            TypeError,
            OSError,
        ) as error:
            raise ChampionReferenceDatasetBuildError(
                "The dataset output directory is invalid."
            ) from error

    @staticmethod
    def _remove_directory(
        directory,
    ):
        """
        Remove a directory tree if it exists.
        """

        if directory.exists():
            shutil.rmtree(
                directory
            )