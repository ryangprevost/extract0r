// ─────────────────────── play a part on something else ───────────────────────
//
// X0R-1327 and X0R-1328, with the MIDI download from X0R-503. Ryan: *"allow for replacing
// that midi with another instrument to play it"*, *"make the replacement previewable"*, and
// ultimately *"generate the wav of it to be included in the overall new master"*.
//
// **One row per part, because the first version was one dropdown.** Choosing a stem, then a
// voice, then pressing a button, then losing the answer when you chose the next stem, is
// auditioning an idea. A remix is several parts at once with the state of all of them
// visible, and closing that gap is what this file is for.
//
// **The honesty problem this screen has, and how it is handled.** Everything else in this
// application compares two recordings and reports a measurement. This takes a *guess* — a
// transcription — and plays it back as if it were fact. Measured through this app's own
// separation, that guess is good: recall 1.000, pitches as accurate as a clean DI. What it
// also is: over-complete. Separation breaks held notes into pieces and each piece arrives as
// its own note, precision 0.462 before repair and 0.727 after.
//
// So every row reports **how many fragments it merged** and **how many notes the voice could
// not reach**. Nobody can hear a precision figure, but "14 pieces rejoined" and "8 out of
// reach" are numbers a person can weigh when something sounds wrong.

const Revoice = (() => {
  //: Everything a part can be played on, fetched once. The page never offers a voice the
  //: renderer does not have.
  let voices = [];
  let samples = [];

  //: Per stem: {voice, notes, said, url, inMaster}. This is the version being built, and it
  //: is what `MasterRequest.revoice` reads. Kept here rather than on `state` because nothing
  //: else on the page has any business with it.
  const parts = new Map();

  //: Every part that can be re-played. Drums arrive through a different door - they are
  //: strokes rather than notes, so they take a kit rather than a voice - but they belong
  //: in the same list because to a person they are one of the parts.
  const PARTS = [
    ["drums", "Drums"],
    ["bass", "Bass"],
    ["guitar", "Guitar"],
    ["piano", "Piano"],
    ["vocals", "Vocals"],
    ["other", "The rest"],
  ];

  //: The three kits, which is what the drums row offers instead of voices.
  const KITS = ["edm", "tight", "roomy", "punchy"];

  //: The tempo this version is being built at, and the one it started from.
  let sourceBpm = 0;
  let targetBpm = null;

  function show() {
    const panel = $("revoice");
    if (!panel) return;
    panel.hidden = !(state.trackId && state.lanes && state.lanes.size);
    if (panel.hidden) return;
    if (!$("revoice-parts").children.length) render();
    // Gated on its own state, not on whether the rows exist. The first version keyed off
    // an empty parts list, so a `show()` that ran before `state.trackId` was set left the
    // tempo unread and every later call skipped it - the box simply never appeared.
    if (!sourceBpm) loadTempo();
  }

  function isSample(id) {
    return samples.some((s) => s.name === id);
  }

  function about(id, stem) {
    const voice = voices.find((v) => v.id === id);
    if (voice) return voice.about;
    const sample = samples.find((v) => v.name === id);
    if (!sample) return "";
    const base = sample.pitched
      ? "Your sample, transposed to follow the part."
      : "Your sample has no clear pitch, so it is triggered at its own pitch — a drum " +
        "machine rather than a sampler.";
    // X0R-1330: say before rendering that most of the part would be skipped, rather than
    // letting somebody wait for a render to find out.
    return [base, sample.reach?.[stem]].filter(Boolean).join(" ");
  }

  // --- one row per part ------------------------------------------------------------

  function row(stem, label) {
    const held = parts.get(stem) || {};
    const line = document.createElement("div");
    line.className = "part-row";
    line.dataset.stem = stem;

    const name = document.createElement("strong");
    name.textContent = label;
    line.appendChild(name);

    const pick = document.createElement("select");
    pick.appendChild(new Option("as recorded", ""));
    if (stem === "drums") {
      // A kit, not a voice: drums are struck rather than pitched, and offering a supersaw
      // here would be offering something the renderer cannot do with them.
      for (const kit of KITS) pick.appendChild(new Option(`${kit} kit`, kit));
    } else {
      for (const voice of voices) pick.appendChild(new Option(voice.label, voice.id));
      for (const sample of samples) {
        pick.appendChild(new Option(`${sample.name} (yours)`, sample.name));
      }
    }
    pick.value = held.voice || "";
    pick.addEventListener("change", () => choose(stem, pick.value));
    line.appendChild(pick);

    const play = document.createElement("button");
    play.className = "small";
    play.textContent = held.url ? "Again" : "Play it";
    play.disabled = !pick.value;
    play.addEventListener("click", () => run(stem));
    line.appendChild(play);

    const inMaster = document.createElement("label");
    inMaster.className = "check";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!held.inMaster;
    // Nothing can go into the master until it has been rendered: the pipeline substitutes
    // a file, and there is no file until the part has been played once. And not at all at a
    // new tempo - the mastering pipeline corrects the original recording, which only exists
    // at the original tempo. That case goes through Make the version instead.
    box.disabled = !held.url || !!targetBpm;
    if (targetBpm) {
      box.checked = false;
      inMaster.title = "At a new tempo, use Make the version below.";
    }
    box.addEventListener("change", () => {
      const now = parts.get(stem);
      if (now) now.inMaster = box.checked;
      summarise();
    });
    inMaster.appendChild(box);
    inMaster.appendChild(document.createTextNode(" in the master"));
    line.appendChild(inMaster);

    const said = document.createElement("span");
    said.className = "muted small part-said";
    said.textContent = held.said || "";
    line.appendChild(said);

    if (held.url) {
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.src = held.url;
      audio.className = "revoice-audio";
      line.appendChild(audio);
    }
    return line;
  }

  function render() {
    const host = $("revoice-parts");
    if (!host) return;
    host.innerHTML = "";
    for (const [stem, label] of PARTS) host.appendChild(row(stem, label));
    summarise();
  }

  function choose(stem, voice) {
    const held = parts.get(stem) || {};
    if (!voice) {
      parts.delete(stem);
    } else if (voice !== held.voice) {
      // A different voice invalidates the render on screen: that audio is of the old
      // voice, and leaving it playable is how somebody ships a mix against the wrong one.
      parts.set(stem, { voice });
    }
    $("revoice-about").textContent = voice ? about(voice, stem) : "";
    showRoot(voice);
    render();
  }

  function summarise() {
    const note = $("revoice-summary");
    if (!note) return;
    const chosen = [...parts.entries()].filter(([, v]) => v.inMaster && v.url);
    note.textContent = chosen.length
      ? "In the master: " +
        chosen.map(([s, v]) => `${s} on the ${v.voice}`).join(", ") +
        ". Render from the mastering page to hear it in the mix."
      : "";
  }

  // --- rendering one part ----------------------------------------------------------

  async function run(stem) {
    const held = parts.get(stem);
    if (!held?.voice) return;
    const wait = Waiting.begin($("revoice-working"), {
      headline: `Reading the notes out of your ${stem} and playing them on the ${held.voice}.`,
      // Not measured. Transcription cost has never been benchmarked on this path, and a
      // made-up estimate is worse than none - the bar would be lying rather than waiting.
      estimateSeconds: 0,
    });
    $("revoice-error").hidden = true;

    try {
      // A sample and a built-in voice go to the same endpoint by different parameters,
      // because they are the same request with a different source of sound.
      const what =
        stem === "drums"
          ? `kit=${encodeURIComponent(held.voice)}`
          : isSample(held.voice)
            ? `sample=${encodeURIComponent(held.voice)}`
            : `voice=${encodeURIComponent(held.voice)}`;
      // The tempo rides along with every part, so a version is at one tempo rather than
      // whatever each part happened to be rendered at.
      const at = targetBpm ? `&target_bpm=${targetBpm}` : "";
      const query = `stem=${stem}&${what}${at}`;
      const started = await api(`/tracks/${state.trackId}/revoice?${query}`, { method: "POST" });
      const result = (await pollJobQuietly(started.job_id, wait.stage)) || {};

      if (!result.notes) {
        held.said = result.why || "Nothing pitched came back from that part.";
        held.url = null;
        held.inMaster = false;
      } else {
        held.notes = result.notes;
        // Used as given. The server's path already starts at /api/v1 and `API` is that same
        // prefix, so concatenating them gave /api/v1/api/v1/... - a 404 and a player that
        // silently never loaded, with no error anywhere.
        held.url = result.url;
        held.said =
          `${result.notes} ${stem === "drums" ? "strokes" : "notes"}` +
          (result.fragments_merged ? `, ${result.fragments_merged} pieces rejoined` : "") +
          (result.out_of_range ? `, ${result.out_of_range} out of reach` : "") +
          (result.moved ? ` — ${result.moved}` : "");
        // Ticked by default only at the original tempo. At a new one the box is disabled,
        // and ticking it here anyway would slip a part into the master request that the
        // pipeline cannot use.
        held.inMaster = !targetBpm;
      }
      render();
    } catch (error) {
      fail("revoice-error", error);
    } finally {
      wait.done();
    }
  }

  // --- the tempo this version is at -------------------------------------------------
  //
  // Sprint 3. The confidence this is meant to give rests on one true sentence: **a
  // re-played part is not a stretched part.** A tempo change normally smears drums,
  // because a phase vocoder cannot keep a transient together; this re-strikes the kit at
  // new positions instead, so a 25% slowdown is as clean as the original. Measured: asking
  // for 90 BPM produced audio an independent tempo estimator reads as 89.1, with the same
  // detector finding 61 clean strokes where the original had 63.
  //
  // Saying that is the point of the panel, not decoration. Somebody who does not know what
  // a phase vocoder is still deserves to know why their drums survived.

  async function loadTempo() {
    const box = $("tempo-box");
    if (!box || !state.trackId) return;
    let info;
    try {
      info = await api(`/tracks/${state.trackId}/tempo`);
    } catch {
      return;
    }
    sourceBpm = info.tempo_bpm || 0;
    if (!sourceBpm) return;

    $("tempo-now").textContent = `This track runs at ${sourceBpm.toFixed(0)} BPM.`;
    const chips = $("tempo-chips");
    chips.innerHTML = "";
    for (const suggestion of info.suggestions || []) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = `${suggestion.label} · ${suggestion.bpm}`;
      chip.addEventListener("click", () => setTempo(suggestion.bpm));
      chips.appendChild(chip);
    }
    box.hidden = false;
    sayTempo();
  }

  function sayTempo() {
    const said = $("tempo-said");
    if (!said) return;
    if (!targetBpm || !sourceBpm) {
      said.textContent = "";
      return;
    }
    const scale = sourceBpm / targetBpm;
    if (scale < 0.5 || scale > 2) {
      said.textContent =
        `${sourceBpm.toFixed(0)} to ${targetBpm} BPM is more than this can move a part. ` +
        `It scales a performance between half and double its own tempo; past that the ` +
        `playing stops being the same playing.`;
      return;
    }
    const percent = Math.round(Math.abs(1 - 1 / scale) * 100);
    said.textContent =
      `${percent}% ${scale > 1 ? "slower" : "faster"}. Every part you re-play below is ` +
      `re-played at ${targetBpm} rather than stretched to it — the drums are struck again ` +
      `at the new spacing and the notes are played again at the new times, so nothing ` +
      `smears. Parts left as recorded stay at ${sourceBpm.toFixed(0)} and will not line up.`;
  }

  /**
   * The detected tempo was wrong; the person can hear the song and gets the last word.
   *
   * Offered as the four mistakes detectors actually make rather than as a blank box,
   * because "is it 85, 113 or 170?" is a question anyone can answer by tapping along, and
   * "type the tempo" is one most people cannot. X0R-1319 proved these confusions cannot
   * always be resolved from onsets, so this is the honest design rather than a workaround.
   */
  async function correctTempo(times) {
    if (!sourceBpm) return;
    const bpm = Math.round(sourceBpm * times * 10) / 10;
    try {
      const fixed = await api(`/tracks/${state.trackId}/tempo?bpm=${bpm}`, { method: "PUT" });
      sourceBpm = fixed.tempo_bpm;
      $("tempo-now").textContent =
        `This track runs at ${sourceBpm.toFixed(0)} BPM (you set this).`;
      // Every render was made against the old source tempo, so every one is now wrong.
      setTempo(targetBpm);
    } catch (error) {
      fail("revoice-error", error);
    }
  }

  function setTempo(bpm) {
    targetBpm = bpm || null;
    $("tempo-target").value = bpm || "";
    // Every existing render is at the old tempo. Keeping them playable would let somebody
    // build a version out of parts at two different tempos without being told.
    for (const [, held] of parts) {
      held.url = null;
      held.inMaster = false;
      held.said = "";
    }
    sayTempo();
    render();
  }

  // --- your own samples -------------------------------------------------------------

  function showRoot(voice) {
    const root = $("sample-root-row");
    if (!root) return;
    const sample = samples.find((s) => s.name === voice);
    root.hidden = !sample?.pitched;
    if (sample?.pitched) {
      root.dataset.sample = sample.name;
      $("sample-root").value = sample.root_midi ?? "";
      $("sample-root-name").textContent = sample.root_name ? `(${sample.root_name})` : "";
    }
  }

  async function refreshSamples() {
    try {
      samples = (await api("/tracks/samples")).samples || [];
    } catch {
      samples = [];
    }
    $("sample-list").textContent = samples.length
      ? `On this machine: ${samples.map((s) => s.name).join(", ")}.`
      : "";
    render();
  }

  async function uploadSample() {
    const button = $("sample-upload");
    const file = $("sample-file").files[0];
    const name = $("sample-name").value.trim();
    const box = $("revoice-error");
    box.hidden = true;

    if (!file || !name) {
      box.textContent = "A name and a file, both.";
      box.hidden = false;
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    form.append("owns_or_licensed", $("sample-rights").checked ? "true" : "false");

    button.disabled = true;
    try {
      await api("/tracks/samples", { method: "POST", body: form });
      await refreshSamples();
      $("sample-name").value = "";
      $("sample-file").value = "";
    } catch (error) {
      fail("revoice-error", error);
    } finally {
      button.disabled = false;
    }
  }

  /** Tell a sample what note it is, then re-read the list so the forecast updates. */
  async function setRoot() {
    const name = $("sample-root-row").dataset.sample;
    const value = $("sample-root").value;
    if (!name) return;
    try {
      await api(
        `/tracks/samples/${encodeURIComponent(name)}` + (value ? `?root_midi=${value}` : ""),
        { method: "PATCH" },
      );
      await refreshSamples();
      showRoot(name);
    } catch (error) {
      fail("revoice-error", error);
    }
  }

  /**
   * The MIDI, which is the hand-off out of this application.
   *
   * Deliberately a plain download and not a preview. What a person does with MIDI is open
   * it somewhere that can re-sequence and re-tempo it — the two things this project has
   * twice decided it should not do itself, because moving a user's kick to where a
   * reference's kick sits is composition rather than mastering. Handing over the notes is
   * how both of those stay true at once.
   */
  async function midi() {
    const button = $("midi-btn");
    button.disabled = true;
    const was = button.textContent;
    button.textContent = "Reading every part…";
    try {
      const response = await fetch(`${API}/tracks/${state.trackId}/midi`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `${response.status}`);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${state.trackId.slice(0, 8)}.mid`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      fail("revoice-error", error);
    } finally {
      button.disabled = false;
      button.textContent = was;
    }
  }

  // --- the version, as one file ---------------------------------------------------

  /**
   * Sum everything at the chosen tempo and hand back a file.
   *
   * What comes back is shown as the account the server keeps, not as a reassurance: which
   * parts were re-played, which stretched, and - when the drums were stretched - what to do
   * about it. The first version of the server's summary said "nothing is smeared" over a
   * bounce where five of six parts had been stretched, and a false reassurance is worse
   * than none for a screen whose job is to make somebody trust what they made.
   */
  async function makeVersion() {
    const button = $("bounce-btn");
    const host = $("bounce-result");
    const wait = Waiting.begin($("revoice-working"), {
      headline: targetBpm
        ? `Building your ${targetBpm} BPM version.`
        : "Building your version.",
      estimateSeconds: 0,
    });
    $("revoice-error").hidden = true;
    button.disabled = true;
    host.innerHTML = "";

    const replayed = {};
    for (const [stem, held] of parts) if (held.url) replayed[stem] = held.voice;

    try {
      const started = await api(`/tracks/${state.trackId}/bounce`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_bpm: targetBpm,
          parts: replayed,
          pump: !!$("opt-pump")?.checked,
          four_on_the_floor: !!$("opt-floor")?.checked,
        }),
      });
      const result = (await pollJobQuietly(started.job_id, wait.stage)) || {};

      if (!result.ok) {
        // A part rendered at another tempo. The message names it and says what to press,
        // which is the useful version of an error.
        fail("revoice-error", new Error(result.why || "The version could not be built."));
        return;
      }

      const head = document.createElement("p");
      head.className = "bounce-head";
      head.textContent = `${result.headline} ${result.duration_s} seconds.`;
      host.appendChild(head);
      for (const text of result.lines || []) {
        const line = document.createElement("p");
        line.className = "muted small";
        line.textContent = text;
        host.appendChild(line);
      }
      if (result.tip) {
        const tip = document.createElement("p");
        tip.className = "bounce-tip small";
        tip.textContent = result.tip;
        host.appendChild(tip);
      }

      const audio = document.createElement("audio");
      audio.controls = true;
      audio.src = result.mp3;
      audio.className = "revoice-audio";
      host.appendChild(audio);

      const links = document.createElement("p");
      links.className = "small";
      links.innerHTML =
        `<a href="${result.mp3}" download>Download MP3</a> · ` +
        `<a href="${result.wav}" download>Download WAV (24-bit)</a>`;
      host.appendChild(links);

      const note = document.createElement("p");
      note.className = "muted tiny";
      note.textContent = result.note || "";
      host.appendChild(note);
    } catch (error) {
      fail("revoice-error", error);
    } finally {
      wait.done();
      button.disabled = false;
    }
  }

  // --- one press to a remix ----------------------------------------------------------

  //: What "make it EDM" chooses for each part. Every choice lands in its row afterwards, so
  //: the preset teaches rather than hides: somebody can see that the guitars became a pluck
  //: and change it to a pad. Vocals stay as recorded - stretched, because a voice is the
  //: one part nobody wants replaced by a synth playing its notes.
  const EDM = {
    tempo: 128,
    parts: { drums: "edm", bass: "808", guitar: "pluck", piano: "pad", other: "pad" },
  };

  /**
   * Choose, render and bounce in one go.
   *
   * Parts with nothing pitched in them come back empty and are simply stretched instead -
   * a song with no piano should not fail because the preset asked for a piano pad.
   */
  async function makeItEdm() {
    const button = $("preset-edm");
    button.disabled = true;
    const was = button.textContent;
    try {
      setTempo(EDM.tempo);
      for (const [stem, voice] of Object.entries(EDM.parts)) {
        parts.set(stem, { voice });
      }
      render();
      for (const stem of Object.keys(EDM.parts)) {
        button.textContent = `Playing the ${stem}…`;
        await run(stem);
      }
      $("opt-pump").checked = true;
      $("opt-floor").checked = true;
      button.textContent = "Putting it together…";
      await makeVersion();
    } finally {
      button.disabled = false;
      button.textContent = was;
    }
  }

  /** What the master render should substitute, for whoever builds that request. */
  function chosen() {
    const out = {};
    for (const [stem, held] of parts) {
      if (held.inMaster && held.url) out[stem] = held.voice;
    }
    return out;
  }

  /** A new track is a new version; nothing from the last one should survive into it. */
  function reset() {
    parts.clear();
    render();
  }

  async function init() {
    const host = $("revoice-parts");
    if (!host || host.dataset.wired) return;
    host.dataset.wired = "yes";
    $("midi-btn")?.addEventListener("click", midi);
    $("sample-upload")?.addEventListener("click", uploadSample);
    $("sample-root-set")?.addEventListener("click", setRoot);
    $("tempo-target")?.addEventListener("change", (e) =>
      setTempo(parseInt(e.target.value, 10) || null),
    );
    $("tempo-clear")?.addEventListener("click", () => setTempo(null));
    $("bounce-btn")?.addEventListener("click", makeVersion);
    $("preset-edm")?.addEventListener("click", makeItEdm);
    for (const chip of document.querySelectorAll("#tempo-fix .chip")) {
      chip.addEventListener("click", () => correctTempo(parseFloat(chip.dataset.times)));
    }
    try {
      voices = (await api("/tracks/voices")).voices || [];
    } catch {
      voices = [];
    }
    await refreshSamples();
  }

  return { init, show, chosen, reset };
})();

document.addEventListener("DOMContentLoaded", () => Revoice.init());
