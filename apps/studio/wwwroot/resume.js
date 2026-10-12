// ──────────────────────── pick up a track the server still has ────────────────────────
//
// X0R-1424. X0R-1423 taught the API to read `storage/` back on boot, and **the page still
// could not reach any of it.** `state.trackId` is written in exactly one place - the upload
// handler in app.js - so a reload, or the API being restarted under a live page, left
// finished separations addressable only by someone who knew the id and had curl. Ryan hit
// this with 534 MB of completed work on disk: both six-stem separations and one side of the
// per-drum split, all of it recovered server-side, none of it reachable from the screen.
//
// That is the complaint X0R-1423 was written about, one layer up. Its own governing line is
// that a tool is allowed not to remember, but not *"to write a person's audio to disk, lose
// the only pointer to it, and then delete it."* The server remembered. The pointer was still
// lost from where the user was sitting.
//
// **This is still not EPIC-07.** Nothing new is persisted, no session, no account, no
// database. It lists what is already in memory because it was already on disk, and offers
// it. The directory layout is still the whole of the record.

const Resume = (() => {
  //: What the per-drum comparison needs on both sides before it can say anything. Listed
  //: so a row can tell the truth about what resuming will get you *before* it is clicked,
  //: rather than landing somebody on a panel that turns out to be half empty.
  const DRUMS = ["bombo", "redoblante", "platillos", "toms"];

  function split(track) {
    const drums = track.drums || {};
    return {
      stems: (track.stems || []).length,
      reference: (track.reference_stems || []).length > 0,
      sourceDrums: (drums.source || []).length >= DRUMS.length,
      referenceDrums: (drums.reference || []).length >= DRUMS.length,
    };
  }

  /** What this track can actually show, said plainly rather than implied by an enabled button. */
  function describe(track) {
    const has = split(track);
    const parts = [];
    if (has.stems) parts.push(has.stems + " stems");
    if (has.reference) parts.push("reference split");
    if (has.sourceDrums && has.referenceDrums) parts.push("drums split both sides");
    else if (has.sourceDrums) parts.push("drums split on yours only");
    if (!parts.length) parts.push("uploaded, nothing split yet");
    return parts.join(" · ");
  }

  function row(track) {
    const has = split(track);
    const item = document.createElement("div");
    item.className = "resume-row";

    const text = document.createElement("div");
    text.innerHTML =
      `<strong>${escapeText(track.name || "a track")}</strong>` +
      `<span class="muted small"> — ${escapeText(describe(track))}</span>`;
    item.appendChild(text);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary small";
    button.textContent = has.reference ? "Open the comparison" : "Open the mixer";
    button.addEventListener("click", () => open(track, button));
    item.appendChild(button);

    // An adopted record has no rights attestation - X0R-1423 records it as adopted rather
    // than inventing one - and anything that needs a fresh claim will still ask.
    if (track.adopted) {
      const note = document.createElement("p");
      note.className = "muted small";
      note.textContent =
        "Recovered from disk after a restart. Its measurements are intact; " +
        "what it was aimed at is not, so pick a reference profile again if you had one.";
      item.appendChild(note);
    }
    return item;
  }

  /**
   * Walk the same path the upload handler walks once separation is done.
   *
   * Deliberately the same calls in the same order rather than a shortcut: `buildMixer`,
   * then `afterReferenceUpload`, then the instrument comparison. Any other route here
   * would be a second way to reach the main screen, and the two would drift.
   */
  async function open(track, button) {
    const note = $("resume-note");
    button.disabled = true;
    try {
      state.trackId = track.track_id;

      const separation = await api(`/tracks/${track.track_id}/stems`);
      // An adopted record never opened the audio - reading six files at boot to fill in
      // two numbers would turn a restart into a wait - so the duration comes from the
      // stems now, when something actually needs it.
      state.duration = separation.stems?.[0]?.duration_s || 0;
      await buildMixer(separation, { track_id: track.track_id, duration_s: state.duration });

      if (typeof refreshLibraryPanel === "function") await refreshLibraryPanel();
      if (typeof refreshProfilePanels === "function") await refreshProfilePanels();

      if ((track.reference_stems || []).length) {
        state.referenceLoaded = true;
        if (note) note.textContent = "Measuring your mix against the reference…";
        await afterReferenceUpload();
        if (state.referenceSeparated) {
          if (note) note.textContent = "Comparing the instruments…";
          await loadInstrumentComparison();
        }
      }
      // Wherever the person is now. This was "master", which took anybody who opened a
      // song from pr0ducer - or went there while it loaded - back to the mastering studio.
      goToPage(state.page);
    } catch (error) {
      if (note) note.textContent = error.message || String(error);
      button.disabled = false;
    }
  }

  async function init() {
    const panel = $("resume-panel");
    if (!panel) return;
    let tracks = [];
    try {
      tracks = (await api("/tracks")).tracks || [];
    } catch {
      // A landing page that fails to render because a convenience did not load is worse
      // than one without the convenience.
      return;
    }
    if (!tracks.length) return;

    const list = $("resume-list");
    list.innerHTML = "";
    for (const track of tracks) list.appendChild(row(track));
    $("resume-note").textContent =
      tracks.length === 1
        ? "One track is still on this machine. Separating it again would cost the same minutes twice."
        : tracks.length + " tracks are still on this machine, already split.";
    panel.hidden = false;
  }

  return { init, open };
})();

document.addEventListener("DOMContentLoaded", () => Resume.init());
