#!/usr/bin/env python3
"""
SAM.gov Opportunity Finder

Pulls open SAM.gov solicitations, sources-sought and presolicitations for
one business profile at a time (see PROFILES):

  --profile p1821  Proverbs 1821 Consulting — tax, accounting, evaluation
      Lane 1: Installation tax center support (Randy White performs)
      Lane 2: Accounting / tax remediation task orders (Randy leads)
      Lane 3: Third-party program evaluation (Forrest / Blackwater Evaluation)

  --profile ares   Ares Robotics — waste, remediation, machinery, structural

Both sets of NAICS codes are on the same SAM.gov registration, but the work
has nothing in common, so each profile keeps its own codes, keywords, PSCs,
score threshold, state file (state-<profile>.sqlite3) and drafts folder
(drafts/<profile>/). Searching them together buried a WOSB financial-analysis
RFP among salt-bath maintenance jobs.

Runs entirely on your machine (or in the scheduled GitHub Action — see
.github/workflows/daily-search.yml, which runs both profiles). Claude's
sandbox can't reach api.sam.gov (egress proxy returns host_not_allowed), so
nothing here is called from Claude's side.

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
  --profile NAME        Which business to search: p1821 (default) or ares
  --posted-days N       How many days back to search postings (default 45)
  --deadline-min N      Skip anything closing sooner than N days (default 7)
  --deadline-max N      Skip anything closing later than N days (default 60)
  --naics CODE[,CODE]   Override the profile's NAICS list
  --csv PATH            Also write full ranked results to a CSV file
  --limit N             Max results per NAICS call (default 100)
  --max-retries N       Retry attempts per API call on 429/5xx/network error (default 4)
  --db PATH             State file of previously-seen notices (default state-<profile>.sqlite3)
  --drafts-dir PATH     Where review scaffolds go (default drafts/<profile>)
  --draft-min-score N   Minimum score for a scaffold (default: the profile's own)
  --include-supplies    Also show supply/equipment buys (digit-prefixed PSC)
  --include-expired     Also show notices whose deadline has passed
  --no-drafts           Skip draft generation entirely
  --include-restricted-set-asides
                        Also show set-asides you're not certified for (8(a), HUBZone,
                        SDVOSB, etc). Excluded by default so they don't clutter results.
  --email               Fail loudly if the Gmail credentials are missing
  --always-email        Send the digest even when nothing is new (daily run)
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
# Registrant confirmed 9/12/26: every code below is live on the registration,
# 541211 verified directly on the Assertions page. The audit's open question —
# whether the 8/19/26 update replaced or merely supplemented the 541-series —
# is answered: it ADDED. The list has only ever grown, never shrunk, and the
# 9/9/26 set went in. So this list is the registration itself, not a
# defensive search net, and nothing here is pending verification.
#
# Still per-solicitation work, unchanged by that: a registered NAICS code does
# not by itself establish that the business is under the size standard for a
# given solicitation's code. Check the SBA size table for the code the
# solicitation actually cites before representing size on a bid.
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
    # --- Added 9/9/26 (recommended then, confirmed entered 9/12/26) ---
    "541213",  # Tax Preparation Services
    "541219",  # Other Accounting Services
    "238190",  # Other Building Exterior Contractors — raised as a maybe for
               # the welder's structural work. A construction trade, so expect
               # this to be the noisiest code in the set.
    # --- Absent from the audit trail but present on the Assertions page
    # (verified 9/12/26). Already producing work: the Coast Guard Academy
    # NAFI audit came in on this code. ---
    "541211",  # Offices of Certified Public Accountants
]

# PSC codes worth a point. R710/B505/R499 came from the original script;
# R407, F108 and J039 are from the registration audit. (Z2AZ was pulled
# before entry, so it is deliberately absent.)
PRIORITY_PSC = {"R710", "B505", "R499", "R407", "F108", "J039"}

# The registration covers two businesses whose work has nothing in common:
# professional services (tax, accounting, evaluation) and industrial trades
# (waste, remediation, machinery, structural). Searching them together put a
# WOSB financial-analysis RFP and a salt-bath maintenance job in one
# undifferentiated pile of 25 packets, scored by one model tuned for the
# former. Each profile gets its own codes, keywords, PSCs, threshold, state
# file and drafts folder, so a run surfaces one business at a time.
# The one offeror. Both lanes below bid under this name and this
# registration — Ares Robotics is in-house, not a separate business, so the
# interface shows one company with two kinds of work rather than a choice
# between two companies.
COMPANY_NAME = "Proverbs 1821 Consulting LLC"

PROFILES = {
    "p1821": {
        "label": "Financial, administrative & construction services",
        "naics": [
            "541211",  # Offices of Certified Public Accountants
            "541213",  # Tax Preparation Services
            "541219",  # Other Accounting Services
            "541611",  # Admin & General Management Consulting
            "541612",  # HR Consulting
            "541613",  # Marketing Consulting
            "541614",  # Logistics Consulting
            "541618",  # Other Management Consulting
            "541620",  # Environmental Consulting (serves both profiles)
            "541690",  # Other Scientific & Technical Consulting
            "541720",  # R&D in Social Sciences & Humanities
            "541990",  # Other Professional/Scientific/Technical Services
            # Construction trades — Jason Teal, general contractor, is
            # in-house and self-performs most work let under these codes.
            "236220",  # Commercial & Institutional Building Construction
            "236118",  # Residential Remodelers
            "238110",  # Poured Concrete Foundation & Structure
            "238120",  # Structural Steel & Precast Concrete (welding)
            "238130",  # Framing
            "238140",  # Masonry
            "238160",  # Roofing
            "238170",  # Siding
            "238190",  # Other Foundation, Structure & Building Exterior
            "238210",  # Electrical
            "238220",  # Plumbing, Heating & Air-Conditioning
            "238290",  # Other Building Equipment
            "238310",  # Drywall & Insulation
            "238320",  # Painting & Wall Covering
            "238330",  # Flooring
            "238350",  # Finish Carpentry
            "238390",  # Other Building Finishing
            "238910",  # Site Preparation
            "238990",  # All Other Specialty Trade Contractors
            "811310",  # Commercial & Industrial Machinery Repair (welding, fabrication)
        ],
        "priority_psc": {"R710", "B505", "R499", "R407"},
        "keywords": [
            "tax", "vita", "evaluation", "accounting", "financial",
            "audit", "irs", "compliance", "remediation",
            "roof", "roofing", "welding", "construction", "renovation",
            "repair", "remodel", "concrete", "carpentry", "painting",
            "hvac", "plumbing", "electrical", "flooring", "demolition",
        ],
        "home_states": {"TX"},
        "draft_min_score": 4,
    },
    "ares": {
        "label": "Industrial, waste, remediation & vessel services",
        "naics": [
            "562211",  # Hazardous Waste Treatment & Disposal
            "562910",  # Remediation Services
            "562998",  # All Other Misc. Waste Management
            "811310",  # Commercial & Industrial Machinery Repair
            "333998",  # All Other General Purpose Machinery Mfg
            "238190",  # Other Building Exterior Contractors (welding/structural)
            "541620",  # Environmental Consulting (serves both profiles)
        ],
        "priority_psc": {"F108", "J039"},
        "keywords": [
            "remediation", "hazardous waste", "environmental", "abatement",
            "decontamination", "demolition", "welding", "structural",
        ],
        "home_states": {"TX"},
        # Higher bar: these codes return far more volume than the
        # professional-services ones, most of it small maintenance jobs.
        "draft_min_score": 5,
    },
}
DEFAULT_PROFILE = "p1821"
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
# Without this, a profile holding only WOSB would read every "Small
# Business Set Aside - Total" notice as ineligible and hide it.
SMALL_BUSINESS_IMPLYING_CERTS = frozenset(CERTIFICATION_HINTS) - {"small_business"}

# What is actually held today. Small-business status is self-certified in
# SAM.gov against the size standard for the NAICS code; every other program
# in the table above requires a certification the business does not have.
#
# WOSB and EDWOSB are deliberately absent. The business is male-owned as of
# September 2026, with an ownership transition to a woman owner planned but
# not executed. WOSB is no longer self-certifiable: FAR 19.15 requires the
# offeror to be certified in SBA's system at the time of quote submission,
# and the set-aside notices say so in their own text. Listing it here would
# put a false certification on federal submissions and score restricted
# work as winnable.
#
# When the transition completes AND the SBA certification is issued, add
# "wosb" (and "edwosb" if the economic-disadvantage criteria are met) to
# this tuple and to the webapp's default certifications. Nothing else needs
# to change — the eligibility logic already handles both.
DEFAULT_HELD_CERTS = ("small_business",)

# Not everything posted on SAM.gov can be bid, and the difference is not
# visible in the title. A Sources Sought Notice is market research: it says
# so in capitals in its own text, it has no line items and no award, and
# responding means sending a capability statement. Building a priced quote
# and a cover email for one is worse than useless — it invites sending a
# price to someone who cannot accept it.
BIDDABLE_NOTICE_TYPES = frozenset({
    "solicitation",
    "combined synopsis/solicitation",
})

NOT_BIDDABLE_REASONS = {
    "sources sought": "market research only — respond with a capability statement, not a priced quote",
    "presolicitation": "advance notice — the solicitation itself has not been issued yet",
    "special notice": "informational notice, not a solicitation",
    "award notice": "already awarded to someone else",
    "justification": "justification for an award already decided",
    "intent to bundle requirements (dod-funded)": "notice of intent, not a solicitation",
    "sale of surplus property": "property sale, not a services contract",
    "foreign government standard": "informational notice, not a solicitation",
}


def notice_type(opp):
    """The notice's type as SAM.gov labels it, e.g. "Sources Sought"."""
    return (opp.get("type") or opp.get("baseType") or "").strip()


