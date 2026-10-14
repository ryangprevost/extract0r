// The arrangement: the song's sections in any order. Sprint 5.
//
// Ryan, asked what "more manipulation" should mean first: rearrange the song. So the
// sections the server found sit along the top as blocks you can hear and add, and below
// them is the running order of the version - each block movable, repeatable, removable,
// with its own mutes (a breakdown is the chorus without drums) and its own drop.
//
// Until something is changed the version plays as written and nothing is sent, so every
// earlier control behaves exactly as it did. Once the order is touched, the single
// "build up and drop into" control gives way to a drop per block, because a bar number in
// the song and a bar number in the arrangement are no longer the same bar.

const Arrange = (() => {
  //: What a block can mute, in the order the page shows them.
  const MUTABLE = [
    ["drums", "drums"], ["bass", "bass"], ["guitar", "guitar"], ["piano", "keys"],
    ["vocals", "vocals"], ["other", "the rest"], ["beat", "added beat"],
  ];
  const STEMS = MUTABLE.map(([id]) => id).filter((id) => id !== "beat");

  let sections = [];
  let tempo = 0;
  //: The running order: {section, mute: Set, drop}.
  let lane = [];
  let touched = false;

  const byId = (id) => sections.find((s) => s.id === id);

  function asWritten() {
    return sections.map((s) => ({ section: s.id, mute: new Set(), drop: false }));
  }

  async function load() {
    const box = $("arrange-box");
    if (!box || !state.trackId) return;
    try {
      const info = await api(`/tracks/${state.trackId}/sections`);
      sections = info.sections || [];
      tempo = info.tempo_bpm || 0;
      $("arrange-note").textContent = info.note || "";
      barDb = info.bar_db || [];
      detected = info.detected || [];
      marks = sections.map((s) => ({ bar: s.start_bar, label: s.label }));
      drawMarks();
    } catch (error) {
      sections = [];
      $("arrange-note").textContent = error.message || String(error);
    }
    lane = asWritten();
    touched = false;
    box.hidden = !sections.length;
    render();
  }

  function reset() {
    sections = [];
    lane = [];
    touched = false;
    render();
  }

  function change(mutator) {
    mutator();
    touched = true;
    render();
  }

  // --- presets ---------------------------------------------------------------------------

  function chorusId() {
    const choruses = sections.filter((s) => s.label === "chorus");
    return (choruses[choruses.length - 1] || sections[sections.length - 1] || {}).id;
  }

  const PRESETS = {
    "As written": () => asWritten(),
    "Start on the chorus": () => {
      const chorus = chorusId();
      return [{ section: chorus, mute: new Set(), drop: false }, ...asWritten()];
    },
    "Club mix": () => {
      // An intro of just the beat, the song with a drop into its first chorus, then a
      // breakdown and the chorus twice - the shape of most extended dance mixes.
      const chorus = chorusId();
      const first = sections[0].id;
      const out = [{ section: first, mute: new Set(STEMS), drop: false }];
      let dropped = false;
      for (const s of sections) {
        const isChorus = s.label === "chorus";
        out.push({ section: s.id, mute: new Set(), drop: isChorus && !dropped });
        if (isChorus) dropped = true;
      }
      out.push({ section: chorus, mute: new Set(["drums", "beat", "bass"]), drop: false });
      out.push({ section: chorus, mute: new Set(), drop: true });
      out.push({ section: chorus, mute: new Set(), drop: false });
      return out;
    },
  };

  // --- drawing -----------------------------------------------------------------------------

  function chip(label, on, title, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (on ? " on" : " off");
    b.textContent = label;
    b.title = title;
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.addEventListener("click", onClick);
    return b;
  }

  function small(label, title, onClick, disabled = false) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "small";
    b.textContent = label;
    b.title = title;
    b.setAttribute("aria-label", title);
    b.disabled = disabled;
    b.addEventListener("click", onClick);
    return b;
  }

  function previewUrl(id) {
    return `${API}/tracks/${state.trackId}/sections/${encodeURIComponent(id)}/preview`;
  }

  let playing = null;
  function play(id, button) {
    if (playing && !playing.audio.paused) {
      playing.audio.pause();
      playing.button.textContent = "▶";
      if (playing.id === id) {
        playing = null;
        return;
      }
    }
    const audio = new Audio(previewUrl(id));
    audio.play();
    button.textContent = "■";
    audio.onended = () => (button.textContent = "▶");
    playing = { id, audio, button };
  }

  function render() {
    const top = $("arrange-sections");
    const host = $("arrange-lane");
    if (!top || !host) return;

    top.innerHTML = "";
    for (const s of sections) {
      const block = document.createElement("div");
      block.className = `arrange-source group-${s.group}`;
      const go = small("▶", `Hear the ${s.label}`, () => play(s.id, go));
      const name = document.createElement("span");
      name.className = "arrange-name";
      name.textContent = `${s.group} · ${s.label} · bars ${s.start_bar}–${s.start_bar + s.bars - 1}`;
      const add = small("+ add", `Add the ${s.label} to the end`, () =>
        change(() => lane.push({ section: s.id, mute: new Set(), drop: false })));
      block.append(go, name, add);
      top.appendChild(block);
    }

    host.innerHTML = "";
    lane.forEach((item, i) => {
      const s = byId(item.section);
      if (!s) return;
      const row = document.createElement("li");
      row.className = `arrange-block group-${s.group}`;

      const head = document.createElement("div");
      head.className = "arrange-head";
      const name = document.createElement("span");
      name.className = "arrange-name";
      const allMuted = STEMS.every((stem) => item.mute.has(stem));
      const what = allMuted ? "beat only" : item.mute.has("drums") && item.mute.has("beat")
        ? "breakdown" : s.label;
      name.textContent = `${i + 1}. ${what} (${s.group}) · ${s.bars} bars`;
      head.append(
        name,
        small("▲", "Move earlier", () => change(() => lane.splice(i - 1, 0, ...lane.splice(i, 1))), i === 0),
        small("▼", "Move later", () => change(() => lane.splice(i + 1, 0, ...lane.splice(i, 1))), i === lane.length - 1),
        small("⧉", "Play it again straight after", () => change(() =>
          lane.splice(i + 1, 0, { section: item.section, mute: new Set(item.mute), drop: false }))),
        small("✕", "Take it out", () => change(() => lane.splice(i, 1)), lane.length === 1),
      );
      const drop = document.createElement("label");
      drop.className = "check small";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = item.drop;
      box.disabled = i === 0;
      box.title = i === 0 ? "A drop needs something before it to build from." : "";
      box.addEventListener("change", () => change(() => (item.drop = box.checked)));
      drop.append(box, document.createTextNode(" build up and drop into it"));
      head.appendChild(drop);

      const mutes = document.createElement("div");
      mutes.className = "arrange-mutes";
      for (const [id, label] of MUTABLE) {
        const on = !item.mute.has(id);
        mutes.appendChild(chip(label, on, on ? `Mute the ${label} in this block` : `Bring the ${label} back`,
          () => change(() => (on ? item.mute.add(id) : item.mute.delete(id)))));
      }
      row.append(head, mutes);
      host.appendChild(row);
    });

    // How long it is, in bars and in time at the version's tempo.
    const bars = lane.reduce((n, item) => n + (byId(item.section)?.bars || 0), 0);
    const target = parseFloat($("tempo-target")?.value) || tempo;
    const seconds = target ? (bars * 4 * 60) / target : 0;
    const m = Math.floor(seconds / 60);
    const sec = Math.round(seconds % 60).toString().padStart(2, "0");
    $("arrange-length").textContent = lane.length
      ? `${lane.length} blocks · ${bars} bars · about ${m}:${sec} at ${Math.round(target)} BPM` +
        (touched ? "" : " · as written")
      : "";

    // A drop per block replaces the single drop control once the order is the user's.
    const single = $("opt-drop");
    if (single) {
      single.closest("label").hidden = touched;
      $("drop-why").textContent = touched
        ? "Drops are set per block in the arrangement now."
        : $("drop-why").dataset.said || $("drop-why").textContent;
    }
  }

  /** Sprint 21: the song's parts, laid out as a recipe asks - some left out, some without the
   *  beat, a drop where a part comes back. Every block stays editable in the lane. */
  function applyPlan(plan) {
    if (!sections.length || !plan) return false;
    const skip = new Set((plan.skip || []).map((s) => s.toLowerCase()));
    const quiet = new Set((plan.subdued || []).map((s) => s.toLowerCase()));
    const dropAt = (plan.drop_at || "").toLowerCase();
    if (!skip.size && !quiet.size && !dropAt) return false;
    lane = [];
    let last = "";
    for (const s of sections) {
      const label = (s.label || "").toLowerCase();
      if (skip.has(label)) continue;
      const mute = quiet.has(label) ? new Set(["beat"]) : new Set();
      lane.push({ section: s.id, mute, drop: !!dropAt && label === dropAt && last !== label });
      last = label;
    }
    // The first block cannot drop - there is nothing before it to build from.
    if (lane.length) lane[0].drop = false;
    touched = true;
    render();
    return true;
  }

  /** Sprint 20: how many bars the version has - the arrangement's, else the song's. */
  function versionBars() {
    const order = touched && lane.length ? lane.map((item) => byId(item.section)) : sections;
    return order.filter(Boolean).reduce((sum, s) => sum + (s.bars || 0), 0);
  }

  /** Sprint 20: the version bars that start a block dropping in. */
  function dropBars() {
    if (!touched) return [];
    const out = [];
    let bar = 1;
    for (const item of lane) {
      if (item.drop) out.push(bar);
      bar += byId(item.section)?.bars || 0;
    }
    return out;
  }

  /** What the version request should carry: null while the song plays as written. */
  function request() {
    if (!touched || !lane.length) return null;
    return lane.map((item) => ({
      section: item.section, mute: [...item.mute], drop: !!item.drop,
    }));
  }

  function init() {
    const presets = $("arrange-presets");
    if (!presets || presets.dataset.wired) return;
    presets.dataset.wired = "yes";
    for (const [name, build] of Object.entries(PRESETS)) {
      presets.appendChild(small(name, `Arrange it as: ${name.toLowerCase()}`, () => {
        if (!sections.length) return;
        lane = build();
        touched = name !== "As written";
        render();
      }));
    }
    $("tempo-target")?.addEventListener("change", render);
    wireMarks();
  }

  // --- Sprint 13: marking the song's parts yourself ----------------------------------------

  const NAMES = ["intro", "verse", "pre-chorus", "chorus", "bridge", "drop", "breakdown", "outro"];
  let barDb = [];
  let detected = [];
  let marks = [];             // [{bar, label}], sorted by bar
  let listening = null;

  /** Which mark a bar falls under - the last one starting at or before it. */
  function markOf(bar) {
    let found = null;
    for (const m of marks) if (m.bar <= bar) found = m;
    return found;
  }

  function groupOf(label) {
    const names = [];
    for (const m of marks) if (!names.includes(m.label)) names.push(m.label);
    return String.fromCharCode(65 + Math.max(0, names.indexOf(label)));
  }

  function listen(bar, button) {
    if (listening) {
      listening.pause();
      listening = null;
    }
    const audio = new Audio(`${API}/tracks/${state.trackId}/listen?bar=${bar}&bars=4`);
    audio.play().catch(() => {});
    listening = audio;
    if (button) {
      button.textContent = "\u25A0";
      audio.onended = () => (button.textContent = "\u25B6");
    }
  }

  function drawMarks() {
    const strip = $("mark-strip");
    const list = $("mark-list");
    if (!strip || !list) return;
    marks.sort((a, b) => a.bar - b.bar);
    strip.innerHTML = "";
    const finite = barDb.filter((v) => v > -100);
    const lo = finite.length ? Math.min(...finite) : -60;
    const hi = finite.length ? Math.max(...finite) : 0;
    barDb.forEach((db, i) => {
      const bar = i + 1;
      const owner = markOf(bar);
      const b = document.createElement("button");
      b.type = "button";
      b.className = `mark-bar group-${owner ? groupOf(owner.label) : "F"}` +
        (marks.some((m) => m.bar === bar) ? " start" : "");
      const f = hi > lo ? (Math.max(lo, db) - lo) / (hi - lo) : 0.5;
      b.style.height = `${8 + f * 58}px`;
      b.title = `Bar ${bar}${owner ? ` - ${owner.label}` : ""}. Click to start a part here.`;
      b.setAttribute("aria-label", b.title);
      if ((bar - 1) % 4 === 0) {
        const num = document.createElement("span");
        num.className = "num";
        num.textContent = bar;
        b.appendChild(num);
      }
      b.addEventListener("click", () => {
        if (!marks.some((m) => m.bar === bar)) {
          // A new part, named after the next one a song usually has.
          const before = markOf(bar);
          const next = NAMES[(NAMES.indexOf(before?.label) + 1) % NAMES.length] || "verse";
          marks.push({ bar, label: next });
        }
        drawMarks();
        listen(bar);
      });
      strip.appendChild(b);
    });

    list.innerHTML = "";
    for (const m of marks) {
      const row = document.createElement("li");
      row.className = "mark-row";
      const where = document.createElement("span");
      where.className = "arrange-name";
      const next = marks.find((x) => x.bar > m.bar);
      // The last part ends on the song's last whole bar, as the sections above do; a partial
      // bar after it only rings out.
      const last = sections.length ? sections.at(-1).start_bar + sections.at(-1).bars - 1 : 0;
      const end = next ? next.bar - 1 : Math.max(m.bar, last || barDb.length);
      where.textContent = `Bars ${m.bar}-${end}`;
      const name = document.createElement("input");
      name.type = "text";
      name.maxLength = 24;
      name.value = m.label;
      name.setAttribute("aria-label", `Name of the part at bar ${m.bar}`);
      name.addEventListener("input", () => { m.label = name.value; });
      name.addEventListener("change", drawMarks);
      const play = document.createElement("button");
      play.type = "button";
      play.className = "small";
      play.textContent = "\u25B6";
      play.setAttribute("aria-label", `Hear bar ${m.bar}`);
      play.addEventListener("click", () => listen(m.bar, play));
      row.append(where, play, name);
      for (const n of NAMES) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip" + (m.label === n ? " on" : "");
        chip.textContent = n;
        chip.addEventListener("click", () => { m.label = n; drawMarks(); });
        row.appendChild(chip);
      }
      if (m.bar !== 1) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "small";
        remove.textContent = "\u2715";
        remove.setAttribute("aria-label", `Remove the part at bar ${m.bar}`);
        remove.addEventListener("click", () => {
          marks = marks.filter((x) => x !== m);
          drawMarks();
        });
        row.appendChild(remove);
      }
      list.appendChild(row);
    }
  }

  async function saveMarks() {
    const said = $("marks-said");
    try {
      await api(`/tracks/${state.trackId}/sections`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marks: marks.map((m) => ({ bar: m.bar, label: m.label.trim() || "section" })) }),
      });
      await load();
      said.textContent = "Saved. The arrangement now uses your parts.";
    } catch (error) {
      said.textContent = error.message || String(error);
    }
  }

  async function clearMarks() {
    try {
      await api(`/tracks/${state.trackId}/sections`, { method: "DELETE" });
      await load();
      $("marks-said").textContent = "Back to the detected parts.";
    } catch (error) {
      $("marks-said").textContent = error.message || String(error);
    }
  }

  function wireMarks() {
    $("marks-open")?.addEventListener("click", () => {
      const box = $("marks-box");
      box.hidden = !box.hidden;
      $("marks-open").textContent = box.hidden ? "Mark the parts yourself" : "Hide";
      drawMarks();
    });
    $("marks-save")?.addEventListener("click", saveMarks);
    $("marks-clear")?.addEventListener("click", clearMarks);
    $("marks-detected")?.addEventListener("click", () => {
      marks = detected.map((d) => ({ ...d }));
      drawMarks();
    });
  }

  return { init, load, reset, request, render, versionBars, dropBars, applyPlan };
})();

document.addEventListener("DOMContentLoaded", () => Arrange.init());
