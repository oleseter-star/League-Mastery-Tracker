import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from flask import current_app

from application.services.json_import_read_service import (
    JsonImportReadError,
    JsonImportReadService,
)


class JsonImportStagingError(RuntimeError):
    """
    Raised when a JSON import cannot be staged, loaded, verified,
    expired, or cancelled safely.
    """


class JsonImportStagingService:
    """
    Stores one validated JSON import temporarily between preview
    and explicit execution confirmation.

    Only one staged import is active at a time. A new successful
    staging operation atomically replaces the active marker and
    removes older staged files.

    The staged file contains the exact uploaded bytes. SHA-256 is
    used to detect changes between preview and execution.
    """

    STAGING_DIRECTORY_NAME = "json_import"

    MARKER_FILE_NAME = "pending_import.json"
    MARKER_FORMAT_VERSION = 1

    STAGED_FILE_PREFIX = "staged_import_"
    STAGED_FILE_SUFFIX = ".json"

    TOKEN_BYTE_LENGTH = 16
    TOKEN_HEX_LENGTH = (
        TOKEN_BYTE_LENGTH
        * 2
    )

    DEFAULT_EXPIRATION_MINUTES = 60

    MARKER_KEYS = {
        "marker_format_version",
        "staging_token",
        "staged_file_name",
        "original_file_name",
        "file_size_bytes",
        "max_file_size_bytes",
        "sha256",
        "created_at",
        "expires_at",
        "format",
        "format_version",
        "database_schema_version",
        "exported_at",
        "record_counts",
    }

    RECORD_COUNT_KEYS = {
        "persons",
        "riot_accounts",
        "champions",
        "mastery_records",
    }

    @classmethod
    def stage_stream(
        cls,
        stream,
        file_name,
        max_file_size_bytes=(
            JsonImportReadService
            .DEFAULT_MAX_FILE_SIZE_BYTES
        ),
        expiration_minutes=(
            DEFAULT_EXPIRATION_MINUTES
        ),
    ):
        """
        Read, validate, and atomically stage one binary JSON stream.

        Returns display-safe metadata and the staging token.

        No database reads or writes are performed.
        """

        normalized_expiration = (
            cls._normalize_expiration_minutes(
                expiration_minutes
            )
        )

        raw_bytes = cls._read_limited_bytes(
            stream=stream,
            max_file_size_bytes=(
                max_file_size_bytes
            ),
        )

        try:
            read_result = (
                JsonImportReadService
                .read_stream(
                    stream=BytesIO(
                        raw_bytes
                    ),
                    file_name=file_name,
                    max_file_size_bytes=(
                        max_file_size_bytes
                    ),
                )
            )

        except JsonImportReadError as error:
            raise JsonImportStagingError(
                "The JSON import file could not be validated "
                "before staging."
            ) from error

        staging_directory = (
            cls._get_staging_directory()
        )

        try:
            staging_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

        except OSError as error:
            raise JsonImportStagingError(
                "The private JSON import staging directory could "
                "not be created."
            ) from error

        staging_token = secrets.token_hex(
            cls.TOKEN_BYTE_LENGTH
        )

        staged_file_name = (
            cls.STAGED_FILE_PREFIX
            + staging_token
            + cls.STAGED_FILE_SUFFIX
        )

        staged_file = cls._build_confined_path(
            staging_directory=(
                staging_directory
            ),
            file_name=staged_file_name,
        )

        staged_temporary_file = (
            staging_directory
            / (
                staged_file_name
                + ".tmp"
            )
        )

        marker_file = (
            staging_directory
            / cls.MARKER_FILE_NAME
        )

        marker_temporary_file = (
            staging_directory
            / (
                cls.MARKER_FILE_NAME
                + "."
                + staging_token
                + ".tmp"
            )
        )

        created_at_value = cls._utc_now()

        expires_at_value = (
            created_at_value
            + timedelta(
                minutes=normalized_expiration
            )
        )

        marker = {
            "marker_format_version": (
                cls.MARKER_FORMAT_VERSION
            ),
            "staging_token": staging_token,
            "staged_file_name": (
                staged_file_name
            ),
            "original_file_name": (
                read_result[
                    "file_name"
                ]
            ),
            "file_size_bytes": (
                read_result[
                    "file_size_bytes"
                ]
            ),
            "max_file_size_bytes": (
                max_file_size_bytes
            ),
            "sha256": read_result[
                "sha256"
            ],
            "created_at": (
                cls._format_utc_timestamp(
                    created_at_value
                )
            ),
            "expires_at": (
                cls._format_utc_timestamp(
                    expires_at_value
                )
            ),
            "format": read_result[
                "format"
            ],
            "format_version": read_result[
                "format_version"
            ],
            "database_schema_version": (
                read_result[
                    "database_schema_version"
                ]
            ),
            "exported_at": read_result[
                "exported_at"
            ],
            "record_counts": dict(
                read_result[
                    "record_counts"
                ]
            ),
        }

        marker_replaced = False

        try:
            cls._write_bytes_atomically(
                temporary_file=(
                    staged_temporary_file
                ),
                final_file=staged_file,
                raw_bytes=raw_bytes,
            )

            cls._write_marker_atomically(
                temporary_file=(
                    marker_temporary_file
                ),
                marker_file=marker_file,
                marker=marker,
            )

            marker_replaced = True

            cls._remove_unreferenced_files(
                staging_directory=(
                    staging_directory
                ),
                active_staged_file_name=(
                    staged_file_name
                ),
            )

        except JsonImportStagingError:
            if not marker_replaced:
                cls._safe_unlink(
                    staged_file
                )

            cls._safe_unlink(
                staged_temporary_file
            )

            cls._safe_unlink(
                marker_temporary_file
            )

            raise

        except OSError as error:
            if not marker_replaced:
                cls._safe_unlink(
                    staged_file
                )

            cls._safe_unlink(
                staged_temporary_file
            )

            cls._safe_unlink(
                marker_temporary_file
            )

            raise JsonImportStagingError(
                "The JSON import file could not be staged."
            ) from error

        return {
            "staging_token": (
                staging_token
            ),
            "original_file_name": (
                marker[
                    "original_file_name"
                ]
            ),
            "file_size_bytes": (
                marker[
                    "file_size_bytes"
                ]
            ),
            "sha256": marker[
                "sha256"
            ],
            "created_at": marker[
                "created_at"
            ],
            "expires_at": marker[
                "expires_at"
            ],
            "format": marker[
                "format"
            ],
            "format_version": marker[
                "format_version"
            ],
            "database_schema_version": (
                marker[
                    "database_schema_version"
                ]
            ),
            "exported_at": marker[
                "exported_at"
            ],
            "record_counts": dict(
                marker[
                    "record_counts"
                ]
            ),
        }

    @classmethod
    def load_staged(
        cls,
        staging_token,
    ):
        """
        Load and revalidate the currently staged JSON import.

        The marker, token, file path, size, SHA-256, timestamps,
        export metadata, and complete JSON document are verified.

        No database reads or writes are performed.
        """

        normalized_token = (
            cls._normalize_staging_token(
                staging_token
            )
        )

        staging_directory = (
            cls._get_staging_directory()
        )

        marker = cls._read_and_validate_marker(
            staging_directory
        )

        if not hmac.compare_digest(
            marker["staging_token"],
            normalized_token,
        ):
            raise JsonImportStagingError(
                "The JSON import staging token is invalid or no "
                "longer active."
            )

        expected_staged_file_name = (
            cls.STAGED_FILE_PREFIX
            + normalized_token
            + cls.STAGED_FILE_SUFFIX
        )

        if (
            marker["staged_file_name"]
            != expected_staged_file_name
        ):
            raise JsonImportStagingError(
                "The JSON import marker contains an invalid "
                "staged file name."
            )

        expires_at = cls._parse_utc_timestamp(
            marker["expires_at"],
            "The JSON import expiry timestamp",
        )

        if cls._utc_now() >= expires_at:
            raise JsonImportStagingError(
                "The staged JSON import has expired."
            )

        staged_file = cls._build_confined_path(
            staging_directory=(
                staging_directory
            ),
            file_name=marker[
                "staged_file_name"
            ],
        )

        try:
            if (
                not staged_file.exists()
                or not staged_file.is_file()
                or staged_file.is_symlink()
            ):
                raise JsonImportStagingError(
                    "The staged JSON import file is missing or "
                    "invalid."
                )

            actual_size = (
                staged_file.stat().st_size
            )

        except JsonImportStagingError:
            raise

        except OSError as error:
            raise JsonImportStagingError(
                "The staged JSON import file could not be "
                "inspected."
            ) from error

        if (
            actual_size
            != marker["file_size_bytes"]
        ):
            raise JsonImportStagingError(
                "The staged JSON import file size has changed."
            )

        try:
            with staged_file.open(
                "rb"
            ) as staged_stream:
                read_result = (
                    JsonImportReadService
                    .read_stream(
                        stream=staged_stream,
                        file_name=marker[
                            "original_file_name"
                        ],
                        max_file_size_bytes=(
                            marker[
                                "max_file_size_bytes"
                            ]
                        ),
                    )
                )

        except JsonImportReadError as error:
            raise JsonImportStagingError(
                "The staged JSON import file failed "
                "revalidation."
            ) from error

        except OSError as error:
            raise JsonImportStagingError(
                "The staged JSON import file could not be read."
            ) from error

        if not hmac.compare_digest(
            read_result["sha256"],
            marker["sha256"],
        ):
            raise JsonImportStagingError(
                "The staged JSON import failed its SHA-256 "
                "integrity check."
            )

        cls._compare_marker_to_read_result(
            marker=marker,
            read_result=read_result,
        )

        return {
            "staging": {
                "staging_token": (
                    normalized_token
                ),
                "original_file_name": (
                    marker[
                        "original_file_name"
                    ]
                ),
                "file_size_bytes": (
                    marker[
                        "file_size_bytes"
                    ]
                ),
                "sha256": marker[
                    "sha256"
                ],
                "created_at": marker[
                    "created_at"
                ],
                "expires_at": marker[
                    "expires_at"
                ],
            },
            "read_result": read_result,
        }

    @classmethod
    def cancel_staged(
        cls,
        staging_token,
    ):
        """
        Cancel the currently staged JSON import.

        The token must match the active marker. A stale token cannot
        cancel a newer staged import.
        """

        normalized_token = (
            cls._normalize_staging_token(
                staging_token
            )
        )

        staging_directory = (
            cls._get_staging_directory()
        )

        marker = cls._read_and_validate_marker(
            staging_directory
        )

        if not hmac.compare_digest(
            marker["staging_token"],
            normalized_token,
        ):
            raise JsonImportStagingError(
                "The JSON import staging token is invalid or no "
                "longer active."
            )

        expected_staged_file_name = (
            cls.STAGED_FILE_PREFIX
            + normalized_token
            + cls.STAGED_FILE_SUFFIX
        )

        if (
            marker["staged_file_name"]
            != expected_staged_file_name
        ):
            raise JsonImportStagingError(
                "The JSON import marker contains an invalid "
                "staged file name."
            )

        staged_file = cls._build_confined_path(
            staging_directory=(
                staging_directory
            ),
            file_name=expected_staged_file_name,
        )

        marker_file = (
            staging_directory
            / cls.MARKER_FILE_NAME
        )

        try:
            cls._safe_unlink(
                staged_file
            )

            cls._safe_unlink(
                marker_file
            )

            cls._remove_unreferenced_files(
                staging_directory=(
                    staging_directory
                ),
                active_staged_file_name=None,
            )

        except OSError as error:
            raise JsonImportStagingError(
                "The staged JSON import could not be cancelled "
                "completely."
            ) from error

        return {
            "cancelled": True,
            "staging_token": (
                normalized_token
            ),
            "original_file_name": (
                marker[
                    "original_file_name"
                ]
            ),
        }

    @classmethod
    def _read_and_validate_marker(
        cls,
        staging_directory,
    ):
        marker_file = (
            staging_directory
            / cls.MARKER_FILE_NAME
        )

        try:
            if (
                not marker_file.exists()
                or not marker_file.is_file()
                or marker_file.is_symlink()
            ):
                raise JsonImportStagingError(
                    "There is no active staged JSON import."
                )

            raw_marker = marker_file.read_text(
                encoding="utf-8"
            )

        except JsonImportStagingError:
            raise

        except (
            OSError,
            UnicodeError,
        ) as error:
            raise JsonImportStagingError(
                "The JSON import staging marker could not be "
                "read."
            ) from error

        try:
            marker = json.loads(
                raw_marker
            )

        except json.JSONDecodeError as error:
            raise JsonImportStagingError(
                "The JSON import staging marker contains invalid "
                "JSON."
            ) from error

        cls._validate_marker(
            marker
        )

        return marker

    @classmethod
    def _validate_marker(
        cls,
        marker,
    ):
        if not isinstance(
            marker,
            dict,
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker must be an "
                "object."
            )

        actual_keys = set(
            marker.keys()
        )

        if actual_keys != cls.MARKER_KEYS:
            raise JsonImportStagingError(
                "The JSON import staging marker has an invalid "
                "structure."
            )

        if (
            marker["marker_format_version"]
            != cls.MARKER_FORMAT_VERSION
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker version is "
                "unsupported."
            )

        staging_token = (
            cls._normalize_staging_token(
                marker["staging_token"]
            )
        )

        expected_staged_file_name = (
            cls.STAGED_FILE_PREFIX
            + staging_token
            + cls.STAGED_FILE_SUFFIX
        )

        if (
            marker["staged_file_name"]
            != expected_staged_file_name
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker contains an "
                "invalid staged file name."
            )

        original_file_name = marker[
            "original_file_name"
        ]

        if (
            not isinstance(
                original_file_name,
                str,
            )
            or not original_file_name
            or original_file_name
            != Path(
                original_file_name
            ).name
            or not original_file_name.lower().endswith(
                ".json"
            )
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker contains an "
                "invalid original file name."
            )

        cls._require_nonnegative_integer(
            marker["file_size_bytes"],
            "The staged JSON import file size",
        )

        cls._require_positive_integer(
            marker["max_file_size_bytes"],
            "The staged JSON import maximum file size",
        )

        if (
            marker["file_size_bytes"]
            > marker["max_file_size_bytes"]
        ):
            raise JsonImportStagingError(
                "The staged JSON import file size exceeds its "
                "recorded maximum."
            )

        if not cls._is_valid_sha256(
            marker["sha256"]
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker contains an "
                "invalid SHA-256 value."
            )

        created_at = cls._parse_utc_timestamp(
            marker["created_at"],
            "The JSON import creation timestamp",
        )

        expires_at = cls._parse_utc_timestamp(
            marker["expires_at"],
            "The JSON import expiry timestamp",
        )

        if expires_at <= created_at:
            raise JsonImportStagingError(
                "The JSON import staging expiry timestamp is "
                "invalid."
            )

        if (
            not isinstance(
                marker["format"],
                str,
            )
            or not marker["format"]
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker contains an "
                "invalid format identifier."
            )

        cls._require_positive_integer(
            marker["format_version"],
            "The staged JSON import format version",
        )

        cls._require_positive_integer(
            marker[
                "database_schema_version"
            ],
            "The staged JSON import database schema version",
        )

        cls._parse_utc_timestamp(
            marker["exported_at"],
            "The staged JSON import export timestamp",
        )

        record_counts = marker[
            "record_counts"
        ]

        if (
            not isinstance(
                record_counts,
                dict,
            )
            or set(
                record_counts.keys()
            )
            != cls.RECORD_COUNT_KEYS
        ):
            raise JsonImportStagingError(
                "The JSON import staging marker contains invalid "
                "record counts."
            )

        for count_name in cls.RECORD_COUNT_KEYS:
            cls._require_nonnegative_integer(
                record_counts[
                    count_name
                ],
                (
                    "The staged JSON import record count for "
                    f"{count_name}"
                ),
            )

    @classmethod
    def _compare_marker_to_read_result(
        cls,
        marker,
        read_result,
    ):
        expected_values = {
            "file_name": marker[
                "original_file_name"
            ],
            "file_size_bytes": marker[
                "file_size_bytes"
            ],
            "sha256": marker[
                "sha256"
            ],
            "format": marker[
                "format"
            ],
            "format_version": marker[
                "format_version"
            ],
            "database_schema_version": marker[
                "database_schema_version"
            ],
            "exported_at": marker[
                "exported_at"
            ],
            "record_counts": marker[
                "record_counts"
            ],
        }

        for field_name, expected_value in (
            expected_values.items()
        ):
            actual_value = read_result[
                field_name
            ]

            if actual_value != expected_value:
                raise JsonImportStagingError(
                    "The staged JSON import no longer matches "
                    f"its marker metadata for {field_name}."
                )

    @classmethod
    def _read_limited_bytes(
        cls,
        stream,
        max_file_size_bytes,
    ):
        normalized_max_size = (
            cls._require_positive_integer(
                max_file_size_bytes,
                "The maximum JSON import file size",
            )
        )

        read_method = getattr(
            stream,
            "read",
            None,
        )

        if not callable(
            read_method
        ):
            raise JsonImportStagingError(
                "The selected JSON import does not provide a "
                "readable binary stream."
            )

        chunks = []
        total_bytes = 0

        try:
            while True:
                remaining_bytes = (
                    normalized_max_size
                    + 1
                    - total_bytes
                )

                if remaining_bytes <= 0:
                    break

                requested_bytes = min(
                    JsonImportReadService
                    .READ_CHUNK_SIZE_BYTES,
                    remaining_bytes,
                )

                chunk = read_method(
                    requested_bytes
                )

                if chunk in (
                    b"",
                    None,
                ):
                    break

                if not isinstance(
                    chunk,
                    (
                        bytes,
                        bytearray,
                    ),
                ):
                    raise JsonImportStagingError(
                        "The selected JSON import must be read "
                        "as binary data."
                    )

                normalized_chunk = bytes(
                    chunk
                )

                chunks.append(
                    normalized_chunk
                )

                total_bytes += len(
                    normalized_chunk
                )

                if (
                    total_bytes
                    > normalized_max_size
                ):
                    break

        except JsonImportStagingError:
            raise

        except (
            OSError,
            ValueError,
        ) as error:
            raise JsonImportStagingError(
                "The selected JSON import stream could not be "
                "read."
            ) from error

        if total_bytes > normalized_max_size:
            raise JsonImportStagingError(
                "The selected JSON import file is too large."
            )

        return b"".join(
            chunks
        )

    @classmethod
    def _write_bytes_atomically(
        cls,
        temporary_file,
        final_file,
        raw_bytes,
    ):
        cls._safe_unlink(
            temporary_file
        )

        try:
            with temporary_file.open(
                "xb"
            ) as file_handle:
                file_handle.write(
                    raw_bytes
                )

                file_handle.flush()

                os.fsync(
                    file_handle.fileno()
                )

            temporary_file.replace(
                final_file
            )

        except OSError as error:
            cls._safe_unlink(
                temporary_file
            )

            raise JsonImportStagingError(
                "The staged JSON import file could not be "
                "written atomically."
            ) from error

    @classmethod
    def _write_marker_atomically(
        cls,
        temporary_file,
        marker_file,
        marker,
    ):
        cls._safe_unlink(
            temporary_file
        )

        try:
            serialized_marker = (
                json.dumps(
                    marker,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )

            with temporary_file.open(
                "x",
                encoding="utf-8",
                newline="\n",
            ) as file_handle:
                file_handle.write(
                    serialized_marker
                )

                file_handle.flush()

                os.fsync(
                    file_handle.fileno()
                )

            temporary_file.replace(
                marker_file
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as error:
            cls._safe_unlink(
                temporary_file
            )

            raise JsonImportStagingError(
                "The JSON import staging marker could not be "
                "written atomically."
            ) from error

    @classmethod
    def _remove_unreferenced_files(
        cls,
        staging_directory,
        active_staged_file_name,
    ):
        if not staging_directory.exists():
            return

        for candidate in (
            staging_directory.iterdir()
        ):
            candidate_name = candidate.name

            if (
                candidate_name
                == cls.MARKER_FILE_NAME
            ):
                continue

            if (
                active_staged_file_name
                and candidate_name
                == active_staged_file_name
            ):
                continue

            is_service_file = (
                candidate_name.startswith(
                    cls.STAGED_FILE_PREFIX
                )
                or (
                    candidate_name.startswith(
                        cls.MARKER_FILE_NAME
                        + "."
                    )
                    and candidate_name.endswith(
                        ".tmp"
                    )
                )
            )

            if is_service_file:
                cls._safe_unlink(
                    candidate
                )

    @classmethod
    def _get_staging_directory(
        cls,
    ):
        try:
            configuration_directory = Path(
                current_app.config[
                    "CONFIG_DIR"
                ]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise JsonImportStagingError(
                "The application configuration directory is "
                "not configured."
            ) from error

        return (
            configuration_directory
            / cls.STAGING_DIRECTORY_NAME
        )

    @classmethod
    def _build_confined_path(
        cls,
        staging_directory,
        file_name,
    ):
        if (
            not isinstance(
                file_name,
                str,
            )
            or not file_name
            or file_name
            != Path(
                file_name
            ).name
        ):
            raise JsonImportStagingError(
                "The staged JSON import file name is invalid."
            )

        try:
            resolved_directory = (
                staging_directory.resolve()
            )

            candidate = (
                staging_directory
                / file_name
            )

            resolved_candidate = (
                candidate.resolve(
                    strict=False
                )
            )

        except OSError as error:
            raise JsonImportStagingError(
                "The staged JSON import path could not be "
                "resolved."
            ) from error

        if (
            resolved_candidate.parent
            != resolved_directory
        ):
            raise JsonImportStagingError(
                "The staged JSON import path escapes the private "
                "staging directory."
            )

        return candidate

    @classmethod
    def _normalize_staging_token(
        cls,
        staging_token,
    ):
        if (
            not isinstance(
                staging_token,
                str,
            )
            or len(
                staging_token
            )
            != cls.TOKEN_HEX_LENGTH
            or any(
                character
                not in "0123456789abcdef"
                for character in staging_token
            )
        ):
            raise JsonImportStagingError(
                "The JSON import staging token is invalid."
            )

        return staging_token

    @staticmethod
    def _normalize_expiration_minutes(
        expiration_minutes,
    ):
        if (
            isinstance(
                expiration_minutes,
                bool,
            )
            or not isinstance(
                expiration_minutes,
                int,
            )
            or expiration_minutes <= 0
        ):
            raise JsonImportStagingError(
                "The JSON import staging expiration must be a "
                "positive integer."
            )

        return expiration_minutes

    @staticmethod
    def _format_utc_timestamp(
        value,
    ):
        return (
            value
            .astimezone(
                timezone.utc
            )
            .isoformat(
                timespec="microseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        )

    @staticmethod
    def _parse_utc_timestamp(
        value,
        label,
    ):
        if (
            not isinstance(
                value,
                str,
            )
            or not value.endswith(
                "Z"
            )
        ):
            raise JsonImportStagingError(
                f"{label} is invalid."
            )

        try:
            parsed_value = datetime.fromisoformat(
                value[
                    :-1
                ]
                + "+00:00"
            )

        except ValueError as error:
            raise JsonImportStagingError(
                f"{label} is invalid."
            ) from error

        return parsed_value.astimezone(
            timezone.utc
        )

    @staticmethod
    def _utc_now():
        return datetime.now(
            timezone.utc
        )

    @staticmethod
    def _is_valid_sha256(
        value,
    ):
        return (
            isinstance(
                value,
                str,
            )
            and len(
                value
            ) == 64
            and all(
                character
                in "0123456789abcdef"
                for character in value
            )
        )

    @staticmethod
    def _require_positive_integer(
        value,
        label,
    ):
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
            or value <= 0
        ):
            raise JsonImportStagingError(
                f"{label} must be a positive integer."
            )

        return value

    @staticmethod
    def _require_nonnegative_integer(
        value,
        label,
    ):
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
            or value < 0
        ):
            raise JsonImportStagingError(
                f"{label} must be a non-negative integer."
            )

        return value

    @staticmethod
    def _safe_unlink(
        file_path,
    ):
        try:
            file_path.unlink(
                missing_ok=True
            )

        except OSError:
            raise