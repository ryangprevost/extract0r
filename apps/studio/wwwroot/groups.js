// Four decisions on the page, everything else behind a named door.
//
// The mastering page used to present nineteen controls in one flat grid. Every one of
// them was added for a reason and several carry three sentences of tooltip explaining the
// physics; the problem was never that any single control was wrong, it was that they
// arrived all at once with no statement of which four mattered. The most-repeated piece
// of feedback this project has had is that it keeps getting harder to use, and this is
// the card for it.
//
// Nothing was removed. The grouping is in `index.html`; this file is the behaviour that
// makes a collapsed group safe to collapse:
//
//   * a group whose contents you have changed says so on its header, so a setting can
//     never hide behind a closed door;
//   * which groups are open survives a reload, because a user who opens Tone every time
//     is telling you something.

const GROUP_STATE_KEY = "x0r.groups.open";

/** Defaults, captured once from the markup, before anything is restored or applied. */
const groupDefaults = new Map();

function captureGroupDefaults() {
  if (groupDefaults.size) return;
  for (const control of document.querySelectorAll(".control-group [id]")) {
    if (!isSettable(control)) continue;
    groupDefaults.set(control.id, currentValue(control));
  }
}

function isSettable(node) {
  return (
    (node.tagName === "INPUT" && ["range", "checkbox", "number"].includes(node.type)) ||
    node.tagName === "SELECT"
  );
}

function currentValue(node) {
  return node.type === "checkbox" ? String(node.checked) : String(node.value);
}

/**
 * Mark each group that holds something set away from its default.
 *
 * The honest version of hiding controls. A user who collapses Tone after adding 2 dB of
 * air has to be able to see, without opening it, that Tone is doing something — otherwise
 * the next export surprises them and the group is a trap rather than a tidy-up.
 */
function refreshGroupBadges() {
  captureGroupDefaults();

  for (const group of document.querySelectorAll(".control-group")) {
    const changed = [...group.querySelectorAll("[id]")]
      .filter(isSettable)
      .filter((node) => {
        const was = groupDefaults.get(node.id);
        return was !== undefined && currentValue(node) !== was;
      });

    const badge = group.querySelector(".group-changed");
    if (!badge) continue;
    badge.hidden = changed.length === 0;
    if (changed.length) {
      badge.textContent = `${changed.length} changed`;
      // Names them, so "2 changed" does not require opening the group to find out which.
      badge.title = changed
        .map((node) => {
          const label = node.closest("label");
          const name = label?.querySelector("span")?.textContent?.trim();
          return name || node.id;
        })
        .join(", ");
    }
  }
}

// --- which groups are open ---------------------------------------------------------------

function restoreOpenGroups() {
  let open = [];
  try {
    open = JSON.parse(localStorage.getItem(GROUP_STATE_KEY) || "[]");
  } catch {
    // A corrupt or unavailable store means the default layout, which is the whole point
    // of the card: everything closed. Never a reason to fail loading the page.
    open = [];
  }
  if (!Array.isArray(open)) open = [];
  for (const group of document.querySelectorAll(".control-group")) {
    group.open = open.includes(group.dataset.group);
  }
}

function rememberOpenGroups() {
  const open = [...document.querySelectorAll(".control-group[open]")].map(
    (g) => g.dataset.group,
  );
  try {
    localStorage.setItem(GROUP_STATE_KEY, JSON.stringify(open));
  } catch {
    // Private browsing, or storage disabled. The page works; it just forgets.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const groups = [...document.querySelectorAll(".control-group")];
  if (!groups.length) return;

  // Defaults are read from the markup, so they have to be taken before anything restores
  // a value or a preset writes one.
  captureGroupDefaults();
  restoreOpenGroups();

  for (const group of groups) {
    group.addEventListener("toggle", rememberOpenGroups);
  }

  // One listener on the container rather than one per control: the taste presets and the
  // "Start from" modes set values in bulk without the controls firing anything the
  // individual listeners would catch, and `input` bubbles.
  for (const event of ["input", "change"]) {
    document.addEventListener(event, (e) => {
      if (e.target instanceof Element && e.target.closest(".control-group")) {
        refreshGroupBadges();
      }
    });
  }

  refreshGroupBadges();
});
