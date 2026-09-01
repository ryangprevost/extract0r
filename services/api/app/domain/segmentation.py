"""Turning a frame-by-frame pitch track into discrete notes.

Pure, so the rule that matters can be tested on plain lists.

The rule that matters: **a note ends when it is re-struck, not only when the pitch
changes.** An earlier version split only on pitch change, so a bass line playing the same
note eight times in a bar — which is most rock bass — came out as a single sustained note.
Comparing against a hand-written tab for a real song made that obvious immediately:
`5-5-5-5-5-5-5-5` was being transcribed as one note.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.notes import NoteEvent


def segment_notes(
    pitches: Sequence[float | None],
    times: Sequence[float],
    confidences: Sequence[float],
    onset_indices: frozenset[int] | set[int] = frozenset(),
    min_duration_s: float = 0.05,
    min_confidence: float = 0.4,
    min_restrike_s: float = 0.09,
) -> list[NoteEvent]:
    """Group consecutive frames of equal pitch into notes, splitting at re-attacks.

    ``pitches`` holds a MIDI number per frame, or None where the frame is unvoiced.
    ``onset_indices`` are frame indices where an attack was detected; a note is closed and
    a new one started at each, even when the pitch has not moved.

    ``min_restrike_s`` is the guard against the opposite failure. Onset detectors fire
    spuriously on sustained material — tremolo, vibrato, an amp's noise floor — and
    without a refractory period a single held note shatters into dozens of fragments.
    Nothing is played twice inside 90 ms, so a split that soon is detector noise.
    """
    if not (len(pitches) == len(times) == len(confidences)):
        raise ValueError("pitches, times and confidences must be the same length")

    notes: list[NoteEvent] = []
    start: int | None = None

    def close(end_index: int) -> None:
        nonlocal start
        if start is None:
            return
        pitch = pitches[start]
        if pitch is not None:
            end_index = min(end_index, len(times) - 1)
            duration = times[end_index] - times[start]
            window = confidences[start:end_index] or [confidences[start]]
            confidence = sum(window) / len(window)
            if duration >= min_duration_s and confidence >= min_confidence:
                notes.append(
                    NoteEvent(
                        start_s=float(times[start]),
                        end_s=float(times[end_index]),
                        pitch=max(0, min(127, int(round(pitch)))),
                        velocity=max(1, min(127, int(confidence * 127))),
                        confidence=float(min(1.0, max(0.0, confidence))),
                    )
                )
        start = None

    for index, pitch in enumerate(pitches):
        if pitch is None:
            close(index)
            continue

        if start is None:
            start = index
            continue

        # Two reasons to end the note here: the pitch moved, or the player struck the
        # string again at the same pitch.
        pitch_changed = round(pitch) != round(pitches[start])  # type: ignore[arg-type]
        restruck = (
            index in onset_indices
            and (times[index] - times[start]) >= min_restrike_s
        )

        if pitch_changed or restruck:
            close(index)
            start = index

    close(len(times) - 1)
    return notes


def nearest_frames(event_times: Sequence[float], frame_times: Sequence[float]) -> set[int]:
    """Map event timestamps onto the nearest analysis frame index.

    Used to line detected onsets up with the pitch track, which is on its own hop grid.
    """
    if not len(frame_times):
        return set()

    out: set[int] = set()
    cursor = 0
    for event in sorted(event_times):
        while (
            cursor + 1 < len(frame_times)
            and abs(frame_times[cursor + 1] - event) <= abs(frame_times[cursor] - event)
        ):
            cursor += 1
        out.add(cursor)
    return out
