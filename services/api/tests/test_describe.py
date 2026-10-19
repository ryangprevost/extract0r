"""Describe it: prompts read into recipes, and a version's levels set to the reference's.
Sprint 21."""

from __future__ import annotations

import json

import numpy as np

from app.services.synth import describe, levels

CONTEXT = describe.Context(labels=["intro", "verse", "chorus", "post-chorus", "bridge"],
                           styles=["EDM", "House", "Half-time"],
                           kits=["edm", "punchy", "club punch tight"])


def read(prompt):
    return describe.VocabularyReader().read(prompt, CONTEXT)


def test_complextro_sets_the_controls_it_means():
    # Sprint 26: complextro is its own style now, with its own config - it used to be read
    # as "EDM, with these extras", which is how a genre ends up half-described.
    r = read("complextro, gritty lead over clean chords, wide, punchy kick").recipe
    assert r.style == "Complextro" and r.beat == "techno" and r.stabs and r.lead_over_chords
    assert r.parts["piano"].grit == 0.65 and r.parts["guitar"].grit == 0.0
    assert r.parts["guitar"].width == 1.0 and r.kit == "club punch tight"


def test_section_names_are_whole_words():
    r = read("no verses, keep the post-chorus subdued, drop into the chorus").recipe
    assert r.arrangement.skip == ["verse"]
    assert r.arrangement.subdued == ["post-chorus"]
    assert r.arrangement.drop_at == "chorus"


def test_tempo_and_what_it_did_not_use():
    reading = read("house at 124 bpm, sparkly, instrumental")
    assert reading.recipe.style == "House" and reading.recipe.tempo == 124.0
    assert reading.recipe.leave_out == ["vocals"]
    assert "sparkly" in reading.unused


def test_the_same_words_make_the_same_recipe():
    a = read("complextro, lots of chops, quiet bridge").to_dict()
    b = read("complextro, lots of chops, quiet bridge").to_dict()
    assert a == b


def test_the_claude_reader_only_fills_the_recipe():
    """With a fake client: its answer is validated as a recipe, nothing more."""

    class Block:
        text = json.dumps({"style": "House", "stabs": True, "understood": ["house, stabs"]})

    class Messages:
        def create(self, **_):
            class Reply:
                content = [Block()]
            return Reply()

    class Client:
        messages = Messages()

    reading = describe.ClaudeReader("key", client=Client()).read("anything", CONTEXT)
    assert reading.recipe.style == "House" and reading.recipe.stabs
    assert reading.reader == "claude" and reading.understood == ["house, stabs"]


def test_the_reader_is_free_unless_claude_is_asked_for_and_has_a_key():
    class S:
        prompt_reader = "claude"
        anthropic_api_key = ""
        prompt_model = ""
    assert describe.reader_for(S()).name == "vocabulary"
    S.anthropic_api_key = "k"
    assert describe.reader_for(S()).name == "claude"
    S.prompt_reader = "vocabulary"
    assert describe.reader_for(S()).name == "vocabulary"


def test_levels_move_each_group_to_the_references_balance():
    rate = 8000
    t = np.arange(rate * 4) / rate

    def tone(hz, amp):
        x = amp * np.sin(2 * np.pi * hz * t)
        return np.stack([x, x], axis=1)

    stems = {"bass": tone(60, 0.5), "drums": tone(100, 0.5), "other": tone(440, 0.5)}
    layers = {"bass": tone(60, 0.5), "beat": tone(100, 0.5), "guitar": tone(440, 2.0)}
    moved = levels.match(layers, rate, stems, rate)
    assert abs(moved["channels"]["guitar"]["gain_db"] - (-12.0)) < 0.3
    assert abs(moved["channels"]["beat"]["gain_db"]) < 0.3


def test_stabs_keep_their_grit_when_the_chords_are_clean():
    r = read("complextro, clean chords").recipe
    assert r.parts["guitar"].grit == 0.0 and r.parts["other"].grit == 0.5


def test_a_part_that_is_hardly_there_is_left_alone():
    rate = 8000
    t = np.arange(rate * 4) / rate

    def tone(hz, amp):
        x = amp * np.sin(2 * np.pi * hz * t)
        return np.stack([x, x], axis=1)

    stems = {"bass": tone(60, 0.5), "vocals": tone(300, 0.5)}
    layers = {"bass": tone(60, 0.5), "vocals": tone(300, 0.001)}
    moved = levels.match(layers, rate, stems, rate)
    assert "vocals" not in moved["channels"]
    assert any("left alone" in s for s in moved["said"])


def test_stabs_keep_their_grit_when_they_are_also_wide():
    r = read("complextro, wide").recipe
    assert r.parts["other"].grit == 0.5 and r.parts["other"].width == 1.0


# --- Sprint 26: styles carry the whole recipe, and the words come from them ------------------


def test_every_style_has_a_recipe_the_reader_can_use():
    """A style is a config, not four settings: each one must name parts this app has, a kit
    and beat it knows, and nothing the Recipe cannot hold."""
    from app.services.drums.kit import KITS
    from app.services.synth import styles
    from app.services.synth.groove import BUILT_IN

    for name in styles.STYLES:
        made = styles.recipe_for(name)
        describe.Recipe.model_validate(made)         # every field is a real control
        style = styles.STYLES[name]
        assert style["kit"] in KITS, f"{name}: unknown kit"
        assert not style["beat"] or style["beat"] in BUILT_IN, f"{name}: unknown beat"
        for stem in (made.get("parts") or {}):
            assert stem in describe.PARTS, f"{name}: unknown part {stem}"
        assert styles.guide(name), f"{name}: says nothing about itself"


def test_the_genres_ryan_named_are_all_there():
    from app.services.synth import styles

    names = {n.lower() for n in styles.STYLES}
    for wanted in ("techno", "trance", "electro house", "house", "complextro", "electro"):
        assert wanted in names or wanted in describe.genres(CONTEXT), wanted


def test_a_genre_word_brings_its_whole_recipe():
    """"more complextro" sets what complextro is, not just a style name."""
    r = read("make it more complextro").recipe
    assert r.style == "Complextro"
    assert r.stabs and r.lead_over_chords and r.chop_instruments
    assert r.chops == "lots" and r.fill and r.follow_bass and r.tidy
    assert r.parts["bass"].grit == 0.5 and r.parts["guitar"].width == 1.0
    assert r.parts["guitar"].pump_db == 14.0


def test_the_longest_genre_name_wins():
    assert read("electro house please").recipe.style == "Electro house"
    assert read("just electro").recipe.style == "Electro"


def test_the_new_words_ryan_asked_for():
    extended = read("extend the midi notes").recipe
    assert extended.fill and not extended.legato

    chopped = read("add suggested chops at key areas").recipe
    assert chopped.chops == "some"

    swung = read("house but swung").recipe
    assert swung.swing == 0.25 and swung.style == "House"

    straight = read("techno, dead straight, no chops").recipe
    assert straight.swing == 0.0 and straight.chops == "none"

    drums = read("no drums").recipe
    assert drums.leave_out == ["drums"]


def test_a_style_says_what_it_will_do_before_it_does_it():
    reading = read("complextro")
    said = " ".join(reading.understood).lower()
    assert "recipe" in said and "stabs" in said and "chopped" in said
    assert any("bpm" in line.lower() for line in reading.understood)
