import hashlib
import json
from pathlib import Path

from application.services.json_export_validation_service import (
    JsonExportValidationError,
    JsonExportValidationService,
)


class JsonImportReadError(RuntimeError):
    """
    Raised when a selected JSON import file cannot be read,
    decoded, parsed, or validated safely.
    """


class _DuplicateJsonObjectKeyError(ValueError):
    """
    Internal parser error for duplicate JSON object keys.
    """


class _NonStandardJsonNumberError(ValueError):
    """
    Internal parser error for NaN and Infinity values.
    """


class JsonImportReadService:
    """
    Reads and validates a portable JSON export without changing
    the application database.

    The service enforces a hard byte limit while reading. It does
    not trust a browser-provided content length and does not save
    uploaded files to disk.

    JSON parsing is strict:

    - duplicate object keys are rejected
    - NaN is rejected
    - positive Infinity is rejected
    - negative Infinity is rejected
    """

    DEFAULT_MAX_FILE_SIZE_BYTES = (
        25
        * 1024
        * 1024
    )

    READ_CHUNK_SIZE_BYTES = (
        64
        * 1024
    )

    @classmethod
    def read_file(
        cls,
        file_path,
        max_file_size_bytes=(
            DEFAULT_MAX_FILE_SIZE_BYTES
        ),
    ):
        """
        Read and validate a JSON document from a local file path.

        This method is useful for tests and trusted local tooling.
        HTTP upload routes call read_stream() through the import
        workflow and staging services.
        """

        normalized_max_size = (
            cls._normalize_max_file_size(
                max_file_size_bytes
            )
        )

        try:
            path = Path(
                file_path
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise JsonImportReadError(
                "The selected import file path is invalid."
            ) from error

        try:
            if not path.exists():
                raise JsonImportReadError(
                    "The selected import file does not exist."
                )

            if not path.is_file():
                raise JsonImportReadError(
                    "The selected import path is not a file."
                )

            file_size = path.stat().st_size

        except JsonImportReadError:
            raise

        except OSError as error:
            raise JsonImportReadError(
                "The selected import file could not be inspected."
            ) from error

        if file_size > normalized_max_size:
            raise JsonImportReadError(
                "The selected import file is too large. "
                "Maximum allowed size: "
                f"{normalized_max_size} bytes."
            )

        try:
            with path.open(
                "rb"
            ) as file_stream:
                return cls.read_stream(
                    stream=file_stream,
                    file_name=path.name,
                    max_file_size_bytes=(
                        normalized_max_size
                    ),
                )

        except JsonImportReadError:
            raise

        except OSError as error:
            raise JsonImportReadError(
                "The selected import file could not be read."
            ) from error

    @classmethod
    def read_stream(
        cls,
        stream,
        file_name,
        max_file_size_bytes=(
            DEFAULT_MAX_FILE_SIZE_BYTES
        ),
    ):
        """
        Read, parse, and validate one binary JSON stream.

        Returns a dictionary containing safe file metadata, the
        validated record counts, and the parsed document.

        No database reads or writes are performed.
        """

        normalized_max_size = (
            cls._normalize_max_file_size(
                max_file_size_bytes
            )
        )

        normalized_file_name = (
            cls._normalize_file_name(
                file_name
            )
        )

        raw_bytes = cls._read_limited_bytes(
            stream=stream,
            max_file_size_bytes=(
                normalized_max_size
            ),
        )

        if not raw_bytes:
            raise JsonImportReadError(
                "The selected import file is empty."
            )

        try:
            decoded_text = raw_bytes.decode(
                "utf-8-sig"
            )

        except UnicodeDecodeError as error:
            raise JsonImportReadError(
                "The selected import file is not valid UTF-8."
            ) from error

        document = cls._parse_json(
            decoded_text
        )

        try:
            record_counts = (
                JsonExportValidationService
                .validate_document(
                    document
                )
            )

        except JsonExportValidationError as error:
            raise JsonImportReadError(
                "The selected import file failed export format "
                f"validation: {error}"
            ) from error

        return {
            "file_name": normalized_file_name,
            "file_size_bytes": len(
                raw_bytes
            ),
            "sha256": hashlib.sha256(
                raw_bytes
            ).hexdigest(),
            "format": document[
                "format"
            ],
            "format_version": document[
                "format_version"
            ],
            "database_schema_version": document[
                "database_schema_version"
            ],
            "exported_at": document[
                "exported_at"
            ],
            "record_counts": dict(
                record_counts
            ),
            "document": document,
        }

    @classmethod
    def _parse_json(
        cls,
        decoded_text,
    ):
        """
        Parse one JSON document using strict object and number rules.

        Python's default JSON decoder accepts NaN and Infinity and
        silently keeps the last occurrence of duplicate object
        keys. Portable import files must not rely on either
        behavior.
        """

        try:
            return json.loads(
                decoded_text,
                object_pairs_hook=(
                    cls._build_unique_object
                ),
                parse_constant=(
                    cls._reject_nonstandard_number
                ),
            )

        except _DuplicateJsonObjectKeyError as error:
            raise JsonImportReadError(
                "The selected import file contains duplicate "
                "JSON object keys."
            ) from error

        except _NonStandardJsonNumberError as error:
            raise JsonImportReadError(
                "The selected import file contains a "
                "non-standard JSON numeric value. "
                "NaN and Infinity are not allowed."
            ) from error

        except json.JSONDecodeError as error:
            raise JsonImportReadError(
                "The selected import file does not contain "
                "valid JSON. "
                f"Line: {error.lineno}. "
                f"Column: {error.colno}."
            ) from error

        except RecursionError as error:
            raise JsonImportReadError(
                "The selected import file contains JSON nesting "
                "that is too deep."
            ) from error

    @staticmethod
    def _build_unique_object(
        object_pairs,
    ):
        """
        Build one decoded JSON object while rejecting duplicate keys.

        object_pairs_hook is called for every object, including
        nested objects.
        """

        parsed_object = {}

        for key, value in object_pairs:
            if key in parsed_object:
                raise _DuplicateJsonObjectKeyError(
                    "Duplicate JSON object key."
                )

            parsed_object[
                key
            ] = value

        return parsed_object

    @staticmethod
    def _reject_nonstandard_number(
        constant_name,
    ):
        """
        Reject Python JSON extensions such as NaN and Infinity.
        """

        raise _NonStandardJsonNumberError(
            "Non-standard JSON numeric value: "
            f"{constant_name}."
        )

    @classmethod
    def _read_limited_bytes(
        cls,
        stream,
        max_file_size_bytes,
    ):
        read_method = getattr(
            stream,
            "read",
            None,
        )

        if not callable(
            read_method
        ):
            raise JsonImportReadError(
                "The selected import file does not provide a "
                "readable binary stream."
            )

        chunks = []
        total_bytes = 0

        try:
            while True:
                remaining_bytes = (
                    max_file_size_bytes
                    + 1
                    - total_bytes
                )

                if remaining_bytes <= 0:
                    break

                requested_bytes = min(
                    cls.READ_CHUNK_SIZE_BYTES,
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
                    raise JsonImportReadError(
                        "The selected import file must be read "
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
                    > max_file_size_bytes
                ):
                    break

        except JsonImportReadError:
            raise

        except (
            OSError,
            ValueError,
        ) as error:
            raise JsonImportReadError(
                "The selected import file could not be read."
            ) from error

        if total_bytes > max_file_size_bytes:
            raise JsonImportReadError(
                "The selected import file is too large. "
                "Maximum allowed size: "
                f"{max_file_size_bytes} bytes."
            )

        return b"".join(
            chunks
        )

    @staticmethod
    def _normalize_file_name(
        file_name,
    ):
        if not isinstance(
            file_name,
            str,
        ):
            raise JsonImportReadError(
                "The selected import file has no valid file name."
            )

        normalized_file_name = (
            file_name
            .replace(
                "\\",
                "/",
            )
            .split(
                "/"
            )[-1]
            .strip()
        )

        if (
            not normalized_file_name
            or normalized_file_name in {
                ".",
                "..",
            }
        ):
            raise JsonImportReadError(
                "The selected import file has no valid file name."
            )

        if len(
            normalized_file_name
        ) > 255:
            raise JsonImportReadError(
                "The selected import file name is too long."
            )

        if not normalized_file_name.lower().endswith(
            ".json"
        ):
            raise JsonImportReadError(
                "The selected import file must use the .json "
                "file extension."
            )

        return normalized_file_name

    @staticmethod
    def _normalize_max_file_size(
        max_file_size_bytes,
    ):
        if (
            isinstance(
                max_file_size_bytes,
                bool,
            )
            or not isinstance(
                max_file_size_bytes,
                int,
            )
        ):
            raise JsonImportReadError(
                "The maximum import file size must be an integer."
            )

        if max_file_size_bytes <= 0:
            raise JsonImportReadError(
                "The maximum import file size must be greater "
                "than zero."
            )

        return max_file_size_bytes