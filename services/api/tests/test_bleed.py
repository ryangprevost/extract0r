"""How much of a drum stem is not that drum. X0R-1413.

Ryan: *"i heard snares in the reference kick when separated"*. He did. `compare_all` pairs
kick with kick by name, so nothing in the comparison could have crossed them over - DrumSep
had put an audible snare in the file labelled kick, and the application had no way to know
or to say so.

**The trap this is built around is that energy is the wrong measure.** On that reference,
87.7% of the kick stem's energy sits below 120 Hz, which reads as a perfectly good kick. A
kick's fundamental carries so much energy that the audible snare was 0.2% of it. Loudness in
the bands the drum does not live in is the measure that matches what a person hears, and it
put that stem 22.6 dB under itself.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.mastering.subdrum import (
    AUDIBLE_BLEED_DB,
    BAND_RESIDENTS,
    HOME_BANDS,
    MOSTLY_FOREIGN_DB,
    bleed_db,
    bleed_warning,
    foreign_bands,
)

SR = 44100
SECONDS = 6.0


def tone(hz: float, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * SECONDS)) / SR
    return amplitude * np.sin(2 * np.pi * hz * t)


def noise(amplitude: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(5)
    return amplitude * rng.standard_normal(int(SR * SECONDS))


# --- which bands belong to which drum ----------------------------------------------------


def test_home_and_foreign_partition_every_band():
    """Each drum's bands split cleanly in two, with nothing left over."""
    from app.services.mastering.instrument import BANDS

    every = {name for name, _low, _high in BANDS}
    for drum in ("kick", "snare", "cymbals", "toms"):
        foreign = set(foreign_bands(drum))
        home = set(HOME_BANDS[drum])
        assert foreign & home == set(), f"{drum} is both at home and foreign somewhere"
        assert foreign | home == every, f"{drum} misses a band entirely"


def test_home_bands_are_not_the_inverse_of_band_residents():
    """They answer different questions, and conflating them got one drum badly wrong.

    `BAND_RESIDENTS` is for attribution - given a finding in this band, which drum should
    I suspect - and it is right that `low` names only the kick, because a low-band finding
    on the snare almost always is the kick. `HOME_BANDS` asks where a drum's own sound
    lives. Inverting the first to answer the second counted a floor tom's fundamental as
    foreign to the toms file.
    """
    inverted = {
        drum: {band for band, residents in BAND_RESIDENTS.items() if drum not in residents}
        for drum in HOME_BANDS
    }
    assert inverted["toms"] != set(foreign_bands("toms")), (
        "foreign_bands is back to inverting the attribution table"
    )


def test_a_tom_lives_in_the_low_band():
    """Ryan: "the toms are ok i think they're more of an EQ range than an instrument."

    He was right and the physics says why: a floor tom's fundamental is 55 to 100 Hz,
    squarely inside `low`, and rack toms straddle the `low`/`low_mid` boundary at 100 to
    250. Counting that as foreign made two real toms stems measure 98% not-toms, which
    read as pure residue and was an artefact of the table.
    """
    assert "low" in HOME_BANDS["toms"]
    assert "low" not in foreign_bands("toms")


def test_a_real_tom_fundamental_does_not_read_as_foreign():
    """The correction, as a measurement rather than a table lookup.

    On the stems that prompted this, the figure moved from -1.2 dB to -15.3 - from
    "barely the drum" to ordinary bleed, in line with the snare.
    """
    floor_tom = tone(70.0) + 0.3 * tone(140.0)
    level = bleed_db(floor_tom, SR, "toms")
    assert level is not None
    assert level < AUDIBLE_BLEED_DB, f"a floor tom read as {level} dB of foreign content"


def test_a_kick_is_foreign_everywhere_above_the_low_mids():
    """Which is what the by-hand version used before this was derived, and it agreed."""
    assert set(foreign_bands("kick")) == {"high_mid", "presence", "air"}


# --- the measurement ------------------------------------------------------------------


def test_a_clean_kick_measures_clean():
    """Nothing but 60 Hz. Whatever comes back must be far below the audible gate."""
    level = bleed_db(tone(60.0), SR, "kick")
    assert level is not None
    assert level < AUDIBLE_BLEED_DB


