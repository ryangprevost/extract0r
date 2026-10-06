// ─────────────────────────────── waiting well ───────────────────────────────
//
// Every long job on this screen used to be a sentence and a pulsing dot. The sentence
// was written before the job started and never changed, so the only thing on screen
// during a ninety-second wait was a dot going on and off. Twice now the honest reading
// of that has been "it has hung".
//
// This is the other half of `jobs/stages.py` on the server. That module measured what
// each stage costs and made the fractions arithmetic; this one puts them where they can
// be read, and adds the two things a fraction cannot give:
//
//   * **the stage's own words**, which the page was throwing away. The server has always
//     sent "measuring the reference's" and then "tracking the vocal's pitch"; nothing
//     ever displayed them. Seeing the words change is what tells somebody it is alive.
//   * **a clock counting up**, against an estimate that scales with their song. A bar
//     that is honestly stuck at 25% for forty seconds still needs something moving
//     beside it, and the choice is between a number that is true and a fraction that is
//     invented. This picks the number.
//
// What it deliberately does not do is creep the bar between stages. Interpolating toward
// a boundary the page has not been told about would be inventing progress, which is the
// exact fault being fixed.

const Waiting = (() => {
  //: Wall clock per second of audio for a two-sided instrument comparison, CPU.
  //: **Must match `SECONDS_PER_SECOND_OF_AUDIO` in `app/jobs/stages.py`**, and a test
  //: reads this file to check that it does - a constant in two languages drifts
  //: otherwise, and the half that drifts is always the one nobody runs.
  const SECONDS_PER_SECOND_OF_AUDIO = 0.5;

  //: What a saved profile saves: the reference half of the measurement. From the same
  //: run - 23.57 s of a 98.75 s job.
  const PROFILE_SHARE = 0.76;

  function clock(seconds) {
    const whole = Math.max(0, Math.round(seconds));
    if (whole < 60) return whole + "s";
    const minutes = Math.floor(whole / 60);
    return minutes + "m " + String(whole % 60).padStart(2, "0") + "s";
  }

  /** Roughly how long a comparison takes on a song this long. */
  function estimate(durationSeconds, bothSides) {
    if (!durationSeconds) return 0;
    const share = bothSides ? 1 : PROFILE_SHARE;
    return durationSeconds * SECONDS_PER_SECOND_OF_AUDIO * share;
  }

  /**
   * Turn one element into an indicator, and hand back something to drive it.
   *
   * `headline` is what the job is for, in the user's terms, and does not change.
   * `estimateSeconds` of 0 means no estimate is offered - which is the right answer
   * when the length is unknown, and better than a guess presented as a figure.
   */
  function begin(element, { headline, estimateSeconds = 0 } = {}) {
    if (!element) return { stage() {}, done() {} };

    element.innerHTML =
      '<span class="wait-head"></span>' +
      '<span class="wait-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100">' +
      '<span class="wait-fill"></span></span>' +
      '<span class="wait-stage"></span>';
    element.hidden = false;
    element.classList.add("waiting");
    // Announced once rather than on every tick: a live region that re-reads a clock
    // every 250 ms is unusable with a screen reader on.
    element.setAttribute("aria-busy", "true");

    const head = element.querySelector(".wait-head");
    const bar = element.querySelector(".wait-bar");
    const fill = element.querySelector(".wait-fill");
    const stage = element.querySelector(".wait-stage");

    head.textContent = headline || "Working…";

    const startedAt = Date.now();
    let fraction = 0;
    let message = "";
    let over = false;

    function paint() {
      const elapsed = (Date.now() - startedAt) / 1000;
      fill.style.width = (fraction * 100).toFixed(1) + "%";
      bar.setAttribute("aria-valuenow", Math.round(fraction * 100));

      let right = clock(elapsed) + " so far";
      if (estimateSeconds) {
        if (elapsed > estimateSeconds * 1.15) {
          // Past the estimate is exactly when a user needs telling, and exactly when
          // most progress UI goes quiet. Say it, once, and keep the clock running.
          over = true;
          right += " — longer than expected, still going";
        } else {
          right += " of about " + clock(estimateSeconds);
        }
      }
      stage.textContent = message ? message + " · " + right : right;
      bar.classList.toggle("wait-over", over);
    }

    paint();
    const ticking = setInterval(paint, 250);

    return {
      /** What the server last said about itself. */
      stage(job) {
        if (!job) return;
        // Monotonic. A later stage reporting a lower fraction would be a bug on the
        // server, and a bar that goes backwards reads as one on the page either way.
        if (typeof job.progress === "number") {
          fraction = Math.max(fraction, Math.min(1, job.progress));
        }
        if (job.message) message = job.message;
        paint();
      },
      done() {
        clearInterval(ticking);
        element.classList.remove("waiting");
        element.removeAttribute("aria-busy");
        element.hidden = true;
      },
    };
  }

  return { begin, estimate, clock, SECONDS_PER_SECOND_OF_AUDIO, PROFILE_SHARE };
})();
