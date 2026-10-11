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

  //: Which stems can be played from notes. Drums are absent on purpose: they are not one
  //: pitched part, and the per-drum panel above already does the drum-level work.
  const PARTS = [
    ["bass", "Bass"],
    ["guitar", "Guitar"],
    ["piano", "Piano"],
    ["vocals", "Vocals"],
    ["other", "The rest"],
  ];

  function show() {
    const panel = $("revoice");
    if (!panel) return;
    panel.hidden = !(state.trackId && state.lanes && state.lanes.size);
    if (!panel.hidden && !$("revoice-parts").children.length) render();
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
    for (const voice of voices) pick.appendChild(new Option(voice.label, voice.id));
    for (const sample of samples) {
      pick.appendChild(new Option(`${sample.name} (yours)`, sample.name));
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
    // a file, and there is no file until the part has been played once.
    box.disabled = !held.url;
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
      const query = isSample(held.voice)
        ? `stem=${stem}&sample=${encodeURIComponent(held.voice)}`
        : `stem=${stem}&voice=${encodeURIComponent(held.voice)}`;
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
          `${result.notes} notes` +
          (result.fragments_merged ? `, ${result.fragments_merged} pieces rejoined` : "") +
          (result.out_of_range ? `, ${result.out_of_range} out of reach` : "");
        held.inMaster = true;
      }
      render();
    } catch (error) {
      fail("revoice-error", error);
    } finally {
      wait.done();
    }
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
