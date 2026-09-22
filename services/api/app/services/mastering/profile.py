"""A reference, kept as measurements instead of audio.

Everything the whole-mix match does with a reference is a *measurement* of it. Five uses,
and not one of them needs the waveform: the tonal curve wants an averaged spectrum, the
width match wants side-to-mid per band, the level stage wants integrated loudness, and the
headroom guard wants loudness against true peak. So a reference can be reduced to those
numbers once and reused for ever, and the audio never has to be kept or handled again.

Which makes this the honest version of "use that record as a reference". A streaming link
cannot be had on terms this tool accepts, and a converter in the middle changes who did the
ripping rather than what the bytes are. But measurements of a recording are facts about it
- its loudness, its tonal balance, how wide it is - in the same family as its tempo or its
key. Nothing here can be played, and nothing here can be turned back into music: ninety-six
magnitudes on a log frequency axis with every phase discarded is not a lossy copy of a song,
it is a description of one.

**What a profile cannot do** is per-instrument matching. That needs the reference separated
into stems, and stems are audio. A profile covers the whole-mix stage and says so.

Storage lives outside `storage_dir` deliberately. The retention sweep deletes every
directory it finds under that root once it is old enough, so a profile folder kept there
would quietly disappear after a day - which is the opposite of the point.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.services.mastering.dsp import (
    DEFAULT_HOP,
    DEFAULT_N_FFT,
    MatchSettings,
    average_spectrum,
    peak_db,
    smooth_log_frequency,
    true_peak_db,
)
from app.services.mastering.loudness_meter import integrated_loudness
from app.services.mastering.dsp import stereo_width
from app.services.mastering.width import mono_loss_db, width_profile

log = logging.getLogger(__name__)

#: How many points of the spectrum to keep, spaced evenly in log frequency.
#:
#: The matcher smooths to a third of an octave before it compares anything, so what is
#: stored is the *smoothed* curve - sampling the raw spectrum this sparsely aliases, and
#: measurably: at 48 points the rebuilt curve was 2.5 dB out in places, worse than at 24,
#: because the error is noise rather than resolution. Smoothed first, 96 points rebuild a
#: matching curve within 0.64 dB at worst and 0.17 dB RMS of the one taken from the audio,
#: and going further stops helping - the remainder is the smoothing, not the sampling.
CURVE_POINTS = 96

#: The band the curve is stored over. Below 20 Hz is rumble and above 20 kHz is nothing.
CURVE_LOW_HZ = 20.0
CURVE_HIGH_HZ = 20000.0

#: Bumped when the shape changes in a way that makes old files unreadable, so a profile
#: saved by an older build is refused with a sentence rather than misread in silence.
FORMAT_VERSION = 1

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _.-]+")


@dataclass(slots=True)
class ReferenceProfile:
    """What one recording teaches, in the terms the match actually uses."""

    name: str
    #: What it was captured from, for the person reading a list of these later.
    captured_from: str = ""
    captured_at: str = ""
    seconds: float = 0.0
    sample_rate: int = 44100

    #: Integrated loudness, and both peaks. Sample peak as well as true peak because
    #: the headroom guard measures the first and the report shows the second, and storing
    #: only one would silently change where a master lands.
    lufs: float = 0.0
    true_peak_db: float = 0.0
    peak_db: float = 0.0

    #: The smoothed spectrum, in dB, at `curve_hz`. Magnitudes only - no phase, which is
    #: what makes this a description rather than a recording.
    curve_hz: list[float] = field(default_factory=list)
    curve_db: list[float] = field(default_factory=list)

    #: Side-to-mid per width band, and what the reference gives up in mono.
    width: dict[str, float] = field(default_factory=dict)
    mono_loss_db: float = 0.0
    #: Overall stereo width. Per-band covers the match; the advice engine compares one
    #: number, and deriving it from the bands afterwards would not give the same answer.
    stereo_width: float = 0.0

    version: int = FORMAT_VERSION

    def spectrum(self, n_fft: int = DEFAULT_N_FFT, sample_rate: int | None = None) -> np.ndarray:
        """Rebuild an rFFT-shaped magnitude array the matcher can consume.

        Interpolated in log frequency, because that is the axis the curve was sampled on
        and the axis the matcher smooths over. Held flat outside the stored range rather
        than extrapolated: a curve that runs off towards infinity below 20 Hz would put
        the matcher's biggest correction where there is no music.
        """
        rate = sample_rate or self.sample_rate
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / rate)
        if not self.curve_hz:
            return np.ones_like(freqs)

        hz = np.asarray(self.curve_hz, dtype=np.float64)
        db = np.asarray(self.curve_db, dtype=np.float64)
        with np.errstate(divide="ignore"):
            rebuilt = np.interp(
                np.log2(np.maximum(freqs, 1e-6)), np.log2(hz), db,
                left=float(db[0]), right=float(db[-1]),
            )
        return 10.0 ** (rebuilt / 20.0)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "ReferenceProfile":
        version = int(data.get("version", 0))
        if version > FORMAT_VERSION:
            raise ValueError(
                f"This profile was written by a newer version of extract0r "
                f"(format {version}, this build reads {FORMAT_VERSION})."
            )
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def capture(
    samples: np.ndarray,
    sample_rate: int,
    name: str,
    captured_from: str = "",
    settings: MatchSettings | None = None,
) -> ReferenceProfile:
    """Measure a recording once, so it never has to be measured - or kept - again."""
    settings = settings or MatchSettings()
    audio = np.asarray(samples, dtype=np.float64)

    spectrum = average_spectrum(audio, settings.n_fft, settings.hop)
    smoothed = smooth_log_frequency(spectrum, sample_rate, settings.smoothing_octaves)
    freqs = np.fft.rfftfreq(settings.n_fft, d=1.0 / sample_rate)

    top = min(CURVE_HIGH_HZ, sample_rate / 2 * 0.99)
    hz = np.geomspace(CURVE_LOW_HZ, top, CURVE_POINTS)
    with np.errstate(divide="ignore"):
        db = np.interp(hz, freqs, 20.0 * np.log10(np.maximum(smoothed, 1e-20)))

    loudness, _ = integrated_loudness(audio, sample_rate)

    return ReferenceProfile(
        name=name,
        captured_from=captured_from,
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seconds=round(len(audio) / sample_rate, 2),
        sample_rate=sample_rate,
        lufs=round(float(loudness), 2) if np.isfinite(loudness) else -120.0,
        true_peak_db=round(true_peak_db(audio, sample_rate), 2),
        peak_db=round(float(peak_db(audio)), 2),
        curve_hz=[round(float(v), 3) for v in hz],
        curve_db=[round(float(v), 3) for v in db],
        width={k: round(float(v), 4) for k, v in width_profile(audio, sample_rate).items()},
        mono_loss_db=round(mono_loss_db(audio), 2),
        stereo_width=round(float(stereo_width(audio)), 3),
    )


# --- on disk ---------------------------------------------------------------------------


def safe_filename(name: str) -> str:
    """A filename from a user-supplied profile name.

    The name comes from a text box, so it is not allowed to decide where the file lands.
    Everything outside a small set is replaced rather than escaped, which also keeps the
    names readable in a folder listing.
    """
    cleaned = _SAFE_NAME.sub("-", name).strip(" .-")
    return (cleaned or "profile")[:80]


def save(profile: ReferenceProfile, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_filename(profile.name)}.json"
    path.write_text(profile.to_json(), encoding="utf-8")
    return path


def load(path: Path) -> ReferenceProfile:
    return ReferenceProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def listing(directory: Path) -> list[ReferenceProfile]:
    """Every readable profile in a folder, newest first.

    An unreadable one is skipped rather than raised on: a single corrupt file should cost
    its own row, not the whole list.
    """
    if not directory.is_dir():
        return []
    out: list[ReferenceProfile] = []
    for path in directory.glob("*.json"):
        try:
            out.append(load(path))
        except Exception:
            log.info("skipping unreadable profile %s", path.name, exc_info=True)
    out.sort(key=lambda p: p.captured_at, reverse=True)
    return out


def find(directory: Path, name: str) -> ReferenceProfile | None:
    path = directory / f"{safe_filename(name)}.json"
    if not path.is_file():
        return None
    try:
        return load(path)
    except Exception:
        log.info("could not read profile %s", path.name, exc_info=True)
        return None