def not_biddable_reason(opp):
    """None when this notice can actually be bid, otherwise why it cannot.

    An unrecognised or missing type is treated as biddable: the API adds
    types over time, and silently hiding real solicitations would be a
    worse failure than showing an odd one.
    """
    label = notice_type(opp)
    if not label:
        return None
    key = label.lower()
    if key in BIDDABLE_NOTICE_TYPES:
        return None
    return NOT_BIDDABLE_REASONS.get(key)


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

    # Every specific program's name contains the words "small business", so
    # "Veteran-Owned Small Business Set-Aside" also matches the generic
    # small-business hint and would read as open to any small business. A
    # notice reserved for a named program is reserved for that program only,
    # so the generic key is dropped whenever a specific one matched.
    specific = matched - {"small_business"}
    if specific:
        matched = specific

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


def score(opp, deadline_min, deadline_max, held_certs=DEFAULT_HELD_CERTS,
          keywords=None, priority_psc=None, home_states=None):
    """Triage score for one notice. keywords/priority_psc/home_states come
    from the active profile; the module-level defaults keep direct callers
    and the CLI's --naics override working without one."""
    keywords = KEYWORDS if keywords is None else keywords
    priority_psc = PRIORITY_PSC if priority_psc is None else priority_psc
    home_states = HOME_STATES if home_states is None else home_states

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

    if opp.get("classificationCode") in priority_psc:
        pts += 1
        reasons.append("PSC match")

    title = (opp.get("title") or "").lower()
    hits = sum(1 for kw in keywords if kw in title)
    if hits:
        pts += min(hits, 2)
        reasons.append(f"{hits} keyword match" + ("es" if hits > 1 else ""))

    pop = opp.get("placeOfPerformance") or {}
    state = (pop.get("state") or {}).get("code")
    if state in home_states:
        pts += 1
        reasons.append(state)

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


