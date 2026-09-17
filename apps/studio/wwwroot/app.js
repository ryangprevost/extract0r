// Extract0r Studio front end. Vanilla JS on purpose: no build step, no node_modules,
// open the .sln and press F5. Requests go to /api on this origin and the ASP.NET host
// proxies them to the Python service, so there is no CORS to think about.

const $ = (id) => document.getElementById(id);
const API = "/api/v1";

// Stems worth offering for transcription. Vocals produce a pitch list, not tab, and are
// left unselectable until X0R-411 makes that useful - but you can still play them.
const TRANSCRIBABLE = ["bass", "guitar", "piano", "drums", "other"];

// Display order, chosen to read like a score: rhythm section at the bottom, top line up.
const STEM_ORDER = ["vocals", "guitar", "piano", "other", "bass", "drums"];

const LABELS = {
  vocals: "Vocals", drums: "Drums", bass: "Bass",
  guitar: "Guitar", piano: "Piano", other: "Other",
};

// Simple stroke glyphs, one per instrument. Inline so there is no icon font to load and
// they inherit the stem colour via currentColor.
const ICONS = {
  guitar: '<circle cx="8" cy="16" r="5"/><circle cx="8" cy="16" r="1.5"/><path d="M11.6 12.4 19 5"/><path d="M17.4 3.4 20.6 6.6"/>',
  bass: '<ellipse cx="7.5" cy="16.5" rx="4.6" ry="5.2"/><circle cx="7.5" cy="16.5" r="1.3"/><path d="M11 12.8 20 4"/><path d="M18.4 2.4 21.6 5.6"/>',
  drums: '<ellipse cx="12" cy="13" rx="8" ry="3.6"/><path d="M4 13v4c0 2 3.6 3.6 8 3.6s8-1.6 8-3.6v-4"/><path d="M6.5 8.5 10 11.5"/><path d="M17.5 8.5 14 11.5"/>',
  piano: '<rect x="3" y="6" width="18" height="12" rx="1.5"/><path d="M7.5 6v7M12 6v7M16.5 6v7"/>',
  vocals: '<rect x="9" y="3" width="6" height="10" rx="3"/><path d="M6 11a6 6 0 0 0 12 0"/><path d="M12 17v4"/><path d="M9.2 21h5.6"/>',
  other: '<path d="M3 12h2.5l2-6.5L11 18l3-9 1.8 3.5H21"/>',
};

const state = {
  file: null,
  trackId: null,
  duration: 0,
  lanes: new Map(),   // stem -> { audio, canvas, peaks, muted, solo }
  compare: null,      // { before, after, delta_db } for the mastering before/after
  suggestion: null,   // what the reference says this mix needs
  mode: null,         // the starting point the user picked, if any
  showAllFindings: false,
  picked: new Set(),
  tunings: {},
  chosenTuning: {},
  playing: false,
  timing: null,
  page: "master",
  referenceFile: null,
  referenceLoaded: false,
  referenceSeparated: false,
};

// ───────────────────────────────── plumbing ─────────────────────────────────

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return body;
}

