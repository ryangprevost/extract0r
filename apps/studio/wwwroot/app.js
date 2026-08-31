// Extract0r Studio front end. Vanilla JS on purpose: no build step, no node_modules,
// open the .sln and press F5. Requests go to /api on this origin and the ASP.NET host
// proxies them to the Python service, so there is no CORS to think about.

const $ = (id) => document.getElementById(id);
const API = "/api/v1";

// Stems worth offering for transcription. Vocals produce a pitch list, not tab, and are
// left off until X0R-411 makes that useful.
const TRANSCRIBABLE = ["bass", "guitar", "piano", "drums", "other"];
const LABELS = {
  vocals: "Vocals", drums: "Drums", bass: "Bass",
  guitar: "Guitar", piano: "Piano", other: "Other",
};

const state = {
  file: null,
  trackId: null,
  stems: [],
  tunings: {},
  picked: new Set(),
  chosenTuning: {},
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

/** Poll a job until it settles, driving the progress panel as it goes. */
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

// ───────────────────────────────── capabilities ─────────────────────────────

async function loadCapabilities() {
  try {
    const caps = await api("/capabilities");
    $("limits").textContent =
      `or click to choose — up to ${caps.limits.max_upload_mb} MB · mp3, wav, flac, m4a, ogg, aiff`;

    // Show what the server actually has, not what it was configured to want. The two
    // differ more often than you would like, and the app silently falls back to stubs.
    const order = ["demucs", "basic_pitch", "pyin", "onset_drums", "ffmpeg"];
    $("backends").innerHTML = order
      .map((name) => {
        const on = caps.installed[name];
        return `<span class="chip ${on ? "on" : "off"}" title="${
          on ? "installed" : "not installed on this server"
        }">${name}${on ? "" : " ✕"}</span>`;
      })
      .join("");

    if (!caps.installed.demucs) {
      fail("upload-error",
        "This server has no Demucs installed, so separation will return copies of your " +
        "file rather than real stems. See docs/RUNBOOK.md.");
    }
  } catch {
    $("backends").innerHTML = '<span class="chip off">API unreachable ✕</span>';
    fail("upload-error",
      "Could not reach the Extract0r API. Start it with scripts/dev-api.ps1, then reload.");
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
  const zone = $("dropzone");
  zone.classList.add("has-file");
  $("dropzone-label").innerHTML =
    `<span class="big">${file.name}</span>
     <span class="small">${(file.size / 1024 / 1024).toFixed(1)} MB — click to choose a different file</span>`;
  $("upload-error").hidden = true;
  refreshUploadButton();
}

async function upload() {
  $("upload-error").hidden = true;
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

    const job = await api(`/tracks/${track.track_id}/separate`, { method: "POST" });
    await runJob(
      job.job_id,
      "Splitting the track into stems…",
      "Demucs runs on the CPU at roughly twice the length of the audio. The very first " +
      "run also downloads the model, which takes a few minutes more.",
    );

    const separation = await api(`/tracks/${track.track_id}/stems`);
    renderStems(separation, track);
  } catch (error) {
    showOnly("step-upload");
    fail("upload-error", error);
  }
}

// ───────────────────────────────── stems ────────────────────────────────────

function renderStems(separation, track) {
  state.stems = separation.stems.filter((s) => TRANSCRIBABLE.includes(s.stem));
  state.picked.clear();

  $("sep-backend").textContent =
    `${separation.backend}:${separation.model} · ${track.duration_s}s · ${track.sample_rate} Hz`;

  const tuningOptions = Object.entries(state.tunings)
    .map(([key, t]) => `<option value="${key}">${t.name}</option>`)
    .join("");

  $("stems").innerHTML = state.stems
    .map((s) => `
      <div class="stem" data-stem="${s.stem}">
        <label>
          <input type="checkbox" data-pick="${s.stem}" />
          <span>${LABELS[s.stem] ?? s.stem}</span>
          <span class="meta">${s.duration_s}s</span>
        </label>
        ${s.stem === "drums"
          ? '<span class="hint">Drum notation — no tuning needed.</span>'
          : `<select data-tuning="${s.stem}">
               <option value="">Default tuning</option>${tuningOptions}
             </select>`}
      </div>`)
    .join("");

  $("stems").querySelectorAll("[data-pick]").forEach((box) => {
    box.addEventListener("change", () => {
      const stem = box.dataset.pick;
      box.checked ? state.picked.add(stem) : state.picked.delete(stem);
      box.closest(".stem").classList.toggle("picked", box.checked);
      const count = state.picked.size;
      $("transcribe-btn").disabled = count === 0;
      $("transcribe-btn").textContent =
        count === 0 ? "Transcribe" : `Transcribe ${count} stem${count === 1 ? "" : "s"}`;
    });
  });

  $("stems").querySelectorAll("[data-tuning]").forEach((select) => {
    select.addEventListener("change", () => {
      state.chosenTuning[select.dataset.tuning] = select.value;
    });
  });

  showOnly("step-stems");
}

async function transcribe() {
  $("stems-error").hidden = true;
  const tunings = {};
  for (const stem of state.picked) {
    if (state.chosenTuning[stem]) tunings[stem] = state.chosenTuning[stem];
  }

  try {
    const job = await api(`/tracks/${state.trackId}/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stems: [...state.picked], tunings }),
    });
    const finished = await runJob(job.job_id, "Writing the tab…");
    renderTabs(finished.result);
  } catch (error) {
    showOnly("step-stems");
    fail("stems-error", error);
  }
}

// ───────────────────────────────── tabs ─────────────────────────────────────

function renderTabs(result) {
  $("x0r-link").href = `${API}/tracks/${state.trackId}/x0r`;

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
        <article class="tab">
          <header>
            <h3>${LABELS[a.stem] ?? a.stem}
              <span class="muted small">${a.note_count} notes · ${a.notation.replace("_", " ")}</span>
            </h3>
            <a class="link" href="${API}/tracks/${state.trackId}/tabs/${a.stem}"
               download="${a.stem}.txt">Download .txt</a>
          </header>
          ${note}
          <pre>${escapeHtml(a.preview)}</pre>
        </article>`;
    })
    .join("");

  showOnly("step-tabs");
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
