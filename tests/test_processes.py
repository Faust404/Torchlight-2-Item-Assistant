"""Whether the tool can tell that the game is running.

One question, and the tests are about the answer's shape rather than about
Torchlight II: the machine running the suite may or may not have the game open,
and neither may change what these assert.  So they ask about the interpreter
they are themselves running in -- a process this test knows is up -- and about
a name that is certainly not.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.processes import GAME_EXE, is_running  # noqa: E402

#: The process these tests can be sure of, because they are running in it.
SELF = os.path.basename(sys.executable or "python.exe")

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="there is no process list to read on this platform",
)


@windows_only
def test_the_program_asking_the_question_is_running():
    """The one process the test can name without hoping.

    If this came back False the enumeration would be broken in the way that
    matters most -- quietly, because a warning that never fires looks exactly
    like a game that is never open.
    """
    assert is_running(SELF) is True


@windows_only
def test_the_name_is_matched_without_regard_to_case():
    """``PYTHON.EXE`` is the same process as ``python.exe``.

    Windows does not distinguish them, and a warning that missed the game over
    a capital letter would be worse than no warning at all -- it would be a
    warning the player has learned not to trust.
    """
    assert is_running(SELF.upper()) is True


@windows_only
def test_a_name_nothing_is_running_under_is_not_running():
    """The ordinary answer, and the one that has to be right: on any machine
    that is not playing Torchlight II, nothing may interrupt a send."""
    assert is_running("torchlight2_item_assistant_no_such_program.exe") is False
    answer = is_running(GAME_EXE)
    assert answer is True or answer is False, "the game's own name is a question"


def test_a_machine_that_is_not_windows_answers_no(monkeypatch):
    """The honest answer rather than an error: there is no ``Torchlight2.exe``
    on a platform that does not run the game, so the tool behaves as it does
    when the game is closed -- which is the way it is meant to behave."""
    import tl2stash.processes as processes

    monkeypatch.setattr(processes.sys, "platform", "linux")

    assert is_running(SELF) is False
