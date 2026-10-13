# Prashnika (public code sample)

Prashnika is a question bank of past exam papers (ISC Class 12 for now): every paper is split into single questions,
tagged, and shown on a website that can be browsed and sorted by **subject, year, paper and chapter**.

This repository is a **read-only code sample** of that website's front end and its question-list pages. It exists so
you can see how the real project is written, not so you can run or rebuild it.

> **Not a working copy, on purpose.** Left out: the database schema and every question (the questions belong to
> their exam board), the real stylesheet and design, all brand assets (logo, icons, fonts), the study tools, the
> paper generator, the written notes, answers and figures, the review panel and the MCP server. What is here will
> not start on its own and, if you gave it your own database, would look like a plain unstyled page. No licence is
> granted: you may read it, nothing more.

The sections below describe the parts that are not included (the MCP server and the review panel) in detail, so the
whole system can be understood from this one page.

---

## What is in this repository

```
site/
  app.py          FastAPI app: the JSON API behind the question list, the sitemap, and every page route
  pages.py        Server-rendered pages: one question, a list of questions in full, SEO titles and descriptions
  hubs.py         Hub pages: home, board, subject, year, paper, chapter, "all papers", "all chapters", about
  catalog.py      What the bank holds: papers, subjects, chapters, and the address (URL) each one gets
  richtext.py     Question text -> safe HTML ($...$ maths left for the browser, ``` code blocks, | tables |)
  sitedb.py       A small pool of read-only database connections
  assets.py       Versioned /static links (?v=<hash>) so browsers can cache files for a year
  templates/page.html       the one HTML template every server-rendered page uses
  static/index.html         the shell of the interactive question list
  static/site.js            the question list: filters, search, sort, paging, the question pop-up (no framework)
  static/page.js            small behaviours on server-rendered pages (maths, filter boxes, back links)
  static/words.js           short names and misspellings for subject search ("eng lit", "phiyscs")
  static/vendor/rich-text.js  the browser's renderer for question text (the same rules as richtext.py)
  static/site.css           a deliberately plain stylesheet (one theme); not the real design
qh/
  text.py         slug() - turns question text into the last part of its URL
  db.py           where the database is (environment variable QH_DB)
