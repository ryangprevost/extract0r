"""Render solved shapes as the ASCII tablature everyone already knows how to read."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.domain.notes import quantize
from app.domain.tab.fretboard import STANDARD_GUITAR, Shape, Tuning

STRING_LABELS = {
    6: ("E", "A", "D", "G", "B", "e"),
    7: ("B", "E", "A", "D", "G", "B", "e"),
    4: ("E", "A", "D", "G"),
    5: ("B", "E", "A", "D", "G"),
}


@dataclass(frozen=True, slots=True)
class TabLayout:
    division: int = 16  # grid resolution, in notes-per-whole-note
    columns_per_line: int = 64
    bar_lines: bool = True
    beats_per_bar: int = 4


def string_labels(tuning: Tuning) -> tuple[str, ...]:
    labels = STRING_LABELS.get(tuning.string_count)
    if labels:
        return labels
    return tuple(str(i) for i in range(tuning.string_count))


def render(
    shapes: Sequence[Shape],
    tuning: Tuning = STANDARD_GUITAR,
    tempo_bpm: float = 120.0,
    layout: TabLayout | None = None,
    title: str | None = None,
    time_signature: tuple[int, int] = (4, 4),
    key_name: str | None = None,
    first_beat_s: float = 0.0,
) -> str:
    """Lay shapes onto a time grid and draw one ASCII staff per line.

    Columns are quantised grid slots, so the horizontal spacing carries real rhythm
    information instead of just note order.
    """
    layout = layout or TabLayout()
    # The detected metre decides where bar lines fall; a 3/4 song barred in 4 is unreadable.
    layout = replace(layout, beats_per_bar=time_signature[0])
    if not shapes:
        return _empty_staff(tuning, layout, title)

    # Map every shape onto a grid column, nudging collisions rather than dropping notes.
    placed: dict[int, list[tuple[int, int]]] = {}
    for shape in shapes:
        # Offset by the detected downbeat so bar one starts at the music, not at t=0.
        column = quantize(shape.start_s - first_beat_s, tempo_bpm, layout.division)
        column = max(0, column)
        while column in placed:
            column += 1
        placed[column] = [(p.string, p.fret) for p in shape.positions]

    total_columns = max(placed) + 1
    # Each grid slot gets as many characters as the widest fret number needs.
    cell = max(2, max((len(str(f)) for cells in placed.values() for _, f in cells), default=1) + 1)

    lines: list[str] = []
    if title:
        lines += [title, "=" * len(title), ""]
    header = (
        f"tuning: {tuning.name}   tempo: {tempo_bpm:.0f} BPM   "
        f"time: {time_signature[0]}/{time_signature[1]}   grid: 1/{layout.division}"
    )
    if key_name:
        header += f"   key: {key_name}"
    lines += [header, ""]

    labels = string_labels(tuning)
    columns_per_line = max(8, layout.columns_per_line)

    for block_start in range(0, total_columns, columns_per_line):
        block_end = min(block_start + columns_per_line, total_columns)
        # Rows are built low-string-first, then reversed so the high string prints on top.
        rows = ["" for _ in range(tuning.string_count)]
        for column in range(block_start, block_end):
            cells = dict(placed.get(column, []))
            grid_per_beat = layout.division // 4
            is_bar = (
                layout.bar_lines
                and grid_per_beat
                and column % (grid_per_beat * layout.beats_per_bar) == 0
                and column != block_start
            )
            for string in range(tuning.string_count):
                if is_bar:
                    rows[string] += "|"
                fret = cells.get(string)
                rows[string] += str(fret).ljust(cell, "-") if fret is not None else "-" * cell

        for string in reversed(range(tuning.string_count)):
            lines.append(f"{labels[string]:>2}|-{rows[string]}-|")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _empty_staff(tuning: Tuning, layout: TabLayout, title: str | None) -> str:
    labels = string_labels(tuning)
    head = [title, "=" * len(title), ""] if title else []
    head.append("(no notes detected above the confidence threshold)")
    head.append("")
    body = [
        f"{labels[s]:>2}|-{'-' * layout.columns_per_line}-|"
        for s in reversed(range(tuning.string_count))
    ]
    return "\n".join(head + body) + "\n"
