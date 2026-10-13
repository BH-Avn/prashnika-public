"""Server-rendered pages.

`Page` and `render` know nothing about questions - they are the plumbing every page shares: a canonical URL, a
title and meta description, JSON-LD, and the one template. Question pages are `question_page`; `full_questions`
shows many questions in full on a paper or chapter page.

    from pages import question_page, render
    page = question_page("q-k7f2qab")     # None if not published/public
    html = render(page)
"""

import json
import os
import re
from datetime import date
import sys
from urllib.parse import urlencode
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

V2 = Path(__file__).resolve().parents[1]
if str(V2) not in sys.path:
    sys.path.insert(0, str(V2))
SITE_DIR = Path(__file__).resolve().parent
if str(SITE_DIR) not in sys.path:
    sys.path.insert(0, str(SITE_DIR))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from sitedb import connect  # noqa: E402  (pooled; site/sitedb.py)
from qh.text import slug  # noqa: E402
import assets  # noqa: E402  (site/assets.py: versioned /static/ links)
import catalog  # noqa: E402  (site/catalog.py: subjects, chapters, paper addresses)
import richtext  # noqa: E402

SITE_URL = os.environ.get("SITE_URL", "http://localhost:8141").rstrip("/")
TEMPLATES = SITE_DIR / "templates"
QID_RE = re.compile(r"^q-[a-z0-9]{7}$")
PUBLISHED = "status = 'published' AND visibility = 'public'"

_env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
_env.globals["asset"] = assets.url


@dataclass
class Page:
    """Enough to render one page: a canonical path, its <title>/<meta description>, ready HTML for the body,
    JSON-LD (or None), and a short heading for <h1> (falls back to title)."""
    path: str
    title: str
    description: str
    body_html: str
    jsonld: Optional[dict] = None
    heading: Optional[str] = None
    og_type: str = "article"
    nav: str = ""                          # which header link is lit: "questions", "papers", "subjects" or "chapters"
    back: Optional[tuple] = None           # (label, path): where "‹ Back" goes when there's no page to go back to
    kicker: str = ""                       # a short line above the <h1> (a single question's slot lead)
    robots: str = ""                       # a robots meta value, e.g. "noindex, follow" (a thin page)
    jsonld_more: tuple = ()                # further JSON-LD blocks (a BreadcrumbList), each its own <script>
    own_h1: bool = False                   # body_html holds the <h1> itself (inside a header card), the template adds none

    def __post_init__(self):
        if not self.heading:
            self.heading = self.title


def render(page: Page) -> str:
    """The one HTML template, for every page kind."""
    tmpl = _env.get_template("page.html")
    # </script> inside a JSON string would otherwise close the tag early.
    blocks = [json.dumps(b, ensure_ascii=False).replace("</", "<\\/")
              for b in ([page.jsonld] if page.jsonld else []) + list(page.jsonld_more)]
    return tmpl.render(page=page, site=SITE_URL, jsonld_blocks=blocks, maths=has_maths(page))


def has_maths(page):
    """Whether the page has $...$ maths for page.js to draw - only then does it load KaTeX (77 KB of script and a
    stylesheet the page waits for). Hubs, the solver and most Computer Science pages have none. A stray "$" just
    loads it as before."""
    return any("$" in (text or "") for text in (page.body_html, page.heading, page.kicker))


# ---------------------------------------------------------------- questions (the first page kind)

#
TYPE_LABEL = {  # matches site.js's TYPE_LABEL, so a page reads the same as the app
    "mcq": "MCQ", "assertion_reason": "Assertion-reason", "true_false": "True/false", "fill_blank": "Fill in", "one_word": "One word",
    "match": "Match", "numerical": "Numerical", "derivation": "Derivation", "drawing": "Drawing",
    "short": "Short answer", "long": "Long answer", "program": "Program", "passage": "Case based",
    "writing": "Writing", "complete": "Complete", "arrange": "Arrange", "rewrite": "Rewrite",
    "compare": "Differentiate", "list": "State points", "conversion": "Conversion", "identify": "Identify",
    "output": "Output", "transformation": "Transformation", "preposition": "Prepositions",
    "verb_form": "Correct verbs", "comprehension": "Comprehension", "truth_table": "Truth table", "kmap": "K-map",
    "lpp": "Linear programming", "distribution": "Probability distribution", "regression": "Regression",
    "tree": "Binary tree", "reaction": "Reaction", "graph": "Graph", "complex_ion": "Coordination complex",
}
KIND_WORDS = {"board_paper": "", "specimen": "Specimen", "improvement": "Improvement", "practice": "Practice",
              "school_paper": "School paper"}