```

## How the site works

Everything the visitor chooses lives in the web address, so any view can be shared or bookmarked.

| Address | What it is |
|---|---|
| `/` | Landing page: search box, counts, a card per subject (written by `hubs.home_html`) |
| `/?view=questions&subject=Physics&year=2024&sort=paper&page=2` | The interactive list (`site.js` calls the API below) |
| `/{board}/{subject}` | A subject: its papers by year and its chapters, with question counts |
| `/{board}/{subject}/{year}` | One year's papers |
| `/{board}/{subject}/{year}/board-paper` | One paper, every question in full, in printed order |
| `/{board}/{subject}/chapter/{chapter}` | One chapter, every question in full, newest first, 20 a page |
| `/{board}/{subject}/{qid}/{slug}` | One question on its own page (the canonical address; a wrong slug 301s to it) |
| `/papers`, `/chapters` | Every paper / chapter, with a box that narrows them as you type |
| `/sitemap.xml`, `/robots.txt` | For search engines; the sitemap is cached and rebuilt when questions change |

**The question list API** (`site/app.py`):

* `GET /api/filters?<filters>`: each filter with its values and counts, counted *under the other chosen filters*
  (so choosing Physics shows how many 2024 questions Physics has, not the whole bank).
* `GET /api/questions?<filters>&q=&sort=&page=&per=`: 20 a page (10 on phones). `sort` is `year_desc`, `year_asc`
  or `paper` (printed order within a paper). `ids=1` returns only the matching ids.
* `GET /api/questions/{id}?<filters>`: one question in full plus the previous/next question *in the current list*,
  which is how the pop-up's arrow keys walk the filtered list.
* `GET /api/papers`: every published paper with its question count.

Filters are plain query parameters, repeatable: `?subject=Physics&year=2024&year=2023`. Which tags are filters is
data, not code: any tag marked `filterable` in `tag_defs` appears automatically. One extra filter, `type`, comes from
a column. Free-text search splits what you typed into up to six words, matches each anywhere in the question's text
fields (not its JSON keys), treats plurals as singular, ignores zero-width characters copied from PDFs, and reads a
subject's name out of the search ("maths integration" becomes the subject Mathematics plus the word "integration").

**Sorting by chapter, subject, paper, year** is three joins computed once for the whole list (a question's year, its
subject, its place in its first published paper) rather than a lookup per row, which keeps a list of thousands of questions quick.

**Every question and every hub is server-rendered** with its own title, description, canonical link, breadcrumb and
JSON-LD, so search engines can index them; the interactive list is a convenience on top of real pages. Thin pages
(a half-mark fill-in-the-blank) say `noindex` and stay out of the sitemap but are still linked from their paper.

## The data model, in words

The real project uses PostgreSQL. This sample reads these tables (the full database has about twenty):

* **`questions`**: `id` (`q-` plus seven random characters with no look-alikes, never changed even when a question
  moves), `type`, `content` (JSON), `status` (`draft`, `checked`, `published`, `hidden`), `visibility`
  (`public`, `school`, `private`), `search_title`. Only `published` + `public` rows are ever read by the site.
* **`sets`** (a paper is a set): `kind` (`board_paper`, `specimen`, `improvement`, `practice`, `school_paper`),
  `title`, `status`, `visibility`. **`set_members`** puts questions in a set with their `position` and the number as
  printed (`printed_number`, e.g. `3(ii)(a)`).
* **Tags** carry everything else. **`tag_defs`** lists which properties exist (board, class, subject, year, chapter,
  marks, paper number, total marks...), whether each is public and whether it is a filter; **`tag_values`** lists the
  allowed values (a chapter belongs to a subject through its `scope`, and has a `position` for syllabus order);
  **`question_tags`** and **`set_tags`** attach values to questions and papers. Adding a property is a new row, not a
  schema change.
* A question's **`content`** follows its type. Every type has `text` (rich text) and optional `parts`
  (`[{label, marks, ...}]`), and adds its own fields: `options` for multiple choice, `assertion`/`reason`,
  `column_a`/`column_b` for matching, `passage` for comprehension, `sample_io` for programs, `word_limit` for
  writing, and so on. Rich text is plain text with maths in `$...$`, code in fenced blocks and tables as `| a | b |`
  rows, rendered by the same rules on the server (`richtext.py`) and in the browser (`rich-text.js`).

## Part not included: the MCP server

Extracting a paper by hand would take hours, so the project runs an **MCP server** (Model Context Protocol) that
lets AI apps such as Claude or Gemini do the reading, with the server doing the checking. The server holds no
model and calls no AI API: the AI app is the client, the owner's own chat subscription pays for the work, and the
server is the set of *buttons* the AI may press. Every call is its own database transaction and is recorded under
the key it came from.

**The principle: the AI proposes, the server verifies.** An AI is good at reading a page image and bad at arithmetic,
so anything mechanical is done by the server and the AI is told to use it: finding question boundaries on a page,
numbering, marks totals, Boolean algebra, running Java, solving maths, checking chemical equations for balance,
drawing circuits and graphs, validating answers against their question type. What an AI sends is refused item by
item with a reason when it does not fit; a refusal never loses the other items in the same call.

**The tools**, grouped by the job:

* *Look things up:* `get_formats` (the shape of each question type, trimmed to one subject), `get_chapter_topics`
  (the syllabus topics under a chapter), `list_papers`, `get_page` (a PDF page as text and image; scanned pages are
  OCR'd and labelled so the AI takes formulas from the image), `get_question` (one question in full, or a search by
  subject, type, label, chapter, year, paper or words), `get_text` (the set texts for literature papers, by chapter,
  line range or phrase).
* *Extract a paper:* `plan_paper` is the start: the server's own layout analysis returns every question it found as a
  ready-to-send object (number, parts, marks, section, "answer any one", figure boxes, the page text, a guessed type
  and chapter, plus a list of things to check). The AI corrects it page by page and sends it back with
  `submit_questions` (about 25 per call; add or replace by position). `add_figure` / `get_figure` / `remove_figure`
  crop diagrams from the PDF by box so a bad crop can be replaced.
* *Check and publish:* `check_paper` reports skipped numbers, marks that do not add up, missing required tags, broken
  maths and missing figures. When nothing is missing it **publishes** the paper and every question with no open
  issue; anything doubtful is held back with `report_issue` first.
* *Answer:* `get_paper(set_id, only="unanswered")` returns an `answer_template` per unanswered part, with `FILL:`
  placeholders (a template sent back unfilled is refused), the rules for each question type, a few already-answered
  similar questions, and the tools that exist for that subject. `submit_answers` stores them. Numerical answers carry
  a final value and unit; structured types carry checked fields (a truth table, a K-map, a binary tree, an LPP, a
  reaction, a circuit netlist) that the server solves or draws and compares with the AI's claim.
* *Fix what is held:* `list_issues` shows every question kept off the site (open issue, publishing problem, answer
  flagged "needs a check") with its notes; the AI fixes it with `submit_questions` and marks it with
  `report_issue(..., ["fixed"])`, after which it waits for the owner.
* *Reshape:* `get_paper(restructure=true)` and `submit_restructure` move an old paper (questions grouped as printed)
  to single questions in printed slots, as a checked proposal the owner approves; `set_types` changes question types
  and short search titles in bulk, logged and undoable; `label` applies the owner's private labels.
* *Server-side tools the AI can call:* `boolean` (simplify and compare Boolean expressions), `calculate` (exact
  arithmetic and symbolic maths), `run_program` (any Java, run in a locked-down sandbox with CPU, memory, output and
  network limits).
* *Notes:* `get_note_guide`, `list_notes`, `get_note`, `submit_note`: the AI writes a study note around a program the
  owner wrote, using the real output of running it.

**Keys and sign-in.** Each AI app has its own key and level. The local server speaks stdio and acts as one user;
the hosted server (HTTP) uses **OAuth** (dynamic client registration, authorisation code with PKCE, refresh tokens)
so web-based AI apps can connect, mapping the access token to the key behind it. A key can be disabled at any time
and every write names the key in a change log. All question tools are marked read-only to the client app on
purpose, so apps do not ask for confirmation before each call; the protection is entirely server-side checks, not the
hint.

**Tool instructions are short.** Apps cut long server instructions (one kept only the first ~2,000 characters of a
10,000-character text), so the server's instructions are a one-page index and each task's full rules come back
*with the call that starts it* (`plan_paper` returns `how_to_extract`, `get_paper` returns `how_to_answer`).

## Part not included: the review panel

The panel is the owner's control room, a single-page web app plus a JSON API. Only the highest-level key can sign
in. Everything it does goes through the same checks as the MCP tools, so the two cannot disagree.

**Papers.** A paper's PDF is uploaded here (`add-paper` on the command line does the same); the server records its
page count, and finds scanned pages. Each paper row shows a progress bar of questions live, one "needs you" line and
one button (Review, Fix issues, Compare, Publish, Open). A "Next up" card suggests the next paper. Subject chips filter
the list.

**One paper.** A slim question list with status dots (draft, checked, published, hidden) and a "Needs work" filter;
the editor for the chosen question, with its answers; and a right column that shows the **source PDF page** (opening a
question jumps to where it starts and marks it) or **the question as the public site would draw it**, using the site's
own page code so there is no second renderer to drift. The bar under the editor has *Looks good, next*, *Hide*,
*Needs work* and *Flag / label*. Edits carry the version the editor loaded: if the question changed meanwhile nothing
is overwritten (HTTP 409) and the latest is shown. Every change is logged with before and after and can be undone.
A drag on the PDF page adds a figure box. *Paper tools* has *Check paper*, *Publish ready questions*, *AI chat* and
*Single questions*.

**AI chat** is the fallback for AI apps that cannot use MCP: the panel builds one block with the instructions and the
paper's data, the owner pastes it into a chat with the PDF attached, then pastes the reply back; the JSON inside it
is read and each item is saved or refused through the same checks as MCP calls.

**Review** collects everything an AI did that waits for the owner, as a list on the left and the chosen item on the
right. A *fixed question* shows the AI's note, a word-by-word before/after, the question with its figures and
answers. An *answer* shows the question, the answer and its picture. **Approve** clears the issues and publishes (if
the paper is published) or clears the answer's "needs a check" flag; **Reject** takes a reason that the next AI is
given, and can put back what the AI changed. Ticked rows can be approved together.

**Questions** is every question in the bank, any status, with the public site's filters plus status, type, answer
state and every private tag. Each value shows the count it would give under the other filters; a value can be
included or excluded. The filters are in the address, so a link keeps them. The owner's own **labels** (optionally in
groups, such as "Difficulty: easy, hard") are private tags that are added to ticked rows in bulk and never reach the
site. Opened from here, the editor's next/previous steps through the filtered list, across papers.

**Single-question review.** For a paper stored as grouped questions, the screen puts the live paper on the left and
the AI's proposed split on the right, row by printed number, saying where each old part went (red if unused or used
twice), what changed in type, marks and chapter, and the wording difference word by word. **Approve** only marks the
proposal approved; **Send back** needs a reason, which the AI receives. **The switch** then puts every approved paper
of a subject on the site as single questions at once, with a per-paper undo that is refused if a new question was
edited or answered meanwhile.

**Inbox** holds what visitors send: reports of mistakes and suggested answers, each approved, rejected or turned into
an issue. **Diagrams** lists answers whose picture still has to be made, with *Paste picture*. **Notes** edits the
study notes (live preview using the public site's template, history with undo, publishing refused while problems are
listed). **Keys** lists AI keys, with rekey and disable.

**Publishing rules.** A question is visible only when its status is `published` and its visibility is `public`, and
a paper only when it too is published. Required tags must be set before publishing. A published question that gets an
issue comes off the site until the owner approves the fix. Every route in the panel API checks the key's level; there
is no way to publish from outside it.

## Why it is built this way

* **Tags instead of columns**, so a new board or subject adds rows, not migrations.
* **IDs that never change and say nothing about the question**, so moving or merging questions breaks no link.
* **Server-rendered pages first, JavaScript second**, because the audience arrives from search results.
* **No framework or build step** in the front end: plain modules, one stylesheet, versioned static URLs.
* **Verify, do not trust**: the server checks what an AI sends and says why it refuses.
