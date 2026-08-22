import os
import unittest

from application.services.windows_dpapi_service import (
    WindowsDpapiService,
)


@unittest.skipUnless(
    os.name == "nt",
    "Windows DPAPI tests require Windows.",
)
class WindowsDpapiServiceTests(unittest.TestCase):
    def test_protected_data_can_be_decrypted(self):
        plaintext = (
            b"RGAPI-test-value-for-dpapi"
        )

        protected_data = (
            WindowsDpapiService.protect(
                plaintext
            )
        )

        decrypted_data = (
            WindowsDpapiService.unprotect(
                protected_data
            )
        )

        self.assertIsInstance(
            protected_data,
            bytes,
        )

        self.assertNotEqual(
            protected_data,
            plaintext,
        )

        self.assertEqual(
            decrypted_data,
            plaintext,
        )

    def test_modified_protected_data_is_rejected(self):
        protected_data = bytearray(
            WindowsDpapiService.protect(
                b"RGAPI-integrity-test-value"
            )
        )

        protected_data[
            len(protected_data) // 2
        ] ^= 0x01

        with self.assertRaises(
            OSError
        ):
            WindowsDpapiService.unprotect(
                bytes(protected_data)
            )

    def test_empty_values_are_rejected(self):
        with self.assertRaises(
            ValueError
        ):
            WindowsDpapiService.protect(
                b""
            )

        with self.assertRaises(
            ValueError
        ):
            WindowsDpapiService.unprotect(
                b""
            )


if __name__ == "__main__":
    unittest.main()