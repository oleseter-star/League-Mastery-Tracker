import os
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from flask import Flask

from application.services.riot_api_key_service import (
    RiotApiKeyService,
    RiotApiKeyStorageError,
)
from application.services.linux_secret_service import (
    LinuxSecretService,
    LinuxSecretServiceStorageError,
)


class _FakeSecretServiceItem:
    def __init__(
        self,
        collection,
        attributes,
        secret,
    ):
        self.collection = collection
        self.attributes = dict(attributes)
        self.secret = secret
        self.deleted = False

    def get_secret(self):
        return self.secret

    def delete(self):
        self.deleted = True
        self.collection.items.remove(self)


class _FakeSecretServiceCollection:
    def __init__(self):
        self.items = []
        self.locked = False
        self.create_item = Mock(
            side_effect=self._create_item
        )

    def is_locked(self):
        return self.locked

    def search_items(self, attributes):
        return (
            item
            for item in self.items
            if item.attributes == dict(attributes)
        )

    def _create_item(
        self,
        label,
        attributes,
        secret,
        replace=False,
    ):
        if replace:
            for item in list(
                self.search_items(attributes)
            ):
                item.delete()

        item = _FakeSecretServiceItem(
            self,
            attributes,
            secret,
        )
        self.items.append(item)
        return item


