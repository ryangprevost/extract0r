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
// That runs one level down too. A per-instrument comparison also reads measurements from
// the reference side - seven numbers per stem - so a profile captured while the reference
// was separated carries those as well and drives that screen with no second split.
//
// The one thing no profile can do is play. There is no audio in it, so a reference stem
// cannot be auditioned against yours, and every surface here says which kind it is holding
// rather than letting someone find out on the comparison screen.

/** Show or hide the "save this reference" box, depending on whether there is one. */
async function refreshProfilePanels() {
  const save = document.getElementById("save-profile");
  const pick = document.getElementById("profile-pick");
  if (!save || !pick || !state.trackId) return;

  // Saving needs a reference *file* on this track. A track already aimed at a profile has
  // nothing new to measure, so the box would be offering to re-save what it is using.
  save.hidden = !(state.referenceLoaded && !state.usingProfile);

  // Say up front what this save will contain, because it depends on something the user
  // chose two screens ago and cannot see from here. Finding out afterwards that a profile
  // is whole-mix-only is a worse moment than being told before the click.
  const what = document.getElementById("profile-what");
  if (what) {
    // One level further in, and said separately because it is a separate thing the user
    // may or may not have done: splitting the reference's drums into four happens only
    // if they ran the drum-by-drum comparison. A profile that carries them is the
    // difference between that comparison being instant on the next song and costing a
    // second pass over a reference whose audio is not kept.
    const drums = state.referenceDrumsSplit
      ? " Its drums have been split into kick, snare, cymbals and toms, so <strong>those "
        + "four go in as well</strong> and the next song aimed at this profile reaches "
        + "the drum-by-drum comparison with nothing to wait for."
      : " Its drums have not been split into four, so the drum-by-drum comparison will "
        + "not be in it. Run that comparison on the master page first if you want it.";
    const base = state.referenceSeparated
      ? "Measures it once and stores the numbers — a spectrum, a width profile, a "
        + "loudness, two peaks, <strong>and each of its instruments</strong>. No audio, "
        + "and enough to aim any future mix at this song — including instrument by "
        + "instrument, with only your own song left to split."
      : "Measures it once and stores the numbers — a spectrum, a width profile, a "
        + "loudness and two peaks. About 6 KB, no audio, and enough to aim any future "
        + "mix at this song's overall tone. This reference has not been separated, so "
        + "its instruments will not be in it; turn on instrument-by-instrument matching "
        + "above first if you want them.";
    // X0R-1401: the panel explained what a profile contains and never what it saves.
    // "Only your own song left to split" is true and abstract; the number is the thing
    // that makes somebody click. Measured per X0R-306 and scaled to the song they just
    // waited for, so it is the wait they have personally just experienced.
    what.innerHTML = base + (state.referenceSeparated ? drums : "") + savedTime();
  }

  if (state.referenceLoaded) {
    pick.hidden = true;
    return;
  }
  await renderProfileList();
}

/**
 * How much of the wait a profile removes, in the length of the song they just loaded.
 *
 * Only claimed when the reference was actually separated here, because that is the pass
 * a profile skips. With a whole-mix-only profile the saving is the reference upload and
 * its measurement, which is seconds and not worth a sentence.
 */
function savedTime() {
  if (!state.referenceSeparated) return "";
  if (typeof Waiting === "undefined" || !state.duration) return "";
  const saved = Waiting.separationEstimate(state.duration, 1);
  return (
    " <strong>It also skips this wait.</strong> Splitting that reference took about " +
    Waiting.clock(saved) +
    ", and every future song you aim at this profile starts from the measurements " +
    "instead — so the next one is roughly that much shorter, however many you do."
  );
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

  renderBlend(profiles);
}

// ───────────────────────── one profile per instrument ─────────────────────────
//
// X0R-1419, and the decision it runs on is Ryan's: **character, not balance.**
//
// A borrowed instrument brings its tone, dynamics, placement and width, and declines to
// bring its level. How loud an instrument sits is a fact about the mix it sat in, so a set
// of levels taken from different records is a balance that existed on none of them. The
// server enforces that; this screen's job is to say it before anybody is surprised by it.

//: The stems a blend can be built from, in the order the comparison lists them.
const BLEND_STEMS = [
  ["vocals", "Vocals"],
  ["drums", "Drums"],
  ["bass", "Bass"],
  ["guitar", "Guitars"],
  ["piano", "Piano"],
  ["other", "Everything else"],
];

function renderBlend(profiles) {
  const panel = document.getElementById("profile-blend");
  if (!panel) return;

  // Only profiles that were captured from a separated reference have instruments to lend,
  // and a blend needs at least two of them to be a blend.
  const lenders = profiles.filter((p) => p.per_stem);
  if (lenders.length < 2) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  document.getElementById("blend-rule").innerHTML =
    "The first row sets the <strong>overall tone, loudness and width</strong> — that half " +
    "describes a finished master and can only come from one record. Each instrument after " +
    "it may come from anywhere. <strong>A borrowed instrument brings its tone, dynamics, " +
    "placement and width, and not its level</strong>: how loud a guitar sits is a fact " +
    "about the mix it sat in, so matching a borrowed one would place yours against " +
    "neighbours that record never had.";

  const rows = document.getElementById("blend-rows");
  rows.innerHTML = "";

  const options = (selected) =>
    lenders
      .map(
        (p) =>
          '<option value="' + escapeText(p.name) + '"' +
          (p.name === selected ? " selected" : "") +
          ">" + escapeText(p.name) + "</option>",
      )
      .join("");

  const base = lenders[0].name;

  const baseRow = document.createElement("label");
  baseRow.className = "blend-row blend-base";
  baseRow.innerHTML =
    "<span>Overall tone and loudness</span>" +
    '<select id="blend-base">' + options(base) + "</select>";
  rows.appendChild(baseRow);

  for (const [stem, label] of BLEND_STEMS) {
    // A stem only appears when at least one profile actually carries it; offering to
    // borrow a piano nobody measured is a dropdown that cannot work.
    const carriers = lenders.filter((p) => (p.instruments || []).includes(stem));
    if (!carriers.length) continue;

    const row = document.createElement("label");
    row.className = "blend-row";
    row.innerHTML =
      "<span>" + label + "</span>" +
      '<select data-blend-stem="' + stem + '">' +
      '<option value="">— same as the overall —</option>' +
      carriers
        .map((p) => '<option value="' + escapeText(p.name) + '">' +
          escapeText(p.name) + "</option>")
        .join("") +
      "</select>";
    rows.appendChild(row);
  }

  const button = document.getElementById("blend-use");
  button.onclick = () => useBlend();
}

