"""Suggesting the finishing moves, from the same measurements that justify them.

The tonal match already answers "is this band too loud". These questions it cannot
ask, because none of them is a level:

  - Is there anything up top to lift at all, or does it have to be made?
  - Is the bass spread across the image instead of sitting in the middle?
  - Is there rumble under the music, eating headroom nobody hears?
  - Is the body thin, in the range where a record feels solid?
  - Does the mix move more than the reference, so its quiet parts fall away?
  - Is the top end *there all the time*, or only when something is hit?

All of them are measured on the summed mix and the summed reference, so this runs in the
fast half of the comparison - no separation needed - and every suggestion arrives with
the number that produced it.

A fourth once lived here, offering a short room to close the gaps between hits. The
measurement said it was working and the ear said otherwise - a reverb tail on drums is
obvious long before it shows up as reduced crest - so it was removed rather than tuned.
Brightness and presence are what "cohesion" turned out to mean, and an exciter provides
those without putting anything in the gaps.
"""

from __future__ import annotations

import numpy as np

#: Where a mix stops having recorded top end and starts having whatever the codec left.
AIR_BAND = (8000.0, 16000.0)
#: The range the air is judged against. Comparing air to the whole mix would just measure
#: how bright the music is; comparing it to the upper mids measures how much *sheen* sits
#: on top of the same material.
MIDS_BAND = (1500.0, 6000.0)
#: Below this much air relative to the reference's, a shelf has nothing to lift.
AIR_SHORTFALL_DB = 2.5

#: Where bass should be sitting in the middle.
BASS_BAND = (120.0, 250.0)
#: Wider than the reference by this factor and the low end is spread rather than solid.
BASS_SPREAD_RATIO = 1.35

#: What counts as under the music. A bass guitar's lowest string is 41 Hz.
RUMBLE_BAND = (18.0, 38.0)
#: More rumble than the reference by this much is worth removing.
RUMBLE_EXCESS_DB = 1.5

#: The octave where cymbals, air and sheen live, and where a record either has something
#: going on at all times or does not.
TOP_BAND = (10000.0, 16000.0)

#: A top octave this much less continuous than the reference's is heard as separate
#: bright events rather than as a sheen over the whole record.
CONTINUITY_GAP_DB = 3.0

#: Below this, a stem is buried deeply enough that what it does up top cannot matter.
BURIED_DB = -25.0

#: Above this continuity a stem is a sustained source rather than a hit-only one.
SUSTAINED_ABOVE = -12.0

#: Where the body of a mix lives - fundamentals and their first harmonics.
BODY_BAND = (300.0, 2000.0)
#: Thinner than the reference through the body by this much and saturation has something
#: to do: it adds harmonics exactly here.
BODY_SHORTFALL_DB = 1.5

#: How much more a mix may swing between its loud and quiet sections than its reference
#: before glue is worth offering. One that already moves less does not need it, and
#: compressing it further would be actively wrong.
RANGE_EXCESS_DB = 1.5

#: And it has to be playing. Continuity compares a quiet percentile against a typical
#: one, which is meaningless when most of the stem is silence: both land near zero and
#: the ratio reads as perfectly continuous. A stem that plays in 4% of the song scored
#: -6 dB by that measure and was named as "the part playing continuously up there".
MIN_ACTIVE_SHARE = 0.4


def _band_rms(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    high = min(high, sample_rate / 2 * 0.99)
    if low >= high:
        return 0.0
    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    return float(np.sqrt(np.mean(sosfiltfilt(sos, audio, axis=0) ** 2)))


def _side_to_mid(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1 or audio.shape[1] < 2:
        return 0.0
    high = min(high, sample_rate / 2 * 0.99)
    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    band = sosfiltfilt(sos, audio, axis=0)
    mid = (band[:, 0] + band[:, 1]) / 2.0
    side = (band[:, 0] - band[:, 1]) / 2.0
    return float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-12))


