"""Recurring-contract gate for the SAM.gov search.

The firm stacks multi-year service contracts. A one-off roof repair, fence
install, or one-day crane lift is not that business, even when the NAICS
code is one we search. This module decides three things for each notice:

  include       recurring work, and both the monthly value and the term
                clear the floor
  needs_review  it looks recurring, but the value or the term cannot be
                read — kept, and labelled, rather than dropped
  exclude       a one-off, or a recurring notice whose stated value or
                term fails the floor
  unconfirmed   nothing says it is a recurring service contract; the
                search drops it once the description has been checked

Thresholds live in company.toml under [shared.contract_criteria] and can
be overridden from the command line or the web Settings form. The
defaults are the strategy set on 2026-11-20: at least $1,000 a month for
at least 24 months ($24,000 over the term), a preferred band of 5 to 10
years, and a ranking bias toward a $10,000-a-month portfolio.
"""

import re
from datetime import date

DEFAULT_CRITERIA = {
    "min_monthly_value": 1000.0,
    "min_months": 24,
    "preferred_months": 60,
    "preferred_months_max": 120,
    "target_monthly_portfolio": 10000.0,
}

CRITERIA_KEYS = tuple(DEFAULT_CRITERIA)

# NAICS that are recurring building services by definition. A notice filed
# under one of these is janitorial, grounds, or facility support even when
# the title is vague.
RECURRING_NAICS = frozenset({
    "561720",  # Janitorial Services
    "561730",  # Landscaping Services
    "561210",  # Facilities Support Services
    "561790",  # Other Services to Buildings and Dwellings
})

_COUNT_WORD = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_COUNT = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})"

# Words that mean "this is a vehicle or a base-plus-options term", not a
# single job. A roofing MATOC matches; a roof repair does not.
_VEHICLE = re.compile(
    r"\bidiq\b|\bbpa\b|\bboa\b|\bmatoc\b|\bsatoc\b|\bmacc\b|\bjoc\b|"
    r"job order contract|blanket purchase|"
    r"indefinite[- ]delivery|indefinite[- ]quantity|multiple[- ]award|"
    r"base\s+(?:year|period)|option\s+(?:year|period)",
    re.I,
)

# The work itself is a repeating service. "repair" is deliberately absent:
# a repair is the one-off this filter exists to stop.
_SERVICE = re.compile(
    r"\bjanitorial\b|\bcustodial\b|"
    r"\bgrounds?\s+maintenance\b|\blandscaping\b|\bgroundskeeping\b|"
    r"\bfacilit(?:y|ies)\s+(?:support|maintenance|operations)\b|"
    r"\brecurring\b|"
    r"\bprevent(?:ive|ative)\s+maintenance\b|"
    r"\bmaintenance\s+services?\b",
    re.I,
)

# A single job. Matched only when no vehicle or recurring-service phrase
# is present, so "janitorial, including minor repair" stays and "roof
# repair" goes.
_ONE_OFF = re.compile(
    r"\bone[- ]time\b|\bone[- ]day\b|"
    r"\broofs?\b|\broofing\b|\bfence\b|\bcrane\b|"
    r"\binstall(?:ation|ing|ed)?\b|\breplacements?\b|"
    r"\brenovat(?:e|ion|ing)\b|\bremodels?\b|\bremodeling\b|"
    r"\bdemolition\b|\brepairs?\b",
    re.I,
)

_MODERATE = re.compile(r"\bannual(?:ly)?\b|\bmonthly\b", re.I)

_NO_OPTIONS = re.compile(
    r"\b(?:no|without|zero|0)\s+option\s+(?:year|period)",
    re.I,
)

_DURATION_CONTEXT = re.compile(
    r"period of performance|performance period|ordering period|"
    r"contract (?:period|term|duration)|term of (?:the )?contract|"
    r"\bpop\b|base\s+(?:year|period)|option\s+(?:year|period)|"
    r"\bidiq\b|\bbpa\b|\bboa\b",
    re.I,
)

