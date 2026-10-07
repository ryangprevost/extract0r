// ──────────────────────────────── say what you want ────────────────────────────────
//
// Ryan's idea: a box you type "I want this song a little bassier" into. The parser is on
// the server, in `app/services/mastering/ask.py`, and its docstring has the reasoning for
// why it is a vocabulary and not a language model.
//
// What lives here is the part that matters on screen, which is **the controls visibly
// move**. A sentence does not open a hidden pipeline: it drives `writeControl`, the same
// function the comparison's own buttons use, so the fader slides, the monitor hears it,
// and the user can drag it back. Nothing is applied that cannot be seen and undone.
//
// The one piece of judgement in this file is the undo. A box that moves six faders at
// once needs it, and it is a snapshot of exactly the controls that moved rather than a
// general undo stack - which is honest about its limits and roughly a hundred lines
// cheaper than one that is not.

const Ask = (() => {
  //: Every control this can be asked to move, as the server names them. Only used to
  //: read the current values out of the lanes - the server decides what is legal.
  const CONTROLS = [
    "gain_db",
    "pan",
    "width",
    "compress_db",
    "tone_low_db",
    "tone_low_mid_db",
    "tone_high_mid_db",
    "tone_presence_db",
    "tone_air_db",
  ];

  //: Where the faders stood when this conversation opened, so a ceiling is measured from
  //: there rather than from wherever the last sentence left things. Reset when a new
  //: track is loaded, not when a reply arrives.
  let baseline = null;
  let history = [];

  function lanesNow() {
    const out = {};
    for (const [stem, lane] of state.lanes) {
      const values = {};
      for (const control of CONTROLS) values[control] = readControl(lane, control);
      out[stem] = values;
    }
    return out;
  }

  function snapshot(changes) {
    const before = {};
    for (const change of changes) {
      const lane = state.lanes.get(change.stem);
      if (!lane) continue;
      before[change.stem] = before[change.stem] || {};
      before[change.stem][change.control] = readControl(lane, change.control);
    }
    return before;
  }

  function restore(before) {
    for (const stem of Object.keys(before)) {
      for (const control of Object.keys(before[stem])) {
        writeControl(stem, control, before[stem][control]);
      }
    }
  }

  // --- the transcript --------------------------------------------------------------

  function line(kind, text) {
    const row = document.createElement("p");
    row.className = "ask-line ask-" + kind;
    row.textContent = text;
    return row;
  }

  function say(node) {
    const log = $("ask-log");
    log.appendChild(node);
    log.hidden = false;
    log.scrollTop = log.scrollHeight;
    return node;
  }

  function chips(suggestions) {
    const wrap = document.createElement("p");
    wrap.className = "ask-chips";
    for (const text of suggestions) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = text;
      chip.addEventListener("click", () => {
        $("ask-input").value = text;
        submit();
      });
      wrap.appendChild(chip);
    }
    return wrap;
  }

  function undoButton(before, heard) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "link ask-undo";
    button.textContent = "Undo that";
    button.addEventListener("click", () => {
      restore(before);
      button.disabled = true;
      button.textContent = "Undone";
      say(line("note", "Put " + heard + " back where it was."));
    });
    return button;
  }

  // --- asking ----------------------------------------------------------------------

  async function submit() {
    const input = $("ask-input");
    const text = input.value.trim();
    if (!text) return;
    if (!state.trackId || state.lanes.size === 0) {
      say(line("reply", "Separate a track first — then there are controls to move."));
      return;
    }

    input.value = "";
    say(line("you", text));

    const lanes = lanesNow();
    if (baseline === null) baseline = lanes;

    let answer;
    try {
      answer = await api("/tracks/" + state.trackId + "/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          lanes,
          baseline,
          // The measurement half of every reply. Sent rather than recomputed: producing
          // it costs about half the song's length, and a question must not cost that.
          comparison: state.instruments || null,
        }),
      });
    } catch (error) {
      say(line("reply", error.message || String(error)));
      return;
    }

    const before = snapshot(answer.changes || []);
    for (const change of answer.changes || []) {
      writeControl(change.stem, change.control, change.to);
    }

    const reply = say(line("reply", answer.reply));
    if ((answer.changes || []).length) {
      reply.appendChild(document.createTextNode(" "));
      reply.appendChild(undoButton(before, answer.heard || "that"));
      history.push({ text, heard: answer.heard, before });
      offerRemaster();
    }
    if ((answer.suggestions || []).length) say(chips(answer.suggestions));
  }

/**
 * A way out of the conversation, once there is something to render. X0R-1418.
 *
 * Ryan asked for this "once its reached a good point", and that phrase is the one part
 * to be careful with: **this box has no opinion about whether a mix is good and should
 * not grow one.** Nothing here measures taste. The honest reading is *once it has done
 * something* - so the button appears after the first applied change and stays, rather
 * than trying to detect a moment that the application cannot see.
 *
 * It clicks the real Master button rather than calling the render itself. That keeps the
 * double-click guard, the disabling and anything added to that path later in one place -
 * and scrolls it into view first, so a render that takes tens of seconds starts where the
 * user is looking instead of somewhere off screen.
 */
