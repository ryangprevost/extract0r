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
    high_cut_hz: 0, reverb: 0, delay: 0, automation: {} };
  const flat = () => ({ ...FLAT, automation: {} });

  // Sprint 9: what can move, its range, how its lane is drawn, and the two shapes offered.
  const MOVES = {
    gain_db: { label: "level", min: -60, max: 12, scale: "lin", unit: "dB",
      up: ["Fade in from here", -60, 0], down: ["Fade out from here", 0, -60] },
    pan: { label: "pan", min: -1, max: 1, scale: "lin", unit: "",
      up: ["Sweep left to right", -1, 1], down: ["Sweep right to left", 1, -1] },
    low_cut_hz: { label: "low cut", min: 20, max: 2000, scale: "log", unit: "Hz",
      up: ["Thin out from here", 20, 800], down: ["Fill back in from here", 800, 20] },
    high_cut_hz: { label: "high cut", min: 200, max: 20000, scale: "log", unit: "Hz",
      up: ["Open up from here", 300, 20000], down: ["Close down from here", 20000, 300] },
    reverb: { label: "reverb", min: 0, max: 1, scale: "lin", unit: "",
      up: ["Wash in from here", 0, 0.8], down: ["Dry out from here", 0.8, 0] },
    delay: { label: "delay", min: 0, max: 1, scale: "lin", unit: "",
      up: ["Echo in from here", 0, 0.8], down: ["Dry out from here", 0.8, 0] },
  };
  let lanes = [];            // [{layer, setting}] in the order they were added

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
    const sayPan = () => (where.textContent = Math.abs(c.pan) < 0.02 ? "center"
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

  /** The whole mix: level, low cut, high cut - after every part and both effects. */
  function wholeStrip() {
    const c = settings.master;
    const box = document.createElement("div");
    box.className = "mix-strip mix-whole";
    box.dataset.layer = "master";
    const name = document.createElement("strong");
    name.textContent = "Whole mix";
    box.appendChild(name);
    const level = document.createElement("span");
    level.className = "muted tiny";
    const sayLevel = () => (level.textContent = c.gain_db <= -60 ? "off" : `${c.gain_db > 0 ? "+" : ""}${c.gain_db.toFixed(1)} dB`);
    sayLevel();
    box.appendChild(knob("Level", range(-60, 12, 0.5, c.gain_db, (v) => {
      c.gain_db = v; sayLevel(); apply();
    }), level));
    box.appendChild(knob("Low cut", select(LOW_CUTS, c.low_cut_hz, (hz) => `${hz} Hz`, (v) => {
      c.low_cut_hz = v; apply();
    })));
    box.appendChild(knob("High cut", select(HIGH_CUTS, c.high_cut_hz,
      (hz) => (hz >= 1000 ? `${hz / 1000} kHz` : `${hz} Hz`), (v) => { c.high_cut_hz = v; apply(); })));
    const note = document.createElement("span");
    note.className = "muted tiny";
    note.textContent = "Everything, reverb and delay included.";
    box.appendChild(note);
    return box;
  }

  function draw() {
    const host = $("mixer-strips");
    if (!host || !version) return;
    host.innerHTML = "";
    for (const layer of version.layers) host.appendChild(strip(layer));
    host.appendChild(wholeStrip());
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
    // Sprint 11: everything - every part and both returns - meets on one bus, which runs
    // through the whole-mix strip, as the server's `whole_mix` does after its sum.
    const bus = ctx.createGain();
    const wholeLow = ctx.createBiquadFilter();
    wholeLow.type = "highpass";
    wholeLow.Q.value = BUTTERWORTH_DB;
    const wholeHigh = ctx.createBiquadFilter();
    wholeHigh.type = "lowpass";
    wholeHigh.Q.value = BUTTERWORTH_DB;
    const wholeFader = ctx.createGain();
    wholeFader.connect(master);
    nodes = { master: { input: bus, low: wholeLow, high: wholeHigh, fader: wholeFader,
      whole: true, wiring: null } };

    const reverb = ctx.createConvolver();
    reverb.normalize = false;        // the server convolves with this impulse as it is
    reverb.buffer = impulse;
    const reverbReturn = ctx.createGain();
    reverbReturn.gain.value = RETURN;
    reverb.connect(reverbReturn).connect(bus);

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
    echoes.connect(delayReturn).connect(bus);

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
      const muter = ctx.createGain();
      const panner = ctx.createStereoPanner();
      const toReverb = ctx.createGain();
      const toDelay = ctx.createGain();
      fader.connect(muter).connect(panner).connect(bus);
      panner.connect(toReverb).connect(reverb);
      panner.connect(toDelay).connect(delay);
      nodes[layer.name] = { input, low, high, fader, muter, panner, toReverb, toDelay,
        wiring: null };
    }
    apply();
  }

  /** A cut that is off is not in the chain at all. A filter parked out of the way is not
   *  the same: a 10 Hz low cut barely moves the level, but it turns the phase of an 808's
   *  sub, and a flat mix here measured -16.8 dB from the bounced file because of it. */
  function wire(n, c) {
    // A moving cut is always in the chain - it is never "off", only somewhere.
    const lowOn = c.low_cut_hz || moving(c, "low_cut_hz");
    const highOn = c.high_cut_hz || moving(c, "high_cut_hz");
    const want = `${lowOn ? 1 : 0}${highOn ? 1 : 0}`;
    if (n.wiring === want) return;
    for (const node of [n.input, n.low, n.high]) node.disconnect();
    let at = n.input;
    if (lowOn) at = at.connect(n.low);
    if (highOn) at = at.connect(n.high);
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
      if (n.whole) {
        if (!moving(c, "gain_db")) n.fader.gain.setTargetAtTime(dbToGain(Math.min(c.gain_db, 12)), now, 0.015);
        if (c.low_cut_hz && !moving(c, "low_cut_hz")) n.low.frequency.setTargetAtTime(c.low_cut_hz, now, 0.015);
        if (c.high_cut_hz && !moving(c, "high_cut_hz")) n.high.frequency.setTargetAtTime(c.high_cut_hz, now, 0.015);
        continue;
      }
      n.muter.gain.setTargetAtTime(audible(name) ? 1 : 0, now, 0.015);
      // A setting with a lane is the lane's: `schedule` owns it.
      if (!moving(c, "gain_db")) n.fader.gain.setTargetAtTime(dbToGain(Math.min(c.gain_db, 12)), now, 0.015);
      if (!moving(c, "pan")) n.panner.pan.setTargetAtTime(c.pan, now, 0.015);
      if (c.low_cut_hz && !moving(c, "low_cut_hz")) n.low.frequency.setTargetAtTime(c.low_cut_hz, now, 0.015);
      if (c.high_cut_hz && !moving(c, "high_cut_hz")) n.high.frequency.setTargetAtTime(c.high_cut_hz, now, 0.015);
      if (!moving(c, "reverb")) n.toReverb.gain.setTargetAtTime(c.reverb, now, 0.015);
      if (!moving(c, "delay")) n.toDelay.gain.setTargetAtTime(c.delay, now, 0.015);
    }
  }

  // --- Sprint 9: automation -------------------------------------------------------------------

  const moving = (c, setting) => (c.automation?.[setting] || []).length > 0;
  const beatSeconds = () => 60 / (version?.tempo_bpm || 120);
  const timeOf = (beat) => (version?.first_beat_s || 0) + beat * beatSeconds();
  const beatAt = (t) => Math.max(0, (t - (version?.first_beat_s || 0)) / beatSeconds());

  /** What the param is given for a point's value: level in linear gain, as the server ramps. */
  function paramValue(setting, v) {
    const m = MOVES[setting];
    v = Math.min(m.max, Math.max(m.min, v));
    if (setting === "gain_db") return v <= -60 ? 0 : 10 ** (Math.min(v, 12) / 20);
    return v;
  }

  /** A lane's value at time t - the server's `curve`: hold, then straight lines (or even in
   *  pitch, for the cuts), then hold. */
  function valueAt(setting, points, t) {
    const pts = [...points].sort((a, b) => a[0] - b[0]).map(([b, v]) => [timeOf(b), paramValue(setting, v)]);
    if (t <= pts[0][0]) return pts[0][1];
    for (let i = 1; i < pts.length; i++) {
      const [t0, v0] = pts[i - 1];
      const [t1, v1] = pts[i];
      if (t <= t1) {
        const f = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
        return MOVES[setting].scale === "log" ? v0 * (v1 / v0) ** f : v0 + (v1 - v0) * f;
      }
    }
    return pts[pts.length - 1][1];
  }

  function paramFor(n, setting) {
    return { gain_db: n.fader?.gain, pan: n.panner?.pan, low_cut_hz: n.low?.frequency,
      high_cut_hz: n.high?.frequency, reverb: n.toReverb?.gain, delay: n.toDelay?.gain }[setting];
  }

  //: What the whole-mix strip can move: a fade and a filter.
  const WHOLE_SETTINGS = ["gain_db", "low_cut_hz", "high_cut_hz"];

  /** Every lane onto its AudioParam from where the song is now: the value here, then a ramp
   *  to each point still to come - the timeline the server's curve describes. */
  function schedule() {
    if (!ctx || !Object.keys(nodes).length) return;
    const now = ctx.currentTime;
    const position = playing ? now - startedAt : offset;
    for (const [name, n] of Object.entries(nodes)) {
      const c = settings[name];
      for (const setting of Object.keys(MOVES)) {
        const param = paramFor(n, setting);
        if (!param) continue;
        if (!moving(c, setting)) {
          param.cancelScheduledValues(0);     // a lane emptied leaves nothing behind
          continue;
        }
        const points = c.automation[setting];
        param.cancelScheduledValues(0);
        param.setValueAtTime(valueAt(setting, points, position), now);
        if (!playing) continue;
        const sorted = [...points].sort((a, b) => a[0] - b[0]);
        for (const [beat, v] of sorted) {
          const t = timeOf(beat);
          if (t <= position) continue;
          const at = startedAt + t;
          if (MOVES[setting].scale === "log") param.exponentialRampToValueAtTime(paramValue(setting, v), at);
          else param.linearRampToValueAtTime(paramValue(setting, v), at);
        }
      }
    }
    apply();
  }

  function toY(setting, v, height) {
    const m = MOVES[setting];
    const f = m.scale === "log" ? Math.log(v / m.min) / Math.log(m.max / m.min) : (v - m.min) / (m.max - m.min);
    return height - 4 - f * (height - 8);
  }

  function fromY(setting, y, height) {
    const m = MOVES[setting];
    const f = Math.min(1, Math.max(0, (height - 4 - y) / (height - 8)));
    const v = m.scale === "log" ? m.min * (m.max / m.min) ** f : m.min + f * (m.max - m.min);
    return m.scale === "log" ? Math.round(v) : Math.round(v * 100) / 100;
  }

  function said(setting, v) {
    const m = MOVES[setting];
    if (setting === "gain_db") return v <= -60 ? "off" : `${v > 0 ? "+" : ""}${v.toFixed(1)} dB`;
    if (setting === "pan") return Math.abs(v) < 0.02 ? "center" : `${Math.round(Math.abs(v) * 100)}% ${v < 0 ? "left" : "right"}`;
    if (m.unit === "Hz") return v >= 1000 ? `${(v / 1000).toFixed(1)} kHz` : `${Math.round(v)} Hz`;
    return `${Math.round(v * 100)}%`;
  }

  const PX_PER_BEAT = 14;
  const LANE_H = 70;

  function drawLane(lane, canvas) {
    const c = settings[lane.layer];
    const points = [...(c.automation[lane.setting] || [])].sort((a, b) => a[0] - b[0]);
    const beats = Math.ceil(beatAt(duration || 30)) + 4;
    const width = beats * PX_PER_BEAT;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = LANE_H * ratio;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${LANE_H}px`;
    const g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888";
    g.fillStyle = css("--panel-2");
    g.fillRect(0, 0, width, LANE_H);
    for (let b = 0; b <= beats; b++) {
      g.strokeStyle = css(b % 4 === 0 ? "--muted" : "--edge");
      g.globalAlpha = b % 4 === 0 ? 0.7 : 0.3;
      g.beginPath();
      g.moveTo(b * PX_PER_BEAT + 0.5, 0);
      g.lineTo(b * PX_PER_BEAT + 0.5, LANE_H);
      g.stroke();
      if (b % 4 === 0) {
        g.globalAlpha = 1;
        g.fillStyle = css("--muted");
        g.font = "10px ui-monospace, monospace";
        g.fillText(`${b / 4 + 1}`, b * PX_PER_BEAT + 3, 10);
      }
    }
    g.globalAlpha = 1;
    // The value it holds when the lane is empty: the strip's own setting.
    const resting = lane.setting === "gain_db" ? c.gain_db : c[lane.setting] || MOVES[lane.setting].min;
    g.strokeStyle = css("--accent");
    g.lineWidth = 2;
    g.beginPath();
    if (!points.length) {
      const y = toY(lane.setting, Math.max(MOVES[lane.setting].min, resting), LANE_H);
      g.moveTo(0, y);
      g.lineTo(width, y);
    } else {
      g.moveTo(0, toY(lane.setting, points[0][1], LANE_H));
      // Cuts are drawn as they move: evenly in pitch, which is a straight line on this scale.
      for (const [b, v] of points) g.lineTo(b * PX_PER_BEAT, toY(lane.setting, v, LANE_H));
      g.lineTo(width, toY(lane.setting, points[points.length - 1][1], LANE_H));
    }
    g.stroke();
    g.lineWidth = 1;
    g.fillStyle = css("--ink");
    for (const [b, v] of points) {
      g.beginPath();
      g.arc(b * PX_PER_BEAT, toY(lane.setting, v, LANE_H), 4, 0, Math.PI * 2);
      g.fill();
    }
    if (version && duration) {
      const now = playing ? ctx.currentTime - startedAt : offset;
      g.strokeStyle = css("--ink");
      g.globalAlpha = 0.6;
      g.beginPath();
      const x = beatAt(now) * PX_PER_BEAT;
      g.moveTo(x, 0);
      g.lineTo(x, LANE_H);
      g.stroke();
      g.globalAlpha = 1;
    }
  }

  function laneEditor(lane) {
    const box = document.createElement("div");
    box.className = "auto-lane";
    const head = document.createElement("div");
    head.className = "auto-head";
    const name = document.createElement("strong");
    const layer = version.layers.find((l) => l.name === lane.layer);
    const who = lane.layer === "master" ? "Whole mix" : layer ? layer.label : lane.layer;
    name.textContent = `${who} · ${MOVES[lane.setting].label}`;
    const readout = document.createElement("span");
    readout.className = "muted tiny";
    const span = document.createElement("select");
    for (const bars of [1, 2, 4, 8, 16]) span.appendChild(new Option(`over ${bars} bar${bars > 1 ? "s" : ""}`, bars));
    span.value = 4;
    const shape = (which) => {
      const [, from, to] = MOVES[lane.setting][which];
      const here = Math.round(beatAt(playing ? ctx.currentTime - startedAt : offset));
      const end = here + 4 * parseInt(span.value, 10);
      const c = settings[lane.layer];
      const kept = (c.automation[lane.setting] || []).filter(([b]) => b < here || b > end);
      c.automation[lane.setting] = [...kept, [here, from], [end, to]].sort((a, b) => a[0] - b[0]);
      changed();
    };
    const up = document.createElement("button");
    up.type = "button";
    up.className = "small";
    up.textContent = MOVES[lane.setting].up[0];
    up.addEventListener("click", () => shape("up"));
    const down = document.createElement("button");
    down.type = "button";
    down.className = "small";
    down.textContent = MOVES[lane.setting].down[0];
    down.addEventListener("click", () => shape("down"));
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "small";
    clear.textContent = "Clear";
    clear.addEventListener("click", () => { settings[lane.layer].automation[lane.setting] = []; changed(); });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "small";
    remove.textContent = "\u2715";
    remove.setAttribute("aria-label", "Remove this lane");
    remove.addEventListener("click", () => {
      delete settings[lane.layer].automation[lane.setting];
      lanes = lanes.filter((l) => l !== lane);
      changed();
    });
    head.append(name, up, down, span, clear, remove, readout);

    const scroll = document.createElement("div");
    scroll.className = "auto-scroll";
    const canvas = document.createElement("canvas");
    canvas.className = "auto-canvas";
    canvas.dataset.layer = lane.layer;
    canvas.dataset.setting = lane.setting;
    scroll.appendChild(canvas);
    box.append(head, scroll);

    // Click to add a point (on the beat), drag to move one, double-click to remove one.
    let dragging = null;
    const where = (e) => {
      const r = canvas.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    const near = (x, y) => (settings[lane.layer].automation[lane.setting] || []).findIndex(([b, v]) =>
      Math.abs(b * PX_PER_BEAT - x) < 7 && Math.abs(toY(lane.setting, v, LANE_H) - y) < 7);
    canvas.addEventListener("pointerdown", (e) => {
      const [x, y] = where(e);
      const c = settings[lane.layer];
      c.automation[lane.setting] = c.automation[lane.setting] || [];
      let i = near(x, y);
      if (i < 0) {
        c.automation[lane.setting].push([Math.round(x / PX_PER_BEAT), fromY(lane.setting, y, LANE_H)]);
        i = c.automation[lane.setting].length - 1;
      }
      dragging = i;
      canvas.setPointerCapture?.(e.pointerId);
      changed(false);
    });
    canvas.addEventListener("pointermove", (e) => {
      const [x, y] = where(e);
      const points = settings[lane.layer].automation[lane.setting] || [];
      if (dragging === null) {
        const i = near(x, y);
        readout.textContent = i >= 0 ? `bar ${Math.floor(points[i][0] / 4) + 1}: ${said(lane.setting, points[i][1])}` : "";
        return;
      }
      points[dragging] = [Math.max(0, Math.round(x / PX_PER_BEAT)), fromY(lane.setting, y, LANE_H)];
      readout.textContent = `bar ${Math.floor(points[dragging][0] / 4) + 1}: ${said(lane.setting, points[dragging][1])}`;
      drawLane(lane, canvas);
    });
    const done = () => {
      if (dragging !== null) {
        dragging = null;
        changed();
      }
    };
    canvas.addEventListener("pointerup", done);
    canvas.addEventListener("pointercancel", done);
    canvas.addEventListener("dblclick", (e) => {
      const [x, y] = where(e);
      const i = near(x, y);
      if (i >= 0) {
        settings[lane.layer].automation[lane.setting].splice(i, 1);
        changed();
      }
    });
    drawLane(lane, canvas);
    return box;
  }

  function drawLanes() {
    const host = $("auto-lanes");
    if (!host || !version) return;
    host.innerHTML = "";
    for (const lane of lanes) host.appendChild(laneEditor(lane));
    $("auto-empty").hidden = lanes.length > 0;
  }

  function redrawPlayheads() {
    for (const canvas of document.querySelectorAll(".auto-canvas")) {
      const lane = lanes.find((l) => l.layer === canvas.dataset.layer && l.setting === canvas.dataset.setting);
      if (lane) drawLane(lane, canvas);
    }
  }

  /** A lane changed: reschedule what is playing, and redraw. */
  function changed(redraw = true) {
    schedule();
    if (redraw) drawLanes();
    else redrawPlayheads();
  }

  function addLane() {
    const layer = $("auto-layer").value;
    const setting = $("auto-setting").value;
    if (!layer || lanes.some((l) => l.layer === layer && l.setting === setting)) return;
    if (layer === "master" && !WHOLE_SETTINGS.includes(setting)) {
      $("auto-empty").hidden = false;
      $("auto-empty").textContent = "The whole mix can fade (level) and filter (low or high " +
        "cut). Pan and the sends belong to the parts.";
      return;
    }
    settings[layer].automation[setting] = settings[layer].automation[setting] || [];
    lanes.push({ layer, setting });
    drawLanes();
  }

  function fillLanePickers() {
    const pick = $("auto-layer");
    if (!pick || !version) return;
    pick.innerHTML = "";
    for (const layer of version.layers) pick.appendChild(new Option(layer.label, layer.name));
    pick.appendChild(new Option("Whole mix", "master"));
    const what = $("auto-setting");
    if (!what.options.length) {
      for (const [setting, m] of Object.entries(MOVES)) what.appendChild(new Option(m.label, setting));
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
    schedule();
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
    schedule();
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
    redrawPlayheads();
  }

  // --- bouncing the mix --------------------------------------------------------------------

  async function bounce() {
    const button = $("mixer-bounce");
    const host = $("mixer-result");
    button.disabled = true;
    host.innerHTML = "";
    const channels = {};
    for (const [name, c] of Object.entries(settings)) {
      const lanesOf = Object.fromEntries(Object.entries(c.automation || {}).filter(([, p]) => p.length));
      const body = { ...c, automation: lanesOf };
      if (JSON.stringify(body) !== JSON.stringify(flat())) channels[name] = body;
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

  // --- Sprint 10: saved mixes --------------------------------------------------------------

  let mixList = { starters: [], yours: [] };

  async function loadMixes() {
    try {
      mixList = await api("/tracks/mixes");
    } catch {
      return;
    }
    const pick = $("mix-pick");
    const was = pick.value;
    pick.innerHTML = "";
    const group = (label, items, yours) => {
      if (!items.length) return;
      const g = document.createElement("optgroup");
      g.label = label;
      for (const m of items) {
        const option = new Option(m.name, m.name);
        option.dataset.about = m.about;
        option.dataset.yours = yours ? "1" : "";
        g.appendChild(option);
      }
      pick.appendChild(g);
    };
    group("Starter mixes", mixList.starters, false);
    group("Your mixes", mixList.yours, true);
    if ([...pick.options].some((o) => o.value === was)) pick.value = was;
    sayMix();
  }

  function sayMix() {
    const option = $("mix-pick").selectedOptions[0];
    $("mix-about").textContent = option?.dataset.about || "";
    $("mix-delete").hidden = !option?.dataset.yours;
  }

  /** Every strip and lane set from a mix: its parts as it says, everything else flat. */
  function useChannels(channels) {
    for (const name of Object.keys(settings)) {
      settings[name] = channels[name] ? { ...flat(), ...channels[name],
        automation: { ...(channels[name].automation || {}) } } : flat();
    }
    lanes = [];
    for (const [name, c] of Object.entries(settings)) {
      for (const [setting, points] of Object.entries(c.automation || {})) {
        if (points.length && MOVES[setting]) lanes.push({ layer: name, setting });
      }
    }
    draw();
    drawLanes();
    schedule();
  }

  async function useMix() {
    const said = $("mix-said");
    const name = $("mix-pick").value;
    if (!version || !name) return;
    try {
      const fitted = await api(`/tracks/${state.trackId}/version/${version.label}/mix/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, stretch: $("mix-fit").checked }),
      });
      useChannels(fitted.channels);
      said.textContent = [`"${name}" is on the strips - play it, change anything, then bounce.`,
        ...fitted.notes].join(" ");
    } catch (error) {
      said.textContent = error.message || String(error);
    }
  }

  async function saveMix() {
    const said = $("mix-said");
    const name = $("mix-name").value.trim();
    const channels = {};
    for (const [layer, c] of Object.entries(settings)) {
      const lanesOf = Object.fromEntries(Object.entries(c.automation || {}).filter(([, p]) => p.length));
      const body = { ...c, automation: lanesOf };
      if (JSON.stringify(body) !== JSON.stringify(flat())) channels[layer] = body;
    }
    const seconds = version?.duration_s || duration || 0;
    const beats = Math.max(0, (seconds - (version?.first_beat_s || 0)) * (version?.tempo_bpm || 0) / 60);
    try {
      const saved = await api("/tracks/mixes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, channels, beats, tempo_bpm: version?.tempo_bpm || 0 }),
      });
      said.textContent = `Saved "${saved.name}" (${saved.about}). Pick it on any version.`;
      await loadMixes();
      $("mix-pick").value = saved.name;
      sayMix();
    } catch (error) {
      said.textContent = error.message || String(error);
    }
  }

  async function deleteMix() {
    const name = $("mix-pick").value;
    try {
      await api(`/tracks/mixes/${encodeURIComponent(name)}`, { method: "DELETE" });
      $("mix-said").textContent = `Deleted "${name}".`;
      await loadMixes();
    } catch (error) {
      $("mix-said").textContent = error.message || String(error);
    }
  }

  /** A version opened fresh - after a reload - gets back the mix it was last bounced with. */
  async function restore() {
    const untouched = Object.values(settings).every((c) => JSON.stringify(c) === JSON.stringify(flat()));
    if (!version || !untouched) return;
    try {
      const kept = await api(`/tracks/${state.trackId}/version/${version.label}/mix`);
      if (Object.keys(kept.channels || {}).length) {
        useChannels(kept.channels);
        $("mix-said").textContent = "This is the mix the version was last bounced with.";
      }
    } catch {
      /* nothing kept - a flat mix */
    }
  }

  /** A new version was made: mix its layers, keeping the settings of any layer it still has. */
  /** Sprint 23: the newest version this track already has, so reopening a song brings the
   *  mixer and the finish back without bouncing again. Does nothing once a version is loaded. */
  async function reopen() {
    if (version || !state.trackId) return;
    try {
      const found = (await api(`/tracks/${state.trackId}/versions`)).versions || [];
      if (found.length) {
        load(found[0]);
        if ($("mix-said")) {
          $("mix-said").textContent =
            `Your ${found[0].label === "same" ? "" : `${found[0].label} BPM `}version, as you left it.`;
        }
      }
    } catch {
      /* nothing made yet */
    }
  }

  function load(result) {
    if (!result?.layers?.length) return;
    if (playing) pause();
    offset = 0;
    version = { ...result, url_key: `${result.label}:${Date.now()}` };
    const kept = {};
    for (const layer of result.layers) {
      kept[layer.name] = settings[layer.name] || flat();
    }
    kept.master = settings.master || flat();
    lanes = lanes.filter((l) => kept[l.layer]);
    settings = kept;
    $("mixer").hidden = false;
    $("mixer-result").innerHTML = "";
    // Sprint 25: "Mix" and "Finish" are reachable from the bar the moment they exist.
    if (typeof Sections !== "undefined") Sections.render();
    draw();
    fillLanePickers();
    drawLanes();
    restore();
  }

  function reset() {
    if (playing) pause();
    if (typeof Finish !== "undefined") Finish.reset();
    version = null;
    settings = {};
    loadedFor = "";
    if ($("mixer")) $("mixer").hidden = true;
    if (typeof Sections !== "undefined") Sections.render();
  }

  function init() {
    $("mixer-match")?.addEventListener("click", matchReference);
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
      else { schedule(); redrawPlayheads(); }
    });
    $("mixer-bounce").addEventListener("click", bounce);
    $("auto-add").addEventListener("click", addLane);
    $("mix-pick").addEventListener("change", sayMix);
    $("mix-use").addEventListener("click", useMix);
    $("mix-save").addEventListener("click", saveMix);
    $("mix-delete").addEventListener("click", deleteMix);
    loadMixes();
    $("mixer-reset").addEventListener("click", () => {
      for (const name of Object.keys(settings)) settings[name] = flat();
      lanes = [];
      apply();
      schedule();
      draw();
      drawLanes();
    });
  }

  /** Sprint 21: the reference's balance, measured, put on the faders - each move said. */
  async function matchReference() {
    if (!version) return;
    const said = $("mix-said");
    try {
      const moved = await api(`/tracks/${state.trackId}/version/${version.label}/match-levels`,
        { method: "POST" });
      const channels = {};
      for (const [name, c] of Object.entries(settings)) {
        channels[name] = { ...c, ...(moved.channels[name] || {}) };
      }
      useChannels(channels);
      if (said) said.textContent = `Set to the reference's balance: ${moved.said.join("; ")}.`;
      return moved;
    } catch (error) {
      if (said) said.textContent = error.message || String(error);
      return null;
    }
  }

  return { init, load, reset, useChannels: (c) => useChannels(c), bounce: () => bounce(),
    matchReference, label: () => version?.label || null, reopen };
})();

document.addEventListener("DOMContentLoaded", () => Mixer.init());
