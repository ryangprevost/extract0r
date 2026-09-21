// Instrument by instrument: your bass against that song's bass.
//
// The whole-mix comparison can only ever move the sum. It can see that the reference has
// more low end and it cannot see whether that means the bass should come up or the kick
// needs weight, so it tilts everything and takes the bass guitar with it. This screen
// compares each instrument with its counterpart, and every difference it finds becomes
// its own control instead of a checkbox on an opaque matching pass.
//
// Everything here writes into the same lane state the mixer and the export already read,
// so a move taken on this screen is audible immediately through the monitor and is in the
// file when Master is pressed. There is deliberately no second copy of the settings: two
// copies of a number is two numbers, and one of them is always out of date.

// The chip beside a tone headline. It shows the frequency range rather than the band's
// name, because the name is already in the headline - "Less air than the reference's
// drums" followed by a chip reading AIR says the same thing twice. The range does not.
// The words the summary uses for each band. The chip beside a row shows the frequency
// range instead, because there the headline has already named the band.
const BAND_WORDS = {
  low: "weight",
  low_mid: "body",
  high_mid: "mids",
  presence: "presence",
  air: "air",
};

const BAND_RANGES = {
  low: "20–120 Hz",
  low_mid: "120–500 Hz",
  high_mid: "500 Hz–3 kHz",
  presence: "3–8 kHz",
  air: "8–16 kHz",
};

// Control name as the server sends it -> how it is presented. The ranges match the
// Field() bounds on StemMixSetting; a slider that can ask for something the API rejects
// is a 422 waiting to happen at the only moment the user cares about.
// The sliders deliberately reach further than the suggestions do. A suggestion is half
// the measured gap, capped; the slider lets you go the rest of the way if your ears say
// so. `off` is where the control does nothing, which is what un-applying returns it to.
const MOVE_CONTROLS = {
  gain_db: { min: -6, max: 6, step: 0.1, off: 0 },
  compress_db: { min: 0, max: 8, step: 0.1, off: 0 },
  pan: { min: -1, max: 1, step: 0.01, off: 0 },
  width: { min: 0.6, max: 1.6, step: 0.01, off: 1 },
  tone_low_db: { min: -6, max: 6, step: 0.1, off: 0 },
  tone_low_mid_db: { min: -6, max: 6, step: 0.1, off: 0 },
  tone_high_mid_db: { min: -6, max: 6, step: 0.1, off: 0 },
  tone_presence_db: { min: -6, max: 6, step: 0.1, off: 0 },
  tone_air_db: { min: -6, max: 6, step: 0.1, off: 0 },
};

/** Read what a control is currently set to on a lane. */
function readControl(lane, control) {
  if (control === "gain_db") return lane.gainDb;
  if (control === "compress_db") return lane.compressDb ?? 0;
  if (control === "pan") return lane.pan;
  if (control === "width") return lane.width;
  if (control.startsWith("tone_")) return lane.tone?.[control.slice(5, -3)] ?? 0;
  return 0;
}

/** Set a control on a lane, move the mixer's own fader to match, and make it audible. */
function writeControl(stem, control, value) {
  const lane = state.lanes.get(stem);
  if (!lane) return;

  if (control === "gain_db") {
    lane.gainDb = value;
    syncLaneSlider(stem, "gain", value, (value > 0 ? "+" : "") + value.toFixed(1) + " dB");
    applyGains();
  } else if (control === "pan") {
    lane.pan = value;
    const side = value < 0 ? "L" : "R";
    const label = value === 0 ? "C" : side + Math.abs(value * 100).toFixed(0);
    syncLaneSlider(stem, "pan", Math.round(value * 100), label);
    Monitor.setPan(stem, value);
  } else if (control === "width") {
    lane.width = value;
    syncLaneSlider(stem, "width", Math.round(value * 100), (value * 100).toFixed(0) + "%");
    Monitor.setWidth(stem, value);
  } else if (control === "compress_db") {
    lane.compressDb = value;
    Monitor.setCompression(stem, value);
  } else if (control.startsWith("tone_")) {
    lane.tone[control.slice(5, -3)] = value;
    Monitor.setTone(stem, lane.tone, lane.toneSolver);
  }
  standDownAutomaticMatching();
  updateMasterSummary();
}

