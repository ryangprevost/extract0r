// ──────────────────────────── what each record plays ────────────────────────────
//
// EPIC-13 stage 1, and the oldest thing in this application to reach a screen.
// `analysis/fingerprint.py` has measured the beat grid, where each drum falls across the
// bar, how far from the grid it sits, the swing and the bass duck for weeks, with
// twenty-six tests behind it - and no route ever called it. All of it was built, correct
// and invisible.
//
// **This panel has no controls in it and is not going to get any.** Experiment 2 measured
// that processing gets you tone and never groove: the drum layer moves the tonal gap to a
// reference by at most 0.09 dB and places zero new grid positions. Where a record's hats
// sit against the beat is a fact about a performance, and moving yours there would be
// composition rather than mastering - which is this epic's governing sentence and the
// line X0R-1307 draws.
//
// So the design problem here is the opposite of the usual one. Everything else on this
// screen ends in a dial; this ends in a sentence, and the risk is that a screenful of
// rhythmic differences reads as a to-do list anyway. The answers are to say so in the
// intro, to say so again in the response, and to draw the bar rather than tabulate it -
// a picture invites comparison where a column of deltas invites correction.

const Groove = (() => {
  //: Sixteenths in a bar of four. The histograms come back at this resolution.
  const STEPS = 16;

  //: Mirrors `fingerprint.MIN_GRID_CONFIDENCE`, and a test holds the two in step.
  //:
  //: This is here because of a bug caught while looking at the first real render. The
  //: server's own figures abstain when the grid is below this - "not measured: the beat
  //: grid is below the confidence floor" - but the two percentages this file works out
  //: for itself, kick-on-the-beat and snare-on-the-backbeat, were being printed bare.
  //: They come from counting hits against the *same untrusted grid*, so a screen showing
  //: "kick on the beat 0%" beside six honest abstentions was the one dishonest number in
  //: the panel, and it was the most eye-catching one.
  const MIN_GRID_CONFIDENCE = 0.35;

  const DRUMS = [
    ["kick_histogram", "kick", "var(--stem-bass)"],
    ["snare_histogram", "snare", "var(--stem-vocals)"],
    ["hat_histogram", "hats", "var(--stem-drums)"],
  ];

  function percent(pair) {
    if (!Array.isArray(pair) || !pair[1]) return null;
    return (100 * pair[0]) / pair[1];
  }

  /** A figure, or the reason there isn't one. Never a bare number. */
  function figureLine(label, figure) {
    const row = document.createElement("p");
    row.className = "muted small groove-figure";
    if (!figure || !figure.measured) {
      const why = (figure && (figure.caveat || figure.basis)) || "not enough to go on";
      row.innerHTML = `<strong>${label}</strong> — not measured: ${escapeText(why)}`;
      return row;
    }
    const unit = figure.unit || "";
    row.innerHTML =
      `<strong>${label}</strong> ${figure.value}${escapeText(unit)}` +
      // The sample size travels with the number, because it is the reader's only way to
      // disagree with it.
      (figure.basis ? ` <span class="groove-basis">${escapeText(figure.basis)}</span>` : "") +
      (figure.caveat ? ` <span class="groove-caveat">${escapeText(figure.caveat)}</span>` : "");
    return row;
  }

  /**
   * One drum's placement across the bar, drawn.
   *
   * A picture rather than sixteen numbers, and that is a deliberate choice about what
   * this panel is for: two bars side by side invite "theirs is busier on the offbeats",
   * where two rows of counts invite "mine should say 12 there".
   */
  function barChart(title, mine, theirs) {
    const wrap = document.createElement("div");
    wrap.className = "groove-bars";

    const head = document.createElement("p");
    head.className = "groove-bars-title";
    head.textContent = title;
    wrap.appendChild(head);

    for (const [who, data] of [["yours", mine], ["the reference", theirs]]) {
      if (!Array.isArray(data) || !data.length) continue;
      const peak = Math.max(1, ...data);
      const line = document.createElement("div");
      line.className = "groove-row";
      line.innerHTML =
        `<span class="groove-who">${who}</span>` +
        `<span class="groove-steps">` +
        data
          .slice(0, STEPS)
          .map((count, i) => {
            const height = Math.round((100 * count) / peak);
            // Beats are the 1st, 5th, 9th and 13th sixteenth. Marked, because "on the
            // beat" and "between them" is the only reading this picture is for.
            const onBeat = i % 4 === 0 ? " on-beat" : "";
            return (
              `<span class="groove-step${onBeat}" title="${count} at step ${i + 1}">` +
              `<span style="height:${height}%"></span></span>`
            );
          })
          .join("") +
        `</span>`;
      wrap.appendChild(line);
    }
    return wrap;
  }

  function side(print_, other) {
    const box = document.createElement("div");
    box.className = "groove-side";

    const head = document.createElement("p");
    head.className = "groove-head";
    const key = print_.key ? ` · ${escapeText(print_.key)}` : "";
    head.innerHTML =
      `<strong>${escapeText(print_.name || "this record")}</strong> ` +
      `<span class="muted">${print_.tempo_bpm} BPM · ${print_.beats_per_bar}/4` +
      `${key} · ${print_.bars} bars</span>`;
    box.appendChild(head);

    // Both of these are counts of hits against the beat grid, so neither can be more
    // trustworthy than the grid is. When it is below the floor they abstain in the same
    // words the server uses, rather than printing a confident-looking percentage derived
    // from a lattice nobody believes.
    const trusted = (print_.grid_confidence ?? 0) >= MIN_GRID_CONFIDENCE;
    const untrusted = "the beat grid is below the confidence floor";

    const placement = [
      ["kick on the beat", percent(print_.kick_on_beats), print_.kick_on_beats, "kicks"],
      [
        "snare on the backbeat",
        percent(print_.snare_on_backbeats),
        print_.snare_on_backbeats,
        "snares",
      ],
    ];
    for (const [label, share, counts, noun] of placement) {
      if (share === null) continue;
      box.appendChild(
        figureLine(label, {
          measured: trusted,
          value: share.toFixed(0),
          unit: "%",
          basis: `${counts[0]} of ${counts[1]} ${noun}`,
          caveat: trusted ? "" : untrusted,
        }),
      );
    }
    box.appendChild(figureLine("hats off the beat", print_.hat_offbeat_share));
    box.appendChild(figureLine("swing", print_.swing));

    for (const [drum, spread] of Object.entries(print_.timing || {})) {
      const line = figureLine(`${drum} against the grid`, spread.detrended_ms);
      line.classList.add("groove-timing");
      box.appendChild(line);
    }

    const duck = print_.duck;
    if (duck) {
      const line = figureLine("bass ducking to the kick", duck.excess_db);
      line.classList.add("groove-duck");
      box.appendChild(line);
    }
    return box;
  }

  function render(data) {
    const host = $("groove-body");
    host.innerHTML = "";

    const note = document.createElement("p");
    note.className = "groove-note";
    note.textContent = data.note || "";
    host.appendChild(note);

    if (!data.reference_measured && data.why_no_reference) {
      const why = document.createElement("p");
      why.className = "muted small";
      why.textContent = data.why_no_reference;
      host.appendChild(why);
    }

    // X0R-1319 criterion 4: a histogram is indexed by the bar length, so it means
    // nothing against a bar length nobody measured. `detect_beats_per_bar` reports zero
    // confidence when there is no accent to read - that is what X0R-407 added - and until
    // now that figure was logged and dropped, so these drew bars against an assumption
    // and said nothing about it.
    const resolved = data.yours?.metre_resolved !== false;
    if (resolved) {
      for (const [key, title] of DRUMS.map(([k, label]) => [k, `${label} across the bar`])) {
        host.appendChild(barChart(title, data.yours?.[key], data.reference?.[key]));
      }
    } else {
      const why = document.createElement("p");
      why.className = "groove-note groove-unresolved";
      why.textContent =
        "No bar chart here: nothing in the audio marks where a bar begins, so " +
        (data.yours?.beats_per_bar || 4) +
        " beats to a bar is an assumption rather than a reading. A picture of where each " +
        "drum falls across a bar is only worth drawing once the bar is known - these " +
        "would be the same hits chopped at an arbitrary point. The figures below do not " +
        "depend on it and are still measured.";
      host.appendChild(why);
    }

    const sides = document.createElement("div");
    sides.className = "groove-sides";
    if (data.yours) sides.appendChild(side(data.yours, data.reference));
    if (data.reference) sides.appendChild(side(data.reference, data.yours));
    host.appendChild(sides);
  }

  async function run() {
    const button = $("groove-btn");
    const wait = Waiting.begin($("groove-working"), {
      headline: "Reading where every drum falls, on both sides.",
      // Not measured, unlike the comparison's. Said as a rough shape rather than a
      // figure, because an estimate with nothing behind it should not look like one.
      estimateSeconds: 0,
    });
    $("groove-error").hidden = true;
    button.disabled = true;
    try {
      const job = await api(`/tracks/${state.trackId}/groove`, { method: "POST" });
      const result = await pollJobQuietly(job.job_id, wait.stage);
      render(result);
      $("groove-intro").hidden = true;
      button.textContent = "Read it again";
    } catch (error) {
      fail("groove-error", error);
    } finally {
      wait.done();
      button.disabled = false;
    }
  }

  /** Offered once there are stems to read. A reference makes it a comparison, not a
   *  precondition - your own groove is worth seeing on its own. */
  function show() {
    const panel = $("groove");
    if (!panel) return;
    panel.hidden = !(state.trackId && state.lanes.size > 0);
    if (typeof Sections !== "undefined") Sections.render();
  }

  function init() {
    const button = $("groove-btn");
    if (button && !button.dataset.wired) {
      button.dataset.wired = "yes";
      button.addEventListener("click", run);
    }
  }

  return { init, show, run };
})();

document.addEventListener("DOMContentLoaded", () => Groove.init());
