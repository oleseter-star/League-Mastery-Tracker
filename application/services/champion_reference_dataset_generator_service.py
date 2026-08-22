import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


class ChampionReferenceDatasetGeneratorError(
    ValueError
):
    """
    Raised when Data Dragon data cannot be converted into a valid,
    deterministic local champion reference dataset.
    """


class ChampionReferenceDatasetGeneratorService:
    """
    Generates manifest.json and champions.json from Data Dragon.

    The generated champion collection is normalized and sorted by
    Riot champion ID. Files are written through temporary files
    before replacing any existing generated files.
    """

    FORMAT_NAME = (
        "league_mastery_tracker_"
        "champion_reference"
    )

    FORMAT_VERSION = 1
    LOCALE = "en_US"
    SOURCE = "riot_data_dragon"

    MANIFEST_FILE_NAME = "manifest.json"
    CHAMPIONS_FILE_NAME = "champions.json"
    ICONS_DIRECTORY_NAME = "champion_icons"

    VERSION_PATTERN = re.compile(
        r"^\d+(?:\.\d+)+$"
    )

    IMAGE_FILENAME_PATTERN = re.compile(
        r"^[A-Za-z0-9_.-]+\.png$"
    )

    def generate_dataset(
        self,
        champion_data,
        data_dragon_version,
        output_directory,
        generated_at,
    ):
        """
        Generate one deterministic champion reference dataset.

        Champion icons are not downloaded by this method. The icon
        directory is created so a separate controlled step can place
        the matching Data Dragon assets there.
        """

        normalized_version = (
            self._normalize_version(
                data_dragon_version
            )
        )

        normalized_generated_at = (
            self._normalize_generated_at(
                generated_at
            )
        )

        champions = (
            self._normalize_champions(
                champion_data
            )
        )

        resolved_output_directory = (
            self._resolve_output_directory(
                output_directory
            )
        )

        icons_directory = (
            resolved_output_directory
            / self.ICONS_DIRECTORY_NAME
        )

        champions_file = (
            resolved_output_directory
            / self.CHAMPIONS_FILE_NAME
        )

        manifest_file = (
            resolved_output_directory
            / self.MANIFEST_FILE_NAME
        )

        champions_temp_file = (
            resolved_output_directory
            / (
                f"{self.CHAMPIONS_FILE_NAME}"
                ".tmp"
            )
        )

        manifest_temp_file = (
            resolved_output_directory
            / (
                f"{self.MANIFEST_FILE_NAME}"
                ".tmp"
            )
        )

        champions_document = {
            "champions": champions,
        }

        champion_bytes = (
            self._encode_json(
                champions_document
            )
        )

        manifest = {
            "format": self.FORMAT_NAME,
            "format_version": (
                self.FORMAT_VERSION
            ),
            "data_dragon_version": (
                normalized_version
            ),
            "locale": self.LOCALE,
            "champion_count": len(
                champions
            ),
            "source": self.SOURCE,
            "generated_at": (
                normalized_generated_at
            ),
            "champions_sha256": (
                hashlib.sha256(
                    champion_bytes
                ).hexdigest()
            ),
        }

        manifest_bytes = (
            self._encode_json(
                manifest
            )
        )

        try:
            resolved_output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            icons_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            champions_temp_file.write_bytes(
                champion_bytes
            )

            manifest_temp_file.write_bytes(
                manifest_bytes
            )

            champions_temp_file.replace(
                champions_file
            )

            manifest_temp_file.replace(
                manifest_file
            )

        except OSError as error:
            self._delete_if_exists(
                champions_temp_file
            )

            self._delete_if_exists(
                manifest_temp_file
            )

            raise (
                ChampionReferenceDatasetGeneratorError(
                    "The champion reference dataset could "
                    "not be written safely."
                )
            ) from error

        return {
            "manifest": manifest,
            "champions": champions,
            "manifest_file": (
                manifest_file.resolve()
            ),
            "champions_file": (
                champions_file.resolve()
            ),
            "icons_directory": (
                icons_directory.resolve()
            ),
            "output_directory": (
                resolved_output_directory
            ),
        }

    def _normalize_champions(
        self,
        champion_data,
    ):
        """
        Validate and normalize the complete Data Dragon collection.
        """

        if not isinstance(
            champion_data,
            dict,
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "Data Dragon champion data must contain "
                    "a JSON object."
                )
            )

        data_collection = (
            champion_data.get(
                "data"
            )
        )

        if (
            not isinstance(
                data_collection,
                dict,
            )
            or not data_collection
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "Data Dragon champion data is missing "
                    "a non-empty data collection."
                )
            )

        normalized_champions = []
        seen_champion_ids = set()

        for champion_entry in (
            data_collection.values()
        ):
            normalized_champion = (
                self._normalize_champion_entry(
                    champion_entry
                )
            )

            champion_id = (
                normalized_champion[
                    "riot_champion_id"
                ]
            )

            if champion_id in seen_champion_ids:
                raise (
                    ChampionReferenceDatasetGeneratorError(
                        "Data Dragon champion data contains "
                        "a duplicate Riot champion ID."
                    )
                )

            seen_champion_ids.add(
                champion_id
            )

            normalized_champions.append(
                normalized_champion
            )

        normalized_champions.sort(
            key=lambda champion: (
                champion[
                    "riot_champion_id"
                ]
            )
        )

        return normalized_champions

    def _normalize_champion_entry(
        self,
        champion_entry,
    ):
        """
        Validate and normalize one Data Dragon champion entry.
        """

        if not isinstance(
            champion_entry,
            dict,
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "Data Dragon champion data contains "
                    "an invalid champion entry."
                )
            )

        raw_champion_id = (
            champion_entry.get(
                "key"
            )
        )

        try:
            champion_id = int(
                raw_champion_id
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "Data Dragon champion data contains "
                    "an invalid Riot champion ID."
                )
            ) from error

        if champion_id <= 0:
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "Data Dragon champion data contains "
                    "an invalid Riot champion ID."
                )
            )

        raw_name = champion_entry.get(
            "name"
        )

        if not isinstance(
            raw_name,
            str,
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    f"Champion {champion_id} is missing "
                    "a valid name."
                )
            )

        name = raw_name.strip()

        if not name:
            raise (
                ChampionReferenceDatasetGeneratorError(
                    f"Champion {champion_id} is missing "
                    "a valid name."
                )
            )

        image_data = champion_entry.get(
            "image"
        )

        if not isinstance(
            image_data,
            dict,
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    f"Champion {champion_id} is missing "
                    "valid image data."
                )
            )

        raw_image_filename = (
            image_data.get(
                "full"
            )
        )

        image_filename = (
            self._normalize_image_filename(
                champion_id=champion_id,
                image_filename=(
                    raw_image_filename
                ),
            )
        )

        return {
            "riot_champion_id": (
                champion_id
            ),
            "name": name,
            "image_filename": (
                image_filename
            ),
        }

    def _normalize_image_filename(
        self,
        champion_id,
        image_filename,
    ):
        """
        Validate a safe local PNG filename.
        """

        if not isinstance(
            image_filename,
            str,
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    f"Champion {champion_id} contains "
                    "an invalid image filename."
                )
            )

        normalized_filename = (
            image_filename.strip()
        )

        if (
            not normalized_filename
            or Path(
                normalized_filename
            ).name
            != normalized_filename
            or "/"
            in normalized_filename
            or "\\"
            in normalized_filename
            or not self.IMAGE_FILENAME_PATTERN.fullmatch(
                normalized_filename
            )
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    f"Champion {champion_id} contains "
                    "an invalid image filename."
                )
            )

        return normalized_filename

    def _normalize_version(
        self,
        data_dragon_version,
    ):
        """
        Validate a Data Dragon version string.
        """

        normalized_version = str(
            data_dragon_version
            or ""
        ).strip()

        if not self.VERSION_PATTERN.fullmatch(
            normalized_version
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "The Data Dragon version is invalid."
                )
            )

        return normalized_version

    @staticmethod
    def _normalize_generated_at(
        generated_at,
    ):
        """
        Validate and serialize an aware generation timestamp.
        """

        if (
            not isinstance(
                generated_at,
                datetime,
            )
            or generated_at.tzinfo
            is None
            or generated_at.utcoffset()
            is None
        ):
            raise (
                ChampionReferenceDatasetGeneratorError(
                    "The dataset generation timestamp "
                    "must include timezone information."
                )
            )

        return generated_at.isoformat()

    @staticmethod
    def _resolve_output_directory(
        output_directory,
    ):
        """
        Resolve the requested dataset output directory.
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
                ChampionReferenceDatasetGeneratorError(
                    "The dataset output directory "
                    "is invalid."
                )
            ) from error

    @staticmethod
    def _encode_json(
        value,
    ):
        """
        Encode deterministic UTF-8 JSON.
        """

        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode(
            "utf-8"
        )

    @staticmethod
    def _delete_if_exists(
        file_path,
    ):
        """
        Best-effort removal of a temporary file.
        """

        try:
            file_path.unlink(
                missing_ok=True
            )

        except OSError:
            pass