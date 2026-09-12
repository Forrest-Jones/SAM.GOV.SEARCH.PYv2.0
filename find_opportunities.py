#!/usr/bin/env python3
"""
SAM.gov Opportunity Finder — Proverbs 1821 Consulting LLC (tax / accounting / evaluation lanes)

Pulls open SAM.gov solicitations, sources-sought, and presolicitations
under the NAICS set that matches:
  - Lane 1: Installation tax center support (Randy White performs)
  - Lane 2: Accounting / tax remediation task orders (Randy leads)
  - Lane 3: Third-party program evaluation (Forrest / Blackwater Evaluation)

Runs entirely on your machine (or in the scheduled GitHub Action — see
.github/workflows/daily-search.yml). Claude's sandbox can't reach
api.sam.gov (egress proxy returns host_not_allowed), so nothing here is
called from Claude's side.

Ares Robotics' separate NAICS set (562998, 562910, 562211, 811310,
333998 / PSC F108, J039) is NOT included here. Say the word if you want
a --profile flag to switch between the two, or a second script.

This tool finds and triages opportunities and drafts a review scaffold
for the promising ones. It never submits anything. SAM.gov has no API
for bid submission — federal proposal submission is a signed, human
process (technical response, priced proposal, reps/certs), so the last
mile stays manual by design.

SETUP
-----
1. pip install -r requirements.txt
2. export SAM_API_KEY="your-key-here"
   Get one at sam.gov -> Account Details -> Get API Key (free, 1,000
   calls/day). If a key has ever been pasted into a chat, rotate it in
   your SAM.gov account before using it here.
3. (optional, for email digests) export GMAIL_USER and GMAIL_APP_PASSWORD
   — see README for how to create a Gmail App Password.
4. python3 find_opportunities.py

OPTIONS
-------
  --posted-days N       How many days back to search postings (default 45)
  --deadline-min N      Skip anything closing sooner than N days (default 7)
  --deadline-max N      Skip anything closing later than N days (default 60)
  --naics CODE[,CODE]   Override the default NAICS list
  --csv PATH            Also write full ranked results to a CSV file
  --limit N             Max results per NAICS call (default 100)
  --max-retries N       Retry attempts per API call on 429/5xx/network error (default 4)
  --db PATH             SQLite state file tracking previously-seen notices (default state.sqlite3)
  --drafts-dir PATH     Where to write review scaffolds for new high scorers (default drafts)
  --draft-min-score N   Minimum score to generate a draft scaffold (default 4)
  --no-drafts           Skip draft generation entirely
  --include-restricted-set-asides
                        Also show set-asides you're not certified for (8(a), HUBZone,
                        SDVOSB, etc). Excluded by default so they don't clutter results.
  --email               Force-send the email digest even if unchanged from defaults
  --no-email            Never send an email, even if GMAIL_APP_PASSWORD is set
  --to EMAIL            Digest recipient (default forrestjones2010@gmail.com)

OUTPUT
------
Ranked shortlist printed to the terminal, optionally written to CSV.
New (never-before-seen) high scorers get a markdown review scaffold in
--drafts-dir and, if configured, an email digest.

The score is a triage heuristic, not a bid decision — read the actual
PWS/SOW before committing capture time to anything, and confirm your
own eligibility (size standard, set-aside certification) before
treating anything here as biddable.
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
from datetime import date, timedelta

import requests

API_URL = "https://api.sam.gov/opportunities/v2/search"

# Every NAICS code in this entity's SAM.gov registration (CAGE 22ND2),
# assembled from the registration audit's four events.
#
# The audit's open question — whether the 8/19/26 update replaced or merely
# supplemented the 541-series — is resolved: it ADDED. The registration has
# only ever grown, never shrunk, so these are codes actually carried today,
# not just a defensive search net. (Confirmed by the registrant, 9/12/26.)
#
# Two items still worth confirming against sam.gov -> Entity Management ->
# Assertions before a bid leans on them: the 9/9/26 set was recorded as
# recommended but never confirmed as entered, and 541211 never appeared in
# the audit at all. Searching them costs nothing either way; certifying size
# standard or set-aside status against them does.
DEFAULT_NAICS = [
    # --- Initial registration, ~7/7/26 ---
    "541611",  # Admin & General Management Consulting (was primary)
    "541618",  # Other Management Consulting
    "541990",  # Other Professional/Scientific/Technical Services
    "541720",  # R&D in Social Sciences & Humanities
    # --- Found live in the record 7/27/26 (the flagged discrepancy) ---
    "541613",  # Marketing Consulting (was showing as primary)
    "541612",  # HR Consulting
    "541614",  # Logistics Consulting
    "541620",  # Environmental Consulting (retained through the 8/19 update)
    "541690",  # Other Scientific & Technical Consulting
    # --- Update submitted 7/27/26, confirmed live 8/19/26 (Ares Robotics) ---
    "562998",  # All Other Misc. Waste Management (new primary)
    "562910",  # Remediation Services
    "562211",  # Hazardous Waste Treatment & Disposal
    "811310",  # Commercial & Industrial Machinery Repair
    "333998",  # All Other General Purpose Machinery Mfg (corrected from 333999)
    # --- Recommended 9/9/26 — still unconfirmed as entered ---
    "541213",  # Tax Preparation Services
    "541219",  # Other Accounting Services
    "238190",  # Other Building Exterior Contractors — raised as a maybe for
               # the welder's structural work. A construction trade, so expect
               # this to be the noisiest code in the set.
    # --- Not in the registration audit, carried over from the original script.
    # Kept because it is already producing relevant work: the Coast Guard
    # Academy NAFI audit came in on this code. ---
    "541211",  # Offices of Certified Public Accountants
]

# PSC codes worth a point. R710/B505/R499 came from the original script;
# R407, F108 and J039 are from the registration audit. (Z2AZ was pulled
# before entry, so it is deliberately absent.)
PRIORITY_PSC = {"R710", "B505", "R499", "R407", "F108", "J039"}
NOTICE_TYPES = "p,k,r"  # presolicitation, combined synopsis/solicitation, sources sought

# Title keywords worth a point each (capped at 2). The first group serves the
# tax/accounting/evaluation lanes; the second was added alongside the
# industrial NAICS codes, since without it those notices never score high
# enough to generate a review packet.
#
# Kept deliberately narrow. An earlier version added "repair", "machinery"
# and "disposal", which scored commodity purchases ("43 Filter Element
# Fluid", "Grease Tank Pumping") high enough to generate review packets —
# a keyword has to describe the WORK, not merely appear near it.
KEYWORDS = [
    "tax", "vita", "evaluation", "accounting", "financial", "audit", "irs",
    "remediation", "hazardous waste", "environmental", "abatement",
]
HOME_STATES = {"TX"}  # small bonus only — best current template (McConnell AFB) is in KS

# Product Service Codes are letter-prefixed for services (R499, B505, F108,
# J039) and digit-prefixed for supplies and equipment (4330, 4730). This
# business sells services, so digit-prefixed notices are parts buys and get
# dropped by default. Adding the industrial NAICS codes pulled in dozens of
# them — filter elements, strainer elements, parts kits — because a
# small-business set-aside parts buy in Texas with a near deadline scores
# just as well as real services work.
def is_supply_notice(opp):
    psc = (opp.get("classificationCode") or "").strip()
    return bool(psc) and psc[0].isdigit()

# Strings SAM.gov actually uses to mean "no set-aside, open to everyone".
# The API sends these as literal text rather than an empty field, so without
# this they read as some unrecognized set-aside program.
NO_SET_ASIDE_PHRASES = {
    "",
    "no set aside used",
    "none",
    "n a",
    "not applicable",
    "full and open",
    "full and open competition",
}

# Certification programs, each with the phrases (in normalized form — see
# normalize_set_aside) that identify a notice as reserved for that program.
# The web UI shows these as checkboxes, so changing what you're certified
# for never requires touching code.
CERTIFICATION_HINTS = {
    "small_business": {
        "label": "Small Business (general set-asides)",
        # Real SAM.gov values include "Small Business Set Aside - Total" and
        # "Total Small Business Set-Aside"; normalization flattens both.
        "hints": ("small business set aside", "total small business"),
    },
    "wosb": {
        "label": "Woman-Owned Small Business (WOSB)",
        "hints": ("woman owned", "women owned", "wosb"),
    },
    "edwosb": {
        "label": "Economically Disadvantaged WOSB (EDWOSB)",
        "hints": ("economically disadvantaged women", "edwosb"),
    },
    "8a": {
        "label": "8(a) Business Development",
        "hints": ("8(a)", "8 a "),
    },
    "hubzone": {
        "label": "HUBZone",
        "hints": ("hubzone", "hub zone"),
    },
    "sdvosb": {
        "label": "Service-Disabled Veteran-Owned Small Business (SDVOSB)",
        "hints": ("service disabled veteran", "sdvosb"),
    },
    "vosb": {
        "label": "Veteran-Owned Small Business (VOSB)",
        "hints": ("veteran owned",),
    },
}

# Every program above is a small-business program, so holding any of them
# means the business qualifies for a generic small-business set-aside too.
# Without this, a WOSB-only profile would treat every "Small Business Set
# Aside - Total" notice as ineligible and hide it.
SMALL_BUSINESS_IMPLYING_CERTS = frozenset(CERTIFICATION_HINTS) - {"small_business"}

DEFAULT_HELD_CERTS = ("small_business", "wosb", "edwosb")


def normalize_set_aside(text):
    """Flattens SAM.gov's inconsistent set-aside phrasing to one comparable
    form. "Small Business Set-Aside", "Small Business Set Aside - Total" and
    "Total Small Business Set-Aside" all reduce to text these hints match.
    Parentheses survive so "8(a)" stays distinguishable."""
    return re.sub(r"[^a-z0-9()]+", " ", (text or "").lower()).strip()


def classify_set_aside(opp):
    """Which certification programs a notice is reserved for.

    Returns None when the notice is open to everyone, otherwise the set of
    CERTIFICATION_HINTS keys it matches (empty set = a set-aside we don't
    recognize). Classifying the notice first, and only then comparing
    against what the user holds, avoids one program's phrasing shadowing
    another's — "veteran owned" sits inside "service disabled veteran
    owned", so SDVOSB is resolved explicitly below.
    """
    normalized = normalize_set_aside(opp.get("typeOfSetAsideDescription"))
    if normalized in NO_SET_ASIDE_PHRASES:
        return None

    matched = set()
    for key, info in CERTIFICATION_HINTS.items():
        if any(hint in normalized for hint in info["hints"]):
            matched.add(key)

    # "service disabled veteran owned" also contains "veteran owned", so a
    # SDVOSB notice would otherwise look like a VOSB one as well.
    if "sdvosb" in matched:
        matched.discard("vosb")
    # EDWOSB text mentions women-owned too; both apply, but EDWOSB is the
    # stricter requirement, so a WOSB-only holder must not read as eligible.
    if "edwosb" in matched:
        matched.discard("wosb")

    return matched


def eligibility(opp, held_certs=DEFAULT_HELD_CERTS):
    """full_open | eligible_set_aside | unknown_set_aside | restricted"""
    programs = classify_set_aside(opp)
    if programs is None:
        return "full_open"
    if not programs:
        return "unknown_set_aside"

    held = set(held_certs)
    if held & SMALL_BUSINESS_IMPLYING_CERTS:
        held.add("small_business")

    return "eligible_set_aside" if programs & held else "restricted"


DEFAULT_DB_PATH = "state.sqlite3"
DEFAULT_DRAFTS_DIR = "drafts"
DEFAULT_TO_EMAIL = "forrestjones2010@gmail.com"

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    notice_id TEXT PRIMARY KEY,
    title TEXT,
    naics TEXT,
    score INTEGER,
    first_seen TEXT,
    last_seen TEXT,
    deadline TEXT,
    link TEXT
)
"""


