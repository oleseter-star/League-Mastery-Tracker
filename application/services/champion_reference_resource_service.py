import sys
from pathlib import Path


class ChampionReferenceResourceService:
    """
    Resolves immutable bundled champion reference resources.

    Source execution resolves resources relative to the application
    package. PyInstaller execution resolves resources relative to
    the temporary bundle root exposed through sys._MEIPASS.

    This service only calculates paths. It never creates files or
    directories.
    """

    APPLICATION_DIRECTORY_NAME = "application"

    BUNDLED_REFERENCE_DIRECTORY_NAME = (
        "bundled_reference_data"
    )

    DATA_DRAGON_DIRECTORY_NAME = "data_dragon"

    MANIFEST_FILE_NAME = "manifest.json"
    CHAMPIONS_FILE_NAME = "champions.json"
    ICONS_DIRECTORY_NAME = "champion_icons"

    @classmethod
    def get_dataset_directory(cls):
        """
        Return the bundled Data Dragon dataset directory.
        """

        bundle_root = getattr(
            sys,
            "_MEIPASS",
            None,
        )

        if bundle_root:
            application_directory = (
                Path(
                    bundle_root
                )
                / cls.APPLICATION_DIRECTORY_NAME
            )

        else:
            application_directory = (
                Path(__file__)
                .resolve()
                .parent
                .parent
            )

        return (
            application_directory
            / cls.BUNDLED_REFERENCE_DIRECTORY_NAME
            / cls.DATA_DRAGON_DIRECTORY_NAME
        ).resolve()

    @classmethod
    def get_manifest_file(cls):
        """
        Return the bundled dataset manifest path.
        """

        return (
            cls.get_dataset_directory()
            / cls.MANIFEST_FILE_NAME
        )

    @classmethod
    def get_champions_file(cls):
        """
        Return the bundled champion collection path.
        """

        return (
            cls.get_dataset_directory()
            / cls.CHAMPIONS_FILE_NAME
        )

    @classmethod
    def get_icons_directory(cls):
        """
        Return the bundled champion icon directory.
        """

        return (
            cls.get_dataset_directory()
            / cls.ICONS_DIRECTORY_NAME
        )