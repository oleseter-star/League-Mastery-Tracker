import io
import unittest
from contextlib import (
    redirect_stderr,
    redirect_stdout,
)
from unittest.mock import patch

import build_champion_reference_bundle
from application.services.champion_reference_bundle_build_service import (
    ChampionReferenceBundleBuildError,
)


class BuildChampionReferenceBundleTests(
    unittest.TestCase
):
    def setUp(self):
        self.build_result = {
            "status": "built",
            "data_dragon_version": (
                "15.15.1"
            ),
            "dataset_directory": (
                "C:\\private\\bundled_reference_data"
            ),
            "dataset": {
                "manifest": {
                    "data_dragon_version": (
                        "15.15.1"
                    ),
                    "locale": "en_US",
                    "champion_count": 170,
                },
                "champions": [
                    {
                        "riot_champion_id": 1,
                        "name": "Annie",
                        "image_filename": (
                            "Annie.png"
                        ),
                    },
                ],
            },
        }

    def test_main_builds_bundled_dataset(
        self,
    ):
        with patch.object(
            build_champion_reference_bundle,
            "ChampionReferenceBundleBuildService",
        ) as service_class:
            service = (
                service_class.return_value
            )

            service.build_bundled_dataset.return_value = (
                self.build_result
            )

            standard_output = io.StringIO()

            with redirect_stdout(
                standard_output
            ):
                exit_code = (
                    build_champion_reference_bundle
                    .main()
                )

        service_class.assert_called_once_with()

        service.build_bundled_dataset.assert_called_once_with()

        self.assertEqual(
            exit_code,
            0,
        )

    def test_success_output_contains_version_locale_and_count(
        self,
    ):
        with patch.object(
            build_champion_reference_bundle,
            "ChampionReferenceBundleBuildService",
        ) as service_class:
            service_class.return_value.build_bundled_dataset.return_value = (
                self.build_result
            )

            standard_output = io.StringIO()

            with redirect_stdout(
                standard_output
            ):
                build_champion_reference_bundle.main()

        output = standard_output.getvalue()

        self.assertIn(
            (
                "The bundled champion reference "
                "dataset was built."
            ),
            output,
        )

        self.assertIn(
            "Data Dragon version: 15.15.1",
            output,
        )

        self.assertIn(
            "Locale: en_US",
            output,
        )

        self.assertIn(
            "Champion count: 170",
            output,
        )

    def test_success_output_does_not_expose_internal_path(
        self,
    ):
        with patch.object(
            build_champion_reference_bundle,
            "ChampionReferenceBundleBuildService",
        ) as service_class:
            service_class.return_value.build_bundled_dataset.return_value = (
                self.build_result
            )

            standard_output = io.StringIO()

            with redirect_stdout(
                standard_output
            ):
                build_champion_reference_bundle.main()

        output = standard_output.getvalue()

        self.assertNotIn(
            "C:\\private",
            output,
        )

        self.assertNotIn(
            "bundled_reference_data",
            output,
        )

    def test_controlled_build_failure_returns_error_exit_code(
        self,
    ):
        with patch.object(
            build_champion_reference_bundle,
            "ChampionReferenceBundleBuildService",
        ) as service_class:
            service_class.return_value.build_bundled_dataset.side_effect = (
                ChampionReferenceBundleBuildError(
                    "C:\\private\\manifest.json"
                )
            )

            error_output = io.StringIO()

            with redirect_stderr(
                error_output
            ):
                exit_code = (
                    build_champion_reference_bundle
                    .main()
                )

        self.assertEqual(
            exit_code,
            1,
        )

        output = error_output.getvalue()

        self.assertIn(
            (
                "The bundled champion reference "
                "dataset could not be built."
            ),
            output,
        )

        self.assertNotIn(
            "C:\\private",
            output,
        )

        self.assertNotIn(
            "manifest.json",
            output,
        )

    def test_invalid_build_result_returns_error_exit_code(
        self,
    ):
        with patch.object(
            build_champion_reference_bundle,
            "ChampionReferenceBundleBuildService",
        ) as service_class:
            service_class.return_value.build_bundled_dataset.return_value = (
                {
                    "status": "built",
                    "dataset": None,
                }
            )

            error_output = io.StringIO()

            with redirect_stderr(
                error_output
            ):
                exit_code = (
                    build_champion_reference_bundle
                    .main()
                )

        self.assertEqual(
            exit_code,
            1,
        )

        self.assertIn(
            (
                "The bundled champion reference "
                "dataset could not be built."
            ),
            error_output.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()