RELATED_LIMIT = 8


def question_path(qid, tags, content):
    """The canonical /{board}/{subject}/{qid}/{slug} path for a question, from its (public) tags and content."""
    board_val = (tags.get("board") or [None])[0]
    subject_val = (tags.get("subject") or [None])[0]
    board = (slug(board_val) if board_val else "") or "isc"
    subject = (slug(subject_val) if subject_val else "") or "general"
    return f"/{board}/{subject}/{qid}/{slug(_plain_text(content))}"


def _paper_neighbours(conn, set_id, qid):
    """{"prev": {...}, "next": {...}}: the published questions either side of `qid` in its paper's printed order,
    each with its path and printed number."""
    order = _rows(conn, "SELECT q.id, q.content, m.printed_number FROM set_members m JOIN questions q ON q.id = "
                  "m.question_id AND q.status = 'published' AND q.visibility = 'public' WHERE m.set_id = %s "
                  "ORDER BY m.position, q.id", (set_id,))
    ids = [r["id"] for r in order]
    if qid not in ids:
        return {}
    i = ids.index(qid)
    out = {}
    for key, j in (("prev", i - 1), ("next", i + 1)):
        if 0 <= j < len(order):
            r = order[j]
            out[key] = {"path": question_path(r["id"], _all_tags(conn, r["id"]), r["content"] or {}),
                        "number": r["printed_number"], "text": _short_text(_plain_text(r["content"] or {}), 60)}
    return out


def _stepper_html(neighbours):
    """Previous / next question in the paper, as two real links."""
    if not neighbours:
        return ""
    cells = []
    for key, arrow_left, word in (("prev", True, "Previous"), ("next", False, "Next")):
        n = neighbours.get(key)
        if not n:
            cells.append('<span></span>')
            continue
        num = f'<span class="muted">Q{richtext.escape_html(n["number"])}</span>' if n.get("number") else ""
        label = f'‹ {word} question' if arrow_left else f'{word} question ›'
        cells.append(f'<a class="btn step-{key}" href="{richtext.escape_html(n["path"])}" rel="{key}">{label}</a>')
    return f'<nav class="stepper" aria-label="Questions in this paper">{"".join(cells)}</nav>'


# ---------------------------------------------------------------- single questions: slots and shared blocks
#
# Types whose questions are too small to be a search result of their own (a half-mark blank): their pages say
# noindex and stay out of the sitemap, but are still linked from their paper.
NOINDEX_TYPES = catalog.NOINDEX_TYPES


def _crumbs(items):
    """[(label, path or None)] as a breadcrumb line."""
    parts = [f'<a href="{richtext.escape_html(p)}">{richtext.escape_html(l)}</a>' if p else
             f'<span aria-current="page">{richtext.escape_html(l)}</span>' for l, p in items]
    return f'<nav class="crumbs" aria-label="Breadcrumb">{"<i>/</i>".join(parts)}</nav>'


def _breadcrumb_ld(items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": label, "item": f"{SITE_URL}{path}"}
        for i, (label, path) in enumerate(items)]}


# ---------------------------------------------------------------- db helpers

def _rows(conn, sql, args=()):
    cur = conn.cursor()
    cur.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def _all_tags(conn, qid):
    out = {}
    for r in _rows(conn, "SELECT tag_key, value FROM question_tags WHERE question_id = %s ORDER BY value", (qid,)):
        out.setdefault(r["tag_key"], []).append(r["value"])
    return out


