"""Clarity: the part of a mix the reference match cannot reach.

Matching works on the summed spectrum, so it can only ever move whole bands up and down.
Clarity is not in that sum. Two mixes with identical spectra sound like mud or like a
record depending on how the *parts* sit inside those bands, and no amount of master EQ
changes which instrument owns 2 kHz.

What actually separates them was measured rather than assumed, on a track held here with
separated stems for both a home mix and its commercial reference:

  - Masking is not the problem. The stems in the professional mix overlapped *more* than
    the home mix's - 0.616 against 0.406 mean spectral overlap. The usual advice about
    carving space so instruments do not collide had the sign backwards.

  - Congestion in one band is. The home mix had 3.0 stems' worth of energy competing in
    2-4 kHz where the reference had 1.3, and almost no structure left there: 3.3 dB of
    contrast against the reference's 8.3 dB. That band is where definition lives -
    consonants, pick attack, stick on skin - and everything was piled into it at once.

  - The top is empty. Above 4 kHz the home mix had 1.2 effective stems against the
    reference's 2.0. Nothing was contributing detail up there, which is the signature of
    DI'd and synthesised sources that were never in a room.

So the measures here are congestion and contrast, not overlap. Contrast and crest come
from summed audio, which matters: a reference is normally just a file and separating one
costs minutes. Congestion needs stems, and those we always have for the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Log-spaced bands. Wide enough that a single note does not define one, narrow enough
#: that "the midrange" cannot hide a problem living in half of it.
BANDS: tuple[tuple[float, float, str], ...] = (
    (60.0, 120.0, "low"),
    (120.0, 250.0, "low mid"),
    (250.0, 500.0, "body"),
    (500.0, 1000.0, "mid"),
    (1000.0, 2000.0, "upper mid"),
    (2000.0, 4000.0, "presence"),
    (4000.0, 8000.0, "brilliance"),
    (8000.0, 16000.0, "air"),
)

#: Below this share a stem is not really in the band and should not count as crowding it.
QUIET_SHARE = 0.02

#: Contrast this far below the reference reads as a smear rather than as tone.
CONTRAST_GAP_DB = 1.5

#: Crowding past this many effective stems is congestion worth acting on.
CROWDED = 2.0

#: Who keeps a band when several stems want it. Deliberately not loudness order: the
#: loudest thing in a congested band is usually the pad or the rhythm bed, which is
#: exactly what should move aside.
OWNERSHIP: dict[str, tuple[str, ...]] = {
    "low": ("bass", "drums"),
    "low mid": ("bass", "drums", "piano"),
    "body": ("vocals", "drums", "bass"),
    "mid": ("vocals", "guitar", "piano"),
    "upper mid": ("vocals", "guitar"),
    "presence": ("vocals", "drums"),
    "brilliance": ("drums", "vocals"),
    "air": ("drums", "vocals"),
}


@dataclass(frozen=True, slots=True)
class BandReading:
    """One band, as it stands in a mix."""

    name: str
    low_hz: float
    high_hz: float
    contrast_db: float
    crest_db: float
    crowding: float = 0.0
    #: Share of the band held by each stem, largest first.
    holders: tuple[tuple[str, float], ...] = ()


@dataclass
class ClarityReport:
    yours: list[BandReading] = field(default_factory=list)
    theirs: list[BandReading] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _spectrum(samples: np.ndarray, n_fft: int, sample_rate: int) -> np.ndarray:
    """Average power spectrum of a long middle section.

    The middle rather than the whole: an intro of one instrument and a silent outro both
    drag every measure here towards nonsense.
    """
    mono = np.asarray(samples, dtype=np.float64)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    start = len(mono) // 4
    segment = mono[start : start + sample_rate * 90]
    if len(segment) < n_fft * 2:
        segment = mono
    if len(segment) < n_fft:
        return np.zeros(n_fft // 2 + 1)

    hop = n_fft // 2
    window = np.hanning(n_fft)
    frames = [
        np.abs(np.fft.rfft(segment[i : i + n_fft] * window)) ** 2
        for i in range(0, len(segment) - n_fft, hop)
    ]
    return np.mean(frames, axis=0) if frames else np.zeros(n_fft // 2 + 1)


def contrast_db(
    spectrum: np.ndarray, freqs: np.ndarray, low: float, high: float
) -> float:
    """Spread between the loud and quiet parts of a band, in dB.

    A band holding a few strong partials with gaps between them measures high; a band
    where everything has filled in measures low. That is the difference between hearing
    instruments and hearing a wash, and unlike loudness it survives any master EQ - which
    is exactly why it is the thing to measure.

    Percentiles rather than max and min, because one bin of either is noise.
    """
    band = spectrum[(freqs >= low) & (freqs < high)]
    if band.size < 8:
        return 0.0
    db = 10 * np.log10(band + 1e-30)
    return float(np.percentile(db, 85) - np.percentile(db, 15))


def crest_db(samples: np.ndarray, sample_rate: int, low: float, high: float) -> float:
    """Peak above RMS within a band, in dB: how much the band moves.

    Short-window peaks, taken as a median, so one crash cymbal does not describe a whole
    track.
    """
    from scipy.signal import butter, sosfilt

    mono = np.asarray(samples, dtype=np.float64)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    start = len(mono) // 4
    segment = mono[start : start + sample_rate * 90]
    if len(segment) < sample_rate:
        segment = mono
    if len(segment) < sample_rate // 2:
        return 0.0

    high = min(high, sample_rate / 2 * 0.99)
    if low >= high:
        return 0.0

    sos = butter(4, [low, high], btype="band", fs=sample_rate, output="sos")
    filtered = sosfilt(sos, segment)
    rms = float(np.sqrt(np.mean(filtered**2)))
    if rms <= 1e-12:
        return 0.0

    window = max(1, sample_rate // 20)
    usable = len(filtered) // window * window
    if usable < window:
        return 0.0
    peaks = np.abs(filtered[:usable]).reshape(-1, window).max(axis=1)
    return float(20 * np.log10(np.median(peaks) / rms + 1e-30))


def read_mix(
    samples: np.ndarray,
    sample_rate: int,
    stems: dict[str, np.ndarray] | None = None,
    n_fft: int = 8192,
) -> list[BandReading]:
    """Measure every band of a mix, with crowding when the stems are available."""
    spectrum = _spectrum(samples, n_fft, sample_rate)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    stem_spectra = (
        {name: _spectrum(buf, n_fft, sample_rate) for name, buf in stems.items()}
        if stems
        else {}
    )

    readings = []
    for low, high, name in BANDS:
        crowding, holders = 0.0, ()
        if stem_spectra:
            selection = (freqs >= low) & (freqs < high)
            energy = {k: float(v[selection].sum()) for k, v in stem_spectra.items()}
            total = sum(energy.values()) + 1e-30
            shares = {
                k: v / total for k, v in energy.items() if v / total >= QUIET_SHARE
            }
            if shares:
                # Inverse Simpson index: how many stems are *effectively* in this band.
                # Two stems at half each reads 2.0; one dominant stem with scraps around
                # it reads near 1.0, which is what an uncontested band looks like.
                crowding = 1.0 / sum(s**2 for s in shares.values())
                holders = tuple(sorted(shares.items(), key=lambda kv: -kv[1]))

        readings.append(
            BandReading(
                name=name,
                low_hz=low,
                high_hz=high,
                contrast_db=contrast_db(spectrum, freqs, low, high),
                crest_db=crest_db(samples, sample_rate, low, high),
                crowding=crowding,
                holders=holders,
            )
        )
    return readings


#: Plain language for each band, and whether it takes a plural verb. "The upper mids is
#: thinner" is the sort of thing that makes a tool feel machine-written.
BAND_WORDS: dict[str, tuple[str, bool]] = {
    "low": ("the bottom", False),
    "low mid": ("the low mids", True),
    "body": ("the body of the mix", False),
    "mid": ("the midrange", False),
    "upper mid": ("the upper mids", True),
    "presence": ("the presence range", False),
    "brilliance": ("the top end", False),
    "air": ("the air", False),
}


def _band_word(name: str) -> str:
    """Plain language for a band, for someone who does not think in hertz."""
    return BAND_WORDS.get(name, (name, False))[0]


def _band_is(name: str) -> str:
    return "are" if BAND_WORDS.get(name, (name, False))[1] else "is"


def _holders_phrase(holders: tuple[tuple[str, float], ...], limit: int = 3) -> str:
    """"guitar, drums and other", from the stems actually holding a band."""
    names = [name for name, _ in holders[:limit]]
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def findings(
    yours: list[BandReading],
    theirs: list[BandReading],
) -> list[dict]:
    """Where this mix differs from the reference in ways EQ cannot reach.

    Deliberately advice rather than actions. Four automated fixes were built against
    these numbers and measured, and all four failed:

      - Carving the crowded band. Stepping the non-owners back by up to 3 dB moved
        crowding 3.02 to 2.94 and made contrast *worse*, 3.33 to 3.11 dB. Scaling one
        contributor down does not open gaps between the partials of the others.
      - Exciting the empty top. Even at a setting well into audible distortion, 4-8 kHz
        reached 1.34 effective stems against the reference's 1.95, and the air band did
        not move at all.
      - Compressing each stem. Presence crest went 10.68 to 10.52 dB at 4.5:1, because a
        broadband detector hears the stem's low mids and never sees a cymbal.
      - Compressing each stem per band, detecting inside the band. 10.68 to 10.62 dB at
        6:1.

    The last one is the informative failure. If in-band compression cannot move in-band
    crest, the number is not describing how compressed the band is - it is describing how
    *sparse* it is. A reference whose presence range is dense and sustained reads low;
    one where a few transients poke through a thin band reads high. That is a property of
    what was played and recorded, not of what was done to it afterwards.

    Which is why this returns findings and no dials. The work is in the arrangement:
    fewer things in the same range at once, different voicings or octaves, and sources
    with real top end. Telling someone plainly that three instruments are fighting over
    2-4 kHz is worth more than a plugin that pretends to fix it.
    """
    theirs_by_name = {band.name: band for band in theirs}
    out: list[dict] = []

    for band in yours:
        reference = theirs_by_name.get(band.name)
        if reference is None:
            continue

        gap = reference.contrast_db - band.contrast_db
        crowded = band.crowding >= CROWDED and band.holders
        flat = gap >= CONTRAST_GAP_DB

        if crowded and flat:
            owners = OWNERSHIP.get(band.name, ())
            present = [name for name, _ in band.holders]
            owner = next((o for o in owners if o in present), None)
            keeps = (
                f" In a mix like your reference {owner} would own this range."
                if owner
                else ""
            )
            out.append(
                {
                    "area": f"clarity:{band.name}",
                    "severity": "notable" if gap >= 3.0 else "slight",
                    "delta_db": round(float(gap), 2),
                    "headline": (
                        f"{_holders_phrase(band.holders).capitalize()} are all competing "
                        f"in {_band_word(band.name)}"
                    ),
                    "detail": (
                        f"{band.crowding:.1f} instruments' worth of energy share "
                        f"{band.low_hz:.0f}-{band.high_hz:.0f} Hz, and the range has "
                        f"{gap:.1f} dB less structure than your reference's - the "
                        f"partials have filled in the gaps between each other."
                        f"{keeps} No EQ fixes this, because every instrument here moves "
                        f"together when you move the band. It is an arrangement change: "
                        f"thin the parts, move one to another octave, or change a "
                        f"voicing."
                    ),
                    "clause": f"a congested {band.name} range",
                }
            )
        elif flat and band.crowding < CROWDED:
            out.append(
                {
                    "area": f"clarity:{band.name}",
                    "severity": "slight",
                    "delta_db": round(float(gap), 2),
                    "headline": (
                        f"{_band_word(band.name).capitalize()} "
                        f"{_band_is(band.name)} thinner than your reference's"
                    ),
                    "detail": (
                        f"{gap:.1f} dB less structure than your reference across "
                        f"{band.low_hz:.0f}-{band.high_hz:.0f} Hz, without anything "
                        f"crowding it. That usually means there is simply less happening "
                        f"here - a part, a double, or a source with more content in this "
                        f"range."
                    ),
                    "clause": f"a thin {band.name} range",
                }
            )

        # An unpopulated top is the signature of direct and synthesised sources, which
        # never pick up the detail a microphone in a room does.
        if band.name in ("brilliance", "air") and band.holders:
            short = reference.crowding - band.crowding
            if short >= 0.5:
                out.append(
                    {
                        "area": f"clarity:{band.name}-empty",
                        "severity": "slight",
                        "delta_db": round(float(short), 2),
                        "headline": f"Only {_holders_phrase(band.holders, 2)} reach into {_band_word(band.name)}",
                        "detail": (
                            f"{band.crowding:.1f} instruments are present above "
                            f"{band.low_hz:.0f} Hz where your reference has "
                            f"{reference.crowding:.1f}. Parts recorded directly or played "
                            f"from a synth patch carry very little up here, and a master "
                            f"EQ can only lift what is already there. Brightness comes "
                            f"from more sources having real content in this range."
                        ),
                        "clause": f"an underpopulated {band.name} range",
                    }
                )

    out.sort(key=lambda f: -abs(f["delta_db"]))
    return out


def compare(
    source: 'Path',
    reference: 'Path',
    source_stems: dict | None = None,
    reference_stems: dict | None = None,
) -> list[dict]:
    """Read both sides and say where this mix is less clear than its reference.

    Degrades rather than failing when the reference has not been separated: contrast and
    crest come from the summed file, so the congestion findings still work. Only the
    "nothing is up here" finding needs the reference's own stems, and it simply does not
    fire without them.

    Returns plain dicts rather than a report object, because the only consumer is JSON.
    """
    from app.services.mixdown.encode import read_audio

    def stems_of(paths):
        if not paths:
            return None
        out = {}
        for kind, path in paths.items():
            try:
                buffer = read_audio(path)
            except Exception:
                continue
            samples = np.asarray(buffer.samples, dtype=np.float64)
            # A stem the separator found nothing for is not evidence of anything.
            if samples.size and np.abs(samples).max() > 1e-4:
                out[getattr(kind, "value", str(kind))] = samples
        return out or None

    try:
        yours_audio = read_audio(source)
        theirs_audio = read_audio(reference)
    except Exception:
        return []

    yours = read_mix(yours_audio.samples, yours_audio.sample_rate, stems_of(source_stems))
    theirs = read_mix(
        theirs_audio.samples, theirs_audio.sample_rate, stems_of(reference_stems)
    )
    return findings(yours, theirs)