def format_notice_lines(pts, reasons, opp):
    days_left = days_until_deadline(opp)
    deadline = (opp.get("responseDeadLine") or "")[:10] or "not listed"
    if days_left is not None and days_left >= 0:
        deadline += f" ({days_left}d left)"
    pop = opp.get("placeOfPerformance") or {}
    where = ", ".join(
        p for p in ((pop.get("city") or {}).get("name"), (pop.get("state") or {}).get("code")) if p
    ) or "not listed"
    lines = [
        f"[{pts}] {opp.get('title')}",
        f"  due {deadline} | {where} | NAICS {opp.get('naicsCode')}",
        f"  set-aside: {opp.get('typeOfSetAsideDescription') or 'none (open to everyone)'}",
    ]
    if reasons:
        lines.append(f"  why it matched: {reasons}")
    lines.append(f"  {opp.get('uiLink', '-')}")
    lines.append("")
    return lines


def credential_blocked(opp, description_text, company):
    """The unmet pass/fail qualification for this notice, or None.

    The credential gate reached the packet checklist and stopped there, so
    a notice the tool already knew was unwinnable kept arriving at the top
    of the digest. The Coast Guard NAFI audit says "independent Certified
    Public Accountant firm or licensed CPA" in its own description, was
    reported as blocked inside its packet, and was still the first thing in
    the email three days running.
    """
    import packet as packet_builder
    from company import satisfies

    gates = packet_builder.credential_gates(
        description_text, opp.get("description"), opp.get("title"))
    for gate in gates:
        if satisfies(company, gate) is None:
            return gate
    return None