def _related(conn, qid, chapters):
    """Up to 8 other published/public questions sharing a chapter tag - the links a crawler can walk the bank by.
    Each question gets its own 8 (a shuffle seeded by its id, the same on every visit): ordered by id, every
    question of a chapter linked the same 8 and the rest were never linked."""
    if not chapters:
        return []
    rel_rows = _rows(conn, "SELECT q2.id, q2.content FROM questions q2 WHERE q2.status = 'published' "
                     "AND q2.visibility = 'public' AND q2.id <> %s AND EXISTS (SELECT 1 FROM question_tags t2 "
                     "WHERE t2.question_id = q2.id AND t2.tag_key = 'chapter' AND t2.value = ANY(%s)) "
                     "ORDER BY md5(%s || q2.id) LIMIT %s", (qid, chapters, qid, RELATED_LIMIT))
    out = []
    for r in rel_rows:
        r_tags = _all_tags(conn, r["id"])
        out.append({"path": question_path(r["id"], r_tags, r["content"] or {}),
                    "text": _short_text(_plain_text(r["content"] or {}), 70)})
    return out


# ---------------------------------------------------------------- content -> HTML

def _plain_text(content):
    """Mirrors site.js's plainText(): every rich-text field, in reading order, maths and markup left as source."""
    pieces = [content.get("passage"), content.get("assertion"), content.get("text")]
    pieces += [p.get("text") for p in content.get("parts") or [] if isinstance(p, dict)]
    return "\n".join(p for p in pieces if p)


def _qtags_html(values):
    tags = [v for v in values if v]
    if not tags:
        return ""
    spans = "".join(f'<span class="qtag">{richtext.escape_html(t)}</span>' for t in tags)
    return f'<div class="qtags">{spans}</div>'


def _marks_text(marks):
    if not marks:
        return ""
    return f"{marks} mark{'' if str(marks) == '1' else 's'}"


def _option_list(items, correct=None, part=""):
    if not items:
        return ""
    correct = set(correct or [])
    lis = []
    for o in items:
        #
        cls = ' class="correct"' if o.get("label") in correct else ""
        lis.append(f'<li{cls} data-opt="{richtext.escape_html(o.get("label", ""))}"><b>{richtext.escape_html(o.get("label", ""))}</b>'
                   f'<span class="otext">{richtext.render_text(o.get("text", ""))}</span></li>')
    return f'<ul class="opts" data-part="{richtext.escape_html(part)}">{"".join(lis)}</ul>'


def _fields_html(c, head=False, skip_text=False, part=""):
    """A content object's own fields (not its parts or passage) - the same rendering for a whole question and for
    one of its parts, as the design requires. `skip_text` omits the leading `text` paragraph when it's already
    shown verbatim as the page's <h1> (see `_redundant`) - only the top-level call ever passes it."""
    out = []
    #
    if c.get("assertion"):
        out.append(f'<p class="qtext"><b>Assertion:</b> {richtext.render_text(c["assertion"])}</p>')
        out.append(f'<p class="qtext"><b>Reason:</b> {richtext.render_text(c.get("reason", ""))}</p>')
    if c.get("text") and not skip_text:
        out.append(f'<div class="{"qhead" if head else "qtext"}">{richtext.render_text(c["text"])}</div>')
    if c.get("start"):
        out.append(f'<p class="qtext"><b>Given:</b> {richtext.render_text(c["start"])}</p>')
    if c.get("target"):
        out.append(f'<p class="qtext"><b>To show:</b> {richtext.render_text(c["target"])}</p>')
    if c.get("draw"):
        out.append(f'<p class="qtext"><b>Draw:</b> {richtext.render_text(c["draw"])}</p>')
    #
    if c.get("must_show"):
        out.append(f'<p class="qtext"><b>Must show:</b> {richtext.escape_html(", ".join(c["must_show"]))}</p>')
    out.append(_option_list(c.get("options"), part=part))
    #
    if c.get("column_a"):
        out.append(f'<div class="cols"><div><b>Column A</b>{_option_list(c["column_a"])}</div>'
                   f'<div><b>Column B</b>{_option_list(c.get("column_b"))}</div></div>')
    #
    if c.get("sample_io"):
        out.append(f'<p><b>Sample input/output</b></p><div class="qtext">'
                   f'{richtext.render_text("```\n" + c["sample_io"] + "\n```")}</div>')
    #
    if c.get("word_limit"):
        out.append(f'<p class="muted">Word limit: {richtext.escape_html(c["word_limit"])}</p>')
    return "".join(out)


