"""Where the game's saves are looked for, and who gets to decide.

What these tests hold down is a precedence, not a path.  Windows is asked,
because the game itself is handed the same answer and a Documents folder the
player has moved has to be followed rather than guessed at; the
``%USERPROFILE%`` spelling is the fallback for a machine where Windows will
not answer; and ``TL2IA_SAVES`` beats both, for saves somewhere neither of
them names.

Nothing here reads the machine: the Shell and the guess are both replaced, so
a test says the same thing wherever the suite runs.  The one test that does
call the Shell asserts only what is true whatever it answers.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash import saves  # noqa: E402

#: The game's folder under a Documents folder, spelled out here rather than
#: imported, so a rename in the module cannot quietly rename the expectation.
TREE = Path("My Games") / "Runic Games" / "Torchlight 2"

#: ``FOLDERID_Profile``, for the one test that watches the id decide the
#: answer -- a folder every Windows machine has.
_PROFILE = uuid.UUID("{5E6C858F-0E22-4760-9AFE-EA3317B67173}")


@pytest.fixture(autouse=True)
def nothing_said(monkeypatch):
    """The variable is not left over from the machine the suite is running on:
    a test that passed because the environment happened to hold it would mean
    nothing anywhere else."""
    monkeypatch.delenv(saves.ENV_SAVES, raising=False)


def _answering(monkeypatch, documents: Path | None) -> None:
    """Windows, made to answer with ``documents`` -- or to say nothing."""
    monkeypatch.setattr(saves, "_known_documents", lambda: documents)


def test_the_documents_folder_windows_names_is_the_one_followed(
    monkeypatch, tmp_path
):
    """The point of asking at all: a Documents folder OneDrive has moved is
    where the game now writes its saves, so it is where the tool looks.

    The guess underneath is not consulted even as a tie-breaker, and the
    answer stands whether or not the folder is there yet: the game would
    create it, and second-guessing the Shell is how a leftover tree gets
    picked over the live one."""
    moved = tmp_path / "OneDrive" / "Documents"
    _answering(monkeypatch, moved)
    monkeypatch.setattr(saves, "_assumed_documents", lambda: tmp_path / "Documents")

    answer = saves._resolve_root()

    assert answer == moved / TREE
    assert answer != tmp_path / "Documents" / TREE
    assert not answer.exists()


def test_the_guess_is_for_a_machine_windows_will_not_answer_for(
    monkeypatch, tmp_path
):
    """``%USERPROFILE%\\Documents``, which is right on a machine that has never
    moved it -- the tool's whole behaviour before it started asking."""
    _answering(monkeypatch, None)
    assumed = tmp_path / "Documents"
    monkeypatch.setattr(saves, "_assumed_documents", lambda: assumed)

    assert saves._resolve_root() == assumed / TREE


def test_the_variable_beats_windows_and_the_guess(monkeypatch, tmp_path):
    """For saves neither of them names: a stick, a second install, a profile
    whose Documents even the Shell has lost track of."""
    elsewhere = tmp_path / "on-a-stick" / "Torchlight 2"
    monkeypatch.setenv(saves.ENV_SAVES, str(elsewhere))
    _answering(monkeypatch, tmp_path / "Documents")
    monkeypatch.setattr(saves, "_assumed_documents", lambda: tmp_path / "Documents")

    assert saves._resolve_root() == elsewhere


def test_the_variable_names_the_folder_with_save_and_modsave_in_it(
    monkeypatch, tmp_path
):
    """What it is taken to mean, because one level too deep is the shape of a
    bug: the folder the game keeps ``save/`` and ``modsave/`` in -- what
    ``SAVE_ROOT`` has always been -- and not the Documents folder above it,
    the way it is taken for neither of the other two sources."""
    saves_folder = tmp_path / "Torchlight 2"
    monkeypatch.setenv(saves.ENV_SAVES, str(saves_folder))

    assert saves._resolve_root() == saves_folder


def test_the_guess_follows_the_profile_variable(monkeypatch, tmp_path):
    """The fallback is the environment's own spelling of the profile, so a
    test or a script that moves ``USERPROFILE`` moves it too."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    assert saves._assumed_documents() == tmp_path / "Documents"


def test_windows_is_asked_with_a_call_that_answers_or_keeps_quiet():
    """The real Shell call, on the machine running the suite: an existing
    folder, or no answer at all, and never an exception -- it decides a module
    constant, so a Shell that will not answer has to be a fallback and not a
    failure to start."""
    answer = saves._known_documents()

    if answer is not None:
        assert answer.is_absolute()
        assert answer.is_dir()


def test_the_id_is_really_what_decides_the_answer():
    """The GUID is handed over in the little-endian order Windows lays a GUID
    out in -- easy to get subtly wrong, and invisible while the one id in use
    keeps answering: asked about two different folders through the same call,
    the Shell answers two different places."""
    documents = saves._known_folder(saves._DOCUMENTS)
    profile = saves._known_folder(_PROFILE)

    if documents is None or profile is None:
        pytest.skip("the Shell will not answer on this machine")
    assert documents != profile
    assert documents.is_dir()
    assert profile.is_dir()


def test_the_root_the_tool_landed_on_is_the_game_s_own_folder():
    """Whatever the machine said, the constant is the folder the game keeps
    ``save/`` and ``modsave/`` in -- the shape every reader of ``SAVE_ROOT``
    is written against."""
    if os.environ.get(saves.ENV_SAVES):
        pytest.skip("TL2IA_SAVES is set in this environment")

    assert saves.SAVE_ROOT.name == "Torchlight 2"
    assert saves.SAVE_ROOT.parent.name == "Runic Games"
    assert saves.SAVE_ROOT.parent.parent.name == "My Games"
