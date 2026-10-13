"""Server-side rich text -> HTML, mirroring v2/panel/static/vendor/rich-text.js MINUS KaTeX.

$...$ maths is left as literal, escaped text: the page ships KaTeX and a small script (site/static/page.js) that
upgrades those spans in the browser, same as the panel and the SPA already do client side. Everything else is
escaped; the caller's container is expected to use white-space:pre-line (site.css already does, via .qtext etc.)
so plain line breaks survive.

Generic building blocks only - nothing here knows what a "question" is. site/pages.py composes these into a
question's HTML; a future written-notes page reuses the same functions.
"""

import html
import re

#
_FENCE = re.compile(r"^\s*```")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*(:?-{3,}:?\s*)?\|?\s*$")
_MATH_SPAN = re.compile(r"\$[^$]*\$")

# Inline styles, not CSS classes: rich-text.js draws code/tables this way (no shared class exists for them), so
# these are copied from it to keep client- and server-rendered questions looking the same.
_CODE_STYLE = ("display:block; margin:8px 0; padding:10px 12px; overflow-x:auto; white-space:pre; "
               "font-family:Consolas, 'DejaVu Sans Mono', monospace; font-size:0.86em; line-height:1.45; "
               "font-weight:400; border:1px solid var(--qb-border, #dcdce6); border-radius:6px; "
               "background:var(--qb-surface, #f5f6fa); color:inherit;")
_TABLE_STYLE = ("display:block; max-width:100%; overflow-x:auto; margin:8px 0; border-collapse:collapse; "
                "font-size:0.94em; line-height:1.4; white-space:normal;")
_CELL_STYLE = ("border:1px solid var(--qb-border-strong, #cfcfdd); padding:5px 10px; text-align:left; "
               "vertical-align:top;")
_HEAD_STYLE = _CELL_STYLE + " font-weight:600; background:var(--qb-accent-tint, #eef0ff);"


def escape_html(s):
    return html.escape(str(s if s is not None else ""), quote=True)


_UNDERLINE = re.compile(r"&lt;u&gt;(.*?)&lt;/u&gt;", re.S)
UNDERLINE_TAG = re.compile(r"</?u>")


#
INLINE_CODE = re.compile(r"`([^`\n]+)`")           # `magicfun()` in a question: a name from its code


#
def underline(escaped):
    """<u>...</u> in already-escaped text (an underlined word, "replace the underlined word") drawn underlined again,
    and `code` as <code>, as rich-text.js does; nothing else is let through."""
    return INLINE_CODE.sub(r"<code>\1</code>", _UNDERLINE.sub(r"<u>\1</u>", escaped))


#
def strip_maths(text):
    """`text` with every $...$ span dropped (for titles and meta descriptions, which don't render maths)."""
    return _MATH_SPAN.sub(" ", text or "")


def _split_cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _looks_like_table(block):
    # Same rule as rich-text.js: a hand-drawn text figure (indented, dashes) isn't a table; a real one is neither,
    # apart from its own | --- | separator row.
    if any(re.match(r"^ {4,}|^\t", line) for line in block):
        return False
    for line in block:
        if _TABLE_SEPARATOR.match(line):
            continue
        if re.search(r"-{4,}", line):
            return False
    return True


def _render_table(lines, cell=escape_html):
    has_header = len(lines) > 1 and bool(_TABLE_SEPARATOR.match(lines[1]))
    rows = [line for i, line in enumerate(lines) if not (i == 1 and has_header) and not _TABLE_SEPARATOR.match(line)]
    out = []
    for i, line in enumerate(rows):
        head = has_header and i == 0
        tag, style = ("th", _HEAD_STYLE) if head else ("td", _CELL_STYLE)
        cells = "".join(f'<{tag} style="{style}">{cell(c)}</{tag}>' for c in _split_cells(line))
        out.append(f"<tr>{cells}</tr>")
    return f'<table style="{_TABLE_STYLE}"><tbody>{"".join(out)}</tbody></table>'


#
def render_text(text):
    """One rich-text string (a question's `text`, an option's `text`, an answer field...) to HTML: ``` fences
    become <pre><code>, | a | b | rows become a <table>, everything else is escaped with line breaks kept. $...$
    maths is left as literal text - see the module docstring."""
    lines = str(text if text is not None else "").split("\n")
    out, prose, dollars = [], [], 0

    def flush():
        if prose:
            out.append(underline(escape_html("\n".join(prose))))
            prose.clear()

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        in_maths = dollars % 2 == 1
        if not in_maths and _FENCE.match(line):
            j = i + 1
            while j < n and not _FENCE.match(lines[j]):
                j += 1
            flush()
            out.append(f"<pre><code>{escape_html(chr(10).join(lines[i + 1:j]))}</code></pre>")
            i = j + 1
            continue
        if not in_maths and _TABLE_ROW.match(line) and i + 1 < n and _TABLE_ROW.match(lines[i + 1]):
            j = i
            while j < n and _TABLE_ROW.match(lines[j]):
                j += 1
            block = lines[i:j]
            if _looks_like_table(block):
                flush()
                out.append(_render_table(block, cell=lambda c: underline(escape_html(c))))
            else:
                for l in block:
                    prose.append(l)
                    dollars += l.count("$")
            i = j
            continue
        prose.append(line)
        dollars += line.count("$")
        i += 1
    flush()
    return "".join(out)


