"""The folder the tool owns, and what decides it.

Two shapes of the tool, two answers -- a checkout keeps its data in ``var/``,
a packaged executable in the player's profile -- and the answers are not
interchangeable: the wrong one puts a database inside a bundle the system
empties, or beside an executable in a folder the player cannot write to.

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


@pytest.fixture(autouse=True)
def a_plain_environment(monkeypatch):
    """Both answers start from nothing being said.

    Every test here is about one of the two things that can be said -- the
    variable, and the freezer -- so neither may be left over from the machine
    the suite is running on.  ``sys.frozen`` is not set in a source run but
    *is* set in a frozen one, and a suite bundled into an executable is not a
    thing that happens; the environment variable is the one that could
    genuinely be set by the person running the tests.
    """
    monkeypatch.delenv(paths.ENV, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)


def test_a_checkout_keeps_its_data_beside_the_code():
    """``var/``, in the repository, which is where every tool here writes and
    where a developer looks for it."""
    answer = paths.data_dir()

    assert answer == Path(paths.__file__).resolve().parent.parent / "var"
    assert answer.name == "var"


def test_a_packaged_tool_keeps_its_data_in_the_player_s_profile(monkeypatch, tmp_path):
    """The executable's answer, and the reason for it: a bundle unpacks into a
    folder Windows empties, so data beside the code is data thrown away."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert paths.data_dir() == tmp_path / paths.APP_NAME


def test_the_profile_folder_still_answers_without_the_variable(monkeypatch):
    """``LOCALAPPDATA`` is set on every Windows this tool runs on.  A stripped
    environment gets a database in an unusual place rather than a crash at
    launch -- a packaged tool that will not start is one nobody can tell you
    about."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert paths.data_dir() == Path.home() / "AppData" / "Local" / paths.APP_NAME


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
    player's profile while checking that it does not."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    paths.data_dir()

    assert list(tmp_path.iterdir()) == []