_YEAR_SPAN = re.compile(
    r"\b(?:(?P<word>one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\s*(?:\(\s*(?P<paren>\d{1,2})\s*\))?|(?P<num>\d{1,2}))"
    r"\s*[- ]?\s*years?\b",
    re.I,
)
_MONTH_SPAN = re.compile(r"\b(?P<num>\d{1,3})\s*[- ]?\s*months?\b", re.I)

_MONTH_NAME = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
)
_NAMED_DATE = re.compile(
    rf"\b(?P<mon>{_MONTH_NAME})\.?\s+(?P<day>\d{{1,2}}),?\s+(?P<year>\d{{4}})\b",
    re.I,
)
_NUMERIC_DATE = re.compile(r"\b(?P<m>\d{1,2})[/-](?P<d>\d{1,2})[/-](?P<y>\d{4})\b")
_ISO_DATE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")

_MONEY = re.compile(
    r"\$\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>million|billion|thousand|m|b|k)?\b",
    re.I,
)
_PER_MONTH = re.compile(
    r"\$\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>million|billion|thousand|m|b|k)?"
    r"\s*(?:per|/|a)\s*months?\b",
    re.I,
)
_PER_YEAR = re.compile(
    r"\$\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>million|billion|thousand|m|b|k)?"
    r"\s*(?:per|/|a)\s*(?:year|annum)\b|\$\s*(?P<num2>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*(?P<unit2>million|billion|thousand|m|b|k)?\s+annually\b",
    re.I,
)
_TOTAL_CUE = re.compile(
    r"estimated(?:\s+(?:total\s+)?)?(?:value|cost|amount|price)?|"
    r"not to exceed|n\.?t\.?e\.?|(?:award\s+)?ceiling|"
    r"base and all options|total(?:\s+contract)?\s+(?:value|amount|price)|"
    r"magnitude",
    re.I,
)
_RANGE = re.compile(
    r"\$\s*(?P<num1>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit1>million|billion|thousand|m|b|k)?"
    r"\s*(?:to|and|–|—|-)\s*"
    r"\$\s*(?P<num2>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<unit2>million|billion|thousand|m|b|k)?",
    re.I,
)


class ContractAssessment(object):
    """The gate's decision for one notice, plus the numbers it used."""

    def __init__(self, disposition, months=None, monthly_value=None,
                 total_value=None, looks_recurring=False, one_time=False,
                 signals=None):
        self.disposition = disposition
        self.months = months
        self.monthly_value = monthly_value
        self.total_value = total_value
        self.looks_recurring = looks_recurring
        self.one_time = one_time
        self.signals = list(signals or [])

    def as_dict(self):
        return {
            "disposition": self.disposition,
            "months": self.months,
            "monthly_value": self.monthly_value,
            "total_value": self.total_value,
            "looks_recurring": self.looks_recurring,
            "one_time": self.one_time,
            "signals": list(self.signals),
        }


def criteria_from_mapping(mapping=None, overrides=None):
    """Defaults, then mapping, then overrides. Empty values are ignored.

    preferred_months is pulled up to the minimum term, and the top of the
    preferred band is pulled up to preferred_months, so a typo cannot
    invert the ranking (a "preferred" term shorter than the floor).
    """
    raw = dict(DEFAULT_CRITERIA)
    for source in (mapping or {}, overrides or {}):
        for key in CRITERIA_KEYS:
            if key not in source:
                continue
            value = source[key]
            if value is None or value == "":
                continue
            raw[key] = value
    criteria = {
        "min_monthly_value": max(1.0, float(raw["min_monthly_value"])),
        "min_months": max(1, int(raw["min_months"])),
        "preferred_months": max(1, int(raw["preferred_months"])),
        "preferred_months_max": max(1, int(raw["preferred_months_max"])),
        "target_monthly_portfolio": max(1.0, float(raw["target_monthly_portfolio"])),
    }
    if criteria["preferred_months"] < criteria["min_months"]:
        criteria["preferred_months"] = criteria["min_months"]
    if criteria["preferred_months_max"] < criteria["preferred_months"]:
        criteria["preferred_months_max"] = criteria["preferred_months"]
    return criteria


