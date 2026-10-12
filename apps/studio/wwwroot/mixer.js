// Mixing each part, heard live. Sprint 7.
//
// Ryan: "go ahead with mixing each part next". Once a version is made, every layer of it -
// each part, the added beat, the builds and drops - comes back as its own file, and this
// plays them together through a channel strip each: level, pan, mute, solo, low and high
// cut, and sends to a reverb and a delay.
//
// What is heard here is what "Bounce this mix" renders, because the server does this page's
// arithmetic (synth/mixer.py): the same StereoPanner law, the same biquads, the same delay
// loop, and the reverb's impulse response fetched from the server and convolved without
// Web Audio's normalisation. Sends are post-fader, as on a desk.

const Mixer = (() => {
  const LOW_CUTS = [0, 40, 80, 120, 200, 400, 800];
  const HIGH_CUTS = [0, 12000, 8000, 5000, 3000, 1500, 800];
  const DELAY_BEATS = 0.75;
  const DELAY_FEEDBACK = 0.35;
  const RETURN = 0.5;
  const BUTTERWORTH_DB = 20 * Math.log10(Math.SQRT1_2);
  const FLAT = { gain_db: 0, pan: 0, mute: false, solo: false, low_cut_hz: 0,
    high_cut_hz: 0, reverb: 0, delay: 0 };

  let version = null;       // the bounce result this mixes
  let settings = {};        // layer name -> channel settings, kept across re-bounces
  let ctx = null;
  let buffers = {};
  let nodes = {};
  let sources = [];
  let master = null;
  let startedAt = 0;
  let offset = 0;
  let playing = false;
  let duration = 0;
  let loadedFor = "";
  let clock = null;
  let loopLatency = 0;

  /** How many extra samples a delay inside a feedback loop adds, measured on a click.
   *  Chromium adds one 128-frame render quantum to it - the second echo of a 15504-sample
   *  delay came at 31136, not 31008 - so a single DelayNode in a loop drifts a little further
   *  from the bounced echoes on every repeat (-31 dB from the server's). Measured rather than
   *  assumed, so a browser that adds nothing gets nothing taken off. */
  async function measureLoopLatency(rate) {
    try {
      const d = 4096;
      const test = new OfflineAudioContext(1, d * 4, rate);
      const click = test.createBuffer(1, d * 4, rate);
      click.getChannelData(0)[0] = 1;
      const source = test.createBufferSource();
      source.buffer = click;
      const loop = test.createDelay(1);
      loop.delayTime.value = d / rate;
      const back = test.createGain();
      back.gain.value = 0.5;
      loop.connect(back).connect(loop);
      source.connect(loop);
      loop.connect(test.destination);
      source.start(0);
      const out = (await test.startRendering()).getChannelData(0);
      const echoes = [];
      for (let i = 1; i < out.length && echoes.length < 2; i++) {
        if (Math.abs(out[i]) > 0.2 && Math.abs(out[i]) >= Math.abs(out[i - 1])) echoes.push(i);
      }
      return echoes.length === 2 ? Math.max(0, echoes[1] - echoes[0] - d) : 0;
    } catch {
      return 0;
    }
  }

  const dbToGain = (db) => (db <= -60 ? 0 : 10 ** (db / 20));
  const anySolo = () => Object.values(settings).some((c) => c.solo);
  const audible = (name) => {
    const c = settings[name];
    return !c.mute && (!anySolo() || c.solo);
  };

  // --- the strips --------------------------------------------------------------------------

  function knob(labelText, input, readout) {
    const wrap = document.createElement("label");
    wrap.className = "mix-control";
    const text = document.createElement("span");
    text.className = "muted tiny";
    text.textContent = labelText;
    wrap.append(text, input);
    if (readout) wrap.appendChild(readout);
    return wrap;
  }

  function range(min, max, step, value, onInput) {
    const input = document.createElement("input");
    input.type = "range";
    input.min = min;
    input.max = max;
    input.step = step;
    input.value = value;
    input.addEventListener("input", () => onInput(parseFloat(input.value)));
    return input;
  }

  function select(options, value, words, onChange) {
    const pick = document.createElement("select");
    for (const hz of options) pick.appendChild(new Option(hz ? words(hz) : "off", hz));
    pick.value = value;
    pick.addEventListener("change", () => onChange(parseFloat(pick.value)));
    return pick;
  }

  function strip(layer) {
    const c = settings[layer.name];
    const box = document.createElement("div");
    box.className = "mix-strip";
    box.dataset.layer = layer.name;

    const name = document.createElement("strong");
    name.textContent = layer.label;
    box.appendChild(name);

    const buttons = document.createElement("div");
    buttons.className = "mix-buttons";
    const mute = document.createElement("button");
    mute.type = "button";
    mute.className = "small" + (c.mute ? " on" : "");
    mute.textContent = "M";
    mute.title = "Mute";
    mute.setAttribute("aria-pressed", String(c.mute));
    mute.addEventListener("click", () => { c.mute = !c.mute; apply(); draw(); });
    const solo = document.createElement("button");
    solo.type = "button";
    solo.className = "small" + (c.solo ? " on" : "");
    solo.textContent = "S";
    solo.title = "Solo - hear only the soloed parts";
    solo.setAttribute("aria-pressed", String(c.solo));
    solo.addEventListener("click", () => { c.solo = !c.solo; apply(); draw(); });
    buttons.append(mute, solo);
    box.appendChild(buttons);

    const level = document.createElement("span");
    level.className = "muted tiny";
    const sayLevel = () => (level.textContent = c.gain_db <= -60 ? "off" : `${c.gain_db > 0 ? "+" : ""}${c.gain_db.toFixed(1)} dB`);
    sayLevel();
    box.appendChild(knob("Level", range(-60, 12, 0.5, c.gain_db, (v) => {
      c.gain_db = v; sayLevel(); apply();
    }), level));

    const where = document.createElement("span");
    where.className = "muted tiny";
    const sayPan = () => (where.textContent = Math.abs(c.pan) < 0.02 ? "centre"
      : `${Math.round(Math.abs(c.pan) * 100)}% ${c.pan < 0 ? "left" : "right"}`);
    sayPan();
    box.appendChild(knob("Pan", range(-1, 1, 0.01, c.pan, (v) => {
      c.pan = Math.abs(v) < 0.02 ? 0 : v; sayPan(); apply();
    }), where));

    box.appendChild(knob("Low cut", select(LOW_CUTS, c.low_cut_hz, (hz) => `${hz} Hz`, (v) => {
      c.low_cut_hz = v; apply();
    })));
    box.appendChild(knob("High cut", select(HIGH_CUTS, c.high_cut_hz,
      (hz) => (hz >= 1000 ? `${hz / 1000} kHz` : `${hz} Hz`), (v) => { c.high_cut_hz = v; apply(); })));
    box.appendChild(knob("Reverb", range(0, 1, 0.01, c.reverb, (v) => { c.reverb = v; apply(); })));
    box.appendChild(knob("Delay", range(0, 1, 0.01, c.delay, (v) => { c.delay = v; apply(); })));
    return box;
  }

  function draw() {
    const host = $("mixer-strips");
    if (!host || !version) return;
    host.innerHTML = "";
    for (const layer of version.layers) host.appendChild(strip(layer));
  }

  // --- sound -------------------------------------------------------------------------------

  async function ensureLoaded() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (loadedFor === version.url_key) return;
    const status = $("mixer-status");
    buffers = {};
    let done = 0;
    status.textContent = `Loading the parts… 0 of ${version.layers.length}`;
    await Promise.all(version.layers.map(async (layer) => {
      const data = await (await fetch(layer.url)).arrayBuffer();
      buffers[layer.name] = await ctx.decodeAudioData(data);
      done += 1;
      status.textContent = `Loading the parts… ${done} of ${version.layers.length}`;
    }));
    const ir = await (await fetch(`${API}/tracks/mixer/impulse?rate=${ctx.sampleRate}`)).arrayBuffer();
    const impulse = await ctx.decodeAudioData(ir);
    duration = Math.max(...Object.values(buffers).map((b) => b.duration));
    loopLatency = await measureLoopLatency(ctx.sampleRate);
    build(impulse);
    loadedFor = version.url_key;
    status.textContent = "";
  }

  function build(impulse) {
    // The layers were scaled to fit 16-bit; this turns them back up, so a flat mix here is
    // exactly the file the version wrote.
    master = ctx.createGain();
    master.gain.value = version.layer_gain || 1;
    master.connect(ctx.destination);

    const reverb = ctx.createConvolver();
    reverb.normalize = false;        // the server convolves with this impulse as it is
    reverb.buffer = impulse;
    const reverbReturn = ctx.createGain();
    reverbReturn.gain.value = RETURN;
    reverb.connect(reverbReturn).connect(master);

    // The server's loop: y[n] = x[n-d] + feedback * y[n-d], d a whole number of samples.
    // Built from two delays - the first echo from one outside the loop, the repeats from one
    // inside it, shortened by the loop latency this browser adds - so every echo lands where
    // the bounce puts it.
    const samples = Math.round(((DELAY_BEATS * 60) / (version.tempo_bpm || 120)) * ctx.sampleRate);
    const delay = ctx.createDelay(5);
    delay.delayTime.value = samples / ctx.sampleRate;
    const echoes = ctx.createGain();
    const repeat = ctx.createDelay(5);
    repeat.delayTime.value = Math.max(128, samples - loopLatency) / ctx.sampleRate;
    const feedback = ctx.createGain();
    feedback.gain.value = DELAY_FEEDBACK;
    delay.connect(echoes);
    echoes.connect(feedback).connect(repeat).connect(echoes);
    const delayReturn = ctx.createGain();
    delayReturn.gain.value = RETURN;
    echoes.connect(delayReturn).connect(master);

    nodes = {};
    for (const layer of version.layers) {
      // Web Audio reads a lowpass or highpass Q in *decibels* (the spec's alpha_QdB), not as
      // a ratio - so the obvious Q = 0.707 is a ratio of 1.085, a slightly peaky filter, and
      // the low cut heard here differed from the one bounced by -15 dB. -3.0103 dB is a ratio
      // of 1/sqrt(2): the flat Butterworth response the server's biquad uses.
      const low = ctx.createBiquadFilter();
      low.type = "highpass";
      low.Q.value = BUTTERWORTH_DB;
      const high = ctx.createBiquadFilter();
      high.type = "lowpass";
      high.Q.value = BUTTERWORTH_DB;
      const input = ctx.createGain();
      const fader = ctx.createGain();
      const panner = ctx.createStereoPanner();
      const toReverb = ctx.createGain();
      const toDelay = ctx.createGain();
      fader.connect(panner).connect(master);
      panner.connect(toReverb).connect(reverb);
      panner.connect(toDelay).connect(delay);
      nodes[layer.name] = { input, low, high, fader, panner, toReverb, toDelay, wiring: null };
    }
    apply();
  }

  /** A cut that is off is not in the chain at all. A filter parked out of the way is not
   *  the same: a 10 Hz low cut barely moves the level, but it turns the phase of an 808's
   *  sub, and a flat mix here measured -16.8 dB from the bounced file because of it. */
  function wire(n, c) {
    const want = `${c.low_cut_hz ? 1 : 0}${c.high_cut_hz ? 1 : 0}`;
    if (n.wiring === want) return;
    for (const node of [n.input, n.low, n.high]) node.disconnect();
    let at = n.input;
    if (c.low_cut_hz) at = at.connect(n.low);
    if (c.high_cut_hz) at = at.connect(n.high);
    at.connect(n.fader);
    n.wiring = want;
  }

  /** Every control's value onto the graph - smoothly, so a fader move does not click. */
  function apply() {
    if (!ctx || !Object.keys(nodes).length) return;
    const now = ctx.currentTime;
    for (const [name, n] of Object.entries(nodes)) {
      const c = settings[name];
      wire(n, c);
      n.fader.gain.setTargetAtTime(audible(name) ? dbToGain(Math.min(c.gain_db, 12)) : 0, now, 0.015);
      n.panner.pan.setTargetAtTime(c.pan, now, 0.015);
      if (c.low_cut_hz) n.low.frequency.setTargetAtTime(c.low_cut_hz, now, 0.015);
      if (c.high_cut_hz) n.high.frequency.setTargetAtTime(c.high_cut_hz, now, 0.015);
      n.toReverb.gain.setTargetAtTime(c.reverb, now, 0.015);
      n.toDelay.gain.setTargetAtTime(c.delay, now, 0.015);
    }
  }

  async function play() {
    if (!version) return;
    await ensureLoaded();
    if (ctx.state === "suspended") await ctx.resume();
    stopSources();
    const at = ctx.currentTime + 0.05;
    for (const layer of version.layers) {
      const source = ctx.createBufferSource();
      source.buffer = buffers[layer.name];
      source.connect(nodes[layer.name].input);
      source.start(at, Math.min(offset, source.buffer.duration));
      sources.push(source);
    }
    startedAt = at - offset;
    playing = true;
    $("mixer-play").textContent = "Pause";
    // A timer rather than requestAnimationFrame: animation frames stop when the tab is in
    // the background, and the music does not, so the position bar froze at 0:00.
    clearInterval(clock);
    clock = setInterval(tick, 200);
    tick();
  }

  function stopSources() {
    for (const s of sources) {
      try { s.stop(); } catch { /* already stopped */ }
    }
    sources = [];
  }

  function pause() {
    if (!playing) return;
    offset = Math.min(duration, ctx.currentTime - startedAt);
    stopSources();
    playing = false;
    clearInterval(clock);
    $("mixer-play").textContent = "Play";
  }

  function tick() {
    if (!playing) return;
    const now = ctx.currentTime - startedAt;
    if (now >= duration) {
      pause();
      offset = 0;
    }
    const seek = $("mixer-seek");
    seek.max = duration.toFixed(2);
    seek.value = Math.min(now, duration).toFixed(2);
    const s = Math.max(0, Math.min(now, duration));
    $("mixer-time").textContent = `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  }

  // --- bouncing the mix --------------------------------------------------------------------

  async function bounce() {
    const button = $("mixer-bounce");
    const host = $("mixer-result");
    button.disabled = true;
    host.innerHTML = "";
    const channels = {};
    for (const [name, c] of Object.entries(settings)) {
      if (JSON.stringify(c) !== JSON.stringify(FLAT)) channels[name] = c;
    }
    try {
      const started = await api(`/tracks/${state.trackId}/version/${version.label}/mix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channels }),
      });
      const result = (await pollJobQuietly(started.job_id, () => {})) || {};
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
    } catch (error) {
      $("mixer-status").textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  // --- the outside -------------------------------------------------------------------------

  /** A new version was made: mix its layers, keeping the settings of any layer it still has. */
  function load(result) {
    if (!result?.layers?.length) return;
    if (playing) pause();
    offset = 0;
    version = { ...result, url_key: `${result.label}:${Date.now()}` };
    const kept = {};
    for (const layer of result.layers) {
      kept[layer.name] = settings[layer.name] || { ...FLAT };
    }
    settings = kept;
    $("mixer").hidden = false;
    $("mixer-result").innerHTML = "";
    draw();
  }

  function reset() {
    if (playing) pause();
    version = null;
    settings = {};
    loadedFor = "";
    if ($("mixer")) $("mixer").hidden = true;
  }

  function init() {
    const playButton = $("mixer-play");
    if (!playButton || playButton.dataset.wired) return;
    playButton.dataset.wired = "yes";
    playButton.addEventListener("click", () => (playing ? pause() : play()));
    $("mixer-stop").addEventListener("click", () => {
      pause();
      offset = 0;
      $("mixer-seek").value = 0;
      $("mixer-time").textContent = "0:00";
    });
    $("mixer-seek").addEventListener("input", (e) => {
      const was = playing;
      if (playing) pause();
      offset = parseFloat(e.target.value) || 0;
      if (was) play();
    });
    $("mixer-bounce").addEventListener("click", bounce);
    $("mixer-reset").addEventListener("click", () => {
      for (const name of Object.keys(settings)) settings[name] = { ...FLAT };
      apply();
      draw();
    });
  }

  return { init, load, reset };
})();

document.addEventListener("DOMContentLoaded", () => Mixer.init());
