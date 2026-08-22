import json
from pathlib import Path

import requests
from flask import current_app

from application.database.database import db
from application.database.models import Champion


class DataDragonService:
    """
    Maintains local champion reference data from Riot Data Dragon.

    Champion Mastery data is never modified by this service.
    Existing champions missing from Data Dragon are preserved.
    """

    VERSIONS_URL = (
        "https://ddragon.leagueoflegends.com/api/versions.json"
    )

    CHAMPION_DATA_URL = (
        "https://ddragon.leagueoflegends.com/cdn/"
        "{version}/data/en_US/champion.json"
    )

    CHAMPION_IMAGE_URL = (
        "https://ddragon.leagueoflegends.com/cdn/"
        "{version}/img/champion/{filename}"
    )

    def __init__(self):
        self.timeout_seconds = 15

    def refresh_reference_data(self, force=False):
        """
        Check the latest Data Dragon version and refresh champion
        reference data when required.

        A download occurs when:
        - force is True
        - no valid local cache exists
        - Riot reports a newer version

        When the cached version is already current, the cache is
        reapplied if it can repair missing or incorrect local
        champion names, images, sources, or records.
        """

        latest_version = self.get_latest_version()
        cached_version = self.get_cached_version()

        cached_champion_data = None

        if cached_version == latest_version:
            try:
                cached_champion_data = (
                    self.load_cached_champion_data()
                )
            except (OSError, ValueError):
                cached_champion_data = None

        if (
            not force
            and cached_version == latest_version
            and cached_champion_data is not None
        ):
            repair_required = (
                self._cache_requires_local_repair(
                    champion_data=cached_champion_data,
                    version=latest_version,
                )
            )

            if not repair_required:
                return {
                    "updated": False,
                    "version": cached_version,
                    "created": 0,
                    "changed": 0,
                    "unchanged": 0,
                    "missing_references": (
                        self._count_missing_references()
                    ),
                    "repaired_from_cache": False,
                }

            update_result = self.apply_champion_data(
                champion_data=cached_champion_data,
                version=latest_version,
            )

            return {
                "updated": True,
                "version": latest_version,
                "created": update_result["created"],
                "changed": update_result["changed"],
                "unchanged": update_result["unchanged"],
                "missing_references": (
                    self._count_missing_references()
                ),
                "repaired_from_cache": True,
            }

        champion_data = self.get_champion_data(
            latest_version
        )

        update_result = self.apply_champion_data(
            champion_data=champion_data,
            version=latest_version,
        )

        self.save_reference_cache(
            version=latest_version,
            champion_data=champion_data,
        )

        return {
            "updated": True,
            "version": latest_version,
            "created": update_result["created"],
            "changed": update_result["changed"],
            "unchanged": update_result["unchanged"],
            "missing_references": (
                self._count_missing_references()
            ),
            "repaired_from_cache": False,
        }

    def get_latest_version(self):
        """
        Retrieve the most recent available Data Dragon version.
        """

        response = requests.get(
            self.VERSIONS_URL,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        versions = response.json()

        if (
            not isinstance(versions, list)
            or not versions
            or not isinstance(versions[0], str)
        ):
            raise ValueError(
                "Data Dragon returned an invalid version list."
            )

        latest_version = versions[0].strip()

        if not latest_version:
            raise ValueError(
                "Data Dragon returned an empty version."
            )

        return latest_version

    def get_champion_data(self, version):
        """
        Download champion reference data for one Data Dragon version.
        """

        normalized_version = self._normalize_version(
            version
        )

        url = self.CHAMPION_DATA_URL.format(
            version=normalized_version
        )

        response = requests.get(
            url,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        champion_data = response.json()

        if not isinstance(champion_data, dict):
            raise ValueError(
                "Data Dragon returned invalid champion data."
            )

        champions = champion_data.get(
            "data"
        )

        if not isinstance(champions, dict):
            raise ValueError(
                "Data Dragon champion data is missing "
                "the data collection."
            )

        return champion_data

    def download_champion_data(self, version):
        """
        Download champion data for explicit build and update flows.

        This public method preserves compatibility with the original
        get_champion_data() method while giving newer orchestration
        services a clear download-specific interface.
        """

        return self.get_champion_data(
            version
        )

    def apply_champion_data(
        self,
        champion_data,
        version,
    ):
        """
        Add or update local Champion records from Data Dragon.

        Champions absent from Data Dragon are not deleted.
        Champion Mastery records are never changed.
        """

        normalized_version = self._normalize_version(
            version
        )

        champions = champion_data.get(
            "data"
        )

        if not isinstance(champions, dict):
            raise ValueError(
                "Champion reference data is invalid."
            )

        created_count = 0
        changed_count = 0
        unchanged_count = 0

        try:
            for champion_data_entry in champions.values():
                parsed_champion = self._parse_champion_entry(
                    champion_data_entry,
                    normalized_version,
                )

                riot_champion_id = parsed_champion[
                    "riot_champion_id"
                ]

                champion = Champion.query.filter_by(
                    riot_champion_id=riot_champion_id
                ).one_or_none()

                if champion is None:
                    champion = Champion(
                        riot_champion_id=riot_champion_id,
                        name=parsed_champion["name"],
                        image=parsed_champion["image"],
                        source="data_dragon",
                    )

                    db.session.add(
                        champion
                    )

                    created_count += 1
                    continue

                changed = False

                if champion.name != parsed_champion["name"]:
                    champion.name = parsed_champion["name"]
                    changed = True

                if champion.image != parsed_champion["image"]:
                    champion.image = parsed_champion["image"]
                    changed = True

                if champion.source != "data_dragon":
                    champion.source = "data_dragon"
                    changed = True

                if changed:
                    changed_count += 1
                else:
                    unchanged_count += 1

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

        return {
            "created": created_count,
            "changed": changed_count,
            "unchanged": unchanged_count,
        }

    def get_cached_version(self):
        """
        Return the locally cached Data Dragon version, if present.
        """

        version_file = self._get_version_file()

        if not version_file.exists():
            return None

        cached_version = version_file.read_text(
            encoding="utf-8"
        ).strip()

        return cached_version or None

    def load_cached_champion_data(self):
        """
        Load locally cached champion JSON, if present.
        """

        champion_file = self._get_champion_file()

        if not champion_file.exists():
            return None

        with champion_file.open(
            "r",
            encoding="utf-8",
        ) as file:
            champion_data = json.load(
                file
            )

        if not isinstance(champion_data, dict):
            raise ValueError(
                "Cached champion reference data is invalid."
            )

        champions = champion_data.get(
            "data"
        )

        if not isinstance(champions, dict):
            raise ValueError(
                "Cached champion reference data is missing "
                "the data collection."
            )

        return champion_data

    def save_reference_cache(
        self,
        version,
        champion_data,
    ):
        """
        Save Data Dragon version and champion JSON atomically.
        """

        normalized_version = self._normalize_version(
            version
        )

        reference_directory = (
            self._get_reference_directory()
        )

        reference_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        champion_file = self._get_champion_file()
        champion_temp_file = champion_file.with_suffix(
            ".json.tmp"
        )

        version_file = self._get_version_file()
        version_temp_file = version_file.with_suffix(
            ".txt.tmp"
        )

        with champion_temp_file.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                champion_data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        version_temp_file.write_text(
            normalized_version,
            encoding="utf-8",
        )

        champion_temp_file.replace(
            champion_file
        )

        version_temp_file.replace(
            version_file
        )

    def _cache_requires_local_repair(
        self,
        champion_data,
        version,
    ):
        """
        Determine whether the current cache can repair local
        champion reference records.

        Unknown champions absent from Data Dragon do not trigger a
        repair or repeated download.
        """

        champions = champion_data.get(
            "data"
        )

        if not isinstance(champions, dict):
            raise ValueError(
                "Cached champion reference data is invalid."
            )

        normalized_version = self._normalize_version(
            version
        )

        for champion_data_entry in champions.values():
            parsed_champion = self._parse_champion_entry(
                champion_data_entry,
                normalized_version,
            )

            champion = Champion.query.filter_by(
                riot_champion_id=(
                    parsed_champion["riot_champion_id"]
                )
            ).one_or_none()

            if champion is None:
                return True

            if champion.name != parsed_champion["name"]:
                return True

            if champion.image != parsed_champion["image"]:
                return True

            if champion.source != "data_dragon":
                return True

        return False

    @staticmethod
    def _count_missing_references():
        """
        Count champions still missing a reference name.
        """

        return (
            Champion.query
            .filter(
                Champion.name.is_(None)
            )
            .count()
        )

    def _parse_champion_entry(
        self,
        champion_data_entry,
        version,
    ):
        """
        Validate and normalize one Data Dragon champion entry.
        """

        if not isinstance(champion_data_entry, dict):
            raise ValueError(
                "Data Dragon contains an invalid champion entry."
            )

        riot_champion_id = champion_data_entry.get(
            "key"
        )

        name = champion_data_entry.get(
            "name"
        )

        image_data = champion_data_entry.get(
            "image"
        )

        try:
            normalized_champion_id = int(
                riot_champion_id
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Data Dragon contains an invalid champion ID."
            ) from error

        normalized_name = str(
            name or ""
        ).strip()

        if not normalized_name:
            raise ValueError(
                f"Champion {normalized_champion_id} "
                "is missing a name."
            )

        if not isinstance(image_data, dict):
            raise ValueError(
                f"Champion {normalized_champion_id} "
                "is missing image data."
            )

        image_filename = str(
            image_data.get("full") or ""
        ).strip()

        if not image_filename:
            raise ValueError(
                f"Champion {normalized_champion_id} "
                "is missing an image filename."
            )

        image_url = self.CHAMPION_IMAGE_URL.format(
            version=version,
            filename=image_filename,
        )

        return {
            "riot_champion_id": normalized_champion_id,
            "name": normalized_name,
            "image": image_url,
        }

    def _get_reference_directory(self):
        """
        Return the Data Dragon cache directory.
        """

        reference_root = Path(
            current_app.config["REFERENCE_DIR"]
        )

        return reference_root / "data_dragon"

    def _get_champion_file(self):
        return (
            self._get_reference_directory()
            / "champions.json"
        )

    def _get_version_file(self):
        return (
            self._get_reference_directory()
            / "version.txt"
        )

    @staticmethod
    def _normalize_version(version):
        """
        Validate a Data Dragon version string.
        """

        normalized_version = str(
            version or ""
        ).strip()

        if not normalized_version:
            raise ValueError(
                "Data Dragon version is required."
            )

        allowed_characters = set(
            "0123456789."
        )

        if not set(normalized_version).issubset(
            allowed_characters
        ):
            raise ValueError(
                "Data Dragon version contains "
                "unsupported characters."
            )

        return normalized_version