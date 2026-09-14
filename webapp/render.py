"""The response document as a page a browser can print.

Notices want a PDF: cover page, a table of contents, then the statement.
Converting the markdown by hand in a word processor is an hour of
formatting per response and a fresh chance to drop a line. This renders
the file on disk straight into a paged, printable page — Save as PDF in
the browser is the last step — and refuses to look finished while a blank
or an unreviewed draft marker is still in it.

Deliberately small: headings, paragraphs, bullet lists, tables, block
quotes, bold, code, links. That is everything the builders write.
"""

import html
import re

FILL_RE = re.compile(r"\[\[FILL: (.*?)\]\]", re.DOTALL)
DRAFT_RE = re.compile(r"\*\*\[DRAFT[^\]]*\]\*\*\s*")


def inline(text):
    out = html.escape(text, quote=False)
    out = FILL_RE.sub(lambda m: f'<mark class="fill">{html.escape(m.group(1))}</mark>', out)
    out = re.sub(r"\*\*\[DRAFT([^\]]*)\]\*\*", r'<mark class="draft">DRAFT\1</mark>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"_(?!_)([^_\n]+?)_(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', out)


def _table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(cells) < 2:
        return ""
    head = "".join(f"<th>{inline(c)}</th>" for c in cells[0])
    body = "".join(
        "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
        for r in cells[2:]
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def blocks(md):
    """Markdown -> HTML, one block at a time."""
    out, para, lst, quote, table = [], [], [], [], []

    def flush():
        nonlocal para, lst, quote, table
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>"); para = []
        if lst:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in lst) + "</ul>"); lst = []
        if quote:
            out.append("<blockquote>" + "".join(blocks(" \n".join(quote).replace(" \n", "\n"))) + "</blockquote>"); quote = []
        if table:
            out.append(_table(table)); table = []

    for line in md.split("\n"):
        s = line.rstrip()
        if not s.strip():
            flush(); continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            flush()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        if s.strip() == "---":
            flush(); out.append("<hr>"); continue
        if s.startswith(">"):
            if para or lst or table:
                flush()
            quote.append(s[1:].strip()); continue
        if s.startswith("|"):
            if para or lst or quote:
                flush()
            if re.match(r"^\|\s*-+", s) or not re.match(r"^\|\s*:?-", s):
                table.append(s)
            continue
        if re.match(r"^\s*[-*]\s+", s):
            if para or quote or table:
                flush()
            lst.append(re.sub(r"^\s*[-*]\s+", "", s)); continue
        if lst and s.startswith("  "):
            lst[-1] += " " + s.strip(); continue
        if quote or table or lst:
            flush()
        para.append(s.strip())
    flush()
    return out


def split_for_print(md):
    """(cover, toc entries, body). The cover is everything above the first
    H2 after the cover section; the TOC is every H2 in the body."""
    lines = md.split("\n")
    cut = None
    seen_cover = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            if seen_cover:
                cut = i; break
            seen_cover = True
    if cut is None:
        return md, [], ""
    cover = "\n".join(lines[:cut])
    body = "\n".join(lines[cut:])
    toc = [re.sub(r"^##\s+", "", l).strip() for l in lines[cut:] if l.startswith("## ")]
    return cover, toc, body


def page(title, md):
    fills = len(FILL_RE.findall(md))
    drafts = len(DRAFT_RE.findall(md))
    cover, toc, body = split_for_print(md)
    warn = ""
    if fills or drafts:
        parts = []
        if fills:
            parts.append(f"{fills} blank{'s' if fills != 1 else ''} still unfilled")
        if drafts:
            parts.append(f"{drafts} draft answer{'s' if drafts != 1 else ''} not yet approved")
        warn = ('<div class="warn no-print"><strong>Not ready to send.</strong> '
                + " and ".join(parts) + ". Go back to the Bid Desk and finish; "
                "each is highlighted below.</div>")
    else:
        warn = ('<div class="ok no-print"><strong>Ready.</strong> No blanks and no '
                'unreviewed drafts. Print → Save as PDF, then attach the PDF to the email.</div>')
    toc_html = "".join(f"<li>{inline(t)}</li>" for t in toc)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ font-family: "Public Sans", Georgia, system-ui, sans-serif; color: #14202a; margin: 0; line-height: 1.5; font-size: 11pt; }}
  .sheet {{ max-width: 8.5in; margin: 0 auto; padding: 0.75in 0.8in; }}
  h1 {{ font-family: Newsreader, Georgia, serif; font-size: 22pt; line-height: 1.15; margin: 0 0 12pt; }}
  h2 {{ font-family: Newsreader, Georgia, serif; font-size: 15pt; margin: 20pt 0 6pt; border-bottom: 1px solid #d3dbe1; padding-bottom: 3pt; }}
  h3 {{ font-size: 11.5pt; margin: 14pt 0 4pt; }}
  p {{ margin: 0 0 8pt; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 9.5pt; margin: 6pt 0 10pt; }}
  th, td {{ border: 1px solid #c9d2d9; padding: 4pt 6pt; text-align: left; vertical-align: top; }}
  th {{ background: #eef2f5; }}
  blockquote {{ margin: 8pt 0; padding: 6pt 10pt; border-left: 3px solid #0f5d73; background: #f4f7f9; }}
  code {{ font-family: "IBM Plex Mono", Menlo, monospace; font-size: 0.9em; }}
  ul {{ padding-left: 18pt; }} li {{ margin-bottom: 3pt; }}
  mark.fill {{ background: #fff1c2; border: 1px dashed #8a6410; color: #8a6410; padding: 0 3pt; }}
  mark.draft {{ background: #f7e8e6; color: #9b2c2c; font-weight: 700; padding: 0 3pt; font-size: 0.85em; }}
  .toc ol {{ padding-left: 20pt; }} .toc li {{ margin-bottom: 4pt; }}
  .warn, .ok {{ padding: 10pt 14pt; margin: 0 0 18pt; border-left: 4px solid; }}
  .warn {{ background: #f7e8e6; border-color: #9b2c2c; color: #9b2c2c; }}
  .ok {{ background: #e4f0ea; border-color: #1f6b4a; color: #1f6b4a; }}
  .bar {{ display: flex; gap: 10px; align-items: center; margin-bottom: 18pt; }}
  .bar button {{ font: inherit; padding: 8px 16px; background: #0f5d73; color: #fff; border: 0; cursor: pointer; }}
  .bar span {{ color: #4a5b68; font-size: 10pt; }}
  .page-break {{ page-break-before: always; break-before: page; }}
  @media print {{ .no-print {{ display: none !important; }} .sheet {{ padding: 0; max-width: none; }} @page {{ margin: 0.75in; }} }}
</style></head><body><div class="sheet">
<div class="bar no-print"><button onclick="window.print()">Print / Save as PDF</button><span>Cover page, contents, then the statement — page breaks are set.</span></div>
{warn}
<section class="cover">{"".join(blocks(cover))}</section>
<section class="toc page-break"><h2>Contents</h2><ol>{toc_html}</ol></section>
<section class="body page-break">{"".join(blocks(body))}</section>
</div></body></html>"""
