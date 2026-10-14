// Chops: stutters, rises, gates, stops and tape stops cut into the version. Sprint 20.
//
// Ryan, 2026-10-13: "add the chops and stabs as controls on the page ... can you add chops to
// the instruments as well like stutters and whatnot" - pointing at Madeon's "Icarus". So a
// chop is on the whole track, or on one part: the lead climbs in a rise while the beat
// carries on. Suggest places them where a producer would - the ends of phrases - and never
// inside the build into a drop, where the riser already owns the moment.

const Chops = (() => {
  const KINDS = {
    stutter: "Stutter - the beat's first slice repeated faster and faster into the next bar",
    rise: "Rise - a stutter that climbs a semitone every sixteenth, Madeon-style",
    gate: "Gate - chopped into sixteenths, on and off",
    stop: "Stop - silence, then everything slams back",
    tape: "Tape stop - slows to a halt, pitch falling with it",
  };
  const LENGTHS = [["0.25", "1/16"], ["0.5", "1/8"], ["1", "1 beat"], ["2", "2 beats"],
    ["4", "a bar"]];
  const PARTS = [["", "whole track"], ["bass", "bass"], ["guitar", "guitar"],
    ["piano", "keys"], ["other", "other"], ["vocals", "vocals"], ["beat", "added beat"]];

  let chops = [];          // {bar, beat (0-3), beats, kind, part}

  function select(options, value, label, onChange) {
    const pick = document.createElement("select");
    pick.setAttribute("aria-label", label);
    for (const [v, text] of options) pick.appendChild(new Option(text, v));
    pick.value = String(value);
    pick.addEventListener("change", () => onChange(pick.value));
    return pick;
  }

  function render() {
    const list = $("chops-list");
    if (!list) return;
    list.innerHTML = "";
    chops.sort((a, b) => a.bar - b.bar || a.beat - b.beat);
    chops.forEach((c, i) => {
      const row = document.createElement("li");
      row.className = "chop-row";
      const bar = document.createElement("input");
      bar.type = "number";
      bar.min = "1";
      bar.value = c.bar;
      bar.setAttribute("aria-label", "Bar");
      bar.addEventListener("change", () => {
        c.bar = Math.max(1, parseInt(bar.value, 10) || 1);
        render();
      });
      row.append("bar ", bar,
        select([["0", "beat 1"], ["1", "beat 2"], ["2", "beat 3"], ["3", "beat 4"]], c.beat,
          "Beat", (v) => { c.beat = Number(v); }),
        select(LENGTHS, c.beats, "Length", (v) => { c.beats = Number(v); }),
        select(Object.keys(KINDS).map((k) => [k, k === "tape" ? "tape stop" : k]), c.kind,
          "Kind", (v) => { c.kind = v; row.title = KINDS[v]; }),
        "on ",
        select(PARTS, c.part, "On", (v) => { c.part = v; }));
      row.title = KINDS[c.kind];
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "small";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", `Remove the chop at bar ${c.bar}`);
      remove.addEventListener("click", () => { chops.splice(i, 1); render(); });
      row.appendChild(remove);
      list.appendChild(row);
    });
    $("chops-said").textContent = chops.length
      ? `${chops.length} chop${chops.length === 1 ? "" : "s"} - cut in when you make the version.`
      : "No chops yet.";
  }

  /** Bars of the version: the arrangement's, else the song's. */
  function versionBars() {
    return typeof Arrange !== "undefined" && Arrange.versionBars ? Arrange.versionBars() : 0;
  }

  function buildBars() {
    const drops = typeof Arrange !== "undefined" && Arrange.dropBars ? Arrange.dropBars() : [];
    if (!drops.length && $("opt-drop")?.checked) {
      const bar = parseInt($("drop-bar")?.value, 10);
      if (bar) drops.push(bar);
    }
    return new Set(drops.flatMap((d) => [d - 2, d - 1]));
  }

  /** Sprint 21: chops for a recipe - how many, and on which instruments. */
  function suggestFor(level, instruments, lead = "piano", stabs = "") {
    if (!level || level === "none") {
      reset();
      return;
    }
    const bars = versionBars();
    const builds = buildBars();
    const every = level === "few" ? 8 : 4;
    chops = [];
    for (let bar = every; bar <= bars; bar += every) {
      if (builds.has(bar)) continue;
      if (bar % 16 === 0) {
        chops.push({ bar, beat: 2, beats: 2, kind: "rise", part: instruments ? lead : "" });
      } else if (bar % 8 === 0) {
        chops.push({ bar, beat: 3, beats: 1, kind: "stutter", part: "" });
      } else {
        chops.push({ bar, beat: 2, beats: 2, kind: "gate", part: instruments ? stabs : "" });
      }
      if (level === "lots" && bar % 8 === 4 && !builds.has(bar - 2)) {
        chops.push({ bar: bar - 2, beat: 3, beats: 1, kind: "stutter",
          part: instruments ? lead : "" });
      }
    }
    render();
  }

  /** At phrase ends: a stutter every eighth bar, a rise every sixteenth, a gate between. */
  function suggest() {
    const bars = versionBars();
    if (!bars) {
      $("chops-said").textContent = "Load a song first, so there are bars to chop.";
      return;
    }
    const builds = buildBars();
    chops = [];
    for (let bar = 4; bar <= bars; bar += 4) {
      if (builds.has(bar)) continue;
      if (bar % 16 === 0) chops.push({ bar, beat: 2, beats: 2, kind: "rise", part: "" });
      else if (bar % 8 === 0) chops.push({ bar, beat: 3, beats: 1, kind: "stutter", part: "" });
      else chops.push({ bar, beat: 2, beats: 2, kind: "gate", part: "" });
    }
    render();
    $("chops-said").textContent += " Change any of them, or put one on a single part.";
  }

  function add() {
    const last = chops.length ? chops[chops.length - 1].bar + 4 : 4;
    chops.push({ bar: last, beat: 3, beats: 1, kind: "stutter", part: "" });
    render();
  }

  /** What the version request carries. */
  function request() {
    return chops.map((c) => ({
      bar: c.bar, beat: c.beat, beats: c.beats, kind: c.kind, parts: c.part ? [c.part] : [],
    }));
  }

  function reset() {
    chops = [];
    render();
  }

  function init() {
    if (!$("chops-add") || $("chops-add").dataset.wired) return;
    $("chops-add").dataset.wired = "yes";
    $("chops-add").addEventListener("click", add);
    $("chops-suggest").addEventListener("click", suggest);
    $("chops-clear").addEventListener("click", reset);
    render();
  }

  return { init, request, reset, suggestFor };
})();

document.addEventListener("DOMContentLoaded", () => Chops.init());