async function runJob(jobId, title, hint = "") {
  showOnly("step-progress");
  $("progress-title").textContent = title;
  $("progress-hint").textContent = hint;

  const started = Date.now();
  for (;;) {
    const job = await api(`/jobs/${jobId}`);
    $("progress-fill").style.width = `${Math.round(job.progress * 100)}%`;

    // "queued" on its own reads as a hang. Say what it is waiting for, and show the
    // clock so a long job is visibly progressing even between stage updates.
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const clockLabel = elapsed >= 3 ? `  ·  ${clock(elapsed)}` : "";
    $("progress-message").textContent =
      job.state === "queued"
        ? `waiting for a free worker — another job is running${clockLabel}`
        : `${job.message}${clockLabel}`;

    if (job.state === "succeeded") return job;
    if (job.state === "failed") throw new Error(job.error ?? "The job failed.");
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

const ALL_SECTIONS = [
  "step-upload", "step-progress", "step-stems", "step-master",
  "step-timing", "step-tabs", "step-about", "step-legal",
];

// Which sections each page shows once a track is loaded. The mixer is shared by both
// working pages on purpose - checking a stem by ear matters as much before mastering as
// before transcribing.
const PAGES = {
  master: {
    name: "Mastering",
    title: "Master a track against a reference.",
    lede: "Upload a song, split it into stems, then match its tone and loudness to a " +
          "commercial reference and export a new MP3.",
    loaded: ["step-stems", "step-master"],
  },
  tab: {
    name: "Tablature",
    title: "Split a song into stems and read it back as tab.",
    lede: "Upload a track, listen to each separated part to check it came out clean, " +
          "then pick the ones you want written out as tablature.",
    loaded: ["step-stems", "step-timing", "step-tabs"],
  },
  about: { name: "Capabilities", standalone: "step-about" },
  legal: { name: "Legal", standalone: "step-legal" },
};

function showOnly(...ids) {
  for (const id of ALL_SECTIONS) $(id).hidden = !ids.includes(id);
  $("restart-row").hidden = !state.trackId || ids.includes("step-progress");
}

function goToPage(name) {
  const page = PAGES[name] ?? PAGES.master;
  state.page = name;
  $("page-name").textContent = page.name;
  document.querySelectorAll(".nav-item").forEach((item) => {
    if (item.dataset.page === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  closeNav();

  if (page.standalone) {
    showOnly(page.standalone);
    if (name === "about") renderCapabilities();
    if (name === "legal") renderLegal();
    return;
  }

  $("upload-title").textContent = page.title;
  $("upload-lede").textContent = page.lede;

  // Tabs only appear once something has been transcribed.
  const sections = state.trackId
    ? page.loaded.filter((id) => id !== "step-tabs" || $("tabs").children.length)
    : ["step-upload"];
  showOnly(...sections);
}

function openNav() {
  $("nav").hidden = false;
  $("scrim").hidden = false;
  $("nav-toggle").setAttribute("aria-expanded", "true");
}

function closeNav() {
  $("nav").hidden = true;
  $("scrim").hidden = true;
  $("nav-toggle").setAttribute("aria-expanded", "false");
}

function fail(elementId, error) {
  const node = $(elementId);
  node.textContent = error instanceof Error ? error.message : String(error);
  node.hidden = false;
}

const clock = (seconds) => {
  if (!Number.isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};

// ───────────────────────────────── capabilities ─────────────────────────────

let apiRetry = null;

/**
 * Ask the API what it can do, and keep asking until it answers.
 *
 * This used to run exactly once at page load, so any moment the API was unavailable -
 * a restart, a slow first boot while torch loads - left the page showing "could not
 * reach the API" forever, with no way back except a manual reload. The check now
 * recovers on its own and clears the banner when the API returns.
 */
async function loadCapabilities({ quiet = false } = {}) {
  let caps;
  try {
    // Only the fetch belongs in this try. Rendering failures are not network failures,
    // and conflating them once made a DOM bug masquerade as an unreachable server.
    caps = await api("/capabilities");
  } catch {
    $("backends").innerHTML = '<span class="chip off">API unreachable ✕</span>';
    if (!quiet) {
      fail("upload-error",
        "Cannot reach the Extract0r API yet — it may still be starting up. " +
        "Retrying automatically; no need to reload.");
    }
    if (!apiRetry) apiRetry = setInterval(() => loadCapabilities({ quiet: true }), 3000);
    return false;
  }

  try {
    $("limits").textContent =
      `or click to choose — up to ${caps.limits.max_upload_mb} MB · mp3, wav, flac, m4a, ogg, aiff`;

    // Show what the server actually has, not what it was configured to want. The two
    // differ more often than you would like, and the app silently falls back to stubs.
    $("backends").innerHTML = ["demucs", "basic_pitch", "pyin", "onset_drums", "ffmpeg"]
      .map((name) => {
        const on = caps.installed[name];
        return `<span class="chip ${on ? "on" : "off"}" title="${
          on ? "installed" : "not installed on this server"
        }">${name}${on ? "" : " ✕"}</span>`;
      })
      .join("");

    if (apiRetry) {
      clearInterval(apiRetry);
      apiRetry = null;
    }
    $("upload-error").hidden = true;

    if (!caps.installed.demucs) {
      fail("upload-error",
        "This server has no Demucs installed, so separation will return copies of your " +
        "file rather than real stems. See docs/RUNBOOK.md.");
    }
  } catch (error) {
    // The API is fine; we failed to draw its answer. Say so, and do not block the upload.
    console.error("failed to render capabilities", error);
  }
  return true;
}

async function loadLegal() {
  try {
    const legal = await api("/legal");
    MODALS.terms = MODALS.terms.replace("{{retention}}", legal.retention_hours);
    MODALS.dmca = MODALS.dmca.replace("{{contact}}", legal.dmca_contact);
  } catch {
    /* The modals carry sensible defaults; a missing API must not blank the legal text. */
  }
}

// ───────────────────────────────── upload ───────────────────────────────────

function refreshUploadButton() {
  $("upload-btn").disabled = !(state.file && $("owns").checked && $("personal").checked);
}

function pickFile(file) {
  if (!file) return;
  state.file = file;
  // Set text on existing nodes rather than rewriting the container's innerHTML. The
  // previous version replaced the whole label, which destroyed #limits - and then any
  // later code touching #limits threw on null. That is not a hypothetical: it made the
  // upload pre-check report "the API is not responding" for a perfectly healthy API,
  // every time, because the throw landed in the catch meant for network errors.
  $("dropzone").classList.add("has-file");
  $("dropzone-name").textContent = file.name;
  $("dropzone-hint").textContent =
    `${(file.size / 1024 / 1024).toFixed(1)} MB — click to choose a different file`;
  $("upload-error").hidden = true;
  refreshUploadButton();
}

async function upload() {
  $("upload-error").hidden = true;

  if (!(await loadCapabilities({ quiet: true }))) {
    fail("upload-error",
      "The Extract0r API is not responding, so the upload would fail. It may be " +
      "restarting — this page retries every few seconds and will clear this message " +
      "on its own. If it persists, run scripts/start.ps1.");
    return;
  }

  const form = new FormData();
  form.append("file", state.file);
  form.append("owns_or_licensed", String($("owns").checked));
  form.append("personal_use_only", String($("personal").checked));

  try {
    showOnly("step-progress");
    $("progress-title").textContent = "Uploading…";
    $("progress-message").textContent = state.file.name;
    $("progress-fill").style.width = "5%";

    const track = await api("/tracks", { method: "POST", body: form });
    state.trackId = track.track_id;
    state.duration = track.duration_s ?? 0;

    const job = await api(`/tracks/${track.track_id}/separate`, { method: "POST" });
    await runJob(
      job.job_id,
      "Splitting the track into stems…",
      "Demucs runs on the CPU at roughly twice the length of the audio. The very first " +
      "run also downloads the model, which takes a few minutes more.",
    );

    const separation = await api(`/tracks/${track.track_id}/stems`);
    await buildMixer(separation, track);
  } catch (error) {
    showOnly("step-upload");
    fail("upload-error", error);
  }
}

// ───────────────────────────────── the mixer ────────────────────────────────

async function buildMixer(separation, track) {
  $("sep-backend").textContent =
    `${separation.backend}:${separation.model} · ${track.duration_s}s · ${track.sample_rate} Hz · ${separation.stems.length} stems`;

  const ordered = [...separation.stems].sort(
    (a, b) => STEM_ORDER.indexOf(a.stem) - STEM_ORDER.indexOf(b.stem),
  );
  state.duration = Math.max(state.duration, ...ordered.map((s) => s.duration_s || 0));
  $("duration").textContent = `/ ${clock(state.duration)}`;

  if (!Object.keys(state.tunings).length) {
    state.tunings = await api("/tracks/tunings").catch(() => ({}));
  }
  const tuningOptions = Object.entries(state.tunings)
    .map(([key, t]) => `<option value="${key}">${t.name}</option>`)
    .join("");

  const container = $("lanes");
  container.querySelectorAll(".lane").forEach((n) => n.remove());

  for (const stem of ordered) {
    const canTranscribe = TRANSCRIBABLE.includes(stem.stem);
    const lane = document.createElement("div");
    lane.className = "lane";
    lane.dataset.stem = stem.stem;
    lane.style.setProperty("--lane", `var(--stem-${stem.stem}, var(--stem-other))`);

    lane.innerHTML = `
      <div class="lane-head">
        <span class="lane-icon"><svg viewBox="0 0 24 24">${ICONS[stem.stem] ?? ICONS.other}</svg></span>
        <span>
          <span class="lane-name">${LABELS[stem.stem] ?? stem.stem}</span><br />
          <span class="lane-sub">${stem.duration_s}s</span>
        </span>
        <span class="lane-buttons">
          <button class="tog solo" data-solo="${stem.stem}" title="Solo — hear only this stem">S</button>
          <button class="tog mute" data-mute="${stem.stem}" title="Mute this stem">M</button>
          ${canTranscribe
            ? `<span class="lane-pick" title="Include in transcription">
                 <input type="checkbox" data-pick="${stem.stem}" aria-label="Transcribe ${LABELS[stem.stem]}" />
               </span>`
            : '<span class="lane-pick"></span>'}
        </span>
      </div>
      <div class="lane-wave" data-wave="${stem.stem}">
        <canvas></canvas>
      </div>
      <div class="fader-row">
        <span class="fader">vol
          <input type="range" data-gain="${stem.stem}" min="-24" max="12" step="0.5" value="0" />
          <output data-gain-out="${stem.stem}">0.0 dB</output>
        </span>
        <span class="fader">pan
          <input type="range" data-pan="${stem.stem}" min="-100" max="100" step="5" value="0" />
          <output data-pan-out="${stem.stem}">C</output>
        </span>
        <span class="fader">width
          <input type="range" data-width="${stem.stem}" min="0" max="200" step="5" value="100" />
          <output data-width-out="${stem.stem}">100%</output>
        </span>
        <span class="fader" title="How much of this stem's own reverb tail to blend in.
The tail length comes from the reference when the comparison can measure it.">reverb
          <input type="range" data-reverb="${stem.stem}" min="0" max="60" step="5" value="0" />
          <output data-reverb-out="${stem.stem}">dry</output>
        </span>
        <button class="link reset" data-reset="${stem.stem}">reset</button>
      </div>`;
    container.appendChild(lane);

    const audio = new Audio(`${API}/tracks/${state.trackId}/stems/${stem.stem}/audio`);
    audio.preload = "metadata";
    state.lanes.set(stem.stem, {
      audio,
      canvas: lane.querySelector("canvas"),
      wave: lane.querySelector(".lane-wave"),
      element: lane,
      peaks: null,
      muted: false,
      solo: false,
      gainDb: 0,
      pan: 0,
      reverbMix: 0,
      reverbS: 1.2,
      width: 1,
    });
    laneSizes.observe(lane.querySelector(".lane-wave"));

    if (canTranscribe && stem.stem !== "drums") {
      const select = document.createElement("select");
      select.className = "sr-only";
      select.dataset.tuning = stem.stem;
      select.innerHTML = `<option value="">Default tuning</option>${tuningOptions}`;
      lane.querySelector(".lane-head").appendChild(select);
    }
  }

  wireLanes();
  goToPage(state.page);
  if (state.page === "tab") loadTiming();
  updateMasterSummary();

  // Waveforms are a separate, cacheable request per stem - draw them as they arrive so
  // the mixer is usable immediately rather than after the slowest one.
  await Promise.all(
    ordered.map(async (stem) => {
      try {
        const data = await api(
          `/tracks/${state.trackId}/stems/${stem.stem}/peaks?buckets=1200`);
        const lane = state.lanes.get(stem.stem);
        lane.peaks = data.peaks;
        if (data.silent) {
          const tag = document.createElement("span");
          tag.className = "silent-tag";
          tag.textContent = "silent — nothing separated into this stem";
          lane.wave.appendChild(tag);
        }
        drawWave(stem.stem);
      } catch {
        /* A missing waveform must not stop you playing the stem. */
      }
    }),
  );
}

// Redraws a lane whenever it changes size - including the 0 -> N transition when the
// page finally gets laid out, which is why the initial draw can safely give up.
const laneSizes = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const stem = entry.target.dataset.wave;
    if (stem) drawWave(stem);
  }
});

// The before/after lanes have a fixed height, so only width changes matter - but the
// 0 -> N transition when the mastering page is first shown is exactly one of those.
const compareSizes = new ResizeObserver(() => drawCompare());

function drawWave(stem) {
  const lane = state.lanes.get(stem);
  if (!lane?.peaks) return;

  const canvas = lane.canvas;
  // A lane with no width yet - tab backgrounded, panel collapsed, window minimised -
  // cannot be drawn. Bail out; the ResizeObserver redraws the moment it gets a size.
  if (!lane.canvas.clientWidth || !lane.canvas.clientHeight) return;

  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;

  // Only touch the backing store when it actually changed. Assigning width/height clears
  // the canvas and, if anything downstream measures it, can retrigger the observer.
  const wantW = Math.round(width * ratio);
  const wantH = Math.round(height * ratio);
  if (canvas.width !== wantW) canvas.width = wantW;
  if (canvas.height !== wantH) canvas.height = wantH;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const colour = getComputedStyle(lane.element).getPropertyValue("--lane").trim();
  ctx.fillStyle = colour || "#9aa7b8";

  const middle = height / 2;
  const peaks = lane.peaks;
  const step = peaks.length / width;

  // One vertical bar per pixel column, mirrored about the centre line.
  for (let x = 0; x < width; x++) {
    let peak = 0;
    const from = Math.floor(x * step);
    const to = Math.min(peaks.length, Math.floor((x + 1) * step) + 1);
    for (let i = from; i < to; i++) peak = Math.max(peak, peaks[i]);
    const h = Math.max(1, peak * (height - 8));
    ctx.fillRect(x, middle - h / 2, 1, h);
  }
}

/** Show the wet amount together with the tail it applies to. */
function showReverb(stem) {
  const lane = state.lanes.get(stem);
  const out = document.querySelector(`[data-reverb-out="${stem}"]`);
  if (!out || !lane) return;
  out.textContent = lane.reverbMix
    ? `${Math.round(lane.reverbMix * 100)}% · ${lane.reverbS.toFixed(1)}s`
    : "dry";
}

function wireLanes() {
  document.querySelectorAll("[data-pick]").forEach((box) => {
    box.addEventListener("change", () => {
      const stem = box.dataset.pick;
      box.checked ? state.picked.add(stem) : state.picked.delete(stem);
      state.lanes.get(stem).element.classList.toggle("picked", box.checked);
      const count = state.picked.size;
      $("transcribe-btn").disabled = count === 0;
      $("transcribe-btn").textContent =
        count === 0 ? "Transcribe" : `Transcribe ${count} stem${count === 1 ? "" : "s"}`;
      $("pick-summary").textContent = count === 0
        ? "Tick the stems you want written out as tab."
        : [...state.picked].map((s) => LABELS[s]).join(", ");
    });
  });

  document.querySelectorAll("[data-solo]").forEach((button) => {
    button.addEventListener("click", () => toggleSolo(button.dataset.solo));
  });
  document.querySelectorAll("[data-mute]").forEach((button) => {
    button.addEventListener("click", () => toggleMute(button.dataset.mute));
  });
  document.querySelectorAll("[data-tuning]").forEach((select) => {
    select.addEventListener("change", () => {
      state.chosenTuning[select.dataset.tuning] = select.value;
    });
  });

  // Volume changes are audible immediately in the preview, so the mixer tells the
  // truth about what will be exported rather than only affecting the render.
  document.querySelectorAll("[data-gain]").forEach((slider) => {
    slider.addEventListener("input", () => {
      const stem = slider.dataset.gain;
      const db = parseFloat(slider.value);
      state.lanes.get(stem).gainDb = db;
      document.querySelector(`[data-gain-out="${stem}"]`).textContent =
        `${db > 0 ? "+" : ""}${db.toFixed(1)} dB`;
      applyGains();
    });
  });

  document.querySelectorAll("[data-pan]").forEach((slider) => {
    slider.addEventListener("input", () => {
      const stem = slider.dataset.pan;
      const pan = parseInt(slider.value, 10) / 100;
      state.lanes.get(stem).pan = pan;
      const label = pan === 0 ? "C" : `${pan < 0 ? "L" : "R"}${Math.abs(pan * 100).toFixed(0)}`;
      document.querySelector(`[data-pan-out="${stem}"]`).textContent = label;
    });
  });

  document.querySelectorAll("[data-width]").forEach((slider) => {
    slider.addEventListener("input", () => {
      const stem = slider.dataset.width;
      const width = parseInt(slider.value, 10) / 100;
      state.lanes.get(stem).width = width;
      document.querySelector(`[data-width-out="${stem}"]`).textContent =
        width === 0 ? "mono" : `${(width * 100).toFixed(0)}%`;
    });
  });

  document.querySelectorAll("[data-reverb]").forEach((slider) => {
    slider.addEventListener("input", () => {
      const stem = slider.dataset.reverb;
      const lane = state.lanes.get(stem);
      lane.reverbMix = parseInt(slider.value, 10) / 100;
      showReverb(stem);
    });
  });

  document.querySelectorAll("[data-reset]").forEach((button) => {
    button.addEventListener("click", () => {
      const stem = button.dataset.reset;
      const lane = state.lanes.get(stem);
      lane.gainDb = 0;
      lane.pan = 0;
      lane.width = 1;
      lane.reverbMix = 0;
      lane.reverbS = 1.2;
      button.closest(".fader-row").querySelector(`[data-reverb="${stem}"]`).value = 0;
      button.closest(".fader-row").querySelector(`[data-gain="${stem}"]`).value = 0;
      button.closest(".fader-row").querySelector(`[data-pan="${stem}"]`).value = 0;
      button.closest(".fader-row").querySelector(`[data-width="${stem}"]`).value = 100;
      document.querySelector(`[data-gain-out="${stem}"]`).textContent = "0.0 dB";
      document.querySelector(`[data-pan-out="${stem}"]`).textContent = "C";
      document.querySelector(`[data-width-out="${stem}"]`).textContent = "100%";
      showReverb(stem);
      applyGains();
    });
  });

  document.querySelectorAll("[data-wave]").forEach((wave) => {
    wave.addEventListener("click", (event) => {
      const rect = wave.getBoundingClientRect();
      seek(((event.clientX - rect.left) / rect.width) * state.duration);
    });
  });

  $("pick-summary").textContent = "Tick the stems you want written out as tab.";
}

// ───────────────────────────────── timing ──────────────────────────────────

/** Show what analysis detected, and let the user correct it before transcribing. */
async function loadTiming() {
  try {
    state.timing = await api(`/tracks/${state.trackId}/timing`);
  } catch {
    state.timing = null;
  }
  if (!state.timing) {
    $("timing-note").textContent = "grid not analysed — defaults to 120 BPM in 4/4";
    $("tempo-input").value = 120;
    return;
  }

  $("tempo-input").value = state.timing.tempo_bpm.toFixed(1);
  $("metre-input").value = String(state.timing.beats_per_bar);

  const bits = [];
  if (state.timing.key) bits.push(`key ${state.timing.key}`);
  // Say plainly when the reading is shaky - a wrong tempo mis-bars the whole tab, and
  // the person who wrote the song can fix it in one field.
  if (state.timing.confidence < 0.6) {
    bits.push("low confidence — check this before transcribing");
  }
  $("timing-note").textContent = bits.join(" · ");
}

function nudgeTempo(factor) {
  const current = parseFloat($("tempo-input").value) || 120;
  $("tempo-input").value = (current * factor).toFixed(1);
}

function timingOverrides() {
  const overrides = {};
  const tempo = parseFloat($("tempo-input").value);
  const metre = parseInt($("metre-input").value, 10);
  if (Number.isFinite(tempo) && tempo > 0) overrides.tempo_bpm = tempo;
  if (Number.isFinite(metre)) overrides.beats_per_bar = metre;
  return overrides;
}

// ───────────────────────────────── transport ────────────────────────────────

function anySolo() {
  return [...state.lanes.values()].some((l) => l.solo);
}

/** Solo wins over mute, the way every DAW behaves. */
function applyGains() {
  const soloed = anySolo();
  for (const [stem, lane] of state.lanes) {
    const audible = soloed ? lane.solo : !lane.muted;
    lane.audio.muted = !audible;
    // HTMLMediaElement volume is linear 0..1, so convert from dB. Boosts above 0 dB
    // cannot be previewed - the element clamps at 1 - but they still apply on export.
    lane.audio.volume = Math.max(0, Math.min(1, 10 ** (Math.min(0, lane.gainDb) / 20)));
    lane.element.classList.toggle("dimmed", !audible);
    lane.element.querySelector("[data-solo]")?.classList.toggle("on", lane.solo);
    lane.element.querySelector("[data-mute]")?.classList.toggle("on", lane.muted);
    void stem;
  }
  $("clear-solo").hidden = !soloed;
  if (state.trackId) updateMasterSummary();
  $("solo-note").textContent = soloed
    ? `soloing ${[...state.lanes].filter(([, l]) => l.solo).map(([s]) => LABELS[s]).join(", ")}`
    : "";
}

function toggleSolo(stem) {
  const lane = state.lanes.get(stem);
  lane.solo = !lane.solo;
  applyGains();
}

function toggleMute(stem) {
  const lane = state.lanes.get(stem);
  lane.muted = !lane.muted;
  applyGains();
}

function seek(seconds) {
  const time = Math.max(0, Math.min(seconds, state.duration));
  for (const lane of state.lanes.values()) lane.audio.currentTime = time;
  paintPlayhead(time);
}

async function togglePlay() {
  if (state.playing) {
    for (const lane of state.lanes.values()) lane.audio.pause();
    state.playing = false;
  } else {
    // Start everything from one timestamp so the stack stays in sync.
    const from = [...state.lanes.values()][0]?.audio.currentTime ?? 0;
    for (const lane of state.lanes.values()) lane.audio.currentTime = from;
    await Promise.all([...state.lanes.values()].map((l) => l.audio.play().catch(() => {})));
    state.playing = true;
  }
  $("play-btn").querySelector(".i-play").hidden = state.playing;
  $("play-btn").querySelector(".i-pause").hidden = !state.playing;
  $("playhead").hidden = false;
}

function paintPlayhead(time) {
  const first = state.lanes.values().next().value;
  if (!first) return;
  const rect = first.wave.getBoundingClientRect();
  const lanesRect = $("lanes").getBoundingClientRect();
  const offset = rect.left - lanesRect.left;
  const fraction = state.duration ? Math.min(1, time / state.duration) : 0;
  $("playhead").style.left = `${offset + fraction * rect.width}px`;
  $("time").textContent = clock(time);
}

// One rAF loop drives the playhead for every lane, rather than six timeupdate handlers.
function tick() {
  if (state.playing) {
    const lead = state.lanes.values().next().value;
    if (lead) {
      paintPlayhead(lead.audio.currentTime);
      // Nudge any stem that has drifted; <audio> elements do not stay locked on their own.
      for (const lane of state.lanes.values()) {
        if (Math.abs(lane.audio.currentTime - lead.audio.currentTime) > 0.08) {
          lane.audio.currentTime = lead.audio.currentTime;
        }
      }
      if (lead.audio.ended) togglePlay();
    }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// ───────────────────────────────── transcription ────────────────────────────

async function transcribe() {
  $("stems-error").hidden = true;
  const tunings = {};
  for (const stem of state.picked) {
    if (state.chosenTuning[stem]) tunings[stem] = state.chosenTuning[stem];
  }

  const picked = [...state.picked];
  try {
    const job = await api(`/tracks/${state.trackId}/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stems: picked, tunings, ...timingOverrides() }),
    });
    const finished = await runJob(job.job_id, "Writing the tab…");
    renderTabs(finished.result);
  } catch (error) {
    goToPage("tab");
    fail("stems-error", error);
  }
}

function renderTabs(result) {
  $("x0r-link").href = `${API}/tracks/${state.trackId}/x0r`;
  if (result.timing) {
    state.timing = result.timing;
    $("tempo-input").value = result.timing.tempo_bpm.toFixed(1);
    $("metre-input").value = String(result.timing.beats_per_bar);
  }

  $("tabs").innerHTML = result.artifacts
    .map((a) => {
      const adjusted = (a.dropped_count ?? 0) + (a.folded_count ?? 0);
      // Separation bleed puts notes outside the instrument's range. Saying so beats
      // quietly handing back a thinner tab than the note count implies.
      const note = adjusted > 0
        ? `<div class="adjusted">${
            a.dropped_count > 0
              ? `${a.dropped_count} note${a.dropped_count === 1 ? "" : "s"} outside this instrument's range left out`
              : ""
          }${a.dropped_count > 0 && a.folded_count > 0 ? " · " : ""}${
            a.folded_count > 0 ? `${a.folded_count} moved by an octave to fit` : ""
          } — usually bleed from another stem.</div>`
        : "";

      return `
        <article class="tab" style="--lane: var(--stem-${a.stem}, var(--stem-other))">
          <header>
            <span class="lane-icon"><svg viewBox="0 0 24 24">${ICONS[a.stem] ?? ICONS.other}</svg></span>
            <span class="grow">
              <h3>${LABELS[a.stem] ?? a.stem}</h3>
              <span class="muted small">${a.note_count} notes · ${a.notation.replace("_", " ")}</span>
            </span>
            <a class="link" href="${API}/tracks/${state.trackId}/tabs/${a.stem}"
               download="${a.stem}.txt">Download .txt</a>
          </header>
          ${note}
          <pre>${escapeHtml(a.preview)}</pre>
        </article>`;
    })
    .join("");

  // Keep the mixer on screen: comparing the tab against the stem you can hear is the
  // whole point, and hiding one to show the other defeats it.
  showOnly("step-stems", "step-timing", "step-tabs");
  $("step-tabs").scrollIntoView({ behavior: "smooth", block: "start" });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// ───────────────────────────────── mastering ────────────────────────────────

function pickReference(file) {
  if (!file) return;
  state.referenceFile = file;
  state.referenceLoaded = false;
  $("ref-dropzone").classList.add("has-file");
  $("ref-name").textContent = file.name;
  $("ref-hint").textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB — uploading…`;
  $("ref-error").hidden = true;
  uploadReference();
}

async function uploadReference() {
  const form = new FormData();
  form.append("file", state.referenceFile);
  form.append("owns_or_licensed", "true");

  try {
    const info = await api(`/tracks/${state.trackId}/reference`, {
      method: "POST",
      body: form,
    });
    state.referenceLoaded = true;
    const loudness =
      info.integrated_lufs != null ? ` · ${info.integrated_lufs.toFixed(1)} LUFS` : "";
    $("ref-hint").textContent =
      `${info.duration_s.toFixed(0)}s${loudness} — will be matched`;
    updateMasterSummary();
    await refreshPerStemState();
    // Now there is something to compare against, so the dials can be set for this pair.
    await loadSuggestion();
  } catch (error) {
    state.referenceLoaded = false;
    $("ref-dropzone").classList.remove("has-file");
    $("ref-name").textContent = "Drop a reference track here";
    $("ref-hint").textContent = "a commercial master you want to sound like — optional";
    fail("ref-error", error);
  }
}

/** Reflect whether the reference has been split, and whether per-stem matching is on. */
async function refreshPerStemState() {
  const box = $("per-stem-match");
  const button = $("separate-ref-btn");
  const note = $("per-stem-note");

  if (!state.referenceLoaded) {
    box.disabled = true;
    box.checked = false;
    button.hidden = true;
    $("per-stem-options").hidden = true;
    note.textContent =
      "Upload a reference first. Matching per instrument fixes a whole-mix match " +
      "cutting your bass away.";
    return;
  }

  let separated = false;
  try {
    separated = (await api(`/tracks/${state.trackId}/reference/stems`)).separated;
  } catch {
    separated = false;
  }
  state.referenceSeparated = separated;

  box.disabled = !separated;
  button.hidden = separated;
  if (separated) {
    note.textContent =
      "Bass matched to bass, drums to drums — level, tone and stereo width each taken " +
      "from the matching instrument.";
    box.checked = true;
    $("per-stem-options").hidden = false;
  } else {
    note.textContent =
      "Needs the reference separated too — another pass of roughly the same length as " +
      "the first. Without it, matching can only tilt the whole mix.";
    $("per-stem-options").hidden = true;
  }
}

async function separateReference() {
  try {
    const job = await api(`/tracks/${state.trackId}/reference/separate`, {
      method: "POST",
    });
    await runJob(
      job.job_id,
      "Splitting the reference…",
      "Same cost as separating your own track. Done once per reference.",
    );
    goToPage("master");
    await refreshPerStemState();
    // Separating the reference is what makes the instrument-by-instrument comparison
    // possible, so it is the other moment worth going and getting it.
    if (state.suggestion?.summary) {
      state.suggestion.summary.stems_available = true;
      state.suggestion.summary.includes_stems = false;
      loadStemComparison();
    } else {
      await loadSuggestion();
    }
  } catch (error) {
    goToPage("master");
    fail("master-error", error);
  }
}

function updateMasterSummary() {
  const stems = [...state.lanes.keys()];
  const audible = stems.filter((s) => !state.lanes.get(s).audio.muted);
  const what =
    audible.length === stems.length
      ? "all stems"
      : audible.map((s) => LABELS[s]).join(", ") || "nothing";
  $("master-summary").textContent = state.referenceLoaded
    ? `${what}, matched to your reference`
    : `${what}, no reference — export only`;
}

async function runMaster() {
  $("master-error").hidden = true;
  $("master-result").hidden = true;

  // Mute and solo on the lanes ARE the mix. No second set of controls to keep in sync:
  // what you hear in the mixer is what gets exported.
  const stems = [...state.lanes].map(([stem, lane]) => ({
    stem,
    gain_db: lane.gainDb,
    reverb_s: lane.reverbS,
    reverb_mix: lane.reverbMix,
    pan: lane.pan,
    width: lane.width,
    muted: lane.muted,
    solo: lane.solo,
  }));

  try {
    const job = await api(`/tracks/${state.trackId}/master`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stems,
        reference_track_id: state.referenceLoaded ? state.trackId : null,
        match_strength: parseInt($("strength").value, 10) / 100,
        per_stem_match: $("per-stem-match").checked,
        preserve_source: $("preserve-source").checked,
        ...kitSettings(),
        brightness_db: parseFloat($("brightness").value),
        warmth_db: parseFloat($("warmth").value),
        bass_db: parseFloat($("bass").value),
        brightness_from_hz: parseFloat($("brightness-hz").value),
        width: parseInt($("stereo-width").value, 10) / 100,
        width_profile: parseInt($("width-profile").value, 10) / 100,
        headroom_db: parseFloat($("headroom").value),
        match_stem_levels: $("ms-levels").checked,
        match_stem_tone: $("ms-tone").checked,
        match_stem_width: $("ms-width").checked,
        vocal_presence: $("vocal-presence").value || null,
        vocal_duck_db: parseFloat($("vocal-duck").value),
        bitrate_kbps: parseInt($("bitrate").value, 10),
      }),
    });
    const finished = await runJob(
      job.job_id,
      "Mastering…",
      "Mixing the stems, matching the reference, then encoding. No ffmpeg involved.",
    );
    renderMaster(finished.result);
  } catch (error) {
    goToPage("master");
    fail("master-error", error);
  }
}

function renderMaster(result) {
  goToPage("master");
  $("master-result").hidden = false;

  // Cache-bust: the URL is stable across renders but the file behind it is not.
  const url = `${API}/tracks/${state.trackId}/master/download?t=${Date.now()}`;
  $("master-download").href = url;
  $("master-download").download = "extract0r-master.mp3";
  $("master-audio").src = url;

  const size = (result.bytes / 1024 / 1024).toFixed(1);
  const info = result.mastering;

  $("master-meters").innerHTML = info
    ? meter("Your mix", info.source) +
      meter("Reference", info.reference) +
      meter("Master", info.result, info.source) +
      `<div class="meter">gain applied<b>${info.gain_applied_db > 0 ? "+" : ""}${info.gain_applied_db} dB</b></div>` +
      `<div class="meter">file<b>${size} MB</b></div>`
    : `<div class="meter">exported<b>${size} MB</b></div>` +
      `<div class="meter">stems<b>${result.stems.length}</b></div>`;

  $("compare-note").innerHTML = compareNote(info);
  renderCompare();
  renderFinishing(result.finishing);

  $("master-curve").innerHTML = info?.eq_curve_db?.length
    ? renderCurve(info.eq_curve_db)
    : "";

  // Where the vocal ended up. Worth its own line: it is the thing a listener notices
  // first, and the number is meaningless unless it is shown.
  const v = result.vocals;
  if (v) {
    const bits = [
      `<span class="tag">was ${v.measured_lu.toFixed(1)} LU</span>`,
      `<span class="tag">target ${v.target_lu.toFixed(1)} LU</span>`,
    ];
    if (v.lift_db > 0) bits.push(`<span class="tag up">lifted +${v.lift_db} dB</span>`);
    else bits.push('<span class="tag">already forward enough</span>');
    if (v.user_gain_db) {
      const dir = v.user_gain_db > 0 ? "up" : "down";
      bits.push(`<span class="tag ${dir}">your fader ${signed(v.user_gain_db)} dB</span>`);
    }
    if (v.ducked_stems?.length) {
      bits.push(`<span class="tag">${v.ducked_stems.join(", ")} ducked ${v.duck_depth_db} dB</span>`);
    }
    for (const note of v.notes ?? []) bits.push(`<span class="tag down">${note}</span>`);
    $("master-curve").innerHTML +=
      `<h4 style="margin:22px 0 0;font-size:14px">Vocal placement</h4>
       <div class="stem-report">
         <div class="row" style="--lane: var(--stem-vocals)"><b>Vocals</b>${bits.join("")}</div>
       </div>`;
  }

  // Per-instrument moves are the interesting part when they happened: they say what the
  // reference thought of your balance, instrument by instrument. Three things have to stay
  // distinguishable here: what the reference asked for, what was inferred for instruments
  // the reference does not contain, and what you did on top with the faders.
  const perStem = result.per_stem ?? [];
  if (perStem.length) {
    const rows = perStem.map((a) => {
      const bits = [];
      if (a.gain_db) {
        const dir = a.gain_db > 0 ? "up" : "down";
        const how = a.proportional ? " with the mix" : "";
        bits.push(`<span class="tag ${dir}">${signed(a.gain_db)} dB${how}</span>`);
      }
      if (a.width_factor && a.width_factor !== 1) {
        bits.push(`<span class="tag">width x${a.width_factor}</span>`);
      }
      const biggest = (a.eq_bands ?? [])
        .slice()
        .sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]))[0];
      if (biggest && Math.abs(biggest[1]) >= 0.5) {
        const hz = biggest[0] >= 1000 ? `${biggest[0] / 1000}k` : biggest[0];
        bits.push(`<span class="tag">${signed(biggest[1])} dB @ ${hz}</span>`);
      }
      for (const note of a.notes ?? []) bits.push(`<span class="tag">${note}</span>`);
      if (!bits.length) bits.push('<span class="tag">no change</span>');
      // Your own fader last, and labelled, so it reads as sitting on top of the match
      // rather than as something the reference asked for.
      if (a.user_gain_db) {
        const dir = a.user_gain_db > 0 ? "up" : "down";
        bits.push(
          `<span class="tag ${dir}">your fader ${signed(a.user_gain_db)} dB</span>`
        );
      }
      const badge = a.matched
        ? ""
        : `<span class="tag ${a.proportional ? "" : "down"}">` +
          `${a.proportional ? "no reference part" : "unmatched"}</span>`;
      return `<div class="row" style="--lane: var(--stem-${a.stem}, var(--stem-other))">
                <b>${LABELS[a.stem] ?? a.stem}</b>${badge}${bits.join("")}
              </div>`;
    });
    $("master-curve").innerHTML +=
      `<h4 style="margin:22px 0 0;font-size:14px">Per-instrument matching</h4>
       <div class="stem-report">${rows.join("")}</div>`;
  }

  const warnings = info?.warnings ?? [];
  $("master-warnings").textContent = warnings.join(" ");
  $("master-warnings").hidden = warnings.length === 0;
}

/** Always show the sign: "+2.1 dB" reads as a decision, "2.1 dB" reads as a magnitude. */
function signed(value) {
  return `${value > 0 ? "+" : ""}${value}`;
}

function meter(label, stats, against = null) {
  if (!stats) return "";
  const delta = against
    ? `<span class="delta">${stats.integrated_lufs > against.integrated_lufs ? "+" : ""}` +
      `${(stats.integrated_lufs - against.integrated_lufs).toFixed(1)} LU</span>`
    : "";
  return `<div class="meter">${label}<b>${stats.integrated_lufs.toFixed(1)} LUFS</b>
          <span class="delta">peak ${stats.true_peak_dbfs.toFixed(1)} dB</span> ${delta}</div>`;
}

/** The applied EQ as bars above and below a centre line - readable without a chart library. */
/** Fetch the mix and the master as envelopes and draw them on one time axis.

Failing to draw a picture is not a reason to hide a finished master, so every failure
path here leaves the rest of the result card alone. */
/** The comparison, in words. Differences first, largest first; the things that already
match are collapsed behind a toggle so the top of the card is the part worth acting on. */
function renderCritique(summary) {
  const card = $("mix-compare");
  if (!summary?.findings?.length) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  $("compare-verdict").textContent = summary.verdict;

  const differences = summary.findings.filter((f) => f.severity !== "match");
  const matching = summary.findings.filter((f) => f.severity === "match");
  state.showAllFindings = false;

  const draw = () => {
    const shown = state.showAllFindings ? [...differences, ...matching] : differences;
    $("compare-findings").innerHTML = shown.map((f, i) => finding(f, i)).join("");

    // Applying one finding moves only its own dials, so the rest of the mix stays where
    // the person left it. That is the difference between this and "apply everything".
    for (const button of $("compare-findings").querySelectorAll(".fix")) {
      button.addEventListener("click", () => {
        applyDials(shown[Number(button.dataset.fix)].action.dials);
        button.dataset.done = "true";
        button.textContent = "Applied";
        state.mode = null;
        document.querySelectorAll(".mode")
          .forEach((b) => b.setAttribute("aria-pressed", "false"));
      });
    }
    const toggle = $("findings-toggle");
    toggle.hidden = matching.length === 0;
    toggle.textContent = state.showAllFindings
      ? "Hide what already matches"
      : `Show ${matching.length} more that already match`;
  };

  $("findings-toggle").onclick = () => {
    state.showAllFindings = !state.showAllFindings;
    draw();
  };
  draw();

  // Nothing to act on is worth saying plainly rather than leaving an empty card.
  if (!differences.length) {
    $("compare-findings").innerHTML =
      '<p class="muted small" style="margin:0">Nothing stands out — every area is ' +
      "within about a decibel of the reference.</p>";
  }
}

function finding(f, index) {
  // Three states, and the difference matters. There is a dial for this; there is no dial
  // because matching already handles it; or it is context with nothing to do about it.
  const foot = f.action
    ? `<div class="finding-foot">
         <button class="fix" data-fix="${index}">${f.action.label}</button>
       </div>`
    : f.handled_by_match
      ? '<div class="finding-foot"><span class="handled">handled by the reference match</span></div>'
      : "";

  return `<div class="finding ${f.severity}">
            <div>
              <b>${f.headline}<span class="area">${f.area}</span></b>
              <span>${f.detail}</span>
              ${foot}
            </div>
          </div>`;
}

/** The drum kit panel. Off until asked for, because triggering samples over someone's
drums is the most opinionated thing here and should never happen by default. */
async function loadDrumKits() {
  const select = $("kit-name");
  if (select.options.length) return;
  try {
    const data = await api("/tracks/drum-kits");
    select.innerHTML = data.kits
      .map((k) => `<option value="${k.name}">${k.name} — ${k.description}</option>`)
      .join("");
  } catch {
    // No kits listed means the panel simply stays unavailable.
    $("kit-on").disabled = true;
  }
}

function kitSettings() {
  if (!$("kit-on").checked) return { drum_kit: null };
  const drums = [...document.querySelectorAll("[data-kit-drum]")]
    .filter((box) => box.checked)
    .map((box) => box.dataset.kitDrum);
  return {
    drum_kit: drums.length ? $("kit-name").value : null,
    drum_targets: drums,
    drum_blend: parseInt($("kit-blend").value, 10) / 100,
  };
}

// ───────────────────────────── finishing dials ──────────────────────────────
//
// Fixed starting points, plus one computed from the reference. They set the sliders and
// then get out of the way: the sliders stay the source of truth, so a preset is somewhere
// to start rather than a mode you are stuck in.

const MODES = {
  flat: {
    label: "Flat",
    why: "Every finishing dial off — whatever the reference match decides, and nothing else.",
    dials: { brightness: 0, brightnessHz: 8000, warmth: 0, bass: 0, width: 100, headroom: 0 },
  },
  bright: {
    label: "Brighten",
    why: "A shelf from <b>6 kHz</b>. High enough to stay out of the midrange, low enough to " +
         "reach the top of the presence range where a closed-in mix usually needs opening up.",
    dials: { brightness: 3, brightnessHz: 6000, warmth: 0, bass: 0, width: 100, headroom: 0 },
  },
  bassier: {
    label: "Bassier",
    why: "A shelf below <b>90 Hz</b> — kick weight and bass fundamentals. Separate from " +
         "Warmer on purpose: 90 Hz is weight, 450 Hz is body, and asking for one usually " +
         "means you do not want the other.",
    dials: { brightness: 0, brightnessHz: 8000, warmth: 0, bass: 3, width: 100, headroom: 0 },
  },
  warm: {
    label: "Warmer",
    why: "Body around <b>450 Hz</b> with the very top eased back. Warmth is weight in the low " +
         "mids, not less treble — the bell leaves the bass alone so it does not turn boomy.",
    dials: { brightness: -1, brightnessHz: 12000, warmth: 2.5, bass: 0, width: 100, headroom: 0 },
  },
  punchy: {
    label: "Punchier",
    why: "Punch is transients surviving the limiter, so this mostly buys headroom: " +
         "<b>1.5 dB</b> further under the reference, with a little presence for attack. " +
         "It trades loudness for impact.",
    dials: { brightness: 1.5, brightnessHz: 3000, warmth: 0.5, bass: 1, width: 100, headroom: 1.5 },
  },
  wide: {
    label: "Wider",
    why: "Spreads everything above <b>250 Hz</b> to 125% and adds sheen at 12 kHz, which the " +
         "ear also reads as width. The bass stays centred so it survives a mono system.",
    dials: { brightness: 1.5, brightnessHz: 12000, warmth: 0, bass: 0, width: 125, headroom: 0 },
  },
};

/** Push a set of dial values into the sliders and fire their listeners.

Guarded, because those listeners include the one that clears the preset badge when a
person moves a slider. Without the flag a preset wipes its own highlight on the way in. */
let settingDials = false;

function applyDials(dials) {
  settingDials = true;

  // Reverb is per stem, so it lands on a lane rather than on one of the master dials.
  for (const [stem, want] of Object.entries(dials.stemReverb ?? {})) {
    const lane = state.lanes.get(stem);
    if (!lane) continue;
    // Snapped to the slider's own step, so the control and the value behind it agree.
    // Left exact, the fader would sit at 25% while the mix was 0.27 and jump the first
    // time it was touched.
    lane.reverbS = want.seconds;
    lane.reverbMix = Math.round(want.mix * 20) / 20;
    const slider = document.querySelector(`[data-reverb="${stem}"]`);
    if (slider) slider.value = String(Math.round(lane.reverbMix * 100));
    showReverb(stem);
  }
  const map = {
    brightness: "brightness", warmth: "warmth", bass: "bass",
    width: "stereo-width", headroom: "headroom",
  };
  for (const [key, id] of Object.entries(map)) {
    if (dials[key] === undefined) continue;
    const el = $(id);
    el.value = dials[key];
    el.dispatchEvent(new Event("input"));
  }
  if (dials.brightnessHz !== undefined) {
    $("brightness-hz").value = String(nearestBrightnessOption(dials.brightnessHz));
  }
  settingDials = false;
}

function selectMode(name) {
  state.mode = name;
  for (const button of document.querySelectorAll(".mode")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === name));
  }
  if (name === "suggested") {
    applySuggestion();
    return;
  }
  applyDials(MODES[name].dials);
  $("mode-why").innerHTML = MODES[name].why;
}

