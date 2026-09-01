"""Dropping overtones that a polyphonic transcriber reported as notes.

A distorted guitar is mostly harmonics by design. Feed one to a polyphonic transcriber
and it dutifully reports the octave and the octave-plus-fifth above every fundamental as
separate notes, because acoustically they *are* there — nobody played them.

Left in, they triple the note count and fill the tab with notes the guitarist never
fretted. The test is positional: an overtone sounds at the same instant as its
fundamental, at a specific interval above it, and more quietly.

Pure, so the rule is testable without audio.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.notes import NoteEvent, cluster_by_onset

# Semitone intervals above a fundamental that a plucked or distorted string produces
# strongly: the octave (2f), the octave-and-a-fifth (3f), and two octaves (4f).
HARMONIC_INTERVALS = (12, 19, 24)


def remove_harmonics(
    notes: Sequence[NoteEvent],
    window_s: float = 0.06,
    intervals: Sequence[int] = HARMONIC_INTERVALS,
    velocity_ratio: float = 1.0,
) -> tuple[list[NoteEvent], list[NoteEvent]]:
    """Split notes into (kept, discarded-as-overtones).

    A note is treated as an overtone when, in the same onset cluster, there is a note
    exactly ``interval`` semitones below it that is at least as loud. The loudness test
    is what stops a genuine melody note an octave above a quiet accompaniment from being
    thrown away — a real note played high is usually not quieter than the note beneath it.
    """
    kept: list[NoteEvent] = []
    dropped: list[NoteEvent] = []

    for cluster in cluster_by_onset(notes, window_s):
        by_pitch: dict[int, NoteEvent] = {}
        for note in cluster:
            # If a pitch appears twice in one cluster, keep the loudest instance.
            existing = by_pitch.get(note.pitch)
            if existing is None or note.velocity > existing.velocity:
                by_pitch[note.pitch] = note

        for note in cluster:
            is_overtone = False
            for interval in intervals:
                root = by_pitch.get(note.pitch - interval)
                if root is not None and root.velocity >= note.velocity * velocity_ratio:
                    is_overtone = True
                    break
            (dropped if is_overtone else kept).append(note)

    kept.sort(key=lambda n: (n.start_s, n.pitch))
    dropped.sort(key=lambda n: (n.start_s, n.pitch))
    return kept, dropped
