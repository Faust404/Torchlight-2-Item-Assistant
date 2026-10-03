"""The choices the tool remembers between runs.

Which is a very short list -- the warning before a send is the only one -- and
the tests are mostly about what happens when the file is not what the tool
wrote: missing, half-written, edited by hand, or not a file at all.  Every one
of those has the same answer, and the answer is the defaults, because a
remembered choice that goes wrong may cost the player one question asked twice
and must never cost them anything else.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import Settings  # noqa: E402


def test_a_choice_survives_the_end_of_the_run(tmp_path):
    """The whole point: written on the spot, read by the next run.

    The next run is a new process, so this is a new ``Settings`` over the same
    path rather than the same one asked twice.
    """
    path = tmp_path / "settings.json"

    Settings(path).set("warn_me", False)

    assert Settings(path).get("warn_me", True) is False


def test_a_file_that_is_not_there_answers_the_default(tmp_path):
    """The first run of the tool, and every run after a player who deleted the
    file -- which is a thing the file being readable is *for*."""
    assert Settings(tmp_path / "settings.json").get("warn_me", True) is True


def test_a_file_that_is_not_json_answers_the_default(tmp_path):
    """A file caught half-written by a crash, or one something else wrote.

    Not an error and not a crash: the tool opens, the player is asked a
    question they had already answered once, and the next tick of the box
    writes a good file over the bad one.
    """
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json", encoding="utf-8")

    settings = Settings(path)

    assert settings.get("warn_me", True) is True
    settings.set("warn_me", False)
    assert json.loads(path.read_text(encoding="utf-8")) == {"warn_me": False}


def test_a_file_that_is_not_even_an_object_answers_the_default(tmp_path):
    """JSON has five things a top-level value can be and only one of them is a
    settings file.  ``[1, 2, 3]`` parses, so the parse is not the check."""
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert Settings(path).get("warn_me", True) is True


def test_a_choice_of_the_wrong_type_answers_the_default(tmp_path):
    """The file is meant to be editable by hand, and ``"no"`` where a boolean
    belongs is a choice the tool has no reading of.

    Saying what the default says beats guessing at what was meant: guessing
    wrong can only ever cost the player the warning, and the warning is the
    thing here that is load-bearing.
    """
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"warn_me": "no"}), encoding="utf-8")

    assert Settings(path).get("warn_me", True) is True
    assert Settings(path).get("warn_me", False) is False


def test_the_file_is_written_the_way_a_person_would_write_it(tmp_path):
    """Indented, sorted, and ending in a newline, because a choice the tool
    remembers for the player should be one they can read and edit without a
    tool.  Sorted as well, so the file does not reshuffle itself between runs
    and a diff of it says only what changed."""
    path = tmp_path / "settings.json"

    settings = Settings(path)
    settings.set("b_second", 2)
    settings.set("a_first", 1)

    assert path.read_text(encoding="utf-8") == (
        '{\n  "a_first": 1,\n  "b_second": 2\n}\n'
    )


def test_the_folder_is_made_if_it_is_not_there(tmp_path):
    """The packaged build will point this at a folder in the player's profile
    that does not exist until the first choice is made."""
    path = tmp_path / "profile" / "deeper" / "settings.json"

    Settings(path).set("warn_me", False)

    assert Settings(path).get("warn_me", True) is False


def test_a_file_that_cannot_be_written_is_not_an_error(tmp_path):
    """A read-only folder, or something else holding the file open.

    What a remembered choice is worth does not justify an error message about
    a checkbox, and the cost of forgetting is one question asked again -- so
    the write is swallowed and the choice still holds for this run.  A
    directory is used as the stand-in for every one of those, because it is
    the one that fails the same way on every machine.
    """
    path = tmp_path / "a_directory"
    path.mkdir()

    settings = Settings(path)
    assert settings.get("warn_me", True) is True

    settings.set("warn_me", False)

    assert settings.get("warn_me", True) is False
    assert path.is_dir(), "the write went somewhere after all"
