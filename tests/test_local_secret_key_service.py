import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask

from application.services.local_secret_key_service import (
    LocalSecretKeyError,
    LocalSecretKeyService,
)


class LocalSecretKeyServiceTests(unittest.TestCase):
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
        )

        self.app_context = (
            self.app.app_context()
        )

        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()
        self.temporary_directory.cleanup()

    def test_secret_key_is_created_with_expected_length(self):
        secret_key = (
            LocalSecretKeyService
            .get_or_create_secret_key()
        )

        key_file = (
            self.configuration_directory
            / "flask_secret_key.bin"
        )

        self.assertIsInstance(
            secret_key,
            bytes,
        )

        self.assertEqual(
            len(secret_key),
            64,
        )

        self.assertTrue(
            key_file.exists()
        )

        self.assertEqual(
            key_file.read_bytes(),
            secret_key,
        )

    def test_existing_secret_key_is_reused(self):
        first_key = (
            LocalSecretKeyService
            .get_or_create_secret_key()
        )

        second_key = (
            LocalSecretKeyService
            .get_or_create_secret_key()
        )

        self.assertEqual(
            second_key,
            first_key,
        )

    def test_deleted_secret_key_is_replaced_with_new_value(self):
        first_key = (
            LocalSecretKeyService
            .get_or_create_secret_key()
        )

        key_file = (
            self.configuration_directory
            / "flask_secret_key.bin"
        )

        key_file.unlink()

        replacement_key = (
            LocalSecretKeyService
            .get_or_create_secret_key()
        )

        self.assertNotEqual(
            replacement_key,
            first_key,
        )

        self.assertEqual(
            len(replacement_key),
            64,
        )

    def test_invalid_existing_secret_key_is_rejected(self):
        key_file = (
            self.configuration_directory
            / "flask_secret_key.bin"
        )

        key_file.write_bytes(
            b"too-short"
        )

        with self.assertRaises(
            LocalSecretKeyError
        ):
            (
                LocalSecretKeyService
                .get_or_create_secret_key()
            )


if __name__ == "__main__":
    unittest.main()