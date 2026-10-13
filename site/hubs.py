"""Hub pages: the pages that let a visitor (and a crawler) walk the bank by board, subject, year, chapter and paper,
server-rendered like the question pages (pages.Page + the one template). Their facts come from catalog.py.

    /isc                                  every subject of the board
    /isc/physics                          the subject: its papers by year and its chapters
    /isc/physics/2024                     one year's papers
    /isc/physics/2024/board-paper         one paper, every question linked in printed order
    /isc/physics/chapter/electrostatics   every question of a chapter, newest first, with a search box
    /chapters                             every chapter of every subject, with a box that narrows them

The homepage's text (home_html) is the same directory in short, served under the interactive list.
Each builder returns a Page, or None when there is nothing at that address (the route 404s).

"""

import json
from urllib.parse import quote

import catalog
import pages
import richtext
from pages import Page, SITE_URL
from sitedb import connect

esc = richtext.escape_html
CHAPTER_FULL_MAX = 20             # questions in full per chapter page (/chapter/x, then /chapter/x/page/2 ...)
CHAPTER_QUESTIONS_MAX = 600       # a chapter page lists at most this many questions (the biggest has far fewer)


def _years(plist):
    return sorted({p["year"] for p in plist if p["path"]}, reverse=True)


def _span(years):
    return f"{years[-1]}-{years[0]}" if len(years) > 1 else (years[0] if years else "")


def _cls(plist):
    return next((p["cls"] for p in plist if p["cls"]), "12")


