// ──────────────────────────── getting between the sections ────────────────────────────
//
// X0R-1417, from Ryan: *"Add a fixed header to the top that takes you directly to each
// section."*
//
// Scoped with X0R-1407 on 2026-10-07, which is what settled the shape of it. The two cards
// looked like one problem and measured as two:
//
//   * the *comparison* is not dense. On a real pair it is 31 rows and **848 px collapsed**,
//     under one screen. The 66-row figure that prompted X0R-1407 was a ceiling nobody sees.
//   * the *page* is long. After a full run, with every disclosure already closed, it is
//     **4 247 px across seven sections** - nearly five screens in its tidiest possible
//     state. Collapsing cannot help, because it is already collapsed.
//
// So this is the card that measured real, and it is about getting *between* sections rather
// than about anything inside one.
//
// **The per-section collapse Ryan also asked for is deliberately not here.** Six of the
// seven sections are already a single card or already collapsible from inside, and bolting
// a second collapse mechanism on top is how a screen ends up with two navigation systems
// that disagree. The nav goes first; collapse follows only if the nav turns out not to be
// enough.

const Sections = (() => {
  //: Every place worth jumping to, in the order they appear. A section absent from the
  //: page - or hidden, which is most of them before a run - simply does not get an entry.
  //: Otto is absent on purpose: it is a fixed shelf in the corner rather than a section of
  //: the page, so "jump to it" is meaningless and a nav entry that scrolls nowhere is worse
  //: than no entry.
  //:
  //: pr0ducer's own sections are listed too. The bar is built from whichever of these is
  //: actually on screen, and the two pages never show each other's, so one list serves
  //: both rather than each page needing its own copy.
  //:
  //: Sprint 25: the remix card's own stages. Measured on the demo after a version was made,
  //: `#revoice` alone is **4 868 px - nearly seven screens** - and until now the bar stopped
  //: at "Drum by drum", three entries before any of it. Everything built from Sprint 3 on
  //: lives inside that one card, in the order a remix is actually made, so the bar follows
  //: that order: describe it, set the tempo, choose the sounds, edit the notes, add the
  //: beat, arrange it, chop it, make it, mix it, finish it.
  const PLACES = [
    ["step-stems", "Stems"],
    ["step-master", "Reference"],
    ["mix-compare", "Your mix vs theirs"],
    ["instrument-compare", "Instrument by instrument"],
    ["group-export", "Export"],
    ["groove", "What each plays"],
    ["produce-drums", "Drum by drum"],
    ["preset-box", "Describe it"],
    ["tempo-box", "Tempo"],
    ["revoice-parts", "Parts"],
    ["notes-editor", "Notes"],
    ["arrange-box", "Arrangement"],
    ["chops-box", "Chops"],
    ["bounce-box", "Make the version"],
    ["mixer", "Mix"],
    ["finish-box", "Finish"],
  ];

  //: How far above a section to land, so its heading is not under the sticky bar itself.
  //: Only the scroll-spy uses this number; the landing offset is `scroll-margin-top` in
  //: the stylesheet, for the reason on `go`.
  const HEADROOM = 76;

  let spying = false;
  //: Sprint 25: what actually drives the highlight - see `watch`.
  let watcher = null;

  function visible(id) {
    const el = document.getElementById(id);
    if (!el || el.hidden) return null;
    // A section inside a hidden parent is just as unreachable as a hidden one.
    return el.offsetParent === null && el.getBoundingClientRect().height === 0 ? null : el;
  }

  function render() {
    const bar = $("section-nav");
    if (!bar) return;

    const here = PLACES.filter(([id]) => visible(id));
    // One destination is not navigation. Before a run there is only the upload, and a bar
    // with a single button in it is furniture.
    if (here.length < 2) {
      bar.hidden = true;
      return;
    }

    const wanted = here.map(([id]) => id).join(",");
    if (bar.dataset.places !== wanted) {
      bar.dataset.places = wanted;
      bar.innerHTML = "";
      for (const [id, label] of here) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "section-link";
        button.dataset.target = id;
        button.textContent = label;
        button.addEventListener("click", () => go(id));
        bar.appendChild(button);
      }
    }
    bar.hidden = false;
    watch(here.map(([id]) => id));
    spy();
  }

  /**
   * Keep the highlight honest when the page moves without a scroll event.

   * A scroll listener only hears about scrolling. It does not hear a section opening above
   * you, the mixer appearing when a version is made, or the piano roll closing - all of
   * which move everything below them and change which section you are actually looking at.
   * An `IntersectionObserver` is driven by layout, so it covers those too, and it is
   * cheaper than a handler that runs on every scroll frame.
   *
   * The root margin leaves a one-pixel line just under the bar: whenever a section crosses
   * it, the answer could have changed, which is exactly when `spy` should run. The scroll
   * listener stays as well, because the two cost nothing together and either one alone has
   * a gap.
   *
   * Neither fires in a browser pane that is not rendering - measured here, where scrolling
   * moved the page, `scrollY` changed and the section landed on its `scroll-margin-top`
   * exactly, while no callback of either kind arrived until the pane drew a frame. Nothing
   * can be done about that from this side, and nothing needs to be: a page nobody is
   * looking at has no highlight to get wrong.
   */
  function watch(ids) {
    if (watcher) watcher.disconnect();
    if (typeof IntersectionObserver === "undefined") return;
    watcher = new IntersectionObserver(() => spy(), {
      rootMargin: `-${HEADROOM}px 0px -${Math.max(0, window.innerHeight - HEADROOM - 1)}px 0px`,
      threshold: 0,
    });
    for (const id of ids) {
      const el = visible(id);
      if (el) watcher.observe(el);
    }
  }

  /**
   * Go to one section.
   *
   * `scrollIntoView` rather than `window.scrollTo`, and the offset comes from
   * `scroll-margin-top` in the stylesheet rather than from arithmetic here. Both of those
   * are because the first version used `window.scrollTo({top, behavior: "smooth"})` and
   * **it silently did nothing** - measured in this project's own browser pane, where
   * `scrollTo(0, 500)` moves and the same call with `behavior: "smooth"` leaves `scrollY`
   * exactly where it was. That is the second time an environment-dependent scrolling API
   * has failed quietly here; `requestAnimationFrame` not running in a backgrounded tab was
   * the first, in X0R-1411. `scrollIntoView` works in both cases and the rest of this
   * codebase already relies on it.
   */
  function go(id) {
    const el = visible(id);
    if (!el) return;
    // A details that happens to be the destination should open rather than be scrolled to
    // while shut, which is the one case where "take me there" would otherwise do nothing
    // visible. Export is the only such section today.
    if (el.tagName === "DETAILS") el.open = true;
    el.scrollIntoView({ block: "start" });
  }

  /**
   * Light the entry for whatever is on screen.
   *
   * The last section whose heading has reached the bar. The first version of this used
   * "the last one above the middle of the viewport", which sounds more forgiving and is
   * wrong: jumping to a short section lit the one *after* it, because that one's heading
   * was also above the midpoint. Landing on a section and seeing its neighbour light up
   * is worse than no highlight at all.
   */
  function spy() {
    const bar = $("section-nav");
    if (!bar || bar.hidden) return;
    // A few pixels of slack, because a jump lands on `scroll-margin-top` exactly and
    // sub-pixel layout should not decide whether the thing you jumped to counts.
    const reached = HEADROOM + 8;

    let current = null;
    let first = null;
    for (const [id] of PLACES) {
      const el = visible(id);
      if (!el) continue;
      if (first === null) first = id;
      if (el.getBoundingClientRect().top <= reached) current = id;
    }
    // At the very top of the page no section has reached the middle yet, and an
    // unlit bar reads as broken rather than as "nowhere in particular".
    if (current === null) current = first;
    for (const link of bar.querySelectorAll(".section-link")) {
      const on = link.dataset.target === current;
      link.classList.toggle("on", on);
      link.setAttribute("aria-current", on ? "true" : "false");
    }
  }

  function init() {
    if (spying) return;
    spying = true;
    // Passive: this only reads geometry, and a scroll handler that can block scrolling is
    // a worse problem than the one it solves.
    window.addEventListener("scroll", spy, { passive: true });
    window.addEventListener("resize", render, { passive: true });
  }

  return { init, render, go };
})();

document.addEventListener("DOMContentLoaded", () => Sections.init());
