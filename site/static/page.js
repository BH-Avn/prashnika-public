// Server-rendered pages (site/pages.py): the body already has real HTML, with $...$ maths left as literal text.
// This walks the text nodes once KaTeX has loaded and swaps each $...$ span for its rendered form, the same as
// rich-text.js does for the SPA. Runs on every [data-maths] container; hub and question pages reuse it.
"use strict";

(function () {
  function upgrade(root, skipCards) {
    if (!window.katex) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) {
      if (n.nodeValue.indexOf("$") === -1) continue;
      if (n.parentElement && n.parentElement.closest("pre, code")) continue;
      if (skipCards && n.parentElement && n.parentElement.closest(LAZY)) continue;
      nodes.push(n);
    }
    nodes.forEach((node) => {
      const parts = node.nodeValue.split(/(\$[^$]+\$)/g);
      if (parts.length < 2) return;
      const frag = document.createDocumentFragment();
      parts.forEach((part) => {
        if (part.length > 1 && part.startsWith("$") && part.endsWith("$")) {
          const span = document.createElement("span");
          try {
            span.innerHTML = window.katex.renderToString(part.slice(1, -1), { throwOnError: false });
          } catch (e) {
            span.textContent = part;
          }
          frag.appendChild(span);
        } else if (part) {
          frag.appendChild(document.createTextNode(part));
        }
      });
      node.parentNode.replaceChild(frag, node);
    });
  }


  // A paper's or chapter's page holds many question cards and links with many formulas: drawing them all at once
  // makes the page lag, so each card, and each link in a list of questions, has its maths drawn only when it comes
  // near the screen.
  const LAZY = ".qfull, .related li";

  function run() {
    const cards = document.querySelectorAll(LAZY);
    if (cards.length && "IntersectionObserver" in window) {
      const seen = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting) return;
          seen.unobserve(e.target);
          upgrade(e.target);
        });
      }, { rootMargin: "800px 0px" });
      cards.forEach((c) => seen.observe(c));
      // what sits outside the cards (an intro, a heading) is drawn straight away
      document.querySelectorAll("[data-maths]").forEach((root) => upgrade(root, true));
      return;
    }
    document.querySelectorAll("[data-maths]").forEach((root) => upgrade(root));
  }

  // "‹ Back": when the visitor came here from another page of this site, it goes back to exactly that page (the
  // list with its filters, the paper, the note); opened from Google or a shared link, it goes to the fallback the
  // server wrote into its href. After Previous / Next the referrer is only the question just left, so what the first
  // question page knew is carried over in sessionStorage (see wireStepper).
  const STEP_KEY = "stepFromHere";
  let fromHere = false;

  function cameFromHere() {
    try {
      const carried = sessionStorage.getItem(STEP_KEY);
      if (carried) {
        sessionStorage.removeItem(STEP_KEY);
        const [path, value] = JSON.parse(carried);
        if (path === location.pathname) return value;
      }
    } catch (e) {}
    try { return !!document.referrer && new URL(document.referrer).origin === location.origin &&
      document.referrer !== location.href && history.length > 1; } catch (e) { return false; }
  }

  function wireBack() {
    fromHere = cameFromHere();
    const link = document.querySelector("[data-back]");
    if (!link || !fromHere) return;
    link.querySelector("span").textContent = "Back";
    link.addEventListener("click", (e) => {
      if (e.ctrlKey || e.metaKey || e.shiftKey) return;
      e.preventDefault();
      history.back();
    });
  }

  // "‹ Previous / Next ›" swap this page for the neighbour instead of adding a history entry, so Back (ours or the
  // browser's) after any number of steps goes to where the visitor was before the first question, not the last one.
  function wireStepper() {
    document.querySelectorAll(".stepper a[rel]").forEach((a) => {
      a.addEventListener("click", (e) => {
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        const target = new URL(a.href, location.href);
        try { sessionStorage.setItem(STEP_KEY, JSON.stringify([target.pathname, fromHere])); } catch (e2) {}
        location.replace(target.href);
      });
    });
  }

  // A search box on /papers, /chapters or a chapter's page (hubs._search_box): as you type, items whose text doesn't
  // hold every typed word (as words.js reads them: short names, misspellings) are hidden, and so is a group (a
  // subject, "More questions") left with nothing. Each item's text is read once and kept, so typing stays quick.
  function wireFilter() {
    document.querySelectorAll("input[data-filter]").forEach((box) => {
      const items = [...document.querySelectorAll(box.dataset.filter)];
      const groups = [...document.querySelectorAll("[data-filter-group]")];
      const none = box.form && box.form.nextElementSibling && box.form.nextElementSibling.matches("[data-filter-none]")
        ? box.form.nextElementSibling : null;
      const { norm, has } = window.PrashnikaWords;
      let texts = null;
      let timer = 0;
      const apply = () => {
        texts = texts || items.map((el) => norm(el.textContent));
        const words = norm(box.value).trim().split(" ").filter(Boolean);
        // a word found nowhere as typed is read as a misspelling ("phiyscs"); one found somewhere is taken as typed
        const fuzzy = words.map((w) => !texts.some((t) => has(t, w)));
        let shown = 0;
        items.forEach((el, i) => {
          const ok = words.every((w, k) => has(texts[i], w, fuzzy[k]));
          el.hidden = !ok;
          if (ok) shown++;
        });
        groups.forEach((g) => { g.hidden = !!words.length && !items.some((el) => !el.hidden && g.contains(el)); });
        if (none) none.hidden = shown > 0;
      };
      box.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(apply, 120); });
      if (box.form && box.form.hasAttribute("data-filter-form")) {
        box.form.addEventListener("submit", (e) => { e.preventDefault(); apply(); });
      }
    });
  }

  // The kind-of-paper chips on /papers: a tile is shown when its kind is the chosen one; a card with none left hides.
  function wireKinds() {
    const chips = [...document.querySelectorAll("[data-kind-chip]")];
    if (!chips.length) return;
    chips.forEach((chip) => chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.toggle("on", c === chip));
      const kind = chip.dataset.kindChip;
      document.querySelectorAll(".paper-index li[data-kind]").forEach((li) => li.classList.toggle("kind-off", !!kind && li.dataset.kind !== kind));
      document.querySelectorAll(".chcard.paper-index").forEach((card) => card.classList.toggle("kind-off", !card.querySelector("li:not(.kind-off)")));
    }));
  }

  // The subject chips on /isc and /chapters: All, or one subject's group ([data-subj]) alone.
  function wireSubjects() {
    const chips = [...document.querySelectorAll("[data-subj-chip]")];
    chips.forEach((chip) => chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.toggle("on", c === chip));
      const want = chip.dataset.subjChip;
      document.querySelectorAll("[data-subj]").forEach((g) => { g.classList.toggle("kind-off", !!want && g.dataset.subj !== want); });
    }));
  }

  function wire() {
    wireFilter();
    wireKinds();
    wireSubjects();
    wireBack();
    wireStepper();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