def request_with_retry(params, max_retries):
    """GET API_URL with exponential backoff on 429/5xx/network errors.
    Returns the Response, or None if every attempt failed."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                print(f"  [network error, giving up after {max_retries} attempts: {e}]", file=sys.stderr)
                return None
            wait = 2 ** attempt
            print(f"  [network error, retry {attempt}/{max_retries} in {wait}s: {e}]", file=sys.stderr)
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            if attempt == max_retries:
                print(f"  [rate limited, giving up after {max_retries} attempts]", file=sys.stderr)
                return None
            wait = int(resp.headers.get("Retry-After") or 2 ** attempt)
            print(f"  [rate limited, retry {attempt}/{max_retries} in {wait}s]", file=sys.stderr)
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            if attempt == max_retries:
                print(f"  [server error {resp.status_code}, giving up after {max_retries} attempts]", file=sys.stderr)
                return None
            wait = 2 ** attempt
            print(f"  [server error {resp.status_code}, retry {attempt}/{max_retries} in {wait}s]", file=sys.stderr)
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp
    return None


def fetch(naics_code, posted_from, posted_to, api_key, limit, max_retries):
    """Pull all pages for one NAICS code. ncode is queried one at a time —
    combining multiple codes in a single call has been unreliable before."""
    results = []
    offset = 0
    while True:
        params = {
            "api_key": api_key,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "ncode": naics_code,
            "ptype": NOTICE_TYPES,
            "limit": limit,
            "offset": offset,
        }
        resp = request_with_retry(params, max_retries)
        if resp is None:
            break
        data = resp.json()
        batch = data.get("opportunitiesData", [])
        results.extend(batch)
        total = data.get("totalRecords", len(batch))
        offset += limit
        if offset >= total or not batch:
            break
    return results


def days_until_deadline(opp):
    """Days from today until the response deadline, or None when the notice
    has no parseable deadline (common on sources-sought notices)."""
    raw = opp.get("responseDeadLine")
    if not raw:
        return None
    try:
        return (date.fromisoformat(raw[:10]) - date.today()).days
    except ValueError:
        return None


def score(opp, deadline_min, deadline_max, held_certs=DEFAULT_HELD_CERTS):
    pts = 0
    reasons = []

    elig = eligibility(opp, held_certs)
    if elig == "eligible_set_aside":
        pts += 2
        reasons.append(f"set-aside ({opp.get('typeOfSetAsideDescription')}) — eligible")
    elif elig == "unknown_set_aside":
        reasons.append(f"set-aside ({opp.get('typeOfSetAsideDescription')}) — verify eligibility")

    days_left = days_until_deadline(opp)
    if days_left is not None and deadline_min <= days_left <= deadline_max:
        pts += 2
        reasons.append(f"{days_left}d to deadline")

    if opp.get("classificationCode") in PRIORITY_PSC:
        pts += 1
        reasons.append("PSC match")

    title = (opp.get("title") or "").lower()
    hits = sum(1 for kw in KEYWORDS if kw in title)
    if hits:
        pts += min(hits, 2)
        reasons.append(f"{hits} keyword match" + ("es" if hits > 1 else ""))

    pop = opp.get("placeOfPerformance") or {}
    state = (pop.get("state") or {}).get("code")
    if state in HOME_STATES:
        pts += 1
        reasons.append("TX")

    return pts, ", ".join(reasons)


def open_state(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(STATE_SCHEMA)
    conn.commit()
    return conn


def diff_and_record(conn, ranked):
    """Marks which ranked (pts, reasons, opp) tuples are new since the
    last run, records them, and refreshes score/last_seen for the rest."""
    new_ones = []
    now = date.today().isoformat()
    for pts, reasons, opp in ranked:
        nid = opp.get("noticeId")
        if not nid:
            continue
        row = conn.execute("SELECT notice_id FROM seen WHERE notice_id = ?", (nid,)).fetchone()
        if row is None:
            new_ones.append((pts, reasons, opp))
            conn.execute(
                "INSERT INTO seen (notice_id, title, naics, score, first_seen, last_seen, deadline, link) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    nid,
                    opp.get("title"),
                    opp.get("naicsCode"),
                    pts,
                    now,
                    now,
                    (opp.get("responseDeadLine") or "")[:10],
                    opp.get("uiLink"),
                ),
            )
        else:
            conn.execute("UPDATE seen SET last_seen = ?, score = ? WHERE notice_id = ?", (now, pts, nid))
    conn.commit()
    return new_ones


def fetch_description(opp, api_key):
    """Best-effort full-text description fetch. The v2 search response
    only gives a URL to the v1 noticedesc endpoint — this hits it once
    per draft candidate (not per result) to stay well under the daily
    call budget."""
    url = opp.get("description")
    if not url:
        return None
    try:
        resp = requests.get(url, params={"api_key": api_key}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("description") or data.get("body")
        return str(data)
    except Exception as e:
        print(f"  [could not fetch description for {opp.get('noticeId')}: {e}]", file=sys.stderr)
        return None


def slugify(text, max_len=50):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text or "").strip("-").lower()
    return s[:max_len] or "opportunity"


def write_draft(opp, pts, reasons, elig, description_text, drafts_dir):
    os.makedirs(drafts_dir, exist_ok=True)
    nid = opp.get("noticeId") or "unknown"
    path = os.path.join(drafts_dir, f"{nid}-{slugify(opp.get('title'))}.md")
    if os.path.exists(path):
        return path  # don't clobber a draft that may already be in progress

    pop = opp.get("placeOfPerformance") or {}
    links = opp.get("resourceLinks") or []

    lines = [
        f"# {opp.get('title')}",
        "",
        f"- **Score:** {pts} ({reasons or 'no heuristic matches'})",
        f"- **Eligibility:** {elig}",
        f"- **NAICS:** {opp.get('naicsCode')}  **PSC:** {opp.get('classificationCode')}",
        f"- **Set-aside:** {opp.get('typeOfSetAsideDescription') or 'none (full & open)'}",
        f"- **Place of performance:** {(pop.get('city') or {}).get('name', '-')}, {(pop.get('state') or {}).get('code', '-')}",
        f"- **Response deadline:** {(opp.get('responseDeadLine') or '-')[:10]}",
        f"- **SAM.gov link:** {opp.get('uiLink', '-')}",
        "",
        "## Description",
        description_text or "_Could not fetch full description automatically — read it on SAM.gov before proceeding._",
        "",
        "## Attachments",
    ]
    if links:
        lines += [f"- {link}" for link in links]
    else:
        lines.append("_None listed by the API — check the SAM.gov listing directly._")

    lines += [
        "",
        "## Go / No-Go checklist",
        "- [ ] Confirmed eligibility and size standard for this NAICS/set-aside",
        "- [ ] Read the full PWS/SOW/RFP and attachments",
        "- [ ] Assessed competition (incumbent, similar past awards)",
        "- [ ] Go / no-go decision made",
        "- [ ] Technical response drafted",
        "- [ ] Price proposal drafted",
        "- [ ] Past performance references gathered",
        "- [ ] Reps & certs current in SAM.gov profile",
        "- [ ] Final review before submission",
        "- [ ] Submitted (manually — this tool never submits automatically)",
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def send_email_digest(new_ones, to_addr, from_addr, app_password):
    import smtplib
    from email.mime.text import MIMEText

    lines = [f"{len(new_ones)} new SAM.gov opportunity(ies) for Proverbs 1821 Consulting:\n"]
    for pts, reasons, opp in new_ones:
        lines.append(f"[{pts}] {opp.get('title')}")
        lines.append(f"  NAICS {opp.get('naicsCode')} | deadline {(opp.get('responseDeadLine') or '-')[:10]}")
        lines.append(f"  {opp.get('uiLink', '-')}")
        if reasons:
            lines.append(f"  why: {reasons}")
        lines.append("")
    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"SAM.gov: {len(new_ones)} new opportunity(ies)"
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_addr, app_password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
    print(f"Emailed digest to {to_addr}", file=sys.stderr)


def run_search(cfg, api_key, log=lambda msg: print(msg, file=sys.stderr)):
    """Runs the full pipeline (fetch -> filter -> score -> rank -> diff ->
    draft -> email) from a plain config dict, so both the CLI and the web
    UI drive identical logic. Returns a dict with the ranked list plus
    everything that happened as a side effect (new notices, drafts written,
    whether an email went out) so a caller can render it however it likes.

    cfg keys: naics_codes (list[str]), posted_days, deadline_min, deadline_max,
    limit, max_retries, held_certs, include_restricted, include_expired,
    db_path, drafts_dir, draft_min_score, generate_drafts (bool),
    to_email, from_email, app_password, send_email (bool).
    """
    posted_to = date.today()
    posted_from = posted_to - timedelta(days=cfg["posted_days"])

    all_opps = {}
    for code in cfg["naics_codes"]:
        log(f"Querying NAICS {code}...")
        batch = fetch(
            code,
            posted_from.strftime("%m/%d/%Y"),
            posted_to.strftime("%m/%d/%Y"),
            api_key,
            cfg["limit"],
            cfg["max_retries"],
        )
        for opp in batch:
            all_opps[opp.get("noticeId")] = opp  # dedupe across codes

    held_certs = cfg["held_certs"]

    excluded_restricted = 0
    excluded_expired = 0
    excluded_supplies = 0
    filtered = []
    for opp in all_opps.values():
        if is_supply_notice(opp) and not cfg.get("include_supplies"):
            excluded_supplies += 1
            continue
        if eligibility(opp, held_certs) == "restricted" and not cfg["include_restricted"]:
            excluded_restricted += 1
            continue
        # A notice whose deadline has passed can't be bid, so it's noise by
        # default. Notices with no deadline at all (many sources-sought) stay.
        days_left = days_until_deadline(opp)
        if days_left is not None and days_left < 0 and not cfg.get("include_expired"):
            excluded_expired += 1
            continue
        filtered.append(opp)

    ranked = []
    for opp in filtered:
        pts, reasons = score(opp, cfg["deadline_min"], cfg["deadline_max"], held_certs)
        ranked.append((pts, reasons, opp))
    ranked.sort(key=lambda r: r[0], reverse=True)

    conn = open_state(cfg["db_path"])
    new_ones = diff_and_record(conn, ranked)
    conn.close()

    draft_paths = []
    descriptions = {}
    draft_candidates = [r for r in new_ones if r[0] >= cfg["draft_min_score"]]
    if draft_candidates and cfg["generate_drafts"]:
        for pts, reasons, opp in draft_candidates:
            description_text = fetch_description(opp, api_key)
            if description_text:
                # Kept so a proposal draft can reuse it instead of spending
                # another call against the 1,000/day budget.
                descriptions[opp.get("noticeId")] = description_text
            path = write_draft(
                opp, pts, reasons, eligibility(opp, held_certs),
                description_text, cfg["drafts_dir"],
            )
            draft_paths.append(path)
            log(f"  drafted {path}")

    emailed = False
    if new_ones and cfg["send_email"] and cfg.get("from_email") and cfg.get("app_password"):
        send_email_digest(new_ones, cfg["to_email"], cfg["from_email"], cfg["app_password"])
        emailed = True

    return {
        "ranked": ranked,
        "excluded_restricted": excluded_restricted,
        "excluded_expired": excluded_expired,
        "excluded_supplies": excluded_supplies,
        "new_ones": new_ones,
        "draft_paths": draft_paths,
        "descriptions": descriptions,
        "emailed": emailed,
    }


def main():
    ap = argparse.ArgumentParser(description="Pull and rank SAM.gov opportunities for P1821's tax/eval lanes.")
    ap.add_argument("--posted-days", type=int, default=45)
    ap.add_argument("--deadline-min", type=int, default=7)
    ap.add_argument("--deadline-max", type=int, default=60)
    ap.add_argument("--naics", type=str, default=",".join(DEFAULT_NAICS))
    ap.add_argument("--csv", type=str, default=None)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--db", type=str, default=DEFAULT_DB_PATH)
    ap.add_argument("--drafts-dir", type=str, default=DEFAULT_DRAFTS_DIR)
    ap.add_argument("--draft-min-score", type=int, default=4)
    ap.add_argument("--no-drafts", action="store_true")
    ap.add_argument("--include-restricted-set-asides", action="store_true")
    ap.add_argument("--include-expired", action="store_true",
                    help="also show notices whose response deadline has already passed")
    ap.add_argument("--include-supplies", action="store_true",
                    help="also show supply/equipment buys (digit-prefixed PSC), not just services")
    ap.add_argument("--certs", type=str, default=",".join(DEFAULT_HELD_CERTS),
                    help=f"certifications held, comma-separated from: {','.join(CERTIFICATION_HINTS)}")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--to", type=str, default=DEFAULT_TO_EMAIL)
    args = ap.parse_args()

    api_key = os.environ.get("SAM_API_KEY")
    if not api_key:
        sys.exit('Set SAM_API_KEY first: export SAM_API_KEY="your-key-here"')

    from_addr = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if args.email and not (from_addr and app_password):
        sys.exit("--email set but GMAIL_USER / GMAIL_APP_PASSWORD are not in the environment")

    cfg = {
        "naics_codes": [c.strip() for c in args.naics.split(",") if c.strip()],
        "posted_days": args.posted_days,
        "deadline_min": args.deadline_min,
        "deadline_max": args.deadline_max,
        "limit": args.limit,
        "max_retries": args.max_retries,
        "held_certs": [c.strip() for c in args.certs.split(",") if c.strip()],
        "include_restricted": args.include_restricted_set_asides,
        "include_expired": args.include_expired,
        "include_supplies": args.include_supplies,
        "db_path": args.db,
        "drafts_dir": args.drafts_dir,
        "draft_min_score": args.draft_min_score,
        "generate_drafts": not args.no_drafts,
        "to_email": args.to,
        "from_email": from_addr,
        "app_password": app_password,
        "send_email": not args.no_email,
    }

    result = run_search(cfg, api_key)
    ranked = result["ranked"]

    scored = sum(1 for r in ranked if r[0] > 0)
    print(f"\n{len(ranked)} unique notices, {scored} scored above zero", file=sys.stderr)
    if result["excluded_supplies"]:
        print(
            f"{result['excluded_supplies']} excluded (supply/equipment buys, not services — "
            f"use --include-supplies to see them)",
            file=sys.stderr,
        )
    if result["excluded_expired"]:
        print(
            f"{result['excluded_expired']} excluded (response deadline already passed — "
            f"use --include-expired to see them)",
            file=sys.stderr,
        )
    if result["excluded_restricted"]:
        print(
            f"{result['excluded_restricted']} excluded (set-aside restricted to a certification we don't hold — "
            f"use --include-restricted-set-asides to see them)",
            file=sys.stderr,
        )
    print()

    for pts, reasons, opp in ranked[:40]:
        pop = opp.get("placeOfPerformance") or {}
        city = (pop.get("city") or {}).get("name", "-")
        state = (pop.get("state") or {}).get("code", "-")
        deadline_raw = opp.get("responseDeadLine")
        deadline_str = deadline_raw[:10] if deadline_raw else "-"
        set_aside = opp.get("typeOfSetAsideDescription") or "no set-aside"

        print(f"[{pts}] {opp.get('title')}")
        print(f"     NAICS {opp.get('naicsCode')} | PSC {opp.get('classificationCode')} | {set_aside}")
        print(f"     {city}, {state} | deadline {deadline_str}")
        if reasons:
            print(f"     why: {reasons}")
        print(f"     {opp.get('uiLink', '-')}\n")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["score", "title", "naics", "psc", "set_aside", "city", "state", "deadline", "link", "notice_id"])
            for pts, reasons, opp in ranked:
                pop = opp.get("placeOfPerformance") or {}
                w.writerow([
                    pts,
                    opp.get("title"),
                    opp.get("naicsCode"),
                    opp.get("classificationCode"),
                    opp.get("typeOfSetAsideDescription") or "",
                    (pop.get("city") or {}).get("name", ""),
                    (pop.get("state") or {}).get("code", ""),
                    (opp.get("responseDeadLine") or "")[:10],
                    opp.get("uiLink", ""),
                    opp.get("noticeId"),
                ])
        print(f"Wrote {args.csv}", file=sys.stderr)

    print(f"{len(result['new_ones'])} notice(s) new since last run (tracked in {args.db})", file=sys.stderr)


if __name__ == "__main__":
    main()
