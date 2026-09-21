// The help panel, and the guided tour inside it.
//
// Kept in its own file because it is meant to grow. Every time a control is added or its
// behaviour changes, the explanation for it belongs here rather than in a comment nobody
// reading the app will see - which is the whole point of having somewhere to put it.
//
// The tour is a captioned animation rather than a recorded video, for a reason worth
// stating: a screen recording of this app would be out of date the next time a label
// changes, and nobody re-records a video for a reworded button. This is drawn from the
// same CSS variables as the app, so it follows the theme and never shows a version of the
// interface that no longer exists. Each scene carries its narration as text, so it doubles
// as the script if a voiceover is ever recorded over it.

const TOUR = [
  {
    title: "What this does",
    caption:
      "Give it a song of yours, and a song you wish yours sounded like. It pulls both " +
      "apart into their separate instruments, compares them one by one, and tells you " +
      "what that other song does differently.",
    art: () => `
      <g class="fade-in">
        <rect x="40" y="60" width="150" height="90" rx="8" class="panel" />
        <text x="115" y="95" class="label">your song</text>
        ${wave(60, 120, 110, "var(--stem-guitar)")}
        <rect x="370" y="60" width="150" height="90" rx="8" class="panel" />
        <text x="445" y="95" class="label">a song you love</text>
        ${wave(390, 120, 110, "var(--stem-bass)")}
        <path d="M200 105 L360 105" class="arrow" marker-end="url(#tip)" />
        <text x="280" y="92" class="caption-sm">compare</text>
      </g>`,
  },
  {
    title: "Both at once",
    caption:
      "Drop them both on the first screen. Splitting is the slow part — roughly the " +
      "length of each song, once — so it happens in a single pass rather than making " +
      "you come back and wait a second time.",
    art: () => `
      <g>
        <rect x="70" y="55" width="180" height="100" rx="10" class="drop" />
        <text x="160" y="100" class="label">your song</text>
        <text x="160" y="122" class="caption-sm">drop it here</text>
        <rect x="310" y="55" width="180" height="100" rx="10" class="drop dashed" />
        <text x="400" y="100" class="label">a reference</text>
        <text x="400" y="122" class="caption-sm">optional</text>
        <rect x="200" y="172" width="160" height="30" rx="15" class="cta pulse" />
        <text x="280" y="192" class="cta-text">Split both and compare</text>
      </g>`,
  },
  {
    title: "Six instruments, twice",
    caption:
      "Each song becomes vocals, drums, bass, guitar, piano and whatever is left. Yours " +
      "and theirs, so every instrument has a counterpart to be measured against.",
    art: () => {
      const names = ["vocals", "drums", "bass", "guitar", "piano", "other"];
      const colors = ["vocals", "drums", "bass", "guitar", "piano", "other"];
      return `<g>
        <rect x="30" y="95" width="90" height="30" rx="6" class="panel" />
        <text x="75" y="115" class="label">one song</text>
        <path d="M128 110 L175 110" class="arrow" marker-end="url(#tip)" />
        ${names.map((n, i) => `
          <g class="stagger" style="--i:${i}">
            <rect x="190" y="${28 + i * 28}" width="230" height="20" rx="4"
                  fill="var(--stem-${colors[i]})" opacity="0.18" />
            <rect x="190" y="${28 + i * 28}" width="${70 + i * 22}" height="20" rx="4"
                  fill="var(--stem-${colors[i]})" opacity="0.65" />
            <text x="432" y="${43 + i * 28}" class="caption-sm start">${n}</text>
          </g>`).join("")}
      </g>`;
    },
  },
  {
    title: "What the other song does differently",
    caption:
      "One card per instrument, closed to begin with, each summed up in a sentence. " +
      "Open one and every difference is its own row: the measurement, what it means, " +
      "and a control set to a suggested value.",
    art: () => `
      <g>
        ${["Drums", "Bass", "Vocals"].map((n, i) => `
          <g class="stagger" style="--i:${i}">
            <rect x="45" y="${38 + i * 58}" width="470" height="48" rx="8" class="panel" />
            <text x="62" y="${58 + i * 58}" class="label start">${n}</text>
            <text x="62" y="${76 + i * 58}" class="caption-sm start">
              ${["could use more body, more mids and more presence",
                 "could use less volume and more body",
                 "could use more presence and a tighter spread"][i]}
            </text>
            <rect x="415" y="${48 + i * 58}" width="84" height="24" rx="12" class="cta" />
            <text x="457" y="${64 + i * 58}" class="cta-text sm">Apply all</text>
          </g>`).join("")}
      </g>`,
  },
  {
    title: "A nudge, not a copy",
    caption:
      "Every suggestion is part of the measured gap, never all of it. Two records are " +
      "not two takes of one arrangement, and closing the gap completely gives you a " +
      "master that no longer sounds like your song. You see both numbers and decide.",
    art: () => `
      <g>
        <line x1="70" y1="150" x2="490" y2="150" class="axis" />
        <text x="70" y="172" class="caption-sm start">yours</text>
        <text x="490" y="172" class="caption-sm end">the reference</text>
        <circle cx="70" cy="150" r="7" fill="var(--stem-guitar)" />
        <circle cx="490" cy="150" r="7" fill="var(--stem-bass)" />
        <g class="slide">
          <circle cx="70" cy="150" r="10" class="marker" />
          <text x="70" y="128" class="label">the suggestion</text>
        </g>
        <path d="M70 150 L280 150" class="arrow thick" marker-end="url(#tip)" />
      </g>`,
  },
  {
    title: "Hear it before you render it",
    caption:
      "Move a control and it is audible straight away — no waiting for a master. Each " +
      "side plays from its own busiest stretch, because two songs reach their choruses " +
      "at different points. Twelve seconds, then it stops itself.",
    art: () => `
      <g>
        <rect x="60" y="60" width="180" height="70" rx="8" class="panel" />
        <text x="150" y="88" class="label">yours</text>
        ${wave(75, 110, 150, "var(--stem-guitar)")}
        <rect x="320" y="60" width="180" height="70" rx="8" class="panel" />
        <text x="410" y="88" class="label">theirs</text>
        ${wave(335, 110, 150, "var(--stem-bass)")}
        <g class="blink">
          <circle cx="150" cy="158" r="13" class="cta" />
          <path d="M146 152 L158 158 L146 164 Z" fill="var(--ink)" />
        </g>
        <circle cx="410" cy="158" r="13" class="panel" />
        <path d="M406 152 L418 158 L406 164 Z" fill="var(--muted)" />
      </g>`,
  },
  {
    title: "Then the whole mix",
    caption:
      "Once the instruments sit right, the finished mix gets compared as a whole for the " +
      "last moves — tone, weight, width, loudness. That stage is deliberately separate: " +
      "tone is a thing to match, arrangement is a thing to keep.",
    art: () => `
      <g>
        ${[0, 1, 2, 3, 4, 5].map((i) => `
          <rect x="${60 + i * 24}" y="${120 - i * 4}" width="16" height="${30 + i * 8}"
                rx="3" fill="var(--stem-guitar)" opacity="0.5" class="stagger"
                style="--i:${i}" />`).join("")}
        <path d="M220 120 L270 120" class="arrow" marker-end="url(#tip)" />
        <rect x="285" y="70" width="200" height="100" rx="10" class="panel" />
        <text x="385" y="100" class="label">one mix</text>
        ${wave(300, 135, 170, "var(--accent)")}
      </g>`,
  },
  {
    title: "Export",
    caption:
      "Press Master. It renders the whole chain and hands you an MP3, named after your " +
      "song. Nothing from the reference ends up in the file — it is measured, never " +
      "sampled.",
    art: () => `
      <g>
        <rect x="200" y="50" width="160" height="34" rx="17" class="cta pulse" />
        <text x="280" y="72" class="cta-text">Master</text>
        <path d="M280 96 L280 132" class="arrow" marker-end="url(#tip)" />
        <rect x="195" y="140" width="170" height="52" rx="8" class="panel" />
        <text x="280" y="163" class="label">your song</text>
        <text x="280" y="181" class="caption-sm">[extract0r].mp3</text>
      </g>`,
  },
];

