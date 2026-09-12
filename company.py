#!/usr/bin/env python3
"""
The fact bank.

Every proposal packet needs the same forty-odd facts about the business:
UEI, CAGE, signatory, insurance, past performance, labor rates. Typed once
into company.toml, they fill themselves in on every bid from here on.

Run this file directly for a readiness report — what is filled, what is
still blank, and how many blanks that leaves in each packet:

    python3 company.py
    python3 company.py --profile ares

Design rule, same as proposal.py: a blank stays visibly blank. Nothing
about the business is guessed, defaulted to something plausible, or
carried over from another profile. A fabricated UEI or past-performance
reference on a federal submission is a false statement, so the only two
outcomes here are "a real value you entered" and "an obvious hole".
"""

import os
import re
import sys

# tomllib joined the standard library in Python 3.11. On 3.7-3.10 the same
# parser ships as "tomli", which is what requirements.txt installs there.
# Assuming 3.11+ broke startup on a Mac running Anaconda's older Python
# with nothing but a ModuleNotFoundError to go on.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on interpreter
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None

CONFIG_NAME = "company.toml"

# Without these a packet cannot be submitted at all — they identify the
# offeror and the person binding the company to the offer.
REQUIRED_FIELDS = (
    ("legal_name", "legal business name"),
    ("uei", "UEI (12 chars, from SAM.gov)"),
    ("cage", "CAGE code"),
    ("address", "business address"),
    ("phone", "phone"),
    ("email", "email"),
    ("signatory_name", "authorized signatory name"),
    ("signatory_title", "signatory title"),
)

# Not fatal, but each one left blank is a blank the human fills on every
# single packet, so the payoff for entering them once is the highest in
# the whole pipeline.
LEVERAGE_FIELDS = (
    ("capability_statement", "capability statement (used in every cover letter)"),
    ("insurance_carrier", "insurance carrier"),
    ("insurance_gl_limit", "general liability limit"),
    ("workers_comp", "workers comp coverage"),
    ("sam_registration_expires", "SAM registration expiry"),
)

SHARED_KEYS = (
    "signatory_name", "signatory_title", "phone", "email",
    "sam_registration_expires", "insurance_carrier", "insurance_gl_limit",
    "workers_comp", "bonding_capacity_single", "bonding_capacity_total",
    "skip_psc", "skip_keywords",
)


def config_path():
    """company.toml from DATA_DIR if the host sets one (the webapp does,
    for hosts with an ephemeral filesystem), else next to this file."""
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        candidate = os.path.join(data_dir, CONFIG_NAME)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_NAME)


