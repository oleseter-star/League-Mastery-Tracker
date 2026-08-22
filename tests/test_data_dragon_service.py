import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from flask import Flask

from application.database.database import db
from application.database.models import Champion
from application.services.data_dragon_service import (
    DataDragonService,
)


class DataDragonServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.root_directory = Path(
            self.temporary_directory.name
        )

        self.database_file = (
            self.root_directory
            / "test.db"
        )

        self.reference_directory = (
            self.root_directory
            / "reference"
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
            REFERENCE_DIR=str(
                self.reference_directory
            ),
        )

        db.init_app(
            self.app
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        db.create_all()

        self.service = DataDragonService()

        self.version = "15.14.1"

    def tearDown(self):
        db.session.remove()

        db.drop_all()

        db.session.remove()
        db.engine.dispose()

        self.app_context.pop()

        self.temporary_directory.cleanup()

    def _build_champion_data(
        self,
        champion_entries=None,
        version=None,
    ):
        if champion_entries is None:
            champion_entries = {
                "Annie": {
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
                "Olaf": {
                    "key": "2",
                    "name": "Olaf",
                    "image": {
                        "full": "Olaf.png",
                    },
                },
            }

        return {
            "type": "champion",
            "format": "standAloneComplex",
            "version": (
                version
                or self.version
            ),
            "data": champion_entries,
        }

    def test_latest_version_is_read_from_data_dragon(self):
        response = Mock()

        response.json.return_value = [
            "15.14.1",
            "15.13.1",
        ]

        with patch(
            "application.services."
            "data_dragon_service."
            "requests.get",
            return_value=response,
        ) as get_mock:
            version = (
                self.service
                .get_latest_version()
            )

        self.assertEqual(
            version,
            "15.14.1",
        )

        get_mock.assert_called_once_with(
            self.service.VERSIONS_URL,
            timeout=15,
        )

        response.raise_for_status.assert_called_once_with()

    def test_invalid_version_list_is_rejected(self):
        response = Mock()

        response.json.return_value = {
            "version": "15.14.1",
        }

        with patch(
            "application.services."
            "data_dragon_service."
            "requests.get",
            return_value=response,
        ):
            with self.assertRaises(
                ValueError
            ):
                (
                    self.service
                    .get_latest_version()
                )

    def test_empty_latest_version_is_rejected(self):
        response = Mock()

        response.json.return_value = [
            "   ",
        ]

        with patch(
            "application.services."
            "data_dragon_service."
            "requests.get",
            return_value=response,
        ):
            with self.assertRaises(
                ValueError
            ):
                (
                    self.service
                    .get_latest_version()
                )

    def test_champion_data_is_downloaded_for_version(self):
        champion_data = (
            self._build_champion_data()
        )

        response = Mock()
        response.json.return_value = champion_data

        expected_url = (
            "https://ddragon.leagueoflegends.com/"
            "cdn/15.14.1/data/en_US/champion.json"
        )

        with patch(
            "application.services."
            "data_dragon_service."
            "requests.get",
            return_value=response,
        ) as get_mock:
            result = (
                self.service
                .get_champion_data(
                    self.version
                )
            )

        self.assertEqual(
            result,
            champion_data,
        )

        get_mock.assert_called_once_with(
            expected_url,
            timeout=15,
        )

        response.raise_for_status.assert_called_once_with()

    def test_champion_data_without_data_collection_is_rejected(
        self
    ):
        response = Mock()

        response.json.return_value = {
            "version": self.version,
        }

        with patch(
            "application.services."
            "data_dragon_service."
            "requests.get",
            return_value=response,
        ):
            with self.assertRaises(
                ValueError
            ):
                (
                    self.service
                    .get_champion_data(
                        self.version
                    )
                )

    def test_champion_data_creates_local_champions(self):
        result = (
            self.service
            .apply_champion_data(
                champion_data=(
                    self._build_champion_data()
                ),
                version=self.version,
            )
        )

        champions = (
            Champion.query
            .order_by(
                Champion.riot_champion_id
            )
            .all()
        )

        self.assertEqual(
            result,
            {
                "created": 2,
                "changed": 0,
                "unchanged": 0,
            },
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
            (
                "https://ddragon.leagueoflegends.com/"
                "cdn/15.14.1/img/champion/Annie.png"
            ),
        )

        self.assertEqual(
            champions[0].source,
            "data_dragon",
        )

    def test_existing_champion_is_updated(self):
        champion = Champion(
            riot_champion_id=1,
            name="Old Annie",
            image="old-image",
            source="manual",
        )

        db.session.add(
            champion
        )

        db.session.commit()

        champion_data = self._build_champion_data(
            champion_entries={
                "Annie": {
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
            }
        )

        result = (
            self.service
            .apply_champion_data(
                champion_data=champion_data,
                version=self.version,
            )
        )

        db.session.refresh(
            champion
        )

        self.assertEqual(
            result,
            {
                "created": 0,
                "changed": 1,
                "unchanged": 0,
            },
        )

        self.assertEqual(
            champion.name,
            "Annie",
        )

        self.assertEqual(
            champion.source,
            "data_dragon",
        )

    def test_unchanged_champion_is_reported(self):
        champion = Champion(
            riot_champion_id=1,
            name="Annie",
            image=(
                "https://ddragon.leagueoflegends.com/"
                "cdn/15.14.1/img/champion/Annie.png"
            ),
            source="data_dragon",
        )

        db.session.add(
            champion
        )

        db.session.commit()

        champion_data = self._build_champion_data(
            champion_entries={
                "Annie": {
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
            }
        )

        result = (
            self.service
            .apply_champion_data(
                champion_data=champion_data,
                version=self.version,
            )
        )

        self.assertEqual(
            result,
            {
                "created": 0,
                "changed": 0,
                "unchanged": 1,
            },
        )

    def test_champion_absent_from_data_dragon_is_preserved(
        self
    ):
        unknown_champion = Champion(
            riot_champion_id=999999,
            name=None,
            image=None,
            source="manual",
        )

        db.session.add(
            unknown_champion
        )

        db.session.commit()

        self.service.apply_champion_data(
            champion_data=(
                self._build_champion_data()
            ),
            version=self.version,
        )

        preserved_champion = (
            Champion.query
            .filter_by(
                riot_champion_id=999999
            )
            .one_or_none()
        )

        self.assertIsNotNone(
            preserved_champion
        )

        self.assertIsNone(
            preserved_champion.name
        )

    def test_invalid_entry_rolls_back_all_database_changes(
        self
    ):
        champion_data = self._build_champion_data(
            champion_entries={
                "Annie": {
                    "key": "1",
                    "name": "Annie",
                    "image": {
                        "full": "Annie.png",
                    },
                },
                "Broken": {
                    "key": "not-an-id",
                    "name": "Broken",
                    "image": {
                        "full": "Broken.png",
                    },
                },
            }
        )

        with self.assertRaises(
            ValueError
        ):
            (
                self.service
                .apply_champion_data(
                    champion_data=champion_data,
                    version=self.version,
                )
            )

        self.assertEqual(
            Champion.query.count(),
            0,
        )

    def test_reference_cache_can_be_saved_and_loaded(self):
        champion_data = (
            self._build_champion_data()
        )

        self.service.save_reference_cache(
            version=self.version,
            champion_data=champion_data,
        )

        loaded_data = (
            self.service
            .load_cached_champion_data()
        )

        cached_version = (
            self.service
            .get_cached_version()
        )

        self.assertEqual(
            loaded_data,
            champion_data,
        )

        self.assertEqual(
            cached_version,
            self.version,
        )

        reference_directory = (
            self.reference_directory
            / "data_dragon"
        )

        self.assertTrue(
            (
                reference_directory
                / "champions.json"
            ).exists()
        )

        self.assertTrue(
            (
                reference_directory
                / "version.txt"
            ).exists()
        )

        self.assertFalse(
            (
                reference_directory
                / "champions.json.tmp"
            ).exists()
        )

        self.assertFalse(
            (
                reference_directory
                / "version.txt.tmp"
            ).exists()
        )

    def test_current_cache_without_repairs_skips_download(
        self
    ):
        champion_data = (
            self._build_champion_data()
        )

        self.service.apply_champion_data(
            champion_data=champion_data,
            version=self.version,
        )

        self.service.save_reference_cache(
            version=self.version,
            champion_data=champion_data,
        )

        with patch.object(
            self.service,
            "get_latest_version",
            return_value=self.version,
        ), patch.object(
            self.service,
            "get_champion_data",
        ) as download_mock:
            result = (
                self.service
                .refresh_reference_data()
            )

        self.assertFalse(
            result["updated"]
        )

        self.assertFalse(
            result["repaired_from_cache"]
        )

        self.assertEqual(
            result["version"],
            self.version,
        )

        download_mock.assert_not_called()

    def test_current_cache_repairs_missing_local_champions(
        self
    ):
        champion_data = (
            self._build_champion_data()
        )

        self.service.save_reference_cache(
            version=self.version,
            champion_data=champion_data,
        )

        with patch.object(
            self.service,
            "get_latest_version",
            return_value=self.version,
        ), patch.object(
            self.service,
            "get_champion_data",
        ) as download_mock:
            result = (
                self.service
                .refresh_reference_data()
            )

        self.assertTrue(
            result["updated"]
        )

        self.assertTrue(
            result["repaired_from_cache"]
        )

        self.assertEqual(
            result["created"],
            2,
        )

        self.assertEqual(
            Champion.query.count(),
            2,
        )

        download_mock.assert_not_called()

    def test_new_version_is_downloaded_applied_and_cached(
        self
    ):
        champion_data = (
            self._build_champion_data()
        )

        with patch.object(
            self.service,
            "get_latest_version",
            return_value=self.version,
        ), patch.object(
            self.service,
            "get_champion_data",
            return_value=champion_data,
        ) as download_mock:
            result = (
                self.service
                .refresh_reference_data()
            )

        self.assertTrue(
            result["updated"]
        )

        self.assertFalse(
            result["repaired_from_cache"]
        )

        self.assertEqual(
            result["created"],
            2,
        )

        self.assertEqual(
            self.service.get_cached_version(),
            self.version,
        )

        self.assertEqual(
            (
                self.service
                .load_cached_champion_data()
            ),
            champion_data,
        )

        download_mock.assert_called_once_with(
            self.version
        )

    def test_force_refresh_downloads_current_version_again(
        self
    ):
        champion_data = (
            self._build_champion_data()
        )

        self.service.apply_champion_data(
            champion_data=champion_data,
            version=self.version,
        )

        self.service.save_reference_cache(
            version=self.version,
            champion_data=champion_data,
        )

        with patch.object(
            self.service,
            "get_latest_version",
            return_value=self.version,
        ), patch.object(
            self.service,
            "get_champion_data",
            return_value=champion_data,
        ) as download_mock:
            result = (
                self.service
                .refresh_reference_data(
                    force=True
                )
            )

        self.assertTrue(
            result["updated"]
        )

        self.assertFalse(
            result["repaired_from_cache"]
        )

        self.assertEqual(
            result["unchanged"],
            2,
        )

        download_mock.assert_called_once_with(
            self.version
        )

    def test_version_with_unsupported_characters_is_rejected(
        self
    ):
        with self.assertRaises(
            ValueError
        ):
            (
                self.service
                .get_champion_data(
                    "../15.14.1"
                )
            )


if __name__ == "__main__":
    unittest.main()