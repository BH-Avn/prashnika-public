// Prashnika: how the site's search boxes read what people type. Shared by page.js (the boxes on /papers, /chapters,
// a chapter's page) and site.js (the question list, which also turns a subject's name into its filter).
// Plain JS, no build step.
(function () {
  "use strict";

  // Short names people type, and what they stand for on the site (subjects, paper kinds). ISC's subjects for now:
  // a new board's or subject's short names go here too.
  const SHORT = {
    math: ["mathematics"], maths: ["mathematics"], cs: ["computer science"], comp: ["computer science"],
    pe: ["physical education"], phy: ["physics"], chem: ["chemistry"], bio: ["biology"], eco: ["economics"],
    econ: ["economics"], lit: ["literature"], lang: ["language"], eng: ["english"], acc: ["accounts", "accountancy"],
    bst: ["business studies"], geo: ["geography"], hist: ["history"], pol: ["political science"],
    sample: ["specimen"], model: ["specimen"], compartment: ["improvement"], supplementary: ["improvement"],
    cfq: ["competency"], board: ["question paper"], pyq: ["question paper", "board paper"],
  };

  // Letters changed, added, dropped or swapped between two words (Damerau-Levenshtein), stopping early past `max`.
  function distance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev2 = null, prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let best = i;
      for (let j = 1; j <= b.length; j++) {
        let d = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d = Math.min(d, prev2[j - 2] + 1);
        cur.push(d);
        best = Math.min(best, d);
      }
      if (best > max) return max + 1;
      prev2 = prev;
      prev = cur;
    }
    return prev[b.length];
  }

  // Is `typed` a misspelling of `word`? Short words must be exact (too many near misses); 5-6 letters may be one
  // slip off, longer ones two ("phiyscs" is Physics).
  function nearly(typed, word) {
    if (typed.length < 5 || word.length < 5) return false;
    const max = typed.length >= 7 ? 2 : 1;
    return distance(typed, word, max) <= max;
  }

  // Lowercase words only, with a space at each end, so " " + w finds the start of a word.
  const norm = (s) => " " + s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() + " ";

  // Does the normalised `text` hold the typed word `w`? At the start of one of its words ("phy" finds Physics), as a
  // whole word without its plural "s" ("papers"), through a short name ("maths" finds Mathematics, "cs" Computer
  // Science), or misspelled (`fuzzy`, "phiyscs" finds Physics).
  function has(text, w, fuzzy) {
    if (text.includes(" " + w)
        || (w.length > 3 && w.endsWith("s") && text.includes(" " + w.slice(0, -1) + " "))
        || shortOf(w).some((long) => text.includes(" " + long))) return true;
    return !!fuzzy && w.length >= 5 && text.trim().split(" ").some((word) => nearly(w, word));
  }

  // SHORT is a plain object: SHORT["constructor"] is Object's own function, not a list
  function shortOf(k) { return Object.prototype.hasOwnProperty.call(SHORT, k) ? SHORT[k] : []; }
  window.PrashnikaWords = { SHORT, shortOf, norm, has, nearly };
})();
