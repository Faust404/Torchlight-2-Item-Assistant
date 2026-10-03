"""The folder the tool owns, and what decides it.

Two shapes of the tool, two answers -- a checkout keeps its data in ``var/``,
a packaged executable in the game's own folder beside the saves -- and the
answers are not interchangeable: the wrong one puts a database inside a bundle
the system empties, or a developer's scratch folder where a player's collection
belongs.

The tests here are the whole of the rule, because it is a rule about *this*
process and not about anything on disk: what shape the tool is, what the
environment says, and what comes back.  Nothing is created by asking, so
these tests can ask all they like without a temporary directory to clean up.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import paths  # noqa: E402
from tl2stash import saves  # noqa: E402


@pytest.fixture(autouse=True)
def a_plain_environment(monkeypatch):
    """Both answers start from nothing being said.

    Every test here is about one of the two things that can be said -- the
    variable, and the freezer -- so neither may be left over from the machine
    the suite is running on.  ``sys.frozen`` is not set in a source run but
    *is* set in a frozen one, and a suite bundled into an executable is not a
    thing that happens; the environment variable is the one that could
    genuinely be set by the person running the tests.

    The saves folder is pointed somewhere that is not there as well, so that a
    test asking about a packaged tool cannot be answered *by the machine
    running the suite* -- which would make it pass here and mean nothing
    anywhere else, and would read the real Documents folder of whoever ran it.
    """
    monkeypatch.delenv(paths.ENV, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(saves, "SAVE_ROOT", Path("nowhere") / "Torchlight 2")


def test_a_checkout_keeps_its_data_beside_the_code():
    """``var/``, in the repository, which is where every tool here writes and
    where a developer looks for it -- and deliberately not the game's folder,
    which belongs to the person playing the game rather than to the person
    changing the parser."""
    answer = paths.data_dir()

    assert answer == Path(paths.__file__).resolve().parent.parent / "var"
    assert answer.name == "var"


def test_a_packaged_tool_keeps_its_data_beside_the_game_s_own_files(
    monkeypatch, tmp_path
):
    """The executable's answer: ``tl2ia_save/`` inside the game's folder, next
    to ``save/`` and ``modsave/``.

    Not beside the executable, and not in the profile: it is the folder the
    player already finds, already backs up, and already takes to another
    machine, so the items ride along with the saves they came out of."""
    game_folder = tmp_path / "My Games" / "Runic Games" / "Torchlight 2"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(saves, "SAVE_ROOT", game_folder)

    answer = paths.data_dir()

    assert answer == game_folder / paths.SAVE_FOLDER
    assert answer.name == "tl2ia_save"


def test_the_folder_follows_the_saves_rather_than_a_path_of_its_own(
    monkeypatch, tmp_path
):
    """Where the answer comes from, which is the point of deriving it: the
    tool's folder is ``SAVE_ROOT`` plus one name, so a machine whose Documents
    folder is somewhere unusual puts the database where it put the saves."""
    elsewhere = tmp_path / "redirected" / "Torchlight 2"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(saves, "SAVE_ROOT", elsewhere)

    assert paths.data_dir().parent == elsewhere


def test_the_variable_moves_the_folder(monkeypatch, tmp_path):
    """And moves it in both shapes of the tool, because it is checked first:
    a player who has said where their data goes has said it for the tool they
    are running, not for one shape of it."""
    wanted = tmp_path / "on-a-stick"

    monkeypatch.setenv(paths.ENV, str(wanted))
    assert paths.data_dir() == wanted

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.data_dir() == wanted


def test_asking_where_the_folder_is_does_not_make_it(monkeypatch, tmp_path):
    """Not tidiness.  A function that created a folder as a side effect would
    create one for every caller that only meant to ask -- and the callers
    include the tests, which is how a suite ends up writing into a real
    player's Documents folder while checking that it does not."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(saves, "SAVE_ROOT", tmp_path / "Torchlight 2")

    paths.data_dir()

    assert list(tmp_path.iterdir()) == []