/**
 * Taking a move by hand turns the automatic matching off, and says so.
 *
 * The two do the same job by different routes. "Match each instrument separately" derives
 * a level, a curve and a width for every stem and applies all of them; this screen shows
 * the same differences one at a time so they can be taken or left. Running both means the
 * gap gets closed twice - the automatic pass moves the guitar up 3 dB, the move the user
 * took moves it up another 3, and the result is 6 dB out in the direction that was meant
 * to be a correction.
 *
 * The hand-made choice wins, because it is the one the user made on purpose.
 */
function standDownAutomaticMatching() {
  const box = $("per-stem-match");
  if (!box || !box.checked) return;
  box.checked = false;
  $("per-stem-options").hidden = true;
  $("per-stem-note").textContent =
    "Switched off because you are taking these instrument by instrument below. Both at " +
    "once would close the same gap twice. Tick it again to hand the whole job back to " +
    "the automatic match.";
}

/** Keep the mixer's own fader showing the number this screen just set. */
function syncLaneSlider(stem, kind, value, label) {
  const slider = document.querySelector('[data-' + kind + '="' + stem + '"]');
  if (slider) slider.value = value;
  const out = document.querySelector('[data-' + kind + '-out="' + stem + '"]');
  if (out) out.textContent = label;
}

async function loadInstrumentComparison() {
  const button = $("compare-instruments-btn");
  $("instrument-error").hidden = true;
  $("instrument-working").hidden = false;
  button.disabled = true;

  try {
    const job = await api("/tracks/" + state.trackId + "/reference/instruments", {
      method: "POST",
    });
    const result = await pollJobQuietly(job.job_id);
    state.instruments = result;
    renderInstruments(result);
    $("monitor-note").hidden = !Monitor.available();
    $("instrument-intro").hidden = true;
    button.textContent = "Compare again";
  } catch (error) {
    fail("instrument-error", error);
  } finally {
    $("instrument-working").hidden = true;
    button.disabled = false;
  }
}

/**
 * Poll a job to completion without taking the page over.
 *
 * `runJob` switches to the progress screen, which is right for separating a track and
 * wrong for this: the comparison belongs beside the mix it is about, and sending the user
 * to a full-page bar and back would lose their scroll position and their place.
 */