def _count(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def _links(items, cls="related tiles"):
    """[(href, text_html, meta)] as a list of link boxes."""
    lis = "".join(f'<li><a href="{esc(h)}">{t}{f" <span class=muted>{esc(m)}</span>" if m else ""}</a></li>'
                  for h, t, m in items)
    return f'<div class="{cls}"><ul>{lis}</ul></div>'


def _graph(kind, name, url, description, crumbs, extra=None):
    node = {"@type": kind, "name": name, "url": f"{SITE_URL}{url}", "description": description}
    node.update(extra or {})
    return {"@context": "https://schema.org", "@graph": [node, pages._breadcrumb_ld(crumbs)]}


def _subject_of(conn, bs, ss):
    return next((s for s in catalog.subjects(conn) if (s["board_slug"], s["subject_slug"]) == (bs, ss)), None)


def _plain(content):
    return pages._plain_text(content or {})


# ---------------------------------------------------------------- the homepage and the board



def _icon(slug, size=22):
    """The site draws a small picture per subject here; this copy of the code draws none."""
    return ""


_ORDER = ("computer-science", "physics", "chemistry", "mathematics", "english-language", "english-literature",
          "physical-education")


def _ordered(subjects):
    """Subjects in the site's order; any other subject after them."""
    return sorted(subjects, key=lambda s: _ORDER.index(s["subject_slug"]) if s["subject_slug"] in _ORDER else len(_ORDER))


def _subject_card(s, n_papers, cls="", big=False, chips=()):
    """A subject as one card that is all one link: icon, name, counts, and a few chips."""
    slug = s["subject_slug"]
    blurb = ""
    chip_html = "".join(f'<span class="tagchip{" acc" if acc else ""}">{esc(t)}</span>' for t, acc in chips)
    return (f'<a class="sub-card{" big" if big else ""} {cls} sub-{esc(slug)}" href="{esc(s["path"])}">'
            f'<span class="ic">{_icon(slug)}</span><h3>{esc(s["subject"])}</h3>'
            f'<span class="meta"><span class="mq">{esc(s["board"])} · {_count(s["n"], "question")} · </span>{_count(n_papers, "paper")}</span>'
            f'{blurb}{f"<span class=chips>{chip_html}</span>" if chip_html else ""}</a>')


def _bento(subjects, plist):
    """The home page's subject cards: the first large, the next four small, the rest wide."""
    out = []
    for i, s in enumerate(subjects):
        key = (s["board_slug"], s["subject_slug"])
        n_papers = sum(1 for p in plist if (p["board_slug"], p["subject_slug"]) == key and p["path"])
        if i == 0:
            out.append(_subject_card(s, n_papers, "c6 r2", big=True, chips=[("By year", False), ("By chapter", False)]))
        else:
            out.append(_subject_card(s, n_papers, "c3" if i <= 4 else "c6"))
    pills = "".join(f'<a class="pill sub-{esc(s["subject_slug"])}" href="{esc(s["path"])}"><span class="sdot"></span>{esc(s["subject"])}</a>'
                    for s in subjects)
    return f'<nav class="hm-pills" aria-label="Subjects">{pills}</nav><div class="bento">{"".join(out)}</div>'












def home_html():
    """The landing page at the bare address: a hero (the <h1> and a search box), a numbers strip, and a card per
    subject. The interactive question list lives at /?view=questions; site.js shows this section only on the bare
    address."""
    conn = connect()
    try:
        subjects, plist = _ordered(catalog.subjects(conn)), catalog.papers(conn)
        counts = catalog.totals(conn)
        n_chapters = len(catalog.chapters(conn))
    finally:
        conn.close()
    if not subjects:
        return ""
    names = [s["subject"] for s in subjects]
    total = counts["questions"]
    papers = [p for p in plist if p["path"]]
    stats = "".join(f'<li><b>{esc(v)}</b><span>{esc(k)}</span></li>' for k, v in (
        ("questions", f"{total:,}"), ("question papers", f"{len(papers):,}"), ("subjects", str(len(subjects))),
        ("chapters", f"{n_chapters:,}")))      # four tiles: the strip is a 4-column grid
    return (
        '<section class="home-about" id="home-about">'
        '<div class="hero hm-hero">'

        '<div class="hm-hero-main">'
        '<h1>Past exam questions, <em>sorted</em></h1>'
        f'<p class="hero-sub">{total:,} questions from past papers, sorted by subject, year, paper and chapter.</p>'
        '<form class="hero-search" action="/" method="get" role="search">'
        '<input type="search" name="q" aria-label="Search questions" autocomplete="off" '
        f'placeholder="Search {total:,} questions">'
        '<button class="btn primary" type="submit">Search</button></form>'
        '<p class="hero-links"><a href="/?view=questions">Browse every question &rarr;</a>'
        '<a href="/papers">All papers &rarr;</a></p>'
        '</div>'
        '</div>'
        f'<ul class="hm-stats">{stats}</ul>'
        '<section><div class="sec-head"><h2>Pick a subject</h2><a href="/papers">All papers &rarr;</a></div>'
        f'{_bento(subjects, plist)}</section>'
        f'<p class="about">Subjects covered: {esc(", ".join(names))}. Every question has its own page with the full '
        'text and links to more questions from the same chapter and the same paper.</p></section>')


def home_description(conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        names = [s["subject"] for s in catalog.subjects(conn)]
    finally:
        if own:
            conn.close()
    if not names:
        return "Past exam questions by subject, year, paper and chapter."
    return (f"Past exam questions for {', '.join(names)}, sorted by year, paper and chapter.")[:300]


def _subject_chips(subjects, all_label="All subjects", counts=None):
    """A row of filter chips, All then one per subject (page.js wireSubjects hides the [data-subj] groups of the others)."""
    chips = [f'<button type="button" class="fchip on" data-subj-chip="">{esc(all_label)}</button>']
    for s in subjects:
        n = f" &middot; {counts[s['subject_slug']]}" if counts else ""
        chips.append(f'<button type="button" class="fchip sub-{esc(s["subject_slug"])}" data-subj-chip="{esc(s["subject_slug"])}">'
                     f'<span class="sdot"></span>{esc(s["subject"])}{n}</button>')
    return f'<div class="fchips" role="group" aria-label="Subject">{"".join(chips)}</div>'


def _chapter_list(mine, limit=None):
    """A subject's chapters as rows: name, a bar against its biggest chapter, the number of questions."""
    rows = sorted(mine, key=lambda c: -c["n"])[:limit] if limit else mine
    top = max((c["n"] for c in mine), default=1) or 1
    return '<ul class="chlist">' + "".join(
        f'<li><a class="chrow" href="{esc(c["path"])}"><span class="nm">{esc(c["chapter"])}</span>'
        f'<span class="cb"><i style="width:{max(4, round(100 * c["n"] / top))}%"></i></span>'
        f'<span class="ct" title="{_count(c["n"], "question")}">{c["n"]}</span></a></li>' for c in rows) + '</ul>'


def _subject_chapters_card(s, mine, limit=None):
    slug = s["subject_slug"]
    return (f'<section class="chcard sub-{esc(slug)}" data-subj="{esc(slug)}" data-filter-group>'
            f'<div class="chcard-head"><span class="ic">{_icon(slug, 20)}</span>'
            f'<h2><a href="{esc(s["path"])}">{esc(s["subject"])}</a></h2>'
            f'<a class="chcard-all" href="{esc(s["path"])}">All {len(mine)} chapters &rarr;</a></div>'
            f'{_chapter_list(mine, limit)}</section>')


def board_page(bs):
    """/isc - the header's "Subjects": a card per subject with its chapters that have the most questions."""
    conn = connect()
    try:
        subjects = _ordered([s for s in catalog.subjects(conn) if s["board_slug"] == bs])
        plist = [p for p in catalog.papers(conn) if p["board_slug"] == bs]
        chapters = [c for c in catalog.chapters(conn) if c["board_slug"] == bs]
    finally:
        conn.close()
    if not subjects:
        return None
    board = subjects[0]["board"]
    path = f"/{bs}"
    heading = f"{board} Class {_cls(plist)} Previous Year Question Papers"
    crumbs = [("Prashnika", "/"), (board, path)]
    cards = []
    for s in subjects:
        mine = [c for c in chapters if c["subject_slug"] == s["subject_slug"]]
        if mine:
            cards.append(_subject_chapters_card(s, mine, limit=6))
    body = (pages._crumbs([("Prashnika", "/"), (board, None)]) +
            f'<p>Every {esc(board)} question on Prashnika, {sum(s["n"] for s in subjects):,} in all, by subject. Pick a '
            'subject to see its chapters and papers; each card lists the chapters with the most questions first.</p>' +
            _subject_chips(subjects) + f'<div class="chap-grid">{"".join(cards)}</div>')
    desc = f"{board} Class {_cls(plist)} question papers: " + ", ".join(s["subject"] for s in subjects) + "."
    return Page(path=path, title=f"{heading} | Prashnika", description=desc[:300], body_html=body, heading=heading,
                og_type="website", nav="subjects",
                jsonld=_graph("CollectionPage", heading, path, desc, crumbs))


_KIND_SHORT = {"board_paper": "Board", "specimen": "Specimen", "improvement": "Improvement", "practice": "CFQ",
               "school_paper": "School"}


def _year_tile(p):
    """One paper as a small tile: its year, then what kind of paper it is. The paper's full name is visible to
    screen readers and to the box that narrows the list (page.js wireFilter), so "Physics 2024" still finds it."""
    return (f'<li data-kind="{esc(p["kind"])}"><a class="yp{" board" if p["kind"] == "board_paper" else ""}" '
            f'href="{esc(p["path"])}"><b>{esc(p["year"])}</b><span>{esc(_KIND_SHORT.get(p["kind"], "Paper"))}</span>'
            f'<span class="sr"> {esc(p["label"])}</span></a></li>')


def _paper_card(s, mine):
    """A subject's card on /papers: its icon and name, a link to the subject, a tile per paper."""
    slug = s["subject_slug"]
    return (f'<section class="chcard paper-index sub-{esc(slug)}" data-filter-group>'
            f'<div class="chcard-head"><span class="ic">{_icon(slug, 20)}</span>'
            f'<h2><a href="{esc(s["path"])}">{esc(s["subject"])}</a></h2>'
            f'<a class="chcard-all" href="{esc(s["path"])}">{_count(len(mine), "paper")} &rarr;</a></div>'
            f'<ul class="ygrid">{"".join(_year_tile(p) for p in mine)}</ul></section>')


def _kind_chips(plist):
    """The row of filter chips above /papers (page.js wireKinds): All, then one per kind of paper present."""
    kinds = [k for k in _KIND_SHORT if any(p["kind"] == k for p in plist)]
    chips = ['<button type="button" class="fchip on" data-kind-chip="">All papers</button>']
    chips += [f'<button type="button" class="fchip" data-kind-chip="{k}">{_KIND_SHORT[k]}</button>' for k in kinds]
    return f'<div class="fchips" role="group" aria-label="Kind of paper">{"".join(chips)}</div>'


def papers_page():
    """/papers: every paper, by subject and year - the page the header's "Papers" link opens."""
    conn = connect()
    try:
        subjects, plist = catalog.subjects(conn), [p for p in catalog.papers(conn) if p["path"]]
    finally:
        conn.close()
    if not plist:
        return None
    body = [pages._crumbs([("Prashnika", "/"), ("Papers", None)]),
            f'<p>All {_count(len(plist), "paper")} on Prashnika: board papers, specimen papers, improvement papers and '
            'Competency Focused Questions (CFQ), by subject and year. Open a paper to see all its questions.</p>',
            '<div class="chiprow">' + _kind_chips(plist) +
            '<p class="legend"><span class="mc board">Board</span>the year&rsquo;s board paper'
            '<span class="mc">Specimen</span>practice and improvement papers</p></div>',
            '<div class="chap-grid">']
    for s in _ordered(subjects):
        mine = [p for p in plist if (p["board_slug"], p["subject_slug"]) == (s["board_slug"], s["subject_slug"])]
        if mine:
            body.append(_paper_card(s, mine))
    body.append('</div>')
    desc = f"All {len(plist)} question papers, by subject and year."
    crumbs = [("Prashnika", "/"), ("Papers", "/papers")]
    return Page(path="/papers", title="ISC Class 12 Question Papers by Subject and Year | Prashnika", description=desc,
                body_html="".join(body), heading="ISC Class 12 Question Papers", og_type="website",
                nav="papers", jsonld=_graph("CollectionPage", "ISC Class 12 Question Papers", "/papers", desc, crumbs))


def about_page():
    """/about: what this site is. Edit the text below for your own deployment."""
    conn = connect()
    try:
        plist = [p for p in catalog.papers(conn) if p["path"]]
        subjects = catalog.subjects(conn)
    finally:
        conn.close()
    n_q = sum(p["n"] for p in plist)
    span = _span(_years(plist))
    subject_links = _links([(s["path"], esc(s["subject"]), _count(s["n"], "question")) for s in subjects])
    body = (pages._crumbs([("Home", "/"), ("About", None)]) +
            '<p>This is a question bank: past exam papers broken into single questions and sorted by subject, year, '
            'paper and chapter.</p>'
            f'<p>It holds {_count(len(plist), "paper")} and {_count(n_q, "question")}'
            f'{" from " + esc(span) if span else ""}. Open a subject to see its papers by year and its questions '
            'chapter by chapter:</p>' +
            subject_links +
            '<p>The <a href="/papers">papers page</a> lists every paper, the <a href="/chapters">chapters page</a> '
            'every chapter.</p>')
    desc = "About this question bank: what it holds and how it is sorted."
    return Page(path="/about", title="About", description=desc, body_html=body, heading="About", og_type="website",
                jsonld=_graph("AboutPage", "About", "/about", desc, [("Home", "/"), ("About", "/about")]))


def privacy_page():
    """/privacy: what the site stores. Keep it true with what the page scripts and server actually keep."""
    body = (pages._crumbs([("Home", "/"), ("Privacy", None)]) +
            '<h2>Kept in your browser</h2>'
            '<p>Your theme and Lite mode are kept only in your own browser (localStorage). The site sets no cookies '
            'and has no accounts.</p>')
    desc = "Privacy: what this site keeps in your browser."
    return Page(path="/privacy", title="Privacy", description=desc, body_html=body, heading="Privacy",
                og_type="website", jsonld=_graph("WebPage", "Privacy", "/privacy", desc,
                                                 [("Home", "/"), ("Privacy", "/privacy")]))


def _search_box(target, placeholder, label, form_to_list=False):
    """A box that hides the items matching `target` (a CSS selector) whose text doesn't hold what is typed
    (page.js wireFilter). With form_to_list, pressing Search instead searches every question (/?q=)."""
    attrs = 'action="/" method="get"' if form_to_list else 'action="#" data-filter-form'
    button = '<button class="btn primary" type="submit">Search all questions</button>' if form_to_list else ""
    return (f'<form class="filterbox" role="search" {attrs}>'
            f'<input type="search" name="q" placeholder="{esc(placeholder)}" aria-label="{esc(label)}" '
            f'autocomplete="off" data-filter="{esc(target)}">{button}</form>'
            '<p class="muted filter-none" data-filter-none hidden>Nothing matches. Try fewer letters.</p>')


def chapters_page():
    """/chapters: every chapter of every subject, with a box that narrows them as you type - the header's
    "Chapters" link. Each chapter opens its own page with all its questions."""
    conn = connect()
    try:
        subjects, chapters = catalog.subjects(conn), catalog.chapters(conn)
    finally:
        conn.close()
    if not chapters:
        return None
    body = [pages._crumbs([("Prashnika", "/"), ("Chapters", None)]),
            f'<p>All {_count(len(chapters), "chapter")} on Prashnika, by subject, with how many past-paper questions each '
            'has. Open a chapter to practise it.</p>',
            _search_box(".chapter-index li", "Find a chapter, e.g. Recursion or Electrostatics", "Find a chapter",
                        form_to_list=True)]
    shown = []
    for s in _ordered(subjects):
        mine = [c for c in chapters if (c["board_slug"], c["subject_slug"]) == (s["board_slug"], s["subject_slug"])]
        if mine:
            shown.append((s, mine))
    body.append(_subject_chips([s for s, _ in shown]))
    body.append('<div class="chap-grid">' + "".join(
        _subject_chapters_card(s, mine).replace('class="chcard ', 'class="chcard chapter-index ', 1) for s, mine in shown)
        + '</div>')
    desc = (f"All {len(chapters)} ISC Class 12 chapters on Prashnika, by subject: every past-paper question on each "
            "chapter.")
    crumbs = [("Prashnika", "/"), ("Chapters", "/chapters")]
    return Page(path="/chapters", title="ISC Class 12 Questions by Chapter, Every Subject | Prashnika", description=desc,
                body_html="".join(body), heading="ISC Class 12 Questions by Chapter", og_type="website",
                nav="chapters", jsonld=_graph("CollectionPage", "ISC Class 12 Questions by Chapter", "/chapters", desc, crumbs))


def _hero(crumbs_html, heading, intro_html, kpis=(), chips_html="", acts_html="", sub=""):
    """A page's header card: crumbs, chips, the <h1>, a line or two, buttons, and numbers on the right."""
    k = "".join(f'<div class="kpi"><b>{esc(v)}</b><span>{esc(l)}</span></div>' for v, l in kpis)
    return (f'<header class="pg-hero{" sub-" + esc(sub) if sub else ""}">'
            f'<div class="pg-hero-main">{crumbs_html}{chips_html}<h1>{esc(heading)}</h1>{intro_html}'
            f'{f"<div class=acts>{acts_html}</div>" if acts_html else ""}</div>'
            f'{f"<div class=kpis>{k}</div>" if k else ""}</header>')


def _side(title, inner):
    return f'<section class="sidecard"><h2>{esc(title)}</h2>{inner}</section>'


def _li(href, text, meta="", on=False):
    return (f'<a class="li{" on" if on else ""}" href="{esc(href)}"{" aria-current=page" if on else ""}>{esc(text)}'
            f'{f"<span>{esc(meta)}</span>" if meta else ""}</a>')


def _btn(href, text, primary=False, nofollow=False):
    return (f'<a class="btn{" primary" if primary else ""}" href="{esc(href)}"{" rel=nofollow" if nofollow else ""}>'
            f'{esc(text)}</a>')


def _sub_chip(subject, slug):
    return f'<span class="tagchip sub-{esc(slug)}"><span class="dot"></span>{esc(subject)}</span>'




def _page_layout(main_html, side_html):
    return f'<div class="pgrid"><div class="pmain">{main_html}</div><aside class="pside" aria-label="More to practise">{side_html}</aside></div>'


# ---------------------------------------------------------------- the subject

def subject_page(bs, ss):
    conn = connect()
    try:
        subj = _subject_of(conn, bs, ss)
        if not subj:
            return None
        plist = [p for p in catalog.papers(conn) if (p["board_slug"], p["subject_slug"]) == (bs, ss)]
        chapters = [c for c in catalog.chapters(conn) if (c["board_slug"], c["subject_slug"]) == (bs, ss)]
        others = [o for o in _ordered(catalog.subjects(conn)) if o["board_slug"] == bs and o["subject_slug"] != ss]
    finally:
        conn.close()
    board, subject, path = subj["board"], subj["subject"], subj["path"]
    years = _years(plist)
    cls = _cls(plist)
    heading = f"{board} Class {cls} {subject} Previous Year Question Papers"
    crumbs = [("Prashnika", "/"), (f"{board} {subject}", path)]
    papers = [p for p in plist if p["path"]]
    intro = (f'<p>{_count(subj["n"], "question")} from {_count(len(plist), "paper")}'
             f'{" (" + _span(years) + ")" if years else ""} for {esc(board)} Class {esc(cls)} {esc(subject)}, '
             'Open a paper for all its questions, or a chapter to practise it.</p>')
    hero = _hero(pages._crumbs([("Prashnika", "/"), (board, f"/{bs}"), (subject, None)]), heading, intro,
                 kpis=((str(len(chapters)), "chapters"), (str(len(plist)), "papers"), (f'{subj["n"]:,}', "questions")),
                 sub=ss)
    main = []
    if papers:
        ylinks = "".join(f'<a class="tagchip" href="{esc(path)}/{y}">{y}</a>' for y in years)
        main.append(f'<section class="chcard paper-index sub-{esc(ss)}"><div class="chcard-head"><span class="ic">{_icon(ss, 20)}</span>'
                    f'<h2>Question papers</h2><span class="chcard-all muted">{_count(len(papers), "paper")}</span></div>'
                    f'<nav class="tagchips" aria-label="Papers by year">{ylinks}</nav>'
                    f'<ul class="ygrid">{"".join(_year_tile(p) for p in papers)}</ul></section>')
    if chapters:
        main.append(f'<div class="sec-head"><h2>{esc(subject)} chapters</h2>'
                    f'<a href="/?subject={quote(subject)}">Search every question &rarr;</a></div>' + _chapter_rows(chapters, ss))
    side = []
    side.append("")
    if others:
        side.append(_side("Other subjects", "".join(_li(o["path"], o["subject"], _count(o["n"], "question")) for o in others)))
    desc = (f"{board} Class {cls} {subject} previous year question papers "
            f"{' from ' + _span(years) if years else ''}: {_count(subj['n'], 'question')}, by year and by chapter.")
    return Page(path=path, title=f"{heading} | Prashnika", description=desc[:300],
                body_html=hero + _page_layout("".join(main), "".join(side)), heading=heading, og_type="website",
                nav="subjects", own_h1=True, jsonld=_graph("CollectionPage", heading, path, desc, crumbs))


def _chapter_rows(chapters, ss):
    """A subject's chapters as a list: number, name, how many questions (with a bar next to the biggest), a link."""
    top = max((c["n"] for c in chapters), default=1) or 1
    rows = "".join(
        f'<a class="crow" href="{esc(c["path"])}"><span class="no">{i:02d}</span>'
        f'<span class="nm"><b>{esc(c["chapter"])}</b></span>'
        f'<span class="bw"><span>{_count(c["n"], "question")}</span><span class="cbar"><i style="width:{max(4, round(100 * c["n"] / top))}%">'
        '</i></span></span><span class="go">Practise &rarr;</span></a>' for i, c in enumerate(chapters, 1))
    return (f'<div class="clist sub-{esc(ss)}"><div class="crow head"><span>No.</span><span>Chapter</span><span>Questions</span>'
            f'<span></span></div>{rows}</div>')






# ---------------------------------------------------------------- a year

def year_page(bs, ss, year):
    conn = connect()
    try:
        subj = _subject_of(conn, bs, ss)
        plist = [p for p in catalog.papers(conn) if (p["board_slug"], p["subject_slug"]) == (bs, ss) and p["path"]]
    finally:
        conn.close()
    year = str(year)
    mine = [p for p in plist if p["year"] == year]
    if not subj or not mine:
        return None
    board, subject = subj["board"], subj["subject"]
    path = f"{subj['path']}/{year}"
    cls = _cls(plist)
    heading = f"{board} Class {cls} {subject} {year} Question Papers"
    crumbs = [("Prashnika", "/"), (f"{board} {subject}", subj["path"]), (year, path)]
    years = _years(plist)
    tiles = "".join(
        f'<li><a class="yp{" board" if p["kind"] == "board_paper" else ""}" href="{esc(p["path"])}"><b>{esc(p["label"])}</b>'
        f'<span>{esc(_KIND_SHORT.get(p["kind"], "Paper"))} · {_count(p["n"], "question")}</span></a></li>' for p in mine)
    ylinks = "".join(f'<a class="tagchip{" acc" if y == year else ""}" href="{esc(subj["path"])}/{y}">{y}</a>' for y in years)
    body = (pages._crumbs([("Prashnika", "/"), (f"{board} {subject}", subj["path"]), (year, None)]) +
            f'<p>The {esc(board)} Class {esc(cls)} {esc(subject)} papers of {year} on Prashnika: '
            f'{_count(len(mine), "paper")}, {_count(sum(p["n"] for p in mine), "question")} in all.</p>' +
            f'<section class="chcard sub-{esc(ss)}"><div class="chcard-head"><span class="ic">{_icon(ss, 20)}</span>'
            f'<h2>{esc(subject)} {year}</h2><a class="chcard-all" href="{esc(subj["path"])}">All {esc(subject)} papers &rarr;</a></div>'
            f'<ul class="ygrid wide">{tiles}</ul></section>'
            f'<div class="sec-head"><h2>Other years</h2></div><nav class="tagchips" aria-label="Other years">{ylinks}</nav>')
    desc = (f"{board} Class {cls} {subject} {year} question papers: "
            + ", ".join(p["label"] for p in mine))[:300]
    return Page(path=path, title=f"{board} Class {cls} {subject} {year} Papers | Prashnika",
                description=desc, body_html=body, heading=heading,
                og_type="website", nav="subjects", jsonld=_graph("CollectionPage", heading, path, desc, crumbs))




# ---------------------------------------------------------------- a paper

def _paper_intro(paper, n, per_chapter, chapter_paths):
    """The opening of a paper page: what the paper is, its marks and the chapters it covers (most questions first,
    each linked to its chapter page)."""
    marks = f", {esc(paper['total_marks'])} marks in all" if paper["total_marks"] else ""
    out = (f'<p>The {esc(paper["label"])} for Class {esc(paper["cls"])}: all {_count(n, "question")}{marks}, in '
           'printed order and in full.</p>')
    if per_chapter:
        ranked = sorted(per_chapter.items(), key=lambda kv: (-kv[1], kv[0]))
        bits = [(f'<a href="{esc(chapter_paths[c])}">{esc(c)}</a>' if c in chapter_paths else esc(c)) + f" ({k})"
                for c, k in ranked]
        out += (f'<p>Chapters this paper asks from, by number of questions: {", ".join(bits)}.</p>')
    return out


def paper_page(bs, ss, year, name):
    conn = connect()
    try:
        paper = catalog.find_paper(conn, bs, ss, str(year), name)
        if not paper:
            return None
        plist = [p for p in catalog.papers(conn) if (p["board_slug"], p["subject_slug"]) == (bs, ss) and p["path"]]
        members = pages._rows(conn, "SELECT q.id, q.type, q.content, m.printed_number FROM set_members m "
                              "JOIN questions q ON q.id = m.question_id AND q.status = 'published' "
                              "AND q.visibility = 'public' WHERE m.set_id = %s ORDER BY m.position, q.id",
                              (paper["id"],))
        per_chapter = {r["value"]: r["n"] for r in pages._rows(
            conn, "SELECT value, count(DISTINCT question_id) AS n FROM question_tags WHERE tag_key = 'chapter' "
                  "AND question_id = ANY(%s) GROUP BY value", ([m["id"] for m in members],))}
        chapter_paths = {c["chapter"]: c["path"] for c in catalog.chapters(conn)
                         if (c["board_slug"], c["subject_slug"]) == (bs, ss)}
    finally:
        conn.close()
    board, subject, year = paper["board"], paper["subject"], paper["year"]
    path = paper["path"]
    heading = f"{paper['label']}"
    subj_path = f"/{bs}/{ss}"
    crumbs = [("Prashnika", "/"), (f"{board} {subject}", subj_path), (year, f"{subj_path}/{year}"),
              (paper["label"], path)]
    tags = {"board": [board], "subject": [subject]}
    conn = connect()
    try:
        full = pages.full_questions(conn, members, {m["id"]: m["printed_number"] for m in members if m["printed_number"]},
                                    meta=("marks", "type"))
    finally:
        conn.close()
    acts = _btn(f"/?paper={paper['id']}&sort=paper", "Practise with filters", primary=True)
    chips = (f'<div class="tagchips">{_sub_chip(subject, ss)}<span class="tagchip">'
             f'{esc(_KIND_SHORT.get(paper["kind"], "Paper"))}</span><span class="tagchip">Class {esc(paper["cls"])}</span></div>')
    kpis = [(str(len(members)), "questions")]
    if paper["total_marks"]:
        kpis.append((str(paper["total_marks"]), "marks"))
    kpis.append((str(len(per_chapter)), "chapters"))
    hero = _hero(pages._crumbs([("Prashnika", "/"), (subject, subj_path), (year, f"{subj_path}/{year}"),
                                (paper["label"], None)]),
                 heading, _paper_intro(paper, len(members), {}, chapter_paths), kpis=kpis,
                 chips_html=chips, acts_html=acts, sub=ss)
    side = []
    if per_chapter:
        ranked = sorted(per_chapter.items(), key=lambda kv: (-kv[1], kv[0]))
        items = "".join(_li(chapter_paths[c], c, _count(k, "question")) if c in chapter_paths else
                        f'<span class="li">{esc(c)}<span>{_count(k, "question")}</span></span>' for c, k in ranked)
        side.append(_side("Chapters in this paper", items))
    others = [p for p in plist if p["year"] == year and p["id"] != paper["id"]]
    links = "".join(_li(p["path"], p["label"], _KIND_SHORT.get(p["kind"], "")) for p in others)
    links += (f'<a class="more-link" href="{esc(subj_path)}/{esc(year)}">All {esc(subject)} {esc(year)} papers &rarr;</a>'
              f'<a class="more-link" href="{esc(subj_path)}">All {esc(subject)} papers &rarr;</a>')
    side.append(_side(f"Other papers of {year}" if others else "More papers", links))
    main = f'<div class="sub-{esc(ss)}">{full}</div>'
    top = [c for c, _ in sorted(per_chapter.items(), key=lambda kv: -kv[1])[:4]]
    desc = (f"{paper['label']} (Class {paper['cls']}): all {len(members)} questions"
            + (f", {paper['total_marks']} marks" if paper["total_marks"] else "")
            + (f". Covers {', '.join(top)} and more" if len(per_chapter) > len(top) else
               f". Covers {', '.join(top)}" if top else "")
            + ".")[:300]
    ld = _graph("CollectionPage", heading, path, desc, crumbs,
                {"mainEntity": {"@type": "ItemList", "numberOfItems": len(members), "itemListElement": [
                    {"@type": "ListItem", "position": i + 1,
                     "url": f"{SITE_URL}{pages.question_path(m['id'], tags, m['content'] or {})}"}
                    for i, m in enumerate(members)]}})
    return Page(path=path, title=f"{paper['label']} (Class {paper['cls']}) | Prashnika",
                description=desc,
                body_html=hero + _page_layout(main, "".join(side)), heading=heading, og_type="website", nav="papers",
                own_h1=True, jsonld=ld)


# ---------------------------------------------------------------- a chapter

def chapter_pages(n):
    """How many pages a chapter of n questions takes."""
    return max(1, -(-n // CHAPTER_FULL_MAX))


def chapter_page(bs, ss, cs, page=1):
    conn = connect()
    try:
        subj = _subject_of(conn, bs, ss)
        chapters = [c for c in catalog.chapters(conn) if (c["board_slug"], c["subject_slug"]) == (bs, ss)]
        chapter = next((c for c in chapters if c["slug"] == cs), None)
        if not subj or not chapter or not 1 <= page <= chapter_pages(chapter["n"]):
            return None
        got = pages._rows(
            conn, "SELECT q.id, q.type, q.content, "
                  "(SELECT min(t.value) FROM question_tags t WHERE t.question_id = q.id AND t.tag_key = 'year') AS year, "
                  "(SELECT min(t.value) FROM question_tags t WHERE t.question_id = q.id AND t.tag_key = 'marks') AS marks "
                  "FROM questions q JOIN question_tags s ON s.question_id = q.id AND s.tag_key = 'subject' AND s.value = %s "
                  "JOIN question_tags c ON c.question_id = q.id AND c.tag_key = 'chapter' AND c.value = %s "
                  f"WHERE {catalog.PUBLISHED} AND NOT q.type = ANY(%s) ORDER BY 4 DESC NULLS LAST, q.id LIMIT %s",
            (subj["subject"], chapter["chapter"], list(catalog.NOINDEX_TYPES), CHAPTER_QUESTIONS_MAX))
    finally:
        conn.close()
    board, subject, name, base = subj["board"], subj["subject"], chapter["chapter"], chapter["path"]
    years = sorted({r["year"] for r in got if r["year"]})
    last = chapter_pages(len(got))
    page = min(page, last)
    path = base if page == 1 else f"{base}/page/{page}"
    lo, hi = (page - 1) * CHAPTER_FULL_MAX, page * CHAPTER_FULL_MAX
    here, rest = got[lo:hi], got[:lo] + got[hi:]
    of = f" (Page {page} of {last})" if last > 1 else ""
    heading = f"{name} - {board} Class 12 {subject} Questions" + (f", Page {page}" if page > 1 else "")
    crumbs = [("Prashnika", "/"), (f"{board} {subject}", subj["path"]), (name, base)] + ([(f"Page {page}", path)] if page > 1 else [])
    tags = {"board": [board], "subject": [subject]}
    # the questions in full, under a heading per year
    conn = connect()
    try:
        groups = []
        for y in dict.fromkeys(r["year"] for r in here):
            rows = [r for r in here if r["year"] == y]
            head = (f'<div class="yhead"><b>{esc(y)}</b><span>{_count(len(rows), "question")}</span></div>' if y else "")
            groups.append(head + pages.full_questions(conn, rows, meta=("marks", "type")))
    finally:
        conn.close()
    lis = []
    for r in rest:
        meta = " · ".join(x for x in (r["year"], pages._marks_text(r["marks"] or ""),
                                      pages.TYPE_LABEL.get(r["type"], r["type"])) if x)
        lis.append(f'<li class="pickrow"><a href="{esc(pages.question_path(r["id"], tags, r["content"] or {}))}">'
                   f'{esc(pages._snippet(_plain(r["content"]), 130))} <span class="muted">{esc(meta)}</span></a></li>')
    pager = _pager(base, page, last)
    shown = (f" Questions {lo + 1}-{lo + len(here)} are on this page, {CHAPTER_FULL_MAX} to a page."
             if last > 1 else "")
    intro = (f'<p>{_count(len(got), "past-paper question")} on {esc(name)} from {esc(board)} Class 12 {esc(subject)} '
             f'papers{" (" + _span(years) + ")" if years else ""}, newest first, in full.{shown}</p>')
    practise = f"/?subject={quote(subject)}&chapter={quote(name)}"
    acts = _btn(practise, "Practise this chapter", primary=True)
    chips = f'<div class="tagchips">{_sub_chip(subject, ss)}<span class="tagchip">Class 12</span></div>'
    hero = _hero(pages._crumbs([("Prashnika", "/"), (board, f"/{bs}"), (subject, subj["path"])] +
                               ([(name, base), (f"Page {page}", None)] if page > 1 else [(name, None)])),
                 heading, intro, chips_html=chips, acts_html=acts, sub=ss,
                 kpis=((str(len(got)), "questions"), (str(len(years)), "years"), (years[-1] if years else "-", "newest")))
    main = (pager + _search_box(".qfull, .chapter-more li", f"Search the questions on {name}", f"Search the questions on {name}") +
            f'<div class="sub-{esc(ss)}">{"".join(groups)}</div>' + pager +
            (f'<section data-filter-group><h2>{"Questions on other pages" if last > 1 else "More questions"} on {esc(name)}</h2>'
             f'<div class="related chapter-more"><ul>{"".join(lis)}</ul></div></section>' if lis else ""))
    side = []
    others = sorted((c for c in chapters if c["slug"] != cs), key=lambda c: -c["n"])
    if others:
        side.append(_side("Other chapters", "".join(_li(c["path"], c["chapter"], _count(c["n"], "question")) for c in others[:6]) +
                          f'<a class="more-link" href="{esc(subj["path"])}">All {esc(subject)} chapters &rarr;</a>'))
    desc = (f"{len(got)} {board} Class 12 {subject} questions on {name} from past papers"
            f"{' (' + _span(years) + ')' if years else ''}{of}.")[:300]
    return Page(path=path, title=f"{heading} | Prashnika", description=desc,
                body_html=hero + _page_layout(main, "".join(side)), heading=heading, og_type="website",
                nav="chapters", own_h1=True, jsonld=_graph("CollectionPage", heading, path, desc, crumbs))


def _pager(base, page, last):
    """Page links under and over a chapter's questions: Previous, 1 2 3 ..., Next. Nothing for a one-page chapter."""
    if last < 2:
        return ""
    href = lambda n: base if n == 1 else f"{base}/page/{n}"            # noqa: E731
    bits = [f'<a href="{esc(href(page - 1))}" rel="prev">&lsaquo; Previous</a>'] if page > 1 else []
    bits += [f'<span aria-current="page">{n}</span>' if n == page else f'<a href="{esc(href(n))}">{n}</a>'
             for n in range(1, last + 1)]
    bits += [f'<a href="{esc(href(page + 1))}" rel="next">Next &rsaquo;</a>'] if page < last else []
    return f'<nav class="pager" aria-label="Pages of this chapter">{"".join(bits)}</nav>'


# ---------------------------------------------------------------- the sitemap's share

def sitemap_urls():
    """[(path, YYYY-MM-DD)] for every hub: boards, subjects, years, papers and chapters."""
    conn = connect()
    try:
        subjects, plist, chapters = catalog.subjects(conn), catalog.papers(conn), catalog.chapters(conn)
    finally:
        conn.close()
    day = lambda ts: ts.date().isoformat()                         # noqa: E731
    out, boards, years = [], {}, {}
    if plist:
        out.append(("/papers", day(max(p["updated_at"] for p in plist))))
    if chapters:
        out.append(("/chapters", day(max(c["updated_at"] for c in chapters))))
    for s in subjects:
        out.append((s["path"], day(s["updated_at"])))
        boards[s["board_slug"]] = max(boards.get(s["board_slug"], s["updated_at"]), s["updated_at"])
    out += [(f"/{b}", day(ts)) for b, ts in boards.items()]
    for p in plist:
        if not p["path"]:
            continue
        out.append((p["path"], day(p["updated_at"])))
        key = f"/{p['board_slug']}/{p['subject_slug']}/{p['year']}"
        years[key] = max(years.get(key, p["updated_at"]), p["updated_at"])
    out += [(k, day(ts)) for k, ts in years.items()]
    for c in chapters:
        out += [(c["path"] if n == 1 else f"{c['path']}/page/{n}", day(c["updated_at"]))
                for n in range(1, chapter_pages(c["n"]) + 1)]
    return out
