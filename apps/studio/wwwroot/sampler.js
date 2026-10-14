// Sampling a sound from the reference, to play your parts on. Sprint 15.
//
// Ryan, 2026-10-12: "not loving the synth sounds honestly. can you allow for sampling a note
// of a synth in the reference and applying that to the midi? thatd be huge."
//
// Pick one of the reference's separated parts, find its clean notes, listen to each one as
// it would be sampled (cut, tuned, held), tick the ones to keep and say you may sample the
// recording. They become an instrument in every part's sound list, named for the reference.
// The one place extract0r samples a reference - only when asked, and it says so.

const Sampler = (() => {
  let found = [];
  let stem = "other";
  let playing = null;
  let playingButton = null;

  function stop() {
    if (playing) playing.pause();
    playing = null;
    playingButton = null;
  }

  /** Play a candidate; pressing its button again stops it. */
  function play(url, button) {
    const same = playingButton === button;
    stop();
    if (same) return;
    const audio = new Audio(url);
    audio.play().catch(() => {});
    playing = audio;
    playingButton = button;
    button.textContent = "■";
    audio.onended = audio.onpause = () => (button.textContent = "▶");
  }

  function describe(c) {
    const held = c.sample_s >= 1 ? `holds ${c.sample_s.toFixed(1)} s`
      : `short (${c.sample_s.toFixed(2)} s) - for short notes`;
    const tuned = Math.abs(c.cents) >= 3
      ? `, tuned ${c.cents > 0 ? "down" : "up"} ${Math.abs(c.cents).toFixed(0)} cents` : "";
    return `at ${fmt(c.start_s)} · ${held}${tuned}`;
  }

  function fmt(s) {
    const m = Math.floor(s / 60);
    return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  }

  function render() {
    const list = $("sampler-list");
    list.innerHTML = "";
    for (const c of found) {
      const row = document.createElement("li");
      row.className = "sampler-row";
      const pick = document.createElement("input");
      pick.type = "checkbox";
      pick.value = c.n;
      // The good ones start ticked: clean, and long enough to hold a note.
      pick.checked = c.clarity >= 0.7 && c.sample_s >= 0.4;
      pick.setAttribute("aria-label", `Use ${c.name}`);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "small";
      button.textContent = "▶";
      button.setAttribute("aria-label", `Hear ${c.name} as sampled`);
      button.addEventListener("click", () => play(c.url, button));
      const name = document.createElement("strong");
      name.textContent = c.name;
      const meter = document.createElement("span");
      meter.className = "sampler-meter";
      meter.title = `Clarity ${(c.clarity * 100).toFixed(0)}%: one pitch at a time, steady ` +
        `(${c.wander_cents.toFixed(0)} cents of wander), ` +
        `${(c.harmonicity * 100).toFixed(0)}% of its sound on its own harmonics`;
      meter.style.setProperty("--fill", `${Math.round(c.clarity * 100)}%`);
      const about = document.createElement("span");
      about.className = "muted small";
      about.textContent = describe(c);
      row.append(pick, button, name, meter, about);
      list.appendChild(row);
    }
    $("sampler-make-row").hidden = !found.length;
  }

  async function find() {
    if (!state.trackId) return;
    stem = $("sampler-stem").value;
    const button = $("sampler-find");
    const said = $("sampler-said");
    button.disabled = true;
    found = [];
    render();
    try {
      const started = await api(`/tracks/${state.trackId}/reference/notes?stem=${stem}`,
        { method: "POST" });
      const result = (await pollJobQuietly(started.job_id, (job) => {
        said.textContent = job.message ? `${job.message}…` : "Working…";
      })) || {};
      found = result.candidates || [];
      said.textContent = result.note || "";
      render();
    } catch (error) {
      said.textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  async function make() {
    const picks = [...document.querySelectorAll("#sampler-list input:checked")]
      .map((box) => Number(box.value));
    const said = $("sampler-made");
    if (!picks.length) {
      said.textContent = "Tick at least one note to sample.";
      return;
    }
    if (!$("sampler-rights").checked) {
      said.textContent = "Tick the box to say you may sample this recording first.";
      return;
    }
    const button = $("sampler-make");
    button.disabled = true;
    try {
      const made = await api(`/tracks/${state.trackId}/reference/sampled`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stem, picks, name: $("sampler-name").value, may_sample: true,
        }),
      });
      if (typeof Revoice !== "undefined") await Revoice.refreshSounds();
      await listSounds();
      said.textContent = `Made "${made.label}" from ${picks.length} note` +
        `${picks.length === 1 ? "" : "s"}. Pick it as the sound on any part above, then ` +
        `play the part. A version made with it will say the sound came from your reference.`;
    } catch (error) {
      said.textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  // --- Sprint 22: tuning a sampled sound ----------------------------------------------------

  //: [setting, label, min, max, step, no-change value, how to say it]
  const KNOBS = [
    ["semitones", "Pitch", -12, 12, 1, 0, (v) => `${v > 0 ? "+" : ""}${v} st`],
    ["cents", "Fine tune", -50, 50, 1, 0, (v) => `${v > 0 ? "+" : ""}${v} cents`],
    ["start_ms", "Start", 0, 300, 5, 0, (v) => (v ? `${v} ms in` : "from the top")],
    ["attack_ms", "Attack", 0, 500, 5, 0, (v) => (v ? `${v} ms fade in` : "as recorded")],
    ["max_s", "Length", 0, 3, 0.05, 0, (v) => (v ? `${v.toFixed(2)} s at most` : "as played")],
    ["release_ms", "Release", -10, 2000, 10, -10,
      (v) => (v < 0 ? "natural" : `${v} ms`)],
    ["low_cut_hz", "Low cut", 0, 1000, 10, 0, (v) => (v ? `${v} Hz` : "off")],
    ["high_cut_hz", "High cut", 0, 20000, 100, 0, (v) => (v ? `${v} Hz` : "off")],
    ["bass_db", "Bass", -12, 12, 0.5, 0, (v) => `${v > 0 ? "+" : ""}${v} dB`],
    ["treble_db", "Treble", -12, 12, 0.5, 0, (v) => `${v > 0 ? "+" : ""}${v} dB`],
  ];
  let previewTimer = null;

  function knobValues(box) {
    const out = {};
    for (const input of box.querySelectorAll("input[data-knob]")) {
      let v = Number(input.value);
      if (input.dataset.knob === "release_ms" && v < 0) v = -1;
      out[input.dataset.knob] = v;
    }
    return out;
  }

  async function previewTweak(id, box) {
    const said = box.querySelector(".tune-said");
    try {
      const response = await fetch(`${API}/tracks/instruments/${encodeURIComponent(id)}/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(knobValues(box)),
      });
      if (!response.ok) throw new Error(await response.text());
      stop();
      const audio = new Audio(URL.createObjectURL(await response.blob()));
      audio.play().catch(() => {});
      playing = audio;
      said.textContent = "";
    } catch (error) {
      said.textContent = error.message || String(error);
    }
  }

  function tunePanel(voice) {
    const box = document.createElement("div");
    box.className = "tune-box";
    for (const [knob, label, min, max, step, neutral, words] of KNOBS) {
      const row = document.createElement("label");
      row.className = "tune-row";
      const input = document.createElement("input");
      input.type = "range";
      input.min = min;
      input.max = max;
      input.step = step;
      input.dataset.knob = knob;
      const kept = voice.tweak?.[knob];
      input.value = kept === undefined ? neutral : (knob === "release_ms" && kept < 0 ? -10 : kept);
      const value = document.createElement("span");
      value.className = "muted small";
      const sayIt = () => { value.textContent = words(Number(input.value)); };
      sayIt();
      input.addEventListener("input", () => {
        sayIt();
        clearTimeout(previewTimer);
        previewTimer = setTimeout(() => previewTweak(voice.id, box), 350);
      });
      row.append(label, input, value);
      box.appendChild(row);
    }
    const buttons = document.createElement("div");
    buttons.className = "preset-row";
    const hear = document.createElement("button");
    hear.type = "button";
    hear.className = "small";
    hear.textContent = "\u25B6 Hear it";
    hear.addEventListener("click", () => previewTweak(voice.id, box));
    const keep = document.createElement("button");
    keep.type = "button";
    keep.className = "primary small";
    keep.textContent = "Keep";
    const replay = document.createElement("button");
    replay.type = "button";
    replay.className = "small";
    replay.textContent = "Play the parts on it again";
    replay.hidden = true;
    const back = document.createElement("button");
    back.type = "button";
    back.className = "small";
    back.textContent = "Reset";
    const said = document.createElement("span");
    said.className = "muted small tune-said";
    async function save(values) {
      const kept = await api(`/tracks/instruments/${encodeURIComponent(voice.id)}/tweak`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      voice.tweak = kept.tweak;
      said.textContent = kept.said;
      replay.hidden = false;
    }
    keep.addEventListener("click", () => save(knobValues(box)).catch((e) => {
      said.textContent = e.message || String(e);
    }));
    back.addEventListener("click", async () => {
      for (const input of box.querySelectorAll("input[data-knob]")) {
        const [, , , , , neutral] = KNOBS.find(([k]) => k === input.dataset.knob);
        input.value = neutral;
        input.dispatchEvent(new Event("input"));
      }
      clearTimeout(previewTimer);
      await save({}).catch((e) => { said.textContent = e.message || String(e); });
    });
    replay.addEventListener("click", async () => {
      if (typeof Revoice === "undefined") return;
      replay.disabled = true;
      said.textContent = "Playing the parts on it again\u2026";
      const n = await Revoice.replayOn(voice.id);
      said.textContent = n ? `Played ${n} part${n === 1 ? "" : "s"} again - make the version ` +
        "to hear it in the song." : "No part is on this sound yet - pick it on a part above.";
      replay.disabled = false;
    });
    buttons.append(hear, keep, back, replay, said);
    box.appendChild(buttons);
    return box;
  }

  async function listSounds() {
    const list = $("sampler-sounds");
    if (!list || !state.trackId) return;
    let voices = [];
    try {
      voices = (await api("/tracks/voices")).voices || [];
    } catch {
      return;
    }
    const mine = voices.filter((v) => v.origin === "reference" && v.track_id === state.trackId);
    list.innerHTML = "";
    $("sampler-sounds-none").hidden = mine.length > 0;
    for (const voice of mine) {
      const item = document.createElement("li");
      const head = document.createElement("div");
      head.className = "sampler-row";
      const name = document.createElement("strong");
      name.textContent = voice.label;
      const tune = document.createElement("button");
      tune.type = "button";
      tune.className = "small";
      tune.textContent = Object.keys(voice.tweak || {}).length ? "Tune (tuned)" : "Tune";
      let panel = null;
      tune.addEventListener("click", () => {
        if (panel) {
          panel.remove();
          panel = null;
          return;
        }
        panel = tunePanel(voice);
        item.appendChild(panel);
      });
      head.append(name, tune);
      item.appendChild(head);
      list.appendChild(item);
    }
  }

  function reset() {
    stop();
    found = [];
    if ($("sampler-list")) render();
    if ($("sampler-said")) $("sampler-said").textContent = "";
    if ($("sampler-made")) $("sampler-made").textContent = "";
  }

  function init() {
    if (!$("sampler-find")) return;
    $("sampler-find").addEventListener("click", find);
    $("sampler-make").addEventListener("click", make);
    $("sampler-box")?.addEventListener("toggle", () => {
      if ($("sampler-box").open) listSounds();
    });
    api("/legal").then((legal) => {
      if (legal.sampling_notice) $("sampler-notice").textContent = legal.sampling_notice;
    }).catch(() => {});
  }

  return { init, reset, listSounds };
})();

document.addEventListener("DOMContentLoaded", () => Sampler.init());
