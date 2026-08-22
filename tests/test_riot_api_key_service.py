import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from flask import Flask

from application.services.riot_api_key_service import (
    RiotApiKeyService,
    RiotApiKeyStorageError,
)


@unittest.skipUnless(
    os.name == "nt",
    "Encrypted Riot API key tests require Windows.",
)
class RiotApiKeyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()

        self.configuration_directory = Path(
            self.temporary_directory.name
        )

        self.app = Flask(
            __name__
        )

        self.app.config.update(
            TESTING=True,
            CONFIG_DIR=str(
                self.configuration_directory
            ),
            RIOT_API_KEY=None,
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

        self.environment_patch = patch.dict(
            os.environ,
            {
                "RIOT_API_KEY": "",
            },
        )

        self.environment_patch.start()

        self.api_key = (
            "RGAPI-test-key-value-"
            "1234567890ABCDEF"
        )

    def tearDown(self):
        self.environment_patch.stop()
        self.app_context.pop()
        self.temporary_directory.cleanup()

    def test_saved_key_is_encrypted_and_can_be_read(self):
        status = RiotApiKeyService.save_api_key(
            self.api_key
        )

        encrypted_file = (
            self.configuration_directory
            / "riot_api_key.dpapi"
        )

        legacy_file = (
            self.configuration_directory
            / "riot_api_key.txt"
        )

        self.assertTrue(
            encrypted_file.exists()
        )

        self.assertFalse(
            legacy_file.exists()
        )

        encrypted_bytes = (
            encrypted_file.read_bytes()
        )

        self.assertNotIn(
            self.api_key.encode("utf-8"),
            encrypted_bytes,
        )

        self.assertEqual(
            RiotApiKeyService.get_api_key(),
            self.api_key,
        )

        self.assertTrue(
            status["configured"]
        )

        self.assertEqual(
            status["source"],
            "local",
        )

        self.assertEqual(
            status["masked_key"],
            "••••••••CDEF",
        )

    def test_legacy_plaintext_key_is_migrated(self):
        legacy_file = (
            self.configuration_directory
            / "riot_api_key.txt"
        )

        encrypted_file = (
            self.configuration_directory
            / "riot_api_key.dpapi"
        )

        legacy_file.write_text(
            self.api_key,
            encoding="utf-8",
        )

        active_key = (
            RiotApiKeyService.get_api_key()
        )

        self.assertEqual(
            active_key,
            self.api_key,
        )

        self.assertTrue(
            encrypted_file.exists()
        )

        self.assertFalse(
            legacy_file.exists()
        )

        self.assertNotIn(
            self.api_key.encode("utf-8"),
            encrypted_file.read_bytes(),
        )

    def test_corrupted_encrypted_file_is_reported_safely(self):
        encrypted_file = (
            self.configuration_directory
            / "riot_api_key.dpapi"
        )

        encrypted_file.write_bytes(
            RiotApiKeyService.ENCRYPTED_FILE_HEADER
            + b"damaged-protected-data"
        )

        status = RiotApiKeyService.get_status()

        self.assertFalse(
            status["configured"]
        )

        self.assertEqual(
            status["source"],
            "local",
        )

        self.assertIsNone(
            status["masked_key"]
        )

        self.assertIsNotNone(
            status["error"]
        )

        self.assertNotIn(
            self.api_key,
            status["error"],
        )

        with self.assertRaises(
            RiotApiKeyStorageError
        ):
            RiotApiKeyService.get_api_key()

    def test_deleting_local_key_allows_environment_fallback(self):
        RiotApiKeyService.save_api_key(
            self.api_key
        )

        fallback_key = (
            "RGAPI-environment-key-"
            "FEDCBA0987654321"
        )

        with patch.dict(
            os.environ,
            {
                "RIOT_API_KEY": fallback_key,
            },
        ):
            deleted = (
                RiotApiKeyService.delete_local_api_key()
            )

            active_key = (
                RiotApiKeyService.get_api_key()
            )

        self.assertTrue(
            deleted
        )

        self.assertEqual(
            active_key,
            fallback_key,
        )

        self.assertFalse(
            (
                self.configuration_directory
                / "riot_api_key.dpapi"
            ).exists()
        )


if __name__ == "__main__":
    unittest.main()