"""Tape saturation: harmonics in the body of the sound, not on top of it.

The exciter and this are often confused because both are distortion. They are aimed at
opposite ends of the spectrum and do opposite jobs.

The exciter drives the upper mids and keeps only what lands *above* them, so nothing is
added to the range it was made from. It makes a mix brighter. Saturation distorts the
whole signal in place and keeps the result, so the harmonics land an octave or two above
each fundamental - which for a bass at 80 Hz means 160 and 240 Hz, and for a snare at
200 Hz means 400 and 600. It makes a mix feel fuller and more solid.

Kept deliberately gentle - about 1% harmonic distortion at the lowest setting and 2.5% at
the highest. A master wants no audible distortion, and a mix whose parts were already
saturated on the way in needs less again rather than more. At an earlier, hotter setting
this measurably rounded transients and was reported as wrecking dense rock mixes; at
these levels it barely moves the peaks at all, and the report says by how much so that
can be checked rather than assumed.

Programme-dependent by construction: the drive is scaled against the signal's own level,
so a quiet passage is not driven as hard as a loud one and the effect follows the music.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Past this it stops being warmth and starts being an effect. Tape machines were driven
#: hard as a sound, but that is a decision to make on a guitar, not on a master.
#:
#: This was 4 dB, which measured about 10% harmonic distortion and was reported as
#: audibly wrecking dense rock mixes. The received wisdom is that 1 to 2 dB is enough on
#: a master and that there should be no obvious distortion at all - and a mix whose parts
#: were already saturated on the way in needs less again, not more.
MAX_SATURATION_DB = 2.0

#: Oversampling factor. Distortion creates harmonics above the original content, and any
#: that land past Nyquist fold back as frequencies unrelated to the note - which sounds
#: like grit rather than warmth. Measured without it, a 7 kHz tone produced an alias at
#: 16.1 kHz only 43.8 dB down, and a bright cymbal-heavy mix is full of such tones. The
#: shaping happens at 4x and the result is filtered before coming back down.
OVERSAMPLE = 4

#: How much second harmonic to add alongside the odd orders. Tape is mostly third-order;
#: the even term is what keeps it sounding warm rather than hard.
EVEN_SHARE = 0.35

#: Where the low end stops being driven. Distorting the sub does not sound like weight,
#: it sounds like a broken speaker, and it eats headroom the limiter then pays for.
DRIVE_ABOVE_HZ = 90.0

#: How hard the dial pushes into the curve, and how much room it is given before it gets
#: there. Calibrated on a 300 Hz tone so the control spans about 3% harmonic distortion
#: at its lowest setting and 10% at its highest - subtle to obvious, both musical.
#:
#: Three attempts. The first put the whole range inside the straight part of the tanh,
#: where 1 dB and 4 dB both produced about -22 dB of harmonics and the dial did nothing.
#: The second fixed the range but started at 7%. The third, at 3-10%, was reported as
#: audibly wrecking dense rock mixes - which matches the advice that a master wants no
#: obvious distortion at all. This one runs about 1% to 2.5%.
DRIVE_PER_DB = 6.0
DRIVE_HEADROOM = 22.0


@dataclass
class SaturationReport:
    saturation_db: float = 0.0
    #: Harmonics added, as a dB change in the 2nd-3rd harmonic range.
    harmonics_added_db: float = 0.0
    #: Peak given up. Small is smoothing; large is losing the attack.
    peak_softened_db: float = 0.0
    notes: list[str] = field(default_factory=list)


def add_saturation(
    samples: np.ndarray,
    sample_rate: int,
    amount_db: float,
    report: SaturationReport | None = None,
) -> np.ndarray:
    """Drive the mix into a soft curve, keeping the low end out of it.

    The sub is split off first and added back untouched, so weight stays clean while
    everything above it gets the harmonics.
    """
    from scipy.signal import butter, sosfilt, sosfiltfilt

    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    if not amount_db:
        return audio

    amount_db = float(np.clip(amount_db, 0.0, MAX_SATURATION_DB))
    nyquist = sample_rate / 2.0

    # Zero-phase split, so low and high sum back to the input exactly and the crossover
    # does not rotate the kick against the bass.
    sos = butter(2, min(DRIVE_ABOVE_HZ / nyquist, 0.99), btype="low", output="sos")
    low = sosfiltfilt(sos, audio, axis=0)
    rest = audio - low

    # Drive scaled against the signal's own level rather than an absolute threshold, so
    # the same setting means the same thing on a quiet mix and a loud one.
    level = float(np.sqrt(np.mean(rest**2)))
    if level <= 1e-12:
        return audio
    drive = 10 ** (amount_db / DRIVE_PER_DB)

    # Up to 4x before shaping, back down after. The harmonics are made in a band where
    # there is room for them, and the downsampling filter removes whatever sits above the
    # original Nyquist instead of folding it back into the music.
    from scipy.signal import resample_poly

    upsampled = resample_poly(rest, OVERSAMPLE, 1, axis=0)
    normalised = upsampled / (level * DRIVE_HEADROOM) * drive
    odd = np.tanh(normalised)
    # Even harmonics come from asymmetry, and a squared term is asymmetric - but it is
    # also strictly positive, so it carries a DC offset straight into the master. The
    # mean comes back off, which leaves the second harmonic and takes the offset away.
    even = odd**2
    even = even - even.mean(axis=0, keepdims=True)
    shaped = (odd + EVEN_SHARE * even) * (level * DRIVE_HEADROOM)
    shaped = resample_poly(shaped, 1, OVERSAMPLE, axis=0)[: len(rest)]
    if len(shaped) < len(rest):
        shaped = np.pad(shaped, ((0, len(rest) - len(shaped)), (0, 0)))

    # Match the level back, so the control adds harmonics rather than volume - otherwise
    # every comparison of it is really a comparison of loudness.
    shaped_rms = float(np.sqrt(np.mean(shaped**2)))
    if shaped_rms > 1e-12:
        shaped *= level / shaped_rms

    out = low + shaped

    if report is not None:
        report.saturation_db = round(amount_db, 2)

        def band(x, lo, hi):
            band_sos = butter(
                4, [lo / nyquist, min(hi / nyquist, 0.99)], btype="band", output="sos"
            )
            return float(np.sqrt(np.mean(sosfilt(band_sos, x.mean(axis=1)) ** 2)))

        before, after = band(audio, 300.0, 2000.0), band(out, 300.0, 2000.0)
        report.harmonics_added_db = round(
            float(20 * np.log10((after + 1e-12) / (before + 1e-12))), 2
        )
        report.peak_softened_db = round(
            float(
                20 * np.log10(float(np.abs(audio).max()) + 1e-12)
                - 20 * np.log10(float(np.abs(out).max()) + 1e-12)
            ),
            2,
        )
        report.notes.append(
            f"saturation +{amount_db:.1f} dB: {report.harmonics_added_db:+.2f} dB through "
            f"the body, peaks softened by {report.peak_softened_db:.2f} dB, sub below "
            f"{DRIVE_ABOVE_HZ:.0f} Hz left clean"
        )
    return out
