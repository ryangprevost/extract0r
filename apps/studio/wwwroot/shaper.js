// Shaping the sounds. Sprint 8.
//
// Ryan: "go ahead with shaping the sounds next". Pick any built-in synth voice or kit, turn
// knobs named for what they do - brighter, longer, snappier, an octave lower - and hear the
// result as you go: the preview is rendered by the same engine that plays your parts, so the
// sound you keep is the sound you heard. Keep it under a name and it joins every voice or kit
// list on the page.

const Shaper = (() => {
  let info = null;            // knobs, bases and your sounds, from /tracks/sounds
  let kind = "voice";
  let base = "";
  let knobs = {};
  let timer = null;
  let audio = null;
  let lastUrl = null;

  function knobRow(label, about, value, onInput) {
    const row = document.createElement("label");
    row.className = "shape-knob";
    const name = document.createElement("span");
    name.className = "shape-name";
    name.textContent = label;
    const input = document.createElement("input");
    input.type = "range";
    input.min = -1;
    input.max = 1;
    input.step = 0.05;
    input.value = value;
    input.setAttribute("aria-label", `${label}: ${about}`);
    const words = document.createElement("span");
    words.className = "muted tiny";
    words.textContent = about;
    input.addEventListener("input", () => onInput(parseFloat(input.value)));
    input.addEventListener("dblclick", () => {
      input.value = 0;
      onInput(0);
    });
    row.append(name, input, words);
    return row;
  }

  function draw() {
    const host = $("shape-knobs");
    if (!host || !info) return;
    host.innerHTML = "";
    if (kind === "voice") {
      for (const [knob, about] of Object.entries(info.voice_knobs)) {
        host.appendChild(knobRow(knob, about, knobs[knob] || 0, (v) => {
          knobs[knob] = v;
          later();
        }));
      }
    } else {
      for (const drum of info.drums) {
        const head = document.createElement("h5");
        head.className = "shape-drum";
        head.textContent = drum === "hihat" ? "Hats" : drum[0].toUpperCase() + drum.slice(1);
        host.appendChild(head);
        knobs[drum] = knobs[drum] || {};
        for (const [knob, about] of Object.entries(info.drum_knobs)) {
          host.appendChild(knobRow(knob, about, knobs[drum][knob] || 0, (v) => {
            knobs[drum][knob] = v;
            later();
          }));
        }
      }
    }
  }

  function fillBases() {
    const pick = $("shape-base");
    pick.innerHTML = "";
    for (const name of kind === "voice" ? info.voices : info.kits) {
      pick.appendChild(new Option(kind === "kit" ? `${name} kit` : name, name));
    }
    base = pick.value;
  }

  function drawYours() {
    const host = $("shape-yours");
    host.innerHTML = "";
    for (const sound of info.yours || []) {
      const row = document.createElement("div");
      row.className = "shape-yours-row";
      const name = document.createElement("strong");
      name.textContent = sound.name;
      const about = document.createElement("span");
      about.className = "muted small";
      about.textContent = sound.about;
      const remove = document.createElement("button");
      remove.className = "small";
      remove.type = "button";
      remove.textContent = "Delete";
      remove.addEventListener("click", async () => {
        await api(`/tracks/sounds/${encodeURIComponent(sound.name)}`, { method: "DELETE" });
        await load();
        refreshLists();
      });
      row.append(name, about, remove);
      host.appendChild(row);
    }
    $("shape-yours-head").hidden = !(info.yours || []).length;
  }

  /** Re-render the preview once the knob has stopped moving for a moment. */
  function later() {
    clearTimeout(timer);
    timer = setTimeout(preview, 300);
  }

  async function preview() {
    const said = $("shape-said");
    try {
      const response = await fetch(`${API}/tracks/sounds/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, base, knobs }),
      });
      if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
      const blob = await response.blob();
      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = URL.createObjectURL(blob);
      if (audio) audio.pause();
      audio = new Audio(lastUrl);
      await audio.play().catch(() => {});   // a browser may wait for a click before sound
      said.textContent = "";
    } catch (error) {
      said.textContent = error.message || String(error);
    }
  }

  async function keep() {
    const said = $("shape-said");
    const name = $("shape-name").value.trim();
    try {
      const saved = await api("/tracks/sounds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, base, knobs, name }),
      });
      said.textContent = `Kept: "${saved.name}" - ${saved.about}. It is in every ` +
        `${kind === "voice" ? "voice" : "kit"} list now.`;
      await load();
      refreshLists();
    } catch (error) {
      said.textContent = error.message || String(error);
    }
  }

  /** The part rows and the kit lists learn about the new sound. */
  function refreshLists() {
    if (typeof Revoice !== "undefined" && Revoice.refreshSounds) Revoice.refreshSounds();
  }

  async function load() {
    try {
      info = await api("/tracks/sounds");
    } catch {
      return;
    }
    drawYours();
  }

  async function init() {
    const box = $("shaper-box");
    if (!box || box.dataset.wired) return;
    box.dataset.wired = "yes";
    await load();
    if (!info) return;
    $("shape-kind").addEventListener("change", (e) => {
      kind = e.target.value;
      knobs = {};
      fillBases();
      draw();
    });
    $("shape-base").addEventListener("change", (e) => {
      base = e.target.value;
      later();
    });
    $("shape-hear").addEventListener("click", preview);
    $("shape-reset").addEventListener("click", () => {
      knobs = {};
      draw();
      later();
    });
    $("shape-keep").addEventListener("click", keep);
    fillBases();
    draw();
  }

  return { init, load };
})();

document.addEventListener("DOMContentLoaded", () => Shaper.init());