/** The computed starting point: what the reference says this particular mix needs. */
function applySuggestion() {
  const s = state.suggestion;
  if (!s?.available) return;
  applyDials({
    brightness: s.settings.brightness_db,
    brightnessHz: nearestBrightnessOption(s.settings.brightness_from_hz),
    warmth: s.settings.warmth_db,
    bass: s.settings.bass_db,
    width: Math.round(s.settings.width * 100),
    headroom: s.settings.headroom_db,
  });
  $("mode-why").innerHTML =
    "Measured against your reference, after allowing for what the tonal match already " +
    "does. Hover any dial for the reasoning behind its value.";
  describeDials(s.reasons);
}

/** The dropdown only holds a few corners; snap a suggested frequency to the nearest. */
function nearestBrightnessOption(hz) {
  const options = [...$("brightness-hz").options].map((o) => parseFloat(o.value));
  return options.reduce((best, v) => (Math.abs(v - hz) < Math.abs(best - hz) ? v : best));
}

/** Put each reason on its own control as hover text, and under the row as help. */
function describeDials(reasons) {
  const targets = {
    brightness: ["brightness", "brightness-hz"],
    warmth: ["warmth"],
    bass: ["bass"],
    width: ["stereo-width"],
    headroom: ["headroom"],
  };
  for (const [control, ids] of Object.entries(targets)) {
    const text = reasons?.[control];
    if (!text) continue;
    for (const id of ids) {
      const label = $(id).closest(".control");
      if (label) label.title = text;
    }
  }
  $("dial-reasons").innerHTML = !reasons
    ? ""
    : Object.entries(targets)
        .filter(([control]) => reasons[control])
        .map(([control]) =>
          `<div class="row" style="--lane: var(--stem-other)">
             <b>${control[0].toUpperCase()}${control.slice(1)}</b>
             <span class="tag">${reasons[control]}</span>
           </div>`)
        .join("");
  // Collapsed by default: the same sentences are on each control as hover text, and four
  // paragraphs open by default push the dials themselves below the fold.
  $("dial-reasons-box").hidden = !reasons;
}

