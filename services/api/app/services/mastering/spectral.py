"""Reference mastering with numpy — the default engine.

Matches a target to a reference in two independent steps, tone then level, because
conflating them makes both impossible to reason about:

1. **Tone** — a clamped, smoothed spectral correction curve (see `dsp.py`).
2. **Level** — a single gain to put the result at the reference's integrated loudness,
   then a ceiling so it cannot clip.

Needs no ffmpeg and no `matchering`; numpy, scipy and soundfile are enough.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from app.services.mastering.base import LoudnessStats, MasteringReport
from app.services.mastering.dsp import (
    MatchSettings,
    apply_curve,
    apply_gain_db,
    average_spectrum,
    limit_with_report,
    matching_curve,
    peak_db,
    stereo_width,
    true_peak_db,
)
from app.services.mastering.loudness_meter import gain_to_lufs, gain_to_match, integrated_loudness
from app.services.mastering.polish import (
    Polish,
    PolishReport,
    add_air,
    add_bass,
    add_warmth,
    ceiling_headroom,
    headroom_for,
    crest_db,
    widen_above,
)
from app.services.mixdown.encode import read_audio, write_wav

log = logging.getLogger(__name__)

# Frequencies to report the correction at, so the UI can draw a curve people recognise.
REPORT_BANDS = (60, 120, 250, 500, 1000, 2000, 4000, 8000, 12000)


class SpectralMatchEngine:
    name = "spectral"

    def __init__(self, settings: MatchSettings | None = None, ceiling_db: float = -1.0) -> None:
        self.settings = settings or MatchSettings()
        self.ceiling_db = ceiling_db

    def available(self) -> bool:
        try:
            import numpy  # noqa: F401
            import soundfile  # noqa: F401
        except ImportError:
            return False
        return True

    def match(
        self,
        target: Path,
        reference: Path | None,
        out_path: Path,
        analysis: Path | None = None,
        polish: Polish | None = None,
        reference_profile=None,
    ) -> MasteringReport:
        """Match `target` to a reference, given either its audio or its measurements.

        `reference_profile` is a saved `ReferenceProfile` and stands in for the audio
        completely at this stage. Everything the whole-mix match reads from a reference is
        a measurement of it - an averaged spectrum, side-to-mid per band, integrated
        loudness and true peak - so a profile is not an approximation of the reference
        here, it is the same numbers arriving by a shorter route.

        Per-instrument matching is the exception and lives in `pipeline`: comparing your
        snare with theirs needs their snare, and stems are audio.
        """
        source = read_audio(target)
        ref = read_audio(reference) if reference is not None else None
        if ref is None and reference_profile is None:
            raise ValueError("matching needs either a reference file or a saved profile")

        # `analysis` is the same mix without the user's own faders. Deriving the tonal
        # correction from it keeps a fader from being read as a tonal deviation: raise
        # the vocal 3 dB and a curve measured on the fadered mix simply cuts that band
        # back down again. Level is still measured on what is actually exported, so the
        # master lands on the reference's loudness wherever the faders sit - and a
        # uniform gain leaves the fader's relative move intact.
        tone_source = read_audio(analysis) if analysis is not None else source

        if ref is not None and source.sample_rate != ref.sample_rate:
            log.info(
                "reference is %d Hz against the target's %d Hz; comparing spectra by "
                "frequency regardless",
                ref.sample_rate, source.sample_rate,
            )

        report = MasteringReport(backend=self.name)
        report.source = self._stats(source.samples, source.sample_rate)
        report.reference = (
            self._stats(ref.samples, ref.sample_rate)
            if ref is not None
            else LoudnessStats(
                integrated_lufs=reference_profile.lufs,
                true_peak_dbtp=reference_profile.true_peak_db,
                # A profile keeps no loudness range: nothing in the match reads it, and
                # storing a number that is never used invites someone to trust it.
                loudness_range_lu=0.0,
            )
        )

        # --- tone -----------------------------------------------------------
        target_spectrum = average_spectrum(
            tone_source.samples, self.settings.n_fft, self.settings.hop
        )
        ref_spectrum = (
            average_spectrum(ref.samples, self.settings.n_fft, self.settings.hop)
            if ref is not None
            else reference_profile.spectrum(self.settings.n_fft, source.sample_rate)
        )
        curve = matching_curve(
            target_spectrum, ref_spectrum, source.sample_rate, self.settings
        )
        processed = apply_curve(source.samples, curve, self.settings.n_fft, self.settings.hop)
        report.eq_curve_db = self._describe_curve(curve, source.sample_rate)

        # --- finishing ------------------------------------------------------
        #
        # Before the level stage, not after: widening and an air lift both add peak
        # energy, and doing them after the limiter would push the master back over its
        # ceiling. Doing them before means the limiter sees what is actually being
        # exported.
        polish = polish or Polish()
        finish = PolishReport(
            air_db=polish.air_db,
            warmth_db=polish.warmth_db,
            bass_db=polish.bass_db,
            width_factor=polish.width,
        )

        # Cleanup first: there is no point shaping, widening or limiting rumble that is
        # about to be thrown away, and removing it frees headroom for everything after.
        if polish.subsonic_hz:
            from app.services.mastering.lowend import LowEndReport, remove_subsonics

            low_report = LowEndReport()
            processed = remove_subsonics(
                processed, source.sample_rate, polish.subsonic_hz, low_report
            )
            finish.subsonic_hz = low_report.subsonic_hz
            finish.notes.extend(low_report.notes)

        if polish.bass_db:
            processed = add_bass(
                processed, source.sample_rate, polish.bass_db, polish.bass_hz
            )
            finish.notes.append(
                f"{polish.bass_db:+.1f} dB shelf below {polish.bass_hz:.0f} Hz"
            )
        if polish.warmth_db:
            processed = add_warmth(
                processed, source.sample_rate, polish.warmth_db, polish.warmth_hz
            )
            finish.notes.append(
                f"{polish.warmth_db:+.1f} dB shelf below {polish.warmth_hz:.0f} Hz"
            )
        if polish.air_db:
            processed = add_air(processed, source.sample_rate, polish.air_db, polish.air_hz)
            finish.notes.append(
                f"{polish.air_db:+.1f} dB shelf above {polish.air_hz / 1000:.0f} kHz"
            )
        if polish.sparkle_db:
            from app.services.mastering.exciter import SparkleReport, add_sparkle

            sparkle_report = SparkleReport()
            processed = add_sparkle(
                processed,
                source.sample_rate,
                polish.sparkle_db,
                polish.sparkle_from_hz,
                sparkle_report,
            )
            finish.sparkle_db = sparkle_report.sparkle_db
            finish.sparkle_from_hz = sparkle_report.from_hz
            finish.air_added_db = sparkle_report.air_added_db
            finish.notes.extend(sparkle_report.notes)

        # Matching the reference's image comes first, so the manual dial rides on top of
        # a mix that is already the right shape rather than fighting it.
        if polish.width_profile > 0.0:
            from app.services.mastering.width import match_to, mono_loss_db, width_profile

            finish.width_before = round(stereo_width(processed), 3)
            # Nine numbers, whether they come from the reference's audio or from a saved
            # profile that measured it once: eight band widths and its mono loss.
            their_width = (
                width_profile(ref.samples, source.sample_rate)
                if ref is not None
                else reference_profile.width
            )
            their_mono_loss = (
                mono_loss_db(ref.samples) if ref is not None
                else reference_profile.mono_loss_db
            )
            processed, width_report = match_to(
                processed, source.sample_rate, their_width, their_mono_loss,
                polish.width_profile,
            )
            finish.width_after = round(stereo_width(processed), 3)
            finish.width_bands = width_report.factors
            finish.mono_loss_db = width_report.mono_loss_db
            moved = {
                name: factor
                for name, factor in width_report.factors.items()
                if abs(factor - 1.0) >= 0.1
            }
            if moved:
                finish.notes.append(
                    "matched the reference's stereo image: "
                    + ", ".join(f"{n} x{f:.2f}" for n, f in moved.items())
                )
            finish.notes.extend(width_report.notes)

        if polish.width != 1.0:
            finish.width_before = finish.width_before or round(stereo_width(processed), 3)
            processed = widen_above(
                processed, source.sample_rate, polish.width, polish.width_floor_hz
            )
            finish.width_after = round(stereo_width(processed), 3)
            finish.notes.append(
                f"widened x{polish.width:.2f} above "
                f"{polish.width_floor_hz:.0f} Hz, low end left centred"
            )

        # Saturation before the spatial moves: it rounds transients, and a tail built
        # from an already-rounded signal sits in the mix rather than on top of it.
        if polish.saturation_db:
            from app.services.mastering.saturation import (
                SaturationReport,
                add_saturation,
            )

            saturation_report = SaturationReport()
            processed = add_saturation(
                processed, source.sample_rate, polish.saturation_db, saturation_report
            )
            finish.saturation_db = saturation_report.saturation_db
            finish.peak_softened_db = saturation_report.peak_softened_db
            finish.notes.extend(saturation_report.notes)

        if polish.ambience_mix or polish.parallel_mix or polish.side_air_db:
            from app.services.mastering.depth import (
                DepthReport,
                add_ambience,
                add_side_air,
                parallel_compress,
            )

            depth_report = DepthReport()
            if polish.ambience_mix:
                processed = add_ambience(
                    processed, source.sample_rate, polish.ambience_mix, report=depth_report
                )
            if polish.parallel_mix:
                processed = parallel_compress(
                    processed, source.sample_rate, polish.parallel_mix, report=depth_report
                )
            if polish.side_air_db:
                processed = add_side_air(
                    processed, source.sample_rate, polish.side_air_db, report=depth_report
                )
            finish.ambience_mix = depth_report.ambience_mix
            finish.parallel_mix = depth_report.parallel_mix
            finish.side_air_db = depth_report.side_air_db
            finish.cymbal_change_db = depth_report.cymbal_change_db
            finish.notes.extend(depth_report.notes)

        # Centring the bass goes after every width move, so nothing widens it again
        # afterwards, and before the limiter, which then sees the tighter signal.
        if polish.centre_bass_hz:
            from app.services.mastering.lowend import LowEndReport, centre_bass

            centre_report = LowEndReport()
            processed = centre_bass(
                processed,
                source.sample_rate,
                polish.centre_bass_hz,
                polish.centre_bass_amount,
                centre_report,
            )
            finish.centred_below_hz = centre_report.centred_below_hz
            finish.bass_width_before = centre_report.width_before
            finish.bass_width_after = centre_report.width_after
            finish.notes.extend(centre_report.notes)

        # --- level ----------------------------------------------------------
        gain, measurements = (
            gain_to_match(processed, ref.samples, source.sample_rate)
            if ref is not None
            else gain_to_lufs(processed, source.sample_rate, reference_profile.lufs)
        )

        # Aim at the reference's loudness relative to its own peak. Chasing the raw
        # LUFS number from a lower ceiling just means driving harder into the limiter,
        # and the difference comes out as gain reduction rather than as loudness.
        if polish.protect_dynamics:
            guard, reference_crest = (
                ceiling_headroom(ref.samples, source.sample_rate, self.ceiling_db)
                if ref is not None
                else headroom_for(
                    reference_profile.peak_db, reference_profile.lufs, self.ceiling_db
                )
            )
            finish.ceiling_headroom_db = round(guard, 2)
            finish.reference_crest_db = round(reference_crest, 2)
            if guard > 0.1:
                gain -= guard
                finish.notes.append(
                    f"held {guard:.1f} dB under the reference, which peaks above our "
                    f"ceiling - this keeps its {reference_crest:.1f} dB of dynamic range"
                )
        if polish.headroom_db:
            gain -= polish.headroom_db
            finish.headroom_db = round(polish.headroom_db, 2)
            finish.notes.append(f"{polish.headroom_db:.1f} dB of extra headroom")

        processed = apply_gain_db(processed, gain)
        report.gain_applied_db = round(gain, 2)
        report.polish = finish

        if measurements.get("clamped"):
            report.warnings.append(
                f"Wanted {measurements['wanted_db']:+.1f} dB to match the reference's "
                "loudness but capped the move — these two tracks are a long way apart."
            )
        if measurements.get("backend") == "rms":
            report.warnings.append(
                "Loudness matched by RMS rather than LUFS; install pyloudnorm for "
                "EBU R128 metering."
            )

        # --- ceiling --------------------------------------------------------
        before_limit = peak_db(processed)
        processed, limiter = limit_with_report(processed, source.sample_rate, self.ceiling_db)
        report.limiter = limiter
        finish.result_crest_db = round(crest_db(processed, source.sample_rate), 2)
        if before_limit > self.ceiling_db + 3:
            report.warnings.append(
                f"Peaks reached {before_limit:.1f} dBFS before limiting; the limiter is "
                f"working hard to hold {self.ceiling_db:.0f} dBFS. Lower the match "
                "strength if it sounds squashed."
            )

        write_wav(out_path, processed, source.sample_rate)
        report.result = self._stats(processed, source.sample_rate)
        return report

    def _stats(self, samples: np.ndarray, sample_rate: int) -> LoudnessStats:
        loudness, _ = integrated_loudness(samples, sample_rate)
        return LoudnessStats(
            integrated_lufs=round(float(loudness), 2) if np.isfinite(loudness) else -70.0,
            true_peak_dbtp=round(true_peak_db(samples, sample_rate), 2),
            loudness_range_lu=0.0,  # LRA needs gated short-term blocks; not measured yet
        )

    def _describe_curve(self, curve: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
        """Sample the correction at recognisable frequencies, in dB."""
        freqs = np.fft.rfftfreq((curve.size - 1) * 2, d=1.0 / sample_rate)
        out: list[tuple[float, float]] = []
        for band in REPORT_BANDS:
            if band >= sample_rate / 2:
                continue
            index = int(np.searchsorted(freqs, band))
            index = min(index, curve.size - 1)
            out.append((float(band), round(float(20.0 * np.log10(curve[index])), 2)))
        return out