async function pollJobQuietly(jobId) {
  for (;;) {
    const job = await api("/jobs/" + jobId);
    if (job.state === "succeeded") return job.result;
    if (job.state === "failed") throw new Error(job.error || "The comparison failed.");
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}

function renderInstruments(data) {
  const host = $("instruments");
  host.innerHTML = "";

  for (const instrument of data.instruments || []) {
    const lane = state.lanes.get(instrument.stem);
    // The band-to-filter solve for this stem, already inverted by the server, so the
    // monitor runs the same EQ the export will.
    if (lane && instrument.tone_solver) lane.toneSolver = instrument.tone_solver;

    host.appendChild(buildInstrumentCard(instrument));
  }
  wireInstrumentCards();
}

/**
 * One sentence saying what this instrument needs, in the words a person would use.
 *
 * The rows below it are precise and there are up to nine of them per instrument; read
 * end to end that is fifty-odd numbers, which is a spreadsheet rather than advice. The
 * summary is what the card is *for* - you should be able to decide whether to open an
 * instrument without opening it.
 */
function summariseMoves(instrument) {
  const label = (LABELS[instrument.stem] || instrument.stem).toLowerCase();
  const song = state.songName ? ` in ${state.songName}` : "";
  const plural = ["drums", "guitar", "other"].includes(instrument.stem);
  const could = plural ? "could use" : "could use";

  if (!instrument.in_reference) {
    return `The reference barely plays ${label}, so there is nothing to compare it with.`;
  }

  const parts = [];
  for (const move of instrument.moves || []) {
    if (!move.control || !move.confident) continue;
    const up = move.suggested > 0;
    if (move.dimension === "tone") parts.push((up ? "more " : "less ") + BAND_WORDS[move.band]);
    else if (move.dimension === "level") parts.push(up ? "more volume" : "less volume");
    else if (move.dimension === "dynamics") parts.push("a steadier level");
    else if (move.dimension === "width") {
      parts.push(move.suggested > 1 ? "a wider spread" : "a tighter spread");
    }
  }

  if (!parts.length) {
    return `Your ${label}${song} already sits where the reference's does.`;
  }
  const list = parts.length === 1
    ? parts[0]
    : parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
  const caps = label.charAt(0).toUpperCase() + label.slice(1);
  return `${caps}${song} ${could} ${list}.`;
}

function buildInstrumentCard(instrument) {
  const label = LABELS[instrument.stem] || instrument.stem;
  // "Take all" deliberately skips the flagged ones. A row that says "worth hearing before
  // you take it" should not then be taken by a button the user pressed to save time -
  // lifting a band that holds 0.04% of a vocal is exactly the move somebody would regret
  // having made in bulk. They stay one click away, individually.
  const actionable = (instrument.moves || []).filter(
    (move) => move.control && move.confident,
  );
  const flagged = (instrument.moves || []).filter(
    (move) => move.control && !move.confident,
  ).length;

  // A <details> rather than a div: six instruments' worth of rows open at once is a wall
  // of numbers, and the summary in the <summary> is meant to be enough to decide with.
  // Closed to begin with, for the same reason.
  const card = document.createElement("details");
  card.className = "instrument";
  card.dataset.stem = instrument.stem;

  const head = document.createElement("summary");
  head.className = "instrument-head";
  head.innerHTML =
    '<span class="instrument-title">' +
    "<strong>" + label + "</strong>" +
    '<span class="instrument-summary">' + summariseMoves(instrument) + "</span>" +
    "</span>";

  // The bulk actions sit on the header, so an instrument can be taken whole without ever
  // being opened - which is the point of summarising it.
  const bulk = document.createElement("div");
  bulk.className = "instrument-bulk";
  bulk.innerHTML =
    (actionable.length
      ? '<button class="primary small apply-all" data-stem="' + instrument.stem + '">' +
        "Apply all " + actionable.length + "</button>" +
        '<button class="link reset-stem" data-stem="' + instrument.stem + '" hidden>' +
        "undo</button>"
      : "") +
    '<span class="players">' +
    '<button class="link" data-hear="yours" data-stem="' + instrument.stem + '">' +
    "▶ yours</button>" +
    '<button class="link" data-hear="theirs" data-stem="' + instrument.stem + '"' +
    (instrument.in_reference ? "" : " disabled") + ">▶ theirs</button>" +
    '<button class="link stop-preview" hidden>■ stop</button>' +
    "</span>";
  head.appendChild(bulk);
  card.appendChild(head);

  const numbers = document.createElement("p");
  numbers.className = "muted small instrument-numbers";
  numbers.innerHTML = describeNumbers(instrument)
    + (flagged ? "<br />" + flagged + " suggestion(s) below are worth hearing first, so "
      + "&ldquo;apply all&rdquo; leaves them alone." : "");
  card.appendChild(numbers);

  const moves = document.createElement("div");
  moves.className = "moves";
  if (!instrument.in_reference) {
    moves.innerHTML =
      '<p class="muted small">The reference does not really play this. There is nothing ' +
      "to match to, so your " + label.toLowerCase() + " is left alone rather than being " +
      "matched to whatever separation left behind.</p>";
  } else if (!(instrument.moves || []).length) {
    moves.innerHTML =
      '<p class="muted small">Nothing to change. This one already sits where the ' +
      "reference's does, in every dimension measured.</p>";
  } else {
    for (const move of instrument.moves) moves.appendChild(buildMove(instrument.stem, move));
  }
  card.appendChild(moves);

  return card;
}

function describeNumbers(instrument) {
  const line = (caption, profile) => {
    if (!profile) return caption + " —";
    return caption + " " + profile.relative_lufs.toFixed(1) + " LU in the mix · swings " +
      profile.dynamic_range_db.toFixed(1) + " dB · " + profile.width.toFixed(2) + " wide";
  };
  return line("yours:", instrument.yours) + "<br />" +
    line("reference:", instrument.reference);
}

function buildMove(stem, move) {
  const spec = MOVE_CONTROLS[move.control];

  const row = document.createElement("div");
  row.className = "move sev-" + move.severity;
  row.dataset.stem = stem;
  row.dataset.control = move.control;

  const text = document.createElement("div");
  text.className = "move-text";
  const band = move.band ? ' <span class="band">' + BAND_RANGES[move.band] + "</span>" : "";
  // The band chip belongs on the headline's line, not under it: it is part of naming the
  // difference, not a second sentence about it.
  text.innerHTML =
    "<strong>" + move.headline + band + "</strong>" +
    "<em>" + move.detail + "</em>" +
    (move.confident ? "" : '<em class="caution">Worth hearing before you take it.</em>');
  row.appendChild(text);

  const action = document.createElement("div");
  action.className = "move-action";
  if (spec) {
    const slider = document.createElement("input");
    slider.type = "range";
    slider.className = "move-slider";
    slider.min = spec.min;
    slider.max = spec.max;
    slider.step = spec.step;
    slider.value = move.suggested;
    slider.dataset.stem = stem;
    slider.dataset.control = move.control;

    const out = document.createElement("output");
    out.textContent = formatMove(move.control, move.suggested);

    const apply = document.createElement("button");
    apply.className = "primary small move-apply";
    apply.dataset.stem = stem;
    apply.dataset.control = move.control;
    apply.dataset.value = move.suggested;
    apply.dataset.confident = move.confident ? "yes" : "no";
    apply.textContent = "Apply";

    action.append(slider, out, apply);
  } else {
    action.innerHTML = '<span class="muted small">no dial — a note</span>';
  }
  row.appendChild(action);
  return row;
}

function formatMove(control, value) {
  const number = Number(value);
  if (control === "pan") {
    if (number === 0) return "centre";
    return (number < 0 ? "L" : "R") + Math.abs(number * 100).toFixed(0);
  }
  if (control === "width") return (number * 100).toFixed(0) + "%";
  return (number > 0 ? "+" : "") + number.toFixed(1) + " dB";
}

function wireInstrumentCards() {
  // The slider IS the setting. Dragging it applies it, so there is never a state where
  // the number on the screen and the number in the mix disagree.
  document.querySelectorAll(".move-slider").forEach((slider) => {
    slider.addEventListener("input", () => {
      const value = parseFloat(slider.value);
      writeControl(slider.dataset.stem, slider.dataset.control, value);
      slider.parentElement.querySelector("output").textContent =
        formatMove(slider.dataset.control, value);
      refreshMoveButtons();
    });
  });

  // Apply is a toggle. Pressing it again puts the control back where it was, which is
  // the undo that was missing: previously the only way out of a suggestion you disliked
  // was to remember its old value and drag the slider back to it by hand.
  document.querySelectorAll(".move-apply").forEach((button) => {
    button.addEventListener("click", () => {
      const control = button.dataset.control;
      const applied = button.classList.contains("applied");
      const value = applied
        ? (MOVE_CONTROLS[control] || {}).off ?? 0
        : parseFloat(button.dataset.value);
      setMove(button.dataset.stem, control, value);
    });
  });

  document.querySelectorAll(".apply-all").forEach((button) => {
    button.addEventListener("click", () => {
      const selector =
        '.move-apply[data-stem="' + button.dataset.stem + '"][data-confident="yes"]';
      document.querySelectorAll(selector).forEach((one) => {
        if (!one.classList.contains("applied")) one.click();
      });
    });
  });

  document.querySelectorAll(".reset-stem").forEach((button) => {
    button.addEventListener("click", () => {
      const selector = '.move-apply[data-stem="' + button.dataset.stem + '"]';
      document.querySelectorAll(selector).forEach((one) => {
        const control = one.dataset.control;
        setMove(one.dataset.stem, control, (MOVE_CONTROLS[control] || {}).off ?? 0);
      });
    });
  });

  document.querySelectorAll(".stop-preview").forEach((button) => {
    button.addEventListener("click", stopPreview);
  });

  // Every control on the header lives inside a <summary>, where a click would otherwise
  // open or close the panel as well as doing its job. Applying a suggestion should not
  // also collapse the card you were reading.
  document.querySelectorAll(".instrument-head button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
  });

  document.querySelectorAll("[data-hear]").forEach((button) => {
    button.addEventListener("click", () => hear(button.dataset.stem, button.dataset.hear));
  });

  refreshMoveButtons();
}

