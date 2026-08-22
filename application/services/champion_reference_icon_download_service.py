import re
import shutil
from pathlib import Path

import requests


class ChampionReferenceIconDownloadError(
    ValueError
):
    """
    Raised when champion icons cannot be validated, downloaded,
    or installed safely.
    """


class ChampionReferenceIconDownloadService:
    """
    Downloads a complete set of champion icons from Data Dragon.

    Icons are downloaded into a temporary directory. The existing
    icon directory is replaced only after every new icon has been
    downloaded and validated successfully.
    """

    IMAGE_BASE_URL = (
        "https://ddragon.leagueoflegends.com/"
        "cdn/{version}/img/champion/{filename}"
    )

    ICONS_DIRECTORY_NAME = "champion_icons"
    TEMPORARY_DIRECTORY_NAME = "champion_icons.tmp"
    PREVIOUS_DIRECTORY_NAME = "champion_icons.previous"

    REQUEST_TIMEOUT_SECONDS = 15

    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    VERSION_PATTERN = re.compile(
        r"^\d+(?:\.\d+)+$"
    )

    IMAGE_FILENAME_PATTERN = re.compile(
        r"^[A-Za-z0-9_.-]+\.png$"
    )

    def download_icons(
        self,
        champions,
        data_dragon_version,
        output_directory,
    ):
        """
        Download and transactionally install all requested icons.
        """

        normalized_version = (
            self._normalize_version(
                data_dragon_version
            )
        )

        normalized_champions = (
            self._normalize_champions(
                champions
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

        temporary_directory = (
            resolved_output_directory
            / self.TEMPORARY_DIRECTORY_NAME
        )

        previous_directory = (
            resolved_output_directory
            / self.PREVIOUS_DIRECTORY_NAME
        )

        existing_icons_moved = False

        try:
            resolved_output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            self._remove_directory(
                temporary_directory
            )

            self._remove_directory(
                previous_directory
            )

            temporary_directory.mkdir(
                parents=True,
                exist_ok=False,
            )

            for champion in normalized_champions:
                image_filename = champion[
                    "image_filename"
                ]

                image_bytes = (
                    self._download_icon(
                        version=normalized_version,
                        image_filename=(
                            image_filename
                        ),
                    )
                )

                (
                    temporary_directory
                    / image_filename
                ).write_bytes(
                    image_bytes
                )

            if icons_directory.exists():
                icons_directory.replace(
                    previous_directory
                )

                existing_icons_moved = True

            temporary_directory.replace(
                icons_directory
            )

            self._remove_directory(
                previous_directory
            )

        except (
            OSError,
            requests.RequestException,
        ) as error:
            self._restore_previous_icons(
                icons_directory=icons_directory,
                previous_directory=(
                    previous_directory
                ),
                existing_icons_moved=(
                    existing_icons_moved
                ),
            )

            self._remove_directory(
                temporary_directory
            )

            self._remove_directory(
                previous_directory
            )

            raise (
                ChampionReferenceIconDownloadError(
                    "The champion icons could not be "
                    "downloaded and installed safely."
                )
            ) from error

        except ChampionReferenceIconDownloadError:
            self._restore_previous_icons(
                icons_directory=icons_directory,
                previous_directory=(
                    previous_directory
                ),
                existing_icons_moved=(
                    existing_icons_moved
                ),
            )

            self._remove_directory(
                temporary_directory
            )

            self._remove_directory(
                previous_directory
            )

            raise

        return {
            "downloaded": len(
                normalized_champions
            ),
            "icons_directory": (
                icons_directory.resolve()
            ),
            "data_dragon_version": (
                normalized_version
            ),
        }

    def _download_icon(
        self,
        version,
        image_filename,
    ):
        """
        Download and validate one PNG icon.
        """

        url = self.IMAGE_BASE_URL.format(
            version=version,
            filename=image_filename,
        )

        response = requests.get(
            url,
            timeout=(
                self.REQUEST_TIMEOUT_SECONDS
            ),
        )

        response.raise_for_status()

        image_bytes = response.content

        if (
            not isinstance(
                image_bytes,
                bytes,
            )
            or not image_bytes.startswith(
                self.PNG_SIGNATURE
            )
        ):
            raise (
                ChampionReferenceIconDownloadError(
                    f"Data Dragon returned an invalid PNG "
                    f"for {image_filename}."
                )
            )

        return image_bytes

    def _normalize_champions(
        self,
        champions,
    ):
        """
        Validate and deterministically order champion entries.
        """

        if (
            not isinstance(
                champions,
                list,
            )
            or not champions
        ):
            raise (
                ChampionReferenceIconDownloadError(
                    "A non-empty champion collection "
                    "is required."
                )
            )

        normalized_champions = []
        seen_champion_ids = set()
        seen_image_filenames = set()

        for champion in champions:
            if not isinstance(
                champion,
                dict,
            ):
                raise (
                    ChampionReferenceIconDownloadError(
                        "The champion collection contains "
                        "an invalid entry."
                    )
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
                raise (
                    ChampionReferenceIconDownloadError(
                        "The champion collection contains "
                        "an invalid Riot champion ID."
                    )
                )

            if champion_id in seen_champion_ids:
                raise (
                    ChampionReferenceIconDownloadError(
                        "The champion collection contains "
                        "a duplicate Riot champion ID."
                    )
                )

            image_filename = (
                self._normalize_image_filename(
                    champion_id=champion_id,
                    image_filename=champion.get(
                        "image_filename"
                    ),
                )
            )

            if (
                image_filename
                in seen_image_filenames
            ):
                raise (
                    ChampionReferenceIconDownloadError(
                        "The champion collection contains "
                        "a duplicate image filename."
                    )
                )

            seen_champion_ids.add(
                champion_id
            )

            seen_image_filenames.add(
                image_filename
            )

            normalized_champions.append(
                {
                    "riot_champion_id": (
                        champion_id
                    ),
                    "image_filename": (
                        image_filename
                    ),
                }
            )

        normalized_champions.sort(
            key=lambda champion: (
                champion[
                    "riot_champion_id"
                ]
            )
        )

        return normalized_champions

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
                ChampionReferenceIconDownloadError(
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
                ChampionReferenceIconDownloadError(
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
                ChampionReferenceIconDownloadError(
                    "The Data Dragon version is invalid."
                )
            )

        return normalized_version

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
                ChampionReferenceIconDownloadError(
                    "The icon output directory is invalid."
                )
            ) from error

    @classmethod
    def _restore_previous_icons(
        cls,
        icons_directory,
        previous_directory,
        existing_icons_moved,
    ):
        """
        Restore the previous icon directory after a failed swap.
        """

        if not existing_icons_moved:
            return

        try:
            if icons_directory.exists():
                cls._remove_directory(
                    icons_directory
                )

            if previous_directory.exists():
                previous_directory.replace(
                    icons_directory
                )

        except OSError:
            pass

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