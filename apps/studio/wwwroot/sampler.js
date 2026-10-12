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
      said.textContent = `Made "${made.label}" from ${picks.length} note` +
        `${picks.length === 1 ? "" : "s"}. Pick it as the sound on any part above, then ` +
        `play the part. A version made with it will say the sound came from your reference.`;
    } catch (error) {
      said.textContent = error.message || String(error);
    } finally {
      button.disabled = false;
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
    api("/legal").then((legal) => {
      if (legal.sampling_notice) $("sampler-notice").textContent = legal.sampling_notice;
    }).catch(() => {});
  }

  return { init, reset };
})();

document.addEventListener("DOMContentLoaded", () => Sampler.init());
