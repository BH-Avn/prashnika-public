// Prashnika site. Plain JS, no build step. Everything the visitor chose (filters, search, sort, page, paper, the
// open question) lives in the web address, so any view can be shared or bookmarked.
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rt = (s, query) => (window.renderRichText ? window.renderRichText(s || "", query) : esc(s));

const HOME_TITLE = "Past Exam Questions | Prashnika";   // the same as index.html's <title>
const SORTS = [["year_desc", "Newest first"], ["year_asc", "Oldest first"], ["paper", "Paper order"]];
const OWN_PARAMS = ["view", "question", "as"];   // page state that isn't part of the question list's query
                                                 // (as=typed: the search as typed, no subject read out of it)
const SHOW_VALUES = 12;                        // values shown per filter before "show all"
const TYPE_LABEL = { mcq: "MCQ", assertion_reason: "Assertion-reason", true_false: "True/false", fill_blank: "Fill in", one_word: "One word",
  match: "Match", numerical: "Numerical", derivation: "Derivation", drawing: "Drawing", short: "Short answer",
  long: "Long answer", program: "Program", passage: "Case based", writing: "Writing",
  complete: "Complete", arrange: "Arrange", rewrite: "Rewrite", compare: "Differentiate", list: "State points",
  conversion: "Conversion", identify: "Identify", output: "Output", transformation: "Transformation",
  preposition: "Prepositions", verb_form: "Correct verbs", comprehension: "Comprehension", truth_table: "Truth table",
  kmap: "K-map", tree: "Binary tree", lpp: "Linear programming", distribution: "Probability distribution",
  regression: "Regression", reaction: "Reaction", graph: "Graph", complex_ion: "Coordination complex" };
const ICON = { search: "", filter: "", sort: "", x: "×" };

const state = { subjects: null, filters: [], filterKeys: [], list: null, listKey: null, open: null, expanded: {}, shown: 0, tagQuery: "",
  openSeq: 0 };

// A card's href is its canonical page (site/pages.py): /{board}/{subject}/{qid}/{slug}. Recognising that shape in
// the address bar is how the SPA knows a question is open after a client-side navigation (a card click, prev/next,
// or the back button) - the canonical URL is only ever server-rendered on a real page load, never reached by this
// script then.
const QUESTION_PATH_RE = /^\/[^/]+\/[^/]+\/(q-[a-z0-9]+)(?:\/[^/]*)?\/?$/;

function pathQid() {
  const m = QUESTION_PATH_RE.exec(location.pathname);
  return m ? m[1] : null;
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { return null; }
}

// Replies are kept for the visit, so going back, closing a question or stepping to one fetched ahead is instant
// instead of another trip to the server. The data only changes when a paper is published; a reload picks that up.
const cache = new Map();
const CACHE_MAX = 80;

function getJSON(path) {
  if (cache.has(path)) return cache.get(path);
  const got = fetch(path, { headers: { Accept: "application/json" } }).then((r) => {
    if (!r.ok) throw new Error(r.status === 404 ? "Not found" : `The server answered ${r.status}`);
    return r.json();
  });
  cache.set(path, got);
  got.catch(() => cache.delete(path));              // a failure is tried again next time
  if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value);
  return got;
}

// ---------------------------------------------------------------- the address

const params = () => new URLSearchParams(location.search);

// Phones get 10 questions a page, other screens 20. A page number in the address counts pages of `per` (20 when
// it's absent), so a link shared from a phone and opened on a laptop (or the other way) is mapped by position and
// lands on the page holding the same first question.
const PHONE = "(max-width: 699px)";
const pageSize = () => (matchMedia(PHONE).matches ? 10 : 20);

function fitPage(p) {
  const size = pageSize(), per = p.get("per") === "10" ? 10 : 20, page = parseInt(p.get("page"), 10);
  const before = p.toString();
  if (page > 1 && per !== size) {
    const moved = Math.floor(((page - 1) * per) / size) + 1;
    if (moved > 1) p.set("page", moved); else p.delete("page");
  }
  if (size === 10 && p.has("page")) p.set("per", "10"); else p.delete("per");
  return p.toString() !== before;
}

function listQuery(p = params()) {
  const q = new URLSearchParams(p);
  OWN_PARAMS.forEach((k) => q.delete(k));
  return q;
}

// Filters, search, sort, page and the tab all live at "/" (only a question has its own path), so go() always
// navigates there - opening a question is a separate, narrower operation: see openQuestion().
function go(p, replace) {
  const s = p.toString();
  const url = s ? `/?${s}` : "/?view=questions";   // a bare "/" is the landing page, not the list
  history[replace ? "replaceState" : "pushState"](null, "", url);
  render();
}

function change(fn, keepPage) {
  const p = params();
  fn(p);
  if (!keepPage) { p.delete("page"); p.delete("per"); }
  go(p);
}