# ---------------------------------------------------------------- articles (written notes)
#
# A note's body: everything render_text() does, plus headings, lists, bold, inline code, links, "> " tip boxes and
# {{q-...}} question cards. Paragraphs are separated by blank lines.

# Code colours for note code boxes: Java words (ISC CS), strings, numbers and comments get a <span class="tok-..">;
# everything else stays plain. One pass, so a keyword inside a string or comment is never coloured.
_JAVA_KEYWORDS = ("abstract boolean break byte case catch char class continue default do double else extends final "
                  "finally float for if implements import int interface long new null package private protected "
                  "public return short static super switch this throw throws true false try void while").split()
_CODE_TOKEN = re.compile(r'(?P<com>//[^\n]*|/\*.*?\*/)|(?P<str>"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')'
                         r'|(?P<num>\b\d+(?:\.\d+)?[LlFfDd]?\b)|(?P<kw>\b(?:' + "|".join(_JAVA_KEYWORDS) + r')\b)'
                         r'|(?P<type>\b[A-Z][A-Za-z0-9_]*\b)', re.S)


#
def highlight_code(src):
    out, pos = [], 0
    for m in _CODE_TOKEN.finditer(src):
        out.append(escape_html(src[pos:m.start()]))
        out.append(f'<span class="tok-{m.lastgroup}">{escape_html(m.group())}</span>')
        pos = m.end()
    out.append(escape_html(src[pos:]))
    return "".join(out)


_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_QCARD = re.compile(r"^\s*\{\{\s*(q-[a-z0-9]{7})\s*\}\}\s*$")
_BLOCK = re.compile(r"^\s*\{\{(program|samples)\}\}\s*$")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _safe_href(url):
    """Site paths, in-page anchors and https:// links only - never javascript:, data: or //host."""
    if url.startswith("/") and not url.startswith("//"):
        return url
    if url.startswith("#") or url.startswith("https://"):
        return url
    return None


def inline(text):
    """One line of article text to HTML: `code`, [links](/path), **bold**; everything else escaped. $...$ maths
    is left as text for page.js, as elsewhere."""
    out, pos = [], 0
    for m in _CODE_SPAN.finditer(text):
        out.append(_inline_plain(text[pos:m.start()]))
        out.append(f"<code>{escape_html(m.group(2).strip())}</code>")
        pos = m.end()
    out.append(_inline_plain(text[pos:]))
    return "".join(out)


def _bold(escaped):
    return _BOLD.sub(r"<b>\1</b>", escaped)


def _inline_plain(text):
    out, pos = [], 0
    for m in _LINK.finditer(text):
        out.append(_bold(escape_html(text[pos:m.start()])))
        href = _safe_href(m.group(2))
        label = _bold(escape_html(m.group(1)))
        out.append(f'<a href="{escape_html(href)}">{label}</a>' if href else label)
        pos = m.end()
    out.append(_bold(escape_html(text[pos:])))
    return "".join(out)


def plain_inline(text):
    """A heading's words without the markup (for the contents list and titles)."""
    t = _LINK.sub(r"\1", strip_maths(text))
    return re.sub(r"\s+", " ", t.replace("`", "").replace("**", "")).strip()


