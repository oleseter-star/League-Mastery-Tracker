import re
from pathlib import Path

from application.services.champion_reference_source_service import (
    ChampionReferenceSourceService,
)


class ChampionReferenceImageError(
    ValueError
):
    """
    Raised when a requested champion image filename is invalid.
    """


class ChampionReferenceImageService:
    """
    Resolves champion icons from the active validated local dataset.

    This service performs no network requests. Missing, unreadable,
    empty, or invalid image files produce a controlled placeholder
    result.
    """

    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    IMAGE_FILENAME_PATTERN = re.compile(
        r"^[A-Za-z0-9_.-]+\.png$"
    )

    LOCAL_IMAGE_SOURCES = {
        "bundled",
        "local_cache",
    }

    def __init__(
        self,
        source_service=None,
    ):
        self.source_service = (
            source_service
            or ChampionReferenceSourceService()
        )

    def resolve_image(
        self,
        image_filename,
    ):
        """
        Resolve one local champion image or return placeholder metadata.
        """

        normalized_filename = (
            self._normalize_image_filename(
                image_filename
            )
        )

        try:
            selected_source = (
                self.source_service.select_source()
            )

        except Exception:
            return self._build_placeholder_result(
                active_source="database"
            )

        if not isinstance(
            selected_source,
            dict,
        ):
            return self._build_placeholder_result(
                active_source="database"
            )

        active_source = selected_source.get(
            "active_source"
        )

        if not isinstance(
            active_source,
            str,
        ):
            active_source = "database"

        if (
            active_source
            not in self.LOCAL_IMAGE_SOURCES
        ):
            return self._build_placeholder_result(
                active_source=active_source
            )

        icons_directory = selected_source.get(
            "icons_directory"
        )

        if icons_directory is None:
            return self._build_placeholder_result(
                active_source=active_source
            )

        try:
            resolved_icons_directory = Path(
                icons_directory
            ).resolve()

            image_file = (
                resolved_icons_directory
                / normalized_filename
            ).resolve()

        except (
            TypeError,
            OSError,
        ):
            return self._build_placeholder_result(
                active_source=active_source
            )

        if (
            image_file.parent
            != resolved_icons_directory
        ):
            return self._build_placeholder_result(
                active_source=active_source
            )

        if not image_file.is_file():
            return self._build_placeholder_result(
                active_source=active_source
            )

        try:
            with image_file.open(
                "rb"
            ) as image_stream:
                signature = image_stream.read(
                    len(
                        self.PNG_SIGNATURE
                    )
                )

        except OSError:
            return self._build_placeholder_result(
                active_source=active_source
            )

        if signature != self.PNG_SIGNATURE:
            return self._build_placeholder_result(
                active_source=active_source
            )

        return {
            "active_source": active_source,
            "image_file": image_file,
            "mime_type": "image/png",
            "placeholder": False,
        }

    def _normalize_image_filename(
        self,
        image_filename,
    ):
        """
        Validate and normalize a safe local PNG filename.
        """

        if not isinstance(
            image_filename,
            str,
        ):
            raise ChampionReferenceImageError(
                "The champion image filename is invalid."
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
            raise ChampionReferenceImageError(
                "The champion image filename is invalid."
            )

        return normalized_filename

    @staticmethod
    def _build_placeholder_result(
        active_source,
    ):
        """
        Return controlled placeholder metadata.
        """

        return {
            "active_source": active_source,
            "image_file": None,
            "mime_type": "image/svg+xml",
            "placeholder": True,
        }