/** Set one control, move its slider to match, and refresh the buttons. */
function setMove(stem, control, value) {
  writeControl(stem, control, value);
  const slider = document.querySelector(
    '.move-slider[data-stem="' + stem + '"][data-control="' + control + '"]',
  );
  if (slider) {
    slider.value = value;
    slider.parentElement.querySelector("output").textContent = formatMove(control, value);
  }
  refreshMoveButtons();
}

/**
 * Light up the buttons whose value is already set.
 *
 * Compared within half a slider step rather than exactly. The slider quantises, so a
 * suggestion of +2.43 dB becomes 2.4 the moment it is applied, and an exact comparison
 * would leave the button reading "Apply" forever on a setting that had in fact been
 * applied. That exact bug shipped once on the whole-mix findings.
 */
function refreshMoveButtons() {
  document.querySelectorAll(".move-apply").forEach((button) => {
    const lane = state.lanes.get(button.dataset.stem);
    if (!lane) return;
    const wanted = parseFloat(button.dataset.value);
    const step = (MOVE_CONTROLS[button.dataset.control] || {}).step || 0.1;
    const applied =
      Math.abs(readControl(lane, button.dataset.control) - wanted) <= step / 2 + 1e-9;
    button.textContent = applied ? "Applied ✓" : "Apply";
    button.classList.toggle("applied", applied);
    button.title = applied ? "Click again to undo this one" : "";
  });

  // The per-instrument undo only appears once there is something to undo, and the card
  // shows at a glance whether it has been acted on - which matters more once they are
  // collapsed, because otherwise the only way to tell is to open all six.
  document.querySelectorAll(".instrument").forEach((card) => {
    const stem = card.dataset.stem;
    const applied = card.querySelectorAll(".move-apply.applied").length;
    const undo = card.querySelector(".reset-stem");
    if (undo) undo.hidden = applied === 0;
    card.classList.toggle("has-applied", applied > 0);

    const all = card.querySelector(".apply-all");
    if (all) {
      const offered = card.querySelectorAll('.move-apply[data-confident="yes"]').length;
      all.textContent = applied >= offered && offered > 0
        ? "Applied ✓"
        : "Apply all " + offered;
      all.classList.toggle("applied", applied >= offered && offered > 0);
    }
    void stem;
  });
}