def load_criteria(profile=None, path=None):
    """Thresholds from company.toml, or the defaults when the file has none."""
    found = {}
    try:
        from company import load_company
        company = load_company(profile or "p1821", path)
        block = company.get("contract_criteria")
        if isinstance(block, dict):
            found = block
    except Exception:
        found = {}
    return criteria_from_mapping(found)


def save_contract_criteria(updates, path=None):
    """Rewrite the five threshold lines in company.toml. Comments stay.

    This is the one copy the daily search and the website both read. A
    second copy in settings.json is how a certification flag went stale
    once already, so the form writes this file instead.
    """
    from company import config_path
    path = path or config_path()
    normalized = criteria_from_mapping(load_criteria(path=path), updates)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    missing = []
    for key, value in normalized.items():
        rendered = _format_number(value)
        pattern = re.compile(
            rf"^({re.escape(key)}\s*=\s*)([0-9]+(?:\.[0-9]+)?)(.*)$",
            re.M,
        )
        text, count = pattern.subn(rf"\g<1>{rendered}\g<3>", text, count=1)
        if count != 1:
            missing.append(f"{key} = {rendered}")
    if missing:
        # An older company.toml, including one copied onto a host before
        # these thresholds existed, gets the block on the first save.
        block = "\n".join(missing) + "\n"
        header = "[shared.contract_criteria]\n"
        if header in text:
            text = text.replace(header, header + block, 1)
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += "\n" + header + block
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return normalized


