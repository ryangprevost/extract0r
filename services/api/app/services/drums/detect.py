"""Finding the individual drums inside a drum stem.

Separation gives one drums track; replacing a snare needs to know which moments *are* the
snare. That is a different question from "where are the onsets", and the difference is
what the first attempt here got wrong.

**One hit can be several drums.** A kick and a hi-hat land together on the downbeat of
almost every rock beat. Picking the single loudest band per onset means the hat wins and
the kick is never seen: against a constructed beat with 32 kicks and 32 snares, all of
them under hats, the old classifier found none of either and still reported itself 100%
correct, because the hat it named was genuinely there. Each drum is now tested
independently and an onset can be labelled with all of them.

**A band's total energy is not a fair comparison.** The old bands were 20-120 Hz for kick
and 5-14 kHz for hi-hat: ninety times wider. Summed raw, the wide band wins whatever is
playing, which is why a real drum stem came back as 615 hi-hats, 205 kicks and no snares
at all.

**What identifies a drum is the rise, not the level.** Cymbals ring through everything, so
the high band is never quiet; what marks a hat is that the high band *jumps*. Measuring the
increase in each band at the onset, against the moment before it, finds a kick underneath a
ringing crash - which comparing levels cannot do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: The bands each drum announces itself in. Deliberately overlapping: a snare is not one
#: band, it is body *and* rattle together, and that pairing is what separates it from a
#: tom below it and a hat above it.
KICK_HZ = (30.0, 120.0)
SNARE_BODY_HZ = (160.0, 450.0)
SNARE_RATTLE_HZ = (1500.0, 4500.0)
HIHAT_HZ = (7500.0, 15000.0)

#: How far a band has to jump, in dB over the moment before, to count as a hit.
RISE_DB = 4.5

#: A snare's rattle is most of its energy, so it has to be there; the body can be buried
#: under a bass note and is allowed to be weaker.
SNARE_BODY_RISE_DB = 2.5

#: How far below a band's own loudest moments a hit may sit and still count.
#:
#: A rise on its own is not enough. In a band that is essentially silent - the low end
#: between kicks sits near the noise floor - a few dB of random variation clears any rise
#: threshold, and a hi-hat then reads as a kick. Against a constructed beat that was 45%
#: of kick claims and 68% of snare claims wrong. Requiring the band to be genuinely loud
#: at the same time is what separates a drum from a fluctuation.
PRESENCE_DB = 22.0

#: Window either side of an onset used to measure the jump.
BEFORE_MS = 30.0
AFTER_MS = 25.0

#: Two onsets closer than this are the same hit found twice.
MIN_SPACING_S = 0.045


@dataclass(slots=True)
class Hit:
    """One drum stroke: when it happened, what it was, and how hard."""

    time_s: float
    kinds: list[str] = field(default_factory=list)
    #: Peak sample value around the onset, for matching a replacement's level.
    strength: float = 0.0
    #: Rise in dB per drum, so a caller can favour the confident ones.
    rises: dict[str, float] = field(default_factory=dict)


def _band_envelope(spectrum, freqs, low: float, high: float) -> np.ndarray:
    """Energy over time inside one band, as dB."""
    inside = (freqs >= low) & (freqs < high)
    if not inside.any():
        return np.zeros(spectrum.shape[1])
    energy = (spectrum[inside, :] ** 2).sum(axis=0)
    return 10.0 * np.log10(np.maximum(energy, 1e-12))


def find_hits(
    samples: np.ndarray,
    sample_rate: int,
    hop: int = 256,
    n_fft: int = 1024,
) -> list[Hit]:
    """Every drum stroke in a drums stem, each labelled with what it contains.

    A hop of 256 rather than 512: at 44.1 kHz that is 5.8 ms, and a kick and a snare
    struck a sixteenth apart at 160 bpm are only 94 ms apart. Resolution here costs little
    and mistimed triggers are the most audible failure there is.
    """
    import librosa

    mono = samples.mean(axis=1) if samples.ndim > 1 else np.asarray(samples)
    mono = np.asarray(mono, dtype=np.float32)

    spectrum = np.abs(librosa.stft(mono, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=n_fft)

    envelopes = {
        "kick": _band_envelope(spectrum, freqs, *KICK_HZ),
        "snare_body": _band_envelope(spectrum, freqs, *SNARE_BODY_HZ),
        "snare_rattle": _band_envelope(spectrum, freqs, *SNARE_RATTLE_HZ),
        "hihat": _band_envelope(spectrum, freqs, *HIHAT_HZ),
    }
    # What each band looks like when its drum is genuinely playing.
    #
    # Measured at the onsets rather than across the whole envelope, because a separated
    # drums stem is not only drums. On a real track the 30-120 Hz band was held up by
    # bass guitar bleed between the hits: it sat at 24 dB while idling and only reached
    # 8 dB on an actual kick, so a ceiling taken from the whole envelope was set by the
    # bass and every kick failed the test. Asking "how loud is this band when something
    # is being struck" is immune to anything that merely sustains.
    ceilings: dict[str, float] = {}

    onset_env = librosa.onset.onset_strength(
        S=librosa.amplitude_to_db(spectrum, ref=np.max), sr=sample_rate, hop_length=hop
    )
    frames = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sample_rate, hop_length=hop, backtrack=True
    )
    times = librosa.frames_to_time(frames, sr=sample_rate, hop_length=hop)

    at_onsets = np.clip(frames.astype(int), 0, spectrum.shape[1] - 1)
    for name, envelope in envelopes.items():
        struck = envelope[at_onsets] if at_onsets.size else envelope
        ceilings[name] = float(np.percentile(struck, 90)) if struck.size else 0.0

    before = max(1, int(BEFORE_MS / 1000.0 * sample_rate / hop))
    after = max(1, int(AFTER_MS / 1000.0 * sample_rate / hop))
    frame_count = spectrum.shape[1]

    hits: list[Hit] = []
    for time_s, frame in zip(times, frames, strict=False):
        index = int(frame)
        if hits and time_s - hits[-1].time_s < MIN_SPACING_S:
            continue

        rises, present = {}, {}
        for name, envelope in envelopes.items():
            quiet = envelope[max(0, index - before) : max(1, index)]
            loud = envelope[index : min(frame_count, index + after)]
            if quiet.size == 0 or loud.size == 0:
                rises[name] = 0.0
                present[name] = False
                continue
            present[name] = bool(loud.max() >= ceilings[name] - PRESENCE_DB)
            # Median of the quiet window, not its minimum: a single dip in the
            # moment before a hit would otherwise inflate every band's rise, and with it
            # every drum's false-positive rate.
            rises[name] = float(loud.max() - np.median(quiet))

        # Both tests, every time: the band jumped, and the band is actually loud.
        kinds = []
        # The second clause mirrors the snare rule: a stroke whose top octave jumped
        # further than its low end did is a cymbal with some thump behind it, not a kick.
        if (
            rises["kick"] >= RISE_DB
            and present["kick"]
            and rises["kick"] >= rises["hihat"]
        ):
            kinds.append("kick")
        # Rattle is the snare's signature; without it a body jump is a tom or a bass note.
        # The last clause is what separates a snare from a hi-hat. Both fill the
        # rattle band, but a hat's energy peaks above it and a snare's peaks below, so a
        # stroke whose top octave jumped further than its rattle did is a cymbal. Without
        # this, 38% of snare claims were hats.
        if (
            rises["snare_rattle"] >= RISE_DB
            and present["snare_rattle"]
            and rises["snare_body"] >= SNARE_BODY_RISE_DB
            and present["snare_body"]
            and rises["snare_rattle"] >= rises["hihat"]
        ):
            kinds.append("snare")
        if rises["hihat"] >= RISE_DB and present["hihat"]:
            kinds.append("hihat")

        if not kinds:
            continue

        start = int(time_s * sample_rate)
        window = mono[start : start + int(0.03 * sample_rate)]
        hits.append(
            Hit(
                time_s=float(time_s),
                kinds=kinds,
                strength=float(np.abs(window).max()) if window.size else 0.0,
                rises={k: round(v, 1) for k, v in rises.items()},
            )
        )

    return hits


def count_by_kind(hits: list[Hit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        for kind in hit.kinds:
            counts[kind] = counts.get(kind, 0) + 1
    return counts
