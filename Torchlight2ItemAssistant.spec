# -*- mode: python ; coding: utf-8 -*-
"""How the executable is built.

Committed rather than passed as command-line flags, because the flags *are*
the program: this file says what goes in, what the exe is called, what icon
and version resource it wears, and that it is one file with no console.  A
release built from this file and a release built from a developer's machine
are the same release.

Build it from the repository root:

    pip install -r requirements-build.txt
    pyinstaller --noconfirm Torchlight2ItemAssistant.spec

The result is ``dist/Torchlight2ItemAssistant.exe`` -- one file, no console,
no installer.  It writes nothing beside itself: the database and the settings
go to the player's own profile, which is :mod:`app.paths`' decision and the
reason this can be dropped anywhere the player likes.
"""

import importlib.util
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).resolve()  # noqa: F821 -- spelled by PyInstaller


def _load(path: Path, name: str):
    """Import a file by path, outside any package.

    ``app/version.py`` is written to be importable this way -- it has no
    imports of its own -- so the build reads the version out of the source
    that is about to be frozen rather than out of anything the build itself
    is told.  A tag and the code under it cannot disagree.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERSION = _load(ROOT / "app" / "version.py", "app_version").__version__
PARTS = tuple(int(part) for part in VERSION.split(".")) + (0,)


def version_resource() -> str:
    """The Windows version resource, written where the build can read it.

    This is what a player sees on the exe's Properties page, and it is the
    only place a downloaded file can be asked what it is without running it.
    Generated from ``app/version.py`` rather than kept as a checked-in file,
    because two copies of a version are two places to forget.
    """
    info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=PARTS,
            prodvers=PARTS,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,  # VOS_NT_WINDOWS32
            fileType=0x1,  # VFT_APP
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",  # US English, Unicode
                        [
                            StringStruct(
                                "FileDescription", "Torchlight 2 Item Assistant"
                            ),
                            StringStruct("FileVersion", VERSION),
                            StringStruct(
                                "InternalName", "Torchlight2ItemAssistant"
                            ),
                            StringStruct(
                                "OriginalFilename",
                                "Torchlight2ItemAssistant.exe",
                            ),
                            StringStruct(
                                "ProductName", "Torchlight 2 Item Assistant"
                            ),
                            StringStruct("ProductVersion", VERSION),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    # ``workpath`` -- lowercase -- is one of the names PyInstaller puts in a
    # spec's namespace, and it is the right place for this: a generated file
    # belongs in the build's own folder, which is already thrown away and
    # already ignored by git.
    out = Path(workpath) / "version_info.txt"  # noqa: F821 -- from PyInstaller
    out.write_text(str(info), encoding="utf-8")
    return str(out)


#: The analysis starts at the launcher rather than at ``app/__main__.py``:
#: a frozen entry script has no package around it, so the package module's
#: relative imports would fail at launch.  See ``tl2ia.py``.
analysis = Analysis(  # noqa: F821 -- from PyInstaller
    [str(ROOT / "tl2ia.py")],
    pathex=[str(ROOT)],
    binaries=[],
    # The faces the tool is drawn in, and the icon it wears.  Both are read at
    # runtime through ``__file__``, which a frozen module answers with the
    # bundle's extracted copy -- so they have to keep the paths they have in
    # the checkout, under ``app/``.
    datas=[
        (str(ROOT / "app" / "fonts"), "app/fonts"),
        (str(ROOT / "app" / "icon.ico"), "app"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing else is excluded.  The bundle holds what the tool imports and
    # nothing more, which is what PyInstaller already does -- an exclusion
    # list here would be a claim about the code that a later import could
    # quietly falsify.
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821 -- from PyInstaller

exe = EXE(  # noqa: F821 -- from PyInstaller
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="Torchlight2ItemAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Not UPX: it shrinks the file and buys a fistful of antivirus false
    # positives on a tool that already writes to the player's save file, which
    # is the last executable that wants to look suspicious.
    upx=False,
    runtime_tmpdir=None,
    # A window, not a console: a black rectangle behind the window is not part
    # of the tool.  A traceback still reaches the player -- PyInstaller shows
    # its own dialog for an unhandled exception when there is no console --
    # which is the one message a downloader might actually need to send back.
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "app" / "icon.ico"),
    version=version_resource(),
)
