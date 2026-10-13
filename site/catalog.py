"""What the site holds, by board, subject, year, chapter and paper: the facts behind the hub pages (hubs.py), the
homepage's subject list, the sitemap, and the paper addresses question pages link to.

A paper's address is /{board}/{subject}/{year}/{kind}: /isc/physics/2024/board-paper, .../specimen-paper,
.../improvement-paper, .../competency-focused-questions (CFQ). Two papers of one kind in one year (the 2022 specimens: two semesters)
tell themselves apart by total marks, then by their id - so an address never depends on how many papers there are
on a day, only on what differs between them. A paper without a board, subject or year tag has no address of its own
(`path` is None) and callers fall back to `/?paper=<id>`. Every function takes an open connection and caches
nothing: the sets are ~125 rows, and the question aggregates are one grouped query each (papers(): ~3 ms).
"""

import re

from qh.text import slug

PUBLISHED = "q.status = 'published' AND q.visibility = 'public'"
NOINDEX_TYPES = ("preposition",)      # a thin page says noindex (pages.py), so no hub lists it and the sitemap skips it


def totals(conn):
    """{"questions": every published question} - the number the question list shows, for the home page."""
    return _rows(conn, f"SELECT count(*) AS questions FROM questions q WHERE {PUBLISHED}")[0]


# (the kinds of paper, not of question: sets.kind)
KIND_SLUG = {"board_paper": "board-paper", "specimen": "specimen-paper", "improvement": "improvement-paper",
             "practice": "competency-focused-questions", "school_paper": "school-paper"}
# addresses a kind had before: they 301 to the new one (app.py paper_hub); CFQ was .../practice-paper until 2026-10-05
OLD_KIND_SLUGS = {"practice-paper": "competency-focused-questions"}
KIND_PHRASE = {"board_paper": "Question Paper", "specimen": "Specimen Paper", "improvement": "Improvement Paper",
               "practice": "Competency Focused Questions (CFQ)", "school_paper": "School Paper"}
YEAR_RE = re.compile(r"^\d{4}$")


def _rows(conn, sql, args=()):
    cur = conn.cursor()
    cur.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def board_slug(value):
    return (slug(value) if value else "") or "isc"


def subject_slug(value):
    return (slug(value) if value else "") or "general"


def chapter_slug(value):
    return slug(value, words=12)


def _one(tags, key):
    return (tags.get(key) or [""])[0]


# ---------------------------------------------------------------- papers

def papers(conn):
    """Every published, public paper that has at least one published question, each as {id, kind, title, label,
    board, subject, year, paper_number, total_marks, cls, n, updated_at, board_slug, subject_slug, path}, newest
    year first then kind. `label` is what the paper is called ("ISC Physics 2024 Question Paper"); `path` its address
    (None when it lacks a board, subject or year)."""
    # one grouped join (~3 ms); a count and a max subquery per paper took ~25 ms, and this runs on most requests
    sets = _rows(conn, "SELECT s.id, s.kind, s.title, s.updated_at, count(*) AS n, max(q.updated_at) AS newest "
                 "FROM sets s JOIN set_members m ON m.set_id = s.id JOIN questions q ON q.id = m.question_id "
                 f"WHERE s.status = 'published' AND s.visibility = 'public' AND {PUBLISHED} "
                 "GROUP BY s.id, s.kind, s.title, s.updated_at")
    tags = {}
    for r in _rows(conn, "SELECT set_id, tag_key, value FROM set_tags WHERE set_id = ANY(%s) AND tag_key IN "
                   "('board', 'subject', 'year', 'paper_number', 'total_marks', 'class')", ([s["id"] for s in sets],)):
        tags.setdefault(r["set_id"], {}).setdefault(r["tag_key"], []).append(r["value"])
    out = []
    for s in sets:
        t = tags.get(s["id"], {})
        board, subject, year = _one(t, "board"), _one(t, "subject"), _one(t, "year")
        out.append({"id": s["id"], "kind": s["kind"], "title": s["title"] or "", "board": board, "subject": subject,
                    "year": year, "paper_number": _one(t, "paper_number"), "total_marks": _one(t, "total_marks"),
                    "cls": _one(t, "class") or "12", "n": s["n"],
                    "updated_at": max(x for x in (s["updated_at"], s["newest"]) if x),
                    "board_slug": board_slug(board), "subject_slug": subject_slug(subject), "path": None})
    _address(out)
    for p in out:
        p["label"] = _label(p)
    out.sort(key=lambda p: (-int(p["year"] or 0), p["kind"], p["paper_number"], p["id"]))
    return out


