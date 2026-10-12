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
  }

  return { init, load, reset, request, render };
})();

document.addEventListener("DOMContentLoaded", () => Arrange.init());