def send_email_digest(new_ones, to_addr, from_addr, app_password,
                      profile_label=None, ranked=None, top_n=10, blocked=None):
    """The daily digest. Leads with what's new, then lists the current best
    matches so the mail is useful even on a day when nothing is new — which
    is most days, and otherwise the reader can't tell a quiet day from a
    broken search."""
    import smtplib
    from email.mime.text import MIMEText

    # Both profiles mail the same inbox, so the subject has to name the
    # business or the two digests are indistinguishable.
    who = profile_label or "Proverbs 1821 Consulting"
    ranked = ranked or []
    blocked = blocked or []
    blocked_ids = {opp.get("noticeId") for opp, _ in blocked}
    new_ones = [r for r in new_ones if r[2].get("noticeId") not in blocked_ids]
    ranked = [r for r in ranked if r[2].get("noticeId") not in blocked_ids]
    new_ids = {opp.get("noticeId") for _, _, opp in new_ones}

    lines = [f"SAM.gov daily search — {who}", f"{date.today().strftime('%A, %B %d, %Y')}", ""]

    if new_ones:
        lines.append(f"NEW SINCE YESTERDAY ({len(new_ones)})")
        lines.append("=" * 40)
        lines.append("")
        for pts, reasons, opp in new_ones:
            lines += format_notice_lines(pts, reasons, opp)
    else:
        lines += ["Nothing new since yesterday.", ""]

    others = [r for r in ranked if r[2].get("noticeId") not in new_ids and r[0] > 0]
    if others:
        lines.append(f"STILL OPEN — TOP MATCHES ({min(len(others), top_n)} of {len(others)})")
        lines.append("=" * 40)
        lines.append("")
        for pts, reasons, opp in others[:top_n]:
            lines += format_notice_lines(pts, reasons, opp)

    # Below the fold, and never in the top matches. A notice requiring a
    # qualification the business does not hold is not a match, however well
    # it scores on codes and deadlines, and putting it first is worse than
    # not mentioning it: it reads as a recommendation.
    if blocked:
        lines.append(f"CANNOT BID — QUALIFICATION NOT HELD ({len(blocked)})")
        lines.append("=" * 40)
        lines.append("Listed so you know they exist. Do not spend time on these.")
        lines.append("")
        for opp, gate in blocked:
            deadline = (opp.get("responseDeadLine") or "")[:10] or "no deadline"
            lines.append(f"  {opp.get('title')}")
            lines.append(f"    due {deadline} — needs {gate}")
            lines.append(f"    {opp.get('uiLink', '-')}")
            lines.append("")

    lines += [
        "-" * 40,
        f"{len(ranked)} open notices matched your codes today"
        + (f"; {len(blocked)} excluded as unbiddable." if blocked else "."),
        "Bid packets are in the repo under packets/.",
        "Nothing has been submitted — every bid stays your decision.",
    ]

    msg = MIMEText("\n".join(lines))
    if new_ones:
        msg["Subject"] = f"SAM.gov: {len(new_ones)} new for {who}"
    else:
        msg["Subject"] = f"SAM.gov: nothing new for {who}"
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
        pts, reasons = score(
            opp, cfg["deadline_min"], cfg["deadline_max"], held_certs,
            keywords=cfg.get("keywords"),
            priority_psc=cfg.get("priority_psc"),
            home_states=cfg.get("home_states"),
        )
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

    # Check the notices that would actually reach the inbox. One
    # description call each against a 1,000/day budget, to stop the tool
    # recommending work the business is barred from — which is what it did
    # for three days with the Coast Guard NAFI audit.
    from company import load_company
    company = load_company(cfg.get("profile") or DEFAULT_PROFILE)
    blocked = []
    for pts, reasons, opp in ranked[:cfg.get("digest_top_n", 10) + len(new_ones)]:
        nid = opp.get("noticeId")
        text = descriptions.get(nid)
        if text is None:
            text = fetch_description(opp, api_key)
            descriptions[nid] = text or ""
        gate = credential_blocked(opp, text, company)
        if gate:
            blocked.append((opp, gate))
            log(f"  cannot bid: {opp.get('title')} — needs {gate}")

    emailed = False
    have_creds = cfg.get("from_email") and cfg.get("app_password")
    # A scheduled daily digest should arrive even on a quiet day, otherwise
    # "no email" is ambiguous between nothing new and a broken search.
    worth_sending = bool(new_ones) or cfg.get("always_email")
    if cfg["send_email"] and have_creds and worth_sending:
        send_email_digest(
            new_ones, cfg["to_email"], cfg["from_email"], cfg["app_password"],
            profile_label=cfg.get("profile_label"),
            ranked=ranked,
            blocked=blocked,
        )
        emailed = True

    return {
        "ranked": ranked,
        "excluded_restricted": excluded_restricted,
        "excluded_expired": excluded_expired,
        "excluded_supplies": excluded_supplies,
        "new_ones": new_ones,
        "blocked": blocked,
        "draft_paths": draft_paths,
        "descriptions": descriptions,
        "emailed": emailed,
    }


