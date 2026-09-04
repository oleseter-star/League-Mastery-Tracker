from pathlib import Path


PROJECT_ROOT = Path(
    SPECPATH
).resolve()

DATA_DIRECTORIES = (
    (
        "templates",
        "application/templates",
    ),
    (
        "static",
        "application/static",
    ),
    (
        "bundled_reference_data",
        "application/bundled_reference_data",
    ),
)

datas = [
    (
        str(
            PROJECT_ROOT
            / "application"
            / source_directory
        ),
        destination_directory,
    )
    for source_directory, destination_directory in (
        DATA_DIRECTORIES
    )
]

LINUX_HIDDEN_IMPORTS = [
    "PIL.Image",
    "PIL.ImageDraw",
    "pystray._xorg",
    "Xlib.error",
    "secretstorage",
    "secretstorage.collection",
    "secretstorage.item",
    "jeepney",
    "jeepney.bus",
    "jeepney.io.blocking",
]

analysis = Analysis(
    ["run.py"],
    pathex=[
        str(
            PROJECT_ROOT
        ),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=LINUX_HIDDEN_IMPORTS,
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
    name="LeagueMasteryTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
