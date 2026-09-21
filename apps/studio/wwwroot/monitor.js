// Real-time monitoring: hear a setting before anything is rendered.
//
// Every control on the mixer used to cost a full master to audition - upload, separate,
// set a slider, wait a minute, listen, decide it was wrong. That loop is too slow to mix
// with. This routes each stem's <audio> element through a Web Audio chain that mirrors
// the server's channel strip, so a slider is audible on the next buffer.
//
// It is a MONITOR, not the render. Where it differs, and why, because a preview that
// quietly disagrees with the export is worse than no preview at all:
//
//   * EQ shape. The render uses zero-phase curves applied in the frequency domain; a Web
//     Audio peaking filter is a biquad and is not the same shape. The BAND GAINS are the
//     same, because the solve matrix comes from the server (see `setTone`), so the amount
//     is right and the skirts are not.
//   * Compression. The render's dial is calibrated in dB of range removed, measured and
//     corrected against the actual material. DynamicsCompressorNode has a threshold and a
//     ratio and no idea what the material is, so this approximates.
//   * Saturation. The render drives against the signal's own level and leaves everything
//     below 90 Hz clean. This does track the level, via an analyser, but shapes the whole
//     band rather than splitting it.
//   * The limiter, the reference match and every master-bus control are not here at all.
//     Those happen to the sum, after this point, and belong to the render.
//
// Same-origin audio throughout, so `createMediaElementSource` does not taint anything and
// no CORS headers are needed.