def _paper_title(title, kind, tags):
    if title:
        return title
    one = lambda k: (tags.get(k) or [""])[0]  # noqa: E731
    bits = [one("board"), one("year"), KIND_WORDS.get(kind, ""), one("subject"),
            f"Paper {one('paper_number')}" if one("paper_number") else ""]
    return " ".join(b for b in bits if b) or "Paper"


# ---------------------------------------------------------------- SEO text

_FENCE_MARK = re.compile(r"```[A-Za-z0-9_+#-]*")


#
def _plain_line(line):
    """A table row's cells as words ("| a | b |" -> "a b"; a | --- | row -> nothing); any other line as it is."""
    if not re.match(r"^\s*\|.*\|\s*$", line):
        return line
    return " ".join(c for c in (c.strip() for c in line.strip().strip("|").split("|")) if not re.fullmatch(r":?-{3,}:?", c))


def _maths_span_text(m):
    """One $...$ span as plain characters; a matrix or other layout can't be said and is dropped."""
    inner = m.group(0)[1:-1]
    if not inner.strip() or re.search(r"\\begin|&|\\\\", inner):
        return " "
    inner = re.sub(r"\\(?:frac)\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", inner)
    inner = re.sub(r"\\([A-Za-z]+)", r"\1", inner)
    return re.sub(r"[{}]", "", inner)


#
def _maths_as_text(text):
    """`text` with its $...$ maths written as plain characters, for a <title>, <h1> or description that can't draw
    it: \\alpha -> alpha, x^2 -> x^2, a layout it can't say (a matrix) is dropped."""
    return richtext._MATH_SPAN.sub(_maths_span_text, text or "")


#
def _clean(text):
    """`text` as plain words for the <h1>, <title> and description: maths written as plain characters (α, x², 1/2;
    since 2026-10-09, it was dropped and left holes), and code fences (```java) and table pipes dropped - they are
    markup, and showed up raw in the headings of questions with code (2026-09-23)."""
    t = _FENCE_MARK.sub(" ", richtext.UNDERLINE_TAG.sub("", _maths_as_text(text)))
    t = richtext.INLINE_CODE.sub(r"\1", t)                  # `magicfun()` -> magicfun()
    t = "\n".join(_plain_line(line) for line in t.split("\n"))
    return re.sub(r"\s+", " ", t).strip()


_TRAILING_PUNCT = re.compile(r"[\s,.;:!?]+$")


def _for_compare(text):
    """`text`, cleaned and with trailing punctuation dropped, for a whitespace/punctuation-insensitive equality
    check (not for display)."""
    return _TRAILING_PUNCT.sub("", _clean(text)).lower()


def _redundant(text, heading):
    """True when `text` is the same sentence as `heading` (the <h1>) once whitespace, maths and trailing
    punctuation are normalised - i.e. showing `text` again in the body would just repeat the heading. A heading
    that was truncated ends in "…" and so never matches a real `text`, which is how a long question keeps its
    full body text. Text with maths in it is never redundant: the heading has its maths stripped, so hiding the
    body would lose the equation (2026-09-22: "the Boolean equation will be equivalent to:")."""
    if richtext.strip_maths(text) != (text or "") or richtext.UNDERLINE_TAG.search(text or ""):
        return False            # the heading lost the maths or the underline: the body must still show them
    return _for_compare(text) == _for_compare(heading)