class _FakeSecretStorage:
    def __init__(self):
        self.collection = _FakeSecretServiceCollection()
        self.dbus_init = Mock(
            return_value=object()
        )
        self.get_default_collection = Mock(
            return_value=self.collection
        )

    def module(self):
        return types.SimpleNamespace(
            dbus_init=self.dbus_init,
            get_default_collection=(
                self.get_default_collection
            ),
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


class LinuxRiotApiKeyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.configuration_directory = Path(
            self.temporary_directory.name
        ) / "configuration"
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            CONFIG_DIR=str(
                self.configuration_directory
            ),
            RIOT_API_KEY=None,
        )
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.environment_patch = patch.dict(
            os.environ,
            {"RIOT_API_KEY": ""},
        )
        self.environment_patch.start()
        self.api_key = (
            "RGAPI-linux-secret-value-"
            "1234567890ABCDEF"
        )

    def tearDown(self):
        self.environment_patch.stop()
        self.app_context.pop()
        self.temporary_directory.cleanup()

    def _linux_boundary(self, backend):
        stack = ExitStack()
        stack.enter_context(
            patch.object(
                sys,
                "platform",
                "linux",
            )
        )
        stack.enter_context(
            patch.dict(
                sys.modules,
                {"secretstorage": backend.module()},
            )
        )
        return stack

    def _application_items(self, backend):
        attributes = (
            RiotApiKeyService
            .SECRET_SERVICE_ATTRIBUTES
        )
        return list(
            backend.collection.search_items(
                attributes
            )
        )

    def _call_or_fail(self, callback):
        try:
            return callback()
        except Exception as error:
            self.fail(
                "Linux Secret Service operation failed: "
                f"{error}"
            )

    def _persistent_storage_status_or_fail(self):
        self.assertTrue(
            hasattr(
                RiotApiKeyService,
                "get_persistent_storage_status",
            )
        )
        return RiotApiKeyService.get_persistent_storage_status()

    def test_linux_save_uses_secret_service_not_dpapi_or_file(self):
        backend = _FakeSecretStorage()

        with self._linux_boundary(backend), patch(
            "application.services.riot_api_key_service."
            "WindowsDpapiService.protect",
            side_effect=AssertionError(
                "Linux must not invoke DPAPI"
            ),
        ):
            status = self._call_or_fail(
                lambda: RiotApiKeyService.save_api_key(
                    self.api_key
                )
            )

        self.assertEqual(
            status["source"],
            "local",
        )
        self.assertEqual(
            len(self._application_items(backend)),
            1,
        )
        self.assertFalse(
            (
                self.configuration_directory
                / "riot_api_key.dpapi"
            ).exists()
        )

    def test_linux_read_returns_secret_service_key(self):
        backend = _FakeSecretStorage()

        with self._linux_boundary(backend):
            self._call_or_fail(
                lambda: RiotApiKeyService.save_api_key(
                    self.api_key
                )
            )
            active_key = self._call_or_fail(
                RiotApiKeyService.get_api_key
            )

        self.assertEqual(active_key, self.api_key)

    def test_linux_read_empty_generator_returns_none_without_diagnostic(
        self,
    ):
        backend = _FakeSecretStorage()
        backend.collection.search_items = Mock(
            return_value=iter(())
        )
        stderr = StringIO()

        with self._linux_boundary(backend), redirect_stderr(stderr):
            result = LinuxSecretService.read_api_key()

        self.assertIsNone(result)
        backend.collection.search_items.assert_called_once_with(
            LinuxSecretService.ITEM_ATTRIBUTES
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_linux_read_consumes_one_unlocked_generator_item(self):
        backend = _FakeSecretStorage()
        item = _FakeSecretServiceItem(
            backend.collection,
            LinuxSecretService.ITEM_ATTRIBUTES,
            self.api_key.encode("utf-8"),
        )
        item.get_secret = Mock(return_value=item.secret)
        yielded = []

        def items(attributes):
            self.assertEqual(
                attributes,
                LinuxSecretService.ITEM_ATTRIBUTES,
            )
            yielded.append(item)
            yield item
            raise AssertionError("read must not consume another item")

        backend.collection.search_items = Mock(side_effect=items)
        stderr = StringIO()

        with self._linux_boundary(backend), redirect_stderr(stderr):
            result = LinuxSecretService.read_api_key()

        self.assertEqual(result, self.api_key)
        self.assertEqual(yielded, [item])
        item.get_secret.assert_called_once_with()
        self.assertEqual(stderr.getvalue(), "")

    def test_linux_read_locked_generator_item_is_redacted(self):
        backend = _FakeSecretStorage()
        item = _FakeSecretServiceItem(
            backend.collection,
            LinuxSecretService.ITEM_ATTRIBUTES,
            self.api_key.encode("utf-8"),
        )
        locked_error = RuntimeError(
            "locked-item backend detail RGAPI-secret-marker"
        )
        item.get_secret = Mock(side_effect=locked_error)
        backend.collection.items.append(item)
        stderr = StringIO()

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {
                LinuxSecretService.DIAGNOSTIC_ENVIRONMENT_VARIABLE: "1",
            },
        ), redirect_stderr(stderr):
            with self.assertRaises(
                LinuxSecretServiceStorageError
            ) as raised:
                LinuxSecretService.read_api_key()

        self.assertEqual(
            str(raised.exception),
            "The stored Riot API key could not be read safely.",
        )
        self.assertIs(raised.exception.__cause__, locked_error)
        item.get_secret.assert_called_once_with()
        self.assertEqual(
            stderr.getvalue(),
            "Linux Secret Service diagnostic: operation=read "
            "phase=get-secret exception=builtins.RuntimeError\n",
        )
        self.assertNotIn("locked-item", stderr.getvalue())
        self.assertNotIn("RGAPI-secret-marker", stderr.getvalue())

    def test_linux_stored_key_precedes_environment_key(self):
        backend = _FakeSecretStorage()
        environment_key = (
            "RGAPI-environment-linux-key-"
            "ABCDEF1234567890"
        )

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {"RIOT_API_KEY": environment_key},
        ):
            self._call_or_fail(
                lambda: RiotApiKeyService.save_api_key(
                    self.api_key
                )
            )
            active_key = self._call_or_fail(
                RiotApiKeyService.get_api_key
            )

        self.assertEqual(active_key, self.api_key)

    def test_linux_delete_removes_only_exact_application_item(self):
        backend = _FakeSecretStorage()
        unrelated = _FakeSecretServiceItem(
            backend.collection,
            {"product": "unrelated"},
            b"unrelated-secret",
        )
        backend.collection.items.append(unrelated)

        with self._linux_boundary(backend):
            application_item = _FakeSecretServiceItem(
                backend.collection,
                {
                    "application": "LeagueMasteryTracker",
                    "secret": "RiotApiKey",
                },
                self.api_key.encode("utf-8"),
            )
            backend.collection.items.append(application_item)
            deleted = self._call_or_fail(
                RiotApiKeyService.delete_local_api_key
            )

        self.assertTrue(deleted)
        self.assertEqual(self._application_items(backend), [])
        self.assertEqual(backend.collection.items, [unrelated])

    def test_linux_missing_item_has_no_local_key(self):
        backend = _FakeSecretStorage()

        with self._linux_boundary(backend):
            active_key = RiotApiKeyService.get_api_key()
            status = RiotApiKeyService.get_status()

        self.assertIsNone(active_key)
        self.assertFalse(status["configured"])
        self.assertIsNone(status["error"])

    def test_linux_empty_secret_service_uses_environment_key(self):
        backend = _FakeSecretStorage()
        environment_key = (
            "RGAPI-environment-linux-key-"
            "ABCDEF1234567890"
        )
        backend.collection.search_items = Mock(
            wraps=backend.collection.search_items
        )

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {"RIOT_API_KEY": environment_key},
        ), patch(
            "application.services.riot_api_key_service."
            "WindowsDpapiService.protect",
            side_effect=AssertionError(
                "Linux must not invoke DPAPI"
            ),
        ) as protect, patch(
            "application.services.riot_api_key_service."
            "WindowsDpapiService.unprotect",
            side_effect=AssertionError(
                "Linux must not invoke DPAPI"
            ),
        ) as unprotect:
            active_key = RiotApiKeyService.get_api_key()
            status = RiotApiKeyService.get_status()

        self.assertEqual(active_key, environment_key)
        self.assertEqual(status["source"], "environment")
        self.assertEqual(status["masked_key"], "••••••••7890")
        self.assertIsNone(status["error"])
        self.assertEqual(
            backend.collection.search_items.call_count,
            2,
        )
        backend.collection.create_item.assert_not_called()
        protect.assert_not_called()
        unprotect.assert_not_called()
        self.assertEqual(backend.collection.items, [])
        self.assertFalse(self.configuration_directory.exists())

    def test_linux_save_replaces_existing_application_item(self):
        backend = _FakeSecretStorage()
        replacement_key = (
            "RGAPI-linux-replacement-key-"
            "FEDCBA0987654321"
        )

        with self._linux_boundary(backend):
            self._call_or_fail(
                lambda: RiotApiKeyService.save_api_key(
                    self.api_key
                )
            )
            self._call_or_fail(
                lambda: RiotApiKeyService.save_api_key(
                    replacement_key
                )
            )

        items = self._application_items(backend)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].secret, replacement_key.encode("utf-8"))
        self.assertTrue(
            backend.collection.create_item.call_args.kwargs[
                "replace"
            ]
        )

    def test_environment_key_remains_usable_when_linux_storage_unavailable(
        self,
    ):
        backend = _FakeSecretStorage()
        unavailable_error = RuntimeError(
            "synthetic-dbus-address /tmp/synthetic-keyring "
            "RGAPI-secret-marker BackendClass Traceback"
        )
        backend.dbus_init.side_effect = unavailable_error
        environment_key = (
            "RGAPI-environment-linux-key-"
            "ABCDEF1234567890"
        )

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {"RIOT_API_KEY": environment_key},
        ):
            active_key = RiotApiKeyService.get_api_key()
            status = RiotApiKeyService.get_status()

        self.assertEqual(active_key, environment_key)
        self.assertEqual(status["source"], "environment")
        self.assertIsNone(status["error"])

    def test_missing_secretstorage_is_controlled_unavailability(self):
        with patch.object(sys, "platform", "linux"), patch.dict(
            sys.modules,
            {"secretstorage": None},
        ):
            with self.assertRaises(RiotApiKeyStorageError) as raised:
                RiotApiKeyService.save_api_key(self.api_key)

            status = self._persistent_storage_status_or_fail()

        self.assertFalse(status["available"])
        self.assertIsNotNone(status["error"])
        self.assertNotIn("secretstorage", str(raised.exception).lower())

    def test_unreachable_secret_service_is_controlled_and_redacted(self):
        backend = _FakeSecretStorage()
        backend.dbus_init.side_effect = RuntimeError(
            "synthetic-dbus-address /tmp/synthetic-keyring "
            "RGAPI-secret-marker BackendClass Traceback"
        )

        with self._linux_boundary(backend):
            with self.assertRaises(RiotApiKeyStorageError) as raised:
                RiotApiKeyService.save_api_key(self.api_key)

            status = self._persistent_storage_status_or_fail()

        self.assertFalse(status["available"])
        for marker in (
            "synthetic-dbus-address",
            "/tmp/synthetic-keyring",
            "RGAPI-secret-marker",
            "BackendClass",
            "Traceback",
        ):
            self.assertNotIn(marker, str(raised.exception))
            self.assertNotIn(marker, status["error"])

    def test_locked_collection_is_unavailable_without_unlocking(self):
        backend = _FakeSecretStorage()
        backend.collection.locked = True
        backend.collection.unlock = Mock()

        with self._linux_boundary(backend):
            with self.assertRaises(RiotApiKeyStorageError):
                RiotApiKeyService.save_api_key(self.api_key)

            status = self._persistent_storage_status_or_fail()

        self.assertFalse(status["available"])
        backend.collection.unlock.assert_not_called()

    def test_collection_lock_check_failure_has_accurate_diagnostic_phase(
        self,
    ):
        backend = _FakeSecretStorage()
        raw_error = RuntimeError(
            "sensitive-backend-detail RGAPI-secret-marker"
        )
        backend.collection.is_locked = Mock(side_effect=raw_error)
        backend.collection.search_items = Mock()
        stderr = StringIO()

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {
                LinuxSecretService.DIAGNOSTIC_ENVIRONMENT_VARIABLE: "1",
            },
        ), redirect_stderr(stderr):
            with self.assertRaises(
                LinuxSecretServiceStorageError
            ) as raised:
                LinuxSecretService.read_api_key()

        self.assertEqual(
            str(raised.exception),
            "Persistent Riot API key storage is unavailable.",
        )
        self.assertIs(raised.exception.__cause__, raw_error)
        backend.collection.search_items.assert_not_called()
        self.assertEqual(
            stderr.getvalue(),
            "Linux Secret Service diagnostic: operation=read "
            "phase=collection-lock-check "
            "exception=builtins.RuntimeError\n",
        )
        self.assertNotIn("sensitive-backend-detail", stderr.getvalue())
        self.assertNotIn("RGAPI-secret-marker", stderr.getvalue())

    def test_backend_operation_failures_are_redacted(self):
        operations = (
            "search_items",
            "create_item",
            "delete",
        )
        markers = (
            "synthetic-dbus-address",
            "/tmp/synthetic-keyring",
            "RGAPI-secret-marker",
            "BackendClass",
            "Traceback",
        )

        for operation in operations:
            with self.subTest(operation=operation):
                backend = _FakeSecretStorage()
                raw_error = RuntimeError(" ".join(markers))

                with self._linux_boundary(backend):
                    if operation == "search_items":
                        backend.collection.search_items = Mock(
                            side_effect=raw_error
                        )
                        action = RiotApiKeyService.get_api_key

                    elif operation == "create_item":
                        backend.collection.create_item.side_effect = raw_error
                        action = lambda: RiotApiKeyService.save_api_key(
                            self.api_key
                        )

                    else:
                        item = _FakeSecretServiceItem(
                            backend.collection,
                            {
                                "application": "LeagueMasteryTracker",
                                "secret": "RiotApiKey",
                            },
                            self.api_key.encode("utf-8"),
                        )
                        backend.collection.items.append(item)
                        item.delete = Mock(side_effect=raw_error)
                        action = RiotApiKeyService.delete_local_api_key

                    with self.assertRaises(RiotApiKeyStorageError) as raised:
                        action()

                for marker in markers:
                    self.assertNotIn(marker, str(raised.exception))

    def test_malformed_secret_service_secret_fails_safely(self):
        backend = _FakeSecretStorage()
        attributes = {
            "application": "LeagueMasteryTracker",
            "secret": "RiotApiKey",
        }
        backend.collection.items.append(
            _FakeSecretServiceItem(
                backend.collection,
                attributes,
                b"\xff\xfe",
            )
        )

        with self._linux_boundary(backend):
            with self.assertRaises(RiotApiKeyStorageError) as raised:
                RiotApiKeyService.get_api_key()

        self.assertNotIn("UnicodeDecodeError", str(raised.exception))

    def test_linux_read_diagnostic_is_disabled_by_default(self):
        backend = _FakeSecretStorage()
        backend.collection.search_items = Mock(
            side_effect=RuntimeError(
                "RGAPI-diagnostic-secret /sensitive/path "
                "LeagueMasteryTracker"
            )
        )
        stderr = StringIO()

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {
                LinuxSecretService.DIAGNOSTIC_ENVIRONMENT_VARIABLE: "",
            },
        ), redirect_stderr(stderr):
            with self.assertRaises(
                LinuxSecretServiceStorageError
            ) as raised:
                LinuxSecretService.read_api_key()

        self.assertEqual(
            str(raised.exception),
            "The stored Riot API key could not be read safely.",
        )
        self.assertEqual(stderr.getvalue(), "")

    def test_linux_read_diagnostic_reports_search_iteration_failure(self):
        backend = _FakeSecretStorage()

        def items():
            raise RuntimeError(
                "RGAPI-diagnostic-secret /sensitive/path "
                "Traceback LeagueMasteryTracker"
            )
            yield None

        backend.collection.search_items = Mock(return_value=items())
        stderr = StringIO()

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {
                LinuxSecretService.DIAGNOSTIC_ENVIRONMENT_VARIABLE: "1",
            },
        ), redirect_stderr(stderr):
            with self.assertRaises(
                LinuxSecretServiceStorageError
            ) as raised:
                LinuxSecretService.read_api_key()

        self.assertEqual(
            str(raised.exception),
            "The stored Riot API key could not be read safely.",
        )
        self.assertEqual(
            stderr.getvalue(),
            "Linux Secret Service diagnostic: operation=read "
            "phase=search-items exception=builtins.RuntimeError\n",
        )
        for marker in (
            "RGAPI-diagnostic-secret",
            "/sensitive/path",
            "LeagueMasteryTracker",
            "Traceback",
        ):
            self.assertNotIn(marker, stderr.getvalue())

    def test_linux_read_diagnostic_reports_get_secret_failure(self):
        backend = _FakeSecretStorage()
        item = _FakeSecretServiceItem(
            backend.collection,
            {
                "application": "LeagueMasteryTracker",
                "secret": "RiotApiKey",
            },
            self.api_key.encode("utf-8"),
        )
        item.get_secret = Mock(
            side_effect=RuntimeError(
                "RGAPI-diagnostic-secret /sensitive/path "
                "Traceback LeagueMasteryTracker"
            )
        )
        backend.collection.items.append(item)
        stderr = StringIO()

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {
                LinuxSecretService.DIAGNOSTIC_ENVIRONMENT_VARIABLE: "1",
            },
        ), redirect_stderr(stderr):
            with self.assertRaises(
                LinuxSecretServiceStorageError
            ) as raised:
                LinuxSecretService.read_api_key()

        self.assertEqual(
            str(raised.exception),
            "The stored Riot API key could not be read safely.",
        )
        self.assertEqual(
            stderr.getvalue(),
            "Linux Secret Service diagnostic: operation=read "
            "phase=get-secret exception=builtins.RuntimeError\n",
        )
        for marker in (
            "RGAPI-diagnostic-secret",
            "/sensitive/path",
            "LeagueMasteryTracker",
            "RiotApiKey",
            "Traceback",
            "The stored Riot API key could not be read safely.",
        ):
            self.assertNotIn(marker, stderr.getvalue())

    def test_linux_read_diagnostic_reports_decode_failure(self):
        backend = _FakeSecretStorage()
        backend.collection.items.append(
            _FakeSecretServiceItem(
                backend.collection,
                {
                    "application": "LeagueMasteryTracker",
                    "secret": "RiotApiKey",
                },
                b"\xff\xfe",
            )
        )
        stderr = StringIO()

        with self._linux_boundary(backend), patch.dict(
            os.environ,
            {
                LinuxSecretService.DIAGNOSTIC_ENVIRONMENT_VARIABLE: "1",
            },
        ), redirect_stderr(stderr):
            with self.assertRaises(
                LinuxSecretServiceStorageError
            ) as raised:
                LinuxSecretService.read_api_key()

        self.assertEqual(
            str(raised.exception),
            "The stored Riot API key could not be read safely.",
        )
        self.assertEqual(
            stderr.getvalue(),
            "Linux Secret Service diagnostic: operation=read "
            "phase=decode-secret "
            "exception=builtins.UnicodeDecodeError\n",
        )
        self.assertNotIn("UnicodeDecodeError:", stderr.getvalue())
        self.assertNotIn("ff", stderr.getvalue())

    def test_linux_legacy_plaintext_migrates_after_secure_save(self):
        backend = _FakeSecretStorage()
        legacy_file = self.configuration_directory / "riot_api_key.txt"
        legacy_file.parent.mkdir(parents=True)
        legacy_file.write_text(self.api_key, encoding="utf-8")

        with self._linux_boundary(backend):
            active_key = self._call_or_fail(
                RiotApiKeyService.get_api_key
            )

        self.assertEqual(active_key, self.api_key)
        self.assertFalse(legacy_file.exists())
        self.assertEqual(len(self._application_items(backend)), 1)

    def test_failed_linux_legacy_migration_retains_plaintext_source(self):
        backend = _FakeSecretStorage()
        backend.collection.create_item.side_effect = RuntimeError(
            "synthetic-write-failure RGAPI-secret-marker"
        )
        legacy_file = self.configuration_directory / "riot_api_key.txt"
        legacy_file.parent.mkdir(parents=True)
        legacy_file.write_text(self.api_key, encoding="utf-8")

        with self._linux_boundary(backend):
            with self.assertRaises(RiotApiKeyStorageError):
                RiotApiKeyService.get_api_key()

        self.assertTrue(legacy_file.exists())
        self.assertEqual(legacy_file.read_text(encoding="utf-8"), self.api_key)

    def test_windows_dispatch_keeps_dpapi_file_path(self):
        protected_data = b"synthetic-dpapi-payload"

        with patch.object(sys, "platform", "win32"), patch(
            "application.services.riot_api_key_service."
            "WindowsDpapiService.protect",
            return_value=protected_data,
        ) as protect, patch(
            "application.services.riot_api_key_service."
            "WindowsDpapiService.unprotect",
            return_value=self.api_key.encode("utf-8"),
        ):
            RiotApiKeyService.save_api_key(self.api_key)

        protect.assert_called_once_with(self.api_key.encode("utf-8"))
        self.assertTrue(
            (self.configuration_directory / "riot_api_key.dpapi").exists()
        )

    def test_module_import_does_not_connect_or_mutate(self):
        backend = _FakeSecretStorage()

        with patch.object(sys, "platform", "linux"), patch.dict(
            sys.modules,
            {"secretstorage": backend.module()},
        ):
            self.assertFalse(
                self.configuration_directory.exists()
            )
            backend.dbus_init.assert_not_called()
        self.assertFalse(self.configuration_directory.exists())

    def test_capability_reports_available_storage_without_backend_details(self):
        backend = _FakeSecretStorage()

        with self._linux_boundary(backend):
            status = self._persistent_storage_status_or_fail()

        self.assertEqual(status, {"available": True, "error": None})


if __name__ == "__main__":
    unittest.main()
