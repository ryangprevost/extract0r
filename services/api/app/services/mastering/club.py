"""The club finish: a version made loud enough to play out, without losing its punch.

Through Sprints 16-22 every remix Ryan was sent had been finished by a script that lived
outside the application, because the bounce deliberately stops at "a sketch of the version,
not a master" and the mastering page is built around matching a reference's *tone* rather
than reaching a club's *loudness*. That left the one step he could not do himself. This is
that script, made a feature, with the measurements that shaped it.

### Why a clipper before the limiter

A limiter alone cannot make a punchy mix loud. Measured on the punchy VaVaVa remix,
reaching -10.6 LUFS with the limiter alone took up to 12.5 dB of gain reduction riding on
the kicks - which flattens exactly the punch the mix was built for. Club masters put a
**soft clipper** first: it shaves the tips of the transients, where a few samples cost
nothing audible, and the limiter then only catches what is left. On the same mix that was
0.3% of samples clipped by more than 3.5 dB, and the limiter's average reduction fell from
1.4 dB to 0.2.

So the chain is: **glue → (optional) tonal match → soft clip → limit → true-peak ceiling**,
with the gain solved so the result lands on the asked-for loudness.

### Why it does not chase the reference's loudness

"Bounce" is mastered at -6 LUFS. A remix pushed there is squashed, so the target is a
setting with a sensible default (-9.5 LUFS, where club and streaming masters meet) rather
than whatever the reference happens to be. The report says what the reference measures, so
the choice is informed rather than hidden.

### Why the tonal match never lifts the top

The mastering engine's `matching_curve` is reused, but above 1.5 kHz only its *cuts* are
kept. On a gritty remix the lift it asks for is the grinding: distortion already puts
intermodulation up there, and matching a cleaner record's spectrum turns that up. Cuts are
left alone, so a mix that is genuinely too bright still gets fixed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Where a club master usually sits, in LUFS. Loud enough to hold its own, with the peaks
#: still alive; -14 is streaming's own normalisation, -8 and below is squashed.
DEFAULT_TARGET_LUFS = -9.5
#: The true peak the file is held under. -1 dBTP is the usual delivery ceiling: a lossy
#: encoder's reconstruction can ride above the samples, and this leaves it room.
CEILING_DBTP = -1.0
#: The limiter's own ceiling, below the clipper's, so it only catches what the clipper left.
LIMITER_DB = -1.5
#: Where the clipper starts to bend, as a fraction of its ceiling. Below this nothing is
#: touched at all.
KNEE = 0.7
#: How much range the glue compressor takes out before any of this.
GLUE_DB = 3.0
#: Above this the tonal match may only cut - see the module docstring.
NO_LIFT_ABOVE_HZ = 1500.0
#: Targets offered on the page.
TARGETS = {"club": -9.5, "loud": -8.0, "streaming": -14.0, "gentle": -12.0}


@dataclass
class Finish:
    """What the finish did, in numbers that can be checked."""

    before_lufs: float
    after_lufs: float
    true_peak_dbtp: float
    gain_db: float
    clipped_share: float          # of samples the clipper touched at all
    limiter_mean_db: float
    limiter_max_db: float
    reference_lufs: float | None = None
    eq_said: str = ""

    def to_dict(self) -> dict:
        return {
            "before_lufs": round(self.before_lufs, 1),
            "after_lufs": round(self.after_lufs, 1),
            "true_peak_dbtp": round(self.true_peak_dbtp, 1),
            "gain_db": round(self.gain_db, 1),
            "clipped_share": round(self.clipped_share, 4),
            "limiter_mean_db": round(self.limiter_mean_db, 2),
            "limiter_max_db": round(self.limiter_max_db, 2),
            "reference_lufs": None if self.reference_lufs is None
            else round(self.reference_lufs, 1),
            "eq_said": self.eq_said,
        }

    def said(self) -> list[str]:
        """The finish in sentences, including what it cost - never a bare reassurance."""
        lines = [f"{self.before_lufs:.1f} LUFS to {self.after_lufs:.1f}, "
                 f"true peak {self.true_peak_dbtp:.1f} dBTP."]
        if self.eq_said:
            lines.append(self.eq_said)
        touched = self.clipped_share * 100
        lines.append(
            f"The clipper shaved the tips of {touched:.1f}% of samples and the limiter rode "
            f"{self.limiter_mean_db:.2f} dB on average ({self.limiter_max_db:.1f} dB at most)."
            if touched or self.limiter_mean_db else "Neither the clipper nor the limiter had "
            "anything to do - this was already under the ceiling.")
        if self.limiter_mean_db > 1.5:
            lines.append("That is a lot of limiting: the punch is coming off. Try a quieter "
                         "target, or turn something down in the mix.")
        if self.reference_lufs is not None:
            lines.append(f"Your reference measures {self.reference_lufs:.1f} LUFS." + (
                " Chasing it would squash this mix, which is why the target is its own setting."
                if self.reference_lufs > self.after_lufs + 1.5 else ""))
        return lines


def soft_clip(audio: np.ndarray, ceiling_db: float = CEILING_DBTP) -> np.ndarray:
    """Round off whatever passes `KNEE` of the ceiling, at twice the sample rate.

    Oversampled because clipping makes harmonics above the original's, and at the base rate
    the ones past Nyquist fold back down as inharmonic fizz - the same reason `synth/grit.py`
    oversamples.

    **It holds the ceiling everywhere but the very ends.** The resampler's step response rings
    at the array's edges - measured at +0.6 dB over on a constant - so this is a shaper, not a
    guarantee. The limiter and the true-peak check after it are what make the ceiling true,
    which is the order `finish` runs them in."""
    from scipy.signal import resample_poly

    x = np.asarray(audio, dtype=np.float64)
    ceiling = 10 ** (ceiling_db / 20)
    knee = ceiling * KNEE
    # Nothing near the ceiling: handed back untouched rather than round-tripped through the
    # resampler, which would leave its own small error on a signal that needed no clipping.
    if float(np.max(np.abs(x))) <= knee:
        return x
    up = resample_poly(x, 2, 1, axis=0)
    over = np.abs(up) > knee
    bend = knee + (ceiling - knee) * np.tanh((np.abs(up) - knee) / (ceiling - knee))
    up = np.where(over, np.sign(up) * bend, up)
    return resample_poly(up, 1, 2, axis=0)[: len(x)]


def _toned(audio: np.ndarray, reference: np.ndarray, sample_rate: int) -> tuple[np.ndarray, str]:
    """`audio` moved towards the reference's tonal balance, never lifted above
    `NO_LIFT_ABOVE_HZ`. Returns the audio and a sentence about the biggest moves."""
    from app.services.mastering.dsp import (
        MatchSettings,
        apply_curve,
        average_spectrum,
        matching_curve,
    )

    settings = MatchSettings()
    curve = matching_curve(
        average_spectrum(audio, settings.n_fft, settings.hop),
        average_spectrum(reference, settings.n_fft, settings.hop),
        sample_rate, settings)
    freqs = np.fft.rfftfreq(settings.n_fft, 1.0 / sample_rate)
    curve = np.where(freqs > NO_LIFT_ABOVE_HZ, np.minimum(curve, 1.0), curve)
    db = 20 * np.log10(np.maximum(curve, 1e-9))
    moves = []
    for hz in (60, 120, 250, 500, 1000, 2000, 4000, 8000):
        value = db[np.argmin(np.abs(freqs - hz))]
        if abs(value) >= 0.5:
            moves.append(f"{hz} Hz {value:+.1f}")
    said = ("Moved towards your reference's tone: " + ", ".join(moves) + " dB."
            if moves else "Already as close to your reference's tone as this moves it.")
    return apply_curve(audio, curve, settings.n_fft, settings.hop), said


def finish(audio: np.ndarray, sample_rate: int, target_lufs: float = DEFAULT_TARGET_LUFS,
           reference: np.ndarray | None = None,
           reference_rate: int | None = None) -> tuple[np.ndarray, Finish]:
    """A version finished for a club: glued, optionally matched to the reference's tone,
    clipped, limited, and landed on `target_lufs` under a -1 dBTP ceiling."""
    from app.services.mastering.dsp import limit_with_report, true_peak_db
    from app.services.mastering.dynamics import compress
    from app.services.mastering.loudness_meter import integrated_loudness

    source = np.asarray(audio, dtype=np.float64)
    if source.ndim == 1:
        source = np.stack([source, source], axis=1)
    before, _ = integrated_loudness(source, sample_rate)

    work = compress(source, sample_rate, GLUE_DB)
    said = ""
    if reference is not None:
        work, said = _toned(work, reference, sample_rate)
    glued, _ = integrated_loudness(work, sample_rate)

    ceiling = 10 ** (CEILING_DBTP / 20)
    gain_db = target_lufs - glued
    out, report, after = work, None, glued
    for _ in range(4):
        pushed = work * 10 ** (gain_db / 20)
        clipped = soft_clip(pushed)
        out, report = limit_with_report(clipped, sample_rate, ceiling_db=LIMITER_DB)
        peak = true_peak_db(out, sample_rate)
        if peak > CEILING_DBTP:
            out = out * 10 ** ((CEILING_DBTP - peak) / 20)
        after, _ = integrated_loudness(out, sample_rate)
        if abs(after - target_lufs) < 0.15:
            break
        gain_db += target_lufs - after
    touched = float(np.mean(np.max(np.abs(work * 10 ** (gain_db / 20)), axis=1) > ceiling * KNEE))

    return np.clip(out, -1.0, 1.0), Finish(
        before_lufs=float(before), after_lufs=float(after),
        true_peak_dbtp=float(true_peak_db(out, sample_rate)), gain_db=float(gain_db),
        clipped_share=touched, limiter_mean_db=float(report.mean_reduction_db),
        limiter_max_db=float(report.max_reduction_db),
        reference_lufs=None if reference is None
        else float(integrated_loudness(reference, reference_rate or sample_rate)[0]),
        eq_said=said)
