// The four drums inside the drums stem: your kick against their kick.
//
// Every other card on this screen compares a stem. The drums row compares three
// instruments averaged together — a kick, a snare and a cymbal playing different things
// in different registers — and the sentence that comes out describes none of them. "The
// reference's drums have 2.1 dB more weight" cannot say whether the kick needs sub or the
// snare is too thin, and those are opposite moves.
//
// This is a second level *inside* the drums card, not four more cards. Four siblings
// would read as nine instruments on a page that a whole sprint was spent making less
// crowded; and the drums stem's own findings are still the only ones with a fader behind
// them, so replacing them would be removing a working feature to add one. A named
// expander, closed to begin with, saying what is inside before it is opened.
//
// It costs a second separation pass per side — about half the audio's length again on
// CPU — which is why it is a button with its price on it rather than something every
// comparison pays for. Both sides are cached on the track afterwards, and the reference
// half can come from a saved profile with no pass at all.
const PerDrum = (() => {
  // The band a finding is about, as a word rather than a key. Same five bands as the
  // stem rows; `BAND_WORDS` and `BAND_RANGES` live in instruments.js and are reused so
  // the two levels cannot end up calling 3–8 kHz different things.
  const LADDER_BANDS = ["low", "low_mid", "high_mid", "presence", "air"];

  // Below this a band is the same on both records. Matches `instrument.SAME_BAND_DB`, so
  // the ladder highlights exactly the gaps the findings below it talk about — a bar drawn
  // as "apart" with no row underneath explaining it is the chart contradicting the text.
  const SAME_BAND_DB = 1.0;

  // Everything auditioning here plays through the monitor so the band chips work, under
  // keys that cannot collide with a lane's or a reference stem's.
  const monitorKey = (drum, side) => `drum:${side}:${drum}`;

  const players = new Map();
  let band = null;       // the band chip currently selected, shared across sides
  let playing = null;    // { drum, side }

  // What has been taken, per drum. The only copy: the export reads it and so does the
  // monitor, so there is no second notion of "what the kick is set to" to drift from
  // this one. A drum with nothing taken has no entry at all, which is what keeps the
  // request empty and the null case exact on the server.
  const taken = new Map();

  // Which controls a per-drum row may offer, and where each one does nothing. The
  // sliders reach further than the suggestions do, exactly as the stem rows' do: a
  // suggestion is a share of the measured gap, and the slider is for when your ears say
  // go the rest of the way.
  const DRUM_CONTROLS = {
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

  /** The expander that goes inside the drums card, or nothing when there is no drums row. */
  function panel(instrument) {
    if (instrument.stem !== "drums") return null;
    const capability = state.perDrum;
    if (!capability) return null;

    const box = document.createElement("details");
    box.className = "per-drum";

    if (!capability.available) {
      // Criterion 9: no expander, no empty rows, no error text — one line saying what
      // would be here and how to get it. A <p>, not a <details>, because there is
      // nothing inside it to disclose.
      const note = document.createElement("p");
      note.className = "muted small per-drum-note";
      note.textContent =
        "Drum by drum — your kick against their kick — is not available on this " +
        "machine. " + (capability.reason || "");
      return note;
    }

    // Already run once this session? Draw the findings rather than the button. Pressing
    // "Compare again" on the stem comparison rebuilds every card including this one, and
    // losing four drums' worth of work - including the dials that were taken, which are
    // still in `taken` and would otherwise have no slider attached to them - to a button
    // about something else is not a trade anybody chose.
    if (state.perDrumResult) {
      render(box, state.perDrumResult);
      box.open = false;
      return box;
    }

    box.appendChild(summaryFor(null, capability));
    box.appendChild(introFor(capability));
    return box;
  }

  function summaryFor(result, capability) {
    const head = document.createElement("summary");
    head.className = "per-drum-head";
    head.innerHTML =
      "<strong>Drum by drum</strong>" +
      '<span class="per-drum-sub">' +
      (result
        ? // Criterion 1, after the fact: how many drums were measured, named.
          `${result.measured} ${result.measured === 1 ? "drum" : "drums"} measured — ` +
          result.drums.map((d) => escapeHtml(d.label)).join(", ")
        : "Your kick against their kick, and the snare, cymbals and toms. " +
          costSentence(capability)) +
      "</span>";
    return head;
  }

  /**
   * What this is about to cost, before it is started.
   *
   * Said in seconds of waiting rather than in passes, and it says which side is already
   * paid for, because "roughly a minute" and "roughly two minutes" are a different
   * decision and the difference is whether a profile is being used.
   */
  function costSentence(capability) {
    if (capability.cached) return "Already split on both sides — this is instant.";
    const seconds = Math.max(Math.round(capability.estimate_s || 0), 1);
    // Pluralised off the number that is actually printed, not off the seconds behind
    // it: 97 seconds rounds to 2 and read "about 2 minute".
    const minutes = Math.round(seconds / 60);
    const spent = seconds >= 90
      ? `about ${minutes} minute${minutes === 1 ? "" : "s"}`
      : `about ${seconds} seconds`;
    const sides =
      capability.sides >= 2
        ? "An extra separation pass on each side"
        : "An extra separation pass on your drums" +
          (capability.reference_kind === "profile"
            ? " — the reference's came with the profile"
            : " — the reference's is already split");
    return `${sides}, ${spent} on this machine.`;
  }

  function introFor(capability) {
    const wrap = document.createElement("div");
    wrap.className = "per-drum-intro";

    const text = document.createElement("p");
    text.className = "muted small";
    text.innerHTML =
      "The drums stem is the one place where the stem is not an instrument. Splitting it " +
      "again gives each drum its own level, tone, evenness and punch — so you can see " +
      "that their kick carries more weight while their snare is the one that is " +
      "brighter, which a single drums row can never tell you. " +
      (capability.reference_audio
        ? "Both sides can be played one drum at a time."
        : "Your own drums can be played one at a time; the reference came from a saved " +
          "profile, which keeps measurements and not music.");
    wrap.appendChild(text);

    const button = document.createElement("button");
    button.className = "primary small per-drum-go";
    button.textContent = "Split and compare";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      run(button);
    });

    const working = document.createElement("p");
    working.className = "muted small working per-drum-working";
    working.hidden = true;

    const error = document.createElement("p");
    error.className = "error per-drum-error";
    error.hidden = true;

    wrap.append(button, working, error);
    return wrap;
  }

  async function run(button) {
    const box = button.closest(".per-drum");
    const working = box.querySelector(".per-drum-working");
    const error = box.querySelector(".per-drum-error");
    error.hidden = true;
    // The server already estimates this one, because it knows how many separation
    // passes are left to pay for and the length of the audio they run on.
    const wait = Waiting.begin(working, {
      headline:
        "Splitting the drums into kick, snare, cymbals and toms. " +
        costSentence(state.perDrum),
      estimateSeconds: state.perDrum.estimate_s || 0,
    });
    button.disabled = true;

    try {
      const budget = typeof currentBudget === "function" ? currentBudget() : "nudge";
      const job = await api(
        "/tracks/" + state.trackId + "/reference/drums?budget=" + budget,
        { method: "POST" },
      );
      const result = await pollJobQuietly(job.job_id, wait.stage);
      state.perDrumResult = result;
      // Only when the reference's own drums were split here. A comparison drawn from a
      // profile already had them, and nothing on this track can be saved into a new one.
      if (result.reference_kind === "stems") state.referenceDrumsSplit = true;
      // Both sides are now on disk, so a second run of this is free. Said on the summary
      // rather than discovered.
      state.perDrum = { ...state.perDrum, cached: true, sides: 0, estimate_s: 0 };
      render(box, result);
    } catch (failure) {
      error.textContent = failure.message || String(failure);
      error.hidden = false;
    } finally {
      wait.done();
      button.disabled = false;
    }
  }

  /**
   * Whether the bass gets out of the kick's way, and the one control for it.
   *
   * The control only goes one way, which the server decides and this just renders: a duck
   * can be added and cannot be taken away, because the bass compressed out of a recording
   * is not in the file any more. When yours already ducks harder than the reference's,
   * the server sends the finding with no `control` and this draws the sentence alone.
   */
  function sidechainRow(move) {
    const row = document.createElement("div");
    row.className = "move sev-" + (move.severity || "slight") + " per-drum-sidechain";

    const head = document.createElement("p");
    head.className = "move-headline";
    head.textContent = move.headline || "";
    row.appendChild(head);

    const detail = document.createElement("p");
    detail.className = "muted small";
    detail.textContent = (move.detail || "").replace(/\*\*/g, "");
    row.appendChild(detail);

    if (!move.control) return row;

    const take = document.createElement("button");
    take.type = "button";
    take.className = "fix";
    take.textContent =
      "Duck the bass " + Number(move.suggested).toFixed(1) + " dB on each kick";
    take.addEventListener("click", () => {
      writeControl("bass", "sidechain_db", Number(move.suggested));
      take.dataset.done = "true";
      take.textContent =
        "Taken — " + Number(move.suggested).toFixed(1) + " dB, heard on export";
    });
    row.appendChild(take);

    const note = document.createElement("p");
    note.className = "muted tiny";
    note.textContent =
      "This one is not audible in the monitor. A duck has to be keyed to the kick's " +
      "times, and the monitor plays six stems without being told where the drums hit — " +
      "so it is applied when you press Master, and the report names it on the bass row.";
    row.appendChild(note);
    return row;
  }

  function render(box, result) {
    box.innerHTML = "";
    box.open = true;
    box.appendChild(summaryFor(result, state.perDrum));

    const caveat = document.createElement("p");
    caveat.className = "muted small per-drum-caveat";
    caveat.textContent = result.bleed_caveat || "";
    box.appendChild(caveat);

    const headline = verdict(result);
    if (headline) {
      const line = document.createElement("p");
      line.className = "per-drum-verdict";
      line.textContent = headline;
      box.appendChild(line);
    }

    // The bass against the kick. Not one of the four drums, and shown with them because
    // this is where both kicks exist as their own files and where somebody is already
    // thinking about the kick. It is drawn whatever the answer is, including "could not
    // tell", because a row that vanishes on an abstention looks like a broken feature.
    for (const move of result.sidechain || []) {
      box.appendChild(sidechainRow(move));
    }

    const heard = document.createElement("p");
    heard.className = "muted small per-drum-heard";
    heard.innerHTML =
      "A dial here is audible straight away <strong>on that drum's own audition</strong> " +
      "- press \u25b6 yours and move it. It is not audible in the mix below, because the " +
      "monitor plays six stems and a kick is not one of them; it reaches the mix when " +
      "you press <strong>Master</strong>, and the report names each drum it moved.";
    box.appendChild(heard);

    box.appendChild(legend());
    for (const drum of result.drums) box.appendChild(drumRow(drum));
    refreshDrumButtons(box);
  }

  /**
   * The two biggest differences across all four drums, as one sentence.
   *
   * This is the thing the feature is for, and until now nobody could say it: a drum bus
   * averages a kick, a snare and a cymbal into one number that describes none of them,
   * so "the reference's drums have more weight" cannot tell you whether that is the
   * kick's sub or the snare's body, and those are opposite moves. Two drums named in one
   * line is the shortest honest form of the answer.
   *
   * Ranked by the measured gap and not by the suggestion, because the suggestion is
   * clamped: a 14 dB level gap and a 4 dB one both offer 3 dB, and the first is the more
   * interesting fact. Flagged findings are left out - a gap past the arrangement
   * threshold is probably two different records rather than a mixing difference, and it
   * should not be the headline.
   */
  function verdict(result) {
    const found = [];
    for (const drum of result.drums || []) {
      if (drum.absent_reason) continue;
      for (const move of drum.moves) {
        if (!move.confident || !move.control) continue;
        if (move.dimension !== "level" && move.dimension !== "tone") continue;
        found.push({ drum: drum.label, move });
      }
    }
    if (!found.length) return "";

    found.sort((a, b) => Math.abs(b.move.measured) - Math.abs(a.move.measured));
    // One per drum, so "their kick, and also their kick" cannot happen - two facts about
    // two instruments is the whole point of splitting the bus up.
    const picked = [];
    for (const one of found) {
      if (picked.some((p) => p.drum === one.drum)) continue;
      picked.push(one);
      if (picked.length === 2) break;
    }

    const many = (label) => label === "cymbals" || label === "toms";
    const say = ({ drum, move }) => {
      const size = Math.abs(move.measured).toFixed(1);
      if (move.dimension === "level") {
        return `their ${drum} ${many(drum) ? "sit" : "sits"} ${size} dB further ` +
          (move.measured > 0 ? "forward" : "back");
      }
      const word = BAND_WORDS[move.band] || move.band;
      return `their ${drum} ${many(drum) ? "have" : "has"} ${size} dB ` +
        `${move.measured > 0 ? "more" : "less"} ${word} (${BAND_RANGES[move.band]})`;
    };

    const sentence = picked.map(say).join(", and ");
    return sentence.charAt(0).toUpperCase() + sentence.slice(1) + ".";
  }

  /** What the two dots on every ladder mean, said once rather than per drum. */
  function legend() {
    const row = document.createElement("p");
    row.className = "muted small ladder-legend";
    row.innerHTML =
      '<span class="ladder-dot yours"></span> yours' +
      '<span class="ladder-dot theirs"></span> the reference' +
      "<span>— each band’s share of that drum’s own energy, so the ladder is " +
      "shape and not volume.</span>";
    return row;
  }

  function drumRow(drum) {
    const row = document.createElement("details");
    row.className = "subdrum";
    row.dataset.drum = drum.drum;

    const head = document.createElement("summary");
    head.className = "subdrum-head";
    head.innerHTML =
      '<span class="subdrum-title">' +
      "<strong>" + escapeHtml(drum.label) + "</strong>" +
      '<span class="subdrum-summary">' + escapeHtml(summarise(drum)) + "</span>" +
      "</span>";
    head.appendChild(playersFor(drum));
    row.appendChild(head);

    if (drum.absent_reason) {
      // Criterion 6: one sentence naming which side is empty and the figures behind it,
      // and no dials at all — not dials at zero. A control set to "no change" reads as
      // something you could change.
      const why = document.createElement("p");
      why.className = "muted small subdrum-absent";
      why.textContent =
        drum.absent_reason.charAt(0).toUpperCase() + drum.absent_reason.slice(1) + ".";
      row.appendChild(why);
      return row;
    }

    row.appendChild(ladder(drum));
    row.appendChild(numbers(drum));

    const moves = document.createElement("div");
    moves.className = "moves";
    if (!drum.moves.length) {
      moves.innerHTML =
        '<p class="muted small">Nothing to change. This one already sits where the ' +
        "reference’s does, in every dimension measured.</p>";
    } else {
      for (const move of drum.moves) moves.appendChild(subMove(drum, move));
    }
    row.appendChild(moves);
    return row;
  }

  /**
   * One sentence per drum, in the words a person would use.
   *
   * Same job as `summariseMoves` one level up and deliberately shorter: there are four of
   * these inside a card that is itself inside a card, and at that depth a paragraph is a
   * wall. You should be able to decide which drum to open without opening any of them.
   */
  function summarise(drum) {
    // Short, not the full sentence. The body already carries the whole reason with its
    // two figures; repeating it verbatim on the closed row made the toms the longest
    // line on a screen about the kick.
    if (drum.absent_reason) {
      if (!drum.in_yours && !drum.in_reference) return "Neither record really plays this.";
      return drum.in_yours
        ? "The reference does not really play this."
        : "Your mix does not really contain this.";
    }
    const parts = [];
    for (const move of drum.moves) {
      if (!move.confident) continue;
      const up = move.suggested > 0;
      if (move.dimension === "tone") parts.push((up ? "more " : "less ") + BAND_WORDS[move.band]);
      else if (move.dimension === "level") parts.push(up ? "more level" : "less level");
      else if (move.dimension === "dynamics") parts.push("a steadier level");
      else if (move.dimension === "width") parts.push(up ? "a wider spread" : "a tighter spread");
    }
    if (!parts.length) {
      const flagged = drum.moves.filter((m) => !m.confident).length;
      if (flagged) {
        return `Nothing confident to suggest, but ${flagged === 1 ? "one difference is" :
          flagged + " differences are"} worth hearing first.`;
      }
      return "Sits where the reference’s does.";
    }
    // Three at most. The rows below name all of them, and a closed row listing six is
    // longer than the thing it was meant to save you opening — which at this depth,
    // four of these inside a card inside a card, is most of the screen.
    const shown = parts.slice(0, 3);
    const rest = parts.length - shown.length;
    // The count joins the list rather than trailing it: "a, b and c, and 4 more" has
            // two conjunctions doing the same job.
    if (rest) shown.push(`${rest} more`);
    const list = shown.length === 1
      ? shown[0]
      : shown.slice(0, -1).join(", ") + " and " + shown[shown.length - 1];
    return `Could use ${list}.`;
  }

  /**
   * Five bands, two dots each, and the distance between them.
   *
   * The findings underneath are precise and there can be seven of them per drum, times
   * four drums — which read end to end is a spreadsheet. This is the shape of the
   * difference at a glance: where the two records agree the dots sit on top of each
   * other, and where they do not the gap is drawn. It is the same comparison the rows
   * below make, not a second one, so the bar highlights at exactly the threshold the
   * rows appear at.
   */
  function ladder(drum) {
    const wrap = document.createElement("div");
    wrap.className = "ladder";
    const yours = drum.yours?.bands || {};
    const theirs = drum.reference?.bands || {};

    // One scale for all five rows of this drum, so the rows can be read against each
    // other. Per-row scaling would make a 0.3 dB gap and a 6 dB gap the same width.
    const values = [];
    for (const key of LADDER_BANDS) {
      if (typeof yours[key] === "number") values.push(yours[key]);
      if (typeof theirs[key] === "number") values.push(theirs[key]);
    }
    if (!values.length) return wrap;
    const low = Math.min(...values);
    const high = Math.max(...values);
    const span = Math.max(high - low, 1);
    const at = (value) => ((value - low) / span) * 100;

    for (const key of LADDER_BANDS) {
      const mine = yours[key];
      const ref = theirs[key];
      if (typeof mine !== "number") continue;

      const line = document.createElement("div");
      line.className = "ladder-row";
      const gap = typeof ref === "number" ? ref - mine : 0;
      if (Math.abs(gap) >= SAME_BAND_DB) line.classList.add("apart");

      const a = at(mine);
      const b = typeof ref === "number" ? at(ref) : a;
      line.innerHTML =
        '<span class="ladder-label">' + (BAND_WORDS[key] || key) + "</span>" +
        '<span class="ladder-track" title="' + (BAND_RANGES[key] || "") + '">' +
        '<span class="ladder-span" style="left:' + Math.min(a, b) + "%;width:" +
        Math.abs(b - a) + '%"></span>' +
        '<span class="ladder-dot yours" style="left:' + a + '%"></span>' +
        (typeof ref === "number"
          ? '<span class="ladder-dot theirs" style="left:' + b + '%"></span>'
          : "") +
        "</span>" +
        '<span class="ladder-gap">' +
        (typeof ref === "number"
          ? (gap > 0 ? "+" : "") + gap.toFixed(1)
          : "—") +
        "</span>";
      wrap.appendChild(line);
    }
    return wrap;
  }

  function numbers(drum) {
    const line = document.createElement("p");
    line.className = "muted small instrument-numbers";
    const say = (caption, profile) => {
      if (!profile) return caption + " —";
      return caption + " " + profile.relative_lufs.toFixed(1) + " LU in the kit · swings " +
        profile.dynamic_range_db.toFixed(1) + " dB · peaks " +
        profile.crest_db.toFixed(1) + " dB over";
    };
    line.innerHTML = say("yours:", drum.yours) + "<br />" + say("reference:", drum.reference);
    return line;
  }

  /**
   * One finding, with the dial that closes it.
   *
   * The same slider-plus-toggle the stem rows use, deliberately: a per-drum move is not
   * a different kind of thing, it is the same kind one level further in. What differs is
   * where it lands. A kick is not a lane, so this writes into `taken` and the export
   * reads it from there, rather than into the mixer.
   */
  function subMove(drum, move) {
    const row = document.createElement("div");
    row.className = "move sev-" + move.severity;
    row.dataset.drum = drum.drum;
    row.dataset.control = move.control;

    const text = document.createElement("div");
    text.className = "move-text";
    const chip = move.band ? ' <span class="band">' + BAND_RANGES[move.band] + "</span>" : "";
    text.innerHTML =
      "<strong>" + escapeHtml(move.headline) + chip + "</strong>" +
      "<em>" + escapeHtml(move.detail) + "</em>" +
      // Only where there is a dial to take - see the same note in instruments.js.
      (move.confident || !move.control
        ? ""
        : '<em class="caution">Worth hearing before you take it.</em>');
    row.appendChild(text);

    const action = document.createElement("div");
    action.className = "move-action";
    const spec = DRUM_CONTROLS[move.control];
    if (spec) {
      const slider = document.createElement("input");
      slider.type = "range";
      slider.className = "move-slider drum-slider";
      slider.min = spec.min;
      slider.max = spec.max;
      slider.step = spec.step;
      // Starts where the suggestion is, not at rest - the same as the stem rows, and
      // for the same reason: the slider's job is to show you the proposal before you
      // decide, and a control sitting at zero next to a button that moves it to -2.7 is
      // two different answers to "what does this row want?". Nothing is applied until
      // the slider is touched or Apply is pressed; once either happens, `taken` wins.
      slider.value = hasTaken(drum.drum, move.control)
        ? readTaken(drum.drum, move.control)
        : move.suggested;
      slider.dataset.drum = drum.drum;
      slider.dataset.control = move.control;

      const out = document.createElement("output");
      out.textContent = formatMove(move.control, slider.value);

      slider.addEventListener("input", () => {
        const value = parseFloat(slider.value);
        writeDrum(drum.drum, move.control, value);
        out.textContent = formatMove(move.control, value);
      });

      const apply = document.createElement("button");
      apply.className = "primary small drum-apply";
      apply.dataset.drum = drum.drum;
      apply.dataset.control = move.control;
      apply.dataset.value = move.suggested;
      apply.dataset.confident = move.confident ? "yes" : "no";
      apply.textContent = "Apply";
      apply.title =
        "Measured " + formatMove(move.control, move.measured) + " apart; this takes " +
        formatMove(move.control, move.suggested) + ", a share of that gap.";
      apply.addEventListener("click", (event) => {
        event.preventDefault();
        const on = apply.classList.contains("applied");
        setDrumMove(drum.drum, move.control, on ? spec.off : parseFloat(apply.dataset.value));
      });

      action.append(slider, out, apply);
    } else {
      action.innerHTML = '<span class="muted small">no dial — a note</span>';
    }
    row.appendChild(action);
    return row;
  }

  // --- hearing one drum on its own ------------------------------------------------------

  function playersFor(drum) {
    const wrap = document.createElement("span");
    wrap.className = "players";

    const mine = document.createElement("button");
    mine.className = "link";
    mine.dataset.side = "source";
    mine.textContent = "▶ yours";
    mine.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      hearDrum(drum, "source", mine);
    });
    wrap.appendChild(mine);

    // Omitted entirely, not disabled, when the reference came from a profile. There is no
    // audio behind one and a disabled control reads as something broken.
    if (drum.reference_audio !== false && drum.in_reference) {
      const ref = document.createElement("button");
      ref.className = "link";
      ref.dataset.side = "reference";
      ref.textContent = "▶ theirs";
      ref.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        hearDrum(drum, "reference", ref);
      });
      wrap.appendChild(ref);
    }

    // Only visible once there is something to undo, and it is the only way back from
    // a set of moves you have decided against - the sliders remember where they were
    // put, not where they started.
    const undo = document.createElement("button");
    undo.className = "link drum-reset";
    undo.textContent = "undo";
    undo.hidden = true;
    undo.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      resetDrum(drum.drum);
    });
    wrap.appendChild(undo);

    // Instant A/B. The two sides start at their own busiest stretch rather than at a
    // shared timestamp - two records reach their choruses at different points - so a
    // flip keeps how far *into* that stretch you are, which is the position that is
    // actually comparable. This is the move a mixing engineer makes forty times in a
    // row, so it is one button and the F key rather than two clicks on two buttons.
    const flip = document.createElement("button");
    flip.className = "link subdrum-flip";
    flip.textContent = "⇄ flip";
    flip.hidden = true;
    flip.title = "Hear the other side from the same place (F)";
    flip.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      flipSides();
    });
    wrap.appendChild(flip);

    const stop = document.createElement("button");
    stop.className = "link subdrum-stop";
    stop.textContent = "■ stop";
    stop.hidden = true;
    stop.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      stopDrum();
    });
    wrap.appendChild(stop);
    return wrap;
  }

  function playerFor(drum, side) {
    const key = monitorKey(drum, side);
    let audio = players.get(key);
    if (!audio) {
      audio = new Audio(
        API + "/tracks/" + state.trackId + "/drums/" + side + "/" + drum + "/audio",
      );
      audio.preload = "none";
      audio.crossOrigin = "anonymous";
      audio.addEventListener("ended", () => stopDrum());
      players.set(key, audio);
      // Through the monitor, so the band chips apply to a kick exactly as they do to a
      // stem. Every control in that chain starts neutral, so routing a drum through it
      // does not process it — all it buys is the isolation filters at the end.
      if (Monitor.available()) Monitor.attach(key, audio);
    }
    return audio;
  }

  async function hearDrum(drum, side, button, offset = null) {
    await Monitor.resume();
    // Anything else making noise stops, including a stem audition started by the card
    // above: two drums at once is not a comparison.
    stopDrum({ keepBand: true });
    if (typeof stopPreview === "function") stopPreview({ keepBand: true });

    const profile = side === "source" ? drum.yours : drum.reference;
    const audio = playerFor(drum.drum, side);
    const start = profile?.preview_start_s ?? 0;
    audio.currentTime = offset === null ? start : start + offset;
    await audio.play().catch(() => {});

    playing = { drum: drum.drum, side };
    const row = button.closest(".subdrum");
    for (const other of document.querySelectorAll(".subdrum .players button.on")) {
      other.classList.remove("on");
    }
    button.classList.add("on");
    for (const chips of document.querySelectorAll(".subdrum .band-strip")) chips.remove();
    for (const stop of document.querySelectorAll(".subdrum-stop")) stop.hidden = true;
    row.querySelector(".subdrum-stop").hidden = false;

    const strip = buildBandChips((pick) => selectDrumBand(drum.drum, pick));
    row.querySelector(".players").insertAdjacentElement("afterend", strip);
    if (band) selectDrumBand(drum.drum, band);

    // Only offered when there is another side to flip to.
    const other = side === "source" ? "reference" : "source";
    const flip = row.querySelector(".subdrum-flip");
    if (flip) flip.hidden = row.querySelector(`[data-side="${other}"]`) === null;

    clearTimeout(state.previewTimer);
    state.previewTimer = setTimeout(() => stopDrum(), PREVIEW_SECONDS * 1000);
  }

  /**
   * Swap to the other side of the pair without losing your place.
   *
   * "Your place" is measured from each side's own preview start, not from zero: the two
   * auditions begin at each recording's own busiest stretch, so the comparable position
   * is how far into that stretch you are. Matching absolute timestamps instead would
   * line up two moments that have nothing to do with each other.
   */
  async function flipSides() {
    if (!playing) return;
    const row = (state.perDrumResult?.drums || []).find((d) => d.drum === playing.drum);
    if (!row || row.reference_audio === false || !row.in_reference) return;

    const here = playerFor(playing.drum, playing.side);
    const from = playing.side === "source" ? row.yours : row.reference;
    const offset = Math.max(here.currentTime - (from?.preview_start_s ?? 0), 0);

    const side = playing.side === "source" ? "reference" : "source";
    const button = document.querySelector(
      `.subdrum[data-drum="${playing.drum}"] [data-side="${side}"]`,
    );
    if (button) await hearDrum(row, side, button, offset);
  }

  /**
   * Hold the chosen band on both sides at once.
   *
   * Both, always, even though only one is audible: the chip has to survive switching from
   * your kick to theirs without being set again, because hearing the same band across the
   * two is the entire point.
   */
  function selectDrumBand(drum, pick) {
    band = pick || null;
    if (Monitor.available()) {
      Monitor.setBand(monitorKey(drum, "source"), band);
      Monitor.setBand(monitorKey(drum, "reference"), band);
    }
    const row = document.querySelector(`.subdrum[data-drum="${drum}"]`);
    for (const chip of row?.querySelectorAll(".band-chip") ?? []) {
      chip.classList.toggle("on", (chip.dataset.band || "") === (band || ""));
    }
  }

  function stopDrum({ keepBand = false } = {}) {
    clearTimeout(state.previewTimer);
    state.previewTimer = null;
    for (const audio of players.values()) audio.pause();
    playing = null;
    for (const button of document.querySelectorAll(".subdrum .players button.on")) {
      button.classList.remove("on");
    }
    for (const stop of document.querySelectorAll(".subdrum-stop")) stop.hidden = true;
    for (const flip of document.querySelectorAll(".subdrum-flip")) flip.hidden = true;
    if (!keepBand) {
      // A band left isolated after the music stops is a trap: the next thing played
      // sounds broken for no visible reason.
      band = null;
      if (Monitor.available()) Monitor.clearBands();
      for (const chips of document.querySelectorAll(".subdrum .band-strip")) chips.remove();
    }
  }

  // --- what has been taken -----------------------------------------------------------

  /**
   * The per-drum moves, in the shape the master request wants.
   *
   * Only the drums something was actually taken on, and only the controls that are not
   * at rest. An entry that is all defaults would still be a move as far as the server is
   * concerned, and the one criterion this card cannot miss is that taking nothing
   * changes nothing.
   */
  function settings() {
    const out = [];
    for (const [drum, controls] of taken) {
      const moved = Object.entries(controls).filter(
        ([control, value]) => value !== (DRUM_CONTROLS[control] || {}).off,
      );
      if (!moved.length) continue;
      out.push(Object.assign({ drum }, Object.fromEntries(moved)));
    }
    return out;
  }

  function readTaken(drum, control) {
    const at = taken.get(drum);
    if (at && control in at) return at[control];
    return (DRUM_CONTROLS[control] || {}).off ?? 0;
  }

  function hasTaken(drum, control) {
    return control in (taken.get(drum) || {});
  }

  /**
   * Set one control on one drum, and make it audible if that drum is playing.
   *
   * Audible on the audition only, which is the honest version rather than a limitation
   * worked around. The monitor plays a mix built from six stems, and a kick does not
   * exist in it as a thing that can be turned up — that is the whole reason this feature
   * needs a render at all. So the dial is heard where it can be heard, on the drum it
   * belongs to, and the panel says where it is not heard rather than leaving the user to
   * work it out from silence.
   */
  function writeDrum(drum, control, value) {
    const at = taken.get(drum) || {};
    at[control] = value;
    taken.set(drum, at);

    const live =
      Monitor.available() && playing && playing.drum === drum && playing.side === "source";
    if (live) {
      const key = monitorKey(drum, "source");
      if (control === "gain_db") Monitor.setGain(key, value);
      else if (control === "pan") Monitor.setPan(key, value);
      else if (control === "width") Monitor.setWidth(key, value);
      else if (control === "compress_db") Monitor.setCompression(key, value);
      else if (control.startsWith("tone_")) {
        const bands = {};
        for (const name of ["low", "low_mid", "high_mid", "presence", "air"]) {
          bands[name] = readTaken(drum, "tone_" + name + "_db");
        }
        Monitor.setTone(key, bands, solverFor(drum));
      }
    }
    refreshDrumButtons();
    // Same rule as the stem rows: a move taken by hand turns the automatic pass off,
    // because both at once closes the same gap twice.
    if (typeof standDownAutomaticMatching === "function") standDownAutomaticMatching();
  }

  /** The band-to-filter solve for one drum, so the monitor runs the render's EQ. */
  function solverFor(drum) {
    const row = (state.perDrumResult?.drums || []).find((d) => d.drum === drum);
    return row?.tone_solver || null;
  }

  /**
   * Light up the buttons whose value is already set, and show the per-drum undo.
   *
   * Compared within half a slider step, not exactly: the slider quantises, so a
   * suggestion of +2.43 dB becomes 2.4 the moment it is applied and an exact comparison
   * would read "Apply" forever on a setting that had in fact been applied. That bug has
   * shipped twice in this application already.
   */
  function refreshDrumButtons(root = document) {
    // Scoped, because `render` calls this on a panel that is not in the document yet:
    // on the redraw path - "Compare again" on the stem comparison rebuilds every card -
    // the panel is built, filled and handed back before anybody appends it. A
    // document-wide query found nothing, so four dials that had been taken came back
    // reading "Apply". Caught by rebuilding the cards in a harness, not by a user.
    for (const button of root.querySelectorAll(".drum-apply")) {
      const { drum, control } = button.dataset;
      const wanted = parseFloat(button.dataset.value);
      const step = (DRUM_CONTROLS[control] || {}).step || 0.1;
      // `hasTaken` first, and that is not belt and braces. Comparing values alone says
      // "Applied ✓" on any row whose suggestion happens to equal the control's rest
      // position - which is not a corner case: the cymbals' pan offered -0.00, because
      // the reference's cymbals are centred, and centre is also where a pan control
      // does nothing. So four untouched dials and an "undo" link appeared on a row
      // nobody had touched. Being taken is a fact about what the user did, not about
      // where the number landed.
      const on =
        hasTaken(drum, control) &&
        Math.abs(readTaken(drum, control) - wanted) <= step / 2 + 1e-9;
      button.textContent = on ? "Applied ✓" : "Apply";
      button.classList.toggle("applied", on);
      button.title = on ? "Click again to undo this one" : button.title;
    }
    for (const row of root.querySelectorAll(".subdrum")) {
      const applied = row.querySelectorAll(".drum-apply.applied").length;
      row.classList.toggle("has-applied", applied > 0);
      const undo = row.querySelector(".drum-reset");
      if (undo) undo.hidden = applied === 0;
    }
    const box = root.closest?.(".per-drum") || root.querySelector?.(".per-drum");
    if (box) box.classList.toggle("has-applied", settings().length > 0);
  }

  function setDrumMove(drum, control, value) {
    writeDrum(drum, control, value);
    const slider = document.querySelector(
      '.drum-slider[data-drum="' + drum + '"][data-control="' + control + '"]',
    );
    if (slider) {
      slider.value = value;
      slider.parentElement.querySelector("output").textContent = formatMove(control, value);
    }
    refreshDrumButtons();
  }

  /** Put every dial on one drum back where it does nothing. */
  function resetDrum(drum) {
    for (const control of Object.keys(DRUM_CONTROLS)) {
      if ((taken.get(drum) || {})[control] === undefined) continue;
      setDrumMove(drum, control, DRUM_CONTROLS[control].off);
    }
  }

  // F flips the pair while a drum is auditioning. Not bound when the user is typing,
  // and not bound to anything else - one key, one job.
  document.addEventListener("keydown", (event) => {
    if (!playing || event.key.toLowerCase() !== "f") return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;
    event.preventDefault();
    flipSides();
  });

  return {
    panel,
    settings,
    stop: stopDrum,
    playing: () => playing,
    // The dials are not lanes, so nothing else on the page knows how to put them back.
    reset: () => {
      for (const drum of [...taken.keys()]) resetDrum(drum);
      taken.clear();
      refreshDrumButtons();
    },
  };
})();
