from application.database.database import db
from application.database.models import Champion


_NOT_PROVIDED = object()


class ChampionService:
    """
    Service layer for local champion reference management.
    """

    # League Classic reports Champion Mastery under 60000 plus the
    # regular Riot champion ID. Classic Mastery is outside the 2.0 scope.
    CLASSIC_CHAMPION_ID_MINIMUM = 60001
    CLASSIC_CHAMPION_ID_MAXIMUM = 60999

    @staticmethod
    def is_classic_champion_id(riot_champion_id):
        """
        Return whether a Riot champion ID belongs to League Classic.
        """

        try:
            normalized_id = int(
                riot_champion_id
            )

        except (TypeError, ValueError):
            return False

        return (
            ChampionService.CLASSIC_CHAMPION_ID_MINIMUM
            <= normalized_id
            <= ChampionService.CLASSIC_CHAMPION_ID_MAXIMUM
        )

    @staticmethod
    def get_all_champions():
        """
        Return all champions ordered by name and Riot champion ID.
        """

        return (
            Champion.query
            .order_by(
                Champion.name.is_(None),
                Champion.name,
                Champion.riot_champion_id,
            )
            .all()
        )

    @staticmethod
    def get_missing_reference_champions():
        """
        Return champions that do not have a reference name.
        """

        return (
            Champion.query
            .filter(
                Champion.name.is_(None)
            )
            .order_by(
                Champion.riot_champion_id
            )
            .all()
        )

    @staticmethod
    def get_champion_by_id(champion_id):
        """
        Return a champion by its internal database ID.
        """

        return db.session.get(
            Champion,
            champion_id,
        )

    @staticmethod
    def get_champion_by_riot_id(riot_champion_id):
        """
        Return a champion by Riot's numeric champion ID.
        """

        normalized_id = (
            ChampionService._normalize_riot_champion_id(
                riot_champion_id
            )
        )

        return Champion.query.filter_by(
            riot_champion_id=normalized_id
        ).one_or_none()

    @staticmethod
    def create_champion(
        riot_champion_id,
        name=None,
        image=None,
        source="manual",
    ):
        """
        Create a local champion reference record.
        """

        normalized_id = (
            ChampionService._normalize_riot_champion_id(
                riot_champion_id
            )
        )

        existing_champion = Champion.query.filter_by(
            riot_champion_id=normalized_id
        ).one_or_none()

        if existing_champion is not None:
            raise ValueError(
                f"Champion with Riot ID {normalized_id} already exists."
            )

        champion = Champion(
            riot_champion_id=normalized_id,
            name=ChampionService._normalize_optional_text(
                name
            ),
            image=ChampionService._normalize_optional_text(
                image
            ),
            source=ChampionService._normalize_source(
                source
            ),
        )

        try:
            db.session.add(
                champion
            )

            db.session.commit()

            return champion

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def update_champion(
        champion,
        name=_NOT_PROVIDED,
        image=_NOT_PROVIDED,
        source=_NOT_PROVIDED,
    ):
        """
        Update only the champion fields that were supplied.
        """

        if champion is None:
            raise ValueError(
                "Champion is required."
            )

        if name is not _NOT_PROVIDED:
            champion.name = (
                ChampionService._normalize_optional_text(
                    name
                )
            )

        if image is not _NOT_PROVIDED:
            champion.image = (
                ChampionService._normalize_optional_text(
                    image
                )
            )

        if source is not _NOT_PROVIDED:
            champion.source = (
                ChampionService._normalize_source(
                    source
                )
            )

        try:
            db.session.commit()

            return champion

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _normalize_riot_champion_id(
        riot_champion_id
    ):
        """
        Convert and validate a Riot champion ID.
        """

        try:
            normalized_id = int(
                riot_champion_id
            )

        except (TypeError, ValueError) as error:
            raise ValueError(
                "Riot champion ID must be an integer."
            ) from error

        if normalized_id <= 0:
            raise ValueError(
                "Riot champion ID must be greater than zero."
            )

        return normalized_id

    @staticmethod
    def _normalize_optional_text(value):
        """
        Normalize optional text values.
        """

        if value is None:
            return None

        normalized_value = str(
            value
        ).strip()

        return normalized_value or None

    @staticmethod
    def _normalize_source(source):
        """
        Normalize the champion reference source.
        """

        normalized_source = str(
            source or "manual"
        ).strip().lower()

        return normalized_source or "manual"