def build_batch(count, profile_key, profile, ranked, descriptions, api_key,
                packets_root, log=lambda m: print(m, file=sys.stderr)):
    """The conveyor belt: turn the top N open matches into packet folders.

    Works off the full ranked list rather than only what is new, because
    the goal is N packets in the tray today — a notice that was new
    yesterday and is still open is still worth bidding.
    """
    import requests

    import packet
    from company import load_company, missing_fields, skip_reason

    company = load_company(profile_key)
    required, leverage = missing_fields(company)
    if company.get("_error"):
        log(f"  !! {company['_error']} — every offeror field will be a blank")
    elif required:
        log(f"  !! fact bank incomplete: {len(required)} required field(s) blank "
            f"({', '.join(required[:3])}{'...' if len(required) > 3 else ''})")
        log("     packets still build, but those blanks repeat on every one — "
            "run: python3 company.py --profile " + profile_key)

    # Attachment URLs on SAM.gov need the same API key the search uses.
    session = requests.Session()
    original_get = session.get

    def keyed_get(url, **kw):
        if "api_key=" not in url:
            url += ("&" if "?" in url else "?") + "api_key=" + api_key
        return original_get(url, **kw)

    session.get = keyed_get

    # The target is N NEW packets to work on, so only first-time builds count
    # against it. Counting reused ones would mean a stable top N produces
    # nothing ever again: the same packets would be recognised as current,
    # fill the quota, and the tray would stop growing while appearing to
    # work. Packets already in the tray are still visited so they pick up
    # new facts or get repaired — they just do not consume the quota.
    floor = profile["draft_min_score"]
    built, skipped, fresh = [], [], 0
    for pts, reasons, opp in ranked:
        if fresh >= count:
            break
        if pts < floor:
            # Walking further down means preparing bids on work this
            # profile does not really match, which is worse than producing
            # fewer than the target.
            break
        # A notice in the firm's own line of work is worth responding to even
        # when it cannot be bid. Market research gets a capability statement;
        # award notices and the rest still get nothing.
        unbiddable = not_biddable_reason(opp)
        capability_kind = notice_type(opp) if unbiddable and notice_type(opp).lower() in (
            "sources sought", "special notice") else None

        why = skip_reason(company, opp) or (unbiddable if not capability_kind else None)
        if why:
            skipped.append((opp, why))
            continue

        description_text = descriptions.get(opp.get("noticeId"))
        if description_text is None and packet.needs_work(opp, company, packets_root):
            # One call against the 1,000/day budget, and the packet is worth
            # far more with the government's own words in it. Skipped for a
            # packet that is already current, which would not use it.
            description_text = fetch_description(opp, api_key)

        if capability_kind:
            out, blanks_left, status = packet.build_capability_response(
                opp, description_text, company, packets_root,
                notice_kind=capability_kind, session=session,
            )
        else:
            out, blanks_left, status = packet.build_packet(
                opp, description_text, company, packets_root, pts, reasons, session=session,
            )
        built.append((out, opp, blanks_left, status))
        if status == "new":
            fresh += 1
        left = "-" if blanks_left is None else f"{blanks_left} blanks left"
        label = "capability" if capability_kind else "packet"
        log(f"  {label} [{status}] {os.path.basename(out)} — {left}")

    if fresh < count:
        log(f"  only {fresh} new packet(s) available at or above score {floor} "
            f"(target was {count})")

    # Attachments are the bulk of the store and are worthless once the
    # solicitation closes, so closed packets give theirs up here.
    pruned, freed = packet.prune_closed_packets(packets_root)
    if pruned:
        log(f"  pruned attachments from {len(pruned)} closed packet(s), "
            f"freeing {freed / 1048576:.1f} MB")

    index = packet.write_batch_index(built, skipped, packets_root, profile["label"])
    log(f"\n{fresh} new, {len(built) - fresh} existing — start here: {index}")
    if skipped:
        log(f"{len(skipped)} skipped by your skip_psc / skip_keywords rules")
    return built, skipped


