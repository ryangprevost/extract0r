// Reference profiles: what a song teaches, kept without the song.
//
// Everything the whole-mix match reads from a reference is a measurement of it - a
// spectrum, side-to-mid per band, a loudness and two peaks. So a reference can be reduced
// to those numbers once and aimed at for ever, and the audio never has to be kept.
//
// Which is also why this exists rather than a streaming picker. Measurements of a
// recording are facts about it, in the same family as its tempo or its key; six kilobytes
// of magnitudes with the phase discarded describes a song and cannot become one.
//
// The one thing it cannot do is per-instrument matching, and every surface here says so:
// comparing your snare with theirs needs their snare, and stems are audio.

/** Show or hide the "save this reference" box, depending on whether there is one. */
async function refreshProfilePanels() {
  const save = document.getElementById("save-profile");
  const pick = document.getElementById("profile-pick");
  if (!save || !pick || !state.trackId) return;

  // Saving needs a reference *file* on this track. A track already aimed at a profile has
  // nothing new to measure, so the box would be offering to re-save what it is using.
  save.hidden = !(state.referenceLoaded && !state.usingProfile);

  if (state.referenceLoaded) {
    pick.hidden = true;
    return;
  }
  await renderProfileList();
}

async function renderProfileList() {
  const pick = document.getElementById("profile-pick");
  const host = document.getElementById("profile-list");

  let body;
  try {
    body = await api("/tracks/reference/profiles");
  } catch {
    pick.hidden = true;
    return;
  }

  const profiles = body.profiles ?? [];
  if (!profiles.length) {
    // Nothing saved yet. Offering an empty list teaches nobody what the feature is, and
    // the way to get one is to load a reference, which the panels above already offer.
    pick.hidden = true;
    return;
  }

  pick.hidden = false;
  host.innerHTML = "";
  for (const profile of profiles) {
    const row = document.createElement("div");
    row.className = "candidate";
    row.innerHTML =
      `<div class="candidate-text">
         <strong>${escapeText(profile.name)}</strong>
         <em>${escapeText(describeProfile(profile))}</em>
       </div>
       <button class="primary small use-profile">Aim at this</button>`;
    row.querySelector(".use-profile").addEventListener("click", () =>
      useProfile(profile, row),
    );
    host.appendChild(row);
  }
}

function describeProfile(profile) {
  const bits = [];
  if (profile.captured_from) bits.push(`from ${profile.captured_from}`);
  if (typeof profile.lufs === "number") bits.push(`${profile.lufs.toFixed(1)} LUFS`);
  if (profile.captured_at) bits.push(`measured ${profile.captured_at.slice(0, 10)}`);
  return bits.join(" · ");
}

async function saveProfile() {
  const input = document.getElementById("profile-name");
  const button = document.getElementById("profile-save-btn");
  const saved = document.getElementById("profile-saved");
  document.getElementById("ref-error").hidden = true;

  const name = input.value.trim();
  if (!name) {
    input.focus();
    return;
  }

  button.disabled = true;
  button.textContent = "Measuring…";
  try {
    const result = await api(`/tracks/${state.trackId}/reference/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    saved.textContent =
      `Saved “${result.name}” — ${(result.bytes / 1024).toFixed(1)} KB of measurements. ` +
      `Any future mix can aim at this without the audio.`;
    saved.hidden = false;
    input.value = "";
  } catch (error) {
    fail("ref-error", error);
  } finally {
    button.disabled = false;
    button.textContent = "Save profile";
  }
}

async function useProfile(profile, row) {
  const button = row.querySelector(".use-profile");
  button.disabled = true;
  button.textContent = "Loading…";
  document.getElementById("ref-error").hidden = true;

  try {
    const result = await api(`/tracks/${state.trackId}/reference/use-profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: profile.name }),
    });

    state.referenceLoaded = true;
    // Flagged, because a profile is not a reference file and two things behave
    // differently as a result: there is nothing to separate, so per-instrument matching
    // is unavailable, and there is nothing new to measure, so saving is pointless.
    state.usingProfile = true;
    state.upfrontReference = { name: result.name };

    document.getElementById("ref-hint").textContent =
      `aiming at the saved profile “${result.name}” · ${result.lufs.toFixed(1)} LUFS`;
    document.getElementById("profile-pick").hidden = true;
    document.getElementById("library-pick").hidden = true;

    await afterReferenceUpload();
  } catch (error) {
    button.disabled = false;
    button.textContent = "Aim at this";
    fail("ref-error", error);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("profile-save-btn");
  if (button) button.addEventListener("click", saveProfile);
  const input = document.getElementById("profile-name");
  if (input) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") saveProfile();
    });
  }
});
