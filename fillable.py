#!/usr/bin/env python3
"""
Turning a packet's [[FILL: ...]] markers into something a browser can edit.

The proposal draft is markdown with visible blanks. Working through them in
a text editor means hunting for a string 54 times. This module exposes them
as an addressable list so the web UI can render one labelled field per
blank, and writes answers back into the same markdown — no second copy of
the document, so the file on disk stays the single source of truth.

Filling is index-addressed and label-verified. The browser holds a snapshot
that may be stale (the file can change underneath it), so every write says
which blank it means AND what that blank was labelled; a mismatch is
refused rather than silently writing an answer into the wrong hole. On a
federal submission, a price landing in the period-of-performance field is
not a cosmetic bug.
"""

import re

FILL_RE = re.compile(r"\[\[FILL: (.*?)\]\]", re.DOTALL)

# Markdown heading immediately above a blank, used to group the form.
HEADING_RE = re.compile(r"^#{1,4}\s+(.*)$")


def _sections(text):
    """Line index -> the nearest heading above it."""
    current = ""
    out = []
    for line in text.split("\n"):
        match = HEADING_RE.match(line)
        if match:
            current = match.group(1).strip()
        out.append(current)
    return out


def blanks(text):
    """Every blank in document order.

    Each entry carries the label (what to supply), the section it sits in,
    and the line it appears on with the marker itself stripped out, which
    is what makes a bare label like "hours" or "section" intelligible.
    """
    sections = _sections(text)
    line_starts, position = [], 0
    for line in text.split("\n"):
        line_starts.append(position)
        position += len(line) + 1

    found = []
    for index, match in enumerate(FILL_RE.finditer(text)):
        line_no = max(i for i, start in enumerate(line_starts) if start <= match.start())
        line = text.split("\n")[line_no]
        found.append({
            "index": index,
            "label": match.group(1).strip(),
            "section": sections[line_no],
            "context": FILL_RE.sub("____", line).strip()[:240],
            "multiline": len(match.group(1)) > 60,
        })
    return found


class FillMismatch(Exception):
    """The blank at that index is not the one the browser thought it was."""


def fill(text, answers):
    """Writes answers into the markdown.

    `answers` maps blank index -> {"label": str, "value": str}. The label is
    checked against the document; a mismatch raises rather than writing to
    the wrong place. An empty value leaves the blank alone, so a partially
    completed form does not erase the markers it did not touch.
    """
    matches = list(FILL_RE.finditer(text))
    out, cursor = [], 0

    for index, match in enumerate(matches):
        answer = answers.get(index) or answers.get(str(index))
        if not answer:
            continue
        value = str(answer.get("value") or "")
        if not value.strip():
            continue
        expected = (answer.get("label") or "").strip()
        actual = match.group(1).strip()
        if expected and expected != actual:
            raise FillMismatch(
                f"blank {index} is now {actual!r}, not {expected!r} — "
                "the file changed since the page loaded, so nothing was written"
            )
        out.append(text[cursor:match.start()])
        out.append(value.strip())
        cursor = match.end()

    out.append(text[cursor:])
    return "".join(out)


def progress(text):
    """(filled, total) for this document, where total is what it started
    with — derived by counting what is left plus what has been answered is
    not knowable from the text alone, so this reports what remains."""
    return len(FILL_RE.findall(text))


PRICE_HEADER = "| Labor category | Qty / hours | Unit | Rate | Extended |"


def write_price_table(text, rows, total=None):
    """Replaces the proposal's price table with the priced rows.

    Without this the price section's blanks appear in the fill-in form as
    two dozen bare boxes labelled "category", "hours", "$rate" — a second,
    worse copy of the price sheet the user just filled in. One price, one
    place to enter it.

    Rows are dicts with category/unit/rate/hours. Extended is computed here
    so the document agrees with the spreadsheet; a row missing either
    number keeps an empty cell rather than showing a guess.
    """
    lines = text.split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == PRICE_HEADER)
    except StopIteration:
        return text

    # The separator row follows the header; data rows run until the Total.
    body_start = start + 2
    body_end = body_start
    while body_end < len(lines) and lines[body_end].startswith("|"):
        if "**Total**" in lines[body_end]:
            break
        body_end += 1

    def number(value):
        cleaned = re.sub(r"[^0-9.\-]", "", str(value or ""))
        try:
            return float(cleaned)
        except ValueError:
            return None

    rendered, computed = [], 0.0
    for row in rows:
        rate, qty = number(row.get("rate")), number(row.get("hours"))
        extended = ""
        if rate is not None and qty is not None:
            value = rate * qty
            computed += value
            extended = f"${value:,.2f}"
        rendered.append(
            f"| {row.get('category') or ''} | {row.get('hours') or ''} "
            f"| {row.get('unit') or 'hr'} | {row.get('rate') or ''} | {extended} |"
        )

    total_text = total if total is not None else (f"${computed:,.2f}" if computed else "")
    total_row = f"| **Total** | | | | **{total_text}** |"

    tail = lines[body_end:]
    if tail and "**Total**" in tail[0]:
        tail = tail[1:]
    return "\n".join(lines[:body_start] + rendered + [total_row] + tail)
