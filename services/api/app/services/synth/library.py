"""The sound library: every kit and voice, previews of each, and kits made of your own hits.
Sprint 4, X0R-1343.

Ryan asked for a *"sample library for synth and drums"*. What that can mean here is bounded by
`kit.py`'s rule, which this keeps: **nothing recorded ships**. Shipping a library means
shipping someone's audio with licensing nobody can check. So the library is two things:

* **Built in** - nine synthesised kits and ten voices, each named for the music it is the
  textbook sound of, each with a preview so a choice is made by ear rather than by name.
* **Yours** - one-shots you upload (the samples you already own: a pack you bought, hits you
  recorded) sorted into kick, snare and hat by listening to them, and saved as a kit you can
  put on any drum part or added beat. They live in `samples/`, outside the repository and
  outside retention, exactly as an uploaded sample already does (X0R-1326).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from app.services.drums.kit import DRUMS, KITS, render_voice

#: Where saved kits live, inside the samples directory.
KIT_DIR = "kits"
#: What a kit may be called - a name becomes a filename.
SAFE_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")

#: What each built-in kit is, in a line.
KIT_ABOUT = {
    "edm": "A 909-shaped kick with deep sub, a clap, a tight hat. Big-room and festival.",
    "house": "A round, warm kick, a clap with body, an airy hat.",
    "techno": "A long rumbling kick, a narrow clap, a metallic tick of a hat.",
    "trap": "A hard, short kick with a click - the 808 carries the sub - and a crisp snare.",
    "dnb": "A short kick out of the bass's way and a high, cracking snare.",
    "lofi": "Soft and dusty - every drum band-limited, nothing sharp.",
    "tight": "Short and controlled. Modern rock and pop.",
    "roomy": "Longer decays, more air around each hit.",
    "punchy": "Fast and forward, with more attack.",
}


# --- telling a kick from a snare from a hat ----------------------------------------------

#: A one-shot with at least this share of its energy under 150 Hz is a kick.
KICK_LOW_DB = -6.0
#: One with less than this share below 3 kHz is a hat or cymbal. Not "most of it above
#: 5 kHz", which was the first rule and called five of the nine built-in snares hats: a snare
#: whose rattle is highpassed noise really does put most of its energy up there. What a snare
#: always keeps is its body and crack under 3 kHz - at least -8 dB of the whole across the
#: built-in kits - where a hat keeps almost nothing (-29 dB at most).
HAT_BELOW_3K_DB = -18.0


def _share(audio: np.ndarray, sample_rate: int, lo: float, hi: float) -> float:
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    freqs = np.fft.rfftfreq(audio.size, 1.0 / sample_rate)
    band = spectrum[(freqs >= lo) & (freqs < hi)].sum() + 1e-12
    return float(10 * np.log10(band / (spectrum.sum() + 1e-12)))


def classify(audio: np.ndarray, sample_rate: int) -> tuple[str, str]:
    """Which drum a one-shot is, and the sentence that says why.

    Two energy shares, because they are what the ear goes by: a kick is mostly below 150 Hz,
    a hat has almost nothing below 3 kHz, and whatever is neither is a snare or a clap.
    Checked against every voice of every built-in kit.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else np.asarray(audio, dtype=np.float64)
    mono = mono[: int(0.5 * sample_rate)]
    low = _share(mono, sample_rate, 20.0, 150.0)
    under = _share(mono, sample_rate, 20.0, 3000.0)
    if low >= KICK_LOW_DB:
        return "kick", f"most of its energy is below 150 Hz ({low:.0f} dB of the whole)"
    if under < HAT_BELOW_3K_DB:
        return "hihat", f"almost nothing below 3 kHz ({under:.0f} dB of the whole)"
    return "snare", "a body and crack under 3 kHz, without a kick's weight - a snare or a clap"


# --- your kits ---------------------------------------------------------------------------


def kit_dir(sample_dir: Path) -> Path:
    return Path(sample_dir) / KIT_DIR


def user_kits(sample_dir: Path) -> dict[str, dict[str, str]]:
    """Every saved kit: name -> {drum: sample name}."""
    out = {}
    folder = kit_dir(sample_dir)
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out[path.stem] = {d: data[d] for d in DRUMS if data.get(d)}
        except Exception:  # noqa: BLE001 - one unreadable kit should not hide the rest
            continue
    return out