/** Ask the API what this mix needs. Cheap - no separation, no mastering run. */
async function loadSuggestion() {
  const button = document.querySelector('.mode[data-mode="suggested"]');
  state.suggestion = null;
  button.disabled = true;
  describeDials(null);
  $("mix-compare").hidden = true;

  try {
    const data = await api(`/tracks/${state.trackId}/master/suggest`);
    if (!data?.available) return;
    state.suggestion = data;
    button.disabled = false;
    renderCritique(data.summary);
    // Only take over the dials if the user has not already chosen something.
    if (!state.mode) selectMode("suggested");
  } catch {
    // A suggestion is a convenience; failing to get one changes nothing else.
    return;
  }

  // The per-instrument half reads every stem on both sides and takes around half a
  // minute. It arrives when it arrives; nothing above waits for it.
  loadStemComparison();
}

/** Fill in the instrument-by-instrument findings, once they are computable. */
async function loadStemComparison() {
  const summary = state.suggestion?.summary;
  if (!summary?.stems_available || summary.includes_stems) return;

  $("stem-compare-note").hidden = false;
  try {
    const data = await api(`/tracks/${state.trackId}/master/suggest?stems=true`);
    if (!data?.available) return;
    // The dials may have been moved by hand in the meantime, so only the reading is
    // replaced - selectMode is deliberately not called again.
    state.suggestion = data;
    renderCritique(data.summary);
    describeDials(data.reasons);
  } catch {
    // The whole-mix findings are already on screen and still true.
  } finally {
    $("stem-compare-note").hidden = true;
  }
}