function offerRemaster() {
  const log = $("ask-log");
  if (!log || log.querySelector(".ask-remaster")) return;

  const row = document.createElement("p");
  row.className = "ask-line ask-note ask-remaster-row";
  row.textContent = "These only reach the file when you render. ";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "primary small ask-remaster";
  button.textContent = "Master and export";
  button.addEventListener("click", () => {
    const real = $("master-btn");
    if (!real) return;
    real.scrollIntoView({ block: "center" });
    real.click();
  });
  row.appendChild(button);
  say(row);
}

  // --- docking ----------------------------------------------------------------------
  //
  // X0R-1412, from Ryan: *"The chat bot should be on the side of the page accessible as
  // you scroll. like an online help chat on amazon"*. It sits above the instrument
  // comparison, so it scrolls away exactly when somebody is deep in the rows it could
  // help with.
  //
  // **The same panel is moved, not copied.** A second rendering of it would be a second
  // transcript, a second input and a second set of listeners, and the two would disagree
  // the first time anybody undid something. Moving one DOM node keeps all of that at one.
  //
  // **It is not styled as a help widget**, which the card flagged before this was built:
  // it moves real faders and quotes measurements, and a cheerful bubble in the corner
  // would misrepresent what pressing things in it does.
  //
  // **Narrow screens do not dock at all.** A fixed panel over 375 px is the whole screen,
  // so below the layout's own breakpoint the launcher scrolls to the panel where it sits
  // instead - which is the same destination by the honest route.

  const NARROW = 720;

  function docked() {
    const dock = $("ask-dock");
    return dock && !dock.hidden;
  }

  function dock(open) {
    const panel = $("ask-panel");
    const shelf = $("ask-dock");
    const home = $("ask-home");
    const launch = $("ask-launch");
    if (!panel || !shelf || !home) return;

    if (open) {
      shelf.appendChild(panel);
      shelf.hidden = false;
    } else {
      home.after(panel);
      shelf.hidden = true;
    }
    if (launch) {
      launch.setAttribute("aria-expanded", open ? "true" : "false");
      launch.textContent = open ? "Close" : "Say what you want";
    }
  }

  /** The launcher: dock on a wide screen, scroll to it on a narrow one. */
  function toggle() {
    if (window.innerWidth <= NARROW) {
      dock(false);
      const panel = $("ask-panel");
      panel.hidden = false;
      panel.scrollIntoView({ block: "center" });
      $("ask-input")?.focus();
      return;
    }
    const open = !docked();
    dock(open);
    if (open) $("ask-input")?.focus();
  }

  /** A window narrowed while docked would leave the panel covering everything. */
  function onResize() {
    if (window.innerWidth <= NARROW && docked()) dock(false);
  }

  // --- wiring ----------------------------------------------------------------------

  function reset() {
    baseline = null;
    history = [];
    dock(false);
    const log = $("ask-log");
    if (log) {
      log.innerHTML = "";
      log.hidden = true;
    }
  }

  function show() {
    const panel = $("ask-panel");
    if (!panel) return;
    panel.hidden = false;
    const launch = $("ask-launch");
    if (launch) launch.hidden = false;
    if (!$("ask-log").children.length) {
      say(
        line(
          "note",
          "Say what you want and it moves the real controls — the faders slide, you " +
            "hear it straight away, and every reply says what the reference comparison " +
            "makes of what you asked for.",
        ),
      );
      say(chips(EXAMPLES));
    }
  }

  //: Shown before the server has been asked for its vocabulary, so the panel is never
  //: empty on first paint. Replaced by the server's own list once it answers.
  let EXAMPLES = ["a little bassier", "make the guitars pop", "less mud", "wider"];

  function init() {
    const form = $("ask-form");
    if (!form) return;
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submit();
    });

    const launch = $("ask-launch");
    if (launch && !launch.dataset.wired) {
      launch.dataset.wired = "yes";
      launch.addEventListener("click", toggle);
      window.addEventListener("resize", onResize);
    }
    api("/tracks/ask/vocabulary")
      .then((vocabulary) => {
        if (vocabulary && vocabulary.examples) EXAMPLES = vocabulary.examples;
        const help = $("ask-help");
        if (help && vocabulary) {
          help.textContent =
            "Parts: " +
            vocabulary.parts.map((p) => p.label).join(", ") +
            ". Tone: " +
            vocabulary.tone.map((t) => t.label).join(", ") +
            ". Qualities: " +
            vocabulary.qualities.join(", ") +
            ". Sizes: a little, plain, a lot.";
        }
      })
      // A panel that works without its help text is better than one that fails to open
      // because the help text did not arrive.
      .catch(() => {});
  }

  return { init, show, reset, submit, toggle };
})();

document.addEventListener("DOMContentLoaded", () => Ask.init());