#
def _snippet(plain, limit):
    """A question's opening words for a list, with its $...$ maths kept (page.js renders it) - never cut inside a
    formula. Code blocks and table pipes are dropped, like _clean."""
    t = re.sub(r"```.*?(```|$)", " … ", richtext.UNDERLINE_TAG.sub("", plain), flags=re.S)
    t = richtext.INLINE_CODE.sub(r"\1", t)
    t = "\n".join(_plain_line(line) for line in t.split("\n"))
    t = re.sub(r"\s+", " ", re.sub(r"(?<![\w$*])\*(\S(?:[^*]*?\S)?)\*(?!\w)", r"\1", t)).strip()
    if len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0] or t[:limit]
        if cut.count("$") % 2:                      # inside a formula: stop before it
            cut = cut[:cut.rfind("$")]
        t = cut.rstrip(" ,.;:") + "…"
    return t or "Question"


def _short_text(plain, limit):
    t = _clean(plain)
    if len(t) > limit:
        t = (t[:limit].rsplit(" ", 1)[0] or t[:limit]).rstrip(",.;:") + "…"
    return t or "Question"


def _title_words(plain, limit):
    """The question's opening words for a <title>: cut at a word, and no "…" - a title that ends in an ellipsis
    spends keyword space on nothing (Google adds its own when it shortens one)."""
    t = _clean(plain)
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] or t[:limit]
        for open_, close in ("[]", "()", "{}"):         # never end inside a bracket ("... from the bracket [first")
            if t.count(open_) > t.count(close):
                t = t[:t.rfind(open_)]
        t = t.rstrip(" ,.;:-")
    return t or "Question"


SHORT_OPENING = 40      # an opening this short ("Evaluate", "Fill in the blanks") says nothing alone: add the marks


def _where(board="", cls="", subject="", year="", number=""):
    """`ISC Class 12 Computer Science 2017 Q5(c)`: the words students search for, in the order they type them."""
    where = " ".join(b for b in (board, f"Class {cls}" if cls and board else "", subject, year) if b)
    return f"{where} Q{number}".strip() if number else where


def _seo_title(plain, board="", subject="", year="", marks="", chapter="", number="", cls="", search_title=""):
    """`<opening> - <Chapter> | ISC Class 12 Chemistry 2024 Q3`: the question's opening words, then where it is from.
    A short, generic opening also names its marks, so two "Evaluate" questions don't share a title. A question's
    own `search_title` (the short name a person or AI gave it) replaces the opening."""
    where = _where(board, cls, subject, year, number)
    if search_title:
        return f"{search_title} | {where}" if where else search_title
    opening = _title_words(plain, 55)
    if chapter and chapter.split(" - ")[0].lower() not in opening.lower():
        opening = f"{opening} - {chapter}"
    if len(_title_words(plain, 55)) < SHORT_OPENING and marks:
        opening = f"{opening} ({_marks_text(marks)})"
    return f"{opening} | {where}" if where else opening


def _seo_description(plain, board="", subject="", year="", marks="", chapter="", number="", cls=""):
    """The question's words first (what a search matches), then where it's from:
    `<question>. ISC Class 12 Physics 2024 Q5, Electrostatics, 4 marks: past paper question.`"""
    facts = ", ".join(b for b in (_where(board, cls, subject, year, number), chapter, _marks_text(marks)) if b)
    tail = f"{facts}: past paper question." if facts else ""
    room = max(100, 158 - len(tail) - 2)          # the question's own words get at least 100 characters
    text = _short_text(plain, room).rstrip(" :;,")
    if not tail:
        return text
    return f"{text}{'' if text.endswith(('.', '?', '…', '!')) else '.'} {tail}"


def _jsonld(name, description, path):
    """schema.org markup for a question page: `name` is the plain question text (the <h1>)."""
    return {
        "@context": "https://schema.org",
        "@type": "LearningResource",
        "name": name,
        "description": description,
        "url": f"{SITE_URL}{path}",
        "learningResourceType": "Practice question",
    }


# ---------------------------------------------------------------- questions

def _question_body(content, skip_text=False, head=False):
    """A question's passage, its own fields and its parts, as HTML. The same for a page and for a paper's list."""
    esc = richtext.escape_html
    body = []
    if content.get("passage"):
        body.append(f'<div class="passage">{richtext.render_text(content["passage"])}</div>')
    body.append(_fields_html(content, head=head, skip_text=skip_text))
    for part in content.get("parts") or []:
        marks_tag = f'<span class="muted">[{esc(part["marks"])}]</span>' if part.get("marks") else ""
        body.append(f'<div class="part"><div><span class="part-label">{esc(part.get("label", ""))}'
                    f'</span>{marks_tag}</div>{_fields_html(part, part=part.get("label") or "")}</div>')
    return "".join(body)


