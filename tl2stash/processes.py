"""Whether Torchlight II is running, for the one decision that needs to know.

Not a way to watch the game.  The tool never synchronises with it, and the
whole of the design is that it does not have to: an item written now is picked
up at the next load, and one a save erased is recovered afterwards.  The one
question that wants an answer *before* anything happens is whether to warn
about a send, and this is that answer.

The list of processes comes from ``CreateToolhelp32Snapshot``, the documented
Win32 way to enumerate them, called through :mod:`ctypes` -- a program whose
one dependency is PySide6 should not grow a second one for a question this
small.  On a machine that is not Windows the answer is always no, which is the
honest one: there is no ``Torchlight2.exe`` there to be running.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

__all__ = ["GAME_EXE", "is_running"]

#: What the game's process is called.  Vanilla and modded alike -- a mod is
#: the same executable reading a different folder -- so this is the whole of
#: what "the game is running" means to the tool.
GAME_EXE = "Torchlight2.exe"

#: ``TH32CS_SNAPPROCESS``: the snapshot is to hold processes.
_TH32CS_SNAPPROCESS = 0x00000002

#: ``MAX_PATH``: how many bytes of executable name the record carries.
_MAX_PATH = 260


class _ProcessEntry32(ctypes.Structure):
    """The record ``Process32First`` and ``Process32Next`` fill in.

    Written out rather than imported from somewhere, because there is
    somewhere: this is the layout ``tlhelp32.h`` declares, in the order it
    declares it, types and all.  Getting the order wrong does not raise --
    the names simply come back from the wrong offsets -- so it is spelled out
    here once, next to the call that needs it.
    """

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * _MAX_PATH),
    ]


def _kernel32():
    """The library, with the three functions this module calls typed.

    ``use_last_error`` rather than ``errno``, which is what ctypes documents
    for the Win32 API.  Nothing here reads the error, because nothing here
    does anything about one -- a snapshot that cannot be taken answers "no".
    """
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    library.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    for name in ("Process32First", "Process32Next"):
        function = getattr(library, name)
        function.restype = wintypes.BOOL
        function.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32))
    library.CloseHandle.argtypes = (wintypes.HANDLE,)
    return library


def is_running(exe_name: str) -> bool:
    """Whether a process with this executable name is running.

    Matched without regard to case, because the name is what the system
    stores and Windows itself does not distinguish -- and a warning that
    missed the game over a capital letter would be worse than no warning.

    A snapshot that cannot be taken answers ``False``: this is only ever a
    reminder, and a reminder that appeared because the tool could not look
    would be noise.  Sending the item is allowed either way.
    """
    if sys.platform != "win32":
        return False

    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return False

    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        wanted = exe_name.casefold()
        found = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.decode("mbcs", "replace").casefold() == wanted:
                return True
            found = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return False
