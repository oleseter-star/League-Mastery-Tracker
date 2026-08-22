import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.database.database import db
from application.database.models import (
    Champion,
    ChampionMastery,
    Person,
    RiotAccount,
)
from application.services.champion_reference_merge_service import (
    ChampionReferenceMergeError,
    ChampionReferenceMergeService,
)


class ChampionReferenceMergeServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        temporary_path = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            temporary_path
            / "reference-merge-test.db"
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=(
                "sqlite:///"
                + self.database_file.as_posix()
            ),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )

        db.init_app(
            self.app
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

        self.service = (
            ChampionReferenceMergeService()
        )

    def tearDown(self):
        try:
            db.session.rollback()
            db.session.remove()

            db.drop_all()

            db.session.remove()
            db.engine.dispose()

        finally:
            self.app_context.pop()

            self.temporary_directory.cleanup()

    @staticmethod
    def _build_dataset(
        champions=None,
    ):
        return {
            "manifest": {
                "data_dragon_version": (
                    "15.14.1"
                ),
                "locale": "en_US",
                "champion_count": len(
                    champions
                    if champions is not None
                    else [
                        {},
                        {},
                    ]
                ),
            },
            "champions": (
                champions
                if champions is not None
                else [
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                    {
                        "riot_champion_id": 2,
                        "name": "Olaf",
                        "image_filename": (
                            "Olaf.png"
                        ),
                    },
                ]
            ),
        }

    @staticmethod
    def _create_champion(
        riot_champion_id,
        name=None,
        image=None,
        source="manual",
    ):
        champion = Champion(
            riot_champion_id=(
                riot_champion_id
            ),
            name=name,
            image=image,
            source=source,
        )

        db.session.add(
            champion
        )

        db.session.flush()

        return champion

    @staticmethod
    def _create_mastery(
        champion,
        mastery_points=123456,
    ):
        person = Person(
            display_name="Merge Tester"
        )

        db.session.add(
            person
        )

        db.session.flush()

        account = RiotAccount(
            person_id=person.id,
            game_name="MergePlayer",
            tag_line="EUW",
            puuid="merge-test-puuid",
            platform_region="euw1",
        )

        db.session.add(
            account
        )

        db.session.flush()

        mastery = ChampionMastery(
            riot_account_id=account.id,
            champion_id=champion.id,
            mastery_points=mastery_points,
        )

        db.session.add(
            mastery
        )

        db.session.flush()

        return mastery

    def test_empty_database_is_seeded(
        self
    ):
        result = self.service.merge_dataset(
            dataset=self._build_dataset(),
            active_source="bundled",
        )

        champions = (
            Champion.query
            .order_by(
                Champion.riot_champion_id
            )
            .all()
        )

        self.assertEqual(
            len(champions),
            2,
        )

        self.assertEqual(
            champions[0].riot_champion_id,
            1,
        )

        self.assertEqual(
            champions[0].name,
            "Annie",
        )

        self.assertEqual(
            champions[0].image,
            "Annie.png",
        )

        self.assertEqual(
            champions[0].source,
            "data_dragon",
        )

        self.assertEqual(
            result["created"],
            2,
        )

        self.assertEqual(
            result["database_count"],
            2,
        )

    def test_existing_data_dragon_champion_is_updated(
        self
    ):
        champion = self._create_champion(
            riot_champion_id=1,
            name="Old Annie",
            image="OldAnnie.png",
            source="data_dragon",
        )

        db.session.commit()

        original_database_id = (
            champion.id
        )

        result = self.service.merge_dataset(
            dataset=self._build_dataset(
                champions=[
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                ]
            ),
            active_source="bundled",
        )

        refreshed_champion = (
            Champion.query.filter_by(
                riot_champion_id=1
            ).one()
        )

        self.assertEqual(
            refreshed_champion.id,
            original_database_id,
        )

        self.assertEqual(
            refreshed_champion.name,
            "Annie",
        )

        self.assertEqual(
            refreshed_champion.image,
            "Annie.png",
        )

        self.assertEqual(
            result["updated"],
            1,
        )

        self.assertEqual(
            result["created"],
            0,
        )

    def test_unchanged_champion_is_reported(
        self
    ):
        self._create_champion(
            riot_champion_id=1,
            name="Annie",
            image="Annie.png",
            source="data_dragon",
        )

        db.session.commit()

        result = self.service.merge_dataset(
            dataset=self._build_dataset(
                champions=[
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                ]
            ),
            active_source="bundled",
        )

        self.assertEqual(
            result["unchanged"],
            1,
        )

        self.assertEqual(
            result["updated"],
            0,
        )

    def test_manual_metadata_is_preserved(
        self
    ):
        champion = self._create_champion(
            riot_champion_id=1,
            name="My Annie",
            image="MyAnnie.png",
            source="manual",
        )

        db.session.commit()

        original_database_id = (
            champion.id
        )

        result = self.service.merge_dataset(
            dataset=self._build_dataset(
                champions=[
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                ]
            ),
            active_source="bundled",
        )

        refreshed_champion = (
            Champion.query.filter_by(
                riot_champion_id=1
            ).one()
        )

        self.assertEqual(
            refreshed_champion.id,
            original_database_id,
        )

        self.assertEqual(
            refreshed_champion.name,
            "My Annie",
        )

        self.assertEqual(
            refreshed_champion.image,
            "MyAnnie.png",
        )

        self.assertEqual(
            refreshed_champion.source,
            "manual",
        )

        self.assertEqual(
            result["preserved_manual"],
            1,
        )

    def test_unknown_champion_receives_metadata_when_known(
        self
    ):
        champion = self._create_champion(
            riot_champion_id=1,
            name=None,
            image=None,
            source="riot_api",
        )

        db.session.commit()

        original_database_id = (
            champion.id
        )

        result = self.service.merge_dataset(
            dataset=self._build_dataset(
                champions=[
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                ]
            ),
            active_source="bundled",
        )

        refreshed_champion = (
            Champion.query.filter_by(
                riot_champion_id=1
            ).one()
        )

        self.assertEqual(
            refreshed_champion.id,
            original_database_id,
        )

        self.assertEqual(
            refreshed_champion.name,
            "Annie",
        )

        self.assertEqual(
            refreshed_champion.image,
            "Annie.png",
        )

        self.assertEqual(
            refreshed_champion.source,
            "data_dragon",
        )

        self.assertEqual(
            result["updated"],
            1,
        )

    def test_champion_missing_from_dataset_is_preserved(
        self
    ):
        self._create_champion(
            riot_champion_id=999999,
            name=None,
            image=None,
            source="riot_api",
        )

        db.session.commit()

        result = self.service.merge_dataset(
            dataset=self._build_dataset(),
            active_source="bundled",
        )

        unknown_champion = (
            Champion.query.filter_by(
                riot_champion_id=999999
            ).one_or_none()
        )

        self.assertIsNotNone(
            unknown_champion
        )

        self.assertEqual(
            Champion.query.count(),
            3,
        )

        self.assertEqual(
            result["preserved_existing"],
            1,
        )

    def test_repeated_merge_is_idempotent(
        self
    ):
        first_result = (
            self.service.merge_dataset(
                dataset=(
                    self._build_dataset()
                ),
                active_source="bundled",
            )
        )

        second_result = (
            self.service.merge_dataset(
                dataset=(
                    self._build_dataset()
                ),
                active_source="bundled",
            )
        )

        self.assertEqual(
            first_result["created"],
            2,
        )

        self.assertEqual(
            second_result["created"],
            0,
        )

        self.assertEqual(
            second_result["unchanged"],
            2,
        )

        self.assertEqual(
            Champion.query.count(),
            2,
        )

    def test_mastery_relationship_is_preserved(
        self
    ):
        champion = self._create_champion(
            riot_champion_id=1,
            name="Old Annie",
            image="OldAnnie.png",
            source="data_dragon",
        )

        mastery = self._create_mastery(
            champion=champion,
            mastery_points=456789,
        )

        db.session.commit()

        original_champion_id = (
            champion.id
        )

        original_mastery_id = (
            mastery.id
        )

        self.service.merge_dataset(
            dataset=self._build_dataset(
                champions=[
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                ]
            ),
            active_source="bundled",
        )

        refreshed_mastery = (
            ChampionMastery.query.get(
                original_mastery_id
            )
        )

        self.assertIsNotNone(
            refreshed_mastery
        )

        self.assertEqual(
            refreshed_mastery.champion_id,
            original_champion_id,
        )

        self.assertEqual(
            refreshed_mastery.mastery_points,
            456789,
        )

    def test_duplicate_dataset_id_is_rejected_without_writes(
        self
    ):
        with self.assertRaises(
            ChampionReferenceMergeError
        ):
            self.service.merge_dataset(
                dataset=self._build_dataset(
                    champions=[
                        {
                            "riot_champion_id": 1,
                            "name": "Annie",
                            "image_filename": (
                                "Annie.png"
                            ),
                        },
                        {
                            "riot_champion_id": 1,
                            "name": "Duplicate",
                            "image_filename": (
                                "Duplicate.png"
                            ),
                        },
                    ]
                ),
                active_source="bundled",
            )

        self.assertEqual(
            Champion.query.count(),
            0,
        )

    def test_invalid_active_source_is_rejected_without_writes(
        self
    ):
        with self.assertRaises(
            ChampionReferenceMergeError
        ):
            self.service.merge_dataset(
                dataset=self._build_dataset(),
                active_source="internet",
            )

        self.assertEqual(
            Champion.query.count(),
            0,
        )

    def test_database_failure_rolls_back_entire_merge(
        self
    ):
        champion = self._create_champion(
            riot_champion_id=1,
            name="Old Annie",
            image="OldAnnie.png",
            source="data_dragon",
        )

        db.session.commit()

        with patch.object(
            db.session,
            "commit",
            side_effect=RuntimeError(
                "database failure"
            ),
        ):
            with self.assertRaises(
                ChampionReferenceMergeError
            ):
                self.service.merge_dataset(
                    dataset=self._build_dataset(),
                    active_source="bundled",
                )

        db.session.expire_all()

        refreshed_champion = (
            Champion.query.filter_by(
                riot_champion_id=1
            ).one()
        )

        self.assertEqual(
            refreshed_champion.name,
            "Old Annie",
        )

        self.assertEqual(
            refreshed_champion.image,
            "OldAnnie.png",
        )

        self.assertIsNone(
            Champion.query.filter_by(
                riot_champion_id=2
            ).one_or_none()
        )

    def test_result_contains_active_dataset_metadata(
        self
    ):
        result = self.service.merge_dataset(
            dataset=self._build_dataset(),
            active_source="local_cache",
        )

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["data_dragon_version"],
            "15.14.1",
        )

        self.assertEqual(
            result["locale"],
            "en_US",
        )

        self.assertEqual(
            result["dataset_count"],
            2,
        )

        self.assertEqual(
            result["database_count"],
            2,
        )


if __name__ == "__main__":
    unittest.main()