def question_page(qid) -> Optional[Page]:
    """The Page for one question, or None when it isn't published and public (or qid is malformed)."""
    if not QID_RE.match(qid or ""):
        return None
    conn = connect()
    try:
        got = _rows(conn, f"SELECT id, type, content, search_title FROM questions WHERE id = %s AND {PUBLISHED}", (qid,))
        if not got:
            return None
        q = got[0]
        content = q["content"] or {}
        tags = _all_tags(conn, qid)
        paper_rows = _rows(conn, "SELECT s.id AS set_id, s.title, s.kind, m.printed_number FROM set_members m "
                           "JOIN sets s ON s.id = m.set_id AND s.status = 'published' AND s.visibility = 'public' "
                           "WHERE m.question_id = %s ORDER BY s.id LIMIT 1", (qid,))
        paper_tags, neighbours, paper_href = {}, {}, ""
        if paper_rows:
            paper_href = catalog.paper_path(conn, paper_rows[0]["set_id"]) or f"/?paper={paper_rows[0]['set_id']}"
            for r in _rows(conn, "SELECT tag_key, value FROM set_tags WHERE set_id = %s", (paper_rows[0]["set_id"],)):
                paper_tags.setdefault(r["tag_key"], []).append(r["value"])
            neighbours = _paper_neighbours(conn, paper_rows[0]["set_id"], qid)
        related = _related(conn, qid, tags.get("chapter") or [])
    finally:
        conn.close()

    subject = (tags.get("subject") or [""])[0]
    year = (tags.get("year") or [""])[0]
    marks = (tags.get("marks") or [""])[0]
    chapters = tags.get("chapter") or []
    plain = _plain_text(content)
    path = question_path(qid, tags, content)
    heading = _short_text(plain, 100)
    # when the leading `text` IS the heading, showing it again as the first paragraph would only repeat it
    skip_text = bool(content.get("text")) and _redundant(content["text"], heading)

    board = (tags.get("board") or [""])[0]
    trail = [("Home", "/")]
    bs = ss = ""
    if subject:
        bs, ss = catalog.board_slug(board), catalog.subject_slug(subject)
        trail.append((f"{board or 'ISC'} {subject}".strip(), f"/{bs}/{ss}"))
        if chapters:
            trail.append((chapters[0], f"/{bs}/{ss}/chapter/{catalog.chapter_slug(chapters[0])}"))
    esc = richtext.escape_html
    h1_hidden = not skip_text and not heading.endswith("…") and bool(content.get("text"))
    chips = []
    if subject:
        chips.append(f'<span class="tagchip sub-{esc(ss)}"><span class="dot"></span>{esc(subject)}</span>')
    chips += [f'<span class="tagchip">{esc(x)}</span>' for x in (year, _marks_text(marks), TYPE_LABEL.get(q["type"], q["type"])) if x]
    if chapters and subject:
        chips += [f'<a class="tagchip" href="/{bs}/{ss}/chapter/{esc(catalog.chapter_slug(c))}">{esc(c)}</a>' for c in chapters]
    card = [f'<div class="tagchips">{"".join(chips)}</div>' if chips else "",
            f'<h1{" class=sr" if h1_hidden else ""}>{esc(heading)}</h1>',
            _question_body(content, skip_text=skip_text, head=True)]
    body = [_crumbs(trail) if len(trail) > 1 else "",
            f'<section class="q-card{" q-big" if h1_hidden else ""}">{"".join(card)}</section>']
    back = ("All questions", "/?view=questions")
    side = []
    if paper_rows:
        p = paper_rows[0]
        title = _paper_title(p["title"], p["kind"], paper_tags)
        back = ("Back to the paper", paper_href)
        items = []
        if neighbours.get("prev"):
            n = neighbours["prev"]
            items.append(f'<a class="li" href="{esc(n["path"])}">Question {esc(n["number"] or "")}<span>{esc(n["text"])}</span></a>')
        items.append(f'<a class="li on" href="{esc(path)}" aria-current="page">Question {esc(p.get("printed_number") or "")}'
                     f'<span>You are here</span></a>')
        if neighbours.get("next"):
            n = neighbours["next"]
            items.append(f'<a class="li" href="{esc(n["path"])}">Question {esc(n["number"] or "")}<span>{esc(n["text"])}</span></a>')
        side.append(f'<section class="sidecard"><h2>In this paper</h2>{"".join(items)}'
                    f'<a class="more-link" href="{esc(paper_href)}">{esc(title)} &rarr;</a></section>')
    if related:
        items = "".join(f'<a class="li" href="{esc(r["path"])}">{esc(r["text"])}</a>' for r in related)
        side.append(f'<section class="sidecard"><h2>More from this chapter</h2>{items}</section>')

    where = dict(board=board, subject=subject, year=year, marks=marks, chapter=chapters[0] if chapters else "",
                 number=(paper_rows[0].get("printed_number") or "") if paper_rows else "",
                 cls=(paper_tags.get("class") or tags.get("class") or ["12" if paper_rows else ""])[0])
    title = _seo_title(plain, **where, search_title=q.get("search_title") or "")
    description = _seo_description(plain, **where)
    jsonld = _jsonld(heading, _short_text(plain, 155), path)
    more = (({"@context": "https://schema.org", **_breadcrumb_ld(trail + [(heading, path)])},)
            if len(trail) > 1 else ())
    body.append(f'<div class="q-foot">{_stepper_html(neighbours)}</div>')
    if side:
        body = body[:1] + ['<div class="qgrid"><div class="qmain">'] + body[1:] + \
            ['</div><aside class="qside" aria-label="More to practise">'] + side + ['</aside></div>']
    return Page(path=path, title=title, description=description, body_html="".join(body), jsonld=jsonld,
                jsonld_more=more, heading=heading, nav="questions", back=back, own_h1=True,
                robots="noindex, follow" if q["type"] in NOINDEX_TYPES else "")


