// ─────────────────────── play a part on something else ───────────────────────
//
// X0R-1327, and the MIDI download from X0R-503. Ryan: *"allow for replacing that midi with
// another instrument to play it"* and *"make the replacement previewable"*.
//
// **The honesty problem this screen has, and how it is handled.** Everything else in this
// application compares two recordings and reports a measurement. This takes a *guess* — a
// transcription — and plays it back as if it were fact. Measured through this app's own
// separation, that guess is good: recall 1.000, pitches as accurate as a clean DI. What it
// also is: over-complete. Separation breaks held notes into pieces and each piece arrives
// as its own note, precision 0.462 before repair and 0.727 after.
//
// So the panel reports **how many fragments it merged**, every time. Nobody can hear a
// precision figure, but "put 14 pieces back together" is a number a person can weigh when
// something sounds wrong — and it is the difference between a tool that admits it is
// inferring and one that quietly presents a guess as a reading.

const Revoice = (() => {
  //: Filled from the server, so the page never invents a voice the renderer does not have.
  let voices = [];

  function show() {
    const panel = $("revoice");
    if (!panel) return;
    panel.hidden = !(state.trackId && state.lanes && state.lanes.size);
  }

  function describe() {
    const picked = voices.find((v) => v.id === $("revoice-voice").value);
    $("revoice-about").textContent = picked ? picked.about : "";
  }

  async function loadVoices() {
    const select = $("revoice-voice");
    if (!select || select.options.length) return;
    try {
      voices = (await api("/tracks/voices")).voices || [];
    } catch {
      return;
    }
    for (const voice of voices) {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = voice.label;
      select.appendChild(option);
    }
    describe();
  }

  /** What the run actually did, in the terms a person can act on. */
  function report(result) {
    const host = $("revoice-result");
    host.innerHTML = "";

    if (!result.notes) {
      host.appendChild(line(result.why || "Nothing pitched came back from that part."));
      return;
    }

    const said = document.createElement("p");
    said.className = "muted small";
    said.textContent =
      `${result.notes} notes read out of your ${result.stem}, played on the ` +
      `${result.voice}.` +
      (result.fragments_merged
        ? ` ${result.fragments_merged} of them arrived split into pieces by the ` +
          `separation and were put back together first.`
        : "");
    host.appendChild(said);

    const audio = document.createElement("audio");
    audio.controls = true;
    // Not `API + result.url`. The server hands back a path that already starts at
    // /api/v1, and `API` is that same prefix - concatenating them produced
    // /api/v1/api/v1/... and a preview that silently never loaded.
    audio.src = result.url;
    audio.className = "revoice-audio";
    host.appendChild(audio);

    // A reminder rather than a disclaimer. This is a transcription being played back, and
    // the one way to know whether it held is to listen to both.
    const compare = document.createElement("p");
    compare.className = "muted small";
    compare.textContent =
      "Worth hearing against the stem it came from — these are the notes this app thinks " +
      "you played, not the recording of you playing them.";
    host.appendChild(compare);
  }

  function line(text) {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = text;
    return p;
  }

  async function run() {
    const button = $("revoice-btn");
    const stem = $("revoice-stem").value;
    const voice = $("revoice-voice").value;
    const wait = Waiting.begin($("revoice-working"), {
      headline: `Reading the notes out of your ${stem} and playing them on the ${voice}.`,
      // Not measured. Transcription cost has never been benchmarked on this path, and a
      // made-up estimate is worse than none - the bar would be lying rather than waiting.
      estimateSeconds: 0,
    });
    $("revoice-error").hidden = true;
    button.disabled = true;

    try {
      const started = await api(
        `/tracks/${state.trackId}/revoice?stem=${stem}&voice=${voice}`,
        { method: "POST" },
      );
      // `pollJobQuietly` rather than `runJob`: this is a panel with its own progress line,
      // not a full-screen step, and it is what the groove and drum panels already use.
      report(await pollJobQuietly(started.job_id, wait.stage));
    } catch (error) {
      fail("revoice-error", error);
    } finally {
      wait.done();
      button.disabled = false;
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
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
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

  function init() {
    const button = $("revoice-btn");
    if (!button || button.dataset.wired) return;
    button.dataset.wired = "yes";
    button.addEventListener("click", run);
    $("midi-btn")?.addEventListener("click", midi);
    $("revoice-voice")?.addEventListener("change", describe);
    loadVoices();
  }

  return { init, show };
})();

document.addEventListener("DOMContentLoaded", () => Revoice.init());
