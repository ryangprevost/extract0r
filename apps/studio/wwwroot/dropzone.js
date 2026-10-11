// ───────────────────────── dropping a file, and knowing early ─────────────────────────
//
// X0R-203, open since the first sprint with three criteria and none of them met. The one
// that bothered me enough to pick this up: **the song dropzone has said "Drop an audio file
// here" since the day it shipped, and nothing listened for a drop.** An interface that
// names a gesture it ignores is worse than one that does not offer it — the user tries,
// nothing happens, and there is no way to tell a broken page from a wrong file.
//
// The *reference* zone beside it did handle drops, with its own inline listeners, which is
// probably why nobody noticed: dropping worked on one of two identical-looking targets. Its
// handlers are gone now, because they skipped the checks below and because two sets of
// listeners on one element means two sources of truth for the highlight — the way a drop
// target ends up stuck looking active after the cursor has left.
//
// The other two are about finding out early. A six-minute song is 60 MB and the server
// refuses anything over `max_duration_s` — on a slow connection that refusal currently
// arrives after the whole upload. The browser can decode the header and know in a second,
// so the refusal happens before a byte moves.
//
// **The server still enforces all of it.** Nothing here is a security control; a check in
// a page the user controls never is. These exist so the answer arrives at the right moment,
// not so the answer exists at all.

const Dropzone = (() => {
  //: Filled from `/capabilities` so the page and the server cannot drift apart on what the
  //: limits are. Until it answers, nothing is refused locally - the server will.
  let limits = null;

  /**
   * How long the audio is, read in the browser.
   *
   * `decodeAudioData` on the first slice rather than the whole file: a 60 MB decode takes
   * seconds and allocates hundreds of megabytes, and the duration is in the header. The
   * fallback is an `<audio>` element, which reads metadata without decoding at all and
   * handles the formats WebAudio will not.
   *
   * Returns null when neither works. A browser that cannot read it is not a reason to
   * block an upload the server might accept.
   */
  async function duration(file) {
    const viaElement = () =>
      new Promise((resolve) => {
        const url = URL.createObjectURL(file);
        const audio = new Audio();
        const done = (value) => {
          URL.revokeObjectURL(url);
          resolve(value);
        };
        audio.addEventListener("loadedmetadata", () =>
          done(Number.isFinite(audio.duration) ? audio.duration : null),
        );
        audio.addEventListener("error", () => done(null));
        // A format the browser will not touch should not hang the upload button.
        setTimeout(() => done(null), 4000);
        audio.preload = "metadata";
        audio.src = url;
      });

    const fromElement = await viaElement();
    if (fromElement !== null) return fromElement;

    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      const context = new Ctx();
      const decoded = await context.decodeAudioData(await file.slice(0, 2_000_000).arrayBuffer());
      context.close();
      // A slice decodes to the length of the slice, not of the file, so this only ever
      // says "at least this long" - useful for the minimum, useless for the maximum.
      return decoded.duration >= (limits?.min_duration_s ?? 0) ? null : decoded.duration;
    } catch {
      return null;
    }
  }

  function clock(seconds) {
    const whole = Math.round(seconds);
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
  }

  /** What is wrong with this file, said in one sentence, or null. */
  async function complain(file) {
    if (!limits) return null;

    const mb = file.size / 1024 / 1024;
    if (limits.max_upload_mb && mb > limits.max_upload_mb) {
      return (
        `That file is ${mb.toFixed(0)} MB and the limit is ${limits.max_upload_mb} MB. ` +
        `Nothing has been uploaded.`
      );
    }

    const seconds = await duration(file);
    if (seconds === null) return null;
    if (limits.max_duration_s && seconds > limits.max_duration_s) {
      return (
        `That is ${clock(seconds)} long and the limit is ${clock(limits.max_duration_s)}. ` +
        `Nothing has been uploaded — trim it, or use a section.`
      );
    }
    if (limits.min_duration_s && seconds < limits.min_duration_s) {
      return (
        `That is only ${clock(seconds)}. Separation needs at least ` +
        `${Math.round(limits.min_duration_s)} seconds to have anything to work with.`
      );
    }
    return null;
  }

  /**
   * Wire one dropzone.
   *
   * `dragover` must call `preventDefault` or the browser navigates to the file and the
   * page is simply gone - the single most common way a drop target does nothing useful.
   * `dragleave` fires when the pointer crosses onto a *child* element too, so the counter
   * exists to stop the highlight flickering as the cursor moves over the text inside.
   */
  function wire(id, onFile) {
    const zone = $(id);
    if (!zone || zone.dataset.dropWired) return;
    zone.dataset.dropWired = "yes";
    let depth = 0;

    const stop = (event) => {
      event.preventDefault();
      event.stopPropagation();
    };

    zone.addEventListener("dragenter", (event) => {
      stop(event);
      depth += 1;
      zone.classList.add("over");
    });
    zone.addEventListener("dragover", stop);
    zone.addEventListener("dragleave", (event) => {
      stop(event);
      depth = Math.max(0, depth - 1);
      if (!depth) zone.classList.remove("over");
    });
    zone.addEventListener("drop", async (event) => {
      stop(event);
      depth = 0;
      zone.classList.remove("over");

      const file = event.dataTransfer?.files?.[0];
      if (!file) return;

      const wrong = await complain(file);
      if (wrong) {
        const box = $("upload-error");
        if (box) {
          box.textContent = wrong;
          box.hidden = false;
        }
        return;
      }
      onFile(file);
    });
  }

  /**
   * Upload with a progress bar that means something. X0R-203's third criterion.
   *
   * `fetch` cannot report upload progress - there is no hook for bytes sent, only for
   * bytes received - so this is the one place in the application that still wants
   * `XMLHttpRequest`. A 60 MB song on a domestic upstream is a minute of a bar that has
   * been sitting at "5%" for the whole of it, and a bar that does not move is the thing
   * users read as a hang.
   */
  function upload(path, form, onProgress) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", API + path);
      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      });
      request.addEventListener("load", () => {
        let body = null;
        try {
          body = JSON.parse(request.responseText);
        } catch {
          body = null;
        }
        if (request.status >= 200 && request.status < 300) {
          resolve(body);
        } else {
          reject(new Error(body?.detail || `${request.status} ${request.statusText}`));
        }
      });
      request.addEventListener("error", () =>
        reject(new Error("The upload did not reach the server.")),
      );
      request.addEventListener("abort", () => reject(new Error("Upload cancelled.")));
      request.send(form);
    });
  }

  async function init() {
    try {
      limits = (await api("/capabilities")).limits || null;
    } catch {
      limits = null;
    }
    // All three: the song and the reference on the first screen, and the reference on the
    // master page for somebody who got that far without one.
    wire("dropzone", (file) => pickFile(file));
    wire("upfront-ref-dropzone", (file) => pickUpfrontReference(file));
    wire("ref-dropzone", (file) => pickReference(file));
  }

  return { init, complain, duration, upload };
})();

document.addEventListener("DOMContentLoaded", () => Dropzone.init());
