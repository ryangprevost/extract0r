"""Drum notation. Same grid idea as string tab, but lanes instead of strings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.domain.notes import NoteEvent, quantize

# General MIDI percussion keys -> (lane label, notehead, sort order top-to-bottom).
GM_DRUM_MAP: dict[int, tuple[str, str, int]] = {
    49: ("CC", "x", 0),   # crash
    57: ("CC", "x", 0),
    51: ("RD", "x", 1),   # ride
    59: ("RD", "x", 1),
    42: ("HH", "x", 2),   # closed hi-hat
    44: ("HH", "x", 2),   # pedal hi-hat
    46: ("HH", "o", 2),   # open hi-hat
    38: ("SD", "o", 3),   # snare
    40: ("SD", "o", 3),
    37: ("SD", "x", 3),   # side stick
    48: ("T1", "o", 4),
    50: ("T1", "o", 4),
    45: ("T2", "o", 5),
    47: ("T2", "o", 5),
    41: ("FT", "o", 6),
    43: ("FT", "o", 6),
    36: ("BD", "o", 7),   # kick
    35: ("BD", "o", 7),
}

LANE_ORDER = ("CC", "RD", "HH", "SD", "T1", "T2", "FT", "BD")


@dataclass(frozen=True, slots=True)
class DrumLayout:
    division: int = 16
    columns_per_line: int = 64
    beats_per_bar: int = 4
    drop_empty_lanes: bool = True


def render(
    notes: Sequence[NoteEvent],
    tempo_bpm: float = 120.0,
    layout: DrumLayout | None = None,
    title: str | None = None,
    time_signature: tuple[int, int] = (4, 4),
    first_beat_s: float = 0.0,
) -> str:
    layout = layout or DrumLayout()
    layout = replace(layout, beats_per_bar=time_signature[0])
    grid: dict[str, dict[int, str]] = {lane: {} for lane in LANE_ORDER}

    for note in notes:
        lane, head, _ = GM_DRUM_MAP.get(note.pitch, ("??", "x", 9))
        if lane == "??":
            continue
        column = max(0, quantize(note.start_s - first_beat_s, tempo_bpm, layout.division))
        grid[lane][column] = head

    used = [
        lane for lane in LANE_ORDER if grid[lane] or not layout.drop_empty_lanes
    ] or list(LANE_ORDER)
    total_columns = max(
        (col for lane in used for col in grid[lane]), default=0
    ) + 1

    lines: list[str] = []
    if title:
        lines += [title, "=" * len(title), ""]
    lines += [
        f"tempo: {tempo_bpm:.0f} BPM   time: {time_signature[0]}/{time_signature[1]}   "
        f"grid: 1/{layout.division}",
        "",
    ]

    grid_per_beat = layout.division // 4
    for block_start in range(0, total_columns, layout.columns_per_line):
        block_end = min(block_start + layout.columns_per_line, total_columns)
        for lane in used:
            row = ""
            for column in range(block_start, block_end):
                if (
                    grid_per_beat
                    and column % (grid_per_beat * layout.beats_per_bar) == 0
                    and column != block_start
                ):
                    row += "|"
                row += grid[lane].get(column, "-")
            lines.append(f"{lane}|{row}|")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
