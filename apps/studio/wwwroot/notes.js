// Editing a part's notes: a piano roll. Sprint 6.
//
// Ryan, 2026-10-12: "yes, go ahead with editing notes and beats". So once a part has been
// played on something, its notes open here - for drums, three lanes of strokes - and can be
// added, moved, resized, deleted, transposed, quantised and swung, with undo. Notes are kept
// in beats on the server, so an edit made at one tempo is still right at another.
//
// Saving keeps the edit and plays the part again from it. The version then says the part
// is yours ("Edited by you ...") - an edit is never passed off as the band's playing.

const Notes = (() => {
  const DRUM_ROWS = [[42, "hat"], [38, "snare"], [36, "kick"]];
  const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const BLACK = new Set([1, 3, 6, 8, 10]);
  const GUTTER = 44;

  let stem = null;
  let label = "";
  let drums = false;
  let notes = [];            // {beat, length, pitch, velocity}
  let selected = new Set();  // indexes into notes
  let history = [];
  let grids = ["1/4", "1/8", "1/16", "1/8 triplet", "1/16 triplet"];
  let pxPerBeat = 48;
  let rowH = 12;
  let low = 36;
  let high = 72;
  let bars = 8;
  let onSaved = null;
  let drag = null;

  const GRID_BEATS = {
    "1/4": 1, "1/8": 0.5, "1/16": 0.25, "1/8 triplet": 1 / 3, "1/16 triplet": 1 / 6,
  };
  const grid = () => GRID_BEATS[$("notes-grid").value] || 0.25;
  const snapOn = () => $("notes-snap").checked;
  const snap = (beat) => (snapOn() ? Math.round(beat / grid()) * grid() : beat);

  // --- geometry ----------------------------------------------------------------------------

  function rows() {
    return drums ? DRUM_ROWS.map(([p]) => p) : range(high, low);
  }
  function range(top, bottom) {
    const out = [];
    for (let p = top; p >= bottom; p--) out.push(p);
    return out;
  }
  const yOf = (pitch) => rows().indexOf(pitch) * rowH;
  const pitchAt = (y) => rows()[Math.max(0, Math.min(rows().length - 1, Math.floor(y / rowH)))];
  const xOf = (beat) => GUTTER + beat * pxPerBeat;
  const beatAt = (x) => Math.max(0, (x - GUTTER) / pxPerBeat);

  function fitRange() {
    if (drums) {
      rowH = 34;
      return;
    }
    rowH = 12;
    const pitches = notes.map((n) => n.pitch);
    const lo = pitches.length ? Math.min(...pitches) : 48;
    const hi = pitches.length ? Math.max(...pitches) : 60;
    low = Math.max(0, lo - 5);
    high = Math.min(127, Math.max(hi + 5, low + 23));
  }

  // --- drawing -------------------------------------------------------------------------------

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  function draw() {
    const canvas = $("notes-canvas");
    if (!canvas) return;
    const end = Math.max(bars * 4, ...notes.map((n) => n.beat + n.length)) + 4;
    const width = Math.ceil(GUTTER + end * pxPerBeat);
    const height = rows().length * rowH;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);

    const panel = css("--panel-2");
    const edge = css("--edge");
    const muted = css("--muted");
    const accent = css("--accent");
    const ink = css("--ink");

    rows().forEach((pitch, i) => {
      g.fillStyle = !drums && BLACK.has(pitch % 12) ? edge : panel;
      g.globalAlpha = !drums && BLACK.has(pitch % 12) ? 0.35 : 1;
      g.fillRect(GUTTER, i * rowH, width - GUTTER, rowH);
      g.globalAlpha = 1;
      g.fillStyle = muted;
      g.font = "10px ui-monospace, monospace";
      const name = drums ? DRUM_ROWS[i][1]
        : pitch % 12 === 0 ? `C${Math.floor(pitch / 12) - 1}` : "";
      if (name) g.fillText(name, 4, i * rowH + rowH / 2 + 3);
    });

    // Grid lines: the chosen grid faint, beats stronger, bars strongest.
    const step = grid();
    for (let b = 0; b <= end + 1e-6; b += step) {
      const bar = Math.abs(b / 4 - Math.round(b / 4)) < 1e-6;
      const beat = Math.abs(b - Math.round(b)) < 1e-6;
      g.strokeStyle = bar ? muted : edge;
      g.globalAlpha = bar ? 0.9 : beat ? 0.55 : 0.25;
      g.beginPath();
      g.moveTo(xOf(b) + 0.5, 0);
      g.lineTo(xOf(b) + 0.5, height);
      g.stroke();
      if (bar) {
        g.globalAlpha = 1;
        g.fillStyle = muted;
        g.fillText(`${Math.round(b / 4) + 1}`, xOf(b) + 3, 10);
      }
    }
    g.globalAlpha = 1;

    notes.forEach((n, i) => {
      if (!rows().includes(n.pitch)) return;
      const x = xOf(n.beat);
      const w = Math.max(4, n.length * pxPerBeat - 1);
      g.globalAlpha = 0.35 + 0.65 * (n.velocity / 127);
      g.fillStyle = accent;
      g.fillRect(x, yOf(n.pitch) + 1, w, rowH - 2);
      g.globalAlpha = 1;
      if (selected.has(i)) {
        g.strokeStyle = ink;
        g.lineWidth = 2;
        g.strokeRect(x + 1, yOf(n.pitch) + 2, w - 2, rowH - 4);
        g.lineWidth = 1;
      }
    });
    say();
  }

  function say() {
    const count = notes.length;
    $("notes-count").textContent =
      `${count} ${drums ? "drum hits" : "notes"}` +
      (selected.size ? ` · ${selected.size} selected` : "") +
      (history.length ? " · unsaved changes" : "");
  }

  // --- editing --------------------------------------------------------------------------------

  function remember() {
    history.push(JSON.stringify(notes));
    if (history.length > 100) history.shift();
  }

  function undo() {
    if (!history.length) return;
    notes = JSON.parse(history.pop());
    selected = new Set();
    draw();
  }

  function hit(x, y) {
    for (let i = notes.length - 1; i >= 0; i--) {
      const n = notes[i];
      if (!rows().includes(n.pitch)) continue;
      const left = xOf(n.beat);
      const right = left + Math.max(4, n.length * pxPerBeat);
      const top = yOf(n.pitch);
      if (x >= left && x <= right && y >= top && y < top + rowH) {
        return { index: i, edge: right - x < 6 && !drums };
      }
    }
    return null;
  }

  function point(event) {
    const box = $("notes-canvas").getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  }

  function down(event) {
    const [x, y] = point(event);
    if (x < GUTTER) return;
    $("notes-canvas").setPointerCapture(event.pointerId);
    const found = hit(x, y);
    remember();
    if (!found) {
      if (!event.shiftKey) selected = new Set();
      const length = drums ? 0.25 : grid();
      notes.push({ beat: Math.max(0, snapOn() ? Math.floor(beatAt(x) / grid()) * grid() : beatAt(x)),
        length, pitch: pitchAt(y), velocity: 100 });
      selected.add(notes.length - 1);
      drag = null;
      draw();
      return;
    }
    if (event.shiftKey) {
      selected.has(found.index) ? selected.delete(found.index) : selected.add(found.index);
    } else if (!selected.has(found.index)) {
      selected = new Set([found.index]);
    }
    drag = {
      mode: found.edge ? "resize" : "move", x, y,
      start: [...selected].map((i) => ({ i, beat: notes[i].beat, pitch: notes[i].pitch,
        length: notes[i].length })),
    };
    draw();
  }

  function moveTo(event) {
    if (!drag) return;
    const [x, y] = point(event);
    const dBeat = (x - drag.x) / pxPerBeat;
    const dRow = Math.round((y - drag.y) / rowH);
    for (const s of drag.start) {
      const n = notes[s.i];
      if (drag.mode === "resize") {
        n.length = Math.max(1 / 16, snapOn() ? Math.max(grid(), snap(s.length + dBeat)) : s.length + dBeat);
      } else {
        n.beat = Math.max(0, snapOn() ? s.beat + snap(dBeat) : s.beat + dBeat);
        const r = rows();
        const at = r.indexOf(s.pitch) + dRow;
        n.pitch = r[Math.max(0, Math.min(r.length - 1, at))];
      }
    }
    draw();
  }

  function up() {
    if (drag) {
      const changed = drag.start.some((s) => {
        const n = notes[s.i];
        return n.beat !== s.beat || n.pitch !== s.pitch || n.length !== s.length;
      });
      if (!changed) history.pop();     // a click that selected, not an edit
    }
    drag = null;
    say();
  }

  function removeSelected() {
    if (!selected.size) return;
    remember();
    notes = notes.filter((_, i) => !selected.has(i));
    selected = new Set();
    draw();
  }

  function nudge(semitones) {
    const which = selected.size ? [...selected] : notes.map((_, i) => i);
    if (!which.length || drums) return;
    remember();
    for (const i of which) notes[i].pitch = Math.max(0, Math.min(127, notes[i].pitch + semitones));
    fitRange();
    draw();
  }

  async function quantise(withSwing) {
    const which = selected.size ? [...selected] : notes.map((_, i) => i);
    if (!which.length) return;
    const swingValue = parseFloat($("beat-swing")?.value);
    const body = {
      notes: which.map((i) => notes[i]),
      grid: $("notes-grid").value,
      strength: parseFloat($("notes-strength").value),
      ends: !drums && $("notes-ends").checked,
      swing: withSwing ? (Number.isFinite(swingValue) ? swingValue : 0.5) : null,
    };
    try {
      const result = await api("/tracks/notes/quantize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      remember();
      which.forEach((index, k) => Object.assign(notes[index], result.notes[k]));
      draw();
    } catch (error) {
      $("notes-said").textContent = error.message || String(error);
    }
  }

  // --- loading and saving ---------------------------------------------------------------------

  async function open(part, name, saved) {
    stem = part;
    label = name;
    onSaved = saved;
    const panel = $("notes-editor");
    $("notes-title").textContent = `Editing the ${name.toLowerCase()}`;
    $("notes-said").textContent = "";
    try {
      const info = await api(`/tracks/${state.trackId}/parts/${part}/notes`);
      drums = info.drums;
      notes = info.notes;
      bars = info.bars;
      grids = info.grids || grids;
      $("notes-state").textContent = info.edited ? "your edit" : "as played";
    } catch (error) {
      $("notes-said").textContent = error.message || String(error);
      panel.hidden = false;
      return;
    }
    const pick = $("notes-grid");
    if (!pick.options.length) for (const g of grids) pick.appendChild(new Option(g, g));
    pick.value = "1/16";
    history = [];
    selected = new Set();
    fitRange();
    $("notes-ends").closest("label").hidden = drums;
    for (const b of document.querySelectorAll(".notes-pitch")) b.hidden = drums;
    panel.hidden = false;
    draw();
    panel.scrollIntoView({ block: "nearest" });
    $("notes-canvas").focus();
  }

  async function save() {
    const button = $("notes-save");
    button.disabled = true;
    try {
      const result = await api(`/tracks/${state.trackId}/parts/${stem}/notes`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes }),
      });
      history = [];
      $("notes-state").textContent = result.edited ? "your edit" : "as played";
      $("notes-said").textContent = result.edited
        ? "Saved. Playing it again from your notes…"
        : "Nothing differs from how it was played, so it plays as played.";
      if (onSaved) await onSaved(stem);
      $("notes-said").textContent = result.edited
        ? "Saved and played. Make the version to hear it in the song - it will say this part is yours."
        : $("notes-said").textContent;
    } catch (error) {
      $("notes-said").textContent = error.message || String(error);
    } finally {
      button.disabled = false;
      say();
    }
  }

  async function reset() {
    try {
      await api(`/tracks/${state.trackId}/parts/${stem}/notes`, { method: "DELETE" });
      await open(stem, label, onSaved);
      if (onSaved) await onSaved(stem);
      $("notes-said").textContent = "Back to as played.";
    } catch (error) {
      $("notes-said").textContent = error.message || String(error);
    }
  }

  function close() {
    $("notes-editor").hidden = true;
    stem = null;
  }

  function key(event) {
    if (!stem) return;
    const mod = event.ctrlKey || event.metaKey;
    if (event.key === "Delete" || event.key === "Backspace") {
      removeSelected();
    } else if (mod && event.key.toLowerCase() === "z") {
      undo();
    } else if (mod && event.key.toLowerCase() === "a") {
      selected = new Set(notes.map((_, i) => i));
      draw();
    } else if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      nudge((event.key === "ArrowUp" ? 1 : -1) * (event.shiftKey ? 12 : 1));
    } else if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && selected.size) {
      remember();
      const by = event.key === "ArrowLeft" ? -grid() : grid();
      for (const i of selected) notes[i].beat = Math.max(0, notes[i].beat + by);
      draw();
    } else {
      return;
    }
    event.preventDefault();
  }

  function init() {
    const canvas = $("notes-canvas");
    if (!canvas || canvas.dataset.wired) return;
    canvas.dataset.wired = "yes";
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", moveTo);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("dblclick", (e) => {
      const [x, y] = point(e);
      const found = hit(x, y);
      if (found) {
        selected = new Set([found.index]);
        removeSelected();
      }
    });
    canvas.addEventListener("keydown", key);
    $("notes-grid").addEventListener("change", draw);
    $("notes-quantise").addEventListener("click", () => quantise(false));
    $("notes-swing").addEventListener("click", () => quantise(true));
    $("notes-up").addEventListener("click", () => nudge(1));
    $("notes-down").addEventListener("click", () => nudge(-1));
    $("notes-oct-up").addEventListener("click", () => nudge(12));
    $("notes-oct-down").addEventListener("click", () => nudge(-12));
    $("notes-delete").addEventListener("click", removeSelected);
    $("notes-all").addEventListener("click", () => {
      selected = new Set(notes.map((_, i) => i));
      draw();
    });
    $("notes-undo").addEventListener("click", undo);
    $("notes-reset").addEventListener("click", reset);
    $("notes-save").addEventListener("click", save);
    $("notes-close").addEventListener("click", close);
    $("notes-zoom-in").addEventListener("click", () => { pxPerBeat = Math.min(160, pxPerBeat * 1.25); draw(); });
    $("notes-zoom-out").addEventListener("click", () => { pxPerBeat = Math.max(12, pxPerBeat / 1.25); draw(); });
  }

  return { init, open, close, isOpenFor: (s) => stem === s };
})();

document.addEventListener("DOMContentLoaded", () => Notes.init());
