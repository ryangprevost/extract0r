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
    limit,
    matching_curve,
    peak_db,
)
from app.services.mastering.loudness_meter import gain_to_match, integrated_loudness
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

    def match(self, target: Path, reference: Path, out_path: Path) -> MasteringReport:
        source = read_audio(target)
        ref = read_audio(reference)

        if source.sample_rate != ref.sample_rate:
            log.info(
                "reference is %d Hz against the target's %d Hz; comparing spectra by "
                "frequency regardless",
                ref.sample_rate, source.sample_rate,
            )

        report = MasteringReport(backend=self.name)
        report.source = self._stats(source.samples, source.sample_rate)
        report.reference = self._stats(ref.samples, ref.sample_rate)

        # --- tone -----------------------------------------------------------
        target_spectrum = average_spectrum(source.samples, self.settings.n_fft, self.settings.hop)
        ref_spectrum = average_spectrum(ref.samples, self.settings.n_fft, self.settings.hop)
        curve = matching_curve(
            target_spectrum, ref_spectrum, source.sample_rate, self.settings
        )
        processed = apply_curve(source.samples, curve, self.settings.n_fft, self.settings.hop)
        report.eq_curve_db = self._describe_curve(curve, source.sample_rate)

        # --- level ----------------------------------------------------------
        gain, measurements = gain_to_match(processed, ref.samples, source.sample_rate)
        processed = apply_gain_db(processed, gain)
        report.gain_applied_db = round(gain, 2)

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
        processed = limit(processed, source.sample_rate, self.ceiling_db)
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
            true_peak_dbtp=round(peak_db(samples), 2),
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
