from application.database.database import db


class Person(db.Model):
    """
    User-created grouping for one real-world person.
    """

    __tablename__ = "persons"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    display_name = db.Column(
        db.String(120),
        nullable=False
    )

    riot_accounts = db.relationship(
        "RiotAccount",
        back_populates="person",
        cascade="all, delete-orphan",
        lazy=True
    )

    def __repr__(self):
        return f"<Person {self.display_name}>"


class RiotAccount(db.Model):
    """
    Riot account belonging to one Person.
    """

    __tablename__ = "riot_accounts"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    person_id = db.Column(
        db.Integer,
        db.ForeignKey("persons.id"),
        nullable=False
    )

    game_name = db.Column(
        db.String(100),
        nullable=False
    )

    tag_line = db.Column(
        db.String(20),
        nullable=False
    )

    puuid = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    platform_region = db.Column(
        db.String(10),
        nullable=False
    )

    last_sync = db.Column(
        db.DateTime,
        nullable=True
    )

    person = db.relationship(
        "Person",
        back_populates="riot_accounts"
    )

    mastery_data = db.relationship(
        "ChampionMastery",
        back_populates="riot_account",
        cascade="all, delete-orphan",
        lazy=True
    )

    mastery_history = db.relationship(
        "ChampionMasteryHistory",
        back_populates="riot_account",
        cascade="all, delete-orphan",
        lazy=True
    )

    def __repr__(self):
        return f"<RiotAccount {self.game_name}#{self.tag_line}>"


class Champion(db.Model):
    """
    Local champion reference data.

    A record may temporarily have no name when Riot mastery data
    contains a champion that is missing from local reference data.
    """

    __tablename__ = "champions"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    riot_champion_id = db.Column(
        db.Integer,
        unique=True,
        nullable=False
    )

    name = db.Column(
        db.String(100),
        nullable=True
    )

    image = db.Column(
        db.String(255),
        nullable=True
    )

    source = db.Column(
        db.String(50),
        nullable=False,
        default="manual"
    )

    mastery_data = db.relationship(
        "ChampionMastery",
        back_populates="champion",
        lazy=True
    )

    def __repr__(self):
        label = self.name or f"Champion {self.riot_champion_id}"
        return f"<Champion {label}>"


class ChampionMastery(db.Model):
    """
    Current mastery points for one Champion on one Riot Account.
    """

    __tablename__ = "champion_masteries"

    __table_args__ = (
        db.UniqueConstraint(
            "riot_account_id",
            "champion_id",
            name="uq_mastery_account_champion"
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    riot_account_id = db.Column(
        db.Integer,
        db.ForeignKey("riot_accounts.id"),
        nullable=False
    )

    champion_id = db.Column(
        db.Integer,
        db.ForeignKey("champions.id"),
        nullable=False
    )

    mastery_points = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    # Empty until the next sync for records imported or stored
    # before levels were tracked.
    mastery_level = db.Column(
        db.Integer,
        nullable=True
    )

    riot_account = db.relationship(
        "RiotAccount",
        back_populates="mastery_data"
    )

    champion = db.relationship(
        "Champion",
        back_populates="mastery_data"
    )

    def __repr__(self):
        return (
            f"<ChampionMastery champion={self.champion_id} "
            f"points={self.mastery_points}>"
        )


class ChampionMasteryHistory(db.Model):
    """
    Mastery points and level for one Champion on one Riot Account
    at one point in time.

    A snapshot is stored only when a sync observes a change, so the
    value at any moment is the latest snapshot at or before it.
    """

    __tablename__ = "champion_mastery_history"

    __table_args__ = (
        db.Index(
            "ix_mastery_history_account_champion_time",
            "riot_account_id",
            "champion_id",
            "recorded_at",
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    riot_account_id = db.Column(
        db.Integer,
        db.ForeignKey("riot_accounts.id"),
        nullable=False
    )

    champion_id = db.Column(
        db.Integer,
        db.ForeignKey("champions.id"),
        nullable=False
    )

    recorded_at = db.Column(
        db.DateTime,
        nullable=False
    )

    mastery_points = db.Column(
        db.Integer,
        nullable=False
    )

    mastery_level = db.Column(
        db.Integer,
        nullable=True
    )

    riot_account = db.relationship(
        "RiotAccount",
        back_populates="mastery_history"
    )

    champion = db.relationship(
        "Champion"
    )

    def __repr__(self):
        return (
            f"<ChampionMasteryHistory champion={self.champion_id} "
            f"points={self.mastery_points} at={self.recorded_at}>"
        )