def test_a_snare_hiding_in_a_kick_is_found():
    """The actual bug: a quiet broadband guest under a loud fundamental."""
    clean = bleed_db(tone(60.0), SR, "kick")
    with_guest = bleed_db(tone(60.0) + 0.02 * noise(), SR, "kick")
    assert with_guest is not None and clean is not None
    assert with_guest > clean + 10, "a guest 34 dB down did not move the figure"


def test_the_figure_rises_with_the_guest():
    levels = [
        bleed_db(tone(60.0) + amount * noise(), SR, "kick")
        for amount in (0.005, 0.02, 0.08)
    ]
    assert all(level is not None for level in levels)
    assert levels == sorted(levels)


def test_energy_share_would_have_missed_it():
    """The finding that shaped this, as an assertion.

    A broadband guest loud enough to hear is a rounding error in the energy of a stem
    whose fundamental is 60 Hz. Anything measuring share rather than loudness reads this
    stem as clean.
    """
    mixed = tone(60.0) + 0.02 * noise()
    spectrum = np.abs(np.fft.rfft(mixed)) ** 2
    freqs = np.fft.rfftfreq(len(mixed), 1 / SR)
    share_above_500 = spectrum[freqs >= 500].sum() / spectrum.sum()

    assert share_above_500 < 0.02, "the fixture is not the case being described"
    assert bleed_db(mixed, SR, "kick") > AUDIBLE_BLEED_DB, "loudness should still catch it"


def test_silence_says_nothing_rather_than_zero():
    """A drum the record barely plays has no honest figure, and 0 dB would read as the
    worst possible one."""
    assert bleed_db(np.zeros(int(SR * SECONDS)), SR, "kick") is None
    assert bleed_db(np.array([]), SR, "kick") is None


def test_stereo_and_mono_agree():
    mono = tone(60.0) + 0.02 * noise()
    stereo = np.stack([mono, mono], axis=-1)
    assert bleed_db(stereo, SR, "kick") == pytest.approx(bleed_db(mono, SR, "kick"), abs=0.5)


# --- what gets said -------------------------------------------------------------------


def test_a_clean_stem_says_nothing():
    """A line on every row saying separation is imperfect is a line nobody reads by the
    third drum."""
    assert bleed_warning("kick", -38.2) == ""


def test_an_audible_one_says_so_and_names_the_number():
    said = bleed_warning("kick", -21.4)
    assert "21 dB below it" in said
    assert "separation rather than the record" in said


def test_a_stem_that_is_barely_the_drum_gets_different_words():
    """Measured at -1.2 dB on a real reference, which is not "some bleed"."""
    said = bleed_warning("toms", -1.2)
    assert "barely the toms" in said
    assert "prefer your ears" in said
    assert "separation rather than the record" not in said, "the milder wording leaked"


def test_the_two_tiers_do_not_overlap():
    assert MOSTLY_FOREIGN_DB > AUDIBLE_BLEED_DB
    mild = bleed_warning("kick", (AUDIBLE_BLEED_DB + MOSTLY_FOREIGN_DB) / 2)
    severe = bleed_warning("kick", MOSTLY_FOREIGN_DB + 1)
    assert mild and severe and mild != severe


def test_an_unmeasurable_stem_says_nothing():
    assert bleed_warning("kick", None) == ""


def test_the_page_uses_the_same_two_thresholds():
    """Written in Python and again in JavaScript, and only one of them has a test runner.

    The same trick as `test_stages.test_the_browser_uses_the_same_constant`, for the same
    reason: a threshold that drifts leaves the page calling a stem clean that the server
    measured as barely the drum.
    """
    import re
    from pathlib import Path

    studio = Path(__file__).resolve().parents[3] / "apps" / "studio" / "wwwroot"
    source = (studio / "drums.js").read_text(encoding="utf-8")
    for name, expected in (
        ("AUDIBLE_BLEED_DB", AUDIBLE_BLEED_DB),
        ("MOSTLY_FOREIGN_DB", MOSTLY_FOREIGN_DB),
    ):
        match = re.search(name + r"\s*=\s*(-?[0-9.]+)", source)
        assert match, f"drums.js no longer declares {name}"
        assert float(match.group(1)) == expected, name
