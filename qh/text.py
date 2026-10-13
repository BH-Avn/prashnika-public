"""Text helpers shared by the server, the panel and the MCP tools."""

import re
import unicodedata

_MATH_COMMANDS = re.compile(r"\\(?:mathrm|text|textbf|textit|mathbf|operatorname|left|right|displaystyle)\b")
_NON_WORD = re.compile(r"[^0-9a-z]+")

_SLUG_FENCE = re.compile(r"```.*?(```|$)", re.S)
_SLUG_MATH = re.compile(r"\$[^$]*\$")
_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")
_SLUG_CAP = 60


#
def slug(text, words=6):
    """A URL slug from `text`: lower-case, $...$ maths, ``` fences and <u> tags dropped, only a-z0-9 kept, words joined by
    '-', capped around 60 characters. Deterministic; never empty (falls back to 'question')."""
    t = _SLUG_FENCE.sub(" ", text or "")
    t = _SLUG_MATH.sub(" ", t)
    t = re.sub(r"</?u>", "", t)                    # an underlined word's markup (<u>up</u>)
    t = unicodedata.normalize("NFKC", t).lower()
    t = _SLUG_NON_WORD.sub(" ", t)
    picked = [w for w in t.split() if w][:words]
    s = "-".join(picked)
    if len(s) > _SLUG_CAP:
        s = s[:_SLUG_CAP].rsplit("-", 1)[0] or s[:_SLUG_CAP]
    s = s.strip("-")
    return s or "question"


