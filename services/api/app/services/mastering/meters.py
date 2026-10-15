"""Meters over time: what a master does across a song, not four numbers for all of it.

X0R-1205. Integrated loudness, true peak and dynamic range are all measured already, and all
three are single figures for a whole song - which says nothing about the quiet bridge, the
chorus that hits the limiter, or the breakdown where the width pushes the mix towards mono.

Three series, on one time axis:

- **Short-term loudness** (EBU R128's 3 s window) - the shape of the song's loudness.
- **Momentary loudness** (400 ms) - where it peaks.
- **Phase correlation** - +1 when the two channels agree, 0 when they are independent,
  negative when they fight. This one matters most here: `synth/width.py` and the bass
  centring both push a mix towards cancellation, and until now nothing warned about it. A
  sustained negative stretch means the mix loses its body in mono - a club's subs, a phone,
  a laptop.

Plus **loudness range** (LRA), computed the EBU way from the short-term series rather than
from the crest factor already shown: the 10th to 95th percentile of the short-term loudness
over the parts of the song that are actually playing.

### Why its own windowing rather than a library's

`pyloudnorm` measures a whole buffer. These are the same K-weighted measurement run over
slices of it, so the short-term series and the integrated figure agree where they should,
and the series exists even on the RMS fallback (where it is labelled as such, as everywhere
else in this application).
"""

from __future__ import annotations

import numpy as np

#: EBU R128's windows.
SHORT_S = 3.0
MOMENTARY_S = 0.4
#: One reading every this long. 0.5 s keeps a four-minute song under 500 points per series -
#: enough to draw, small enough to send.
HOP_S = 0.5
#: Correlation below this, held for `WARN_SECONDS`, is called out.
WARN_CORRELATION = 0.0
WARN_SECONDS = 1.5
#: Short-term readings this far under the loudest are not part of the loudness range: EBU
#: gates the quiet ends out so a fade-in does not count as range.
LRA_GATE_LU = -20.0


def _loudness(block: np.ndarray, sample_rate: int) -> float:
    from app.services.mastering.loudness_meter import integrated_loudness

    value, _ = integrated_loudness(block, sample_rate)
    return float(value)


def correlation(block: np.ndarray) -> float:
    """How much the two channels agree, -1 to +1. Silence counts as +1: nothing is fighting."""
    left, right = block[:, 0], block[:, 1]
    spread = float(np.sqrt(np.dot(left, left) * np.dot(right, right)))
    if spread <= 1e-12:
        return 1.0
    return float(np.clip(np.dot(left, right) / spread, -1.0, 1.0))


def loudness_range(short_term: list[float]) -> float | None:
    """EBU's LRA from the short-term series: the 10th to 95th percentile of what is playing.

    `None` when there is not enough of the song above the gate to measure one - which is not
    the same as a song whose range is zero, and saying 0.0 for both would be a made-up
    number. The gate is relative, as EBU's is: a passage this far under the song's own
    loudness is an intro or a fade, not part of its range."""
    values = np.array([v for v in short_term if np.isfinite(v)])
    if values.size < 4:
        return None
    playing = values[values > values.max() + LRA_GATE_LU]
    if playing.size < 4:
        return None
    return float(np.percentile(playing, 95) - np.percentile(playing, 10))


def over_time(audio: np.ndarray, sample_rate: int) -> dict:
    """The three series, the loudness range, and any stretch where the channels fight."""
    from app.services.mastering.dsp import true_peak_db
    from app.services.mastering.loudness_meter import integrated_loudness, loudness_backend

    data = np.asarray(audio, dtype=np.float64)
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    hop = max(1, int(HOP_S * sample_rate))
    short = max(hop, int(SHORT_S * sample_rate))
    momentary = max(hop, int(MOMENTARY_S * sample_rate))

    times, short_term, moment, phase = [], [], [], []
    for start in range(0, max(1, len(data) - hop + 1), hop):
        middle = start + hop / 2
        times.append(round(middle / sample_rate, 2))
        a = max(0, int(middle - short / 2))
        short_term.append(round(_loudness(data[a: a + short], sample_rate), 1))
        b = max(0, int(middle - momentary / 2))
        moment.append(round(_loudness(data[b: b + momentary], sample_rate), 1))
        phase.append(round(correlation(data[start: start + hop]), 3))

    # Where the channels fight for long enough to hear it in mono.
    fighting, run, at = [], 0, 0.0
    for time, value in zip(times, phase, strict=True):
        if value < WARN_CORRELATION:
            if run == 0:
                at = time
            run += 1
        else:
            if run * HOP_S >= WARN_SECONDS:
                fighting.append([at, time])
            run = 0
    if run * HOP_S >= WARN_SECONDS:
        fighting.append([at, times[-1]])

    integrated, backend = integrated_loudness(data, sample_rate)
    said = []
    if fighting:
        worst = min(phase)
        said.append(
            f"The two channels fight for {sum(e - s for s, e in fighting):.0f} s in all "
            f"(from {fighting[0][0]:.0f} s, worst {worst:+.2f}): that much of this mix "
            f"cancels in mono, where a club's subs and a phone live. Less width on the "
            f"widest parts is the fix.")
    lra = loudness_range(short_term)
    if lra is not None and lra >= 12:
        said.append(f"Its loudness range is {lra:.1f} LU - a lot of lift and drop, which is "
                    f"a choice rather than a fault, but it will feel quiet between the peaks.")
    elif lra is not None and lra <= 3:
        said.append(f"Its loudness range is {lra:.1f} LU: very even. Loud all the way through "
                    f"reads as flat after a minute or two.")
    return {
        "times": times,
        "short_term": short_term,
        "momentary": moment,
        "correlation": phase,
        "integrated_lufs": round(float(integrated), 1),
        "true_peak_dbtp": round(float(true_peak_db(data, sample_rate)), 1),
        "loudness_range_lu": None if lra is None else round(lra, 1),
        "fighting": fighting,
        "backend": backend or loudness_backend(),
        "said": said,
    }