def _is_filled(value):
    """A value counts as entered only if it is non-empty after stripping.
    Lists of blank dicts (the placeholder rate card and past-performance
    rows shipped in company.toml) do not count as filled."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_is_filled(v) for v in value)
    if isinstance(value, dict):
        return any(_is_filled(v) for v in value.values())
    return value is not None


def load_company(profile, path=None):
    """The merged fact bank for one business profile: the [shared] block
    plus that profile's own block, profile winning on any collision.

    A missing or unparseable company.toml is not an error — it means
    nothing has been entered yet, and every field becomes a visible blank
    in the packet. The pipeline still runs.
    """
    path = path or config_path()
    if tomllib is None:
        # Every offeror field becomes a visible blank rather than the whole
        # pipeline failing, and the message says exactly how to fix it.
        return {
            "_source": None,
            "_error": (
                "no TOML parser available on Python "
                f"{sys.version_info.major}.{sys.version_info.minor} — run: "
                "python3 -m pip install tomli"
            ),
        }
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {"_source": None, "_error": f"could not read {path}"}

    merged = {"_source": path}
    shared = raw.get("shared") or {}
    for key in SHARED_KEYS:
        if key in shared:
            merged[key] = shared[key]
    merged.update(raw.get(profile) or {})
    return merged


# A row in one of these lists counts as real only when its identifying
# fields are filled. Without this, the blank rate-card row shipped in
# company.toml reads as a real labor category purely because it carries
# unit = "hr", and an empty priced line would reach a packet.
ROW_IDENTITY = {
    "past_performance": ("customer", "contract"),
    "rate_card": ("category", "rate"),
}


def filled_rows(company, key):
    """Real entries only, from a list-of-tables like past_performance or
    rate_card. Keeps the blank template rows out of the packet."""
    identity = ROW_IDENTITY.get(key)
    rows = company.get(key) or []
    if not identity:
        return [row for row in rows if _is_filled(row)]
    return [row for row in rows if all(_is_filled(row.get(f)) for f in identity)]


def missing_fields(company):
    """(required, leverage) — the labels still blank in each group."""
    required = [label for key, label in REQUIRED_FIELDS if not _is_filled(company.get(key))]
    leverage = [label for key, label in LEVERAGE_FIELDS if not _is_filled(company.get(key))]
    if not filled_rows(company, "past_performance"):
        leverage.append("past performance (at least one real contract)")
    if not filled_rows(company, "rate_card"):
        leverage.append("rate card (pre-fills the price sheet)")
    return required, leverage


# Credentials the business actually holds, and which pass/fail gate each
# one answers. The mapping is deliberately narrow, because the expensive
# mistake is the generous one.
#
# An Enrolled Agent is a real federal credential — IRS-licensed under
# Circular 230, with unlimited representation rights before the IRS — and
# it satisfies NOTHING on the CPA line. Attest and audit work, and any
# opinion on financial statements, is reserved to CPAs licensed by a state
# board of accountancy. An EA answering a "licensed CPA" requirement would
# be a false representation on a federal submission, so "ea" appears in
# this table with its own gate and never touches the CPA one.
CREDENTIAL_SATISFIES = {
    "cpa": "a licensed CPA or CPA firm",
    "pe": "a licensed Professional Engineer",
    "clearance": "a security clearance or facility clearance",
    "state_license": "a state contractor or professional license",
    "osha_nfpa": "documented OSHA / NFPA safety training for the crew",
    "iso_assessor": "accredited assessor or auditor competence for a named standard",
    "other_cert": "a named third-party certification",
    # Held, useful, and answers no gate above. Present so it can be cited
    # where it IS the qualification — tax preparation and IRS
    # representation — rather than being quietly treated as an audit
    # credential.
    "ea": None,
}

CREDENTIAL_LABELS = {
    "cpa": "Certified Public Accountant (state-licensed)",
    "ea": "Enrolled Agent (IRS, Circular 230)",
    "pe": "Professional Engineer",
    "clearance": "Security / facility clearance",
    "state_license": "State contractor or professional license",
    "osha_nfpa": "OSHA / NFPA confined-space or safety training",
    "iso_assessor": "Accredited assessor for a named standard",
    "other_cert": "Third-party certification",
}


def held_credentials(company):
    """Real credential entries on file: kind, holder, identifier, expiry."""
    out = []
    for row in company.get("credentials") or []:
        kind = str(row.get("kind") or "").strip().lower()
        if kind and _is_filled(row.get("holder")):
            out.append({
                "kind": kind,
                "label": CREDENTIAL_LABELS.get(kind, kind),
                "holder": str(row.get("holder")).strip(),
                "identifier": str(row.get("identifier") or "").strip(),
                "expires": str(row.get("expires") or "").strip(),
            })
    return out


def satisfies(company, gate):
    """The credential on file that answers this gate, or None.

    Only an exact mapping counts. Nothing is inferred from adjacency: a
    credential in the same field as the requirement is not the
    requirement.
    """
    for credential in held_credentials(company):
        if CREDENTIAL_SATISFIES.get(credential["kind"]) == gate:
            return credential
    return None


# A malformed identifier is worse than a blank one: a blank is obviously
# unfinished, while a typo'd UEI reaches a contracting officer looking
# legitimate and identifies nobody. Format only — whether the value is
# really yours is between you and SAM.gov.
FORMAT_RULES = (
    ("uei", r"^[A-Z0-9]{12}$", "UEI should be exactly 12 letters/digits"),
    ("cage", r"^[A-Z0-9]{5}$", "CAGE should be exactly 5 letters/digits"),
    ("sam_registration_expires", r"^\d{4}-\d{2}-\d{2}$", "SAM expiry should be YYYY-MM-DD"),
)


def format_warnings(company):
    """Values that are present but cannot be right."""
    problems = []
    for key, pattern, message in FORMAT_RULES:
        value = str((company or {}).get(key) or "").strip()
        if value and not re.match(pattern, value.upper()):
            problems.append(f"{key}: {message} (got {value!r})")
    return problems


def skip_reason(company, opp):
    """Why the conveyor belt should not build a packet for this notice,
    or None. Driven entirely by packet_naics / skip_psc / skip_keywords in
    company.toml, so teaching the belt to stop producing work you don't
    perform is a one-line edit rather than a code change."""
    # A registration can carry more codes than the business can actually
    # perform, and the search deliberately covers all of them — you should
    # still see everything in the digest. This narrows only which ones get
    # a bid packet built, so nothing is hidden and nothing unwinnable is
    # prepared. Empty means every registered code is fair game.
    allowed = [str(c).strip() for c in (company.get("packet_naics") or []) if str(c).strip()]
    naics = str(opp.get("naicsCode") or "").strip()
    if allowed and naics and naics not in allowed:
        return f"NAICS {naics} is outside packet_naics (still shown in the digest)"

    psc = (opp.get("classificationCode") or "").upper()

    # NAICS says what industry the buyer filed under; PSC says what is
    # actually being bought, and it is the sharper signal by a wide margin.
    # A gas leak survey at Luke AFB — hoses, gauges, underground leak
    # detection — arrived coded NAICS 541990, the "all other professional
    # services" junk drawer, but its PSC was H999: inspection. Professional
    # services live under R (support services) and B (special studies).
    prefixes = [str(x).strip().upper() for x in (company.get("packet_psc_prefixes") or []) if str(x).strip()]
    if prefixes and psc and not any(psc.startswith(pre) for pre in prefixes):
        return f"PSC {psc} is outside packet_psc_prefixes (still shown in the digest)"

    for blocked in company.get("skip_psc") or []:
        if psc and psc == str(blocked).upper():
            return f"PSC {psc} is in skip_psc"
    haystack = " ".join(
        str(opp.get(field) or "") for field in ("title", "naicsCode", "classificationCode")
    ).lower()
    for phrase in company.get("skip_keywords") or []:
        text = str(phrase).strip().lower()
        if text and text in haystack:
            return f'matches skip_keywords entry "{phrase}"'
    return None


def readiness_report(profile, path=None):
    company = load_company(profile, path)
    required, leverage = missing_fields(company)
    lines = [f"Fact bank: {company.get('_source') or 'NOT FOUND'}", f"Profile:   {profile}", ""]

    if company.get("_error"):
        lines.append(f"  !! {company['_error']}")
        lines.append("     Every field will show as a blank in the packet.")
        return "\n".join(lines), required, leverage

    total_required = len(REQUIRED_FIELDS)
    lines.append(f"Required to submit at all: {total_required - len(required)}/{total_required} entered")
    for label in required:
        lines.append(f"  [ ] {label}")
    if not required:
        lines.append("  all entered")

    lines.append("")
    lines.append("Highest-leverage blanks (each one fills itself on EVERY future packet):")
    for label in leverage:
        lines.append(f"  [ ] {label}")
    if not leverage:
        lines.append("  all entered")

    problems = format_warnings(company)
    if problems:
        lines.append("")
        lines.append("Values that look wrong:")
        for problem in problems:
            lines.append(f"  !! {problem}")

    pp = filled_rows(company, "past_performance")
    rc = filled_rows(company, "rate_card")
    lines += [
        "",
        f"Past performance references on file: {len(pp)} (three is the usual ask)",
        f"Labor categories on file: {len(rc)}",
    ]
    return "\n".join(lines), required, leverage


def main():
    profile = "p1821"
    args = sys.argv[1:]
    if "--profile" in args:
        profile = args[args.index("--profile") + 1]
    report, required, _ = readiness_report(profile)
    print(report)
    print()
    if required:
        print(f"Not submission-ready: {len(required)} required field(s) still blank.")
        print(f"Edit {CONFIG_NAME} and run this again.")
        return 1
    print("Required fields complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
