import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from find_opportunities import (  # noqa: E402
    classify_set_aside,
    days_until_deadline,
    eligibility,
    normalize_set_aside,
    score,
    slugify,
)

# Set-aside strings below are the real values observed in SAM.gov API
# responses during a live run, not invented examples — the earlier
# hyphen-dependent matching failed on exactly these.
REAL_NO_SET_ASIDE = "No Set aside used"
REAL_TOTAL_SB = "Small Business Set Aside - Total"
REAL_WOSB_SOLE_SOURCE = "SBA Certified Women-Owned Small Business (WOSB) Program Sole Source (FAR 19.15)"

WOSB_HOLDER = ["wosb", "edwosb"]


def make_opp(**overrides):
    opp = {
        "noticeId": "N1",
        "title": "Tax and Accounting Support Services",
        "naicsCode": "541213",
        "classificationCode": "R710",
        "typeOfSetAsideDescription": None,
        "responseDeadLine": None,
        "placeOfPerformance": {"city": {"name": "Austin"}, "state": {"code": "TX"}},
        "uiLink": "https://sam.gov/opp/N1",
        "description": None,
        "resourceLinks": [],
    }
    opp.update(overrides)
    return opp


# ---------- normalization ----------

def test_normalize_flattens_hyphens_and_case():
    assert normalize_set_aside("Small Business Set-Aside") == "small business set aside"
    assert normalize_set_aside(REAL_TOTAL_SB) == "small business set aside total"


def test_normalize_keeps_parentheses_so_8a_stays_distinct():
    assert "8(a)" in normalize_set_aside("8(a) Sole Source")


# ---------- "no set-aside" phrasings ----------

def test_empty_set_aside_is_full_and_open():
    assert eligibility(make_opp(typeOfSetAsideDescription=None)) == "full_open"


def test_literal_no_set_aside_used_is_full_and_open():
    # Regression: SAM.gov sends this string instead of an empty field, and it
    # was previously read as an unrecognized set-aside needing verification.
    opp = make_opp(typeOfSetAsideDescription=REAL_NO_SET_ASIDE)
    assert classify_set_aside(opp) is None
    assert eligibility(opp) == "full_open"


def test_full_and_open_wording_is_full_and_open():
    assert eligibility(make_opp(typeOfSetAsideDescription="Full and Open")) == "full_open"


# ---------- real total-small-business phrasing ----------

def test_real_total_small_business_string_is_recognized():
    # Regression: "Small Business Set Aside - Total" has no hyphen in "Set
    # Aside", so the old hint "small business set-aside" never matched and
    # every such notice scored as unknown.
    assert classify_set_aside(make_opp(typeOfSetAsideDescription=REAL_TOTAL_SB)) == {"small_business"}


def test_wosb_holder_is_eligible_for_generic_small_business_set_aside():
    # A WOSB *is* a small business, so a WOSB-only profile must still qualify
    # for total-small-business set-asides.
    opp = make_opp(typeOfSetAsideDescription=REAL_TOTAL_SB)
    assert eligibility(opp, WOSB_HOLDER) == "eligible_set_aside"


def test_holding_nothing_makes_a_small_business_set_aside_restricted():
    opp = make_opp(typeOfSetAsideDescription=REAL_TOTAL_SB)
    assert eligibility(opp, []) == "restricted"


# ---------- WOSB / EDWOSB ----------

def test_real_wosb_sole_source_string_is_eligible_for_wosb_holder():
    opp = make_opp(typeOfSetAsideDescription=REAL_WOSB_SOLE_SOURCE)
    assert eligibility(opp, WOSB_HOLDER) == "eligible_set_aside"


def test_edwosb_is_not_satisfied_by_plain_wosb_certification():
    # EDWOSB text also says "women-owned", but EDWOSB is the stricter
    # program — a WOSB-only holder must not read as eligible.
    opp = make_opp(typeOfSetAsideDescription="Economically Disadvantaged Women-Owned Small Business (EDWOSB)")
    assert classify_set_aside(opp) == {"edwosb"}
    assert eligibility(opp, ["wosb"]) == "restricted"
    assert eligibility(opp, ["edwosb"]) == "eligible_set_aside"


