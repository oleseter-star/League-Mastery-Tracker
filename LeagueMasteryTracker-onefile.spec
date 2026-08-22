from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_submodules,
)
from pyinstaller_build_metadata import (
    load_application_build_metadata,
    write_pyinstaller_version_file,
)


PROJECT_ROOT = Path(
    SPECPATH
).resolve()

APPLICATION_BUILD_METADATA = (
    load_application_build_metadata()
)

APPLICATION_VERSION_FILE = (
    write_pyinstaller_version_file(
        metadata=(
            APPLICATION_BUILD_METADATA
        ),
        destination_file=(
            PROJECT_ROOT
            / "build"
            / "pyinstaller"
            / "application-version-info.txt"
        ),
    )
)

APPLICATION_ICON = (
    PROJECT_ROOT
    / "application"
    / "static"
    / "application.ico"
)

DATA_DIRECTORIES = (
    (
        PROJECT_ROOT
        / "application"
        / "templates",
        "application/templates",
    ),
    (
        PROJECT_ROOT
        / "application"
        / "static",
        "application/static",
    ),
    (
        PROJECT_ROOT
        / "application"
        / "bundled_reference_data",
        "application/bundled_reference_data",
    ),
)

datas = []

for source_directory, destination_directory in (
    DATA_DIRECTORIES
):
    if source_directory.is_dir():
        datas.append(
            (
                str(
                    source_directory
                ),
                destination_directory,
            )
        )


hiddenimports = collect_submodules(
    "pystray"
)


analysis = Analysis(
    ["run.py"],
    pathex=[
        str(
            PROJECT_ROOT
        ),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

python_archive = PYZ(
    analysis.pure
)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=(
        APPLICATION_BUILD_METADATA
        .executable_basename
    ),
    version=str(
        APPLICATION_VERSION_FILE
    ),
    icon=str(
        APPLICATION_ICON
    ),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
