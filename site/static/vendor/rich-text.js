// Question and answer text -> HTML. The one renderer for the list page, the
// popup, question.html and PDF export (script/pdf_export.py serves this same
// file to its headless page), so text can't look different in each.
//
// Understands three things on top of plain text:
//   - $...$ maths, rendered with KaTeX (window.katex; shown as source until
//     it has loaded);
//   - ``` fenced code blocks, shown in a box that keeps indentation;
//   - tables written as | a | b | rows (an optional | --- | separator row
//     after the first makes that row a header), shown as a real table.
// Everything else is HTML-escaped, except <u>...</u> (an underlined word). The container is expected to use
// white-space:pre-line, so plain line breaks survive.
//
// renderRichText(text, query): query, if given, is highlighted in the
// non-maths text, as the list page's search does.

(function () {
  const FENCE = /^\s*```/;
  const TABLE_ROW = /^\s*\|.*\|\s*$/;
  const TABLE_SEPARATOR = /^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*(:?-{3,}:?\s*)?\|?\s*$/;
  const MARK = '<mark style="background:var(--qb-mark-bg, #fde68a); color:var(--qb-mark-fg, #3b2f00); border-radius:2px; padding:0 2px;">$1</mark>';
  const CODE_STYLE = "display:block; margin:8px 0; padding:10px 12px; overflow-x:auto; white-space:pre; " +
    "font-family:Consolas, 'DejaVu Sans Mono', monospace; font-size:0.86em; line-height:1.45; font-weight:400; " +
    "border:1px solid var(--qb-border, #dcdce6); border-radius:6px; background:var(--qb-surface, #f5f6fa); color:inherit;";
  const INLINE_CODE_STYLE = "font-family:Consolas, 'DejaVu Sans Mono', monospace; font-size:0.9em; padding:1px 4px; " +
    "border-radius:4px; background:var(--qb-surface, #f5f6fa);";
  const TABLE_STYLE = "display:block; max-width:100%; overflow-x:auto; margin:8px 0; border-collapse:collapse; " +
    "font-size:0.94em; line-height:1.4; white-space:normal;";
  const CELL_STYLE = "border:1px solid var(--qb-border-strong, #cfcfdd); padding:5px 10px; text-align:left; vertical-align:top;";
  const HEAD_STYLE = CELL_STYLE + " font-weight:600; background:var(--qb-accent-tint, #eef0ff);";

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // each word of the search is lit, wherever it is, and an apostrophe or quote matches any - as the site's search
  // finds them (site/app.py search_words, text_like; 2026-10-09)
  // a plural is cut back to its singular, as site/app.py singular() searches it ("capacitors" lights "capacitor")
  function singular(w) {
    const l = w.toLowerCase();
    if (l.length < 5 || !/^[a-z]+$/.test(l) || /(ss|us|is|ics)$/.test(l) || l === "series" || l === "species") return w;
    if (l.endsWith("ies") && l.length > 4) return w.slice(0, -3);
    if (/(ses|xes|zes|ches|shes)$/.test(l)) return w.slice(0, -2);
    return l.endsWith("s") ? w.slice(0, -1) : w;
  }

  function searchPattern(query) {
    const words = [...new Set((query || "").trim().split(/\s+/).filter(Boolean).map(singular))].sort((a, b) => b.length - a.length);
    if (!words.length) return null;
    const one = (w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/['‘’`"“”]/g, "['‘’`\"“”]");
    return new RegExp("(" + words.map(one).join("|") + ")", "gi");
  }

  function highlight(escaped, re) {
    return re ? escaped.replace(re, MARK) : escaped;
  }

  // Plain text with $...$ maths.
  function renderInline(text, re) {
    return text.split(/(\$[^$]+\$)/g).map(part => {
      if (part.length > 1 && part.startsWith("$") && part.endsWith("$")) {
        if (window.katex) {
          try {
            return window.katex.renderToString(part.slice(1, -1), {throwOnError: false});
          } catch (e) {
            return escapeHtml(part);
          }
        }
        return escapeHtml(part);
      }
      return underline(highlight(escapeHtml(part), re));
    }).join("");
  }

  // <u>...</u> (an underlined word in the question, e.g. "replace the underlined word") stays underlined, and
  // `code` (a name from the question's code, `magicfun()`) is drawn as code - as site/richtext.py does.
  //
  function underline(escaped) {
    return escaped.replace(/&lt;u&gt;([\s\S]*?)&lt;\/u&gt;/g, "<u>$1</u>")
      .replace(/`([^`\n]+)`/g, '<code style="' + INLINE_CODE_STYLE + '">$1</code>');
  }

  function splitCells(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map(c => c.trim());
  }

  function renderTable(lines, re) {
    const hasHeader = lines.length > 1 && TABLE_SEPARATOR.test(lines[1]);
    const rows = lines.filter((l, i) => !(i === 1 && hasHeader) && !TABLE_SEPARATOR.test(l));
    const html = rows.map((line, i) => {
      const head = hasHeader && i === 0;
      const tag = head ? "th" : "td";
      const style = head ? HEAD_STYLE : CELL_STYLE;
      return "<tr>" + splitCells(line).map(c => "<" + tag + ' style="' + style + '">' + renderInline(c, re) + "</" + tag + ">").join("") + "</tr>";
    }).join("");
    return '<table style="' + TABLE_STYLE + '"><tbody>' + html + "</tbody></table>";
  }

  // Some questions carry a hand-drawn text figure (a circuit, an optical
  // bench) whose lines also start and end with "|". Those are indented and
  // drawn with runs of dashes; a real table is neither, apart from its
  // | --- | separator row.
  function looksLikeTable(block) {
    return block.every(l => !/^ {4,}|^\t/.test(l)) &&
      block.every(l => TABLE_SEPARATOR.test(l) || !/-{4,}/.test(l));
  }

  // An odd number of $ so far means the next line is still inside maths, so
  // a "|x|" line there is an absolute value, not a table row.
  function dollarCount(s) {
    return (s.match(/\$/g) || []).length;
  }

  //
  function renderRichText(text, query) {
    const re = searchPattern(query);
    const lines = String(text).split("\n");
    const out = [];
    let prose = [];
    let dollars = 0;

    function flushProse() {
      if (prose.length) out.push(renderInline(prose.join("\n"), re));
      prose = [];
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const inMaths = dollars % 2 === 1;
      if (!inMaths && FENCE.test(line)) {
        let j = i + 1;
        while (j < lines.length && !FENCE.test(lines[j])) j++;
        flushProse();
        // An unclosed fence (a truncated preview) runs to the end.
        out.push('<pre style="' + CODE_STYLE + '">' + highlight(escapeHtml(lines.slice(i + 1, j).join("\n")), re) + "</pre>");
        i = j;
        continue;
      }
      if (!inMaths && TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_ROW.test(lines[i + 1])) {
        let j = i;
        while (j < lines.length && TABLE_ROW.test(lines[j])) j++;
        const block = lines.slice(i, j);
        if (looksLikeTable(block)) {
          flushProse();
          out.push(renderTable(block, re));
        } else {
          block.forEach(l => { prose.push(l); dollars += dollarCount(l); });
        }
        i = j - 1;
        continue;
      }
      prose.push(line);
      dollars += dollarCount(line);
    }
    flushProse();
    return out.join("");
  }

  // True when text has blocks that line-joining would destroy, so the MCQ
  // option re-flow (normalizeMcqText) must leave it alone.
  function hasBlocks(text) {
    const lines = String(text).split("\n");
    if (lines.some(l => FENCE.test(l))) return true;
    for (let i = 0; i + 1 < lines.length; i++) {
      if (!TABLE_ROW.test(lines[i]) || !TABLE_ROW.test(lines[i + 1])) continue;
      let j = i;
      while (j < lines.length && TABLE_ROW.test(lines[j])) j++;
      if (looksLikeTable(lines.slice(i, j))) return true;
      i = j;
    }
    return false;
  }

  window.renderRichText = renderRichText;
  window.richTextHasBlocks = hasBlocks;
})();
