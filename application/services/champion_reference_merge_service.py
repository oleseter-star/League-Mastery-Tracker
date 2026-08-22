from application.database.database import db
from application.database.models import Champion


class ChampionReferenceMergeError(
    RuntimeError
):
    """
    Raised when a champion reference dataset cannot be validated
    or merged into the local database safely.
    """


class ChampionReferenceMergeService:
    """
    Transactionally merges validated champion reference metadata
    into the local database.

    Existing database rows are updated in place so primary keys and
    mastery relationships remain intact. Champions absent from the
    active reference dataset are never deleted.
    """

    SUPPORTED_ACTIVE_SOURCES = {
        "bundled",
        "local_cache",
    }

    REFERENCE_CHAMPION_SOURCE = (
        "data_dragon"
    )

    def merge_dataset(
        self,
        dataset,
        active_source,
    ):
        """
        Validate and merge one complete champion reference dataset.
        """

        try:
            normalized_dataset = (
                self._validate_dataset(
                    dataset=dataset,
                    active_source=active_source,
                )
            )

            result = self._merge_champions(
                champions=normalized_dataset[
                    "champions"
                ],
            )

            db.session.commit()

            result.update(
                {
                    "active_source": (
                        active_source
                    ),
                    "data_dragon_version": (
                        normalized_dataset[
                            "data_dragon_version"
                        ]
                    ),
                    "locale": (
                        normalized_dataset[
                            "locale"
                        ]
                    ),
                    "dataset_count": len(
                        normalized_dataset[
                            "champions"
                        ]
                    ),
                    "database_count": (
                        Champion.query.count()
                    ),
                }
            )

            return result

        except ChampionReferenceMergeError:
            db.session.rollback()
            raise

        except Exception as error:
            db.session.rollback()

            raise ChampionReferenceMergeError(
                "The champion reference dataset could not "
                "be merged into the database safely."
            ) from error

    def _merge_champions(
        self,
        champions,
    ):
        """
        Merge all validated champion entries into existing rows.
        """

        existing_champions = {
            champion.riot_champion_id: champion
            for champion in Champion.query.all()
        }

        dataset_champion_ids = {
            champion["riot_champion_id"]
            for champion in champions
        }

        created = 0
        updated = 0
        unchanged = 0
        preserved_manual = 0

        for reference_champion in champions:
            riot_champion_id = (
                reference_champion[
                    "riot_champion_id"
                ]
            )

            reference_name = (
                reference_champion[
                    "name"
                ]
            )

            reference_image = (
                reference_champion[
                    "image_filename"
                ]
            )

            existing_champion = (
                existing_champions.get(
                    riot_champion_id
                )
            )

            if existing_champion is None:
                db.session.add(
                    Champion(
                        riot_champion_id=(
                            riot_champion_id
                        ),
                        name=reference_name,
                        image=reference_image,
                        source=(
                            self
                            .REFERENCE_CHAMPION_SOURCE
                        ),
                    )
                )

                created += 1
                continue

            if (
                existing_champion.source
                == "manual"
            ):
                preserved_manual += 1
                continue

            metadata_changed = (
                existing_champion.name
                != reference_name
                or existing_champion.image
                != reference_image
                or existing_champion.source
                != self.REFERENCE_CHAMPION_SOURCE
            )

            if metadata_changed:
                existing_champion.name = (
                    reference_name
                )

                existing_champion.image = (
                    reference_image
                )

                existing_champion.source = (
                    self
                    .REFERENCE_CHAMPION_SOURCE
                )

                updated += 1

            else:
                unchanged += 1

        preserved_existing = len(
            set(
                existing_champions
            )
            - dataset_champion_ids
        )

        return {
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "preserved_manual": (
                preserved_manual
            ),
            "preserved_existing": (
                preserved_existing
            ),
        }

    def _validate_dataset(
        self,
        dataset,
        active_source,
    ):
        """
        Validate the complete merge input before database writes.
        """

        if (
            active_source
            not in self.SUPPORTED_ACTIVE_SOURCES
        ):
            raise ChampionReferenceMergeError(
                "The active champion reference source "
                "is invalid."
            )

        if not isinstance(
            dataset,
            dict,
        ):
            raise ChampionReferenceMergeError(
                "The champion reference dataset "
                "is invalid."
            )

        manifest = dataset.get(
            "manifest"
        )

        champions = dataset.get(
            "champions"
        )

        if not isinstance(
            manifest,
            dict,
        ):
            raise ChampionReferenceMergeError(
                "The champion reference manifest "
                "is invalid."
            )

        if (
            not isinstance(
                champions,
                list,
            )
            or not champions
        ):
            raise ChampionReferenceMergeError(
                "The champion reference collection "
                "must be a non-empty list."
            )

        data_dragon_version = (
            manifest.get(
                "data_dragon_version"
            )
        )

        locale = manifest.get(
            "locale"
        )

        champion_count = manifest.get(
            "champion_count"
        )

        if (
            not isinstance(
                data_dragon_version,
                str,
            )
            or not data_dragon_version.strip()
        ):
            raise ChampionReferenceMergeError(
                "The champion reference version "
                "is invalid."
            )

        if (
            not isinstance(
                locale,
                str,
            )
            or not locale.strip()
        ):
            raise ChampionReferenceMergeError(
                "The champion reference locale "
                "is invalid."
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
            or champion_count
            != len(
                champions
            )
        ):
            raise ChampionReferenceMergeError(
                "The champion reference count does "
                "not match the manifest."
            )

        normalized_champions = []
        seen_champion_ids = set()

        for champion in champions:
            normalized_champion = (
                self._validate_champion(
                    champion
                )
            )

            champion_id = (
                normalized_champion[
                    "riot_champion_id"
                ]
            )

            if champion_id in seen_champion_ids:
                raise ChampionReferenceMergeError(
                    "The champion reference collection "
                    "contains a duplicate Riot champion ID."
                )

            seen_champion_ids.add(
                champion_id
            )

            normalized_champions.append(
                normalized_champion
            )

        return {
            "data_dragon_version": (
                data_dragon_version.strip()
            ),
            "locale": locale.strip(),
            "champions": (
                normalized_champions
            ),
        }

    @staticmethod
    def _validate_champion(
        champion,
    ):
        """
        Validate and normalize one champion reference entry.
        """

        if not isinstance(
            champion,
            dict,
        ):
            raise ChampionReferenceMergeError(
                "The champion reference collection "
                "contains an invalid entry."
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
            raise ChampionReferenceMergeError(
                "The champion reference collection "
                "contains an invalid Riot champion ID."
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
            raise ChampionReferenceMergeError(
                f"Champion {champion_id} is missing "
                "a valid name."
            )

        image_filename = champion.get(
            "image_filename"
        )

        if (
            not isinstance(
                image_filename,
                str,
            )
            or not image_filename.strip()
        ):
            raise ChampionReferenceMergeError(
                f"Champion {champion_id} is missing "
                "a valid image filename."
            )

        return {
            "riot_champion_id": champion_id,
            "name": name.strip(),
            "image_filename": (
                image_filename.strip()
            ),
        }