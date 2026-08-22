"""
Build-only application identity and Windows version-resource support.

Importing this module does not load application runtime configuration or
generate files. Callers must explicitly load the canonical configuration
and request version-file generation.
"""

import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile


WINDOWS_VERSION_COMPONENT_MAXIMUM = 65535

PYINSTALLER_VERSION_FILE_NAME = (
    "application-version-info.txt"
)


class ApplicationBuildMetadataError(
    RuntimeError
):
    """
    Raised when canonical build metadata cannot be validated or written.
    """


@dataclass(
    frozen=True
)
class ApplicationBuildMetadata:
    """
    Immutable application identity prepared for PyInstaller.
    """

    product_name: str
    release_name: str
    application_version: str
    windows_executable_name: str
    executable_basename: str
    file_description: str
    file_version: str
    internal_name: str
    original_filename: str
    product_version: str
    file_version_tuple: tuple
    product_version_tuple: tuple


def parse_windows_version(
    application_version,
):
    """
    Convert a three-part application version to Windows's four parts.
    """

    if (
        not isinstance(
            application_version,
            str,
        )
        or not application_version
    ):
        raise ApplicationBuildMetadataError(
            "The application version must be a non-empty string."
        )

    version_parts = application_version.split(
        "."
    )

    if len(version_parts) != 3:
        raise ApplicationBuildMetadataError(
            "The application version must contain exactly three "
            "numeric components."
        )

    if any(
        not version_part.isascii()
        or not version_part.isdecimal()
        for version_part in version_parts
    ):
        raise ApplicationBuildMetadataError(
            "Application version components must contain only "
            "decimal digits."
        )

    numeric_parts = tuple(
        int(
            version_part
        )
        for version_part in version_parts
    )

    if any(
        version_part
        > WINDOWS_VERSION_COMPONENT_MAXIMUM
        for version_part in numeric_parts
    ):
        raise ApplicationBuildMetadataError(
            "Application version components must be between 0 and "
            f"{WINDOWS_VERSION_COMPONENT_MAXIMUM}."
        )

    return (
        *numeric_parts,
        0,
    )


def derive_windows_executable_basename(
    windows_executable_name,
):
    """
    Validate a plain Windows executable filename and return its basename.
    """

    if (
        not isinstance(
            windows_executable_name,
            str,
        )
        or not windows_executable_name
    ):
        raise ApplicationBuildMetadataError(
            "The Windows executable name must be a non-empty string."
        )

    executable_path = PureWindowsPath(
        windows_executable_name
    )

    if (
        executable_path.drive
        or executable_path.parent
        != PureWindowsPath(".")
        or executable_path.name
        != windows_executable_name
        or "/" in windows_executable_name
        or "\\" in windows_executable_name
    ):
        raise ApplicationBuildMetadataError(
            "The Windows executable name must be a plain filename, "
            "not a path."
        )

    if (
        windows_executable_name.lower()
        == ".exe"
    ):
        raise ApplicationBuildMetadataError(
            "The Windows executable name must have a non-empty "
            "basename."
        )

    if (
        executable_path.suffix.lower()
        != ".exe"
    ):
        raise ApplicationBuildMetadataError(
            "The Windows executable name must have a valid .exe "
            "suffix."
        )

    executable_basename = (
        windows_executable_name[:-4]
    )

    if (
        not executable_basename
        or executable_basename
        in {
            ".",
            "..",
        }
    ):
        raise ApplicationBuildMetadataError(
            "The Windows executable name must have a non-empty "
            "basename."
        )

    invalid_characters = (
        '<>:"/\\|?*'
    )

    if any(
        character in invalid_characters
        or ord(
            character
        ) < 32
        for character in executable_basename
    ):
        raise ApplicationBuildMetadataError(
            "The Windows executable basename contains invalid "
            "filename characters."
        )

    return executable_basename


