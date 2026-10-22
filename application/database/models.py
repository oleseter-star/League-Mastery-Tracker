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

    # Deleting a Riot Account keeps its games and clears the link.
    match_participations = db.relationship(
        "MatchParticipant",
        back_populates="riot_account",
        lazy=True
    )

    match_import_state = db.relationship(
        "MatchImportState",
        back_populates="riot_account",
        cascade="all, delete-orphan",
        uselist=False,
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


class Match(db.Model):
    """
    One Riot game, shared by every tracked Riot Account that played it.

    Match tables are additive: older versions ignore them, so they do
    not change the database schema version.
    """

    __tablename__ = "matches"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    riot_match_id = db.Column(
        db.String(40),
        unique=True,
        nullable=False
    )

    platform_id = db.Column(
        db.String(10),
        nullable=False
    )

    queue_id = db.Column(
        db.Integer,
        nullable=False
    )

    game_mode = db.Column(
        db.String(40),
        nullable=True
    )

    map_id = db.Column(
        db.Integer,
        nullable=True
    )

    game_version = db.Column(
        db.String(40),
        nullable=True
    )

    game_creation = db.Column(
        db.DateTime,
        nullable=False
    )

    game_duration_seconds = db.Column(
        db.Integer,
        nullable=False
    )

    # The complete Match-V5 document, zlib-compressed.
    raw_data = db.Column(
        db.LargeBinary,
        nullable=True
    )

    imported_at = db.Column(
        db.DateTime,
        nullable=False
    )

    participants = db.relationship(
        "MatchParticipant",
        back_populates="match",
        cascade="all, delete-orphan",
        order_by="MatchParticipant.participant_id",
        lazy=True
    )

    def __repr__(self):
        return f"<Match {self.riot_match_id}>"


class MatchParticipant(db.Model):
    """
    One of the ten participants in a Match.

    riot_account_id links a participant to a tracked Riot Account. It is
    the link statistics use, because Riot encrypts PUUIDs per API key
    project and stored PUUIDs can stop matching after a key change.
    """

    __tablename__ = "match_participants"

    __table_args__ = (
        db.UniqueConstraint(
            "match_id",
            "participant_id",
            name="uq_match_participant"
        ),
        db.Index(
            "ix_match_participants_riot_account_id",
            "riot_account_id"
        ),
        db.Index(
            "ix_match_participants_riot_champion_id",
            "riot_champion_id"
        ),
    )

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    match_id = db.Column(
        db.Integer,
        db.ForeignKey("matches.id", ondelete="CASCADE"),
        nullable=False
    )

    participant_id = db.Column(
        db.Integer,
        nullable=False
    )

    puuid = db.Column(
        db.String(100),
        nullable=True
    )

    riot_id_game_name = db.Column(
        db.String(100),
        nullable=True
    )

    riot_id_tagline = db.Column(
        db.String(20),
        nullable=True
    )

    riot_champion_id = db.Column(
        db.Integer,
        nullable=False
    )

    team_id = db.Column(
        db.Integer,
        nullable=False
    )

    team_position = db.Column(
        db.String(20),
        nullable=False,
        default=""
    )

    win = db.Column(
        db.Boolean,
        nullable=False
    )

    kills = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    deaths = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    assists = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    riot_account_id = db.Column(
        db.Integer,
        db.ForeignKey("riot_accounts.id", ondelete="SET NULL"),
        nullable=True
    )

    match = db.relationship(
        "Match",
        back_populates="participants"
    )

    riot_account = db.relationship(
        "RiotAccount",
        back_populates="match_participations"
    )

    def __repr__(self):
        return (
            f"<MatchParticipant match={self.match_id} "
            f"participant={self.participant_id}>"
        )


class MatchImportState(db.Model):
    """
    Match history import progress for one Riot Account.
    """

    __tablename__ = "match_import_states"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    riot_account_id = db.Column(
        db.Integer,
        db.ForeignKey("riot_accounts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )

    last_import_at = db.Column(
        db.DateTime,
        nullable=True
    )

    # Set once every available older game has been imported.
    history_complete = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    riot_account = db.relationship(
        "RiotAccount",
        back_populates="match_import_state"
    )

    def __repr__(self):
        return (
            f"<MatchImportState account={self.riot_account_id} "
            f"complete={self.history_complete}>"
        )