// How long an audition runs before it stops itself. Long enough to hear how a part sits,
// short enough that comparing six instruments is not a five-minute job.
const PREVIEW_SECONDS = 12;

/**
 * Play one side of a pair on its own, so the two can be heard against each other.
 *
 * Each side starts at *its own* busiest stretch, not at zero and not at the same
 * timestamp. Two different songs reach their choruses at different points, so the only
 * thing a shared playhead guarantees is that both are the same distance from their own
 * beginnings - which on a track with a long intro means auditioning two silences.
 */
async function hear(stem, side) {
  await Monitor.resume();
  stopPreview();

  const instrument = (state.instruments?.instruments ?? []).find((i) => i.stem === stem);
  const profile = side === "yours" ? instrument?.yours : instrument?.reference;
  const from = profile?.preview_start_s ?? 0;

  if (side === "yours") {
    // Solo it in the mixer, which is already the thing that decides what is audible. A
    // second, private notion of "what is playing" would drift from the mixer's within
    // about a minute of use.
    for (const [key, lane] of state.lanes) lane.solo = key === stem;
    applyGains();
    seek(from);
    if (!state.playing) await togglePlay();
  } else {
    if (state.playing) await togglePlay();
    const audio = referencePlayer(stem);
    audio.currentTime = from;
    await audio.play().catch(() => {});
  }

  markHearing(stem, side);
  state.previewTimer = setTimeout(stopPreview, PREVIEW_SECONDS * 1000);
  document.querySelectorAll(".stop-preview").forEach((b) => (b.hidden = false));
}

/** Stop whichever side is playing, and put the solo back. */
function stopPreview() {
  clearTimeout(state.previewTimer);
  state.previewTimer = null;

  for (const audio of state.referencePlayers?.values() ?? []) audio.pause();
  if (state.playing) togglePlay();
  // Leaving a lane soloed after an audition means the next thing the user plays is that
  // stem on its own, with no clue why.
  for (const lane of state.lanes.values()) lane.solo = false;
  applyGains();

  markHearing(null, null);
  document.querySelectorAll(".stop-preview").forEach((b) => (b.hidden = true));
}

function referencePlayer(stem) {
  if (!state.referencePlayers) state.referencePlayers = new Map();
  let audio = state.referencePlayers.get(stem);
  if (!audio) {
    audio = new Audio(
      API + "/tracks/" + state.trackId + "/reference/stems/" + stem + "/audio",
    );
    audio.preload = "none";
    audio.addEventListener("ended", stopPreview);
    state.referencePlayers.set(stem, audio);
  }
  return audio;
}

function markHearing(stem, side) {
  document.querySelectorAll("[data-hear]").forEach((button) => {
    const on = stem !== null && button.dataset.stem === stem && button.dataset.hear === side;
    button.classList.toggle("on", on);
  });
}

/** Show the comparison once there is something to compare, and wire its button once. */
function refreshInstrumentSection() {
  const section = $("instrument-compare");
  if (!section) return;
  section.hidden = !(state.referenceLoaded && state.referenceSeparated);
}

document.addEventListener("DOMContentLoaded", () => {
  const button = $("compare-instruments-btn");
  if (button) button.addEventListener("click", loadInstrumentComparison);
});