const Monitor = (() => {
  let ctx = null;
  const chains = new Map();

  // The five filters the tone controls are built from. Frequencies and kinds match
  // `instrument.BASIS` on the server; if that list changes, this one has to change with
  // it, which is what `bandOrder` is checked against when a comparison arrives.
  const BASIS = [
    { band: "low", type: "lowshelf", hz: 120 },
    { band: "low_mid", type: "peaking", hz: 250 },
    { band: "high_mid", type: "peaking", hz: 1200 },
    { band: "presence", type: "peaking", hz: 5000 },
    { band: "air", type: "highshelf", hz: 9000 },
  ];

  // The server's bells are Gaussian at 0.9 octaves. A biquad's Q for a given bandwidth in
  // octaves: Q = sqrt(2^B) / (2^B - 1). At 1.8 octaves total width that lands near 0.8.
  const BELL_Q = 0.8;

  // Matches saturation.DRIVE_PER_DB and DRIVE_HEADROOM on the server.
  const DRIVE_PER_DB = 6.0;
  const DRIVE_HEADROOM = 22.0;
  const EVEN_SHARE = 0.35;

  function context() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    return ctx;
  }

  /**
   * Move a parameter, smoothly when that is possible and instantly when it is not.
   *
   * `setTargetAtTime` schedules an approach against the context clock, and that clock is
   * stopped while the context is suspended - which it is until the first gesture. A
   * slider dragged before pressing play would schedule a ramp from now to now and never
   * arrive, so the setting would be visibly on and audibly absent. Writing `.value`
   * directly in that state is correct and costs nothing: with nothing playing there is no
   * click to smooth over.
   */
  function ramp(param, value, seconds = 0.02) {
    const audio = context();
    if (audio.state === "running") param.setTargetAtTime(value, audio.currentTime, seconds);
    else param.value = value;
  }

  /** Browsers start the context suspended until a gesture. Call this from a click. */
  async function resume() {
    if (ctx && ctx.state === "suspended") await ctx.resume();
  }

  function available() {
    return typeof window !== "undefined" && !!(window.AudioContext || window.webkitAudioContext);
  }

  /**
   * Build the chain for one stem and route its element through it.
   *
   * source -> tone x5 -> compressor -> saturation -> width (M/S) -> pan -> gain -> out
   *
   * Tone first for the same reason the render does it first: the compressor reacts to
   * what it is fed, and a few dB of EQ changes what it reacts to.
   */
  function attach(key, element) {
    if (chains.has(key)) return chains.get(key);
    const audio = context();

    let source;
    try {
      source = audio.createMediaElementSource(element);
    } catch (error) {
      // Already attached to another graph, or the element is not ready. Either way the
      // page keeps working with plain <audio> playback - the monitor is an enhancement.
      console.warn("monitor: could not attach", key, error);
      return null;
    }

    const filters = BASIS.map((spec) => {
      const filter = audio.createBiquadFilter();
      filter.type = spec.type;
      filter.frequency.value = spec.hz;
      if (spec.type === "peaking") filter.Q.value = BELL_Q;
      filter.gain.value = 0;
      return filter;
    });

    const compressor = audio.createDynamicsCompressor();
    compressor.threshold.value = 0;
    compressor.ratio.value = 1;
    compressor.knee.value = 6;
    compressor.attack.value = 0.015;
    compressor.release.value = 0.18;

    const shaper = audio.createWaveShaper();
    shaper.oversample = "4x"; // the render oversamples for the same reason: aliasing
    const preDrive = audio.createGain();
    const postDrive = audio.createGain();

    // An analyser only so the drive can follow the signal's level, the way the render's
    // does. Without it a quiet passage would be driven as hard as a loud one.
    const analyser = audio.createAnalyser();
    analyser.fftSize = 2048;

    const width = buildWidth(audio);
    const panner = audio.createStereoPanner();
    const gain = audio.createGain();

    let node = source;
    for (const filter of filters) {
      node.connect(filter);
      node = filter;
    }
    node.connect(analyser);
    node.connect(compressor);
    compressor.connect(preDrive);
    preDrive.connect(shaper);
    shaper.connect(postDrive);
    postDrive.connect(width.input);
    width.output.connect(panner);
    panner.connect(gain);
    gain.connect(audio.destination);

    const chain = {
      element,
      source,
      filters,
      compressor,
      shaper,
      preDrive,
      postDrive,
      analyser,
      width,
      panner,
      gain,
      buffer: new Float32Array(analyser.fftSize),
      saturationDb: 0,
      gainDb: 0,
      muted: false,
      solver: null,
      bands: {},
    };
    setSaturation(key, 0, chain);
    chains.set(key, chain);
    return chain;
  }

  /**
   * Mid/side width, built from gain nodes.
   *
   * A GainNode sums everything connected to it, so mid is L and R at 0.5 each and side is
   * L at 0.5 against R at -0.5. Scaling side alone and decoding back is what a width
   * control is; scaling both channels would only be a volume.
   */
  function buildWidth(audio) {
    const input = audio.createGain();
    const splitter = audio.createChannelSplitter(2);
    const mid = mono(audio);
    const side = mono(audio);
    const sideScale = mono(audio);
    const leftOut = mono(audio);
    const rightOut = mono(audio);
    const merger = audio.createChannelMerger(2);
    const output = audio.createGain();

    const half = (value) => {
      const node = audio.createGain();
      node.gain.value = value;
      node.channelCount = 1;
      node.channelCountMode = "explicit";
      return node;
    };

    input.connect(splitter);
    const [lToMid, rToMid, lToSide, rToSide] = [half(0.5), half(0.5), half(0.5), half(-0.5)];
    splitter.connect(lToMid, 0);
    splitter.connect(rToMid, 1);
    splitter.connect(lToSide, 0);
    splitter.connect(rToSide, 1);
    lToMid.connect(mid);
    rToMid.connect(mid);
    lToSide.connect(side);
    rToSide.connect(side);

    side.connect(sideScale);
    // L = mid + side, R = mid - side
    const [midToL, midToR, sideToL, sideToR] = [half(1), half(1), half(1), half(-1)];
    mid.connect(midToL);
    mid.connect(midToR);
    sideScale.connect(sideToL);
    sideScale.connect(sideToR);
    midToL.connect(leftOut);
    sideToL.connect(leftOut);
    midToR.connect(rightOut);
    sideToR.connect(rightOut);

    leftOut.connect(merger, 0, 0);
    rightOut.connect(merger, 0, 1);
    merger.connect(output);
    return { input, output, sideScale };
  }

  function mono(audio) {
    const node = audio.createGain();
    node.channelCount = 1;
    node.channelCountMode = "explicit";
    node.channelInterpretation = "discrete";
    return node;
  }

  function get(key) {
    return chains.get(key) ?? null;
  }

  /**
   * Set the five tone bands, in the dB the comparison speaks in.
   *
   * `solver` is the server's band-to-filter solve for this stem, already inverted and
   * damped: multiply it by the request and the filter gains fall out. The page used to
   * receive the raw matrix and invert it here, exactly, which agreed with the render
   * right up until the render started damping its own solve to stop overlapping filters
   * combing. One matrix, sent solved, and the two cannot drift apart again.
   */
  function setTone(key, bands, solver) {
    const chain = get(key);
    if (!chain) return;
    chain.bands = { ...bands };
    if (solver) chain.solver = solver;

    const order = BASIS.map((spec) => spec.band);
    const target = order.map((band) => Number(bands[band] ?? 0));
    const gains = chain.solver ? apply(chain.solver, target) : target;

    gains.forEach((value, index) => {
      const clamped = Math.max(-12, Math.min(12, value || 0));
      ramp(chain.filters[index].gain, clamped);
    });
  }

  /** Matrix times vector. */
  function apply(matrix, vector) {
    return matrix.map((row) =>
      row.reduce((sum, value, index) => sum + value * vector[index], 0),
    );
  }

  /**
   * Approximate the render's compression, whose dial is dB of range removed.
   *
   * DynamicsCompressorNode cannot be told that. What it can be told is a threshold and a
   * ratio, so the dial is mapped onto both: further below the peaks and harder as it goes
   * up. The render measures the result and corrects itself; this cannot, so treat the
   * monitor as "roughly this much" rather than as the number.
   */
  function setCompression(key, rangeDb) {
    const chain = get(key);
    if (!chain) return;
    const amount = Math.max(0, Number(rangeDb) || 0);
    if (amount <= 0) {
      chain.compressor.threshold.value = 0;
      chain.compressor.ratio.value = 1;
      ramp(chain.postDrive.gain, driveMakeup(chain), 0.05);
      return;
    }
    chain.compressor.threshold.value = -6 - amount * 2.5;
    chain.compressor.ratio.value = 1 + amount * 0.6;
    // Make-up, so the control is a balance rather than a volume - the same reason the
    // render level-matches after compressing.
    chain.compressionMakeupDb = amount * 0.8;
    ramp(chain.postDrive.gain, driveMakeup(chain), 0.05);
  }

  function driveMakeup(chain) {
    return 10 ** ((chain.compressionMakeupDb ?? 0) / 20);
  }

  /** Build the tanh-plus-even-harmonic curve the render uses, as a lookup table. */
  function setSaturation(key, amountDb, existing) {
    const chain = existing ?? get(key);
    if (!chain) return;
    chain.saturationDb = Math.max(0, Number(amountDb) || 0);

    const size = 2048;
    const curve = new Float32Array(size);
    const drive = 10 ** (chain.saturationDb / DRIVE_PER_DB);

    for (let index = 0; index < size; index += 1) {
      const x = (index / (size - 1)) * 2 - 1;
      if (chain.saturationDb <= 0) {
        curve[index] = x;
        continue;
      }
      const odd = Math.tanh(x * drive);
      // The even term is x^2, which is strictly positive and would put a DC offset
      // straight into the output. tanh(x*drive)^2 - tanh(drive)^2/2 keeps it centred,
      // which is the lookup-table equivalent of the render subtracting the mean.
      const even = odd * odd - Math.tanh(drive) ** 2 / 2;
      curve[index] = (odd + EVEN_SHARE * even) / drive;
    }
    chain.shaper.curve = curve;
    chain.needsDriveUpdate = true;
  }

  function setWidth(key, factor) {
    const chain = get(key);
    if (!chain) return;
    const value = Math.max(0, Math.min(3, Number(factor) || 1));
    ramp(chain.width.sideScale.gain, value);
  }

  function setPan(key, pan) {
    const chain = get(key);
    if (!chain) return;
    ramp(chain.panner.pan, Math.max(-1, Math.min(1, Number(pan) || 0)));
  }

  function setGain(key, db) {
    const chain = get(key);
    if (!chain) return;
    chain.gainDb = Number(db) || 0;
    applyGain(chain);
  }

  function setMuted(key, muted) {
    const chain = get(key);
    if (!chain) return;
    chain.muted = !!muted;
    applyGain(chain);
  }

  function applyGain(chain) {
    // Through the graph rather than through element.volume, so a boost above 0 dB is
    // actually audible. The <audio> element clamps volume at 1 and silently throws away
    // anything a fader asks for above unity.
    const value = chain.muted ? 0 : 10 ** (chain.gainDb / 20);
    ramp(chain.gain.gain, value);
  }

  /**
   * Follow each stem's level so the drive tracks the music, as the render's does.
   *
   * Called from the page's existing animation loop and throttled hard - four times a
   * second is plenty for something whose whole purpose is to change slowly.
   */
  let lastTick = 0;
  function tick(now) {
    if (now - lastTick < 250) return;
    lastTick = now;

    for (const chain of chains.values()) {
      if (chain.saturationDb <= 0) {
        chain.preDrive.gain.value = 1;
        continue;
      }
      chain.analyser.getFloatTimeDomainData(chain.buffer);
      let sum = 0;
      for (let index = 0; index < chain.buffer.length; index += 1) {
        sum += chain.buffer[index] * chain.buffer[index];
      }
      const level = Math.sqrt(sum / chain.buffer.length);
      if (level < 1e-5) continue;

      // Same arithmetic as the render: normalise by the signal's own level with headroom,
      // shape, then undo the normalisation.
      const scale = 1 / (level * DRIVE_HEADROOM);
      ramp(chain.preDrive.gain, scale, 0.15);
      ramp(chain.postDrive.gain, (1 / scale) * driveMakeup(chain), 0.15);
    }
  }

  function has(key) {
    return chains.has(key);
  }

  function forget(key) {
    const chain = chains.get(key);
    if (!chain) return;
    try {
      chain.gain.disconnect();
    } catch {
      /* already torn down */
    }
    chains.delete(key);
  }

  function reset() {
    for (const key of [...chains.keys()]) forget(key);
  }

  return {
    available, resume, attach, has, forget, reset, tick, apply,
    setTone, setCompression, setSaturation, setWidth, setPan, setGain, setMuted,
    BASIS,
  };
})();
