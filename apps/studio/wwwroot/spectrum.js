// Three songs on one pair of axes: where you started, where you ended, what you aimed at.
//
// Every other panel on this page *tells* you what happened. This one shows it, which is a
// different job and the reason it exists: the report can say "lifted the presence band by
// 2 dB" and be perfectly true while the master still sits nowhere near the reference,
// because 2 dB was not the gap. A curve cannot make that mistake.
//
// The drawing decisions that matter are on the server - level matching and smoothing, in
// `spectrum_view` - because they are what make the comparison honest rather than pretty.
// What is left here is the chart, and its own rule is that the three lines share one
// vertical scale. Three lines each fitted to themselves would fill the box and look
// identical, which is exactly the answer this panel must not give by accident.

const SPECTRUM_TICKS = [30, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 16000];

/** How each curve is drawn. Keyed by the server's `key`, so a new curve needs a line here
 * rather than a change to the drawing code. */
const SPECTRUM_STYLE = {
  source: { colour: "--stem-other", width: 1.5, dash: [4, 3] },
  master: { colour: "--accent", width: 2.5, dash: [] },
  reference: { colour: "--stem-piano", width: 2, dash: [] },
};

async function renderSpectrum() {
  const panel = $("master-spectrum");
  if (!panel) return;
  panel.hidden = true;
  state.spectrum = null;

  let data;
  try {
    data = await api(`/tracks/${state.trackId}/master/spectrum`);
  } catch {
    return; // no picture; every number on the page is still true
  }
  if (!data?.available) return;

  state.spectrum = data;
  panel.hidden = false;
  spectrumSizes.observe($("spectrum-canvas"));

  renderSpectrumKey(data);
  drawSpectrum();
}

/** The legend, and the sentence about level that stops the picture being misread. */
function renderSpectrumKey(data) {
  const style = getComputedStyle(document.documentElement);
  const key = $("spectrum-key");
  const difference = spectrumView() === "difference";

  key.innerHTML = (difference ? spectrumLines(data) : data.curves)
    .map((curve) => {
      const how = SPECTRUM_STYLE[curve.key] ?? { colour: "--muted" };
      const colour = style.getPropertyValue(how.colour).trim() || "#8b96a5";
      const dashed = (how.dash ?? []).length ? "dashed" : "solid";
      // On the difference view a curve is a gap, and a gap has no loudness of its own.
      // Elsewhere: the loudness it was measured at, how far it was shifted to level-match
      // it, and whether it came from audio or from a saved profile's stored numbers. All
      // three are in the payload and none of them reached the screen until now - the
      // panel was asking to be trusted about a comparison without saying what it had
      // compared.
      let loud = "";
      if (curve.lufs != null && !difference) {
        const shift = curve.shifted_db
          ? `, shifted ${curve.shifted_db > 0 ? "+" : ""}${curve.shifted_db.toFixed(1)} dB to match`
          : "";
        const from = curve.source === "profile" ? " · recalled" : "";
        loud =
          `<em title="Measured at ${curve.lufs.toFixed(1)} LUFS${shift}.">` +
          `${curve.lufs.toFixed(1)} LUFS${from}</em>`;
      }
      return (
        `<span class="spectrum-tag">` +
        `<i style="background:${colour};border-bottom-style:${dashed}"></i>` +
        `${escapeText(curve.label)}${loud}` +
        `</span>`
      );
    })
    .join("");

  // Say the loudness difference in words as well as showing it in the legend. It is the
  // one thing the chart deliberately hides, so leaving it to be inferred from two small
  // numbers would be hiding it twice.
  const master = data.curves.find((c) => c.key === "master");
  const reference = data.curves.find((c) => c.key === "reference");
  const loudness =
    master && reference
      ? ` Your master is ${Math.abs(master.lufs - reference.lufs).toFixed(1)} dB ` +
        `${master.lufs > reference.lufs ? "louder" : "quieter"} than the reference; that ` +
        "difference is taken out here so the shapes can be compared."
      : "";

  const shared =
    "Level-matched and smoothed to a third of an octave — the same width the matching " +
    "engine works at, so a difference you can see here is one the tool can act on.";

  $("spectrum-note").textContent = difference
    ? "Distance from the reference, band by band. Zero is a match; above the line your " +
      "mix has more there, below it has less. " + shared + loudness
    : `Each song's tonal balance, tilted ${data.tilt_db_per_octave} dB per octave so a ` +
      "mix reads roughly level and the vertical space goes on what makes them differ " +
      "rather than on the fact that music has more bass than treble. " + shared + loudness;

  // Where the chart stops, and why. Without this the missing top octave reads as a bug.
  if (data.high_hz) {
    $("spectrum-note").textContent +=
      ` Drawn to ${(data.high_hz / 1000).toFixed(0)} kHz, which is as far as the matching ` +
      "engine reasons: above it an MP3's own lowpass can separate two records by 40 dB " +
      "for reasons no control here can change.";
  }
}

