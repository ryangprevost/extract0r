"""Sparkle: manufacturing top end that was never recorded.

A high shelf can only lift what is already there. That is the whole difference between
this and the air control, and it is why a shelf does nothing for a part played from a
synth patch or taken direct off a DI - there is no content above 8 kHz to raise, so
turning it up raises hiss and nothing else. An exciter makes new content instead, by
distorting the band below and keeping the harmonics that fall above it.

Worth being honest about an earlier attempt. Exciting the individual stems was tried to
close a measured gap - a home mix had 1.2 instruments' worth of energy above 4 kHz where
its reference had 2.0 - and it failed: even at a setting well into audible distortion it
reached 1.34, and the band above 8 kHz did not move at all. That failure was structural.
One drive band spanning 1.5-4 kHz produces harmonics at 3-8 kHz and cannot reach the top
octave however hard it is pushed.

So this drives two bands in series, and the second exists purely to reach the air band.
It is also a taste control rather than a match: nothing here is derived from the
reference, because "sparkle" is a preference and pretending to measure it would be
dishonest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Drive bands: where the harmonics are made from. The first pass feeds the brilliance
#: range, the second feeds the air above it - which one stage cannot reach, since
#: distortion multiplies frequency rather than adding to it.
DRIVE_BANDS: tuple[tuple[float, float], ...] = ((1500.0, 4000.0), (4000.0, 8000.0))

#: Where the harmonics are kept from, by default. Everything below this is filtered back
#: out, so the drive band is a source of harmonics rather than a thing being distorted.
DEFAULT_FROM_HZ = 6000.0
#: The usable span for that corner. Low is presence - consonants, pick attack, the part
#: of "clearer" that is not brightness. High is air, which is sheen and nothing else.
#: Below about 3 kHz it stops adding definition and starts adding grit.
MIN_FROM_HZ = 3000.0
MAX_FROM_HZ = 10000.0

#: The second stage's corner, relative to the first. Its harmonics come from an octave
#: higher, so keeping them at the same frequency would just double the first stage.
SECOND_STAGE_RATIO = 1.5

#: Ceiling on the control. Past this it stops being air and starts being distortion, and
#: the harmonics pile up faster than the ear reads them as brightness.
MAX_SPARKLE_DB = 6.0

#: Drive into the shaper. Enough to generate harmonics, not so much that the shaper
#: clips the drive signal itself into square waves.
DRIVE = 3.0

#: How much of the squared term to add. tanh alone is odd-order only, which sounds hard
#: and hollow; the even harmonics are what reads as air rather than as fuzz.
EVEN_SHARE = 0.5

#: The least air a mix is treated as having, relative to its own upper mids. Without a
#: floor, "add 3 dB of top end" applied to a mix with no top end adds 3 dB of nothing -
#: and a mix with no top end is precisely what this control is for.
AIR_FLOOR_SHARE = 0.03

#: The most this may add to the mix's peak, as a share of it. Harmonics from a soft
#: clipper are spiky and they arrive just before the limiter, so an uncapped exciter
#: spends the master's headroom on content nobody asked to be that loud.
MAX_PEAK_SHARE = 1.0

#: Where the generated harmonics are rounded off, as a multiple of their own RMS. Low
#: enough to flatten the handful of transients that dominate the peak, high enough to
#: leave the body of the signal alone.
SPIKE_CEILING = 2.5


@dataclass
class SparkleReport:
    sparkle_db: float = 0.0
    from_hz: float = DEFAULT_FROM_HZ
    #: Energy added above 8 kHz, in dB relative to what was there.
    air_added_db: float = 0.0
    #: How closely the added content follows the material it was made from. Near 1 means
    #: it moves with the playing; near 0 would mean noise was added.
    tracks_source: float = 0.0
    #: Set when the peak cap bound, so the setting delivered less than it asked for.
    capped: bool = False
    notes: list[str] = field(default_factory=list)


def _shape(drive: np.ndarray) -> np.ndarray:
    """Asymmetric soft clipping: odd harmonics from tanh, even from the squared term."""
    peak = float(np.abs(drive).max())
    if peak <= 1e-9:
        return np.zeros_like(drive)
    norm = drive / peak
    return (np.tanh(norm * DRIVE) + EVEN_SHARE * np.sign(norm) * norm**2) * peak


def add_sparkle(
    samples: np.ndarray,
    sample_rate: int,
    sparkle_db: float,
    from_hz: float = DEFAULT_FROM_HZ,
    report: SparkleReport | None = None,
) -> np.ndarray:
    """Generate harmonics from the mix's own upper mids and add them above `from_hz`.

    The generated content is high-passed before it is mixed in, so nothing is added back
    into the range it was made from - otherwise this would be a midrange distortion
    control wearing a brighter name.

    `from_hz` decides which of the three words an exciter is sold on it delivers. Low, at
    3-5 kHz, the harmonics land on consonants, pick attack and stick, and the result reads
    as *clearer* and more present. High, at 8-10 kHz, they land above everything and the
    result is *brighter* - sheen, and nothing that helps a part cut through. The default
    sits between the two.
    """
    from scipy.signal import butter, sosfilt

    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    if not sparkle_db:
        return audio

    sparkle_db = float(np.clip(sparkle_db, 0.0, MAX_SPARKLE_DB))
    from_hz = float(np.clip(from_hz, MIN_FROM_HZ, MAX_FROM_HZ))
    nyquist = sample_rate / 2.0
    generated = np.zeros_like(audio)

    corners = (from_hz, from_hz * SECOND_STAGE_RATIO)
    for (low, high), keep_above in zip(DRIVE_BANDS, corners, strict=True):
        if keep_above >= nyquist * 0.95:
            continue
        drive_sos = butter(
            4, [low / nyquist, min(high / nyquist, 0.99)], btype="band", output="sos"
        )
        keep_sos = butter(4, keep_above / nyquist, btype="high", output="sos")
        for channel in range(audio.shape[1]):
            shaped = _shape(sosfilt(drive_sos, audio[:, channel]))
            generated[:, channel] += sosfilt(keep_sos, shaped)

    # Scale the harmonics to actually produce the decibels asked for, measured on this
    # material rather than applied as a fixed fraction. A fixed fraction was the first
    # attempt and it was useless: the setting at maximum raised the air band by 0.36 dB,
    # because how much a constant gain achieves depends entirely on how much top end the
    # mix already had.
    air_sos = butter(4, 8000.0 / nyquist, btype="high", output="sos")
    existing = float(np.sqrt(np.mean(sosfilt(air_sos, audio.mean(axis=1)) ** 2)))
    made = float(np.sqrt(np.mean(sosfilt(air_sos, generated.mean(axis=1)) ** 2)))
    if made <= 1e-12:
        return audio

    # The floor is the point of the whole control. A part played from a synth patch has
    # almost no air, and scaling against "almost none" would add almost none - leaving
    # the one case an exciter exists for as the one case it does nothing about. So a mix
    # with less top end than this is treated as having this much, and the harmonics are
    # sized against its upper mids instead.
    mids_sos = butter(
        4, [1500.0 / nyquist, min(8000.0 / nyquist, 0.99)], btype="band", output="sos"
    )
    mids = float(np.sqrt(np.mean(sosfilt(mids_sos, audio.mean(axis=1)) ** 2)))
    reference_level = max(existing, mids * AIR_FLOOR_SHARE)

    # Power, not amplitude. The harmonics are not correlated with what is already up
    # there, so the two sum as energy: to end up N dB louder the addition has to be
    # sqrt(10^(N/10) - 1) times the existing level, not 10^(N/20) - 1. Using the
    # amplitude form undershot every setting by about half.
    wanted = reference_level * float(np.sqrt(10 ** (sparkle_db / 10.0) - 1.0))
    gain = wanted / made

    # Harmonics out of a soft clipper are spiky - a handful of transients tower over the
    # rest - and spikes are expensive here because this runs just before the limiter.
    # Rounding the spikes off first lets far more *energy* through the same peak budget,
    # which is the difference between a control that brightens and one that only ticks
    # the peak meter. Capping the gain instead was tried and simply disabled the control:
    # against an already-limited master every setting hit the cap and delivered the same
    # 0.4 dB.
    made_rms = float(np.sqrt(np.mean(generated**2)))
    if made_rms > 1e-12:
        ceiling = made_rms * SPIKE_CEILING
        generated = np.tanh(generated / ceiling) * ceiling
        # Softening changed the level, so re-measure what it now contributes.
        made = float(np.sqrt(np.mean(sosfilt(air_sos, generated.mean(axis=1)) ** 2)))
        if made <= 1e-12:
            return audio
        gain = wanted / made

    added_peak = float(np.abs(generated * gain).max())
    ceiling = float(np.abs(audio).max()) * MAX_PEAK_SHARE
    capped = False
    if added_peak > ceiling > 0:
        gain *= ceiling / added_peak
        capped = True

    out = audio + generated * gain

    if report is not None:
        report.sparkle_db = round(sparkle_db, 2)
        report.from_hz = round(from_hz)
        air_sos = butter(4, 8000.0 / nyquist, btype="high", output="sos")
        before = float(np.sqrt(np.mean(sosfilt(air_sos, audio.mean(axis=1)) ** 2)))
        after = float(np.sqrt(np.mean(sosfilt(air_sos, out.mean(axis=1)) ** 2)))
        report.air_added_db = round(
            float(20 * np.log10((after + 1e-12) / (before + 1e-12))), 2
        )

        # Does what arrived up there follow the playing, or is it just a haze?
        added = (out - audio).mean(axis=1)
        source = sosfilt(
            butter(4, [1500.0 / nyquist, 8000.0 / nyquist], btype="band", output="sos"),
            audio.mean(axis=1),
        )
        window = max(1, sample_rate // 10)
        usable = len(added) // window * window
        if usable >= window * 4:
            a = np.abs(added[:usable]).reshape(-1, window).mean(axis=1)
            b = np.abs(source[:usable]).reshape(-1, window).mean(axis=1)
            if a.std() > 1e-12 and b.std() > 1e-12:
                report.tracks_source = round(float(np.corrcoef(a, b)[0, 1]), 3)
        report.capped = capped
        report.notes.append(
            f"sparkle +{sparkle_db:.1f} dB from {from_hz / 1000:.1f} kHz up: "
            f"{report.air_added_db:+.1f} dB above 8 kHz, generated from the mix's own "
            "upper mids"
            + (", eased back to protect the peaks" if capped else "")
        )
    return out
