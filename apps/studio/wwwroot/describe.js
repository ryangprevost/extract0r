// Describe it: a remix in words. Sprint 21.
//
// Ryan, 2026-10-14: "I guess I'm looking for something generative like Suno that takes
// prompts and uses a reference track" - "keep it free for now but allow architecture to
// easily switch to the API as needed."
//
// The server reads the words into a recipe of this page's own controls (with the free,
// offline vocabulary unless it has been switched to Claude). The plan is shown first - what
// each phrase set, and which words were not used - and "Make it" then sets those controls
// and makes the version the ordinary way, so everything it chose is somewhere to see and
// change afterwards.

const Describe = (() => {
  let reading = null;

  function list(items) {
    const ul = document.createElement("ul");
    ul.className = "recipe-lines small";
    for (const text of items) {
      const li = document.createElement("li");
      li.textContent = text;
      ul.appendChild(li);
    }
    return ul;
  }

  async function read() {
    const prompt = $("describe-prompt").value.trim();
    const plan = $("describe-plan");
    plan.innerHTML = "";
    $("describe-make").hidden = true;
    if (!prompt) return;
    try {
      reading = await api("/tracks/describe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, track_id: state.trackId || null }),
      });
    } catch (error) {
      plan.textContent = error.message || String(error);
      return;
    }
    const head = document.createElement("p");
    head.className = "small";
    head.textContent = reading.understood.length
      ? "Here is what that sets:" : "None of those words set anything.";
    plan.appendChild(head);
    if (reading.understood.length) plan.appendChild(list(reading.understood));
    if (reading.unused.length) {
      const unused = document.createElement("p");
      unused.className = "muted small";
      unused.textContent = `Not used: ${reading.unused.join(", ")}. ` +
        "Try words like complextro, gritty, wide, punchy, stabs, chops, lead over clean " +
        "chords, no verses, a quiet bridge, levels like the reference.";
      plan.appendChild(unused);
    }
    const by = document.createElement("p");
    by.className = "muted tiny";
    by.textContent = reading.reader === "claude"
      ? "Read by Claude." : "Read by the built-in vocabulary - free, and offline.";
    plan.appendChild(by);
    $("describe-make").hidden = !reading.understood.length || !state.trackId;
  }

  async function make() {
    if (!reading || typeof Revoice === "undefined") return;
    const button = $("describe-make");
    const said = $("describe-said");
    button.disabled = true;
    try {
      await Revoice.applyRecipe(reading.recipe, (text) => { said.textContent = text; });
      said.textContent = "Done. Every choice is in the controls below - change any of them " +
        "and make the version again, or describe the next change.";
    } catch (error) {
      said.textContent = error.message || String(error);
    } finally {
      button.disabled = false;
    }
  }

  function init() {
    if (!$("describe-read") || $("describe-read").dataset.wired) return;
    $("describe-read").dataset.wired = "yes";
    $("describe-read").addEventListener("click", read);
    $("describe-make").addEventListener("click", make);
    $("describe-prompt").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) read();
    });
  }

  return { init };
})();

document.addEventListener("DOMContentLoaded", () => Describe.init());