def save_kit(sample_dir: Path, name: str, drums: dict[str, str]) -> Path:
    folder = kit_dir(sample_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({d: drums[d] for d in DRUMS if drums.get(d)}), "utf-8")
    return path


def delete_kit(sample_dir: Path, name: str) -> bool:
    path = kit_dir(sample_dir) / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def exists(kit: str, sample_dir: Path | None) -> bool:
    return kit in KITS or (sample_dir is not None and kit in user_kits(sample_dir))


def _load(path: Path, sample_rate: int) -> np.ndarray:
    """A one-shot at the track's rate, mono, peak 1. Rate-converted properly - a resample
    that keeps pitch, unlike the sampler's repitching - because a kick at the wrong rate
    should still be the same kick."""
    import soundfile as sf
    from scipy.signal import resample_poly

    data, rate = sf.read(str(path), dtype="float64", always_2d=True)
    mono = data.mean(axis=1)
    if rate != sample_rate:
        from math import gcd

        g = gcd(int(rate), int(sample_rate))
        mono = resample_poly(mono, sample_rate // g, rate // g)
    mono = mono[: int(2.0 * sample_rate)]
    edge = max(2, int(0.002 * sample_rate))
    if mono.size > 2 * edge:
        mono[-edge:] *= np.linspace(1.0, 0.0, edge)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    return mono / peak if peak > 0 else mono


def sounds(kit: str, sample_rate: int, sample_dir: Path | None = None,
           seed: int = 0) -> dict[str, np.ndarray]:
    """One hit per drum for a kit, built in or yours. A drum your kit leaves out falls back
    to the edm kit's, so a kit of just a kick and a clap still plays a whole beat."""
    if kit in KITS:
        return {d: render_voice(KITS[kit][d], sample_rate, seed=seed + i)
                for i, d in enumerate(DRUMS) if d in KITS[kit]}
    mine = user_kits(sample_dir) if sample_dir is not None else {}
    if kit not in mine:
        raise KeyError(kit)
    out = {}
    for i, drum in enumerate(DRUMS):
        name = mine[kit].get(drum)
        path = Path(sample_dir) / f"{name}.wav" if name else None
        if path is not None and path.exists():
            out[drum] = _load(path, sample_rate)
        else:
            out[drum] = render_voice(KITS["edm"][drum], sample_rate, seed=seed + i)
    return out


# --- previews ----------------------------------------------------------------------------


def preview_kit(kit_sounds: dict[str, np.ndarray], sample_rate: int) -> np.ndarray:
    """Two bars of a plain beat - kick on 1 and 3, snare on 2 and 4, hats in eighths - so
    kits are compared on the same pattern rather than on whatever showed them off."""
    beat = 60.0 / 120.0
    out = np.zeros(int(4.6 * sample_rate))

    def lay(drum: str, t: float, gain: float) -> None:
        hit = kit_sounds.get(drum)
        if hit is None:
            return
        at = int(t * sample_rate)
        end = min(out.size, at + hit.size)
        out[at:end] += hit[: end - at] * gain

    for b in range(8):
        t = b * beat
        if b % 2 == 0:
            lay("kick", t, 0.9)
        else:
            lay("snare", t, 0.7)
        lay("hihat", t, 0.35)
        lay("hihat", t + beat / 2, 0.25)
    return out / max(float(np.max(np.abs(out))), 1e-9) * 0.89


def preview_voice(voice: str, sample_rate: int) -> np.ndarray:
    """A short phrase in the voice's own register: an arpeggio, then the chord held."""
    from app.domain.notes import NoteEvent
    from app.services.synth.voice import render_notes

    low = voice in ("808", "subbass", "reese")
    root = 36 if low else 60
    steps = [0, 7, 12, 7] if low else [0, 4, 7, 12]
    notes = [NoteEvent(i * 0.25, i * 0.25 + 0.22, root + s, 100) for i, s in enumerate(steps)]
    chord = [0] if low else [0, 4, 7]
    notes += [NoteEvent(1.0, 2.4, root + s, 90) for s in chord]
    audio = render_notes(notes, sample_rate, voice, duration_s=3.0)
    return audio / max(float(np.max(np.abs(audio))), 1e-9) * 0.89


def wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    import io

    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
