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
  picked: new Set(),
  tunings: {},
  chosenTuning: {},
  playing: false,
  timing: null,
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

  for (;;) {
    const job = await api(`/jobs/${jobId}`);
    $("progress-fill").style.width = `${Math.round(job.progress * 100)}%`;
    $("progress-message").textContent = job.message;
    if (job.state === "succeeded") return job;
    if (job.state === "failed") throw new Error(job.error ?? "The job failed.");
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

function showOnly(...ids) {
  for (const id of ["step-upload", "step-progress", "step-stems", "step-tabs"]) {
    $(id).hidden = !ids.includes(id);
  }
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
  try {
    const caps = await api("/capabilities");

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
    return true;
  } catch {
    $("backends").innerHTML = '<span class="chip off">API unreachable ✕</span>';
    if (!quiet) {
      fail("upload-error",
        "Cannot reach the Extract0r API yet — it may still be starting up. " +
        "Retrying automatically; no need to reload.");
    }
    // Keep trying rather than stranding the page on a stale error.
    if (!apiRetry) apiRetry = setInterval(() => loadCapabilities({ quiet: true }), 3000);
    return false;
  }
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
  $("dropzone").classList.add("has-file");
  $("dropzone-label").innerHTML =
    `<span class="big">${file.name}</span>
     <span class="small">${(file.size / 1024 / 1024).toFixed(1)} MB — click to choose a different file</span>`;
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
  showOnly("step-stems");
  loadTiming();

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
    lane.element.classList.toggle("dimmed", !audible);
    lane.element.querySelector("[data-solo]")?.classList.toggle("on", lane.solo);
    lane.element.querySelector("[data-mute]")?.classList.toggle("on", lane.muted);
    void stem;
  }
  $("clear-solo").hidden = !soloed;
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
    showOnly("step-stems");
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
  showOnly("step-stems", "step-tabs");
  $("step-tabs").scrollIntoView({ behavior: "smooth", block: "start" });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
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
  await loadCapabilities();
  try {
    state.tunings = await api("/tracks/tunings");
  } catch {
    state.tunings = {};
  }
})();