/** A little waveform, drawn from a fixed seed so it does not flicker between renders. */
function wave(x, y, width, color) {
  let d = `M${x} ${y}`;
  let seed = 7;
  for (let i = 0; i <= width; i += 5) {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    const h = ((seed / 2147483648) * 2 - 1) * 16;
    d += ` L${x + i} ${y + h}`;
  }
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"
           stroke-linejoin="round" opacity="0.85" />`;
}

const HELP_REFERENCE = [
  {
    heading: "The short version",
    body: `
      <p>Upload your song and a song you want it to sound more like. Both get split into
        their instruments. You are then shown, instrument by instrument, what the other
        song does differently — and you take the suggestions you agree with.</p>
      <p>Nothing is applied until you say so, and everything can be undone.</p>`,
  },
  {
    heading: "Why the suggestions are smaller than the measurements",
    body: `
      <p>Each row shows two numbers: the gap that was measured, and what is being offered.
        The second is deliberately smaller.</p>
      <p>Two records are not two takes of the same arrangement. A reference whose guitars
        sit nine decibels hotter than yours may simply be a wall-of-guitars record where
        yours is not, and "correcting" that replaces your arrangement with someone else's.
        The sliders reach further than the suggestions do, so you can go the rest of the
        way when your ears say so.</p>`,
  },
  {
    heading: "What the five tone bands mean",
    body: `
      <table class="help-table">
        <tr><td><b>weight</b></td><td>20–120 Hz</td>
            <td>Sub and the bottom of the kick. Felt more than heard.</td></tr>
        <tr><td><b>body</b></td><td>120–500 Hz</td>
            <td>Where bass notes and the warmth of most instruments live. Too much is
                mud; too little is thin.</td></tr>
        <tr><td><b>mids</b></td><td>500 Hz–3 kHz</td>
            <td>The part your ear is most sensitive to. Vocals, snare, guitar body.</td></tr>
        <tr><td><b>presence</b></td><td>3–8 kHz</td>
            <td>Clarity and the sense of a mix being in front of you.</td></tr>
        <tr><td><b>air</b></td><td>8–16 kHz</td>
            <td>Sheen on cymbals and breath on vocals. Sparkle, not definition.</td></tr>
      </table>`,
  },
  {
    heading: "Rows marked “worth hearing before you take it”",
    body: `
      <p>Some differences are real measurements that still make poor advice. A vocal stem
        holds almost nothing below 120 Hz — correctly, because a voice does not live
        there — so lifting that band mostly lifts whatever leaked in from the kick.</p>
      <p>Those rows are still shown, because the measurement is true, but
        <b>Apply all</b> leaves them alone. Take them one at a time, after listening.</p>`,
  },
  {
    heading: "What the preview does and does not tell you",
    body: `
      <p>Moving a control is audible immediately. The preview runs the same band gains the
        export will, so the <i>amount</i> is right.</p>
      <p>It is still a preview. The filters are the browser's rather than the ones used for
        the render, the compressor is an approximation, and none of the whole-mix stage is
        in it — that happens to the sum, after this point. Press <b>Master</b> for the
        real thing.</p>`,
  },
  {
    heading: "An instrument the reference does not play",
    body: `
      <p>Separation returns a stem for every instrument it knows about, whether or not the
        song contains one. A record with no piano still yields a piano stem — forty-odd
        decibels below its own mix, made of whatever leaked in.</p>
      <p>Those are detected and left alone. Matching to them would ask for a huge cut and
        silence a part you actually played.</p>`,
  },
  {
    heading: "The reference is analysed, never sampled",
    body: `
      <p>Its tonal balance, loudness and stereo image are measured. No audio from it
        reaches your export. You can play its separated stems to compare them with yours,
        and that is playback only — there is no path from those bytes into a master.</p>`,
  },
];

/** Build the help panel and the tour once, then reuse it. */
function helpMarkup() {
  return `
    <div class="help">
      <h2>How to use extract0r studio</h2>

      <div class="tour" id="tour">
        <svg viewBox="0 0 560 220" class="tour-stage" id="tour-stage"
             role="img" aria-labelledby="tour-caption">
          <defs>
            <marker id="tip" viewBox="0 0 10 10" refX="8" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0 0 L10 5 L0 10 z" fill="var(--muted)" />
            </marker>
          </defs>
        </svg>
        <div class="tour-bar">
          <button class="ghost small" id="tour-back" aria-label="Previous step">‹</button>
          <button class="primary small" id="tour-play">Pause</button>
          <button class="ghost small" id="tour-next" aria-label="Next step">›</button>
          <div class="tour-dots" id="tour-dots"></div>
        </div>
        <h3 class="tour-title" id="tour-title"></h3>
        <p class="tour-caption" id="tour-caption"></p>
      </div>

      ${HELP_REFERENCE.map(
        (s) => `<section class="help-section">
                  <h3>${s.heading}</h3>${s.body}
                </section>`,
      ).join("")}
    </div>`;
}

const tour = { index: 0, timer: null, playing: true };

function showScene(index) {
  const scene = TOUR[((index % TOUR.length) + TOUR.length) % TOUR.length];
  tour.index = TOUR.indexOf(scene);

  const stage = document.getElementById("tour-stage");
  if (!stage) return;
  // Keep the <defs> and replace everything after it, so the arrow marker survives.
  const defs = stage.querySelector("defs");
  stage.innerHTML = "";
  stage.appendChild(defs);
  stage.insertAdjacentHTML("beforeend", scene.art());

  document.getElementById("tour-title").textContent = scene.title;
  document.getElementById("tour-caption").textContent = scene.caption;
  document.querySelectorAll("#tour-dots button").forEach((dot, i) => {
    dot.classList.toggle("on", i === tour.index);
    dot.setAttribute("aria-current", i === tour.index ? "step" : "false");
  });
}

function tourStep(by) {
  showScene(tour.index + by);
  if (tour.playing) restartTourTimer();
}

function restartTourTimer() {
  clearInterval(tour.timer);
  // Long enough to read the caption without it feeling like a slideshow on rails.
  tour.timer = setInterval(() => showScene(tour.index + 1), 7000);
}

function setTourPlaying(playing) {
  tour.playing = playing;
  const button = document.getElementById("tour-play");
  if (button) button.textContent = playing ? "Pause" : "Play";
  if (playing) restartTourTimer();
  else clearInterval(tour.timer);
}

function openHelp() {
  const body = document.getElementById("modal-body");
  body.innerHTML = helpMarkup();

  const dots = document.getElementById("tour-dots");
  dots.innerHTML = TOUR.map(
    (s, i) => `<button aria-label="Step ${i + 1}: ${s.title}"></button>`,
  ).join("");
  [...dots.children].forEach((dot, i) =>
    dot.addEventListener("click", () => {
      setTourPlaying(false);
      showScene(i);
    }),
  );

  document.getElementById("tour-back").addEventListener("click", () => tourStep(-1));
  document.getElementById("tour-next").addEventListener("click", () => tourStep(1));
  document.getElementById("tour-play").addEventListener("click", () =>
    setTourPlaying(!tour.playing),
  );

  // Someone who opens help while a preview is playing wants to read, not to listen.
  if (typeof stopPreview === "function") stopPreview();

  showScene(0);
  setTourPlaying(true);
  document.getElementById("modal").showModal();
}

// The tour is animation on a timer; leaving it running behind a closed dialog would keep
// the page busy for no one's benefit.
document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("modal");
  if (modal) modal.addEventListener("close", () => clearInterval(tour.timer));

  for (const id of ["help-btn", "help-link"]) {
    const button = document.getElementById(id);
    if (button) button.addEventListener("click", (event) => {
      event.preventDefault();
      openHelp();
    });
  }
});