async function renderCompare() {
  const panel = $("master-compare");
  panel.hidden = true;
  state.compare = null;

  let data;
  try {
    data = await api(`/tracks/${state.trackId}/master/peaks`);
  } catch {
    return; // no picture; the numbers above still stand
  }
  if (!data?.matched) return; // nothing was matched, so there is no "before"

  state.compare = data;
  panel.hidden = false;
  for (const lane of panel.querySelectorAll(".compare-lane")) compareSizes.observe(lane);

  const seconds = data.after?.duration_s ?? 0;
  $("compare-end").textContent =
    `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

  drawCompare();
}

/** One vertical bar per pixel column, mirrored about the centre line - the same shape
the stem lanes use, so the two pages read as the same instrument. */
function drawCompare() {
  const data = state.compare;
  if (!data) return;

  for (const lane of document.querySelectorAll(".compare-lane")) {
    const canvas = lane.querySelector("canvas");
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    // No size yet - page hidden, window minimised. The observer redraws on the 0 -> N
    // transition, so giving up here is safe.
    if (!width || !height) continue;

    const ratio = window.devicePixelRatio || 1;
    const wantW = Math.round(width * ratio);
    const wantH = Math.round(height * ratio);
    if (canvas.width !== wantW) canvas.width = wantW;
    if (canvas.height !== wantH) canvas.height = wantH;

    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const style = getComputedStyle(document.documentElement);
    const accent = style.getPropertyValue("--accent").trim() || "#35e08a";
    const warn = style.getPropertyValue("--warn").trim() || "#ffb454";
    const grey = style.getPropertyValue("--stem-other").trim() || "#9aa7b8";

    const scale = envelopeScale(data.before, data.after);

    if (lane.dataset.when === "delta") {
      drawDelta(ctx, width, height, data.delta_db, accent, warn);
    } else if (lane.dataset.when === "after") {
      // The master filled, with the mix traced over the top of it as a line. A ghost
      // underneath would be the obvious choice and is the wrong one: mastering makes
      // almost every moment louder, so the mix sits entirely inside the master's shape
      // and the ghost never shows. An outline is visible either way, and the gap between
      // the line and the edge of the fill is exactly what mastering added.
      drawEnvelope(ctx, width, height, data.after.db, scale, accent, 0.9);
      traceEnvelope(ctx, width, height, data.before.db, scale, grey);
    } else {
      drawEnvelope(ctx, width, height, data.before.db, scale, grey, 0.75);
    }
  }
}

/** A drawing scale fitted to these two files, and shared between them.

The stem lanes draw against a fixed -55 dB floor, which is right for a stem: it has real
silence in it and a rest has to look like a rest. A finished mix has no silence. This song
sits between -25 and -7 dB, so on the stem scale the entire arrangement is squeezed into
the top third of the lane and both renders read as solid blocks.

Fitting the scale to the content spreads it out. Both lanes get the *same* floor and
ceiling, so a taller shape still means a louder moment - which is the one property the
comparison cannot lose. */
function envelopeScale(before, after) {
  const sorted = [...before.db, ...after.db].sort((a, b) => a - b);
  const ceiling = sorted[sorted.length - 1];
  // The 2nd percentile rather than the minimum: a single silent moment should not
  // flatten the whole song back out again.
  let floor = sorted[Math.floor(sorted.length * 0.02)];
  if (ceiling - floor < 6) floor = ceiling - 6; // near-constant level, e.g. a drone
  floor = Math.max(floor - 3, ceiling - 60);    // a little air under the quietest part
  const range = ceiling - floor;
  return (db) => Math.max(0, Math.min(1, (db - floor) / range));
}

function columnHeights(db, scale, width, height) {
  const step = db.length / width;
  const heights = [];
  for (let x = 0; x < width; x++) {
    let loudest = -Infinity;
    const from = Math.floor(x * step);
    const to = Math.min(db.length, Math.floor((x + 1) * step) + 1);
    for (let i = from; i < to; i++) loudest = Math.max(loudest, db[i]);
    heights.push(Math.max(1, scale(loudest) * (height - 10)));
  }
  return heights;
}

function drawEnvelope(ctx, width, height, db, scale, colour, alpha) {
  ctx.globalAlpha = alpha;
  ctx.fillStyle = colour;
  const middle = height / 2;
  columnHeights(db, scale, width, height).forEach((h, x) => {
    ctx.fillRect(x, middle - h / 2, 1, h);
  });
  ctx.globalAlpha = 1;
}

/** The top edge of an envelope as a line, mirrored, for laying one shape over another. */
function traceEnvelope(ctx, width, height, db, scale, colour) {
  const middle = height / 2;
  const heights = columnHeights(db, scale, width, height);

  ctx.strokeStyle = colour;
  ctx.globalAlpha = 0.85;
  ctx.lineWidth = 1;
  for (const sign of [-1, 1]) {
    ctx.beginPath();
    heights.forEach((h, x) => {
      const y = middle + (sign * h) / 2;
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x + 0.5, y);
    });
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

/** Level change per moment, around a zero line. A couple of dB on a 55 dB waveform is a
few pixels; on its own axis it is the clearest thing on the page. */
function drawDelta(ctx, width, height, delta, accent, warn) {
  const low = Math.min(...delta);
  const high = Math.max(...delta);

  // Mastering usually makes every moment louder, so the values nearly always share a
  // sign. Anchoring to the middle regardless would throw away half the height and leave
  // a 3 dB spread squeezed into 18 pixels; the baseline moves to the edge instead and
  // the strip uses all of itself.
  const zero = low >= 0 ? height - 4 : high <= 0 ? 4 : height / 2;
  const reach = low >= 0 || high <= 0 ? height - 8 : height / 2 - 4;
  const span = Math.max(1.5, Math.abs(low), Math.abs(high));
  const step = delta.length / width;

  ctx.strokeStyle = getComputedStyle(document.documentElement)
    .getPropertyValue("--edge").trim() || "#232a32";
  ctx.beginPath();
  ctx.moveTo(0, zero + 0.5);
  ctx.lineTo(width, zero + 0.5);
  ctx.stroke();

  for (let x = 0; x < width; x++) {
    const from = Math.floor(x * step);
    const to = Math.min(delta.length, Math.floor((x + 1) * step) + 1);
    // Mean, not max: this is a trend, and a single loud bucket should not spike it.
    let sum = 0;
    let count = 0;
    for (let i = from; i < to; i++) { sum += delta[i]; count++; }
    if (!count) continue;
    const value = sum / count;
    const h = Math.max(1, (Math.abs(value) / span) * reach);
    ctx.fillStyle = value >= 0 ? accent : warn;
    ctx.fillRect(x, value >= 0 ? zero - h : zero, 1, h);
  }
}

/** The same story as the picture, in numbers, for anyone who would rather read it. */
function compareNote(info) {
  if (!info?.source || !info?.result) return "";
  const louder = info.result.integrated_lufs - info.source.integrated_lufs;
  const before = info.source.true_peak_dbfs - info.source.integrated_lufs;
  const after = info.result.true_peak_dbfs - info.result.integrated_lufs;
  const squash = before - after;

  // Only claim the limiter did something when the numbers say it did.
  const verdict =
    squash > 0.5
      ? `<b>${squash.toFixed(1)} dB</b> more tightly controlled — the limiter held the ` +
        "loud moments while the quiet ones came up"
      : squash < -0.5
        ? `<b>${Math.abs(squash).toFixed(1)} dB</b> more dynamic`
        : "about as dynamic as before";

  return (
    `Overall the master is <b>${signed(+louder.toFixed(1))} dB</b> louder than your mix. ` +
    `Its peaks sit <b>${before.toFixed(1)} dB</b> → <b>${after.toFixed(1)} dB</b> above ` +
    `the average level, so it is ${verdict}.`
  );
}

/** What the finishing stage did, and how hard the limiter had to work to get there.

The limiter numbers are the point. "Sounds squashed" is not a matter of taste - it is
gain reduction, and a master three dB down for a third of its length is measurably a
different record from one that never touches the ceiling. */
function renderFinishing(finishing) {
  const node = $("master-finishing");
  if (!finishing) {
    node.hidden = true;
    return;
  }
  node.hidden = false;

  const bits = [];
  if (finishing.brightness_db) {
    bits.push(`<span class="tag up">brightness ${signed(finishing.brightness_db)} dB</span>`);
  }
  if (finishing.width_factor && finishing.width_factor !== 1) {
    const from = finishing.width_before;
    const to = finishing.width_after;
    bits.push(
      `<span class="tag">width x${finishing.width_factor.toFixed(2)}` +
      (from && to ? ` (${from.toFixed(2)} → ${to.toFixed(2)})` : "") +
      "</span>"
    );
  }
  if (finishing.ceiling_headroom_db) {
    bits.push(`<span class="tag">held -${finishing.ceiling_headroom_db} dB off the reference</span>`);
  }
  if (finishing.headroom_db) {
    bits.push(`<span class="tag">your headroom -${finishing.headroom_db} dB</span>`);
  }
  if (!bits.length) bits.push('<span class="tag">nothing added</span>');

  // How hard the limiter worked, said plainly.
  const active = (finishing.limiter_active ?? 0) * 100;
  const verdict =
    active >= 25 ? ["down", "working hard — try more headroom"]
      : active >= 8 ? ["", "busy but reasonable"]
        : ["up", "barely touching it"];
  const limiter =
    finishing.limiter_max_db === undefined
      ? ""
      : `<div class="row" style="--lane: var(--stem-other)"><b>Limiter</b>
           <span class="tag ${verdict[0]}">${verdict[1]}</span>
           <span class="tag">on ${active.toFixed(0)}% of the track</span>
           <span class="tag">up to -${finishing.limiter_max_db} dB</span>
           ${finishing.result_crest_db
             ? `<span class="tag">${finishing.result_crest_db} dB dynamic range` +
               (finishing.reference_crest_db
                 ? `, reference ${finishing.reference_crest_db} dB` : "") + "</span>"
             : ""}
         </div>`;

  node.innerHTML =
    `<h4 class="sub">Finishing</h4>
     <div class="stem-report">
       <div class="row" style="--lane: var(--accent)"><b>Applied</b>${bits.join("")}</div>
       ${limiter}
     </div>` +
    (finishing.notes?.length
      ? `<p class="muted small">${finishing.notes.join(" · ")}</p>`
      : "");
}

function renderCurve(bands) {
  const largest = Math.max(3, ...bands.map(([, db]) => Math.abs(db)));
  const rows = bands.map(([hz, db]) => {
    const height = Math.round((Math.abs(db) / largest) * 38);
    const label = hz >= 1000 ? `${hz / 1000}k` : hz;
    const bar =
      db >= 0
        ? `<div class="curve-bar" style="height:${height}px"></div><div class="curve-mid"></div><div style="height:38px"></div>`
        : `<div style="height:38px"></div><div class="curve-mid"></div><div class="curve-bar cut" style="height:${height}px"></div>`;
    return `<div class="curve-band" title="${db > 0 ? "+" : ""}${db} dB at ${hz} Hz">
              ${bar}<span class="curve-label">${label}</span></div>`;
  });
  return `<div class="curve">${rows.join("")}</div>
          <p class="muted small">Correction applied, per band. Green is boost, amber is cut.</p>`;
}

// ───────────────────────────────── capabilities page ────────────────────────

const CAPABILITY_NOTES = {
  demucs: ["Stem separation", "Without it, splitting returns copies of your file."],
  basic_pitch: ["Polyphonic transcription", "Guitar and piano tab."],
  pyin: ["Monophonic transcription", "Bass and vocal lines."],
  onset_drums: ["Drum transcription", "Onset detection and drum tab."],
  spectral_master: ["Reference mastering", "Tonal and loudness matching."],
  mp3_export: ["MP3 export", "LAME encoding, no external process."],
  lufs_metering: ["LUFS metering", "EBU R128. Falls back to RMS without it."],
  aac_decode: ["m4a / AAC input", "Decoded by bundled libraries, no install needed."],
  ffmpeg: ["ffmpeg", "Optional - a fallback for unusual containers."],
};

async function renderCapabilities() {
  const node = $("about-caps");
  node.innerHTML = '<p class="muted">checking…</p>';
  try {
    const caps = await api("/capabilities");
    const rows = Object.entries(CAPABILITY_NOTES).map(([key, [what, why]]) => {
      const on = caps.installed[key];
      return `<div class="cap ${on ? "on" : ""}">
                <span class="dot"></span>
                <span class="what"><strong>${what}</strong><br /><span class="why">${why}</span></span>
                <span class="muted small">${on ? "installed" : "not installed"}</span>
              </div>`;
    });
    node.innerHTML =
      `<div class="cap-grid">${rows.join("")}</div>
       <p class="muted small" style="margin-top:16px">
         Configured backends: ${Object.entries(caps.configured).map(([k, v]) => `${k}=${v}`).join(" · ")}<br />
         Limits: ${caps.limits.max_upload_mb} MB upload, deleted after
         ${caps.limits.retention_hours} hours.
       </p>`;
  } catch {
    node.innerHTML = '<p class="error">Could not reach the API.</p>';
  }
}

function renderLegal() {
  $("legal-body").innerHTML =
    `${MODALS.terms}<hr style="border-color:var(--edge);margin:32px 0" />${MODALS.dmca}`;
}

// ───────────────────────────────── legal modals ─────────────────────────────

const MODALS = {
  terms: `
    <h2>Terms of use</h2>
    <p class="small" style="color:var(--warn)">Placeholder copy written by engineers.
      Have a lawyer review it before anyone but you uploads to this.</p>
    <h3>What you promise when you upload</h3>
    <p>That you own the recording, hold a licence covering this use, or that your use is
      otherwise permitted by law; that you did not obtain the file by circumventing DRM or
      breaching a streaming service's terms; and that you will not distribute Extract0r's
      output from someone else's recording without permission.</p>
    <h3>What Extract0r does not give you</h3>
    <p>No licence, no permission, and no legal opinion. A transcription of a copyrighted
      song is itself a derivative work of that composition. Private study is often argued
      to be fair use in the United States, but fair use is a defence decided case by case,
      not a permission slip, and other countries treat private copying differently.</p>
    <h3>How long your audio is kept</h3>
    <p>Uploads and everything derived from them are deleted automatically after
      {{retention}} hours. You can delete a track immediately from the stems screen.</p>
    <h3>Accuracy</h3>
    <p>Automatic transcription is approximate. Expect wrong octaves, missed notes in dense
      passages, and fingerings a human would voice differently. Treat the output as a
      starting point, not a published score.</p>`,

  dmca: `
    <h2>Copyright &amp; DMCA</h2>
    <h3>Our position</h3>
    <p>Extract0r is a processing tool. It hosts no catalogue, lets nobody search or share
      another person's uploads, and purges everything on a schedule. Uploaders confirm
      they hold the rights to their audio before anything is processed.</p>
    <h3>Sending a notice</h3>
    <p>A notice should include:</p>
    <ol>
      <li>Identification of the copyrighted work you say has been infringed.</li>
      <li>Identification of the material at issue and enough detail to locate it.</li>
      <li>Your name, address, telephone number, and email address.</li>
      <li>A statement of good-faith belief that the use is not authorised.</li>
      <li>A statement, under penalty of perjury, that you are authorised to act for the
        rights holder.</li>
      <li>Your physical or electronic signature.</li>
    </ol>
    <p>Send it to {{contact}}.</p>`,
};

function openModal(name) {
  $("modal-body").innerHTML = MODALS[name] ?? "";
  $("modal").showModal();
}

// ───────────────────────────────── wiring ───────────────────────────────────

$("dropzone").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => pickFile(e.target.files[0]));

for (const type of ["dragenter", "dragover"]) {
  $("dropzone").addEventListener(type, (e) => {
    e.preventDefault();
    $("dropzone").classList.add("hot");
  });
}
for (const type of ["dragleave", "drop"]) {
  $("dropzone").addEventListener(type, (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("hot");
  });
}
$("dropzone").addEventListener("drop", (e) => pickFile(e.dataTransfer.files[0]));

$("owns").addEventListener("change", refreshUploadButton);
$("personal").addEventListener("change", refreshUploadButton);
$("upload-btn").addEventListener("click", upload);
$("transcribe-btn").addEventListener("click", transcribe);
$("play-btn").addEventListener("click", togglePlay);
$("timing-halve").addEventListener("click", () => nudgeTempo(0.5));
$("timing-double").addEventListener("click", () => nudgeTempo(2));
$("clear-solo").addEventListener("click", () => {
  for (const lane of state.lanes.values()) lane.solo = false;
  applyGains();
});

$("delete-btn").addEventListener("click", async () => {
  await api(`/tracks/${state.trackId}`, { method: "DELETE" }).catch(() => {});
  location.reload();
});
$("restart-btn").addEventListener("click", () => location.reload());

$("nav-toggle").addEventListener("click", () =>
  ($("nav").hidden ? openNav() : closeNav()));
$("scrim").addEventListener("click", closeNav);
document.querySelectorAll(".nav-item").forEach((item) =>
  item.addEventListener("click", () => goToPage(item.dataset.page)));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("nav").hidden) closeNav();
});

$("ref-dropzone").addEventListener("click", () => $("ref-file").click());
$("ref-file").addEventListener("change", (e) => pickReference(e.target.files[0]));
for (const type of ["dragenter", "dragover"]) {
  $("ref-dropzone").addEventListener(type, (e) => {
    e.preventDefault();
    $("ref-dropzone").classList.add("hot");
  });
}
for (const type of ["dragleave", "drop"]) {
  $("ref-dropzone").addEventListener(type, (e) => {
    e.preventDefault();
    $("ref-dropzone").classList.remove("hot");
  });
}
$("ref-dropzone").addEventListener("drop", (e) => pickReference(e.dataTransfer.files[0]));

/** Fetch a reference from a link instead of uploading one.

The server does the fetching and enforces what a URL may point at, so this only has to
report back - the interesting refusals (streaming sites, internal addresses) arrive as
ordinary error messages and are worth showing verbatim. */
async function fetchReferenceUrl() {
  const url = $("ref-url").value.trim();
  if (!url) return;

  const button = $("ref-url-btn");
  button.disabled = true;
  button.textContent = "Fetching…";
  $("ref-error").hidden = true;

  try {
    const info = await api(`/tracks/${state.trackId}/reference/url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, owns_or_licensed: true }),
    });

    state.referenceLoaded = true;
    state.referenceFile = null;
    $("ref-dropzone").classList.add("has-file");
    $("ref-name").textContent = info.filename;
    const loudness =
      info.integrated_lufs != null ? ` · ${info.integrated_lufs.toFixed(1)} LUFS` : "";
    $("ref-hint").textContent =
      `${info.duration_s.toFixed(0)}s${loudness} — fetched, will be matched`;
    $("ref-url").value = "";

    updateMasterSummary();
    await refreshPerStemState();
    await loadSuggestion();
  } catch (error) {
    state.referenceLoaded = false;
    fail("ref-error", error);
  } finally {
    button.disabled = false;
    button.textContent = "Fetch";
  }
}

