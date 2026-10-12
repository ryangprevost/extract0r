"""Turn downloaded free synth samples into instruments and a kit in the samples folder.

    python tools/import_instruments.py <staging folder> [<samples folder>]

Sprint 12. Ryan asked for real synth samples to start from, and approved downloading three
free-licensed sets into his own samples folder (never the repository):

* Sonic Pi's bundled samples - CC0, sourced from freesound.org
  https://github.com/sonic-pi-net/sonic-pi/tree/dev/etc/samples
* Versilian Community Sample Library, Yamaha TX81Z - CC0 1.0
  https://github.com/sgossner/VCSL
* Modular Samples hardware multisamples - public domain (Unlicense)
  https://github.com/publicsamples

The staging folder is what `fetch` put there (one folder per set). For every file this
decodes it, trims the leading silence (an MP3 starts with ~25 ms of encoder delay, which
would make every note late), measures its pitch with pYIN - a file name's "C3" is a claim,
the measurement is the check - normalises it, and files it as a note of an instrument with
its licence beside it. Needs the ML venv for pYIN.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

import soundfile as sf  # noqa: E402

RATE = 44100
SONIC_PI = ("CC0 1.0 (public domain), via Sonic Pi's bundled samples from freesound.org",
            "https://github.com/sonic-pi-net/sonic-pi/tree/dev/etc/samples")
VCSL = ("CC0 1.0 (public domain), Versilian Community Sample Library",
        "https://github.com/sgossner/VCSL")
MODULAR = ("Public domain (Unlicense), Modular Samples", "https://github.com/publicsamples")

#: staged folder -> (instrument id, name, kind, about, licence)
SETS = {
    "modular_SharpBass": ("microbrute-sharp-bass", "MicroBrute sharp bass", "bass",
                          "Arturia MicroBrute: a hard, bright analog bass - house and techno.",
                          MODULAR),
    "modular_ConcertmateMG1sawbasswobble": ("mg1-wobble-bass", "MG-1 wobble bass", "bass",
                                            "Moog-built Concertmate MG-1: a saw bass with "
                                            "movement - dubstep and electro.", MODULAR),
    "modular_DynamicSaw": ("microbrute-saw-lead", "MicroBrute saw lead", "lead",
                           "Arturia MicroBrute: a raw saw lead.", MODULAR),
    "modular_JP4K3Combo": ("jupiter-stack", "Jupiter-style stack", "stack",
                           "A layered poly-synth stack in the Jupiter manner - big chords, "
                           "trance and synthwave.", MODULAR),
    "modular_BigStack": ("big-stack", "Big stack", "stack",
                         "A wide stacked synth for chords and hooks.", MODULAR),
    "modular_ClusterStrings": ("cluster-strings", "Cluster strings", "strings",
                               "Synth strings - the pad under a drop.", MODULAR),
    "modular_MBStrings": ("microbrute-strings", "MicroBrute strings", "strings",
                          "Arturia MicroBrute string patch - darker, analog.", MODULAR),
    "modular_ConcertmateMG1mg1_pad1": ("mg1-pad", "MG-1 pad", "pad",
                                       "Concertmate MG-1 pad - warm and soft.", MODULAR),
    "tx81z_fm_piano": ("tx81z-fm-piano", "TX81Z FM piano", "keys",
                       "Yamaha TX81Z electric piano - the house and garage keys sound.", VCSL),
    "tx81z_clavisynth": ("tx81z-clavisynth", "TX81Z Clavisynth", "keys",
                         "Yamaha TX81Z clav-like synth - short, funky stabs.", VCSL),
}
#: Sonic Pi basses, each one recorded note: file stem -> (id, name, about).
SONIC_BASSES = {
    "bass_trance_c": ("trance-bass", "Trance bass", "A rolling trance bass."),
    "bass_hard_c": ("hard-bass", "Hard bass", "A hard, gritty bass for big-room EDM."),
    "bass_thick_c": ("thick-bass", "Thick bass", "A thick, round bass."),
    "bass_voxy_c": ("voxy-bass", "Voxy bass", "A vocal, formant-y bass - talking bass."),
    "bass_woodsy_c": ("woodsy-bass", "Woodsy bass", "A soft, woody bass for lo-fi and house."),
    "bass_hit_c": ("hit-bass", "Hit bass", "A short bass hit - plucky."),
    "bass_dnb_f": ("dnb-bass", "DnB bass", "A drum and bass bass."),
}
#: Sonic Pi electronic drums for a kit: drum -> sample stem.
SONIC_KIT = {"kick": "elec_soft_kick", "snare": "elec_snare", "hihat": "elec_tick"}
NOTE = re.compile(r"_([A-G]#?)(-?\d)_")
NAMES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9,
         "A#": 10, "B": 11}


def load(path: Path) -> np.ndarray:
    audio, rate = sf.read(str(path), dtype="float64", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != RATE:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(int(rate), RATE)
        mono = resample_poly(mono, RATE // g, rate // g)
    # Trim the silence in front - an MP3's encoder delay would make every note late.
    peak = float(np.max(np.abs(mono))) or 1.0
    start = int(np.argmax(np.abs(mono) > peak * 10 ** (-50 / 20)))
    mono = mono[max(0, start - int(0.001 * RATE)):]
    return mono / peak * 0.89


def pitch(mono: np.ndarray) -> float | None:
    """The note it plays, by pYIN over its first second and a half. None if unclear."""
    import librosa

    clip = mono[: int(1.5 * RATE)]
    f0, voiced, _ = librosa.pyin(clip, fmin=30, fmax=2000, sr=RATE, frame_length=4096)
    f0 = f0[voiced & np.isfinite(f0)]
    if f0.size < 5:
        return None
    return float(librosa.hz_to_midi(np.median(f0)))


def write_instrument(dest: Path, ident: str, name: str, kind: str, about: str, licence,
                     notes: dict[int, np.ndarray]) -> int:
    folder = dest / "instruments" / ident
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.wav"):
        old.unlink()
    files = {}
    for midi, mono in sorted(notes.items()):
        sf.write(str(folder / f"{midi}.wav"), mono, RATE, subtype="PCM_16")
        files[str(midi)] = f"{midi}.wav"
    (folder / "instrument.json").write_text(json.dumps({
        "name": name, "kind": kind, "about": about, "license": licence[0],
        "source": licence[1], "notes": files}, indent=1), "utf-8")
    return len(files)


def main() -> None:
    stage = Path(sys.argv[1])
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else API.parents[1] / "samples"
    report = []

    for folder, (ident, name, kind, about, licence) in SETS.items():
        notes: dict[int, np.ndarray] = {}
        skipped = 0
        for path in sorted((stage / folder).glob("*")):
            if path.suffix.lower() not in (".wav", ".mp3", ".flac", ".aif", ".aiff"):
                continue
            mono = load(path)
            measured = pitch(mono)
            claimed = NOTE.search(path.name)
            if claimed:
                # VCSL names its notes; a name the measurement agrees with (to within a
                # semitone, any octave) is trusted for the octave too.
                named = 12 * (int(claimed.group(2)) + 1) + NAMES[claimed.group(1)]
                if measured is None or abs(((measured - named) + 6) % 12 - 6) > 1.0:
                    skipped += 1
                    continue
                key = named
            else:
                if measured is None:
                    skipped += 1
                    continue
                key = int(round(measured))
            notes.setdefault(key, mono)
        count = write_instrument(dest, ident, name, kind, about, licence, notes)
        report.append(f"{name}: {count} notes" + (f" ({skipped} unclear, left out)"
                                                  if skipped else ""))

    for stem, (ident, name, about) in SONIC_BASSES.items():
        path = stage / "sonicpi" / f"{stem}.flac"
        if not path.exists():
            continue
        mono = load(path)
        measured = pitch(mono)
        if measured is None:
            report.append(f"{name}: no clear pitch, left out")
            continue
        write_instrument(dest, ident, name, "bass", about, SONIC_PI, {int(round(measured)): mono})
        report.append(f"{name}: 1 note ({int(round(measured))})")

    # The electro kit: one-shots in the samples folder, and a kit naming them.
    from app.services.synth import library

    names = {}
    for drum, stem in SONIC_KIT.items():
        path = stage / "sonicpi" / f"{stem}.flac"
        if path.exists():
            sample_name = f"sonic pi {stem.replace('_', ' ')}"
            sf.write(str(dest / f"{sample_name}.wav"), load(path), RATE, subtype="PCM_16")
            names[drum] = sample_name
    if names:
        library.save_kit(dest, "electro", names)
        report.append(f"electro kit: {', '.join(names)}")
    (dest / "instruments" / "SOURCES.txt").write_text(
        "Instruments here were made by tools/import_instruments.py from:\n"
        + "\n".join(f"- {lic[0]}: {lic[1]}" for lic in (SONIC_PI, VCSL, MODULAR)) + "\n",
        "utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
