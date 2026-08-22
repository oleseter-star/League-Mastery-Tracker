import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


class ChampionReferenceDatasetError(
    ValueError
):
    """
    Raised when a bundled or cached champion reference dataset is
    missing, unreadable, unsupported, incomplete, or invalid.
    """


class ChampionReferenceDatasetService:
    """
    Loads and validates a complete local champion reference dataset.

    The complete manifest, champion collection, checksum, ordering,
    and icon set are validated before any data is returned.
    """

    FORMAT_NAME = (
        "league_mastery_tracker_"
        "champion_reference"
    )

    FORMAT_VERSION = 1
    SUPPORTED_LOCALE = "en_US"
    SUPPORTED_SOURCE = "riot_data_dragon"

    MANIFEST_FILE_NAME = "manifest.json"
    CHAMPIONS_FILE_NAME = "champions.json"
    ICONS_DIRECTORY_NAME = "champion_icons"

    SHA256_PATTERN = re.compile(
        r"^[0-9a-f]{64}$"
    )

    VERSION_PATTERN = re.compile(
        r"^\d+(?:\.\d+)+$"
    )

    IMAGE_FILENAME_PATTERN = re.compile(
        r"^[A-Za-z0-9_.-]+\.png$"
    )

    def load_dataset(
        self,
        dataset_directory,
    ):
        """
        Load and validate one complete champion reference dataset.

        No partially validated data is returned.
        """

        resolved_dataset_directory = (
            self._resolve_dataset_directory(
                dataset_directory
            )
        )

        manifest_file = (
            resolved_dataset_directory
            / self.MANIFEST_FILE_NAME
        )

        champions_file = (
            resolved_dataset_directory
            / self.CHAMPIONS_FILE_NAME
        )

        icons_directory = (
            resolved_dataset_directory
            / self.ICONS_DIRECTORY_NAME
        )

        manifest = self._read_json_object(
            manifest_file,
            description="manifest",
        )

        champion_file_bytes = (
            self._read_file_bytes(
                champions_file,
                description=(
                    "champion collection"
                ),
            )
        )

        self._validate_manifest(
            manifest=manifest,
            champion_file_bytes=(
                champion_file_bytes
            ),
        )

        champion_document = (
            self._decode_json_object(
                raw_bytes=champion_file_bytes,
                description=(
                    "champion collection"
                ),
            )
        )

        champions = champion_document.get(
            "champions"
        )

        if not isinstance(
            champions,
            list,
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset is missing "
                "the champions collection."
            )

        self._validate_champions(
            champions=champions,
            icons_directory=icons_directory,
            expected_count=manifest[
                "champion_count"
            ],
        )

        return {
            "manifest": manifest,
            "champions": champions,
            "dataset_directory": (
                resolved_dataset_directory
            ),
            "icons_directory": (
                icons_directory.resolve()
            ),
        }

    def _validate_manifest(
        self,
        manifest,
        champion_file_bytes,
    ):
        """
        Validate the manifest and champion-file checksum.
        """

        if (
            manifest.get("format")
            != self.FORMAT_NAME
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset uses an "
                "unsupported format."
            )

        format_version = manifest.get(
            "format_version"
        )

        if (
            isinstance(
                format_version,
                bool,
            )
            or format_version
            != self.FORMAT_VERSION
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset uses an "
                "unsupported format version."
            )

        data_dragon_version = manifest.get(
            "data_dragon_version"
        )

        if (
            not isinstance(
                data_dragon_version,
                str,
            )
            or not self.VERSION_PATTERN.fullmatch(
                data_dragon_version.strip()
            )
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset contains an "
                "invalid Data Dragon version."
            )

        if (
            manifest.get("locale")
            != self.SUPPORTED_LOCALE
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset uses an "
                "unsupported locale."
            )

        champion_count = manifest.get(
            "champion_count"
        )

        if (
            isinstance(
                champion_count,
                bool,
            )
            or not isinstance(
                champion_count,
                int,
            )
            or champion_count <= 0
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset contains an "
                "invalid champion count."
            )

        if (
            manifest.get("source")
            != self.SUPPORTED_SOURCE
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset contains an "
                "unsupported source."
            )

        self._validate_generated_timestamp(
            manifest.get(
                "generated_at"
            )
        )

        expected_sha256 = manifest.get(
            "champions_sha256"
        )

        if (
            not isinstance(
                expected_sha256,
                str,
            )
            or not self.SHA256_PATTERN.fullmatch(
                expected_sha256
            )
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset contains an "
                "invalid champion checksum."
            )

        actual_sha256 = hashlib.sha256(
            champion_file_bytes
        ).hexdigest()

        if actual_sha256 != expected_sha256:
            raise ChampionReferenceDatasetError(
                "The champion reference dataset checksum "
                "does not match champions.json."
            )

    def _validate_champions(
        self,
        champions,
        icons_directory,
        expected_count,
    ):
        """
        Validate every champion and the complete collection.
        """

        if len(champions) != expected_count:
            raise ChampionReferenceDatasetError(
                "The champion reference dataset count does "
                "not match the manifest."
            )

        if not icons_directory.is_dir():
            raise ChampionReferenceDatasetError(
                "The champion reference icon directory is "
                "missing."
            )

        seen_champion_ids = set()
        previous_champion_id = None

        for champion in champions:
            if not isinstance(
                champion,
                dict,
            ):
                raise ChampionReferenceDatasetError(
                    "The champion reference dataset contains "
                    "an invalid champion entry."
                )

            champion_id = champion.get(
                "riot_champion_id"
            )

            if (
                isinstance(
                    champion_id,
                    bool,
                )
                or not isinstance(
                    champion_id,
                    int,
                )
                or champion_id <= 0
            ):
                raise ChampionReferenceDatasetError(
                    "The champion reference dataset contains "
                    "an invalid Riot champion ID."
                )

            if champion_id in seen_champion_ids:
                raise ChampionReferenceDatasetError(
                    "The champion reference dataset contains "
                    "a duplicate Riot champion ID."
                )

            if (
                previous_champion_id is not None
                and champion_id
                <= previous_champion_id
            ):
                raise ChampionReferenceDatasetError(
                    "The champion reference dataset is not "
                    "sorted by Riot champion ID."
                )

            name = champion.get(
                "name"
            )

            if (
                not isinstance(
                    name,
                    str,
                )
                or not name.strip()
            ):
                raise ChampionReferenceDatasetError(
                    f"Champion {champion_id} is missing a "
                    "valid name."
                )

            image_filename = champion.get(
                "image_filename"
            )

            self._validate_image_filename(
                champion_id=champion_id,
                image_filename=image_filename,
            )

            icon_file = (
                icons_directory
                / image_filename
            )

            if not icon_file.is_file():
                raise ChampionReferenceDatasetError(
                    f"Champion {champion_id} is missing its "
                    "local icon."
                )

            seen_champion_ids.add(
                champion_id
            )

            previous_champion_id = (
                champion_id
            )

    def _validate_image_filename(
        self,
        champion_id,
        image_filename,
    ):
        """
        Validate a safe local PNG filename.
        """

        if (
            not isinstance(
                image_filename,
                str,
            )
            or not image_filename
            or Path(
                image_filename
            ).name
            != image_filename
            or "\\"
            in image_filename
            or "/"
            in image_filename
            or not self.IMAGE_FILENAME_PATTERN.fullmatch(
                image_filename
            )
        ):
            raise ChampionReferenceDatasetError(
                f"Champion {champion_id} contains an "
                "invalid image filename."
            )

    def _validate_generated_timestamp(
        self,
        generated_at,
    ):
        """
        Validate an ISO-8601 timestamp with timezone information.
        """

        if not isinstance(
            generated_at,
            str,
        ):
            raise ChampionReferenceDatasetError(
                "The champion reference dataset contains an "
                "invalid generation timestamp."
            )

        normalized_timestamp = (
            generated_at.strip()
        )

        if normalized_timestamp.endswith(
            "Z"
        ):
            normalized_timestamp = (
                normalized_timestamp[:-1]
                + "+00:00"
            )

        try:
            parsed_timestamp = (
                datetime.fromisoformat(
                    normalized_timestamp
                )
            )

        except ValueError as error:
            raise ChampionReferenceDatasetError(
                "The champion reference dataset contains an "
                "invalid generation timestamp."
            ) from error

        if parsed_timestamp.tzinfo is None:
            raise ChampionReferenceDatasetError(
                "The champion reference dataset generation "
                "timestamp must include a timezone."
            )

    @staticmethod
    def _resolve_dataset_directory(
        dataset_directory,
    ):
        """
        Resolve and validate the dataset root directory.
        """

        try:
            resolved_directory = Path(
                dataset_directory
            ).resolve()

        except (
            TypeError,
            OSError,
        ) as error:
            raise ChampionReferenceDatasetError(
                "The champion reference dataset path is "
                "invalid."
            ) from error

        if not resolved_directory.is_dir():
            raise ChampionReferenceDatasetError(
                "The champion reference dataset directory "
                "was not found."
            )

        return resolved_directory

    def _read_json_object(
        self,
        file_path,
        description,
    ):
        """
        Read a UTF-8 JSON file containing one object.
        """

        raw_bytes = self._read_file_bytes(
            file_path,
            description=description,
        )

        return self._decode_json_object(
            raw_bytes=raw_bytes,
            description=description,
        )

    @staticmethod
    def _read_file_bytes(
        file_path,
        description,
    ):
        """
        Read one required dataset file.
        """

        try:
            return file_path.read_bytes()

        except OSError as error:
            raise ChampionReferenceDatasetError(
                f"The champion reference {description} "
                "could not be read."
            ) from error

    @staticmethod
    def _decode_json_object(
        raw_bytes,
        description,
    ):
        """
        Decode one UTF-8 JSON object.
        """

        try:
            decoded_value = json.loads(
                raw_bytes.decode(
                    "utf-8"
                )
            )

        except (
            UnicodeError,
            json.JSONDecodeError,
        ) as error:
            raise ChampionReferenceDatasetError(
                f"The champion reference {description} "
                "contains invalid JSON."
            ) from error

        if not isinstance(
            decoded_value,
            dict,
        ):
            raise ChampionReferenceDatasetError(
                f"The champion reference {description} "
                "must contain a JSON object."
            )

        return decoded_value