def continuity_db(
    samples: np.ndarray,
    sample_rate: int,
    low: float = TOP_BAND[0],
    high: float = TOP_BAND[1],
) -> float:
    """How much of the time the top octave is doing something, as a dB gap.

    The quiet tenth of the track against the median. Near zero means something is up
    there continuously; deeply negative means it only appears when something is struck.

    This is the difference a bright home mix usually has from a record, and it is not a
    level: a mix can carry *more* top end than its reference and still sound like ticks,
    because the cymbals have nothing behind them to ring over. Measured on one such mix,
    2.3 dB more sheen than the reference and 8.9 dB less continuity.
    """
    from scipy.signal import butter, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    high = min(high, sample_rate / 2 * 0.99)
    if low >= high or audio.size == 0:
        return 0.0
    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    filtered = np.abs(sosfiltfilt(sos, audio, axis=0))
    if filtered.ndim > 1:
        filtered = filtered.mean(axis=1)

    window = max(1, sample_rate // 10)
    usable = len(filtered) // window * window
    if usable < window * 8:
        return 0.0
    levels = filtered[:usable].reshape(-1, window).mean(axis=1)
    quiet = float(np.percentile(levels, 10))
    typical = float(np.percentile(levels, 50))
    return float(20 * np.log10((quiet + 1e-12) / (typical + 1e-12)))


def _range_db(samples: np.ndarray, sample_rate: int) -> float:
    """The spread between this mix's loud sections and its quiet ones, in dB.

    Measured as a percentile spread of one-second block levels, which is the shape of the
    EBU loudness-range measure and describes what parallel compression actually changes.

    Not crest. Crest - the median short-window peak against the overall RMS - was tried
    here and is backwards for this question: when a mix has quiet passages the median
    window *is* quiet, so the ratio falls, and a dynamic mix scores lower than a flat one.
    That measure answers "how dense is this", not "how much does it move", and the two
    point in opposite directions. It is the third time in this codebase that a ratio of
    percentiles has been mistaken for a measure of peakiness.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    window = max(1, sample_rate)
    usable = len(audio) // window * window
    if usable < window * 8:
        return 0.0
    blocks = audio[:usable].reshape(-1, window)
    levels = np.sqrt((blocks**2).mean(axis=1))
    with np.errstate(divide="ignore"):
        db = 20 * np.log10(np.maximum(levels, 1e-12))
    # Anything far below the loudest block is silence between sections, not a quiet part.
    db = db[db > db.max() - 40.0]
    if db.size < 4:
        return 0.0
    return float(np.percentile(db, 95) - np.percentile(db, 10))


def _middle(samples: np.ndarray, sample_rate: int, seconds: float = 60.0) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float64)
    start = len(audio) // 4
    window = audio[start : start + int(sample_rate * seconds)]
    return window if len(window) > sample_rate else audio


def suggest(
    source: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    reference_rate: int | None = None,
    source_stems: dict | None = None,
) -> list[dict]:
    """Findings for each finishing move, carrying the dial that answers it.

    `source_stems` is optional and only sharpens one finding: given the separated stems,
    the continuity finding can name which instrument is sustained but turned down, which
    is the thing to actually move.
    """
    reference_rate = reference_rate or sample_rate
    mine = _middle(source, sample_rate)
    theirs = _middle(reference, reference_rate)
    out: list[dict] = []

    # --- is there any top end to lift? ------------------------------------------------
    my_air = _band_rms(mine.mean(axis=1), sample_rate, *AIR_BAND)
    my_mids = _band_rms(mine.mean(axis=1), sample_rate, *MIDS_BAND)
    their_air = _band_rms(theirs.mean(axis=1), reference_rate, *AIR_BAND)
    their_mids = _band_rms(theirs.mean(axis=1), reference_rate, *MIDS_BAND)
    if my_mids > 1e-9 and their_mids > 1e-9:
        my_sheen = 20 * np.log10((my_air + 1e-12) / my_mids)
        their_sheen = 20 * np.log10((their_air + 1e-12) / their_mids)
        shortfall = float(their_sheen - my_sheen)
        if shortfall >= AIR_SHORTFALL_DB:
            wanted = float(np.clip(shortfall * 0.8, 1.5, 6.0))
            out.append(
                {
                    "area": "finish:sparkle",
                    "severity": "notable" if shortfall >= 5.0 else "slight",
                    "delta_db": round(shortfall, 2),
                    "headline": "There is less on top than the reference has to work with",
                    "detail": (
                        f"Against the same amount of upper-mid content, your mix carries "
                        f"{shortfall:.1f} dB less above 8 kHz than the reference does. "
                        f"Brightness is a shelf and can only lift what is already there, "
                        f"which is why it does so little for parts played from a synth "
                        f"patch or taken direct off a DI - there is nothing up there to "
                        f"raise. Sparkle makes the harmonics instead, from the mix's own "
                        f"upper mids, so what arrives follows the playing."
                    ),
                    "action": {
                        "label": f"Add {wanted:.1f} dB of sparkle",
                        "dials": {"sparkle": round(wanted, 1)},
                    },
                    "clause": "a darker top end",
                }
            )

    # --- is the bass spread? ----------------------------------------------------------
    my_bass = _side_to_mid(mine, sample_rate, *BASS_BAND)
    their_bass = _side_to_mid(theirs, reference_rate, *BASS_BAND)
    if their_bass > 1e-6 and my_bass > their_bass * BASS_SPREAD_RATIO:
        ratio = my_bass / their_bass
        out.append(
            {
                "area": "finish:bass-width",
                "severity": "notable" if ratio >= 2.0 else "slight",
                "delta_db": round(float(20 * np.log10(ratio)), 2),
                "headline": "Your bass is spread where the reference keeps it centred",
                "detail": (
                    f"Between {BASS_BAND[0]:.0f} and {BASS_BAND[1]:.0f} Hz your low end "
                    f"measures {my_bass:.2f} of side against mid where the reference "
                    f"measures {their_bass:.2f} - {ratio:.1f} times as wide. That is "
                    f"usually what a muddy, loose bottom end is, and it is also why the "
                    f"bass can seem to disappear: side content cancels the moment "
                    f"anything sums to mono, so it is loud on headphones and half gone "
                    f"on a phone. Centring it applies no EQ - nothing gets louder, more "
                    f"of it simply survives."
                ),
                "action": {
                    "label": "Centre the bass",
                    "dials": {"centreBass": 150},
                },
                "clause": "a spread low end",
            }
        )

    # --- is there rumble under the music? ---------------------------------------------
    my_rumble = _band_rms(mine.mean(axis=1), sample_rate, *RUMBLE_BAND)
    my_level = float(np.sqrt(np.mean(mine**2)))
    their_rumble = _band_rms(theirs.mean(axis=1), reference_rate, *RUMBLE_BAND)
    their_level = float(np.sqrt(np.mean(theirs**2)))
    if my_level > 1e-9 and their_level > 1e-9:
        excess = float(
            20 * np.log10((my_rumble + 1e-12) / my_level)
            - 20 * np.log10((their_rumble + 1e-12) / their_level)
        )
        if excess >= RUMBLE_EXCESS_DB:
            out.append(
                {
                    "area": "finish:subsonic",
                    "severity": "slight",
                    "delta_db": round(excess, 2),
                    "headline": "There is more under the music than the reference carries",
                    "detail": (
                        f"Below {RUMBLE_BAND[1]:.0f} Hz you have {excess:.1f} dB more "
                        f"than the reference, relative to the rest of the mix. Nothing "
                        f"plays down there - a bass guitar's lowest string is 41 Hz - so "
                        f"it is rumble, handling and room. You will not hear it on most "
                        f"systems, but the limiter hears it perfectly well and spends "
                        f"headroom on it that could have gone to the music."
                    ),
                    "action": {"label": "Cut it", "dials": {"subsonic": 30}},
                    "clause": "rumble under the music",
                }
            )

    # --- is it thinner through the body than the reference? ---------------------------
    my_body = _band_rms(mine.mean(axis=1), sample_rate, *BODY_BAND)
    their_body = _band_rms(theirs.mean(axis=1), reference_rate, *BODY_BAND)
    my_level = float(np.sqrt(np.mean(mine**2)))
    their_level = float(np.sqrt(np.mean(theirs**2)))
    if my_level > 1e-9 and their_level > 1e-9:
        thin_by = float(
            20 * np.log10((their_body + 1e-12) / their_level)
            - 20 * np.log10((my_body + 1e-12) / my_level)
        )
        if thin_by >= BODY_SHORTFALL_DB:
            # A quarter of the shortfall, capped low. Saturation does not fill a body gap
            # the way an EQ does - it adds harmonics of what is already there - so asking
            # it to close 4 dB just distorts. The measured shortfall says *look at this*;
            # it does not say how hard to push.
            wanted = float(np.clip(thin_by * 0.25, 0.5, 1.5))
            out.append(
                {
                    "area": "finish:saturation",
                    "severity": "slight",
                    "delta_db": round(thin_by, 2),
                    "headline": "Thinner through the body than the reference",
                    "detail": (
                        f"Between {BODY_BAND[0]:.0f} Hz and {BODY_BAND[1] / 1000:.0f} kHz "
                        f"you carry {thin_by:.1f} dB less than the reference does relative "
                        f"to the rest of the mix. That range is fundamentals and their "
                        f"first harmonics, which is where a record feels solid. Saturation "
                        f"adds harmonics exactly there - the other end of the spectrum "
                        f"from sparkle, which only works above 6 kHz - and rounds the "
                        f"transients on the way, which is most of what glue means. "
                        f"Deliberately a small amount: a master wants no audible "
                        f"distortion, and a mix whose parts were already saturated going "
                        f"in needs less again. Start here and stop as soon as it stops "
                        f"helping."
                    ),
                    "action": {
                        "label": f"Add {wanted:.1f} dB of saturation",
                        "dials": {"saturation": round(wanted * 2) / 2},
                    },
                    "clause": "a thinner body",
                }
            )

    # --- does it move more than the reference does? -----------------------------------
    my_range = _range_db(mine, sample_rate)
    their_range = _range_db(theirs, reference_rate)
    if my_range and their_range and (my_range - their_range) >= RANGE_EXCESS_DB:
        excess = float(my_range - their_range)
        wanted = int(np.clip(round(excess * 3 / 5) * 5, 5, 25))
        out.append(
            {
                "area": "finish:parallel",
                "severity": "slight",
                "delta_db": round(excess, 2),
                "headline": "Your mix moves more than the reference does",
                "detail": (
                    f"Your loud sections sit {my_range:.1f} dB above your quiet ones, "
                    f"against {their_range:.1f} dB on the reference - so the quiet parts "
                    f"of your mix fall further back than theirs do. Parallel glue blends a "
                    f"heavily compressed copy underneath, which lifts the quiet detail "
                    f"without touching the attacks, because the copy sits below the dry "
                    f"signal rather than replacing it. This is the gentler half of what "
                    f"the loudness difference is made of; the rest is the limiter."
                ),
                "action": {
                    "label": f"Blend in {wanted}%",
                    "dials": {"parallel": wanted},
                },
                "clause": "more movement than the reference",
            }
        )

    # --- is the top end there all the time, or only on hits? --------------------------
    mine_continuity = continuity_db(mine, sample_rate)
    theirs_continuity = continuity_db(theirs, reference_rate)
    gap = theirs_continuity - mine_continuity
    if mine_continuity and theirs_continuity and gap >= CONTINUITY_GAP_DB:
        # The same stretch of music the mix was measured over. Given whole files while
        # the mix was windowed, a part that only plays in the last chorus reads as a
        # quiet constant presence across the whole song, which it is not.
        windowed = {
            name: _middle(np.asarray(samples, dtype=np.float64), sample_rate)
            for name, samples in (source_stems or {}).items()
        }
        culprits = _sustained_but_buried(windowed, sample_rate)
        pointer = ""
        if culprits:
            # One name and two names need different sentences. "the only parts are
            # guitar, and they are turned down" is the sort of thing that makes a tool
            # read as generated rather than written.
            # "the guitar stem" rather than "the guitar". Separation sorts a track into
            # six buckets and anything that is not one of them lands in the nearest, so a
            # synth pad arrives labelled guitar or other. Naming the stem is true; naming
            # the instrument is a guess, and being confidently wrong about what someone
            # played is a good way to have the rest of the finding disbelieved.
            if len(culprits) == 1:
                pointer = (
                    f" In your mix the only part playing continuously up there is the "
                    f"{culprits[0]} stem, and it is turned well down. Bringing it up is "
                    f"what puts something behind the cymbals - a fader move rather than a "
                    f"master one."
                )
            else:
                names = " and ".join((", ".join(culprits[:-1]), culprits[-1]))
                pointer = (
                    f" In your mix the only parts playing continuously up there are the "
                    f"{names} stems, and both are turned well down. Bringing one up is "
                    f"what puts something behind the cymbals - a fader move rather than a "
                    f"master one."
                )

        out.append(
            {
                "area": "finish:continuity",
                "severity": "notable" if gap >= 6.0 else "slight",
                "delta_db": round(float(gap), 2),
                "headline": "Your top end arrives on hits; the reference's is always there",
                "detail": (
                    f"Above {TOP_BAND[0] / 1000:.0f} kHz your quiet moments sit "
                    f"{mine_continuity:.1f} dB under your typical ones, against "
                    f"{theirs_continuity:.1f} dB on the reference - so the reference has "
                    f"something up there continuously and your mix does not. This is not "
                    f"a level and it does not mean you are dark: a mix can carry more top "
                    f"end than its reference and still sound like ticks, because cymbals "
                    f"read as splash when they ring over a bed and as ticks when they ring "
                    f"over silence.{pointer} Sparkle will not close this - it is "
                    f"programme-dependent, so it makes harmonics only while a part is "
                    f"playing and cannot fill a gap. Measured on one mix, exciting each "
                    f"stem in turn moved this by under a decibel, and two of them made it "
                    f"worse. Some of any reference's continuity is also heavy limiting "
                    f"lifting its quiet moments, so expect to close part of this, not all."
                ),
                "clause": "a top end that only arrives on hits",
            }
        )

    out.sort(key=lambda f: -abs(f["delta_db"]))
    return out


def _active_share(samples: np.ndarray, sample_rate: int) -> float:
    """What fraction of the time this stem is playing at all.

    Guards the continuity measure from its own blind spot. Continuity is a ratio of
    percentiles, so a stem that is silent for most of a song has a quiet percentile and a
    typical percentile that are both near zero, and reads as flawlessly continuous. It is
    not continuous; it is absent.
    """
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    window = max(1, sample_rate // 2)
    usable = len(audio) // window * window
    if usable < window:
        return 0.0
    levels = np.abs(audio[:usable]).reshape(-1, window).mean(axis=1)
    loudest = float(levels.max())
    if loudest <= 1e-9:
        return 0.0
    return float((levels > loudest * 0.05).mean())


def _sustained_but_buried(
    stems: dict, sample_rate: int, limit: int = 2
) -> list[str]:
    """Stems that play continuously up top but are too quiet to be doing so audibly.

    These are the ones worth a fader rather than an effect: the character is already
    right and only the level is wrong.
    """
    if not stems:
        return []

    loudest = 0.0
    levels: dict[str, float] = {}
    for name, samples in stems.items():
        audio = np.asarray(samples, dtype=np.float64)
        if audio.size == 0:
            continue
        level = float(np.sqrt(np.mean(audio**2)))
        levels[name] = level
        loudest = max(loudest, level)
    if loudest <= 1e-9:
        return []

    found: list[tuple[float, str]] = []
    for name, level in levels.items():
        relative = 20 * np.log10((level + 1e-12) / loudest)
        # Quiet enough not to matter yet, but not so quiet it is effectively absent.
        if not (-55.0 < relative < BURIED_DB):
            continue
        if _active_share(stems[name], sample_rate) < MIN_ACTIVE_SHARE:
            continue
        if continuity_db(stems[name], sample_rate) > SUSTAINED_ABOVE:
            found.append((relative, name))

    found.sort(reverse=True)
    return [name for _, name in found[:limit]]