# ---------- programs we don't hold ----------

def test_8a_restricted_for_wosb_holder():
    assert eligibility(make_opp(typeOfSetAsideDescription="8(a) Sole Source"), WOSB_HOLDER) == "restricted"


def test_hubzone_restricted_for_wosb_holder():
    assert eligibility(make_opp(typeOfSetAsideDescription="HUBZone Set-Aside"), WOSB_HOLDER) == "restricted"


def test_sdvosb_does_not_read_as_vosb():
    # "veteran owned" is a substring of "service-disabled veteran-owned", so a
    # VOSB holder must not be told an SDVOSB set-aside is theirs to bid.
    opp = make_opp(typeOfSetAsideDescription="Service-Disabled Veteran-Owned Small Business (SDVOSB) Set-Aside")
    assert classify_set_aside(opp) == {"sdvosb"}
    assert eligibility(opp, ["vosb"]) == "restricted"


def test_unrecognized_set_aside_is_flagged_not_assumed():
    opp = make_opp(typeOfSetAsideDescription="Some Future Set-Aside Program")
    assert classify_set_aside(opp) == set()
    assert eligibility(opp) == "unknown_set_aside"


# ---------- deadlines ----------

def test_days_until_deadline_handles_timestamps_and_blanks():
    future = (date.today() + timedelta(days=9)).isoformat()
    assert days_until_deadline(make_opp(responseDeadLine=future + "T09:00:00-04:00")) == 9
    assert days_until_deadline(make_opp(responseDeadLine=None)) is None
    assert days_until_deadline(make_opp(responseDeadLine="not-a-date")) is None


def test_days_until_deadline_is_negative_once_passed():
    past = (date.today() - timedelta(days=3)).isoformat()
    assert days_until_deadline(make_opp(responseDeadLine=past)) == -3


# ---------- scoring ----------

def test_eligible_set_aside_scores_above_full_and_open():
    eligible = make_opp(typeOfSetAsideDescription=REAL_WOSB_SOLE_SOURCE)
    open_to_all = make_opp(typeOfSetAsideDescription=REAL_NO_SET_ASIDE)
    assert score(eligible, 7, 60, WOSB_HOLDER)[0] > score(open_to_all, 7, 60, WOSB_HOLDER)[0]


def test_full_and_open_is_not_flagged_for_verification():
    _, reasons = score(make_opp(typeOfSetAsideDescription=REAL_NO_SET_ASIDE), 7, 60, WOSB_HOLDER)
    assert "verify eligibility" not in reasons


def test_unknown_set_aside_is_flagged_but_unscored():
    pts_unknown, reasons = score(make_opp(typeOfSetAsideDescription="Some Future Program"), 7, 60, WOSB_HOLDER)
    pts_plain, _ = score(make_opp(typeOfSetAsideDescription=None), 7, 60, WOSB_HOLDER)
    assert "verify eligibility" in reasons
    assert pts_unknown == pts_plain


def test_score_keyword_matches_title():
    _, reasons = score(make_opp(title="Independent Program Evaluation and Audit Services"), 7, 60)
    assert "keyword match" in reasons


def test_score_home_state_bonus():
    tx = make_opp(placeOfPerformance={"city": {"name": "Austin"}, "state": {"code": "TX"}})
    ks = make_opp(placeOfPerformance={"city": {"name": "Wichita"}, "state": {"code": "KS"}})
    assert score(tx, 7, 60)[0] > score(ks, 7, 60)[0]


def test_score_deadline_window():
    in_window = make_opp(responseDeadLine=(date.today() + timedelta(days=20)).isoformat())
    too_soon = make_opp(responseDeadLine=(date.today() + timedelta(days=1)).isoformat())
    pts_in, reasons_in = score(in_window, 7, 60)
    pts_soon, _ = score(too_soon, 7, 60)
    assert "deadline" in reasons_in
    assert pts_in > pts_soon


def test_slugify_handles_punctuation_and_length():
    assert slugify("Tax & Accounting: Support, Services!") == "tax-accounting-support-services"
    assert slugify(None) == "opportunity"
    assert len(slugify("x" * 200)) <= 50
