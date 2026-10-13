#!/usr/bin/env python3
"""The public site: a question list you can filter and sort, plus a page for every question, paper, year, subject
and chapter. It only reads.

    python site/app.py                        # http://127.0.0.1:8141

Only questions with status 'published' and visibility 'public' are ever read, with their public tags. The filters
come from tag_defs rows marked public + filterable, so a new filterable tag needs no code here - plus one virtual
filter not backed by a tag ("type", the questions.type column).

    GET /api/filters?<filters>            each filter's values with counts (counted under the other filters)
    GET /api/questions?<filters>&q=&sort=&page=&per=  20 per page (per=10: phones); sort = year_desc | year_asc | paper
    GET /api/questions/{id}?<filters>&q=&sort=      one question in full, with the previous/next in that list
    GET /api/papers                        published papers
    GET /api/questions?<filters>&ids=1     just the matching ids, in order

<filters> are tag keys as query parameters, repeatable for several values: ?subject=Physics&year=2024&year=2023,
plus paper=<set_id> for one paper's questions.

Each question also has a real, server-rendered page (pages.py + templates/page.html), so it can be indexed:
GET /{board}/{subject}/{qid}/{slug} (canonical - only `qid` is authoritative; a wrong board, subject or slug 301s
to the canonical one).

Hub pages (hubs.py, catalog.py): GET /chapters, GET /papers, /{board}, /{board}/{subject}, /{board}/{subject}/{year},
/{board}/{subject}/{year}/{kind} (a paper's own address, e.g. /isc/physics/2024/board-paper) and
/{board}/{subject}/chapter/{chapter}. The bare homepage carries their text.
"""

import argparse
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))     # the repo root, for qh/
sys.path.insert(0, str(HERE))            # this directory, for pages.py/hubs.py (module names, not a "site" package -
                                         # that would shadow the stdlib module of the same name)

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from sitedb import connect  # noqa: E402  (pooled)

import assets  # noqa: E402
import catalog  # noqa: E402
import hubs  # noqa: E402
import pages  # noqa: E402