$("ref-url-btn").addEventListener("click", fetchReferenceUrl);
$("ref-url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    fetchReferenceUrl();
  }
});

$("strength").addEventListener("input", () => {
  $("strength-out").textContent = `${$("strength").value}%`;
});
$("vocal-duck").addEventListener("input", () => {
  $("vocal-duck-out").textContent = `${parseFloat($("vocal-duck").value).toFixed(1)} dB`;
});
// "off" rather than "0.0 dB" at centre: a dial doing nothing should say so.
$("brightness").addEventListener("input", () => {
  const value = parseFloat($("brightness").value);
  $("brightness-out").textContent = value ? `${signed(value.toFixed(1))} dB` : "off";
});
$("width-profile").addEventListener("input", () => {
  const value = parseInt($("width-profile").value, 10);
  $("width-profile-out").textContent =
    value === 0 ? "off" : value === 100 ? "100% (full match)" : `${value}%`;
});
$("stereo-width").addEventListener("input", () => {
  const value = parseInt($("stereo-width").value, 10);
  $("stereo-width-out").textContent =
    value === 100 ? "100% (as mixed)" : `${value}%`;
});
$("headroom").addEventListener("input", () => {
  const value = parseFloat($("headroom").value);
  $("headroom-out").textContent = value ? `-${value.toFixed(1)} dB` : "off";
});
$("bass").addEventListener("input", () => {
  const value = parseFloat($("bass").value);
  $("bass-out").textContent = value ? `${signed(value.toFixed(1))} dB` : "off";
});
$("warmth").addEventListener("input", () => {
  const value = parseFloat($("warmth").value);
  $("warmth-out").textContent = value ? `${signed(value.toFixed(1))} dB` : "off";
});
for (const button of document.querySelectorAll(".mode")) {
  button.addEventListener("click", () => selectMode(button.dataset.mode));
}
// The same thing the Suggested chip does, put where someone has just finished reading
// why they would want it.
$("apply-suggested").addEventListener("click", () => {
  selectMode("suggested");
  $("modes").scrollIntoView({ behavior: "smooth", block: "start" });
});
// Touching a slider means the preset no longer describes what is set.
for (const id of ["brightness", "warmth", "bass", "stereo-width", "width-profile", "headroom"]) {
  $(id).addEventListener("input", () => {
    if (settingDials || !state.mode) return;
    state.mode = null;
    document.querySelectorAll(".mode").forEach((b) => b.setAttribute("aria-pressed", "false"));
  });
}
$("kit-on").addEventListener("change", () => {
  const on = $("kit-on").checked;
  $("kit-options").hidden = !on;
  $("kit-note").hidden = !on;
  $("kit-note").textContent =
    "Hi-hats are off by default: they are the densest part of a kit and the least " +
    "forgiving, so a mistriggered hat is far more audible than a reinforced kick.";
  if (on) loadDrumKits();
});
$("kit-blend").addEventListener("input", () => {
  $("kit-blend-out").textContent = `${$("kit-blend").value}%`;
});
$("master-btn").addEventListener("click", runMaster);
$("separate-ref-btn").addEventListener("click", separateReference);
$("per-stem-match").addEventListener("change", () => {
  $("per-stem-options").hidden = !$("per-stem-match").checked;
});

$("modal-close").addEventListener("click", () => $("modal").close());
document.addEventListener("click", (e) => {
  const trigger = e.target.closest("[data-modal]");
  if (!trigger) return;
  e.preventDefault();
  openModal(trigger.dataset.modal);
});

// Space bar is the transport control every DAW uses; match it.
document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || $("step-stems").hidden) return;
  if (["INPUT", "BUTTON", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  e.preventDefault();
  togglePlay();
});

// ───────────────────────────────── boot ─────────────────────────────────────

(async function boot() {
  await loadLegal();
  goToPage("master");
  await loadCapabilities();
  try {
    state.tunings = await api("/tracks/tunings");
  } catch {
    state.tunings = {};
  }
})();