def full_questions(conn, rows, numbers=None, meta=("year", "marks", "type")):
    """Published questions shown in full, one after another, for a paper's or a chapter's own page: the number, marks
    and type, then the question. rows: [{id, type, content}] in the order to show; numbers: {qid: printed number}."""
    ids = [r["id"] for r in rows]
    if not ids:
        return ""
    numbers = numbers or {}
    esc = richtext.escape_html
    tag_of = {}
    for r in _rows(conn, "SELECT question_id, tag_key, value FROM question_tags WHERE question_id = ANY(%s) "
                         "AND tag_key IN ('board', 'subject', 'year', 'marks') ORDER BY value", (ids,)):
        tag_of.setdefault(r["question_id"], {}).setdefault(r["tag_key"], []).append(r["value"])
    out = []
    for q in rows:
        qid = q["id"]
        content = q["content"] or {}
        tags = tag_of.get(qid, {})
        path = question_path(qid, tags, content)
        facts = []
        if "year" in meta and tags.get("year"):
            facts.append(tags["year"][0])
        if "marks" in meta and tags.get("marks"):
            facts.append(_marks_text(tags["marks"][0]))
        if "type" in meta:
            facts.append(TYPE_LABEL.get(q["type"], q["type"]))
        num = numbers.get(qid)
        num_html = f'<span class="qf-num">Q{esc(num)}</span>' if num else ""
        head = (f'<header class="qf-head">{num_html}'
                f'<span class="qf-meta">{esc(" · ".join(f for f in facts if f))}</span>'
                f'<a class="qf-open" href="{esc(path)}" title="Open this question on its own page">Open'
                f'<span class="sr">: {esc(_short_text(_plain_text(content), 80))}</span></a></header>')
        out.append(f'<article class="qfull" id="{esc(qid)}">{head}<div class="qf-body">{_question_body(content)}</div></article>')
    return f'<div class="qfull-list" data-maths>{"".join(out)}</div>'
