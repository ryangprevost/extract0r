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
  // Gain reduction on the bass, keyed to the kick. Its ceiling is the hardest the solver
  // will ever ask for rather than a round number - see `sidechain.MAX_APPLIED_DB`.
  sidechain_db: { min: 0, max: 8, step: 0.1, off: 0 },
};

/** Read what a control is currently set to on a lane. */
function readControl(lane, control) {
  if (control === "gain_db") return lane.gainDb;
  if (control === "sidechain_db") return lane.sidechainDb ?? 0;
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
  } else if (control === "sidechain_db") {
    // No monitor for this one. A duck keyed to the kick needs the kick's times, and the
    // monitor plays six stems without ever having been told where the drums hit. Rather
    // than approximate it with a tremolo, the row says plainly that it is heard on
    // export - which is the same bargain the per-drum dials already make.
    lane.sidechainDb = value;
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
  // What this costs depends entirely on which side the reference comes from, and saying
  // "around half a minute" on a four-second job was both wrong and oddly discouraging.
  // A profile's instruments were measured once, when it was saved; only the user's own
  // stems are read now.
  // Neither route costs the "around half a minute" this used to claim. By the time the
  // button is pressable both sides are already separated, so what is left is reading
  // them: measured at 4.3 s from a profile and 5.0 s from a pair of split references.
  // "About twenty seconds" was true of the twenty-eight-second pair it was measured on
  // and of nothing else. X0R-1403 measured the job at 0.47x the song's length, so a
  // three-and-a-half-minute song is closer to a minute and three quarters - and the
  // estimate now comes from the length of what the user actually loaded.
  const bothSides = !state.profileHasInstruments;
  const wait = Waiting.begin($("instrument-working"), {
    headline: bothSides
      ? "Reading every stem on both sides, end to end, and tracking the vocal's pitch."
      : "Reading your stems and comparing them with the saved profile, which was " +
        "measured when you saved it.",
    estimateSeconds: Waiting.estimate(state.duration, bothSides),
  });
  button.disabled = true;

  try {
    // The budget decides how far a suggestion may go, so it belongs on the request that
    // produces the suggestions rather than only on the render.
    const budget = typeof currentBudget === "function" ? currentBudget() : "nudge";
    const job = await api(
      "/tracks/" + state.trackId + "/reference/instruments?budget=" + budget,
      { method: "POST" },
    );
    const result = await pollJobQuietly(job.job_id, wait.stage);
    state.instruments = result;
    renderInstruments(result);
    $("monitor-note").hidden = !Monitor.available();
    $("instrument-intro").hidden = true;
    button.textContent = "Compare again";
  } catch (error) {
    fail("instrument-error", error);
  } finally {
    wait.done();
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
async function pollJobQuietly(jobId, onProgress) {
  for (;;) {
    const job = await api("/jobs/" + jobId);
    // The server has been sending a stage name and a measured fraction on every one of
    // these polls since the job existed, and this function used to drop both on the
    // floor. Handing them to a caller is the whole of the loading indicator.
    if (onProgress) onProgress(job);
    if (job.state === "succeeded") return job.result;
    if (job.state === "failed") throw new Error(job.error || "The comparison failed.");
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}

/**
 * Point at the drum-by-drum comparison from the top of the screen.
 *
 * It is two disclosures deep - inside the Drums card, inside a second expander - and it
 * has nowhere better to be: it compares your kick with that record's kick, so it cannot
 * exist outside the comparison that produced both. What it can have is a way in from
 * somewhere a user is already looking.
 *
 * Deliberately not shown once it has been run. A signpost to a place you are already
 * standing is clutter, and the drums card carries the findings from then on.
 */
function renderPerDrumSignpost() {
  const host = $("per-drum-signpost");
  if (!host) return;
  const capability = state.perDrum;

  if (!capability || !capability.available || state.perDrumResult) {
    host.hidden = true;
    return;
  }

  host.innerHTML =
    '<span class="signpost-icon" aria-hidden="true">●●●●</span>' +
    "<span><strong>The drums can go one level further.</strong> Your kick against " +
    "their kick, and the snare, cymbals and toms separately — because “the drums " +
    "want more body” cannot say whether the kick needs sub or the snare is thin." +
    "</span>";

  const go = document.createElement("button");
  go.type = "button";
  go.className = "primary small";
  go.textContent = "Take me there";
  go.addEventListener("click", openPerDrum);
  host.appendChild(go);
  host.hidden = false;
}

/** Open both disclosures and put the panel on screen. The three steps, as one. */
function openPerDrum() {
  const panel = document.querySelector(".per-drum");
  if (!panel) return;
  const card = panel.closest("details.instrument");
  if (card) card.open = true;
  panel.open = true;
  // Directly, not inside requestAnimationFrame. Opening a <details> applies
  // synchronously and scrollIntoView forces the layout it needs, so the frame callback
  // bought nothing - and it does not run at all in a backgrounded tab, which is how this
  // was caught: the jump silently did nothing while the pane was hidden.
  panel.scrollIntoView({ block: "center", behavior: "smooth" });
  panel.classList.add("just-opened");
  setTimeout(() => panel.classList.remove("just-opened"), 1600);
}

function renderInstruments(data) {
  const host = $("instruments");
  host.innerHTML = "";

  // Where the reference half came from. Worth a line, because a comparison drawn from a
  // profile is missing exactly one thing a user might go looking for - the ▶ theirs
  // button - and an unexplained absence reads as a bug.
  const source = $("instrument-source");
  if (source) {
    const fromProfile = data.reference_kind === "profile";
    source.hidden = !fromProfile;
    if (fromProfile) {
      source.innerHTML =
        "Compared against the saved profile <strong>" +
        escapeText(data.reference_name || "") +
        "</strong>, whose instruments were measured when it was saved — which is why " +
        "there was no second split to wait for. Its stems cannot be played back: a " +
        "profile keeps the measurements, not the music.";
    }
  }

  // Whether the drums card can offer a second level, and what that would cost. Sent
  // with the comparison even when the answer is no, because "not available, and here is
  // how" belongs on the card rather than nowhere.
  state.perDrum = data.per_drum || null;
  renderPerDrumSignpost();

  for (const instrument of data.instruments || []) {
    const lane = state.lanes.get(instrument.stem);
    // The band-to-filter solve for this stem, already inverted by the server, so the
    // monitor runs the same EQ the export will.
    if (lane && instrument.tone_solver) lane.toneSolver = instrument.tone_solver;

    const card = buildInstrumentCard(instrument);
    // The drums stem is the one place where the stem is not an instrument, so it gains a
    // disclosure holding the four drums inside it. Appended after the card is built, and
    // below the drums' own findings rather than instead of them: those findings are real
    // and they are the ones with a fader behind them today.
    // `typeof`, not `window.PerDrum`. `PerDrum` is a top-level `const` in drums.js, and
    // a top-level `const` in a classic script lives in the script scope rather than on
    // `window` - so the property test was always false and the panel was never built.
    // Every harness passed, because a harness calls `PerDrum.panel()` by name.
    if (instrument.stem === "drums" && typeof PerDrum !== "undefined") {
      const panel = PerDrum.panel(instrument);
      if (panel) card.appendChild(panel);
    }
    host.appendChild(card);
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
/**
 * Which of five situations an instrument is in.
 *
 * Exists because the summary and the card body used to decide this separately, and drifted
 * the moment one of them was corrected: a guitar 58 LU under its own mix got a summary
 * reading "there is almost no guitar in your mix" directly above a body reading "nothing to
 * change, this one already sits where the reference's does". Two answers on one card, and
 * the corrected half made the stale half look authoritative.
 *
 * One function, two callers, no way for them to disagree again.
 */
function instrumentState(instrument) {
  if (!instrument.in_reference) return "not-in-reference";
  // A stem this far under its own mix is what separation leaves behind when the part is
  // not there. `compare` returns nothing for it, and "no differences" is not "no
  // difference" - matching to it would be matching to silence.
  if (instrument.yours?.present === false) return "not-in-yours";

  const moves = instrument.moves || [];
  if (moves.some((m) => m.control && m.confident)) return "has-moves";
  if (moves.some((m) => m.control && !m.confident)) return "flagged-only";
  return "matched";
}

/** Stems whose names take a plural verb: "drums sit", not "drums sits". */
const PLURAL_STEMS = ["drums", "guitar", "other"];

function isPlural(stem) {
  return PLURAL_STEMS.includes(stem);
}

function summariseMoves(instrument) {
  const label = (LABELS[instrument.stem] || instrument.stem).toLowerCase();
  const song = state.songName ? ` in ${state.songName}` : "";
  const plural = isPlural(instrument.stem);

  // Named `situation`, not `state`. Calling it `state` shadowed the global `state` object
  // for this whole function, and the `state.songName` read two lines above then landed in
  // the temporal dead zone — so every instrument threw "Cannot access 'state' before
  // initialization" and the comparison screen rendered the raw error text instead of six
  // cards. It never reached the console, because the caller's try/catch put it on screen
  // instead. A one-word name took out the headline feature of the application.
  const situation = instrumentState(instrument);

  if (situation === "not-in-reference") {
    return `The reference barely plays ${label}, so there is nothing to compare it with.`;
  }

  if (situation === "not-in-yours") {
    // `relative_lufs` is already negative and the sentence already says "under", so the
    // sign is spelled out once and taken off the number.
    const yours = Math.abs(instrument.yours.relative_lufs).toFixed(0);
    const theirs = instrument.reference?.relative_lufs;
    const against =
      typeof theirs === "number"
        ? `, against the reference's ${Math.abs(theirs).toFixed(0)}`
        : "";
    return `There is almost no ${label} in your mix — ${yours} LU under it${against}. ` +
      "Either you did not record this part, or separation filed it under another stem. " +
      "Nothing is suggested, because matching to it would be matching to silence.";
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
    // `tuning` and `density` are deliberately not listed here. The summary names things
    // a user could take, and neither has a control - putting "a tighter vocal" in a
    // sentence that reads "could use..." would promise a dial that does not exist.
  }

  if (!parts.length) {
    // `parts` holds only the confident moves, so an instrument whose every finding was
    // flagged "worth hearing first" would otherwise report itself as matched — the
    // opposite of what the rows underneath say.
    const flagged = (instrument.moves || []).filter((m) => m.control && !m.confident);
    if (situation === "flagged-only") {
      return `Nothing confident to suggest for your ${label}${song}, but ${
        flagged.length === 1 ? "one difference is" : `${flagged.length} differences are`
      } worth hearing before you decide.`;
    }
    return `Your ${label}${song} already ${plural ? "sit" : "sits"} where the ` +
      "reference's does.";
  }
  const list = parts.length === 1
    ? parts[0]
    : parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
  const caps = label.charAt(0).toUpperCase() + label.slice(1);
  // "could use" regardless of number — it reads correctly either way, which is why the
  // ternary that used to compute it had identical arms. Inlined rather than left as a
  // variable that looked like it was deciding something.
  return `${caps}${song} could use ${list}.`;
}

function buildInstrumentCard(instrument) {
  const plural = isPlural(instrument.stem);
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
    // Omitted entirely when the reference half came from a saved profile. There is no
    // audio behind one, so the button could only ever fail - and a disabled control with
    // a tooltip reads as something broken rather than as something a profile never had.
    // The line under the card says where the comparison came from instead.
    (instrument.reference_audio === false
      ? ""
      : '<button class="link" data-hear="theirs" data-stem="' + instrument.stem + '"' +
        (instrument.in_reference ? "" : " disabled") + ">▶ theirs</button>") +
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
  const situation = instrumentState(instrument);
  if (situation === "not-in-reference") {
    moves.innerHTML =
      '<p class="muted small">The reference does not really play this. There is nothing ' +
      "to match to, so your " + label.toLowerCase() + (plural ? " are" : " is") +
      " left alone rather than being " +
      "matched to whatever separation left behind.</p>";
  } else if (situation === "not-in-yours") {
    moves.innerHTML =
      '<p class="muted small">There is almost no ' + label.toLowerCase() + " in your mix " +
      "to compare. Nothing is suggested here, because every suggestion would be asking " +
      "you to match silence to a part the reference actually plays — which is a " +
      "difference of arrangement, not of mixing.</p>";
  } else if (situation === "matched") {
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
  // The caution belongs on a row you could act on. "Worth hearing before you take it"
  // under a finding with no dial is advice about a decision nobody is being offered -
  // it was already wrong on `punch`, and the two observations added for X0R-1320 and
  // X0R-1321 would have inherited it four more times.
  text.innerHTML =
    "<strong>" + move.headline + band + "</strong>" +
    "<em>" + move.detail + "</em>" +
    (move.confident || !move.control
      ? ""
      : '<em class="caution">Worth hearing before you take it.</em>');
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
    if (number === 0) return "center";
    return (number < 0 ? "L" : "R") + Math.abs(number * 100).toFixed(0);
  }
  if (control === "width") return (number * 100).toFixed(0) + "%";
  if (control === "sidechain_db") {
    return number <= 0 ? "none" : "-" + number.toFixed(1) + " dB on each kick";
  }
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
    button.addEventListener("click", () => stopPreview());
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
  // Tidy up the previous audition but *keep* the band. Switching from your snare to the
  // reference's with "presence" selected has to keep playing presence — comparing the
  // same band across the two sides is the entire point of the feature, and this call is
  // the only thing that stood between it and working.
  stopPreview({ keepBand: true });

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

/**
 * Stop whichever side is playing, and put the solo back.
 *
 * `keepBand` is for the one caller that is starting another audition immediately — the
 * band belongs to the comparison, not to one side of it. Everywhere else the band is
 * cleared, because a band left isolated after the music stops is a trap: the next thing
 * played sounds broken for no visible reason.
 */
function stopPreview({ keepBand = false } = {}) {
  clearTimeout(state.previewTimer);
  state.previewTimer = null;

  for (const audio of state.referencePlayers?.values() ?? []) audio.pause();
  if (state.playing) togglePlay();
  // Leaving a lane soloed after an audition means the next thing the user plays is that
  // stem on its own, with no clue why. A band left isolated is the same trap and worse,
  // because a band-limited mix sounds broken rather than merely unexpected.
  for (const lane of state.lanes.values()) lane.solo = false;
  if (!keepBand) {
    state.soloBand = null;
    if (Monitor.available()) Monitor.clearBands();
  }
  applyGains();

  markHearing(null, null);
  document.querySelectorAll(".stop-preview").forEach((b) => (b.hidden = true));
}

/** The monitor key for a reference stem, kept distinct from the lane key for yours. */
function referenceKey(stem) {
  return "ref:" + stem;
}

function referencePlayer(stem) {
  if (!state.referencePlayers) state.referencePlayers = new Map();
  let audio = state.referencePlayers.get(stem);
  if (!audio) {
    audio = new Audio(
      API + "/tracks/" + state.trackId + "/reference/stems/" + stem + "/audio",
    );
    audio.preload = "none";
    audio.crossOrigin = "anonymous";
    audio.addEventListener("ended", () => stopPreview());
    state.referencePlayers.set(stem, audio);

    // Routed through the monitor so the band chips work on this side too. Every control
    // in that chain starts neutral - no EQ, ratio 1, no drive, width 1, unity gain - so
    // attaching a reference does not process it. All it buys is the isolation filters at
    // the end, which is the whole reason the reference goes through the same chain as
    // your own stem rather than a second one built to be different.
    if (Monitor.available()) Monitor.attach(referenceKey(stem), audio);
  }
  return audio;
}

/**
 * Hear one band of whichever side is playing.
 *
 * A finding says "the reference's drums have more presence" and offers a dial. You can
 * already play your drums and play theirs — but presence is one of five bands inside
 * each, and the whole stem is what plays. Deciding whether a finding is real means
 * hearing the band the finding is about.
 *
 * Borrowed from Metric AB, whose filter bank solos the same band on the mix and the
 * reference at once. It is cheap here because all three pieces already existed: the five
 * bands, an audition per side, and a Web Audio chain to hang filters on.
 */
function buildBandStrip(stem) {
  const strip = buildBandChips((band) => selectBand(stem, band));
  strip.dataset.stem = stem;
  return strip;
}

/**
 * The five chips plus "all", wired to whatever wants to hear one band.
 *
 * Split out from `buildBandStrip` for the per-drum level, which solos a kick rather than
 * a stem and so cannot use the lane key the stem version is built around. The chips, the
 * labels and the frequency titles are the same five bands either way, and two copies of
 * that list is how one of them comes to be missing a band.
 */
function buildBandChips(select) {
  const strip = document.createElement("div");
  strip.className = "band-strip";

  const bands = state.instruments?.bands ?? [];
  const chips = [
    { band: "", label: "all", title: "The whole stem." },
    ...bands.map((b) => ({
      band: b.band,
      label: BAND_WORDS[b.band] ?? b.band,
      title: `${Math.round(b.low_hz)}–${Math.round(b.high_hz)} Hz`,
    })),
  ];

  for (const chip of chips) {
    const button = document.createElement("button");
    button.className = "band-chip" + (chip.band === "" ? " on" : "");
    button.dataset.band = chip.band;
    button.textContent = chip.label;
    button.title = chip.title;
    button.addEventListener("click", () => select(chip.band));
    strip.appendChild(button);
  }
  return strip;
}

/**
 * Apply a band to both sides at once.
 *
 * Both, always, even though only one is audible: the chip has to survive switching from
 * "yours" to "theirs" without the user setting it again, because comparing the same band
 * across the two is the entire point of the feature.
 */
function selectBand(stem, band) {
  state.soloBand = band || null;
  if (Monitor.available()) {
    Monitor.setBand(stem, state.soloBand);
    Monitor.setBand(referenceKey(stem), state.soloBand);
  }
  for (const chip of document.querySelectorAll(`.band-strip[data-stem="${stem}"] .band-chip`)) {
    chip.classList.toggle("on", (chip.dataset.band || "") === (band || ""));
  }
}

function markHearing(stem, side) {
  document.querySelectorAll("[data-hear]").forEach((button) => {
    const on = stem !== null && button.dataset.stem === stem && button.dataset.hear === side;
    button.classList.toggle("on", on);
  });

  // The strip belongs to whatever is playing, and only while it plays. A card that is
  // silent showing band chips would be offering a control with nothing to apply it to.
  for (const strip of document.querySelectorAll(".band-strip")) strip.remove();
  if (stem === null) return;

  const players = document.querySelector(
    `[data-hear][data-stem="${stem}"]`,
  )?.closest(".players");
  if (players) players.insertAdjacentElement("afterend", buildBandStrip(stem));
  // Carry the current band onto the strip that was just built, so switching sides keeps
  // the band rather than silently resetting to "all" while the chip still says otherwise.
  if (state.soloBand) selectBand(stem, state.soloBand);
}

/** Show the comparison once there is something to compare, and wire its button once. */
function refreshInstrumentSection() {
  const section = $("instrument-compare");
  if (!section) return;
  // Two ways to have a reference to compare against: one separated just now, or a saved
  // profile that carries the measurements of one separated once, long ago.
  const haveReferenceInstruments =
    state.referenceSeparated || (state.usingProfile && state.profileHasInstruments);
  section.hidden = !(state.referenceLoaded && haveReferenceInstruments);
}

document.addEventListener("DOMContentLoaded", () => {
  const button = $("compare-instruments-btn");
  if (button) button.addEventListener("click", loadInstrumentComparison);
});
