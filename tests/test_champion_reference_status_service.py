import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from application.database.database import db
from application.database.models import Champion
from application.services.champion_reference_status_service import (
    ChampionReferenceStatusService,
)


class ChampionReferenceStatusServiceTests(
    unittest.TestCase
):
    def setUp(self):
        self.temporary_directory = (
            TemporaryDirectory()
        )

        self.database_file = (
            Path(
                self.temporary_directory.name
            )
            / "champion-reference-status.db"
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
            STARTUP_CHAMPION_REFERENCE_RESULT=None,
            CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE=None,
            CHAMPION_REFERENCE_LAST_UPDATE_ERROR=None,
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
            ChampionReferenceStatusService()
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
    def _create_champion(
        riot_champion_id,
        name,
        image,
        source="data_dragon",
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

    def _set_startup_result(
        self,
        *,
        active_source="bundled",
        reference_data_available=True,
        database_fallback=False,
        version="15.14.1",
        locale="en_US",
        dataset_count=2,
        generated_at=(
            "2026-07-23T12:30:45+00:00"
        ),
        warnings=None,
    ):
        self.app.config[
            "STARTUP_CHAMPION_REFERENCE_RESULT"
        ] = {
            "active_source": active_source,
            "reference_data_available": (
                reference_data_available
            ),
            "database_fallback": (
                database_fallback
            ),
            "data_dragon_version": version,
            "locale": locale,
            "generated_at": generated_at,
            "dataset_directory": (
                "C:\\private\\bundled"
            ),
            "icons_directory": (
                "C:\\private\\bundled\\champion_icons"
            ),
            "warnings": list(
                warnings
                or []
            ),
            "merge": (
                {
                    "dataset_count": (
                        dataset_count
                    ),
                    "database_count": (
                        dataset_count
                    ),
                }
                if reference_data_available
                else None
            ),
        }

    def test_bundled_source_status_is_returned(
        self,
    ):
        self._set_startup_result(
            active_source="bundled",
            dataset_count=2,
        )

        self._create_champion(
            riot_champion_id=1,
            name="Annie",
            image="Annie.png",
        )

        self._create_champion(
            riot_champion_id=2,
            name="Olaf",
            image="Olaf.png",
        )

        db.session.commit()

        result = self.service.get_status()

        self.assertEqual(
            result["active_source"],
            "bundled",
        )

        self.assertEqual(
            result["active_source_label"],
            "Bundled dataset",
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
            result["dataset_champion_count"],
            2,
        )

        self.assertEqual(
            result["database_champion_count"],
            2,
        )

        self.assertTrue(
            result["uses_bundled_fallback"]
        )

        self.assertFalse(
            result["uses_local_cache"]
        )

        self.assertFalse(
            result["database_only"]
        )

    def test_local_cache_source_flags_are_returned(
        self,
    ):
        self._set_startup_result(
            active_source="local_cache",
        )

        result = self.service.get_status()

        self.assertEqual(
            result["active_source"],
            "local_cache",
        )

        self.assertEqual(
            result["active_source_label"],
            "Local cache",
        )

        self.assertFalse(
            result["uses_bundled_fallback"]
        )

        self.assertTrue(
            result["uses_local_cache"]
        )

        self.assertFalse(
            result["database_only"]
        )

    def test_database_fallback_is_normalized(
        self,
    ):
        self._set_startup_result(
            active_source="database",
            reference_data_available=False,
            database_fallback=True,
            version=None,
            locale=None,
            dataset_count=0,
            generated_at=None,
        )

        result = self.service.get_status()

        self.assertEqual(
            result["active_source"],
            "database_only",
        )

        self.assertEqual(
            result["active_source_label"],
            "Database-only fallback",
        )

        self.assertFalse(
            result["uses_bundled_fallback"]
        )

        self.assertFalse(
            result["uses_local_cache"]
        )

        self.assertTrue(
            result["database_only"]
        )

        self.assertIsNone(
            result["data_dragon_version"]
        )

        self.assertIsNone(
            result["locale"]
        )

        self.assertIsNone(
            result["dataset_champion_count"]
        )

    def test_database_count_uses_current_database(
        self,
    ):
        self._set_startup_result(
            dataset_count=170,
        )

        self._create_champion(
            riot_champion_id=1,
            name="Annie",
            image="Annie.png",
        )

        self._create_champion(
            riot_champion_id=2,
            name="Olaf",
            image="Olaf.png",
        )

        self._create_champion(
            riot_champion_id=999999,
            name=None,
            image=None,
            source="riot_api",
        )

        db.session.commit()

        result = self.service.get_status()

        self.assertEqual(
            result["dataset_champion_count"],
            170,
        )

        self.assertEqual(
            result["database_champion_count"],
            3,
        )

    def test_missing_name_is_counted(
        self,
    ):
        self._create_champion(
            riot_champion_id=1,
            name=None,
            image="Unknown.png",
            source="riot_api",
        )

        self._create_champion(
            riot_champion_id=2,
            name="   ",
            image="Olaf.png",
        )

        db.session.commit()

        result = self.service.get_status()

        self.assertEqual(
            result["missing_name_count"],
            2,
        )

        self.assertTrue(
            result["has_missing_metadata"]
        )

    def test_missing_image_is_counted(
        self,
    ):
        self._create_champion(
            riot_champion_id=1,
            name="Annie",
            image=None,
        )

        self._create_champion(
            riot_champion_id=2,
            name="Olaf",
            image="   ",
        )

        db.session.commit()

        result = self.service.get_status()

        self.assertEqual(
            result["missing_image_count"],
            2,
        )

        self.assertTrue(
            result["has_missing_metadata"]
        )

    def test_missing_metadata_union_is_not_double_counted(
        self,
    ):
        self._create_champion(
            riot_champion_id=1,
            name=None,
            image=None,
            source="riot_api",
        )

        self._create_champion(
            riot_champion_id=2,
            name="Olaf",
            image=None,
        )

        self._create_champion(
            riot_champion_id=3,
            name=None,
            image="Unknown.png",
            source="riot_api",
        )

        db.session.commit()

        result = self.service.get_status()

        self.assertEqual(
            result["missing_name_count"],
            2,
        )

        self.assertEqual(
            result["missing_image_count"],
            2,
        )

        self.assertEqual(
            result["missing_metadata_count"],
            3,
        )

    def test_complete_metadata_reports_no_missing_data(
        self,
    ):
        self._create_champion(
            riot_champion_id=1,
            name="Annie",
            image="Annie.png",
        )

        db.session.commit()

        result = self.service.get_status()

        self.assertEqual(
            result["missing_name_count"],
            0,
        )

        self.assertEqual(
            result["missing_image_count"],
            0,
        )

        self.assertEqual(
            result["missing_metadata_count"],
            0,
        )

        self.assertFalse(
            result["has_missing_metadata"]
        )

    def test_startup_generated_timestamp_is_used(
        self,
    ):
        self._set_startup_result(
            generated_at=(
                "2026-07-23T12:30:45+00:00"
            )
        )

        result = self.service.get_status()

        self.assertEqual(
            result["last_successful_update"],
            "2026-07-23T12:30:45+00:00",
        )

    def test_manual_update_timestamp_overrides_startup_timestamp(
        self,
    ):
        self._set_startup_result(
            generated_at=(
                "2026-07-23T12:30:45+00:00"
            )
        )

        self.app.config[
            "CHAMPION_REFERENCE_LAST_SUCCESSFUL_UPDATE"
        ] = (
            "2026-07-23T16:45:00+00:00"
        )

        result = self.service.get_status()

        self.assertEqual(
            result["last_successful_update"],
            "2026-07-23T16:45:00+00:00",
        )

    def test_last_controlled_update_error_is_returned(
        self,
    ):
        self.app.config[
            "CHAMPION_REFERENCE_LAST_UPDATE_ERROR"
        ] = (
            "Champion reference data could not be updated."
        )

        result = self.service.get_status()

        self.assertEqual(
            result["last_update_error"],
            "Champion reference data could not be updated.",
        )

    def test_missing_startup_result_uses_safe_database_status(
        self,
    ):
        self.app.config[
            "STARTUP_CHAMPION_REFERENCE_RESULT"
        ] = None

        result = self.service.get_status()

        self.assertEqual(
            result["active_source"],
            "database_only",
        )

        self.assertEqual(
            result["active_source_label"],
            "Database-only fallback",
        )

        self.assertTrue(
            result["database_only"]
        )

        self.assertIsNone(
            result["data_dragon_version"]
        )

        self.assertIsNone(
            result["locale"]
        )

        self.assertIsNone(
            result["dataset_champion_count"]
        )

        self.assertEqual(
            result["warnings"],
            [],
        )

    def test_internal_paths_are_not_exposed(
        self,
    ):
        self._set_startup_result()

        result = self.service.get_status()

        self.assertNotIn(
            "dataset_directory",
            result,
        )

        self.assertNotIn(
            "icons_directory",
            result,
        )

        serialized_result = repr(
            result
        )

        self.assertNotIn(
            "C:\\private",
            serialized_result,
        )


if __name__ == "__main__":
    unittest.main()