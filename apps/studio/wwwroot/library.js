// Picking a reference from music you already own.
//
// The ranking behind this has existed for a while with nothing to drive it: the server
// could say which of your own records made the best target and there was no way to act on
// the answer short of going and finding the file yourself.
//
// It is also the honest answer to "let me pick a Spotify or YouTube track". Those are
// refused by name in `app.services.fetch`, and the app's own terms are why. What actually
// makes a reference useful is that its audio can be *measured*, which a streaming link
// never offers - so the tool looks at the music already on the machine instead, and can
// explain its choices in a way a genre tag never could.

/** What makes a record a good target rather than a mirror, in one line per candidate. */
function describeCandidate(c) {
  const bits = [];
  if (c.louder_by_db > 0.5) bits.push(`${c.louder_by_db.toFixed(1)} dB louder`);
  if (c.wider_above_1k_by_db > 0.5) bits.push(`wider up top`);
  if (c.tighter_below_250_by_db > 0.5) bits.push(`tighter underneath`);
  if (c.mono) bits.push("mono");
  return bits.join(" · ");
}

async function refreshLibraryPanel() {
  const panel = document.getElementById("library-pick");
  if (!panel || !state.trackId) return;

  // Only offered once a reference is still wanted. With one already loaded the panel is
  // noise, and swapping it underneath a comparison computed against the old one is worse
  // than noise.
  if (state.referenceLoaded) {
    panel.hidden = true;
    return;
  }

  let status;
  try {
    status = await api(`/tracks/${state.trackId}/reference/library`);
  } catch {
    panel.hidden = true;
    return;
  }

  panel.hidden = false;
  const note = document.getElementById("library-note");
  const scan = document.getElementById("library-scan");

  if (!status.configured) {
    note.innerHTML =
      `${status.why} Then reload this page — the scan runs on the server, so the folder ` +
      `never leaves your machine and no audio is uploaded.`;
    scan.hidden = true;
    return;
  }
  note.textContent =
    `Reading ${status.path}. Nothing is copied: each file is measured for tonal balance, ` +
    `loudness and stereo image, and only the measurements are kept.`;
  scan.hidden = false;
}

async function scanLibrary() {
  const scan = document.getElementById("library-scan");
  const working = document.getElementById("library-working");
  const results = document.getElementById("library-results");
  document.getElementById("ref-error").hidden = true;

  scan.disabled = true;
  working.hidden = false;
  results.innerHTML = "";

  try {
    const job = await api(`/tracks/${state.trackId}/reference/suggestions`, {
      method: "POST",
    });
    const result = await pollJobQuietly(job.job_id);

    if (!result.available) {
      results.innerHTML = `<p class="muted small">${result.why ?? "Nothing to measure."}</p>`;
      return;
    }
    renderCandidates(result);
  } catch (error) {
    fail("ref-error", error);
  } finally {
    working.hidden = true;
    scan.disabled = false;
    scan.textContent = "Scan again";
  }
}

function renderCandidates(result) {
  const results = document.getElementById("library-results");
  const candidates = result.candidates ?? [];

  if (!candidates.length) {
    results.innerHTML =
      `<p class="muted small">Measured ${result.scanned} file(s) and found nothing close ` +
      `enough to be a useful target. A reference wants to be the same sort of ` +
      `arrangement as your song, further along in how it was mastered.</p>`;
    return;
  }

  results.innerHTML =
    `<p class="muted small">Measured ${result.scanned} file(s). Ranked by how close their ` +
    `tonal balance is to yours — the nearest is the most sensible target, not the best ` +
    `song. Anything that already sounds like your mix is left out: it has nothing to ` +
    `teach.</p><div class="candidates"></div>`;

  const host = results.querySelector(".candidates");
  for (const c of candidates.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "candidate";
    row.innerHTML =
      `<div class="candidate-text">
         <strong>${escapeText(c.name)}</strong>
         <em>${escapeText(c.why ?? "")}</em>
         <span class="candidate-stats">${describeCandidate(c)}</span>
       </div>
       <button class="primary small use-candidate">Use this</button>`;
    row.querySelector(".use-candidate").addEventListener("click", () => useCandidate(c, row));
    host.appendChild(row);
  }
}

/** Names come off the filesystem, so they are text rather than markup. */
function escapeText(value) {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
}

async function useCandidate(candidate, row) {
  const button = row.querySelector(".use-candidate");
  button.disabled = true;
  button.textContent = "Loading…";
  document.getElementById("ref-error").hidden = true;

  try {
    const info = await api(`/tracks/${state.trackId}/reference/from-library`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: candidate.path }),
    });

    state.referenceLoaded = true;
    // The rest of the page reads this to decide whether a reference can still be swapped,
    // and the up-front dropzone is not where this one came from. The candidate's own name
    // rather than `info.filename`: every reference is stored as "reference.mp3", which is
    // fine on disk and useless on screen.
    state.upfrontReference = { name: candidate.name };

    const loudness =
      info.integrated_lufs != null ? ` · ${info.integrated_lufs.toFixed(1)} LUFS` : "";
    document.getElementById("ref-hint").textContent =
      `${info.duration_s.toFixed(0)}s${loudness} — will be matched`;

    await afterReferenceUpload();
    document.getElementById("library-pick").hidden = true;
  } catch (error) {
    button.disabled = false;
    button.textContent = "Use this";
    fail("ref-error", error);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const scan = document.getElementById("library-scan");
  if (scan) scan.addEventListener("click", scanLibrary);
});
