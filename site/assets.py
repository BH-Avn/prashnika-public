"""Versioned links to the site's static files, so browsers can keep them for a year.

`url("/static/site.css")` -> "/static/site.css?v=<first 10 hex of its sha256>". The version changes whenever the
file does, so a deploy reaches visitors at once even though nginx tells browsers to keep a versioned file for a
year. Unversioned requests get a one-day cache there instead.

page.html calls url() directly; index.html is a static file, so stamp() rewrites its /static/ links when served.
"""

import hashlib
import re
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
STATIC = SITE_DIR / "static"
VENDOR = STATIC / "vendor"   # KaTeX and rich-text.js

_versions = {}   # file path -> (mtime_ns, size, version); re-hashed only when the file changes


def _file(path):
    if path.startswith("/static/vendor/"):
        return VENDOR / path[len("/static/vendor/"):]
    if path.startswith("/static/"):
        return STATIC / path[len("/static/"):]
    return None


def url(path):
    """`path` with ?v=<content hash> added; unchanged if it isn't one of our static files."""
    f = _file(path)
    if f is None or ".." in path:
        return path
    try:
        st = f.stat()
    except OSError:
        return path
    known = _versions.get(f)
    if not known or known[:2] != (st.st_mtime_ns, st.st_size):
        known = (st.st_mtime_ns, st.st_size, hashlib.sha256(f.read_bytes()).hexdigest()[:10])
        _versions[f] = known
    return f"{path}?v={known[2]}"


_LINK = re.compile(r'(\b(?:href|src)=")(/static/[^"?#]+)(")')


def stamp(html):
    """Every href="/static/..." and src="/static/..." in `html`, versioned."""
    return _LINK.sub(lambda m: m.group(1) + url(m.group(2)) + m.group(3), html)