def _anchor(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", plain_inline(text).lower()).strip("-")[:60].strip("-") or "section"
    a, n = base, 2
    while a in taken:
        a, n = f"{base}-{n}", n + 1
    taken.add(a)
    return a


def _join(lines):
    return " ".join(l.strip() for l in lines)


def _indent(line):
    return len(line) - len(line.lstrip(" \t"))


def _render_list(lines, i):
    """The list starting at lines[i] to (html, index after it). A marker line indented deeper than the list's own
    items starts a nested list inside the current item; an indented line without a marker is that item's next line
    (kept as a line break: drafting chats put one thought per line). A blank line, a fence, a line indented less
    than the list, or a marker of the other kind at the list's own depth ends it."""
    base, numbered = _indent(lines[i]), not _BULLET.match(lines[i])
    item_re = _NUMBERED if numbered else _BULLET
    items, j, n = [], i, len(lines)     # each item: a list of parts, ("text", [lines]) or ("html", nested list)
    while j < n:
        line = lines[j]
        if not line.strip() or _FENCE.match(line) or _indent(line) < base:
            break
        marker = _BULLET.match(line) or _NUMBERED.match(line)
        if marker and _indent(line) == base:
            m = item_re.match(line)
            if not m:
                break
            items.append([("text", [m.group(1).strip()])])
            j += 1
        elif not items:
            break
        elif marker:
            nested, j = _render_list(lines, j)
            items[-1].append(("html", nested))
        elif _indent(line) > base:
            if items[-1][-1][0] == "text":
                items[-1][-1][1].append(line.strip())
            else:
                items[-1].append(("text", [line.strip()]))
            j += 1
        else:
            break
    tag = "ol" if numbered else "ul"
    body = "".join("<li>" + "".join("<br>".join(inline(l) for l in part) if kind == "text" else part
                                    for kind, part in item) + "</li>" for item in items)
    return f"<{tag}>{body}</{tag}>", j


#
def program_html(program):
    """The owner's program as a note code box (page.js adds the Copy / Hide comments bar)."""
    return f'<pre class="program"><code>{highlight_code((program or "").rstrip())}</code></pre>' if program else ""


#
def samples_html(samples):
    """A note's real sample runs: each as the terminal showed it, the input the program read in bold. The input
    arrives wrapped in \\x01...\\x02 (qh/javarun.py)."""
    out = []
    for i, s in enumerate(samples or [], 1):
        if not s.get("ok"):
            continue
        text = escape_html(str(s.get("output") or "").rstrip("\n"))
        text = re.sub(r"\x01(.*?)\x02", lambda m: f'<b class="typed">{m.group(1).rstrip(chr(10))}</b>'
                      + ("\n" if m.group(1).endswith("\n") else ""), text, flags=re.S)
        text = text.replace("\x01", "").replace("\x02", "")
        out.append(f'<p class="runlabel">Sample {i}</p><pre class="run"><code>{text}</code></pre>')
    return f'<div class="runs">{"".join(out)}</div>' if out else ""


#
def _is_code(fence_line, src):
    """A note's ``` block is code (coloured as Java) when tagged ```java, or untagged and looking like code; a
    program's output ("Enter a number: 9") or a ```text / ```output block is not."""
    tag = fence_line.strip()[3:].strip().lower()
    if tag:
        return tag in ("java", "code")
    return bool(re.search(r"[;{}]", src))


def render_article(text, question_card=None, blocks=None):
    """A note's body to (html, contents), where contents is [(anchor, heading text)] for each ## heading.
    `question_card(qid)` returns the HTML for a {{q-...}} line, or "" to leave it out (unpublished question).
    `blocks` maps "program" / "samples" to the HTML for a {{program}} / {{samples}} line (left out if missing)."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out, contents, taken, para = [], [], set(), []

    def flush():
        if para:
            out.append(f"<p>{inline(_join(para))}</p>")
            para.clear()

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if _FENCE.match(line):
            flush()
            j = i + 1
            while j < n and not _FENCE.match(lines[j]):
                j += 1
            src = chr(10).join(lines[i + 1:j])
            #
            if _is_code(line, src):
                out.append(f"<pre><code>{highlight_code(src)}</code></pre>")
            else:                        # a program's output: as the sample runs look, no colours and no Copy bar
                out.append(f'<pre class="run"><code>{escape_html(src)}</code></pre>')
            i = j + 1
            continue
        if _TABLE_ROW.match(line) and i + 1 < n and _TABLE_ROW.match(lines[i + 1]):
            j = i
            while j < n and _TABLE_ROW.match(lines[j]):
                j += 1
            block = lines[i:j]
            if _looks_like_table(block):
                flush()
                out.append(_render_table(block, cell=inline))
            else:
                para.extend(block)
            i = j
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            level = 3 if len(m.group(1)) == 3 else 2
            anchor = _anchor(m.group(2), taken)
            out.append(f'<h{level} id="{anchor}">{inline(m.group(2))}</h{level}>')
            if level == 2:
                contents.append((anchor, plain_inline(m.group(2))))
            i += 1
            continue
        m = _QCARD.match(line)
        if m:
            flush()
            out.append(question_card(m.group(1)) if question_card else "")
            i += 1
            continue
        m = _BLOCK.match(line)
        if m:
            flush()
            out.append((blocks or {}).get(m.group(1), ""))
            i += 1
            continue
        if _QUOTE.match(line):
            flush()
            j, quoted = i, []
            while j < n and _QUOTE.match(lines[j]):
                quoted.append(_QUOTE.match(lines[j]).group(1))
                j += 1
            paras = [p for p in "\n".join(quoted).split("\n\n") if p.strip()]
            body = "".join(f"<p>{inline(_join(p.split(chr(10))))}</p>" for p in paras)
            out.append(f'<div class="tip">{body}</div>')
            i = j
            continue
        if _BULLET.match(line) or _NUMBERED.match(line):
            flush()
            html_list, i = _render_list(lines, i)
            out.append(html_list)
            continue
        para.append(line)
        i += 1
    flush()
    return "".join(out), contents