async function useBlend() {
  const said = document.getElementById("blend-said");
  const button = document.getElementById("blend-use");
  const base = document.getElementById("blend-base").value;

  const instruments = {};
  document.querySelectorAll("[data-blend-stem]").forEach((select) => {
    if (select.value && select.value !== base) {
      instruments[select.dataset.blendStem] = select.value;
    }
  });

  if (!Object.keys(instruments).length) {
    said.textContent =
      "Nothing is borrowed yet — every instrument is set to the overall record, which is " +
      "the same as aiming at it directly.";
    said.hidden = false;
    return;
  }

  button.disabled = true;
  said.hidden = true;
  try {
    const name = document.getElementById("blend-name").value.trim();
    const result = await api(`/tracks/${state.trackId}/reference/combine-profiles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base, instruments, save_as: name || null }),
    });

    state.referenceLoaded = true;
    state.usingProfile = true;
    state.profileHasInstruments = !!result.per_stem_available;

    const borrowed = Object.entries(result.borrowed || {})
      .map(([stem, from]) => stem + " from " + from)
      .join(", ");
    const parts = [
      "Aiming at " + base + (borrowed ? ", with " + borrowed + "." : "."),
      result.note,
    ];
    // What was asked for and could not be lent. Said plainly: a profile captured from an
    // unseparated reference has no instruments in it, and quietly falling back to the
    // base would look like the borrowing had worked.
    if ((result.unavailable || []).length) {
      parts.push(
        "No instruments in " +
          result.unavailable.join(", ") +
          "'s profile to borrow — it was measured whole-mix only, so those stayed with " +
          base + ".",
      );
    }
    if (result.saved) parts.push("Kept as “" + result.name + "”.");
    said.textContent = parts.join(" ");
    said.hidden = false;

    const hint = document.getElementById("ref-hint");
    if (hint) hint.textContent = "aiming at a blend of " + ((borrowed ? 1 : 0) + 1) + " profiles";
    await refreshProfilePanels();
  } catch (error) {
    said.textContent = error.message || String(error);
    said.hidden = false;
  } finally {
    button.disabled = false;
  }
}

function describeProfile(profile) {
  const bits = [];
  if (profile.captured_from) bits.push(`from ${profile.captured_from}`);
  if (typeof profile.lufs === "number") bits.push(`${profile.lufs.toFixed(1)} LUFS`);
  // The difference that decides which screens this profile can drive, so it goes in the
  // row rather than behind a click.
  bits.push(
    profile.per_stem
      ? `${profile.instruments.length} instruments`
      : "whole mix only",
  );
  // A third state, and distinct from both of the above: six stems *and* the four drums
  // inside one of them. Rare, so it is worth calling out rather than folding into the
  // instrument count.
  if (profile.per_drum) bits.push(`${profile.drums.length} drums`);
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
    // Say which kind was written. The difference is not the user's fault and not visible
    // from anything they did - it depends on whether this track's reference happened to
    // have been separated - so leaving them to discover it later would be a trap.
    const andDrums = result.per_drum
      ? ` Its drums are in there too, split into ${result.drums.length} — so the next `
        + "song aimed at this reaches the drum-by-drum comparison with no second split "
        + "of either side."
      : "";
    saved.textContent = result.per_stem
      ? `Saved “${result.name}” — ${(result.bytes / 1024).toFixed(1)} KB of measurements, `
        + `including all ${result.instruments.length} of the reference's instruments. Any `
        + "future mix can aim at this and get the instrument-by-instrument comparison "
        + "from one split instead of two."
      : `Saved “${result.name}” — ${(result.bytes / 1024).toFixed(1)} KB of measurements. `
        + "Any future mix can aim at this without the audio, for overall tone. This "
        + "reference was not separated, so there are no instruments in it; separate it "
        + "and save again to include them.";
    saved.textContent += andDrums;
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
    state.profileHasInstruments = !!result.per_stem_available;
    // Read by the drums card: a profile that carries the four drums reaches the per-drum
    // comparison with only this song's own drums left to split.
    state.profileHasDrums = !!result.per_drum_available;
    state.upfrontReference = { name: result.name };

    const reach =
      (result.per_stem_available
        ? ` · ${result.instruments.length} instruments measured`
        : " · whole mix only") +
      (result.per_drum_available ? ` · ${result.drums.length} drums` : "");
    document.getElementById("ref-hint").textContent =
      `aiming at the saved profile “${result.name}” · ${result.lufs.toFixed(1)} LUFS${reach}`;
    document.getElementById("profile-pick").hidden = true;
    document.getElementById("library-pick").hidden = true;

    await afterReferenceUpload();
    // A profile with instruments makes the comparison possible immediately, so run it
    // rather than leaving a button the user has to find.
    if (state.profileHasInstruments && typeof loadInstrumentComparison === "function") {
      await loadInstrumentComparison();
    }
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