function chosenCount() {
  const p = params();
  return state.filterKeys.reduce((n, k) => n + p.getAll(k).length, 0);
}

// ---------------------------------------------------------------- little pieces

function first(tags, key) { return (tags?.[key] || [])[0] || ""; }

function marksText(tags, short) {
  const m = first(tags, "marks");
  if (!m) return "";
  return short ? `${m} mk${m === "1" ? "" : "s"}` : `${m} mark${m === "1" ? "" : "s"}`;
}

function whereLine(q) {
  return [first(q.tags, "year"), TYPE_LABEL[q.type] || q.type, (q.tags.chapter || [])[0]]
    .filter(Boolean).join(" · ");
}

function questionHeading(q) {
  // "Q1(A)(i)" only means something while a paper is open; in a mixed list it is noise
  const sid = params().get("paper");
  const paper = sid ? q.papers?.find((x) => x.set_id === sid) : null;
  return [first(q.tags, "subject"), first(q.tags, "year"), paper?.printed_number ? `Q${paper.printed_number}` : ""]
    .filter(Boolean).join(" · ") || "Question";
}

// The tab's title starts with the question's opening words, so a tab says which question it is ("Physics · 2027"
// alone did not; 2026-10-09). Maths markers and Markdown are dropped, not drawn.
function titleWords(q) {
  const t = (q.content.text || plainText(q.content)).replace(/\$|\\[a-zA-Z]+|[{}*_#`]/g, " ").replace(/\s+/g, " ").trim();
  return t ? `${t.length > 60 ? `${t.slice(0, 57).replace(/\s+\S*$/, "")}…` : t} · ` : "";
}

function plainText(c) {
  return [c.passage, c.assertion, c.text, ...(c.parts || []).map((p) => p.text)].filter(Boolean).join("\n");
}

// ---------------------------------------------------------------- views

// Light up Home, Questions or Papers in the header (the hub pages are server-rendered and light their own).
function markNav() {
  const p = params();
  const home = location.search === "";               // the bare address is the landing page (server-written #home-about)
  const about = document.getElementById("home-about");
  if (about) about.hidden = !home;
  $("#main").hidden = home;                          // the list's own container: drawn only once someone leaves the landing page
  document.body.classList.toggle("soft", home);      // the landing page has the quieter contrast
  document.documentElement.classList.toggle("is-home", home);   // the menu's subject list shows on the landing page only
  document.documentElement.classList.toggle("is-list", !home);   // the list has its own search box: no top bar
  const on = home ? "home" : p.get("view") === "papers" || p.get("paper") ? "papers" : "questions";
  document.querySelectorAll(".topnav [data-nav], .tabbar [data-nav]").forEach((a) => {
    a.classList.toggle("on", a.dataset.nav === on);
    if (a.dataset.nav === on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

const OPENED_HOME = location.search === "";      // was this page opened at "/" (with the home text)?

async function render() {
  const p = params();
  const shown = ++state.shown;                   // replies for an older address are dropped
  const view = p.get("view") === "papers" ? "papers" : "questions";
  markNav();
  if (location.search === "") {                  // the landing page needs no data
    // its text is server-written only when the page was opened at "/": reached from the list (Home link, Back), load it
    if (!OPENED_HOME) { location.reload(); return; }
    document.title = HOME_TITLE; closeDialog(true); return;
  }
  if (view === "papers") await showPapers();
  else await showQuestions();
  if (shown !== state.shown) return;
  const qid = pathQid();
  if (qid) openQuestion(qid); else closeDialog(true);
}

async function showPapers() {
  const main = $("#main");
  const shown = state.shown;
  let data;
  try { data = await getJSON("/api/papers"); } catch (e) { main.innerHTML = errorBox(e); return; }
  if (shown !== state.shown) return;
  document.title = "Question Papers | Prashnika";
  if (!data.papers.length) {
    main.innerHTML = emptyBox("No papers yet", "Papers will be listed here as they are added and checked.");
    return;
  }
  main.innerHTML = `<div class="paper-head"><h1>Papers</h1></div><div class="papers">${data.papers.map((pp) => `
    <a class="paper-link" href="${pp.url || `/?paper=${encodeURIComponent(pp.set_id)}`}"><b>${esc(pp.title)}</b>
      <span class="muted">${pp.questions} question${pp.questions === 1 ? "" : "s"}</span></a>`).join("")}</div>`;
}

// Every subject's name, for reading one out of a search. Asked once, without filters: a filtered reply leaves out
// the subjects with nothing matching.
async function subjectNames() {
  if (!state.subjects) {
    const f = (await getJSON("/api/filters")).filters.find((x) => x.key === "subject");
    state.subjects = f ? f.values.map((v) => v.value) : [];
  }
  return state.subjects;
}

// The subjects named in a search, and the rest of it: "maths integration" is Mathematics and "integration". A name
// counts when each of its words is typed, as itself, a short name ("eng lit") or a misspelling ("phiyscs"); a whole
// short name counts too ("cs", "pe"). A word that is itself part of some subject's name is never read as a
// misspelling of another ("physical" is not Physics). Short names and misspellings: words.js.
function subjectsInSearch(text, names) {
  const W = window.PrashnikaWords;
  const words = (s) => W.norm(s).trim().split(" ").filter(Boolean);
  const tokens = text.trim().split(/\s+/);
  const keys = tokens.map((t) => W.norm(t).trim());
  const nameWords = new Set(names.flatMap(words));
  const used = new Set();
  const found = [];
  for (const name of names) {
    const parts = words(name);
    const whole = keys.findIndex((k, i) => !used.has(i) && W.shortOf(k).includes(parts.join(" ")));
    const take = whole >= 0 ? [whole] : parts.map((part) => keys.findIndex((k, i) => !used.has(i) && (k === part
      || W.shortOf(k).includes(part) || (!nameWords.has(k) && W.nearly(k, part)))));
    if (!take.length || take.some((i) => i < 0) || new Set(take).size < take.length) continue;
    take.forEach((i) => used.add(i));
    found.push(name);
  }
  return { found, rest: tokens.filter((_, i) => !used.has(i)).join(" ") };
}

async function showQuestions() {
  const p = params();
  if (p.get("q") && p.get("as") !== "typed") {      // a subject's name in the search becomes its filter
    const shown = state.shown;
    let names = [];
    try { names = await subjectNames(); } catch (e) { /* the search still works as typed */ }
    if (shown !== state.shown) return;
    const typed = p.get("q");
    const { found, rest } = subjectsInSearch(typed, names);
    if (found.length) {
      const before = new URLSearchParams(p);
      found.forEach((n) => { if (!p.getAll("subject").includes(n)) p.append("subject", n); });
      if (rest) p.set("q", rest); else p.delete("q");
      history.replaceState(history.state, "", `/?${p}`);
      // "kinetic energy ke pe" read "pe" as Physical Education and found nothing (2026-10-09): if this finds
      // nothing, the empty list offers the search as typed (as=typed), in every subject
      before.set("as", "typed");
      state.asTyped = { from: location.search, typed, url: `/?${before}` };
    }
  }
  if (fitPage(p)) history.replaceState(history.state, "", `/?${p}`);
  const query = listQuery(p);
  if (pageSize() === 10) query.set("per", "10");
  const main = $("#main");
  if (!$(".layout", main)) {
    main.innerHTML = `<div class="layout">
      <aside class="side" id="side"></aside>
      <div class="tools">
        <label class="search">${ICON.search}
          <input type="search" id="search" placeholder="Search questions" aria-label="Search questions" enterkeyhint="search">
        </label>
        <button class="btn" id="open-filters" type="button">${ICON.filter}Filters<span class="count" id="filter-count" hidden></span></button>
      </div>
      <div class="subjects" id="subjects"></div>
      <div class="summary" id="summary"></div>
      <div id="paper-head"></div><div id="results"></div>
    </div>`;
    wireTools();
  }
  if (document.activeElement !== $("#search")) $("#search").value = p.get("q") || "";
  const key = query.toString();
  if (state.listKey === key && $("#results .cards, #results .empty")) {   // this list is already on screen
    document.title = HOME_TITLE;
    $("#results").classList.remove("busy");         // a newer click may have dimmed it, then been undone by Back
    return;
  }

  const shown = state.shown;
  const results = $("#results");
  results.classList.add("busy");                    // dim the old list at once, so a click visibly did something
  let filters, list;
  try {
    // the filter counts don't depend on the page or the sort, so leave those out and paging reuses the cached reply
    const filterQuery = new URLSearchParams(query);
    filterQuery.delete("page");
    filterQuery.delete("per");
    filterQuery.delete("sort");
    [filters, list] = await Promise.all([getJSON(`/api/filters?${filterQuery}`), getJSON(`/api/questions?${query}`)]);
  } catch (e) { results.classList.remove("busy"); results.innerHTML = errorBox(e); state.listKey = null; return; }
  if (shown !== state.shown) return;
  results.classList.remove("busy");
  state.listKey = key;
  state.filters = filters.filters;
  state.filterKeys = filters.filters.map((f) => f.key);
  state.list = list;
  document.title = HOME_TITLE;

  $("#side").innerHTML = filterHtml();
  if ($("#sheet-body")) refreshSheet();
  $("#subjects").innerHTML = subjectsHtml();
  const n = chosenCount();
  $("#filter-count").hidden = !n;
  $("#filter-count").textContent = n;
  renderPaperHead(p, list);
  renderSummary(p, list);

  if (!filters.total_published) {
    $("#results").innerHTML = emptyBox("No questions yet",
      "Questions are being added and checked, and will appear here as soon as they are ready. Please check back soon.");
    return;
  }
  if (!list.total) {
    const back = state.asTyped?.from === location.search ? state.asTyped : null;
    $("#results").innerHTML = emptyBox("No questions match", "Try fewer filters or a different search.",
      (back ? `<a class="btn" href="${esc(back.url)}">Search “${esc(back.typed)}” in every subject</a> ` : "") +
      `<button class="btn" type="button" data-clear>Clear filters and search</button>`);
    return;
  }
  const from = (list.page - 1) * list.page_size;
  $("#results").innerHTML = `<div class="cards">${list.questions.map((q, i) => cardHtml(q, from + i + 1)).join("")}</div>${pagerHtml(list)}`;
  markOpenCard();
}

function subjectsHtml() {
  const f = state.filters.find((x) => x.key === "subject");
  if (!f || f.values.length < 2) return "";
  const all = `<button class="pill${f.selected.length ? "" : " on"}" type="button" data-subject-all>All</button>`;
  return all + f.values.map((v) => `<button class="pill${f.selected.includes(v.value) ? " on" : ""}" type="button"
    data-filter="subject" data-value="${esc(v.value)}" aria-pressed="${f.selected.includes(v.value)}">${esc(v.label)}
    <span class="n">${v.count}</span></button>`).join("");
}

function renderPaperHead(p, list) {
  const sid = p.get("paper");
  const head = $("#paper-head");
  if (!sid) { head.innerHTML = ""; return; }
  const title = list.questions[0]?.papers.find((x) => x.set_id === sid)?.title || "This paper";
  // questions of the paper still being checked, so a gap in the numbering isn't a mystery
  const held = list.not_shown?.length ? `<p class="muted">Not on the site yet: ${list.not_shown.map((n) => `Q${esc(n)}`)
    .join(", ")} (still being checked).</p>` : "";
  head.innerHTML = `<div class="paper-head"><h1>${esc(title)}</h1>
    <button class="linkish" type="button" data-unpaper>Leave this paper, show every question</button></div>${held}`;
}

function renderSummary(p, list) {
  const chosen = [];
  for (const f of state.filters) {
    if (f.key === "subject") continue;                       // subjects have their own row
    for (const v of f.selected) {
      const label = f.values.find((x) => x.value === v)?.label || v;
      chosen.push(`<button class="chip on" type="button" data-remove="${esc(f.key)}" data-value="${esc(v)}"
        aria-label="Remove filter ${esc(f.label)}: ${esc(label)}">${esc(f.label)}: ${esc(label)} ×</button>`);
    }
  }
  const text = p.get("q");
  const count = `<b>${list.total} question${list.total === 1 ? "" : "s"}</b>${text ? ` for “${esc(text)}”` : ""}`;
  $("#summary").innerHTML = `<span class="total">${count}</span>${chosen.join("")}` +
    (chosen.length || text ? `<button class="linkish" type="button" data-clear>Clear all</button>` : "") +
    sortHtml(p.get("sort") || (p.get("paper") ? "paper" : "year_desc"));
  wireSort();
}

// Our own dropdown, not a <select>: a native one draws its list in the browser's colours, not the theme's.
function sortHtml(current) {
  const label = SORTS.find(([v]) => v === current)?.[1] || SORTS[0][1];
  return `<div class="sortwrap"><button class="sortbtn" type="button" id="sortbtn" aria-haspopup="listbox"
      aria-expanded="false" aria-label="Sort">${ICON.sort}<span>${esc(label)}</span></button>
    <ul class="sortmenu" id="sortmenu" role="listbox" aria-label="Sort" hidden>${SORTS.map(([v, l]) =>
      `<li role="option" tabindex="-1" data-sort="${esc(v)}" aria-selected="${v === current}">${esc(l)}</li>`)
      .join("")}</ul></div>`;
}

function openSort(open) {
  const btn = $("#sortbtn"), menu = $("#sortmenu");
  if (!btn || !menu) return;
  menu.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
  if (open) (menu.querySelector('[aria-selected="true"]') || menu.firstElementChild)?.focus();
}

function wireSort() {
  $("#sortbtn").addEventListener("click", () => openSort($("#sortmenu").hidden));
  $("#sortmenu").addEventListener("click", (e) => {
    const li = e.target.closest("[data-sort]");
    if (li) change((q) => q.set("sort", li.dataset.sort));
  });
  $("#sortmenu").addEventListener("keydown", (e) => {
    const items = [...e.currentTarget.querySelectorAll("[data-sort]")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1) + items.length) % items.length].focus();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      change((q) => q.set("sort", document.activeElement.dataset.sort));
    } else if (e.key === "Escape") {
      openSort(false);
      $("#sortbtn").focus();
    }
  });
}

// A filter with one value to choose (every question ISC) filters nothing, so it isn't shown - except a yes/no one:
// "Has a figure: yes" is a real choice though "yes" is its only value.
function offered(f) {
  return f.values.length > 1 || f.selected.length || (f.kind === "yesno" && f.values.length > 0);
}

function filterHtml() {
  if (!state.filters.some(offered)) {
    return `<p class="muted">Filters appear once there are questions.</p>`;
  }
  return `<div class="side-head"><b>Filters</b><span><button class="linkish" type="button" data-fold-all="open">Open all</button>
      <button class="linkish" type="button" data-fold-all="shut">Fold all</button></span></div>
    <div class="fsearch">${ICON.search}<input class="tagsearch" type="search" placeholder="Search filters"
      aria-label="Search filters" value="${esc(state.tagQuery)}"></div>
    <div class="fgroups">${filterGroupsHtml()}</div>`;
}

// Which filter groups are folded: the visitor's own choice (kept in this browser), else Subject and Year open and
// the rest folded unless something in them is chosen.
const FOLD_KEY = "qh-fold";
function folds() {
  try { return JSON.parse(store(FOLD_KEY) || "{}") || {}; } catch (e) { return {}; }
}
function isShut(f) {
  const mine = folds()[f.key];
  if (mine !== undefined) return mine;
  return !["subject", "year"].includes(f.key) && !f.selected.length;
}
function setFold(key, shut) {
  const all = folds();
  all[key] = shut;
  store(FOLD_KEY, JSON.stringify(all));
}

// The groups on their own, so typing in the filter search redraws these without touching the input.
function filterGroupsHtml() {
  const find = state.tagQuery.trim().toLowerCase();
  const hit = (text) => text.toLowerCase().includes(find);
  const groups = state.filters
    .filter(offered)
    .map((f) => (!find || hit(f.label) ? f : { ...f, values: f.values.filter((v) => hit(v.label)) }))
    .filter((f) => f.values.length || f.selected.length);
  if (!groups.length) return `<p class="muted">No filters match “${esc(state.tagQuery)}”.</p>`;
  return groups.map((f) => {
    // while searching, every match shows: hiding them behind "Show all" would hide what was searched for
    const all = state.expanded[f.key] || !!find;
    const values = all ? f.values : f.values.slice(0, SHOW_VALUES);
    for (const s of f.selected) {                       // a chosen value stays visible
      if (!values.find((v) => v.value === s)) values.push({ value: s, label: s, count: 0 });
    }
    const shut = !find && isShut(f);
    return `<div class="fgroup${shut ? " shut" : ""}"><h3><button class="fold" type="button" data-fold="${esc(f.key)}"
      aria-expanded="${!shut}">${esc(f.label)}${f.selected.length ? `<span class="nsel">${f.selected.length}</span>` : ""}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"
        stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></h3><div class="fvalues">${values.map((v) => `
      <button class="chip${f.selected.includes(v.value) ? " on" : ""}" type="button" data-filter="${esc(f.key)}"
        data-value="${esc(v.value)}" aria-pressed="${f.selected.includes(v.value)}"
        aria-label="${esc(f.label)}: ${esc(v.label)}, ${v.count} question${v.count === 1 ? "" : "s"}"
        ><span>${esc(v.label)}</span><span class="n" aria-hidden="true">${v.count}</span></button>`).join("")}</div>
      ${!find && f.values.length > SHOW_VALUES ? `<button class="linkish" type="button" data-expand="${esc(f.key)}">
        ${all ? "Show fewer" : `Show all ${f.values.length}`}</button>` : ""}</div>`;
  }).join("");
}

// Card snippets, rendered once each: KaTeX is the slow part of drawing a list, and paging back and forth, or a new
// sort, shows the same questions again. Keyed by the search too, which the snippet highlights.
const snippets = new Map();
const SNIPPETS_MAX = 200;

function snippetHtml(q, query) {
  const key = `${q.id}\u0000${query}\u0000${window.katex ? 1 : 0}`;   // KaTeX may load after the first list
  let html = snippets.get(key);
  if (html === undefined) {
    html = rt(plainText(q.content), query);
    snippets.set(key, html);
    if (snippets.size > SNIPPETS_MAX) snippets.delete(snippets.keys().next().value);
  }
  return html;
}

function cardHtml(q, n) {
  const query = params().get("q") || "";
  // a real link to the question's own page (crawlable), that a plain click still opens as a dialog - see the
  // document click handler below
  // the badge counts this list, in the order it is sorted; the paper's own number is in the meta line below
  const subj = ((q.tags && q.tags.subject) || [""])[0].toLowerCase().replace(/[^a-z0-9]+/g, "-");   // its colour stripe
  return `<div class="cardrow"><a class="card${subj ? ` sub-${esc(subj)}` : ""}" href="${esc(q.url)}" data-open="${esc(q.id)}">
    <span class="badge"><b>${n}</b>
      <span>${esc(marksText(q.tags, true))}</span></span>
    <span class="body">
      <span class="snippet">${snippetHtml(q, query)}</span>
      <span class="meta"><span class="where">${esc(whereLine(q))}</span></span>
    </span></a></div>`;
}

function pagerHtml(list) {
  if (list.pages <= 1) return "";
  return `<nav class="pager" aria-label="Pages">
    <button class="btn" type="button" data-page="${list.page - 1}" ${list.page <= 1 ? "disabled" : ""}>‹ Previous</button>
    <span>Page ${list.page} of ${list.pages}</span>
    <button class="btn" type="button" data-page="${list.page + 1}" ${list.page >= list.pages ? "disabled" : ""}>Next ›</button></nav>`;
}

function emptyBox(title, text, extra) {
  return `<div class="empty"><h2>${esc(title)}</h2><p>${esc(text)}</p>${extra || ""}</div>`;
}

function errorBox(e) {
  return emptyBox("Couldn't load this", `${e.message}. Please try again in a moment.`);
}

function markOpenCard(qid) {
  const id = qid === undefined ? pathQid() : qid;
  document.querySelectorAll(".card").forEach((c) => c.classList.toggle("on", c.dataset.open === id));
}

// ---------------------------------------------------------------- one question

// history: "push" (a fresh navigation, e.g. a card click - gets a back-button entry), "replace" (stepping to a
// neighbour, or normalising the address once the canonical URL is known), or "none" (the address already names
// this question - render()/popstate got here from a navigation that already happened).
async function openQuestion(qid, { history: mode = "none" } = {}) {
  const dialog = $("#dialog");
  const wasOpen = !dialog.hidden;
  dialog.hidden = false;
  document.body.classList.add("q-open");
  if (!matchMedia("(min-width: 900px)").matches) document.body.style.overflow = "hidden";
  if (!wasOpen) state.returnFocus = document.activeElement;
  markOpenCard(qid);
  const seq = ++state.openSeq;
  const path = questionApi(qid);
  // a question fetched ahead draws straight away; otherwise say it is loading
  if (!cache.has(path)) $("#dialog-body").innerHTML = `<p class="muted">Loading…</p>`;
  let q;
  try { q = await getJSON(path); }
  catch (e) {
    if (seq !== state.openSeq) return;              // a newer open superseded this one
    $("#dialog-title").textContent = "Question"; $("#dialog-body").innerHTML = errorBox(e); return;
  }
  if (seq !== state.openSeq) return;
  if (mode !== "none") {
    const qs = listQuery().toString();
    history[mode === "push" ? "pushState" : "replaceState"](null, "", q.url + (qs ? `?${qs}` : ""));
  }
  state.open = q;
  markOpenCard(qid);
  $("#dialog-title").textContent = questionHeading(q);
  $("#dialog-page").href = q.url;
  document.title = `${titleWords(q)}${questionHeading(q)} - Prashnika`;
  const pos = q.position;
  $("#dialog-count").textContent = pos.index ? `${pos.index} / ${pos.total}` : "";
  $("#dialog-progress").style.width = pos.index ? `${(pos.index / pos.total) * 100}%` : "0";
  document.querySelectorAll("[data-step]").forEach((b) => { b.disabled = !pos[b.dataset.step]; });
  $("#dialog-body").innerHTML = questionHtml(q);
  $("#dialog-body").scrollTop = 0;
  if (!wasOpen) $("#dialog-close").focus();
  // fetch the neighbours now, while the visitor reads, so Next and Previous open at once
  for (const id of [pos.next, pos.prev]) if (id) getJSON(questionApi(id)).catch(() => {});
}

function questionApi(qid) {
  return `/api/questions/${encodeURIComponent(qid)}?${listQuery()}`;
}

function closeDialog(silent) {
  const dialog = $("#dialog");
  if (dialog.hidden) return;
  state.openSeq++;                                  // a question still loading must not reopen it
  dialog.hidden = true;
  document.body.classList.remove("q-open");
  document.body.style.overflow = "";
  state.open = null;
  markOpenCard(null);
  if (state.returnFocus?.focus) state.returnFocus.focus();
  if (!silent) go(params());                        // back to the list, at "/"
}

function optionList(list, part = "") {
  if (!list?.length) return "";
  // no line breaks inside <li>: options keep the text's own line breaks (white-space: pre-line)
  return `<ul class="opts" data-part="${esc(part)}">${list.map((o) => {
    return `<li data-opt="${esc(o.label)}"><b>${esc(o.label)}</b><span class="otext">${rt(o.text)}</span></li>`;
  }).join("")}</ul>`;
}

function fieldsHtml(c, head, part = "") {
  let html = "";
  // 
  if (c.assertion) html += `<p class="qtext"><b>Assertion:</b> ${rt(c.assertion)}</p><p class="qtext"><b>Reason:</b> ${rt(c.reason)}</p>`;
  if (c.text) html += `<div class="${head ? "qhead" : "qtext"}">${rt(c.text)}</div>`;
  if (c.start) html += `<p class="qtext"><b>Given:</b> ${rt(c.start)}</p>`;
  if (c.target) html += `<p class="qtext"><b>To show:</b> ${rt(c.target)}</p>`;
  if (c.draw) html += `<p class="qtext"><b>Draw:</b> ${rt(c.draw)}</p>`;
    if (c.must_show?.length) html += `<p class="qtext"><b>Must show:</b> ${c.must_show.map(esc).join(", ")}</p>`;
  html += optionList(c.options, part);
    if (c.column_a) html += `<div class="cols"><div><b>Column A</b>${optionList(c.column_a)}</div><div><b>Column B</b>${optionList(c.column_b)}</div></div>`;
    if (c.sample_io) html += `<p><b>Sample input/output</b></p><div class="qtext">${rt("```\n" + c.sample_io + "\n```")}</div>`;
    if (c.word_limit) html += `<p class="muted">Word limit: ${esc(c.word_limit)}</p>`;
  return html;
}

function questionHtml(q) {
  const c = q.content;
  const tags = [first(q.tags, "subject"), first(q.tags, "year"), marksText(q.tags), TYPE_LABEL[q.type]].filter(Boolean);
  let html = `<div class="qtags">${tags.map((t) => `<span class="qtag">${esc(t)}</span>`).join("")}</div>`;
  if (c.passage) html += `<div class="passage">${rt(c.passage)}</div>`;
  html += fieldsHtml(c, true);
  for (const part of c.parts || []) {
    html += `<div class="part"><div><span class="part-label">${esc(part.label)}</span>${part.marks ? `<span class="muted">[${esc(part.marks)}]</span>` : ""}</div>
      ${fieldsHtml(part, false, part.label || "")}</div>`;
  }
  const paper = q.papers?.[0];
  const google = `https://www.google.com/search?q=${encodeURIComponent(plainText(c).replace(/\$/g, "").slice(0, 200))}`;
  html += `<div class="q-links"><a href="${google}" target="_blank" rel="noopener">Find on Google</a>
    ${paper ? `<span class="dot">·</span><a href="${paper.url || `/?paper=${encodeURIComponent(paper.set_id)}`}">Whole paper</a>` : ""}
  </div>`;
  const chapters = ["chapter", "unit", "topic"].flatMap((k) => q.tags[k] || []);
  if (chapters.length) html += `<div class="qtags">${chapters.map((t) => `<span class="qtag">${esc(t)}</span>`).join("")}</div>`;
  if (paper) html += `<p class="muted">From ${esc(paper.title)}${paper.printed_number ? `, question ${esc(paper.printed_number)}` : ""}.</p>`;
  return html;
}

// ---------------------------------------------------------------- events

function wireTools() {
  let timer;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(timer);
    // one Back step per search, not one per pause while typing it: the first pause adds a history entry (marked
    // typing), later ones replace it (2026-10-09). A new search is typed as written (no as=typed left over).
    timer = setTimeout(() => {
      const p = params(), text = e.target.value.trim();
      if (text) p.set("q", text); else p.delete("q");
      ["as", "page", "per"].forEach((k) => p.delete(k));
      const qs = p.toString(), typing = history.state?.typing === true;
      history[typing ? "replaceState" : "pushState"]({ typing: true }, "", qs ? `/?${qs}` : "/?view=questions");
      render();
    }, 350);
  });
  $("#open-filters").addEventListener("click", openSheet);
}

function refreshSheet() {
  $("#sheet-body").innerHTML = filterHtml();
  const n = state.list?.total ?? 0;
  $("#sheet-show").textContent = `Show ${n} question${n === 1 ? "" : "s"}`;
}

function openSheet() {
  const sheet = document.createElement("div");
  sheet.className = "sheet";
  sheet.innerHTML = `<div class="sheet-box" role="dialog" aria-modal="true" aria-label="Filters">
    <div class="sheet-grip" aria-hidden="true"></div>
    <div class="sheet-head"><h2>Filters</h2>
      <button class="icon" type="button" data-close-sheet aria-label="Close filters">${ICON.x}</button></div>
    <div class="sheet-body" id="sheet-body"></div>
    <div class="sheet-foot"><button class="btn" type="button" data-clear>Clear all</button>
      <button class="btn primary" type="button" id="sheet-show" data-close-sheet></button></div></div>`;
  sheet.addEventListener("click", (e) => { if (e.target === sheet || e.target.closest("[data-close-sheet]")) sheet.remove(); });
  document.body.appendChild(sheet);
  refreshSheet();
}

document.addEventListener("input", (e) => {
  if (!e.target.classList.contains("tagsearch")) return;
  state.tagQuery = e.target.value;
  document.querySelectorAll(".fgroups").forEach((el) => { el.innerHTML = filterGroupsHtml(); });
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".sortwrap")) openSort(false);          // a click anywhere else closes the sort menu
  const t = e.target.closest("button, a");
  if (!t) return;
  const d = t.dataset;
  if (d.open) {
    if (e.ctrlKey || e.metaKey) return;              // let the browser open a new tab
    e.preventDefault();
    openQuestion(d.open, { history: "push" });
  }
  else if (t.id === "dialog-page") {
    if (e.ctrlKey || e.metaKey || e.shiftKey) return;   // a new tab: this page stays as it is
    // The address shows this question now, and loading that address gives its own page - so Back from that page
    // would land on the same question again. Point this history entry at the list first, so Back returns there.
    const qs = listQuery().toString();
    history.replaceState(null, "", qs ? `/?${qs}` : "/");
  }
  else if (d.filter) {
    change((p) => {
      const now = p.getAll(d.filter);
      p.delete(d.filter);
      (now.includes(d.value) ? now.filter((v) => v !== d.value) : [...now, d.value]).forEach((v) => p.append(d.filter, v));
    });
  } else if (d.remove) {
    change((p) => { const now = p.getAll(d.remove); p.delete(d.remove); now.filter((v) => v !== d.value).forEach((v) => p.append(d.remove, v)); });
  } else if ("subjectAll" in d) {
    change((p) => p.delete("subject"));
  } else if ("clear" in d) {
    change((p) => { state.filterKeys.forEach((k) => p.delete(k)); p.delete("q"); });
  } else if ("unpaper" in d) {
    change((p) => { p.delete("paper"); p.delete("sort"); });
  } else if (d.fold) {
    const shut = !t.closest(".fgroup").classList.contains("shut");
    setFold(d.fold, shut);
    document.querySelectorAll(`[data-fold="${CSS.escape(d.fold)}"]`).forEach((b) => {   // the side panel and the phone sheet
      b.closest(".fgroup").classList.toggle("shut", shut);
      b.setAttribute("aria-expanded", String(!shut));
    });
  } else if (d.foldAll) {
    const shut = d.foldAll === "shut";
    state.filters.filter(offered).forEach((f) => setFold(f.key, shut));
    $("#side").innerHTML = filterHtml();
    if ($("#sheet-body")) refreshSheet();
  } else if (d.expand) {
    state.expanded[d.expand] = !state.expanded[d.expand];
    $("#side").innerHTML = filterHtml();
    if ($("#sheet-body")) refreshSheet();
  } else if (d.page) {
    change((p) => { p.set("page", d.page); if (pageSize() === 10) p.set("per", "10"); }, true);
    window.scrollTo({ top: 0 });
  } else if (d.step) {
    step(d.step);
  } else if (t.tagName === "A" && t.getAttribute("href")?.startsWith("/?") && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    document.querySelector(".sheet")?.remove();
    history.pushState(null, "", t.getAttribute("href"));
    $("#main").innerHTML = `<p class="muted pad">Loading…</p>`;
    render();
  } else if (t.tagName === "A" && t.getAttribute("href") === "/" && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    history.pushState(null, "", "/");
    $("#main").innerHTML = `<p class="muted pad">Loading…</p>`;
    render();
  }
});

function step(dir) {
  const id = state.open?.position?.[dir];
  if (!id) return;
  openQuestion(id, { history: "replace" });
}

$("#dialog-close").addEventListener("click", () => closeDialog());
$("#dialog").addEventListener("click", (e) => { if (e.target.id === "dialog") closeDialog(); });
document.addEventListener("keydown", (e) => {
  if ($("#dialog").hidden || e.target.closest("input, textarea, select")) return;
  if (e.key === "Escape") closeDialog();
  else if (e.key === "ArrowLeft") step("prev");
  else if (e.key === "ArrowRight") step("next");
});
// Back from a question's own page can restore this page from the browser's memory, with the pop-up still open
// though the address (see the dialog-page click above) is the list: draw what the address says.
window.addEventListener("pageshow", (e) => { if (e.persisted) render(); });
window.addEventListener("popstate", () => {
  if (!$(".layout") || params().get("view") === "papers") $("#main").innerHTML = `<p class="muted pad">Loading…</p>`;
  render();
});

render();