def load_application_build_metadata(
    config_class=None,
):
    """
    Load build identity from the canonical application configuration.
    """

    if config_class is None:
        from application.config import Config

        config_class = Config

    product_name = _require_non_empty_text(
        config_class.PRODUCT_NAME,
        field_name="Product name",
    )

    release_name = _require_non_empty_text(
        config_class.RELEASE_NAME,
        field_name="Release name",
    )

    application_version = (
        _require_non_empty_text(
            config_class.APPLICATION_VERSION,
            field_name=(
                "Application version"
            ),
        )
    )

    windows_executable_name = (
        _require_non_empty_text(
            config_class.WINDOWS_EXECUTABLE_NAME,
            field_name=(
                "Windows executable name"
            ),
        )
    )

    executable_basename = (
        derive_windows_executable_basename(
            windows_executable_name
        )
    )

    windows_version = (
        parse_windows_version(
            application_version
        )
    )

    return ApplicationBuildMetadata(
        product_name=product_name,
        release_name=release_name,
        application_version=(
            application_version
        ),
        windows_executable_name=(
            windows_executable_name
        ),
        executable_basename=(
            executable_basename
        ),
        file_description=release_name,
        file_version=application_version,
        internal_name=(
            executable_basename
        ),
        original_filename=(
            windows_executable_name
        ),
        product_version=(
            application_version
        ),
        file_version_tuple=(
            windows_version
        ),
        product_version_tuple=(
            windows_version
        ),
    )


def write_pyinstaller_version_file(
    metadata,
    destination_file,
):
    """
    Atomically write deterministic text-form PyInstaller version info.
    """

    if not isinstance(
        metadata,
        ApplicationBuildMetadata,
    ):
        raise ApplicationBuildMetadataError(
            "The application build metadata is invalid."
        )

    try:
        destination_path = Path(
            destination_file
        ).expanduser().resolve(
            strict=False
        )

    except (
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise ApplicationBuildMetadataError(
            "The PyInstaller version-file destination is invalid."
        ) from error

    if (
        destination_path.name
        != PYINSTALLER_VERSION_FILE_NAME
    ):
        raise ApplicationBuildMetadataError(
            "The PyInstaller version file must be named "
            f"{PYINSTALLER_VERSION_FILE_NAME}."
        )

    destination_directory = (
        destination_path.parent
    )

    version_file_content = (
        _render_pyinstaller_version_info(
            metadata
        )
    )

    temporary_path = None

    try:
        destination_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=(
                ".application-version-info."
            ),
            suffix=".tmp",
            dir=destination_directory,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(
                temporary_file.name
            )

            temporary_file.write(
                version_file_content
            )

            temporary_file.flush()

            os.fsync(
                temporary_file.fileno()
            )

        os.replace(
            temporary_path,
            destination_path,
        )

        temporary_path = None

    except OSError as error:
        raise ApplicationBuildMetadataError(
            "The PyInstaller version file could not be written."
        ) from error

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(
                    missing_ok=True
                )

            except OSError:
                pass

    return destination_path


def _require_non_empty_text(
    value,
    field_name,
):
    if (
        not isinstance(
            value,
            str,
        )
        or not value
        or value != value.strip()
    ):
        raise ApplicationBuildMetadataError(
            f"{field_name} must be a non-empty string without "
            "surrounding whitespace."
        )

    return value


def _render_pyinstaller_version_info(
    metadata,
):
    string_values = (
        (
            "FileDescription",
            metadata.file_description,
        ),
        (
            "FileVersion",
            metadata.file_version,
        ),
        (
            "InternalName",
            metadata.internal_name,
        ),
        (
            "OriginalFilename",
            metadata.original_filename,
        ),
        (
            "ProductName",
            metadata.product_name,
        ),
        (
            "ProductVersion",
            metadata.product_version,
        ),
    )

    string_structures = ",\n".join(
        (
            "            StringStruct("
            f"{field_name!r}, {field_value!r}"
            ")"
        )
        for field_name, field_value in (
            string_values
        )
    )

    return (
        "# UTF-8\n"
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={metadata.file_version_tuple!r},\n"
        f"    prodvers={metadata.product_version_tuple!r},\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo(\n"
        "      [\n"
        "        StringTable(\n"
        "          '040904B0',\n"
        "          [\n"
        f"{string_structures}\n"
        "          ]\n"
        "        )\n"
        "      ]\n"
        "    ),\n"
        "    VarFileInfo(\n"
        "      [\n"
        "        VarStruct('Translation', [1033, 1200])\n"
        "      ]\n"
        "    )\n"
        "  ]\n"
        ")\n"
    )
