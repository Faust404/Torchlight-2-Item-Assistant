"""Tests for the game-data facade.

Most of these run against a synthetic install -- a manifest, an archive and a
handful of DAT files built in the test -- so they hold on a machine that has
never seen Torchlight II.  What they cannot check is whether the *constants*
are right, since a fixture built from a wrong constant would agree with
itself; ``tests/test_dat.py`` pins those against the real files instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tl2stash.dat import (  # noqa: E402
    VAR_BADDES,
    VAR_BADDESOT,
    VAR_DISPLAYPRECISION,
    VAR_EFFECT_TYPE,
    VAR_GOODDES,
    VAR_GOODDESOT,
    VAR_NAME,
    VAR_SLOT_BASE,
    DatFile,
)
from tl2stash.gamedata import (  # noqa: E402
    DEFAULT_PRECISION,
    GameData,
    archive_path,
    find_install,
)

from test_dat import TEXT, TRANSLATE, write_dat  # noqa: E402
from test_pak import write_synthetic_pak  # noqa: E402


# --------------------------------------------------------------------------
# A synthetic install
# --------------------------------------------------------------------------


def install(tmp_path: Path) -> Path:
    """An install directory with just enough in it to load."""
    files: dict[str, bytes] = {}
    strings: dict[int, str] = {}

    def string(text: str) -> int:
        """The index of ``text`` in this file's dictionary, adding it if new."""
        index = len(strings)
        strings[index] = text
        return index

    def effect(name: str, templates: dict[int, str]) -> dict:
        """One effect node.  ``templates`` maps a description variable to its
        wording; written as a dict because the keys are the game's constants.
        """
        variables = {
            VAR_NAME: (TEXT, string(name)),
            VAR_EFFECT_TYPE: (TEXT, string(f"KEFFECT_TYPE_{name}")),
            VAR_DISPLAYPRECISION: (2, 2),
        }
        for var, text in templates.items():
            variables[var] = (TRANSLATE, string(text))
        return {"vars": variables}

    # The effects are the root's children -- EFFECTSLIST is a list, not a
    # single node -- and every string they mention shares one dictionary.
    effects = {
        "kids": [
            effect(
                "MELEEDAMAGEBONUS",
                {
                    VAR_GOODDES: "+[VALUE] Melee weapon damage bonus",
                    VAR_GOODDESOT: "+[VALUE] Melee weapon damage bonus for [DURATION]",
                    VAR_BADDES: "-[VALUE] Melee weapon damage penalty",
                    VAR_BADDESOT: "-[VALUE] Melee weapon damage penalty for [DURATION]",
                },
            ),
            effect("MAX MANA", {VAR_GOODDES: "+[VALUE] Max Mana"}),
        ]
    }
    files["MEDIA/EFFECTSLIST.DAT"] = write_dat(strings, [effects])

    # Containers: each names itself and declares the id the save file records.
    for name, cid in (("ARMS", 24), ("SPELLS", 26)):
        files[f"MEDIA/INVENTORY/CONTAINERS/SHARED_STASH_BAG_{name}.DAT"] = write_dat(
            {0: f"SHARED_STASH_BAG_{name}"},
            [{"vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, cid)}}],
        )
    # A slot file *beside* the containers: same idea, different space of
    # numbers, and its 0 is not container 0.
    files["MEDIA/INVENTORY/BAG.DAT"] = write_dat(
        {0: "BAG"}, [{"vars": {VAR_NAME: (TEXT, 0), VAR_SLOT_BASE: (2, 0)}}]
    )

    files["MEDIA/UNITS/ITEMS/SWORDS/DJINN FIRE SWORD.DAT"] = write_dat(
        {0: "Djinn Fire Sword"}, [{"vars": {VAR_NAME: (TEXT, 0)}}]
    )
    # Something the prefixes sweep up that is not a DAT at all.
    files["MEDIA/SKILLS/EMBER/EMBERBEAM.LAYOUT"] = b"<layout/>"
    # And something that is a DAT and will not parse.
    files["MEDIA/UNITS/ITEMS/BROKEN.DAT"] = b"\xff" * 40

    write_synthetic_pak(tmp_path / "PAKS", files)
    return tmp_path


@pytest.fixture
def game(tmp_path):
    return GameData.load(install(tmp_path))


# --------------------------------------------------------------------------
# Finding the install
# --------------------------------------------------------------------------


def test_an_install_is_recognised_by_its_manifest(tmp_path):
    root = install(tmp_path)
    assert archive_path(root).is_file()
    assert find_install(explicit=root) == root


def test_the_paks_folder_can_be_named_instead(tmp_path):
    """Whichever of the two someone has to hand."""
    root = install(tmp_path)
    assert archive_path(root / "PAKS").is_file()
    assert find_install(explicit=root / "PAKS") == root / "PAKS"


def test_a_directory_that_is_not_an_install_is_not_returned(tmp_path):
    """No manifest, so it is not an install, however it was typed."""
    (tmp_path / "somewhere").mkdir()
    assert find_install(explicit=tmp_path / "somewhere") is None


def test_the_environment_variable_is_used_when_given(tmp_path, monkeypatch):
    root = install(tmp_path)
    monkeypatch.setenv("TL2_INSTALL", str(root))
    assert find_install() == root


def test_a_bad_environment_variable_does_not_fall_through(tmp_path, monkeypatch):
    """Pointed somewhere wrong on purpose means None, not a different install.

    Falling back to the search would quietly show the player stats from an
    installation they did not ask for -- and if the one it fell back to were
    modded, the numbers would be wrong rather than missing.
    """
    monkeypatch.setenv("TL2_INSTALL", str(tmp_path / "nowhere"))
    assert find_install() is None


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def test_the_wanted_files_are_read_and_the_rest_are_left(game):
    """Five parse; the sixth is a DAT that will not, and a seventh is not a
    DAT at all."""
    assert game.files_read == 5
    assert [name for name, _ in game.failed] == ["MEDIA/UNITS/ITEMS/BROKEN.DAT"]


def test_a_file_that_will_not_parse_is_recorded_not_raised(game):
    """One bad file out of twelve thousand is not a reason to refuse to start.

    The items are in the save file and are unaffected either way, so the
    choice is between a tooltip with a line missing and a tool that does not
    open.
    """
    assert game.failed[0][1], "the reason was not kept"


def test_a_layout_file_is_never_offered_to_the_dat_parser(game):
    """It would fail, and calling that a broken data file would be a lie."""
    assert not any("LAYOUT" in name for name, _ in game.failed)


def test_a_manifest_that_is_not_there_raises(tmp_path):
    with pytest.raises(OSError):
        GameData.load(tmp_path / "nothing")


# --------------------------------------------------------------------------
# Looking things up
# --------------------------------------------------------------------------


def test_names_are_found_regardless_of_case(game):
    assert game.by_name("Djinn Fire Sword") is not None
    assert game.by_name("DJINN FIRE SWORD") is not None
    assert game.by_name("djinn fire sword") is not None
    assert game.by_name("Nobody") is None
    assert game.by_name("") is None


def test_an_effect_name_comes_from_the_effect_list(game):
    """Even when something else in the archive has the same name.

    Only EFFECTSLIST carries the description templates, so a node picked up
    from anywhere else would render an effect with no words.
    """
    node = game.by_name("MELEEDAMAGEBONUS")
    assert node is not None
    assert node.text(VAR_GOODDES) == "+[VALUE] Melee weapon damage bonus"


def test_an_effect_name_with_a_space_is_still_found(game):
    """The name is the one in the data, spaces and all.

    What the effect calls its *type* is a different string, and there the
    game puts an underscore in: the effect named ``MAX MANA`` declares itself
    ``KEFFECT_TYPE_MAX_MANA``.  Looking a name up uses the name.
    """
    node = game.by_name("MAX MANA")
    assert node is not None
    assert node.text(VAR_NAME) == "MAX MANA"
    assert node.text(VAR_EFFECT_TYPE) == "KEFFECT_TYPE_MAX MANA"


def test_effects_are_found_by_position_too(game):
    """The order in the file is the game's, and position is the fallback for
    a name that does not resolve."""
    assert game.effect_count == 2
    assert game.effect(0).text(VAR_NAME) == "MELEEDAMAGEBONUS"
    assert game.effect(1).text(VAR_NAME) == "MAX MANA"
    assert game.effect(2) is None
    assert game.effect(-1) is None
    assert game.effect(9999) is None


def test_a_description_is_chosen_by_the_type_the_item_asked_for(game):
    """Which of the four an effect uses is decided by the item, not the data."""
    node = game.by_name("MELEEDAMAGEBONUS")

    assert game.effect_template(node, 0x00) == "+[VALUE] Melee weapon damage bonus"
    assert game.effect_template(node, 0x01) == "+[VALUE] Melee weapon damage bonus"
    assert game.effect_template(node, 0x02) == (
        "+[VALUE] Melee weapon damage bonus for [DURATION]"
    )
    assert game.effect_template(node, 0x03) == "-[VALUE] Melee weapon damage penalty"
    assert game.effect_template(node, 0x04) == (
        "-[VALUE] Melee weapon damage penalty for [DURATION]"
    )


def test_a_type_with_no_wording_gives_nothing_rather_than_a_wrong_line(game):
    """An effect with no description for this type shows no line in the game
    either, so the honest answer is to say nothing.

    Falling back to one of the other three would put a penalty on the tooltip
    of an item that has a bonus.
    """
    node = game.by_name("MELEEDAMAGEBONUS")
    assert game.effect_template(node, 0x05) is None
    assert game.effect_template(node, 0xFF) is None

    bare = game.by_name("MAX MANA")
    assert game.effect_template(bare, 0x03) is None, "there is no penalty wording"


def test_precision_is_read_and_defaulted(game):
    assert game.display_precision(game.by_name("MELEEDAMAGEBONUS")) == 2

    # An effect that does not say.  All 239 in the shipped game do, so this is
    # the path a mod's effect would take.
    quiet = DatFile.parse(
        write_dat({}, [{"vars": {VAR_NAME: (TEXT, 0)}}])
    ).root
    assert game.display_precision(quiet) == DEFAULT_PRECISION


# --------------------------------------------------------------------------
# Containers
# --------------------------------------------------------------------------


def test_the_stash_bags_are_named_and_ordered(game):
    assert game.stash_tabs == [24, 26]
    assert game.container_name(24) == "SHARED_STASH_BAG_ARMS"
    assert game.container_name(26) == "SHARED_STASH_BAG_SPELLS"


def test_a_tab_is_reported_as_the_player_counts_it(game):
    """The player sees "the first tab", not "container 24"."""
    assert game.stash_tab(24) == 1
    assert game.stash_tab(26) == 2


def test_the_slot_files_beside_the_containers_are_not_containers(game):
    """They index the same idea in a different space of numbers.

    ``MEDIA/INVENTORY/BAG.DAT`` and ``MEDIA/INVENTORY/CONTAINERS/BODY.DAT``
    both declare 0.  Taking both would have one silently overwrite the other
    and hand out a container name for a number that means something else.
    """
    assert game.container_name(0) is None
    assert "BAG" not in game.containers.values()


def test_a_container_the_data_does_not_name_has_no_name(game):
    assert game.container_name(999) is None
    assert game.stash_tab(999) is None
    assert game.stash_tab(21) is None
