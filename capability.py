#!/usr/bin/env python3
"""
Capability statement responses to Sources Sought notices and RFIs.

A Sources Sought is market research, not a solicitation — there are no
line items, no award, and a priced quote in response is a category error.
The belt refuses to build bid packets for them, which is right, and for a
while meant they vanished from the tray entirely, which was wrong: they
are often the best available opening, and for a firm with no federal past
performance they may be the only realistic one.

Responding costs no price commitment and carries no certification risk.
It puts the company in the record the government reads while writing the
eventual solicitation, and it is where the NAICS/PSC/set-aside decisions
for that solicitation actually get made — most notices explicitly invite
comment on them.

Same two invariants as the proposal builder: nothing about the business is
invented, and nothing is sent.
"""

import os
import re
from datetime import date

from company import filled_rows, held_credentials

FILL = "[[FILL: {}]]"

# Sources Sought notices almost always carry a numbered or lettered list
# of questions, and answering them one for one is the whole substance of a
# good response. Evaluators read for their own questions, in their order.
QUESTION_RE = re.compile(
    r"(?:^|\s)((?:[a-z]|[ivx]{1,4}|\d{1,2})[.)]\s+[A-Z][^?]{15,400}\?)",
    re.MULTILINE,
)


def extract_questions(text, limit=25):
    """The notice's own questions, in the order it asks them.

    Returns [] when none are detectable rather than inventing a generic
    set — a response that answers questions the government did not ask
    reads as boilerplate, which is what these notices are screening out.
    """
    if not text:
        return []
    found, seen = [], set()
    for match in QUESTION_RE.finditer(text):
        question = re.sub(r"\s+", " ", match.group(1)).strip()
        question = re.sub(r"^(?:[a-z]|[ivx]{1,4}|\d{1,2})[.)]\s+", "", question)
        key = question.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        found.append(question)
        if len(found) >= limit:
            break
    return found


def build_capability_markdown(opp, description_text, company, notice_kind=""):
    """The response document, structured to what these notices ask for:
    a cover page, a company profile, a capability narrative, and answers
    to the notice's own questions."""
    deadline = (opp.get("responseDeadLine") or "")[:10] or FILL.format("response date")
    sol = opp.get("solicitationNumber") or opp.get("noticeId") or FILL.format("notice number")
    questions = extract_questions(description_text)
    credentials = held_credentials(company)
    references = filled_rows(company, "past_performance")

    def value(key, label):
        got = str((company or {}).get(key) or "").strip()
        return got or FILL.format(label)

    lines = [
        f"# Capability Statement — {opp.get('title') or FILL.format('notice title')}",
        "",
        f"> **{notice_kind or 'Sources Sought'} response. This is not a bid and contains no price.**",
        "> Responding is voluntary market research. It is also how a small business",
        "> gets into the record the government reads while writing the solicitation,",
        "> and where the NAICS, PSC and set-aside decisions for it are still open.",
        "",
        "## Cover page",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Date of submission | {date.today().isoformat()} |",
        f"| Notice / solicitation number | {sol} |",
        f"| Notice title | {opp.get('title') or ''} |",
        f"| Response due | {deadline} |",
        f"| Company | {value('legal_name', 'legal business name')} |",
        f"| Address | {value('address', 'business address')} |",
        f"| UEI | {value('uei', 'UEI')} |",
        f"| CAGE | {value('cage', 'CAGE code')} |",
        f"| Point of contact | {value('signatory_name', 'name')}, "
        f"{value('signatory_title', 'title')} |",
        f"| Phone / email | {value('phone', 'phone')} / {value('email', 'email')} |",
        f"| Business size | Small business for NAICS {opp.get('naicsCode') or FILL.format('NAICS')} "
        "(self-certified in SAM.gov against the size standard) |",
        f"| Socio-economic status | {FILL.format('state only what is actually certified — leave blank if none')} |",
        "",
        "## Company profile",
        "",
        (company.get("capability_statement") or "").strip()
        or FILL.format("2-3 paragraphs: what the firm does, for whom, and the depth behind it "
                       "— put this in company.toml so it fills itself in on every response"),
        "",
    ]

    if credentials:
        lines += ["**Credentials held**", ""]
        for credential in credentials:
            detail = f" — {credential['identifier']}" if credential["identifier"] else ""
            lines.append(f"- {credential['label']}: {credential['holder']}{detail}")
        lines.append("")

    lines += [
        "## Relevant experience",
        "",
        "Market research notices are screening for demonstrated capability, so",
        "general statements are discounted. Each entry needs scope, size and",
        "who can confirm it.",
        "",
        "| # | Customer | Contract / order | Value | Period | Scope, and why it is relevant here |",
        "|---|---|---|---|---|---|",
    ]
    for i in range(1, 4):
        ref = references[i - 1] if i <= len(references) else {}
        lines.append(
            f"| {i} | {ref.get('customer') or FILL.format('customer')} "
            f"| {ref.get('contract') or FILL.format('contract number')} "
            f"| {ref.get('value') or FILL.format('$ value')} "
            f"| {ref.get('period') or FILL.format('start–end')} "
            f"| {(str(ref.get('scope') or '').strip() + ' — ') if ref.get('scope') else ''}"
            f"{FILL.format('why it is relevant to THIS requirement')} |"
        )

    lines += [
        "",
        f"- Commercial (non-federal) work counts here: {FILL.format('list it if federal past performance is thin — say so plainly rather than leaving a gap')}",
        "",
        "## Answers to the notice's questions",
        "",
    ]

    if questions:
        lines += [
            "Taken from the notice itself, in its order. Evaluators read for their",
            "own questions — answering them one for one is the substance of the",
            "response.",
            "",
        ]
        for i, question in enumerate(questions, 1):
            lines += [
                f"**{i}. {question}**",
                "",
                FILL.format("your answer"),
                "",
            ]
    else:
        lines += [
            "No numbered questions were detectable in the notice text, which means",
            "either it asks none or they are inside an attachment. Open the notice",
            "and check before submitting — unanswered questions are the most common",
            "reason a capability statement is set aside.",
            "",
            f"- {FILL.format('paste each question from the notice and answer it')}",
            "",
        ]

    lines += [
        "## Capacity and approach",
        "",
        f"- Staffing available for this scope: {FILL.format('how many people, in what roles')}",
        f"- Ability to scale: {FILL.format('what you would add, and how quickly')}",
        f"- Teaming or subcontracting intent: {FILL.format('prime alone, prime with subs, or sub to another prime')}",
        f"- Place of performance you can support: {FILL.format('on-site, remote, or both')}",
        "",
        "## Comment on the acquisition strategy",
        "",
        "These notices usually invite this explicitly, and it is the part with",
        "real leverage: the NAICS code, PSC, set-aside and contract type are",
        "still being decided when market research is running.",
        "",
        f"- Suggested NAICS / PSC, if different: {FILL.format('code and why — or state that the proposed codes fit')}",
        f"- Set-aside recommendation: {FILL.format('what you would recommend and why')}",
        f"- Anything in the draft PWS that would limit competition: {FILL.format('or state none')}",
        "",
        "---",
        "",
        "**Not a bid. No price is offered and none is implied.** Submit only through",
        "the method the notice names, by the date above.",
        "",
        f"_Prepared {date.today().isoformat()} from SAM.gov notice "
        f"{opp.get('noticeId') or 'unknown'}._",
        "",
    ]
    return "\n".join(lines)