def _base_slug(p):
    base = KIND_SLUG.get(p["kind"]) or slug(p["kind"] or "paper")
    if p["paper_number"] and p["paper_number"] != "1":
        base += f"-{slug(p['paper_number'])}"
    return base


def _address(plist):
    """Fill in each paper's `path`: the kind's slug, then total marks if two share one, then the id."""
    groups = {}
    for p in plist:
        if p["board"] and p["subject"] and YEAR_RE.match(p["year"] or ""):
            groups.setdefault((p["board_slug"], p["subject_slug"], p["year"], _base_slug(p)), []).append(p)
    for (b, s, y, base), group in groups.items():
        if len(group) > 1:
            by_marks = {}
            for p in group:
                by_marks.setdefault(p["total_marks"], []).append(p)
            for p in group:
                name = base + (f"-{slug(p['total_marks'])}-marks" if p["total_marks"] else "")
                if len(by_marks[p["total_marks"]]) > 1:
                    name += f"-{slug(p['id'])}"
                p["path"] = f"/{b}/{s}/{y}/{name}"
        else:
            group[0]["path"] = f"/{b}/{s}/{y}/{base}"


def _label(p):
    if p["title"]:
        return p["title"]
    phrase = KIND_PHRASE.get(p["kind"], "Paper")
    bits = [p["board"], p["subject"], p["year"], phrase]
    if p["paper_number"] and p["paper_number"] != "1":
        bits.append(f"(Paper {p['paper_number']})")
    return " ".join(b for b in bits if b)


def paper_path(conn, set_id):
    """The address of one paper, or None when it has none (or isn't published)."""
    return next((p["path"] for p in papers(conn) if p["id"] == set_id), None)


def find_paper(conn, board, subject, year, name):
    """The paper at /{board}/{subject}/{year}/{name}, or None."""
    path = f"/{board}/{subject}/{year}/{name}"
    return next((p for p in papers(conn) if p["path"] == path), None)


# ---------------------------------------------------------------- subjects and chapters

def subjects(conn):
    """[{board, subject, board_slug, subject_slug, n, updated_at, path}] over published, indexable questions, in
    the order of most questions first."""
    got = _rows(conn, "SELECT b.value AS board, s.value AS subject, count(DISTINCT q.id) AS n, max(q.updated_at) AS updated_at "
                "FROM questions q JOIN question_tags s ON s.question_id = q.id AND s.tag_key = 'subject' "
                "LEFT JOIN question_tags b ON b.question_id = q.id AND b.tag_key = 'board' "
                f"WHERE {PUBLISHED} AND NOT q.type = ANY(%s) GROUP BY 1, 2", (list(NOINDEX_TYPES),))
    out = []
    for r in got:
        bs, ss = board_slug(r["board"]), subject_slug(r["subject"])
        out.append({"board": r["board"] or "ISC", "subject": r["subject"], "board_slug": bs, "subject_slug": ss,
                    "n": r["n"], "updated_at": r["updated_at"], "path": f"/{bs}/{ss}"})
    out.sort(key=lambda s: (-s["n"], s["subject"]))
    return out


def chapters(conn):
    """[{board_slug, subject_slug, chapter, slug, n, updated_at, path}] for every chapter with published, indexable
    questions, in each subject's syllabus order (tag_values.position), then by name."""
    got = _rows(conn, "SELECT b.value AS board, s.value AS subject, c.value AS chapter, count(DISTINCT q.id) AS n, "
                "max(q.updated_at) AS updated_at FROM questions q "
                "JOIN question_tags s ON s.question_id = q.id AND s.tag_key = 'subject' "
                "JOIN question_tags c ON c.question_id = q.id AND c.tag_key = 'chapter' "
                "LEFT JOIN question_tags b ON b.question_id = q.id AND b.tag_key = 'board' "
                f"WHERE {PUBLISHED} AND NOT q.type = ANY(%s) GROUP BY 1, 2, 3", (list(NOINDEX_TYPES),))
    order = {(r["subject"], r["value"]): r["position"] for r in _rows(
        conn, "SELECT scope->>'subject' AS subject, value, min(position) AS position FROM tag_values "
              "WHERE tag_key = 'chapter' GROUP BY 1, 2")}
    out = []
    for r in got:
        bs, ss, cs = board_slug(r["board"]), subject_slug(r["subject"]), chapter_slug(r["chapter"])
        out.append({"board_slug": bs, "subject_slug": ss, "subject": r["subject"], "chapter": r["chapter"], "slug": cs,
                    "n": r["n"], "updated_at": r["updated_at"], "path": f"/{bs}/{ss}/chapter/{cs}"})
    out.sort(key=lambda c: (c["board_slug"], c["subject_slug"], order.get((c["subject"], c["chapter"])) or 9999,
                            c["chapter"]))
    return out
