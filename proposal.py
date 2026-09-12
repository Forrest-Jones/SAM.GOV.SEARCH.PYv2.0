#!/usr/bin/env python3
"""
Proposal draft builder.

Turns one SAM.gov notice into a structured response document that's ready
for a human to price, verify, and sign — the step between "here's a
matching contract" and "here's something I can submit."

Two rules this module will not break:

1. Nothing is invented. Every fact about the business (UEI, CAGE, past
   performance, rates, personnel) comes from the company profile the user
   filled in, or it stays a visible [[FILL: ...]] placeholder. A proposal
   with a plausible-sounding but fabricated past-performance reference or
   certification is a false statement on a federal submission, so the
   generator would rather leave a blank that's obviously blank.
2. Nothing is submitted. This writes a file. Submission is a signed,
   human act performed through the channel the solicitation names.
"""

import os
import re
from datetime import date

from company import filled_rows

FILL = "[[FILL: {}]]"

# Section headings commonly used in a PWS/SOW. When the solicitation text
# contains one, the technical approach mirrors the government's own
# structure — evaluators score against their outline, not ours.
PWS_SECTION_HINTS = [
    "scope",
    "background",
    "objectives",
    "tasks",
    "performance requirements",
    "deliverables",
    "period of performance",
    "place of performance",
    "qualifications",
    "key personnel",
    "security",
    "quality control",
    "transition",
    "reporting",
    "travel",
]

DEFAULT_COMPANY_PROFILE = {
    "legal_name": "",
    "uei": "",
    "cage": "",
    "address": "",
    "phone": "",
    "email": "",
    "signatory_name": "",
    "signatory_title": "",
    "certifications_text": "",
    "capability_statement": "",
}


def profile_value(profile, key, label):
    """A real value from the profile, or a conspicuous placeholder."""
    value = (profile or {}).get(key) or ""
    value = value.strip()
    return value if value else FILL.format(label)


def detect_pws_sections(description_text):
    """Returns the PWS_SECTION_HINTS that actually appear in the
    solicitation text, in the order the text presents them, so the
    technical approach can track the government's own outline."""
    if not description_text:
        return []
    lowered = description_text.lower()
    found = []
    for hint in PWS_SECTION_HINTS:
        position = lowered.find(hint)
        if position != -1:
            found.append((position, hint))
    found.sort()
    return [hint for _, hint in found]


def extract_deliverable_lines(description_text, limit=12):
    """Pulls bullet/numbered lines out of the solicitation so the
    requirements traceability table starts from the government's actual
    words rather than a generic list. Returns [] when the text has no
    recognizable list — an empty table the user fills in is better than
    invented requirements."""
    if not description_text:
        return []
    candidates = []
    for raw in description_text.splitlines():
        line = raw.strip()
        if len(line) < 12 or len(line) > 300:
            continue
        if re.match(r"^(\(?[a-z0-9]{1,3}[\).]|[-*•])\s+", line, re.IGNORECASE):
            cleaned = re.sub(r"^(\(?[a-z0-9]{1,3}[\).]|[-*•])\s+", "", line, flags=re.IGNORECASE)
            candidates.append(cleaned.strip())
        if len(candidates) >= limit:
            break
    return candidates


def slugify(text, max_len=50):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
    return s[:max_len] or "opportunity"


