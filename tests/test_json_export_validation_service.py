import copy
import unittest

from application.services.json_export_validation_service import (
    JsonExportValidationError,
    JsonExportValidationService,
)


class JsonExportValidationServiceTests(unittest.TestCase):
    def _build_valid_document(self):
        return {
            "format": (
                "league-mastery-tracker-export"
            ),
            "format_version": 1,
            "database_schema_version": 1,
            "exported_at": (
                "2026-07-16T15:00:00Z"
            ),
            "record_counts": {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 2,
                "mastery_records": 2,
            },
            "data": {
                "champions": [
                    {
                        "riot_champion_id": 22,
                        "name": "Ashe",
                        "image": "Ashe.png",
                        "source": "data_dragon",
                    },
                    {
                        "riot_champion_id": 266,
                        "name": "Aatrox",
                        "image": "Aatrox.png",
                        "source": "data_dragon",
                    },
                ],
                "persons": [
                    {
                        "display_name": (
                            "Validation Person"
                        ),
                        "riot_accounts": [
                            {
                                "game_name": (
                                    "ValidationPlayer"
                                ),
                                "tag_line": "EUW",
                                "puuid": (
                                    "validation-puuid"
                                ),
                                "platform_region": (
                                    "euw1"
                                ),
                                "last_sync": (
                                    "2026-07-16T14:00:00Z"
                                ),
                                "champion_mastery": [
                                    {
                                        "riot_champion_id": 22,
                                        "mastery_points": 1000,
                                    },
                                    {
                                        "riot_champion_id": 266,
                                        "mastery_points": 500,
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
        }

    def test_valid_document_is_accepted(self):
        document = self._build_valid_document()

        actual_counts = (
            JsonExportValidationService
            .validate_document(
                document
            )
        )

        self.assertEqual(
            actual_counts,
            {
                "persons": 1,
                "riot_accounts": 1,
                "champions": 2,
                "mastery_records": 2,
            },
        )

    def test_invalid_format_identifier_is_rejected(self):
        document = self._build_valid_document()

        document["format"] = (
            "some-other-format"
        )

        with self.assertRaises(
            JsonExportValidationError
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_unsupported_format_version_is_rejected(self):
        document = self._build_valid_document()

        document["format_version"] = 999

        with self.assertRaises(
            JsonExportValidationError
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_incorrect_record_count_is_rejected(self):
        document = self._build_valid_document()

        document[
            "record_counts"
        ]["mastery_records"] = 999

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "mastery_records",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_duplicate_champion_id_is_rejected(self):
        document = self._build_valid_document()

        duplicate_champion = copy.deepcopy(
            document[
                "data"
            ]["champions"][0]
        )

        document[
            "data"
        ]["champions"].append(
            duplicate_champion
        )

        document[
            "record_counts"
        ]["champions"] = 3

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "duplicate Riot champion ID",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_duplicate_puuid_is_rejected(self):
        document = self._build_valid_document()

        duplicate_person = {
            "display_name": (
                "Second Person"
            ),
            "riot_accounts": [
                copy.deepcopy(
                    document[
                        "data"
                    ]["persons"][0][
                        "riot_accounts"
                    ][0]
                )
            ],
        }

        document[
            "data"
        ]["persons"].append(
            duplicate_person
        )

        document[
            "record_counts"
        ]["persons"] = 2

        document[
            "record_counts"
        ]["riot_accounts"] = 2

        document[
            "record_counts"
        ]["mastery_records"] = 4

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "duplicate PUUID",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_missing_mastery_champion_is_rejected(self):
        document = self._build_valid_document()

        document[
            "data"
        ]["persons"][0][
            "riot_accounts"
        ][0][
            "champion_mastery"
        ][0][
            "riot_champion_id"
        ] = 999999

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "missing Riot champion ID",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_duplicate_mastery_for_account_is_rejected(self):
        document = self._build_valid_document()

        document[
            "data"
        ]["persons"][0][
            "riot_accounts"
        ][0][
            "champion_mastery"
        ][1][
            "riot_champion_id"
        ] = 22

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "duplicate mastery",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_invalid_utc_timestamp_is_rejected(self):
        document = self._build_valid_document()

        document["exported_at"] = (
            "2026-07-16T15:00:00+02:00"
        )

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "ending in Z",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

    def test_invalid_last_sync_uses_synchronized_terminology(self):
        document = self._build_valid_document()

        document[
            "data"
        ]["persons"][0][
            "riot_accounts"
        ][0][
            "last_sync"
        ] = "not-a-timestampZ"

        with self.assertRaises(
            JsonExportValidationError
        ) as raised_error:
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

        self.assertEqual(
            str(
                raised_error.exception
            ),
            (
                "Person at index 0, Riot account at index 0 "
                "last-synchronized timestamp is not a valid "
                "timestamp."
            ),
        )

    def test_negative_mastery_points_are_rejected(self):
        document = self._build_valid_document()

        document[
            "data"
        ]["persons"][0][
            "riot_accounts"
        ][0][
            "champion_mastery"
        ][0][
            "mastery_points"
        ] = -1

        with self.assertRaisesRegex(
            JsonExportValidationError,
            "non-negative integer",
        ):
            (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )