// The club finish: a version made loud enough to play out. Sprint 23.
//
// Through Sprints 16-22 every remix Ryan was sent had been finished by a script outside the
// app, because the bounce stops at a sketch and the mastering page is about matching a
// reference's tone rather than reaching a club's loudness. This is that step, in the app:
// pick how loud, press it, hear what it cost. The version itself is left alone beside it.

const Finish = (() => {
  let last = null;

  function label() {
    return typeof Mixer !== "undefined" && Mixer.label ? Mixer.label() : null;
  }

  async function run() {
    const version = label();
    const host = $("finish-result");
    const button = $("finish-btn");
    if (!version || !state.trackId) {
      host.textContent = "Make a version first - this finishes what the bounce wrote.";
      return;
    }
    const wait = Waiting.begin($("finish-working"), {
      headline: "Gluing, clipping and limiting your version.",
      estimateSeconds: 0,
    });
    button.disabled = true;
    host.innerHTML = "";
    try {
      const started = await api(`/tracks/${state.trackId}/version/${version}/finish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target: $("finish-target").value,
          match_reference: !!$("finish-match").checked,
        }),
      });
      const result = (await pollJobQuietly(started.job_id, wait.stage)) || {};
      last = result;
      for (const text of result.lines || []) {
        const line = document.createElement("p");
        line.className = "muted small";
        line.textContent = text;
        host.appendChild(line);
      }
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.src = `${result.mp3}?t=${Date.now()}`;
      audio.className = "revoice-audio";
      host.appendChild(audio);
      const links = document.createElement("p");
      links.className = "small";
      links.innerHTML = `<a href="${result.mp3}" download>Download MP3</a> · ` +
        `<a href="${result.wav}" download>Download WAV (24-bit)</a>`;
      host.appendChild(links);
      const note = document.createElement("p");
      note.className = "muted tiny";
      note.textContent = result.note || "";
      host.appendChild(note);
    } catch (error) {
      host.textContent = error.message || String(error);
    } finally {
      wait.done();
      button.disabled = false;
    }
  }

  function reset() {
    last = null;
    if ($("finish-result")) $("finish-result").innerHTML = "";
  }

  function init() {
    if (!$("finish-btn") || $("finish-btn").dataset.wired) return;
    $("finish-btn").dataset.wired = "yes";
    $("finish-btn").addEventListener("click", run);
  }

  return { init, reset, latest: () => last };
})();

document.addEventListener("DOMContentLoaded", () => Finish.init());
