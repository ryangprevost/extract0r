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
    r = read("complextro, gritty lead over clean chords, wide, punchy kick").recipe
    assert r.style == "EDM" and r.beat == "techno" and r.stabs and r.lead_over_chords
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