const spectrumSizes = new ResizeObserver(() => drawSpectrum());

function drawSpectrum() {
  const data = state.spectrum;
  const canvas = $("spectrum-canvas");
  if (!data || !canvas) return;

  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return; // page hidden; the observer redraws on 0 -> N

  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * ratio)) canvas.width = Math.round(width * ratio);
  if (canvas.height !== Math.round(height * ratio)) canvas.height = Math.round(height * ratio);

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const style = getComputedStyle(document.documentElement);
  const edge = style.getPropertyValue("--edge").trim() || "#232a32";
  const muted = style.getPropertyValue("--muted").trim() || "#8b96a5";

  const pad = { left: 38, right: 10, top: 10, bottom: 22 };
  const plot = {
    x: pad.left,
    y: pad.top,
    w: Math.max(1, width - pad.left - pad.right),
    h: Math.max(1, height - pad.top - pad.bottom),
  };

  const hz = data.hz;
  const lo = Math.log2(hz[0]);
  const hi = Math.log2(hz[hz.length - 1]);
  const xOf = (f) => plot.x + ((Math.log2(f) - lo) / (hi - lo)) * plot.w;
  const [floor, ceiling] = spectrumRange(data);
  const yOf = (db) =>
    plot.y + plot.h * (1 - (db - floor) / Math.max(1e-6, ceiling - floor));

  drawSpectrumGrid(ctx, { plot, xOf, yOf, edge, muted, data, floor, ceiling });

  drawSpectrumGap(ctx, { data, xOf, yOf, style, plot });

  // Drawn in payload order, which puts the reference under the master: the master is the
  // line being judged, so it is the one that must never be hidden by another.
  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();
  for (const curve of spectrumLines(data)) {
    if (!curve.db?.length) continue;
    const how = SPECTRUM_STYLE[curve.key] ?? { colour: "--muted", width: 1.5, dash: [] };
    ctx.strokeStyle = style.getPropertyValue(how.colour).trim() || muted;
    ctx.lineWidth = how.width;
    ctx.setLineDash(how.dash ?? []);
    ctx.lineJoin = "round";
    ctx.beginPath();
    curve.db.forEach((db, i) => {
      const x = xOf(hz[i]);
      const y = yOf(db);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.restore();

  if (state.spectrumHover != null) {
    drawSpectrumCursor(ctx, { plot, xOf, hz, index: state.spectrumHover, muted });
  }
}

function drawSpectrumGrid(ctx, { plot, xOf, yOf, edge, muted, data, floor, ceiling }) {
  ctx.font = "10px ui-monospace, monospace";
  ctx.strokeStyle = edge;
  ctx.fillStyle = muted;
  ctx.lineWidth = 1;

  // Frequency lines. Labelled in the units people say out loud: 2k, not 2000.
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (const f of SPECTRUM_TICKS) {
    const x = Math.round(xOf(f)) + 0.5;
    if (x < plot.x || x > plot.x + plot.w) continue;
    ctx.beginPath();
    ctx.moveTo(x, plot.y);
    ctx.lineTo(x, plot.y + plot.h);
    ctx.stroke();
    ctx.fillText(f >= 1000 ? `${f / 1000}k` : `${f}`, x, plot.y + plot.h + 5);
  }

  // Level lines every 6 dB - one halving, which is the step an ear is used to thinking
  // in. The numbers are relative: every curve was shifted to 0 LUFS, so what they mark is
  // distance between the curves rather than any absolute level.
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const step = spectrumView() === "difference" ? 2 : 6;
  const first = Math.ceil(floor / step) * step;
  for (let db = first; db <= ceiling; db += step) {
    const y = Math.round(yOf(db)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    // On the balance view these are relative levels on a tilted axis, so the absolute
    // number means little and only the spacing matters. On the difference view each one
    // is a real "dB out", which is worth signing.
    ctx.fillText(`${db > 0 ? "+" : ""}${db}`, plot.x - 6, y);
  }

  // The five bands the instrument screen speaks in, named along the top. The two screens
  // are about the same song and should be readable against each other.
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  // Muted rather than the gridline colour: these are labels to be read, and at 10px on a
  // dark panel the gridline grey is legible as a smudge and nothing more.
  ctx.fillStyle = muted;
  ctx.globalAlpha = 0.75;
  for (const band of data.bands ?? []) {
    const from = Math.max(plot.x, xOf(band.low_hz));
    const to = Math.min(plot.x + plot.w, xOf(band.high_hz));
    if (to - from < 34) continue; // no room for the word; better blank than clipped
    ctx.fillText(SPECTRUM_BAND_WORDS[band.band] ?? band.band, (from + to) / 2, plot.y + 1);
  }
  ctx.globalAlpha = 1;
}

const SPECTRUM_BAND_WORDS = {
  low: "weight",
  low_mid: "body",
  high_mid: "mids",
  presence: "presence",
  air: "air",
};

/**
 * Which of the two readings of the same three measurements is on screen.
 *
 * `balance` draws the curves: the shape of each song, which is what you look at to
 * understand a mix. `difference` draws how far each sits from the reference, which is what
 * you look at to decide whether to change something - because on the balance view a 2 dB
 * gap is four pixels tall, and 2 dB is a real mixing decision.
 *
 * Neither summarises the other, which is why this is a switch and not a default.
 */
function spectrumView() {
  return document.querySelector(".spectrum-views .chip.on")?.dataset.view ?? "balance";
}

/** The lines to draw, for whichever view is showing. */
function spectrumLines(data) {
  if (spectrumView() !== "difference") return data.curves;

  const named = (key) => data.curves.find((c) => c.key === key)?.label ?? key;
  const lines = [];
  // Where you started, so the improvement is visible rather than asserted. Dashed and
  // grey, the same as it is on the balance view: the same song should not change costume
  // between two pictures of it.
  if (data.started_db?.length) {
    lines.push({ key: "source", label: `${named("source")} vs reference`, db: data.started_db });
  }
  if (data.remaining_db?.length) {
    lines.push({ key: "master", label: `${named("master")} vs reference`, db: data.remaining_db });
  }
  return lines;
}

/** The vertical range for the view on screen. */
function spectrumRange(data) {
  if (spectrumView() !== "difference") return [data.floor_db, data.ceiling_db];

  // Symmetric about zero, so "too much here" and "too little there" are the same size on
  // screen. An auto-fitted asymmetric range would make a mix that is 6 dB bright look
  // like one that is 1 dB bright.
  //
  // Every point, not a percentile of them. This used to take the 97th percentile to stop
  // one narrow spike setting the scale — which guaranteed that 3% of the curve was
  // outside the chart, and on a well-matched master that 3% was the top octave reaching
  // +51.8 dB inside a chart fitted to ±4. A number drawn nowhere is worse than a spiky
  // axis: the user cannot tell "no difference here" from "off the top of the chart".
  //
  // The reason the spike existed has been removed upstream rather than worked around
  // here. The server no longer sends anything above 16 kHz, because above that an MP3
  // lowpass separates two records by 40-50 dB for reasons nobody can act on.
  const all = [...(data.started_db ?? []), ...(data.remaining_db ?? [])].map(Math.abs);
  if (!all.length) return [-6, 6];

  // Floored so a nearly-matched master still has a readable axis. No cap: a curve that
  // leaves the chart is exactly the failure this replaced.
  //
  // Padded by a decibel before rounding, matching the +/-2 the server gives the Balance
  // view. A point landing exactly on the floor is inside the range and still half
  // outside the picture, because a stroke has width - the line is drawn centred on its
  // coordinate, so the lower half of a 1.5 px stroke falls past the axis.
  const edge = Math.max(4, Math.ceil((Math.max(...all) + 1) / 2) * 2);
  return [-edge, edge];
}

/** The distance still to close, as a filled region rather than two lines to eyeball. */
function drawSpectrumGap(ctx, { data, xOf, yOf, style, plot }) {
  const accent = style.getPropertyValue("--accent").trim() || "#35e08a";

  ctx.save();
  ctx.beginPath();
  ctx.rect(plot.x, plot.y, plot.w, plot.h);
  ctx.clip();

  if (spectrumView() === "difference") {
    // Zero is the reference. Drawn as a solid line rather than another grid rule, because
    // on this view it is not a gridline - it is the thing being aimed at.
    const zero = Math.round(yOf(0)) + 0.5;
    ctx.strokeStyle =
      (style.getPropertyValue("--stem-piano").trim() || "#7aa2f7") + "cc";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(plot.x, zero);
    ctx.lineTo(plot.x + plot.w, zero);
    ctx.stroke();

    // The area still to close, between the master's line and that zero.
    if (data.remaining_db?.length) {
      ctx.beginPath();
      data.remaining_db.forEach((db, i) => {
        const x = xOf(data.hz[i]);
        i ? ctx.lineTo(x, yOf(db)) : ctx.moveTo(x, yOf(db));
      });
      for (let i = data.remaining_db.length - 1; i >= 0; i--) {
        ctx.lineTo(xOf(data.hz[i]), zero);
      }
      ctx.closePath();
      ctx.fillStyle = accent + "22";
      ctx.fill();
    }
    ctx.restore();
    return;
  }

  const master = data.curves.find((c) => c.key === "master");
  const reference = data.curves.find((c) => c.key === "reference");
  if (!master?.db?.length || !reference?.db?.length) {
    ctx.restore();
    return;
  }

  ctx.beginPath();
  master.db.forEach((db, i) => {
    const x = xOf(data.hz[i]);
    i ? ctx.lineTo(x, yOf(db)) : ctx.moveTo(x, yOf(db));
  });
  for (let i = reference.db.length - 1; i >= 0; i--) {
    ctx.lineTo(xOf(data.hz[i]), yOf(reference.db[i]));
  }
  ctx.closePath();
  ctx.fillStyle = accent + "22";
  ctx.fill();
  ctx.restore();
}

function drawSpectrumCursor(ctx, { plot, xOf, hz, index, muted }) {
  const x = Math.round(xOf(hz[index])) + 0.5;
  ctx.strokeStyle = muted;
  ctx.setLineDash([2, 3]);
  ctx.beginPath();
  ctx.moveTo(x, plot.y);
  ctx.lineTo(x, plot.y + plot.h);
  ctx.stroke();
  ctx.setLineDash([]);
}

/**
 * What every curve reads at one frequency, and the gap between the two that matter.
 *
 * The lines answer "roughly where am I"; this answers "by how much", which is the question
 * anybody who is going to *change* something has to ask next. Without it the panel is a
 * picture to nod at rather than a measurement to act on.
 */
function onSpectrumHover(event) {
  const data = state.spectrum;
  const canvas = $("spectrum-canvas");
  if (!data || !canvas) return;

  const box = canvas.getBoundingClientRect();
  const pad = { left: 38, right: 10 };
  const w = Math.max(1, box.width - pad.left - pad.right);
  const share = (event.clientX - box.left - pad.left) / w;
  if (share < 0 || share > 1) return onSpectrumLeave();

  const lo = Math.log2(data.hz[0]);
  const hi = Math.log2(data.hz[data.hz.length - 1]);
  const wanted = 2 ** (lo + share * (hi - lo));

  let index = 0;
  let best = Infinity;
  data.hz.forEach((f, i) => {
    const distance = Math.abs(Math.log2(f) - Math.log2(wanted));
    if (distance < best) [best, index] = [distance, i];
  });

  state.spectrumHover = index;
  drawSpectrum();

  const hz = data.hz[index];
  const label = hz >= 1000 ? `${(hz / 1000).toFixed(1)} kHz` : `${Math.round(hz)} Hz`;
  // The lines actually on screen. Reading `data.curves` here regardless of the view was
  // a defect: on the Difference view it printed three balance figures and named a curve
  // that was not drawn, while the two lines in front of the user went unreported.
  const values = spectrumLines(data)
    .filter((c) => c.db?.length)
    .map((c) => `${escapeText(c.label)} ${c.db[index].toFixed(1)}`)
    .join(" · ");

  // The gap, in the words the rest of the app uses. "More" and "less" rather than a
  // signed number, because the sign of a difference is the thing people reverse.
  const remaining = data.remaining_db?.[index];
  let verdict = "";
  if (remaining != null) {
    const size = Math.abs(remaining);
    verdict =
      size < 0.5
        ? " — matched here"
        : ` — yours has ${size.toFixed(1)} dB ${remaining > 0 ? "more" : "less"} here`;

    // What mastering did to this frequency, in whichever direction it went.
    //
    // This clause used to fire only on an improvement, so a master that had moved 7.7 dB
    // *away* from the reference reported the gap and said nothing about having caused
    // it. On a tool whose whole claim is that it explains itself, a readout that reports
    // only good news is a worse defect than a wrong number — a wrong number gets
    // noticed.
    const started = data.started_db?.[index];
    if (started != null) {
      const was = Math.abs(started);
      const moved = was - size;
      if (moved > 0.5) verdict += ` (was ${was.toFixed(1)} dB out)`;
      else if (moved < -0.5) verdict += ` (mastering widened this from ${was.toFixed(1)} dB)`;
    }
  }

  $("spectrum-readout").textContent = `${label} · ${values}${verdict}`;
}

function onSpectrumLeave() {
  state.spectrumHover = null;
  $("spectrum-readout").textContent = "";
  drawSpectrum();
}

document.addEventListener("DOMContentLoaded", () => {
  const canvas = $("spectrum-canvas");
  if (canvas) {
    canvas.addEventListener("mousemove", onSpectrumHover);
    canvas.addEventListener("mouseleave", onSpectrumLeave);
  }
  for (const chip of document.querySelectorAll(".spectrum-views .chip")) {
    chip.addEventListener("click", () => {
      for (const other of document.querySelectorAll(".spectrum-views .chip")) {
        other.classList.toggle("on", other === chip);
      }
      if (state.spectrum) renderSpectrumKey(state.spectrum);
      drawSpectrum();
    });
  }
});