def build_proposal_markdown(opp, description_text, profile, score=None, reasons=""):
    """Returns the proposal draft as markdown text."""
    profile = {**DEFAULT_COMPANY_PROFILE, **(profile or {})}
    pop = opp.get("placeOfPerformance") or {}
    city = (pop.get("city") or {}).get("name") or ""
    state = (pop.get("state") or {}).get("code") or ""
    where = ", ".join(p for p in (city, state) if p) or FILL.format("place of performance")
    deadline = (opp.get("responseDeadLine") or "")[:10] or FILL.format("response deadline")
    sections = detect_pws_sections(description_text)
    deliverables = extract_deliverable_lines(description_text)

    lines = [
        f"# Proposal Draft — {opp.get('title') or FILL.format('solicitation title')}",
        "",
        "> **DRAFT — NOT SUBMITTED.** Every highlighted blank below is one only you",
        "> can fill. Nothing here has been sent to the government, and this tool cannot",
        "> send it: federal responses require your signed price and signed reps & certs,",
        "> submitted through the channel the solicitation names.",
        "",
        "## 1. Solicitation reference",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Notice ID | {opp.get('noticeId') or FILL.format('notice ID')} |",
        f"| Solicitation number | {opp.get('solicitationNumber') or FILL.format('solicitation number')} |",
        f"| Agency / office | {opp.get('fullParentPathName') or FILL.format('issuing office')} |",
        f"| NAICS | {opp.get('naicsCode') or FILL.format('NAICS')} |",
        f"| PSC | {opp.get('classificationCode') or FILL.format('PSC')} |",
        f"| Set-aside | {opp.get('typeOfSetAsideDescription') or 'None (full and open)'} |",
        f"| Place of performance | {where} |",
        f"| Response deadline | {deadline} |",
        f"| SAM.gov listing | {opp.get('uiLink') or FILL.format('listing URL')} |",
        f"| Contracting officer | {opp.get('pointOfContact', [{}])[0].get('email') if opp.get('pointOfContact') else FILL.format('CO email — read it off the listing')} |",
        "",
        "**Submit to:** the address or portal named in the solicitation itself —"
        " confirm it on the listing before sending. Do not assume email.",
        "",
        "## 2. Offeror information",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Legal business name | {profile_value(profile, 'legal_name', 'legal business name')} |",
        f"| UEI | {profile_value(profile, 'uei', 'UEI from your SAM.gov registration')} |",
        f"| CAGE code | {profile_value(profile, 'cage', 'CAGE code')} |",
        f"| Address | {profile_value(profile, 'address', 'business address')} |",
        f"| Phone | {profile_value(profile, 'phone', 'phone')} |",
        f"| Email | {profile_value(profile, 'email', 'email')} |",
        f"| Authorized signatory | {profile_value(profile, 'signatory_name', 'signatory name')}, "
        f"{profile_value(profile, 'signatory_title', 'title')} |",
        "",
        "## 3. Cover letter",
        "",
        f"{date.today().strftime('%B %-d, %Y') if os.name != 'nt' else date.today().strftime('%B %d, %Y')}",
        "",
        f"{FILL.format('Contracting Officer name')}",
        f"{opp.get('fullParentPathName') or FILL.format('issuing office')}",
        "",
        f"**Subject:** Response to {opp.get('solicitationNumber') or FILL.format('solicitation number')}, "
        f"{opp.get('title') or ''}",
        "",
        f"{profile_value(profile, 'legal_name', 'legal business name')} is pleased to submit this "
        "response. We have reviewed the requirement in full and confirm our ability to perform "
        "within the stated period and place of performance.",
        "",
        (profile.get("capability_statement") or "").strip()
        or FILL.format("2-3 sentences on why you're qualified — paste your capability statement into Settings so this fills itself in"),
        "",
        f"This offer remains valid for {FILL.format('number')} days. Questions may be directed to "
        f"{profile_value(profile, 'signatory_name', 'signatory name')} at "
        f"{profile_value(profile, 'phone', 'phone')} or {profile_value(profile, 'email', 'email')}.",
        "",
        "Respectfully,",
        "",
        f"{FILL.format('SIGNATURE — wet or digital, applied by the authorized signatory')}",
        f"{profile_value(profile, 'signatory_name', 'signatory name')}, "
        f"{profile_value(profile, 'signatory_title', 'title')}",
        "",
        "## 4. Technical approach",
        "",
    ]

    if sections:
        lines.append(
            "The solicitation text references the sections below. Answer them in the "
            "government's order — evaluators score against their own outline."
        )
        lines.append("")
        for heading in sections:
            lines.append(f"### {heading.title()}")
            lines.append("")
            lines.append(FILL.format(f"your approach to '{heading}' — cite the PWS paragraph you're answering"))
            lines.append("")
    else:
        lines += [
            "The full solicitation text wasn't machine-readable, so this falls back to a "
            "standard outline. Replace these headings with the solicitation's own.",
            "",
            "### Understanding of the requirement",
            "",
            FILL.format("restate the government's need in your own words"),
            "",
            "### Technical approach",
            "",
            FILL.format("how you will perform the work, task by task"),
            "",
            "### Staffing and key personnel",
            "",
            FILL.format("who performs the work, and their qualifications against the stated requirements"),
            "",
            "### Quality control",
            "",
            FILL.format("how you will ensure and measure performance"),
            "",
        ]

    lines += [
        "## 5. Requirements traceability",
        "",
        "One row per stated requirement, so nothing in the PWS goes unanswered — the "
        "most common reason a technically capable bid loses.",
        "",
        "| # | Requirement (from the solicitation) | Where answered | Can we perform? |",
        "|---|---|---|---|",
    ]
    if deliverables:
        for i, item in enumerate(deliverables, 1):
            short = item if len(item) <= 140 else item[:137] + "..."
            lines.append(f"| {i} | {short} | {FILL.format('section')} | {FILL.format('yes/no/partial')} |")
    else:
        lines.append(
            f"| 1 | {FILL.format('paste each requirement from the PWS — no list was detectable in the text')} "
            f"| {FILL.format('section')} | {FILL.format('yes/no/partial')} |"
        )

    lines += [
        "",
        "## 6. Past performance",
        "",
        "**Only real, verifiable contracts belong here.** Three references is the usual ask.",
        "",
        "| # | Customer | Contract # | Value | Period | Scope relevance | Reference contact |",
        "|---|---|---|---|---|---|---|",
    ]
    references = filled_rows(profile, "past_performance")
    for i in range(1, 4):
        ref = references[i - 1] if i <= len(references) else {}
        contact = ", ".join(
            str(ref.get(k) or "").strip()
            for k in ("ref_name", "ref_phone", "ref_email")
            if str(ref.get(k) or "").strip()
        )
        lines.append(
            f"| {i} "
            f"| {ref.get('customer') or FILL.format('customer')} "
            f"| {ref.get('contract') or FILL.format('contract number')} "
            f"| {ref.get('value') or FILL.format('$ value')} "
            f"| {ref.get('period') or FILL.format('start–end')} "
            # Relevance is per-solicitation by definition: the same contract
            # is relevant to this requirement for a different reason than to
            # the last one, so the stored scope is offered as a starting
            # point and the tailoring stays a blank.
            f"| {(str(ref.get('scope') or '').strip() + ' — ') if ref.get('scope') else ''}"
            f"{FILL.format('why it is relevant to THIS requirement')} "
            f"| {contact or FILL.format('name, phone, email')} |"
        )

    lines += [
        "",
        "## 7. Price proposal",
        "",
        "**Your numbers, your commitment.** This worksheet is deliberately empty: a price "
        "is a binding offer, and a guessed rate either loses the bid or wins work you "
        "can't deliver profitably.",
        "",
        "| Labor category | Qty / hours | Unit | Rate | Extended |",
        "|---|---|---|---|---|",
    ]
    rate_card = filled_rows(profile, "rate_card")
    if rate_card:
        # Rates come from the fact bank; hours are the only genuinely
        # per-solicitation number, so they are the only blank left here.
        for row in rate_card:
            lines.append(
                f"| {row.get('category')} | {FILL.format('hours')} | "
                f"{row.get('unit') or 'hr'} | {row.get('rate')} | {FILL.format('$total')} |"
            )
    else:
        for _ in range(4):
            lines.append(
                f"| {FILL.format('category')} | {FILL.format('hours')} | {FILL.format('hr/ea')} | "
                f"{FILL.format('$rate')} | {FILL.format('$total')} |"
            )
    lines += [
        f"| **Total** | | | | **{FILL.format('$ total offered price')}** |",
        "",
        f"- Other direct costs: {FILL.format('travel, materials, ODCs — or state none')}",
        f"- Basis of estimate: {FILL.format('how you built this price')}",
        f"- Wage determination applied: {FILL.format('SCA/Davis-Bacon WD number if the solicitation attaches one')}",
        "",
        "## 8. Representations and certifications",
        "",
        "Check each against your live SAM.gov registration before signing. A stale or "
        "inaccurate cert on a federal submission is a legal exposure, not a formality.",
        "",
        "- [ ] SAM.gov registration active, and UEI/CAGE above match it exactly",
        "- [ ] Reps & certs in SAM.gov current as of today",
        f"- [ ] Size standard confirmed for NAICS {opp.get('naicsCode') or FILL.format('NAICS')}"
        " (check the SBA table — it varies by code)",
    ]
    set_aside = opp.get("typeOfSetAsideDescription")
    if set_aside:
        lines.append(
            f"- [ ] Certification actually held for this set-aside: **{set_aside}** "
            "(the matching tool flags this heuristically from notice text — verify it yourself)"
        )
    lines += [
        "- [ ] No active exclusions/debarment",
        f"- [ ] SAM registration active through {profile.get('sam_registration_expires') or FILL.format('SAM expiry date')}",
        "- [ ] Any required solicitation-specific forms completed (SF-1449, SF-33, etc.)",
        (profile.get("certifications_text") or "").strip(),
        "",
        "## 9. Insurance and bonding",
        "",
        "Requested on most commercial-item buys. Values come from the fact bank.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Carrier | {profile_value(profile, 'insurance_carrier', 'insurance carrier')} |",
        f"| General liability | {profile_value(profile, 'insurance_gl_limit', 'GL limit')} |",
        f"| Workers compensation | {profile_value(profile, 'workers_comp', 'workers comp')} |",
        f"| Bonding (single / aggregate) | {profile.get('bonding_capacity_single') or 'n/a'}"
        f" / {profile.get('bonding_capacity_total') or 'n/a'} |",
        "",
        "## 10. Submission checklist",
        "",
        f"- [ ] Confirmed submission method and address from the solicitation (not assumed)",
        f"- [ ] Submitted before the deadline: **{deadline}** (confirm the time zone)",
        "- [ ] All attachments the solicitation requires are included",
        "- [ ] Price signed by the authorized signatory",
        "- [ ] Copy retained for your records",
        "",
        "---",
        "",
        f"_Draft generated {date.today().isoformat()} from SAM.gov notice "
        f"{opp.get('noticeId') or 'unknown'}"
        + (f" (triage score {score}: {reasons})" if score is not None else "")
        + "._ _Not a submission._",
        "",
    ]
    return "\n".join(line for line in lines if line is not None)


def write_proposal(opp, description_text, profile, proposals_dir, score=None, reasons=""):
    """Writes the draft and returns its path. Never overwrites an existing
    draft — the user may already be editing it."""
    os.makedirs(proposals_dir, exist_ok=True)
    nid = opp.get("noticeId") or "unknown"
    path = os.path.join(proposals_dir, f"{nid}-{slugify(opp.get('title'))}-proposal.md")
    if os.path.exists(path):
        return path
    with open(path, "w") as f:
        f.write(build_proposal_markdown(opp, description_text, profile, score, reasons))
    return path
