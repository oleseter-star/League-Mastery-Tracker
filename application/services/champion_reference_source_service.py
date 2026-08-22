from pathlib import Path

from flask import current_app

from application.services.champion_reference_dataset_service import (
    ChampionReferenceDatasetError,
    ChampionReferenceDatasetService,
)
from application.services.champion_reference_resource_service import (
    ChampionReferenceResourceService,
)


class ChampionReferenceSourceService:
    """
    Selects the best available validated champion reference source.

    A newer valid local cache takes priority over the bundled
    dataset. Equal or older cache versions do not replace bundled
    data. If neither file source is valid, the existing database is
    used without a reference-data merge.
    """

    BUNDLED_WARNING = (
        "The bundled champion reference "
        "dataset is unavailable or invalid."
    )

    LOCAL_CACHE_WARNING = (
        "The local champion reference "
        "cache is unavailable or invalid."
    )

    def __init__(
        self,
        dataset_service=None,
        bundled_dataset_directory=None,
        local_cache_directory=None,
    ):
        self.dataset_service = (
            dataset_service
            or ChampionReferenceDatasetService()
        )

        self.bundled_dataset_directory = (
            bundled_dataset_directory
        )

        self.local_cache_directory = (
            local_cache_directory
        )

    def select_source(
        self,
    ):
        """
        Validate both file sources and select the active dataset.
        """

        warnings = []

        bundled_directory = (
            self._get_bundled_dataset_directory()
        )

        local_cache_directory = (
            self._get_local_cache_directory()
        )

        bundled_dataset = self._load_dataset(
            dataset_directory=(
                bundled_directory
            ),
            warning_message=(
                self.BUNDLED_WARNING
            ),
            warnings=warnings,
        )

        local_cache_dataset = (
            self._load_dataset(
                dataset_directory=(
                    local_cache_directory
                ),
                warning_message=(
                    self.LOCAL_CACHE_WARNING
                ),
                warnings=warnings,
            )
        )

        selected_source = (
            self._select_valid_dataset(
                bundled_dataset=(
                    bundled_dataset
                ),
                local_cache_dataset=(
                    local_cache_dataset
                ),
            )
        )

        if selected_source is None:
            return {
                "active_source": "database",
                "dataset": None,
                "data_dragon_version": None,
                "locale": None,
                "dataset_directory": None,
                "icons_directory": None,
                "warnings": warnings,
            }

        active_source = selected_source[
            "active_source"
        ]

        dataset = selected_source[
            "dataset"
        ]

        manifest = dataset[
            "manifest"
        ]

        return {
            "active_source": active_source,
            "dataset": dataset,
            "data_dragon_version": (
                manifest[
                    "data_dragon_version"
                ]
            ),
            "locale": manifest[
                "locale"
            ],
            "dataset_directory": (
                Path(
                    dataset[
                        "dataset_directory"
                    ]
                ).resolve()
            ),
            "icons_directory": (
                Path(
                    dataset[
                        "icons_directory"
                    ]
                ).resolve()
            ),
            "warnings": warnings,
        }

    def _load_dataset(
        self,
        dataset_directory,
        warning_message,
        warnings,
    ):
        """
        Load one source or record a controlled validation warning.
        """

        try:
            dataset = (
                self.dataset_service
                .load_dataset(
                    dataset_directory
                )
            )

            self._get_dataset_version(
                dataset
            )

            return dataset

        except (
            ChampionReferenceDatasetError,
            KeyError,
            TypeError,
            ValueError,
        ):
            warnings.append(
                warning_message
            )

            return None

    def _select_valid_dataset(
        self,
        bundled_dataset,
        local_cache_dataset,
    ):
        """
        Apply deterministic source-priority rules.
        """

        if (
            bundled_dataset is None
            and local_cache_dataset is None
        ):
            return None

        if bundled_dataset is None:
            return {
                "active_source": (
                    "local_cache"
                ),
                "dataset": (
                    local_cache_dataset
                ),
            }

        if local_cache_dataset is None:
            return {
                "active_source": "bundled",
                "dataset": bundled_dataset,
            }

        bundled_version = (
            self._get_dataset_version(
                bundled_dataset
            )
        )

        local_cache_version = (
            self._get_dataset_version(
                local_cache_dataset
            )
        )

        if (
            local_cache_version
            > bundled_version
        ):
            return {
                "active_source": (
                    "local_cache"
                ),
                "dataset": (
                    local_cache_dataset
                ),
            }

        return {
            "active_source": "bundled",
            "dataset": bundled_dataset,
        }

    def _get_bundled_dataset_directory(
        self,
    ):
        """
        Resolve the immutable bundled dataset directory.
        """

        if (
            self.bundled_dataset_directory
            is not None
        ):
            return Path(
                self.bundled_dataset_directory
            )

        return (
            ChampionReferenceResourceService
            .get_dataset_directory()
        )

    def _get_local_cache_directory(
        self,
    ):
        """
        Resolve the mutable per-user reference cache directory.
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
    def _get_dataset_version(
        cls,
        dataset,
    ):
        """
        Return a numerically comparable Data Dragon version tuple.
        """

        if not isinstance(
            dataset,
            dict,
        ):
            raise ValueError(
                "The champion reference "
                "dataset is invalid."
            )

        manifest = dataset.get(
            "manifest"
        )

        if not isinstance(
            manifest,
            dict,
        ):
            raise ValueError(
                "The champion reference "
                "manifest is invalid."
            )

        version = manifest.get(
            "data_dragon_version"
        )

        return cls._parse_version(
            version
        )

    @staticmethod
    def _parse_version(
        version,
    ):
        """
        Parse a dotted numeric Data Dragon version.
        """

        if not isinstance(
            version,
            str,
        ):
            raise ValueError(
                "The Data Dragon version "
                "is invalid."
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
            raise ValueError(
                "The Data Dragon version "
                "is invalid."
            )

        return tuple(
            int(
                part
            )
            for part in version_parts
        )