#
def fingerprint(text):
    """The question's text reduced to lower-case letters and digits, for the exact-duplicate warning.

    Two questions that differ only in spacing, punctuation, capitals, `$` signs, code fences or common LaTeX
    wrappers (\\mathrm, \\left...) get the same fingerprint. Different numbers or words give a different one.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("```", " ")
    t = _MATH_COMMANDS.sub(" ", t)
    return _NON_WORD.sub(" ", t).strip()


_FENCE = re.compile(r"```.*?(```|$)", re.S)
_DOUBLED = re.compile(r"\\\\(?=[A-Za-z,;:!])|(?<=[0-9}])\\\\(?= \\[A-Za-z])")   # '\\,dx' (a visible comma); also '4\\ \Omega'


def fix_doubled_backslashes(s):
    """Gemini often over-escapes LaTeX, sending '\\\\frac' (two backslashes) for '\\frac'. Two backslashes followed
    by a letter become one; a real line/matrix-row break '\\\\' is followed by a space, digit or sign and stays.
    Code fences are left alone. Returns (fixed text, number of fixes)."""
    if not s or "\\\\" not in s:
        return s, 0
    parts, n = re.split(r"(```.*?(?:```|$))", s, flags=re.S), 0
    for i in range(0, len(parts), 2):
        parts[i], k = _DOUBLED.subn(r"\\", parts[i])
        n += k
    return "".join(parts), n


_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
_PARTS_IN_TEXT = re.compile(r"^\s*\((?:[a-h]|i{1,3}|iv|v|vi{0,3})\)\s", re.M)


def fix_display_maths(s):
    """$$...$$ (display maths, which the site doesn't use) becomes $...$ on its own line. Returns (text, fixes)."""
    if not s or "$$" not in s:
        return s, 0
    parts, n = re.split(r"(```.*?(?:```|$))", s, flags=re.S), 0
    for i in range(0, len(parts), 2):
        parts[i], k = _DISPLAY.subn(lambda m: "$" + m.group(1).strip() + "$", parts[i])
        n += k
    return "".join(parts), n


def labelled_lines(s):
    """Labels of lines that start like a sub-part: '(a) ...', '(ii) ...'."""
    return [m.group(0).strip() for m in _PARTS_IN_TEXT.finditer(s or "")]


_LITERAL_NL = re.compile(r"\\n(?![a-z])|\\n(?=[A-Z])")   # "\n" as two characters; LaTeX \nu, \neq... are lower case


def fix_literal_escapes(s):
    """Over-escaped JSON from some models: a literal backslash-n instead of a line break and \\" instead of ".
    Only outside $...$ maths and code, so LaTeX like \\neq is untouched. Returns (text, fixes)."""
    if not s or "\\" not in s:
        return s, 0
    pieces, n = re.split(r"(```.*?(?:```|$)|\$[^$]*\$)", s, flags=re.S), 0
    for i in range(0, len(pieces), 2):
        pieces[i], a = _LITERAL_NL.subn("\n", pieces[i])
        pieces[i], b = re.subn(r'\\"', '"', pieces[i])
        n += a + b
    return "".join(pieces), n


#
def fix_string(s):
    s, a = fix_doubled_backslashes(s)
    s, b = fix_display_maths(s)
    s, c = fix_literal_escapes(s)
    return s, a + b + c


_WORD = re.compile(r"[a-z]{4,}")


def words(s):
    """Lower-case words of 4+ letters (for comparing a page's text with the questions extracted from it)."""
    return set(_WORD.findall((s or "").lower()))


#
def fix_content_escapes(value):
    """fix_string (doubled backslashes, $$ maths) on every string in a content object (lists and nested objects)."""
    if isinstance(value, str):
        return fix_string(value)
    if isinstance(value, list):
        out, n = [], 0
        for v in value:
            fixed, k = fix_content_escapes(v)
            out.append(fixed)
            n += k
        return out, n
    if isinstance(value, dict):
        out, n = {}, 0
        for key, v in value.items():
            fixed, k = fix_content_escapes(v)
            out[key] = fixed
            n += k
        return out, n
    return value, 0


#
# LaTeX commands that only mean something inside $...$; outside it the site shows them as typed ("\frac{x}{2}")
_BARE_LATEX = re.compile(r"\\(?:frac|dfrac|sqrt|times|cdot|text|mathrm|left|right|alpha|beta|gamma|delta|Delta|theta|"
                         r"lambda|mu|omega|Omega|pi|sigma|int|sum|vec|hat|circ|sin|cos|tan|log|le|ge|leq|geq|neq|"
                         r"infty|rightarrow|to|pm|degree)(?![A-Za-z])")     # \sqrt5 as well as \sqrt{5}
_TEXT_UNDERSCORE = re.compile(r"\\(?:text|textbf|textit)\{[^{}$]*_[^{}$]*\}")   # KaTeX: '_' is maths-mode only
_MARKUP = re.compile(r"\*\*[^*\n]+\*\*|<br\s*/?>", re.I)      # markdown/HTML that rich text doesn't draw


#
EXPRESSION_FIELDS = ("start", "target", "final_value")    # one formula each: x^2 there is maths, not text


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")        # \x0c from \frac, \x08 from \beta, \x07 from \approx...
_MATH_SPAN = re.compile(r"\$[^$]*\$")
_SEPARATED = re.compile(r"(?:[·•∙]\s?[A-Za-z]){4,}")   # '·W·h·a·t·': a letter-by-letter extraction


#
def extraction_junk(s):
    """Damage an extraction leaves in a string that the other checks can't see: control characters (a one-backslash
    LaTeX command read as an escape: \\frac -> form feed, \\right -> carriage return, \\times -> tab, \\beta ->
    backspace), and letters separated by middle dots. Returns a list of problems."""
    out = []
    if _CONTROL.search(s or ""):
        out.append("has a control character, usually a LaTeX command that lost its backslash (\\frac, \\beta...): "
                   "send each backslash doubled in the JSON")
    elif any(re.search(r"[\t\r]", m) for m in _MATH_SPAN.findall(s or "")):
        out.append("has a tab or carriage return inside $...$ maths (\\times, \\theta, \\text or \\right lost its "
                   "backslash): send each backslash doubled in the JSON")
    if _SEPARATED.search(s or ""):
        out.append("has letters separated by dots (\xb7W\xb7h\xb7a\xb7t\xb7): the text was read letter by letter, "
                   "retype it from the page")
    return out


#
def maths_problems(s, field=""):
    """Problems with $...$ maths in a rich-text string (code fences are ignored): '$$' display maths, an odd
    number of '$' (a span opened and never closed) and LaTeX written outside $...$ - in an EXPRESSION_FIELDS
    `field`, also a bare ^, _ or backslash ("24x^2 - 23x = 0", "3 sqrt5" with a backslash). The full KaTeX render check comes with the
    panel."""
    if field in EXPRESSION_FIELDS and "$" not in (s or "") and re.search(r"[\^_\\]", s or ""):
        return ["has maths outside $...$ (put the whole expression between $ signs)"]
    body = _FENCE.sub(" ", s or "")
    problems = []
    if "$$" in body:
        problems.append("uses $$...$$; write maths as $...$")
    if (body.count("$") - body.count("\\$")) % 2:
        problems.append("has an odd number of $ signs (a maths span isn't closed)")
    else:
        outside = re.sub(r"\$[^$]*\$", " ", body)
        if _BARE_LATEX.search(outside):
            problems.append("has LaTeX outside $...$ (put the maths between $ signs)")
        if _TEXT_UNDERSCORE.search(body):
            problems.append("has an underscore inside \\text{...}, which KaTeX can't draw (the whole formula shows as "
                            "red source): write a blank as \\underline{\\hspace{2em}}, not \\text{ _____ }")
        if _MARKUP.search(outside):
            problems.append("has **bold** or <br>, which the site shows as typed: leave them out (a line break is "
                            "a real new line)")
    return problems


def question_fingerprint(content):
    """Fingerprint of a question's whole content: its text, passage, options and parts, in order."""
    pieces = []

    def walk(value):
        if isinstance(value, str):
            pieces.append(value)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, dict):
            for key in sorted(value):
                if key not in ("label", "marks", "type"):   # structure, not wording
                    walk(value[key])

    walk(content)
    return fingerprint(" ".join(pieces))