def main():
    # Progress and summary lines go to stderr, the ranked list to stdout.
    # Redirected to a file (a CI log), stdout is block-buffered and flushes
    # only at exit, so the whole list lands after every stderr line and the
    # counts end up buried mid-log instead of under the results they
    # describe. Line buffering keeps the two streams in real order.
    sys.stdout.reconfigure(line_buffering=True)

    ap = argparse.ArgumentParser(description="Pull and rank SAM.gov opportunities for one business profile.")
    ap.add_argument("--profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE,
                    help="which business to search: " + " | ".join(
                        f"{k} ({v['label']})" for k, v in PROFILES.items()))
    ap.add_argument("--posted-days", type=int, default=45)
    ap.add_argument("--deadline-min", type=int, default=7)
    ap.add_argument("--deadline-max", type=int, default=60)
    ap.add_argument("--naics", type=str, default=None,
                    help="override the profile's NAICS list")
    ap.add_argument("--csv", type=str, default=None)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--db", type=str, default=None,
                    help="default: state-<profile>.sqlite3")
    ap.add_argument("--drafts-dir", type=str, default=None,
                    help="default: drafts/<profile>")
    ap.add_argument("--draft-min-score", type=int, default=None,
                    help="default: the profile's own threshold")
    ap.add_argument("--no-drafts", action="store_true")
    ap.add_argument("--batch", type=int, default=0, metavar="N",
                    help="build N submission-ready bid packets from the top matches "
                         "(the conveyor belt: folder each, with price sheet, cover email "
                         "and the solicitation's own attachments)")
    ap.add_argument("--packets-dir", type=str, default=None,
                    help="default: packets/<profile>")
    ap.add_argument("--include-restricted-set-asides", action="store_true")
    ap.add_argument("--include-expired", action="store_true",
                    help="also show notices whose response deadline has already passed")
    ap.add_argument("--include-supplies", action="store_true",
                    help="also show supply/equipment buys (digit-prefixed PSC), not just services")
    ap.add_argument("--certs", type=str, default=",".join(DEFAULT_HELD_CERTS),
                    help=f"certifications held, comma-separated from: {','.join(CERTIFICATION_HINTS)}")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--always-email", action="store_true",
                    help="send the digest even when nothing is new (for the daily run)")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-identity-check", action="store_true",
                    help="search even with no legal identity on file (for testing)")
    ap.add_argument("--to", type=str, default=DEFAULT_TO_EMAIL)
    args = ap.parse_args()

    api_key = os.environ.get("SAM_API_KEY")
    if not api_key:
        sys.exit('Set SAM_API_KEY first: export SAM_API_KEY="your-key-here"')

    from_addr = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if args.email and not (from_addr and app_password):
        sys.exit("--email set but GMAIL_USER / GMAIL_APP_PASSWORD are not in the environment")

    profile = PROFILES[args.profile]
    print(f"Profile: {args.profile} — {profile['label']}", file=sys.stderr)

    # A profile with no legal identity on file cannot submit anything, so
    # searching and emailing for it produces nothing but noise — and worse,
    # it produces credible-looking opportunities that cost real hours before
    # anyone notices the business behind them cannot bid. Setting --batch 0
    # stopped the packets and left the digest arriving daily, which is
    # exactly how an hour went into a DLA hazardous waste solicitation for a
    # profile with no registered name.
    #
    # Skipped entirely until the identity exists, and it comes back by
    # itself the moment company.toml has it.
    if not args.no_identity_check:
        from company import load_company, missing_fields
        company_facts = load_company(args.profile)

        # A lane can be deliberately quiet. Both businesses bid under one
        # registration, so neither is blocked by identity any more — but a
        # lane whose opportunities cannot be acted on this month is noise,
        # and noise in a daily email is how an afternoon went into a DLA
        # hazardous waste solicitation nobody was going to bid.
        active = company_facts.get("active_profiles")
        if active and args.profile not in active:
            print(f"  {args.profile} is not in active_profiles "
                  f"({', '.join(active)}) — no search, no email.", file=sys.stderr)
            print(f"  Add \"{args.profile}\" to active_profiles in company.toml"
                  " to turn this lane back on.", file=sys.stderr)
            return

        required, _ = missing_fields(company_facts)
        blocking = [f for f in required
                    if f in ("legal business name", "UEI (12 chars, from SAM.gov)", "CAGE code")]
        if blocking:
            print(f"  skipping {args.profile}: no legal identity on file "
                  f"({', '.join(blocking)}).", file=sys.stderr)
            print("  Nothing found under this profile could be submitted by anyone, so"
                  " no search and no email.", file=sys.stderr)
            print(f"  Fill it in company.toml under [{args.profile}] and this resumes"
                  " on the next run.", file=sys.stderr)
            return

    cfg = {
        "profile": args.profile,
        "naics_codes": (
            [c.strip() for c in args.naics.split(",") if c.strip()]
            if args.naics else list(profile["naics"])
        ),
        "profile_label": profile["label"],
        "keywords": profile["keywords"],
        "priority_psc": profile["priority_psc"],
        "home_states": profile["home_states"],
        "posted_days": args.posted_days,
        "deadline_min": args.deadline_min,
        "deadline_max": args.deadline_max,
        "limit": args.limit,
        "max_retries": args.max_retries,
        "held_certs": [c.strip() for c in args.certs.split(",") if c.strip()],
        "include_restricted": args.include_restricted_set_asides,
        "include_expired": args.include_expired,
        "include_supplies": args.include_supplies,
        "db_path": args.db or f"state-{args.profile}.sqlite3",
        "drafts_dir": args.drafts_dir or os.path.join(DEFAULT_DRAFTS_DIR, args.profile),
        "draft_min_score": (
            args.draft_min_score if args.draft_min_score is not None
            else profile["draft_min_score"]
        ),
        "generate_drafts": not args.no_drafts,
        "to_email": args.to,
        "from_email": from_addr,
        "app_password": app_password,
        "send_email": not args.no_email,
        "always_email": args.always_email,
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
        kind = notice_type(opp) or "type not stated"
        blocked = not_biddable_reason(opp)
        print(f"     {kind}{' — NOT BIDDABLE: ' + blocked if blocked else ''}")
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

    print(
        f"{len(result['new_ones'])} notice(s) new since last run "
        f"(tracked in {cfg['db_path']})",
        file=sys.stderr,
    )

    if args.batch:
        packets_root = args.packets_dir or os.path.join("packets", args.profile)
        print(f"\nBuilding up to {args.batch} bid packet(s) in {packets_root}/",
              file=sys.stderr)
        build_batch(
            args.batch, args.profile, profile, ranked,
            result["descriptions"], api_key, packets_root,
        )


if __name__ == "__main__":
    main()