def _format_number(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def assess_contract(opp, criteria=None, description_text=None):
    """Classify one notice. criteria defaults to the built-in floors."""
    criteria = criteria_from_mapping(criteria)
    blob = _notice_blob(opp, description_text)
    looks_recurring, one_time = _shape(opp, blob)
    months = _duration_months(opp, blob)
    monthly, total, high, ambiguous = _value(opp, blob)
    monthly, total, ambiguous = _resolve_range(
        monthly, total, high, ambiguous, months, criteria)

    if monthly is None and total and months and not ambiguous:
        monthly = round(total / float(months), 2)
    if monthly and total and months is None and not ambiguous and monthly > 0:
        inferred = int(round(total / float(monthly)))
        if 12 <= inferred <= 240:
            months = inferred

    disposition = _disposition(
        looks_recurring, one_time, months, monthly, total, ambiguous, criteria)
    signals = []
    if looks_recurring:
        signals.append("recurring")
    if one_time and not looks_recurring:
        signals.append("one-time")
    if months:
        signals.append(f"{months} months")
    if monthly:
        signals.append(f"${monthly:,.0f}/mo")
    return ContractAssessment(
        disposition=disposition,
        months=months if disposition != "exclude" or months else months,
        monthly_value=monthly,
        total_value=total,
        looks_recurring=looks_recurring,
        one_time=one_time and not looks_recurring,
        signals=signals,
    )


def score_contract_fit(assessment, criteria=None):
    """Points and reasons for the ranker.

    Confirmed longer terms and higher monthly value outrank a notice that
    only looks recurring. Needs-review still ranks — on whatever number
    could be read, then on the ordinary score — and always says so.
    A one-off is scored far below anything the filter might have missed.
    """
    criteria = criteria_from_mapping(criteria)
    if assessment.disposition == "exclude":
        return -12, ["one-time or below the recurring-contract floor"]
    if assessment.disposition == "unconfirmed":
        return 0, []

    points = 2
    reasons = ["recurring service contract"]
    duration = _duration_points(assessment.months, criteria)
    if duration:
        points += duration
        reasons.append(_duration_reason(assessment.months, criteria))
    value = _value_points(assessment.monthly_value, criteria)
    if value:
        points += value
        reasons.append(_value_reason(assessment.monthly_value, criteria))
    if assessment.disposition == "needs_review":
        reasons.append("needs review — value or duration not stated")
    return points, reasons


def contract_fit_label(opp):
    """One line for the shortlist card, or None when the notice was not assessed."""
    fit = opp.get("_contract_fit") or {}
    if not fit:
        return None
    parts = []
    if fit.get("months"):
        parts.append(f"{fit['months']} months")
    monthly = fit.get("monthly_value")
    if monthly:
        parts.append(f"${monthly:,.0f}/mo")
    if fit.get("disposition") == "needs_review":
        parts.append("needs review — value or duration not stated")
    elif fit.get("disposition") == "include" and not parts:
        parts.append("recurring service contract")
    if not parts:
        return None
    return ", ".join(parts)


def _disposition(looks_recurring, one_time, months, monthly, total, ambiguous, criteria):
    if one_time and not looks_recurring:
        return "exclude"
    if not looks_recurring:
        return "unconfirmed"

    floor = criteria["min_monthly_value"]
    min_months = criteria["min_months"]
    floor_total = floor * min_months

    if months is not None and months < min_months:
        return "exclude"
    if monthly is not None and monthly < floor:
        return "exclude"
    if monthly is None and total is not None and not ambiguous and total < floor_total:
        return "exclude"
    if ambiguous:
        # A range that straddles the floor is not a number we can rank on.
        # Both-ends-below and both-ends-above are resolved before this.
        return "needs_review"

    known_value = monthly is not None and monthly >= floor
    known_term = months is not None and months >= min_months
    if known_value and known_term and not ambiguous:
        return "include"
    return "needs_review"


def _shape(opp, blob):
    naics = str(opp.get("naicsCode") or "").strip()
    psc = (opp.get("classificationCode") or "").strip().upper()
    text_recurring = bool(_VEHICLE.search(blob) or _SERVICE.search(blob))
    one_off_job = bool(_ONE_OFF.search(blob))
    construction = naics.startswith("23") or (bool(psc) and psc[0] in {"Y", "Z"})
    code_recurring = naics in RECURRING_NAICS or (psc.startswith("S") and len(psc) >= 2)
    moderate = bool(_MODERATE.search(blob))

    if text_recurring:
        return True, False
    if one_off_job or construction:
        return False, True
    if code_recurring or moderate:
        return True, False
    return False, False


def _notice_blob(opp, description_text):
    parts = [opp.get("title") or ""]
    pop = opp.get("periodOfPerformance")
    if isinstance(pop, str):
        parts.append(pop)
    elif isinstance(pop, dict):
        parts.append(" ".join(str(v) for v in pop.values() if v))
    if description_text:
        parts.append(description_text)
    return "\n".join(parts)


def _duration_months(opp, blob):
    narrative = _base_plus_option_months(blob)
    ranged = _date_range_months(blob)
    structured = _structured_months(opp)
    chosen = [m for m in (narrative, ranged, structured) if m]
    if chosen:
        return max(chosen)
    return _span_months(blob)


def _base_plus_option_months(text):
    if _NO_OPTIONS.search(text):
        base = _base_months(text)
        return base
    base = _base_months(text)
    options = _option_months(text)
    mentions_options = bool(re.search(r"\boption\s+(?:year|period)", text, re.I))
    if base is not None and options is not None:
        return base + options
    if options is not None:
        if re.search(r"\bbase\s+year\b", text, re.I):
            return 12 + options
        return options
    if mentions_options:
        # "base year and option years" with the count left unstated is
        # still at least two years. Recording only the base year would
        # throw the notice out for being too short.
        if base is None:
            return 24
        return max(base + 12, 24)
    if base is not None and not mentions_options:
        return base
    return None


def _base_months(text):
    match = re.search(r"\b(\d{1,3})\s*[- ]?months?\s+base\b", text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(
        r"\bbase\s+(?:year|period|term)s?\s+of\s+(\d{1,3})\s*(months?|years?)\b",
        text, re.I)
    if match:
        length = int(match.group(1))
        if match.group(2).lower().startswith("year"):
            return length * 12
        return length
    match = re.search(
        rf"\b(?P<count>{_COUNT})\s*(?:\(\s*(?P<paren>\d{{1,2}})\s*\))?\s+base\s+years?\b",
        text, re.I)
    if match:
        count = _count_from(match.group("paren"), match.group("count"))
        if count:
            return count * 12
    if re.search(r"\bbase\s+year\b", text, re.I):
        return 12
    return None


def _option_months(text):
    patterns = (
        re.compile(
            rf"\b(?P<count>{_COUNT})\s*(?:\(\s*(?P<paren>\d{{1,2}})\s*\))?\s+"
            rf"(?P<length>\d{{1,3}})\s*[- ]?months?\s+options?\b",
            re.I,
        ),
        re.compile(
            rf"\b(?P<count>{_COUNT})\s*(?:\(\s*(?P<paren>\d{{1,2}})\s*\))?\s+"
            rf"(?:one[- ]year|12[- ]month)\s+options?\b",
            re.I,
        ),
        re.compile(
            rf"\b(?P<count>{_COUNT})\s*(?:\(\s*(?P<paren>\d{{1,2}})\s*\))?\s+"
            rf"option\s+years?\b",
            re.I,
        ),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        count = _count_from(match.group("paren"), match.group("count"))
        if not count:
            continue
        if "length" in match.groupdict() and match.group("length"):
            return count * int(match.group("length"))
        return count * 12
    return None


def _count_from(paren, word):
    if paren and str(paren).isdigit():
        return int(paren)
    return _parse_count(word)


def _parse_count(token):
    if token is None:
        return None
    text = str(token).strip().lower()
    if text in _COUNT_WORD:
        return _COUNT_WORD[text]
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _span_months(text):
    """The longest 'N years' or 'N months' sitting next to a term phrase.

    '5 years of experience' with no term phrase nearby is not a period of
    performance. When several spans sit near one, the longest wins, so a
    '12 months' transition does not hide a 5-year term in the same paragraph.
    """
    best = None
    for match in _YEAR_SPAN.finditer(text):
        count = _count_from(match.group("paren"), match.group("word") or match.group("num"))
        if not count:
            continue
        if not _near_context(text, match.start(), match.end()):
            continue
        best = max(best or 0, count * 12)
    for match in _MONTH_SPAN.finditer(text):
        count = int(match.group("num"))
        if not _near_context(text, match.start(), match.end()):
            continue
        best = max(best or 0, count)
    return best


def _near_context(text, start, end, window=70):
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    return bool(_DURATION_CONTEXT.search(text[lo:hi]))


def _date_range_months(text):
    found = []
    for pattern, parser in (
        (_ISO_DATE, lambda m: _safe_date(int(m.group("y")), int(m.group("m")), int(m.group("d")))),
        (_NUMERIC_DATE, lambda m: _safe_date(int(m.group("y")), int(m.group("m")), int(m.group("d")))),
        (_NAMED_DATE, lambda m: _safe_date(int(m.group("year")), _month_number(m.group("mon")), int(m.group("day")))),
    ):
        for match in pattern.finditer(text):
            parsed = parser(match)
            if parsed:
                found.append((match.start(), match.end(), parsed))
    found.sort()
    best = None
    for index in range(len(found) - 1):
        left_end = found[index][1]
        right_start = found[index + 1][0]
        between = text[left_end:right_start]
        if len(between) > 30 or not re.search(r"through|thru|\bto\b|–|—|-", between, re.I):
            continue
        if not _near_context(text, found[index][0], found[index + 1][1]):
            continue
        months = _months_between(found[index][2], found[index + 1][2])
        if months:
            best = max(best or 0, months)
    return best


def _structured_months(opp):
    pop = opp.get("periodOfPerformance")
    if isinstance(pop, dict):
        start = pop.get("startDate") or pop.get("start") or pop.get("popStart")
        end = pop.get("endDate") or pop.get("end") or pop.get("popEnd")
        months = _months_between_raw(start, end)
        if months:
            return months
    for start_key, end_key in (
        ("popStartDate", "popEndDate"),
        ("performanceStart", "performanceEnd"),
        ("periodOfPerformanceStart", "periodOfPerformanceEnd"),
    ):
        months = _months_between_raw(opp.get(start_key), opp.get(end_key))
        if months:
            return months
    return None


def _months_between_raw(start, end):
    if not start or not end:
        return None
    left = _parse_any_date(str(start)[:10])
    right = _parse_any_date(str(end)[:10])
    if not left or not right:
        return None
    return _months_between(left, right)


def _parse_any_date(text):
    text = (text or "").strip()
    iso = _ISO_DATE.search(text)
    if iso:
        return _safe_date(int(iso.group("y")), int(iso.group("m")), int(iso.group("d")))
    numeric = _NUMERIC_DATE.search(text)
    if numeric:
        return _safe_date(int(numeric.group("y")), int(numeric.group("m")), int(numeric.group("d")))
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _months_between(start, end):
    days = (end - start).days
    if days <= 0:
        return None
    months = int(round(days / 30.436875))
    return months if months > 0 else None


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _month_number(token):
    key = (token or "").lower()[:3]
    return {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }.get(key)


def _resolve_range(monthly, total, high, ambiguous, months, criteria):
    """Turn a dollar range into a single monthly figure, or leave it open.

    Both ends under the floor is a no. Both ends over it ranks on the low
    end, so a wide range cannot outrank a contract that actually pays the
    top of that range. A range that straddles the floor stays unresolved.
    """
    if not ambiguous or high is None or total is None:
        return monthly, total, False
    floor = criteria["min_monthly_value"]
    floor_total = floor * criteria["min_months"]
    if months:
        low_monthly = total / float(months)
        high_monthly = high / float(months)
        if high_monthly < floor:
            return round(high_monthly, 2), total, False
        if low_monthly >= floor:
            return round(low_monthly, 2), total, False
        return None, None, True
    if high < floor_total:
        return monthly, high, False
    return None, None, True


def _value(opp, blob):
    """(monthly, total, high, ambiguous).

    An explicit per-month or per-year figure is the monthly rate. A range
    keeps both ends so the caller can see whether it clears the floor. A
    bare dollar amount with no value cue (a wage, a bond) is ignored.
    """
    consumed = []
    monthly = _first_amount(_PER_MONTH, blob, consumed, allow_num2=False)
    annual = _first_amount(_PER_YEAR, blob, consumed, allow_num2=True)
    low, high = _range_totals(blob, consumed)
    totals = _cued_totals(blob, consumed)
    structured = _structured_total(opp)

    if monthly is None and annual:
        monthly = round(annual / 12.0, 2)
    if monthly is not None:
        # A stated rate is the number to rank. A ceiling beside it does not
        # replace it; it is kept only so a missing term can be inferred.
        total = max(totals) if totals else structured
        return monthly, total, None, False
    if low is not None and high is not None:
        if structured and structured > high:
            high = structured
        return None, low, high, True
    if totals:
        return None, max(totals), None, False
    if structured:
        return None, structured, None, False
    return None, None, None, False


def _range_totals(text, consumed):
    match = _RANGE.search(text)
    if not match:
        return None, None
    if not _TOTAL_CUE.search(text[max(0, match.start() - 50):match.end() + 20]):
        # "between $25,000 and $100,000" uses "between", which the cue
        # list does not name. Accept "between" and "magnitude" neighbours.
        window = text[max(0, match.start() - 40):match.start()]
        if not re.search(r"between|from|range|magnitude", window, re.I):
            return None, None
    if _overlaps(consumed, match.start(), match.end()):
        return None, None
    low = _money(match.group("num1"), match.group("unit1"))
    high = _money(match.group("num2"), match.group("unit2"))
    if low is None or high is None:
        return None, None
    if low > high:
        low, high = high, low
    consumed.append((match.start(), match.end()))
    return low, high


def _cued_totals(text, consumed):
    found = []
    for cue in _TOTAL_CUE.finditer(text):
        window_end = min(len(text), cue.end() + 50)
        money = _MONEY.search(text, cue.end(), window_end)
        if not money:
            continue
        if _overlaps(consumed, money.start(), money.end()):
            continue
        amount = _money(money.group("num"), money.group("unit"))
        if amount:
            found.append(amount)
            consumed.append((money.start(), money.end()))
    return found


def _first_amount(pattern, text, consumed, allow_num2):
    for match in pattern.finditer(text):
        if _overlaps(consumed, match.start(), match.end()):
            continue
        number = match.group("num") if match.groupdict().get("num") else None
        unit = match.group("unit") if match.groupdict().get("unit") else None
        if allow_num2 and not number:
            number = match.groupdict().get("num2")
            unit = match.groupdict().get("unit2")
        amount = _money(number, unit)
        if amount:
            consumed.append((match.start(), match.end()))
            return amount
    return None


def _structured_total(opp):
    for key in (
        "baseAndAllOptionsValue", "awardCeiling", "estimatedValue",
        "estimatedTotalValue", "ceiling",
    ):
        amount = _coerce_money(opp.get(key))
        if amount:
            return amount
    award = opp.get("award")
    if isinstance(award, dict):
        return _coerce_money(award.get("amount"))
    return None


def _coerce_money(value):
    if value in (None, "", 0, 0.0, "0", "0.0", "0.00"):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value).strip()
    match = _MONEY.search(text if "$" in text else "$" + text)
    if not match:
        return None
    return _money(match.group("num"), match.group("unit"))


def _money(number, unit):
    if not number:
        return None
    try:
        amount = float(str(number).replace(",", ""))
    except ValueError:
        return None
    unit = (unit or "").lower()
    if unit in ("million", "m"):
        amount *= 1000000
    elif unit in ("billion", "b"):
        amount *= 1000000000
    elif unit in ("thousand", "k"):
        amount *= 1000
    if amount <= 0:
        return None
    return amount


def _overlaps(spans, start, end):
    return any(not (end <= left or start >= right) for left, right in spans)


def _duration_points(months, criteria):
    if not months:
        return 0
    preferred = criteria["preferred_months"]
    preferred_max = criteria["preferred_months_max"]
    minimum = criteria["min_months"]
    if months >= preferred_max:
        return 8
    if months >= preferred:
        span = max(preferred_max - preferred, 1)
        return 6 + int(2 * (months - preferred) / span)
    if months >= minimum:
        span = max(preferred - minimum, 1)
        return 2 + int(3 * (months - minimum) / span)
    return 0


def _value_points(monthly, criteria):
    if not monthly:
        return 0
    target = criteria["target_monthly_portfolio"]
    floor = criteria["min_monthly_value"]
    if monthly >= target:
        extra = min(4, int((monthly - target) / target * 4))
        return 8 + extra
    if monthly >= floor:
        span = max(target - floor, 1)
        return 2 + int(6 * (monthly - floor) / span)
    return 0


def _duration_reason(months, criteria):
    if months >= criteria["preferred_months_max"]:
        return f"{months}-month term (at or above the preferred range)"
    if months >= criteria["preferred_months"]:
        return f"{months}-month term (preferred range)"
    return f"{months}-month term"


def _value_reason(monthly, criteria):
    shown = f"${monthly:,.0f}/mo"
    target = criteria["target_monthly_portfolio"]
    if monthly >= target:
        return f"{shown} (at or above the ${target:,.0f}/mo portfolio target)"
    return shown

