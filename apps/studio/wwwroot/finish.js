// The club finish: a version made loud enough to play out. Sprint 23.
//
// Through Sprints 16-22 every remix Ryan was sent had been finished by a script outside the
// app, because the bounce stops at a sketch and the mastering page is about matching a
// reference's tone rather than reaching a club's loudness. This is that step, in the app:
// pick how loud, press it, hear what it cost. The version itself is left alone beside it.

const Finish = (() => {
  let last = null;
  //: Sprint 24 (X0R-804): the two files, playing together, one of them audible. Switching is
  //: instant and in the same place in the song, and the louder one is turned down to the
  //: quieter one's loudness - otherwise louder always "wins", which is the oldest trap in
  //: mastering.
  let pair = null;      // {version: {audio, gain}, master: {...}, hearing: "master"}
  //: What the canvas is currently showing, so it can be drawn again at a new size.
  let shown = null;

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
      // Straight into the honest comparison: the two at the same loudness.
      await compare();
    } catch (error) {
      host.textContent = error.message || String(error);
    } finally {
      wait.done();
      button.disabled = false;
    }
  }

  function stopPair() {
    if (!pair) return;
    for (const side of ["version", "master"]) pair[side]?.audio.pause();
    pair = null;
  }

  function hear(which) {
    if (!pair) return;
    pair.hearing = which;
    for (const side of ["version", "master"]) {
      const held = pair[side];
      if (held) held.audio.volume = side === which ? held.gain : 0;
    }
    for (const button of document.querySelectorAll("[data-ab]")) {
      button.classList.toggle("on", button.dataset.ab === which);
    }
    $("ab-said").textContent = which === "master"
      ? "Hearing the master." : "Hearing the version, at the master's loudness.";
  }

  /** The two files, loudness-matched, started together and kept together. */
  async function buildPair(meters) {
    stopPair();
    const made = { hearing: "master" };
    for (const side of ["version", "master"]) {
      const m = meters[side];
      if (!m) continue;
      const audio = new Audio(`${m.mp3}?t=${Date.now()}`);
      audio.preload = "auto";
      audio.volume = 0;
      made[side] = { audio, gain: Math.min(1, 10 ** ((m.match_db || 0) / 20)) };
    }
    pair = made;
  }

  function meterLines(meters) {
    const host = document.createElement("div");
    for (const [side, m] of Object.entries(meters)) {
      const name = side === "master" ? "The master" : "The version";
      const line = document.createElement("p");
      line.className = "muted small";
      const range = m.loudness_range_lu === null
        ? "its loudness range could not be measured (too short)"
        : `loudness range ${m.loudness_range_lu} LU`;
      line.textContent = `${name}: ${m.integrated_lufs} LUFS, true peak ` +
        `${m.true_peak_dbtp} dBTP, ${range}.`;
      host.appendChild(line);
      for (const text of m.said || []) {
        const warn = document.createElement("p");
        warn.className = "bounce-tip small";
        warn.textContent = `${name}: ${text}`;
        host.appendChild(warn);
      }
    }
    return host;
  }

  /** Short-term loudness for each, and the phase correlation under it. */
  function drawMeters(meters) {
    const canvas = $("ab-canvas");
    if (!canvas) return;
    shown = meters;
    const width = canvas.clientWidth || 600;
    const height = 120;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    canvas.style.height = `${height}px`;
    const g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    const css = (name) => getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim() || "#888";
    g.fillStyle = css("--panel-2");
    g.fillRect(0, 0, width, height);
    const series = Object.values(meters);
    const span_s = Math.max(...series.map((m) => m.times[m.times.length - 1] || 1));
    const loudTop = -3;
    const loudFloor = -30;
    const loudY = (v) => 8 + (loudTop - Math.max(loudFloor, v)) / (loudTop - loudFloor) * 70;
    // Loudness guides at -9 (club) and -14 (streaming).
    g.font = "10px ui-monospace, monospace";
    for (const mark of [-9, -14]) {
      g.strokeStyle = css("--edge");
      g.beginPath();
      g.moveTo(0, loudY(mark) + 0.5);
      g.lineTo(width, loudY(mark) + 0.5);
      g.stroke();
      g.fillStyle = css("--muted");
      g.fillText(`${mark}`, 2, loudY(mark) - 2);
    }
    const colors = { version: css("--muted"), master: css("--accent") };
    for (const [side, m] of Object.entries(meters)) {
      g.strokeStyle = colors[side];
      g.lineWidth = side === "master" ? 2 : 1;
      g.beginPath();
      m.times.forEach((time, i) => {
        const x = (time / span_s) * width;
        const y = loudY(m.short_term[i]);
        if (i === 0) g.moveTo(x, y);
        else g.lineTo(x, y);
      });
      g.stroke();
    }
    // Correlation, in its own strip: +1 at the top, -1 at the bottom, zero marked.
    const base = 88;
    const span = 28;
    g.strokeStyle = css("--edge");
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(0, base + span / 2 + 0.5);
    g.lineTo(width, base + span / 2 + 0.5);
    g.stroke();
    const phased = meters.master || meters.version;
    phased.times.forEach((time, i) => {
      const value = phased.correlation[i];
      const x = (time / span_s) * width;
      const y = base + span / 2 - (value * span) / 2;
      g.strokeStyle = value < 0 ? css("--warn") : colors[meters.master ? "master" : "version"];
      g.beginPath();
      g.moveTo(x, base + span / 2);
      g.lineTo(x, y);
      g.stroke();
    });
    g.fillStyle = css("--muted");
    g.fillText("loudness (LUFS, 3 s)", width - 120, 12);
    g.fillText("left/right agreement", width - 120, base + span + 8);
  }

  /** Measure the version and its master, draw them, and set up the A/B. */
  async function compare() {
    const version = label();
    const host = $("ab-result");
    if (!version || !state.trackId) return;
    const button = $("ab-measure");
    button.disabled = true;
    host.innerHTML = "";
    try {
      const got = await api(`/tracks/${state.trackId}/version/${version}/meters`);
      host.appendChild(meterLines(got.meters));
      const note = document.createElement("p");
      note.className = "muted tiny";
      note.textContent = got.note;
      host.appendChild(note);
      drawMeters(got.meters);
      $("ab-row").hidden = !(got.meters.version && got.meters.master);
      if (got.meters.version && got.meters.master) await buildPair(got.meters);
    } catch (error) {
      host.textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  async function playPair() {
    if (!pair) return;
    const starting = pair.version?.audio.paused !== false;
    if (!starting) {
      for (const side of ["version", "master"]) pair[side]?.audio.pause();
      $("ab-play").textContent = "\u25B6 Play both";
      return;
    }
    for (const side of ["version", "master"]) {
      if (pair[side]) pair[side].audio.currentTime = 0;
    }
    hear(pair.hearing);
    await Promise.all(["version", "master"].map((s) => pair[s]?.audio.play()));
    $("ab-play").textContent = "\u25A0 Stop";
  }

  function reset() {
    last = null;
    shown = null;
    stopPair();
    if ($("finish-result")) $("finish-result").innerHTML = "";
    if ($("ab-result")) $("ab-result").innerHTML = "";
    if ($("ab-row")) $("ab-row").hidden = true;
  }

  function init() {
    if (!$("finish-btn") || $("finish-btn").dataset.wired) return;
    $("finish-btn").dataset.wired = "yes";
    $("finish-btn").addEventListener("click", run);
    $("ab-measure")?.addEventListener("click", compare);
    // A canvas sized once is stretched and blurry at any other width: it is drawn in CSS
    // pixels times the display's ratio, and neither follows a resize on its own. Measured
    // here at 300 px wide against a 308 px box on a 2x display.
    window.addEventListener("resize", () => {
      if (shown) drawMeters(shown);
    }, { passive: true });
    $("ab-play")?.addEventListener("click", playPair);
    for (const button of document.querySelectorAll("[data-ab]")) {
      button.addEventListener("click", () => hear(button.dataset.ab));
    }
  }

  return { init, reset, latest: () => last };
})();

document.addEventListener("DOMContentLoaded", () => Finish.init());
