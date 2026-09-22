"""Finding a reference in music you already own.

The obvious version of this feature reads a Spotify link and suggests similar tracks.
It cannot be built. Spotify withdrew ``/audio-features``, ``/audio-analysis``,
``/recommendations`` and ``/related-artists`` for any application created after
27 November 2024 - deliberately, to stop the data being used to train models - and
offered no replacement. A new integration gets titles, artists and popularity, none of
which says anything about how a record was mastered. Nor could it: a reference is only
useful because its *audio* can be measured, and a metadata API never had the audio.

Measuring a local library does work, and works better. The files are already on disk,
already owned, and can be compared on the things that actually matter - tonal balance,
loudness, stereo image - rather than on a genre tag.

What makes a good reference is not the closest match. A record that already sounds like
the mix teaches it nothing. The useful reference is close enough in *arrangement* that
its tonal balance is a sensible target, while being further along in the ways a
commercial master differs: louder, wider up top, tighter at the bottom. So candidates
are ranked on similarity of spectral shape and reported with the distance in every other
dimension, which is what makes one a target rather than a mirror.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

#: Audio we can read. Matches the upload gate; m4a included since PyAV arrived.
SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif"}

#: Seconds sampled from the middle of each candidate. Long enough to average over a
#: chorus and a verse, short enough that a library scan finishes: the whole cost here is
#: decoding, and decoding all of a thousand tracks to measure their tone is wasteful.
WINDOW_S = 60.0

#: Bands for the tonal fingerprint, matching the rest of the mastering code.
BANDS: tuple[tuple[float, float, str], ...] = (
    (20.0, 60.0, "sub"),
    (60.0, 120.0, "low"),
    (120.0, 250.0, "low mid"),
    (250.0, 500.0, "body"),
    (500.0, 1000.0, "mid"),
    (1000.0, 2000.0, "upper mid"),
    (2000.0, 4000.0, "presence"),
    (4000.0, 8000.0, "brilliance"),
    (8000.0, 16000.0, "air"),
)

#: A track shorter than this is an interlude, a skit or a sample, not a reference.
MIN_SECONDS = 60.0

CACHE_NAME = ".extract0r-library.json"
CACHE_VERSION = 2


@dataclass
class Profile:
    """How one recording is mastered, in numbers that survive being compared."""

    path: str
    name: str
    seconds: float
    lufs: float
    peak_db: float
    #: Each band's share of the whole, in dB. Level drops out, so a quiet file and a loud
    #: one with the same balance look identical - which is the point.
    bands: dict[str, float] = field(default_factory=dict)
    #: Side-to-mid per band, from `mastering.width`.
    width: dict[str, float] = field(default_factory=dict)
    size: int = 0
    mtime: float = 0.0


#: Below this side-to-mid across the board, a file has no stereo image at all.
MONO_WIDTH = 0.02


@dataclass
class Candidate:
    profile: Profile
    #: How close the tonal balance is. Lower is closer.
    tonal_distance_db: float
    #: Where it goes further than the source, which is what makes it a target.
    louder_by_db: float
    wider_above_1k_by_db: float
    tighter_below_250_by_db: float
    #: A mono file has no image to compare, so the width figures above are 0 rather than
    #: the -170 dB that comparing against silence produces.
    mono: bool = False
    why: str = ""


def _read_window(path: Path) -> tuple[np.ndarray, int] | None:
    """Decode the middle `WINDOW_S` of a file, seeking rather than reading it all."""
    try:
        import soundfile as sf

        info = sf.info(str(path))
        if info.duration < MIN_SECONDS:
            return None
        start = int(max(0.0, (info.duration - WINDOW_S) / 2) * info.samplerate)
        frames = int(min(WINDOW_S, info.duration) * info.samplerate)
        samples, rate = sf.read(
            str(path), start=start, frames=frames, dtype="float64", always_2d=True
        )
        return samples, int(rate)
    except Exception:
        # libsndfile cannot open m4a, and seeking is not worth a second code path for
        # the handful of formats that land here.
        from app.services.audio.probe import decode_with_av

        decoded = decode_with_av(path)
        if decoded is None:
            return None
        samples, rate = decoded
        samples = np.asarray(samples, dtype=np.float64)
        if len(samples) < MIN_SECONDS * rate:
            return None
        start = max(0, (len(samples) - int(WINDOW_S * rate)) // 2)
        return samples[start : start + int(WINDOW_S * rate)], int(rate)


def profile_of(path: Path) -> Profile | None:
    """Measure one file. Returns None for anything too short or unreadable."""
    from app.services.mastering.loudness_meter import integrated_loudness
    from app.services.mastering.width import width_profile

    window = _read_window(path)
    if window is None:
        return None
    samples, rate = window
    if samples.ndim == 1:
        samples = np.stack([samples, samples], axis=1)

    n_fft = 8192
    mono = samples.mean(axis=1)
    if len(mono) < n_fft * 2:
        return None
    hop = n_fft // 2
    window_fn = np.hanning(n_fft)
    spectrum = np.mean(
        [
            np.abs(np.fft.rfft(mono[i : i + n_fft] * window_fn)) ** 2
            for i in range(0, len(mono) - n_fft, hop)
        ],
        axis=0,
    )
    freqs = np.fft.rfftfreq(n_fft, 1.0 / rate)
    total = spectrum.sum() + 1e-30
    bands = {
        name: float(10 * np.log10(spectrum[(freqs >= lo) & (freqs < hi)].sum() / total + 1e-30))
        for lo, hi, name in BANDS
    }

    loudness, _ = integrated_loudness(samples, rate)
    stat = path.stat()
    return Profile(
        path=str(path),
        name=path.stem,
        seconds=round(len(samples) / rate, 1),
        lufs=round(float(loudness), 2) if np.isfinite(loudness) else -99.0,
        peak_db=round(float(20 * np.log10(np.abs(samples).max() + 1e-12)), 2),
        bands={k: round(v, 2) for k, v in bands.items()},
        width={k: round(v, 3) for k, v in width_profile(samples, rate).items()},
        size=stat.st_size,
        mtime=stat.st_mtime,
    )


def _cache_path(root: Path) -> Path:
    return root / CACHE_NAME


def load_cache(root: Path) -> dict[str, Profile]:
    path = _cache_path(root)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != CACHE_VERSION:
            return {}
        return {k: Profile(**v) for k, v in raw.get("profiles", {}).items()}
    except Exception:
        log.debug("could not read the library cache; rebuilding", exc_info=True)
        return {}


def save_cache(root: Path, profiles: dict[str, Profile]) -> None:
    try:
        _cache_path(root).write_text(
            json.dumps(
                {"version": CACHE_VERSION, "profiles": {k: asdict(v) for k, v in profiles.items()}},
                indent=1,
            ),
            encoding="utf-8",
        )
    except Exception:
        log.debug("could not write the library cache", exc_info=True)


def _key(path: Path) -> str:
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]


def scan(
    root: Path,
    limit: int | None = None,
    progress=None,
) -> dict[str, Profile]:
    """Measure every track under `root`, reusing anything already measured.

    Cached against size and modification time rather than content: hashing a library to
    decide whether to re-read it costs most of what re-reading it would.
    """
    profiles = load_cache(root)
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in SUFFIXES)
    if limit:
        files = files[:limit]

    fresh = 0
    for index, path in enumerate(files):
        key = _key(path)
        existing = profiles.get(key)
        try:
            stat = path.stat()
        except OSError:
            continue
        if existing and existing.size == stat.st_size and existing.mtime == stat.st_mtime:
            continue
        if progress:
            progress(index / max(len(files), 1), f"measuring {path.name}")
        try:
            measured = profile_of(path)
        except Exception:
            log.debug("could not profile %s", path, exc_info=True)
            continue
        if measured is not None:
            profiles[key] = measured
            fresh += 1

    if fresh:
        save_cache(root, profiles)
    return profiles


def _mean(values: dict[str, float], names: tuple[str, ...]) -> float:
    picked = [values[n] for n in names if n in values]
    return float(np.mean(picked)) if picked else 0.0


#: Below this tonal distance, a candidate that is no louder, wider or tighter than the
#: source is the same recording wearing a different filename - or one of this tool's own
#: exports of it. Both are true matches and neither is a reference.
MIRROR_DISTANCE_DB = 3.0


def rank(
    source: Profile,
    profiles: dict[str, Profile],
    top: int = 8,
) -> list[Candidate]:
    """Order a library by how useful each track would be as a reference for `source`.

    Ranked on tonal distance alone, because that is the axis on which a reference has to
    be *appropriate*: matching a mix to a record with a different balance of instruments
    moves it towards the wrong shape however good that record is. The other differences
    are reported rather than scored - they are what the match will actually change, so a
    candidate that is close in tone and far in loudness and width is the most useful of
    all, and scoring it down for that would be backwards.
    """
    from app.services.mastering.width import BAND_NAMES

    wide = ("mid", "upper mid", "presence", "top")
    tight = ("sub", "low", "low mid")

    out: list[Candidate] = []
    for candidate in profiles.values():
        # The same file, by path. Catches the common case and not the interesting one:
        # what a user uploads is a copy in the track's own storage, so their own song
        # sitting in the library is a different path holding identical audio. See the
        # mirror check further down, which is the one that catches that.
        if Path(candidate.path) == Path(source.path):
            continue
        shared = [n for _, _, n in BANDS if n in source.bands and n in candidate.bands]
        if not shared:
            continue
        distance = float(
            np.sqrt(np.mean([(source.bands[n] - candidate.bands[n]) ** 2 for n in shared]))
        )

        def width_db(profile: Profile, names: tuple[str, ...]) -> float:
            picked = [profile.width[n] for n in names if n in profile.width]
            if not picked:
                return 0.0
            return float(20 * np.log10(np.mean(picked) + 1e-9))

        def is_mono(profile: Profile) -> bool:
            values = list(profile.width.values())
            return bool(values) and max(values) < MONO_WIDTH

        louder = round(candidate.lufs - source.lufs, 2)
        # Comparing a stereo image against a file that has none produces about -170 dB,
        # which is arithmetically correct and completely useless to read.
        mono = is_mono(candidate) or is_mono(source)
        wider = 0.0 if mono else round(width_db(candidate, wide) - width_db(source, wide), 2)
        tighter = (
            0.0 if mono else round(width_db(source, tight) - width_db(candidate, tight), 2)
        )

        notes = []
        if louder >= 1.0:
            notes.append(f"{louder:.1f} dB louder")
        if wider >= 1.0:
            notes.append(f"{wider:.1f} dB wider above 1 kHz")
        if tighter >= 1.0:
            notes.append(f"{tighter:.1f} dB tighter at the bottom")
        if is_mono(candidate):
            notes.append("but it is mono, so it can teach nothing about width")

        # A mirror: close in tone and no further along on any axis the match can act on.
        #
        # This is what "a record that already sounds like the mix teaches it nothing"
        # means in code, and it is not hypothetical. Pointed at a folder containing the
        # song being mastered and several of extract0r's own exports of it, the top four
        # suggestions were the song itself and three of its own masters - the first at
        # "within 0.0 dB of your tonal balance", which is true and useless.
        #
        # `notes` is empty exactly when the candidate is not meaningfully louder, wider
        # or tighter, so it is already the test for "nothing to learn here".
        if not notes and distance < MIRROR_DISTANCE_DB:
            continue

        why = (
            f"within {distance:.1f} dB of your tonal balance"
            + (", and " + ", ".join(notes) if notes else ", and mastered much like it")
        )

        out.append(
            Candidate(
                profile=candidate,
                tonal_distance_db=round(distance, 2),
                louder_by_db=louder,
                wider_above_1k_by_db=wider,
                tighter_below_250_by_db=tighter,
                mono=is_mono(candidate),
                why=why,
            )
        )

    # Stereo first. A mono file may match the tone perfectly and still be the wrong
    # reference, because half of what a master does is place things across the image and
    # a mono candidate has no opinion about that to copy.
    out.sort(key=lambda c: (c.mono, c.tonal_distance_db))
    return out[:top]
