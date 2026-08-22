import ctypes
import os
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    """
    ctypes representation of the Windows DATA_BLOB structure.
    """

    _fields_ = [
        (
            "cbData",
            wintypes.DWORD,
        ),
        (
            "pbData",
            ctypes.POINTER(
                ctypes.c_ubyte
            ),
        ),
    ]


class WindowsDpapiService:
    """
    Encrypts and decrypts byte values with Windows DPAPI.

    Protection is tied to the current Windows user account.
    Machine-wide protection is intentionally not enabled.
    """

    CRYPTPROTECT_UI_FORBIDDEN = 0x00000001

    DATA_DESCRIPTION = (
        "League Mastery Tracker local secret"
    )

    OPTIONAL_ENTROPY = (
        b"LeagueMasteryTracker:"
        b"RiotApiKey:"
        b"v1"
    )

    @classmethod
    def protect(cls, plaintext):
        """
        Encrypt a non-empty byte value for the current Windows user.
        """

        cls._ensure_windows()

        normalized_plaintext = cls._normalize_bytes(
            plaintext,
            value_name="Plaintext",
        )

        input_buffer = ctypes.create_string_buffer(
            normalized_plaintext
        )

        input_blob = _DataBlob(
            cbData=len(normalized_plaintext),
            pbData=ctypes.cast(
                input_buffer,
                ctypes.POINTER(
                    ctypes.c_ubyte
                ),
            ),
        )

        entropy_buffer = ctypes.create_string_buffer(
            cls.OPTIONAL_ENTROPY
        )

        entropy_blob = _DataBlob(
            cbData=len(cls.OPTIONAL_ENTROPY),
            pbData=ctypes.cast(
                entropy_buffer,
                ctypes.POINTER(
                    ctypes.c_ubyte
                ),
            ),
        )

        output_blob = _DataBlob()

        crypt32 = cls._get_crypt32()

        success = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            cls.DATA_DESCRIPTION,
            ctypes.byref(entropy_blob),
            None,
            None,
            cls.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )

        if not success:
            raise ctypes.WinError(
                ctypes.get_last_error()
            )

        try:
            return ctypes.string_at(
                output_blob.pbData,
                output_blob.cbData,
            )

        finally:
            cls._free_windows_memory(
                output_blob.pbData
            )

    @classmethod
    def unprotect(cls, protected_data):
        """
        Decrypt and integrity-check a DPAPI-protected byte value.
        """

        cls._ensure_windows()

        normalized_protected_data = (
            cls._normalize_bytes(
                protected_data,
                value_name="Protected data",
            )
        )

        input_buffer = ctypes.create_string_buffer(
            normalized_protected_data
        )

        input_blob = _DataBlob(
            cbData=len(
                normalized_protected_data
            ),
            pbData=ctypes.cast(
                input_buffer,
                ctypes.POINTER(
                    ctypes.c_ubyte
                ),
            ),
        )

        entropy_buffer = ctypes.create_string_buffer(
            cls.OPTIONAL_ENTROPY
        )

        entropy_blob = _DataBlob(
            cbData=len(cls.OPTIONAL_ENTROPY),
            pbData=ctypes.cast(
                entropy_buffer,
                ctypes.POINTER(
                    ctypes.c_ubyte
                ),
            ),
        )

        output_blob = _DataBlob()

        crypt32 = cls._get_crypt32()

        success = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            cls.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )

        if not success:
            raise ctypes.WinError(
                ctypes.get_last_error()
            )

        try:
            return ctypes.string_at(
                output_blob.pbData,
                output_blob.cbData,
            )

        finally:
            cls._free_windows_memory(
                output_blob.pbData
            )

    @staticmethod
    def _normalize_bytes(
        value,
        value_name,
    ):
        """
        Normalize a required bytes-like value.
        """

        if isinstance(value, bytearray):
            normalized_value = bytes(
                value
            )

        elif isinstance(value, bytes):
            normalized_value = value

        else:
            raise TypeError(
                f"{value_name} must be bytes."
            )

        if not normalized_value:
            raise ValueError(
                f"{value_name} cannot be empty."
            )

        return normalized_value

    @staticmethod
    def _ensure_windows():
        """
        Prevent accidental use on unsupported operating systems.
        """

        if os.name != "nt":
            raise OSError(
                "Windows DPAPI is only available on Windows."
            )

    @staticmethod
    def _get_crypt32():
        """
        Load crypt32.dll and configure the DPAPI signatures.
        """

        crypt32 = ctypes.WinDLL(
            "crypt32.dll",
            use_last_error=True,
        )

        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]

        crypt32.CryptProtectData.restype = (
            wintypes.BOOL
        )

        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]

        crypt32.CryptUnprotectData.restype = (
            wintypes.BOOL
        )

        return crypt32

    @staticmethod
    def _free_windows_memory(pointer):
        """
        Release memory allocated by a Windows DPAPI function.
        """

        if not pointer:
            return

        kernel32 = ctypes.WinDLL(
            "kernel32.dll",
            use_last_error=True,
        )

        kernel32.LocalFree.argtypes = [
            ctypes.c_void_p,
        ]

        kernel32.LocalFree.restype = (
            ctypes.c_void_p
        )

        kernel32.LocalFree(
            ctypes.cast(
                pointer,
                ctypes.c_void_p,
            )
        )