STATIC = HERE / "static"
PAGE_SIZES = (20, 10)                                   # 20, or 10 on phones (site.js maps page numbers between them)
SORTS = ("year_desc", "year_asc", "paper")
MAX_QUERY = 200
PUBLISHED = "q.status = 'published' AND q.visibility = 'public'"

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class HeadAsGet:
    """A HEAD request (link checkers, uptime monitors, some crawlers and link previews) is answered like the GET it
    stands for, headers only: FastAPI's routes answer every HEAD with 405 otherwise."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "HEAD":
            return await self.inner(scope, receive, send)

        async def headers_only(message):
            if message["type"] == "http.response.body":
                if not message.get("more_body"):
                    await send({"type": "http.response.body", "body": b""})
                return
            await send(message)
        await self.inner(dict(scope, method="GET"), receive, headers_only)


app.add_middleware(HeadAsGet)


@app.middleware("http")
async def drop_trailing_slash(request: Request, call_next):
    """"/isc/physics/" moves for good (301) to "/isc/physics": FastAPI's own redirect is a 307, which tells Google
    the slashed address is still the real one."""
    path = request.url.path
    if len(path) > 1 and path.endswith("/") and request.method in ("GET", "HEAD"):
        query = request.url.query
        return RedirectResponse("/" + path.strip("/") + ("?" + query if query else ""), status_code=301)   # one leading /: "//x.com/" must stay on this site
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    """A page that isn't there gets a real page (the site's menu, a search box prefilled with the address's words,
    the main links), not bare JSON. The API and files keep the JSON reply their scripts read."""
    path = request.url.path
    if exc.status_code != 404 or path.startswith(("/api/", "/static/")) or re.search(r"\.\w{2,4}$", path):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    words = " ".join(w for w in re.split(r"[^a-z0-9]+", re.sub(r"q-[a-z0-9]{7}", " ", path.lower()))
                     if w and w not in ("isc", "chapter", "page"))[:80]
    esc = pages.richtext.escape_html
    body = (pages._crumbs([("Home", "/"), ("Not found", None)]) +
            "<p>There's no page at this address. It may have moved, or the link may be mistyped. "
            "Search every question instead:</p>"
            '<form class="filterbox" role="search" action="/" method="get">'
            f'<input type="search" name="q" value="{esc(words)}" placeholder="Search questions" '
            'aria-label="Search every question"><button class="btn primary" type="submit">Search</button></form>'
            '<p><a href="/papers">Every paper</a> &middot; <a href="/chapters">Every chapter</a> &middot; '
            '<a href="/">Home</a></p>')
    page = pages.Page(path=path, title="Page not found", description="This page isn't here.",
                      body_html=body, heading="Page not found", og_type="website", robots="noindex, follow")
    return HTMLResponse(pages.render(page), status_code=404, headers={"Cache-Control": "no-cache"})


def rows(sql, args=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# One filter not backed by tag_defs: "type" is a column on questions. Spliced into filter_defs() next to the tag it
# belongs near (marks).
VIRTUAL_FILTERS = {
    "type": {"label": "Question type", "kind": "one", "on_question": True},
}


def filter_defs():
    """The public, filterable tags, plus the virtual filter above: key -> {label, kind, on_question}."""
    defs = {}
    for r in rows("SELECT key, label, kind, applies_to FROM tag_defs WHERE public AND filterable "
                  "ORDER BY position, key"):
        defs[r["key"]] = {"label": r["label"], "kind": r["kind"], "on_question": "question" in r["applies_to"]}
        if r["key"] == "marks":
            defs["type"] = VIRTUAL_FILTERS["type"]
    return defs


def read_filters(request, defs):
    """{tag key: [values]} from the query string, only for known filters; plus the paper (set id) if given."""
    chosen = {}
    for key in defs:
        values = [v.strip()[:MAX_QUERY] for v in request.query_params.getlist(key) if v.strip()][:50]
        if values:
            chosen[key] = values
    return chosen, request.query_params.get("paper", "").strip()[:20]


# Search the question's words only: its text fields' values, not the stored JSON, whose field names ("text", "label",
# "type"...) would match nearly every question, and whose escaping (\frac stored as \\frac) would hide maths and quotes.
TEXT_MATCH = """EXISTS (SELECT 1 FROM jsonb_path_query(q.content, 'strict $.** ? (@.type() == "object")') o,
                     jsonb_each(o) kv
               WHERE kv.key NOT IN ('type', 'label', 'marks', 'word_limit')
                 AND (CASE WHEN jsonb_typeof(kv.value) = 'string' THEN kv.value #>> '{}'
                           WHEN kv.key = 'must_show' THEN kv.value::text END) ILIKE %s)"""


def text_like(text):
    """A word as an ILIKE pattern; an apostrophe or quote matches any ("kirchhoff's" typed on a phone finds
    "Kirchhoff’s")."""
    t = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + re.sub(r"['‘’`\"“”]", "_", t) + "%"


def search_text(request):
    """The ?q= search as typed, without the invisible characters a copy from a PDF or chat carries (zero-width
    spaces, soft hyphens, byte-order marks) and with full-width letters made plain (NFKC)."""
    text = unicodedata.normalize("NFKC", request.query_params.get("q", ""))
    return re.sub(r"[­​-‏⁠﻿]", "", text).strip()[:MAX_QUERY]


SEARCH_WORDS = 6


def singular(word):
    """A plural search word cut back so it finds the singular too (each word matches anywhere, so "capacitor" still
    finds "capacitors"). Words under 5 letters and -ss/-us/-is/-ics endings stay as typed. Mirrored in
    rich-text.js searchPattern, so the highlight lights what was found."""
    w = word.lower()
    if len(w) < 5 or not w.isalpha() or w.endswith(("ss", "us", "is", "ics")) or w in ("series", "species"):
        return word
    if w.endswith("ies") and len(w) > 4:
        return word[:-3]
    if w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if w.endswith("s"):
        return word[:-1]
    return word


def search_words(text):
    """The search as words, each found anywhere in the question ("ohm's law", "parts integration"), not only the
    exact phrase; plurals as their singular (`singular`)."""
    return list(dict.fromkeys(singular(w) for w in text.split()))[:SEARCH_WORDS]


def text_conds(text):
    """(SQL conditions, arguments): TEXT_MATCH once per word."""
    words = search_words(text)
    return [TEXT_MATCH] * len(words), [text_like(w) for w in words]


def text_matches(text):
    """The published questions whose words contain `text`: TEXT_MATCH run once per word, for a caller that would
    otherwise repeat it in many queries (/api/filters counts each filter separately)."""
    conds, args = text_conds(text)
    return [r["id"] for r in rows(f"SELECT q.id FROM questions q WHERE {' AND '.join([PUBLISHED] + conds)}", args)]


def where(defs, chosen, paper, text, skip=None, matched=None):
    """SQL conditions (on questions q) and their arguments for these filters; `skip` leaves one filter out.
    `matched`: text_matches(text) already worked out, used in place of the text search."""
    conds, args = [PUBLISHED], []
    for key, values in chosen.items():
        if key == skip:
            continue
        if key == "type":                               # a column, not a tag
            conds.append("q.type = ANY(%s)")
            args.append(values)
        elif defs[key]["on_question"]:
            conds.append("EXISTS (SELECT 1 FROM question_tags t WHERE t.question_id = q.id AND t.tag_key = %s "
                         "AND t.value = ANY(%s))")
            args += [key, values]
        else:                                           # a set-only tag (e.g. paper number): through published sets
            conds.append("EXISTS (SELECT 1 FROM set_members m JOIN sets s ON s.id = m.set_id AND s.status = 'published' "
                         "JOIN set_tags t ON t.set_id = s.id WHERE m.question_id = q.id AND t.tag_key = %s "
                         "AND t.value = ANY(%s))")
            args += [key, values]
    if paper:
        conds.append("EXISTS (SELECT 1 FROM set_members m JOIN sets s ON s.id = m.set_id AND s.status = 'published' "
                     "WHERE m.question_id = q.id AND m.set_id = %s)")
        args.append(paper)
    if matched is not None:
        conds.append("q.id = ANY(%s)")
        args.append(matched)
    elif text:
        more, more_args = text_conds(text)
        conds += more
        args += more_args
    return " AND ".join(conds), args


# The question's year and its place in its (first published) paper, for sorting. Worked out for all questions at
# once and joined (hash joins), not looked up question by question (a per-row subquery each is ten times slower).
ORDER_COLUMNS = "yt.yr, st.subj, pm.set_id AS paper_id, pm.position AS pos, pm.printed_number"
PAPER_JOIN = """
    LEFT JOIN (SELECT DISTINCT ON (m.question_id) m.question_id, m.set_id, m.position, m.printed_number
               FROM set_members m JOIN sets s ON s.id = m.set_id AND s.status = 'published'
               ORDER BY m.question_id, m.set_id) pm ON pm.question_id = q.id
    LEFT JOIN (SELECT question_id, max(CASE WHEN value ~ '^[0-9]+$' THEN value::int END) AS yr FROM question_tags
               WHERE tag_key = 'year' GROUP BY question_id) yt ON yt.question_id = q.id
    LEFT JOIN (SELECT question_id, min(value) AS subj FROM question_tags
               WHERE tag_key = 'subject' GROUP BY question_id) st ON st.question_id = q.id"""
ORDER_BY = {
    "year_desc": "yr DESC NULLS LAST, subj, paper_id, pos, q.id",
    "year_asc": "yr ASC NULLS LAST, subj, paper_id, pos, q.id",
    "paper": "paper_id NULLS LAST, pos, q.id",
}


def list_query(request):
    defs = filter_defs()
    chosen, paper = read_filters(request, defs)
    text = search_text(request)
    sort = request.query_params.get("sort", "")
    if sort not in SORTS:
        sort = "paper" if paper else "year_desc"
    cond, args = where(defs, chosen, paper, text)
    return f"SELECT q.id, {ORDER_COLUMNS} FROM questions q {PAPER_JOIN} WHERE {cond} ORDER BY {ORDER_BY[sort]}", args


def standin_units():
    """Units that only repeat their one chapter's name. A unit without sub-units holds a chapter of its own name;
    showing it as a unit as well just says the chapter twice."""
    return {r["parent"] for r in rows("SELECT parent FROM tag_values WHERE tag_key = 'chapter' AND parent IS NOT NULL "
                                      "AND NOT retired GROUP BY parent HAVING bool_and(value = parent)")}


def public_tags(qids):
    """{question id: {tag key: [values]}} for public tags. A stand-in unit (standin_units) is left out."""
    out = {qid: {} for qid in qids}
    if not qids:
        return out
    standin = standin_units()
    for r in rows("SELECT t.question_id, t.tag_key, t.value FROM question_tags t JOIN tag_defs d ON d.key = t.tag_key "
                  "AND d.public WHERE t.question_id = ANY(%s) ORDER BY d.position, t.value", (qids,)):
        if r["tag_key"] == "unit" and r["value"] in standin:
            continue
        out[r["question_id"]].setdefault(r["tag_key"], []).append(r["value"])
    return out


def papers_of(qids):
    """{question id: [{set_id, title, printed_number, url}]} over published papers."""
    out = {qid: [] for qid in qids}
    if not qids:
        return out
    members = rows("SELECT m.question_id, m.set_id, m.printed_number, s.title, s.kind FROM set_members m "
                   "JOIN sets s ON s.id = m.set_id AND s.status = 'published' AND s.visibility = 'public' "
                   "WHERE m.question_id = ANY(%s) ORDER BY m.set_id", (qids,))
    set_tags = {}
    for r in rows("SELECT t.set_id, t.tag_key, t.value FROM set_tags t JOIN tag_defs d ON d.key = t.tag_key AND d.public "
                  "WHERE t.set_id = ANY(%s)", (list({m["set_id"] for m in members}),)):
        set_tags.setdefault(r["set_id"], {}).setdefault(r["tag_key"], []).append(r["value"])
    urls = _paper_urls()
    for m in members:
        out[m["question_id"]].append({"set_id": m["set_id"], "printed_number": m["printed_number"], "url": urls.get(m["set_id"]),
                                      "title": pages._paper_title(m["title"], m["kind"], set_tags.get(m["set_id"], {}))})
    return out


def _paper_urls():
    """{set id: the paper's own address} for the papers that have one (catalog.py)."""
    conn = connect()
    try:
        return {p["id"]: p["path"] for p in catalog.papers(conn) if p["path"]}
    finally:
        conn.close()


def card(q, tags, papers):
    return {"id": q["id"], "type": q["type"], "content": q["content"], "tags": tags, "papers": papers,
            "answered": False, "has_figure": False, "lead": "",
            "url": pages.question_path(q["id"], tags, q["content"])}


def fetch_cards(qids):
    if not qids:
        return []
    got = {r["id"]: r for r in rows(
        f"SELECT q.id, q.type, q.content FROM questions q WHERE q.id = ANY(%s) AND {PUBLISHED}", (qids,))}
    tags, papers = public_tags(qids), papers_of(qids)
    return [card(got[i], tags[i], papers[i]) for i in qids if i in got]


def cached(data, seconds=60):
    return JSONResponse(data, headers={"Cache-Control": f"public, max-age={seconds}"})


# ---------------------------------------------------------------- API

@app.get("/api/filters")
def filters(request: Request):
    defs = filter_defs()
    chosen, paper = read_filters(request, defs)
    text = search_text(request)
    labels = {(r["tag_key"], r["value"]): r["label"] for r in rows(
        "SELECT DISTINCT ON (tag_key, value) tag_key, value, label FROM tag_values WHERE label <> ''")}
    out = []
    standin = standin_units()
    matched = text_matches(text) if text else None      # the slow text search once, not once per filter
    for key, d in defs.items():
        cond, args = where(defs, chosen, paper, text, skip=key, matched=matched)
        if key == "type":
            sql = f"SELECT q.type AS value, count(*) AS n FROM questions q WHERE {cond} GROUP BY q.type"
            values = rows(sql, args)
        elif d["on_question"]:
            sql = (f"SELECT t.value, count(*) AS n FROM questions q JOIN question_tags t ON t.question_id = q.id "
                   f"AND t.tag_key = %s WHERE {cond} GROUP BY t.value")
            values = rows(sql, [key] + args)
        else:
            sql = (f"SELECT t.value, count(DISTINCT q.id) AS n FROM questions q JOIN set_members m ON m.question_id = q.id "
                   f"JOIN sets s ON s.id = m.set_id AND s.status = 'published' JOIN set_tags t ON t.set_id = s.id "
                   f"AND t.tag_key = %s WHERE {cond} GROUP BY t.value")
            values = rows(sql, [key] + args)
        if key == "unit":                               # a unit that only repeats its chapter isn't a filter of its own
            values = [v for v in values if v["value"] in chosen.get(key, []) or v["value"] not in standin]
        numeric = d["kind"] == "number" and all(v["value"].replace(".", "", 1).isdigit() for v in values)
        values.sort(key=(lambda v: -float(v["value"])) if key == "year" and numeric else
                    (lambda v: float(v["value"])) if numeric else (lambda v: v["value"].lower()))
        label_of = pages.TYPE_LABEL.get if key == "type" else (lambda v: labels.get((key, v)))
        out.append({"key": key, "label": d["label"], "kind": d["kind"], "selected": chosen.get(key, []),
                    "values": [{"value": v["value"], "label": label_of(v["value"]) or v["value"],
                                "count": v["n"]} for v in values]})
    total = rows(f"SELECT count(*) AS n FROM questions q WHERE {PUBLISHED}")[0]["n"]
    return cached({"filters": out, "total_published": total})


@app.get("/api/questions")
def questions(request: Request):
    sql, args = list_query(request)
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    per = request.query_params.get("per", "")
    size = int(per) if per in {str(n) for n in PAGE_SIZES} else PAGE_SIZES[0]
    ids = [r["id"] for r in rows(sql, args)]
    if request.query_params.get("ids") == "1":     # every match, in order
        return cached({"total": len(ids), "ids": ids[:500]})
    pages_n = max(1, -(-len(ids) // size))
    page = min(page, pages_n)     # an old link past the end (the list has shrunk): its last page, not an empty one
    start = (page - 1) * size
    out = {"total": len(ids), "page": page, "page_size": size,
           "pages": pages_n, "questions": fetch_cards(ids[start:start + size])}
    paper = request.query_params.get("paper", "").strip()[:20]
    if paper:
        # the paper's questions still unpublished, so the paper view says what's missing
        out["not_shown"] = [r["printed_number"] or "?" for r in rows(
            "SELECT m.printed_number FROM set_members m JOIN sets s ON s.id = m.set_id AND s.status = 'published' "
            "AND s.visibility = 'public' JOIN questions q ON q.id = m.question_id "
            f"WHERE m.set_id = %s AND NOT ({PUBLISHED}) ORDER BY m.position", (paper,))]
    return cached(out)


@app.get("/api/questions/{qid}")
def question(qid: str, request: Request):
    got = fetch_cards([qid])
    if not got:
        raise HTTPException(404, "no such question")
    q = got[0]
    q["block"] = None
    q["figures"] = []
    q["answers"] = []
    sql, args = list_query(request)
    ids = [r["id"] for r in rows(sql, args)]
    i = ids.index(qid) if qid in ids else -1
    q["position"] = {"index": i + 1 if i >= 0 else None, "total": len(ids),
                     "prev": ids[i - 1] if i > 0 else None, "next": ids[i + 1] if 0 <= i < len(ids) - 1 else None}
    return cached(q)


@app.get("/api/papers")
def papers():
    sets = rows("SELECT s.id, s.title, s.kind, (SELECT count(*) FROM set_members m JOIN questions q ON q.id = m.question_id "
                f"WHERE m.set_id = s.id AND {PUBLISHED}) AS questions FROM sets s "
                "WHERE s.status = 'published' AND s.visibility = 'public'")
    tags = {}
    for r in rows("SELECT t.set_id, t.tag_key, t.value FROM set_tags t JOIN tag_defs d ON d.key = t.tag_key AND d.public "
                  "WHERE t.set_id = ANY(%s)", ([s["id"] for s in sets],)):
        tags.setdefault(r["set_id"], {}).setdefault(r["tag_key"], []).append(r["value"])
    urls = _paper_urls()
    out = [{"set_id": s["id"], "title": pages._paper_title(s["title"], s["kind"], tags.get(s["id"], {})),
            "url": urls.get(s["id"]), "tags": tags.get(s["id"], {}), "questions": s["questions"]} for s in sets]
    out.sort(key=lambda p: (-int((p["tags"].get("year") or ["0"])[0] or 0), p["title"]))
    return cached({"papers": out})


# ---------------------------------------------------------------- robots, sitemap, icons

ROBOTS_TXT = "User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: " + pages.SITE_URL + "/sitemap.xml\n"


@app.get("/robots.txt")
def robots():
    return Response(ROBOTS_TXT, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


SITEMAP_SECONDS = 600
_sitemap = {"at": 0.0, "stamp": None, "xml": ""}
# what changing would change the sitemap, read in a few milliseconds: rows added, removed or edited
SITEMAP_STAMP = ("SELECT (SELECT count(*) || '/' || coalesce(max(updated_at)::text, '') FROM questions) AS q, "
                 "(SELECT count(*) || '/' || coalesce(max(updated_at)::text, '') FROM sets) AS s")


@app.get("/sitemap.xml")
def sitemap():
    """Kept and served again until the questions or papers change, or for at most 10 minutes (it reads every
    question), so a crawler fetching it again and again doesn't slow the site down for visitors."""
    stamp = rows(SITEMAP_STAMP)[0]
    if not _sitemap["xml"] or stamp != _sitemap["stamp"] or time.monotonic() - _sitemap["at"] > SITEMAP_SECONDS:
        _sitemap["xml"], _sitemap["stamp"], _sitemap["at"] = _sitemap_xml(), stamp, time.monotonic()
    return Response(_sitemap["xml"], media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})


def _sitemap_xml():
    # lastmod is when the page really changed, not today. A thin page (pages.NOINDEX_TYPES) says noindex, so it
    # isn't listed either.
    qrows = rows(f"SELECT q.id, q.content, q.updated_at FROM questions q WHERE {PUBLISHED} AND NOT q.type = ANY(%s)",
                 (list(pages.NOINDEX_TYPES),))
    newest_q = max((r["updated_at"] for r in qrows), default=None)
    site = pages.SITE_URL
    urls = [(f"{site}/", (newest_q.date() if newest_q else date.today()).isoformat())]
    for path, lastmod in hubs.sitemap_urls():       # boards, subjects, years, papers (their own addresses) and chapters
        urls.append((f"{site}{path}", lastmod))
    urls.append((f"{site}/about", urls[0][1]))
    urls.append((f"{site}/privacy", urls[0][1]))
    tags = public_tags([r["id"] for r in qrows])
    for r in qrows:
        path = pages.question_path(r["id"], tags[r["id"]], r["content"])
        urls.append((f"{site}{path}", r["updated_at"].date().isoformat()))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in urls:
        lines.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
    lines.append("</urlset>")
    return "\n".join(lines)


@app.get("/favicon.ico")
def favicon():
    return FileResponse(STATIC / "favicon.ico", media_type="image/x-icon",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    return FileResponse(STATIC / "apple-touch-icon.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------- the page

# Tags that apps and ads add to a shared link (Google's srsltid on search results, Facebook's fbclid, WhatsApp and
# newsletters' utm_*): not the visitor's choice of anything, so a page reads as if they weren't there.
TRACKING = re.compile(r"utm_\w+|fbclid|gclid|gbraid|wbraid|dclid|msclkid|srsltid|igsh|igshid|mc_cid|mc_eid|ref|si|_ga")


def _own_params(request):
    """The query string's keys, less the tracking tags."""
    return [k for k in request.query_params if not TRACKING.fullmatch(k)]


@app.get("/")
def index(request: Request):
    if request.query_params and not _own_params(request):
        return RedirectResponse("/", status_code=301)
    qid = request.query_params.get("question", "").strip()
    if qid:
        page = pages.question_page(qid)
        if page:
            return RedirectResponse(_with_query(page.path, request, drop=("question",)), status_code=301)
    if request.query_params.get("view") == "papers" and len(request.query_params) == 1:
        return RedirectResponse("/papers", status_code=301)          # the old Papers list: its server-rendered page
    paper = request.query_params.get("paper", "").strip()
    if paper and len(request.query_params) == 1:        # a bare ?paper=<id>: the paper's own page (301)
        conn = connect()
        try:
            to = catalog.paper_path(conn, paper)
        finally:
            conn.close()
        if to:
            return RedirectResponse(to, status_code=301)
    # its /static/ links carry ?v=<content hash> (assets.py), so those files can be cached for a year
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    bare = not request.query_params
    try:
        about = hubs.home_html() if bare else ""
        description = hubs.home_description()
    except Exception:                                   # the interactive list still works without the text
        about, description = "", ""
    if description:
        html = re.sub(r'(<meta name="description" content=")[^"]*(">)',
                      lambda m: m.group(1) + description.replace("&", "&amp;").replace('"', "&quot;") + m.group(2), html, 1)
        html = re.sub(r'(<meta property="og:description" content=")[^"]*(">)',
                      lambda m: m.group(1) + description.replace("&", "&amp;").replace('"', "&quot;") + m.group(2), html, 1)
    html = html.replace("<!--HOME-->", about)
    if about:                                           # the text below is the visible content; no "Loading..." beside it
        html = html.replace('<p class="muted pad">Loading…</p>', "", 1)
    headers = {"Cache-Control": "no-cache"}
    if not bare:          # a filtered list (?paper=..&sort=.., ?subject=..) is built in the browser: the hubs are
        headers["X-Robots-Tag"] = "noindex, follow"     # the indexed pages
    return HTMLResponse(assets.stamp(html), headers=headers)


# nginx (or any web server) can serve /static/ from disk itself; these mounts are for simple runs and tests.
app.mount("/static/vendor", StaticFiles(directory=assets.VENDOR), name="vendor")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------------------------------------------------------------- question pages and hubs
#
# Registered after the mounts above, so /static/... and every /api/... route are always tried first; the question
# routes only ever see what nothing more specific matched. qid is validated inside pages.question_page so these
# routes can't swallow unrelated paths.

def _with_query(path, request, drop=()):
    """`path`, with the request's other query params (if any) appended - list-view filters like ?subject=Physics
    must survive a redirect, but the params in `drop` (e.g. "question") never should."""
    kept = [(k, v) for k, v in request.query_params.multi_items() if k not in drop]
    if not kept:
        return path
    return f"{path}?{urlencode(kept)}"


def _question_page_response(qid, board, subject, slug, request):
    page = pages.question_page(qid)
    if page is None:
        raise HTTPException(404, "no such question")
    parts = page.path.strip("/").split("/")   # always board/subject/qid/slug - question_path never omits the slug
    if [board, subject, qid, slug] != parts:
        return RedirectResponse(_with_query(page.path, request), status_code=301)
    return HTMLResponse(pages.render(page))


def _hub(page):
    if page is None:
        raise HTTPException(404, "no such page")
    return HTMLResponse(pages.render(page))


@app.get("/papers")
def papers_hub():
    return _hub(hubs.papers_page())


@app.get("/about")
def about():
    return _hub(hubs.about_page())


@app.get("/privacy")
def privacy():
    return _hub(hubs.privacy_page())


@app.get("/chapters")
def chapters_hub():
    return _hub(hubs.chapters_page())


@app.get("/{board}/{subject}/chapter/{chapter}")
def chapter_hub(board: str, subject: str, chapter: str):
    return _hub(hubs.chapter_page(board, subject, chapter))


@app.get("/{board}/{subject}/chapter/{chapter}/page/{n:int}")
def chapter_hub_page(board: str, subject: str, chapter: str, n: int):
    if n == 1:                                          # page 1 is the chapter's own address
        return RedirectResponse(f"/{board}/{subject}/chapter/{chapter}", status_code=301)
    return _hub(hubs.chapter_page(board, subject, chapter, n))


@app.get("/{board}/{subject}/{year:int}/{name}")
def paper_hub(board: str, subject: str, year: int, name: str):
    for old, new in catalog.OLD_KIND_SLUGS.items():         # a kind's old address: send it on for good
        if name == old or name.startswith(old + "-"):
            return RedirectResponse(f"/{board}/{subject}/{year}/{new}{name[len(old):]}", status_code=301)
    return _hub(hubs.paper_page(board, subject, year, name))


@app.get("/{board}/{subject}/{year:int}")
def year_hub(board: str, subject: str, year: int):
    return _hub(hubs.year_page(board, subject, year))


@app.get("/{board}/{subject}/{qid}/{slug}")
def question_page_with_slug(board: str, subject: str, qid: str, slug: str, request: Request):
    return _question_page_response(qid, board, subject, slug, request)


@app.get("/{board}/{subject}/{qid}")
def question_page_no_slug(board: str, subject: str, qid: str, request: Request):
    page = pages.question_page(qid)
    if page is None:
        raise HTTPException(404, "no such question")
    return RedirectResponse(_with_query(page.path, request), status_code=301)


@app.get("/{board}/{subject}")
def subject_hub(board: str, subject: str):
    return _hub(hubs.subject_page(board, subject))


@app.get("/{board}")
def board_hub(board: str):
    return _hub(hubs.board_page(board))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8141)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
