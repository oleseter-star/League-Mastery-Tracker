from sqlalchemy import inspect, text

from application.database.database import db


class MatchSchemaService:
    """
    Adds columns that later versions introduced to existing match tables.

    db.create_all() creates missing tables but never changes existing
    ones. Match tables are additive and do not change the database schema
    version, so columns added to them after a database first created the
    tables are added here at startup. Every column added this way must be
    nullable or have a default, so older versions can keep ignoring it.
    """

    ADDITIVE_COLUMNS = (
        (
            "match_participants",
            "played_by_person_id",
            "INTEGER REFERENCES persons (id) ON DELETE SET NULL",
        ),
        (
            "match_participants",
            "ignored",
            "BOOLEAN NOT NULL DEFAULT 0",
        ),
    )

    @classmethod
    def add_missing_columns(cls):
        """
        Add every missing additive column. Returns the added
        "table.column" names.
        """

        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        added = []

        with db.engine.begin() as connection:
            for table, column, definition in cls.ADDITIVE_COLUMNS:
                if table not in existing_tables:
                    continue

                existing_columns = {
                    existing["name"]
                    for existing in inspector.get_columns(table)
                }

                if column in existing_columns:
                    continue

                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                )
                added.append(f"{table}.{column}")

        return added
