import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from find_opportunities import eligibility, score, slugify  # noqa: E402


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


def test_eligibility_full_and_open():
    assert eligibility(make_opp(typeOfSetAsideDescription=None)) == "full_open"


def test_eligibility_wosb_is_eligible():
    opp = make_opp(typeOfSetAsideDescription="Woman-Owned Small Business Set-Aside")
    assert eligibility(opp) == "eligible_set_aside"


def test_eligibility_edwosb_is_eligible():
    opp = make_opp(typeOfSetAsideDescription="Economically Disadvantaged Women-Owned Small Business")
    assert eligibility(opp) == "eligible_set_aside"


def test_eligibility_total_small_business_is_eligible():
    opp = make_opp(typeOfSetAsideDescription="Total Small Business Set-Aside")
    assert eligibility(opp) == "eligible_set_aside"


def test_eligibility_8a_is_restricted():
    opp = make_opp(typeOfSetAsideDescription="8(a) Sole Source")
    assert eligibility(opp) == "restricted"


def test_eligibility_hubzone_is_restricted():
    opp = make_opp(typeOfSetAsideDescription="HUBZone Set-Aside")
    assert eligibility(opp) == "restricted"


def test_eligibility_sdvosb_is_restricted():
    opp = make_opp(typeOfSetAsideDescription="Service-Disabled Veteran-Owned Small Business")
    assert eligibility(opp) == "restricted"


def test_eligibility_unrecognized_is_unknown():
    opp = make_opp(typeOfSetAsideDescription="Some Future Set-Aside Program")
    assert eligibility(opp) == "unknown_set_aside"


def test_score_gives_points_for_eligible_set_aside():
    with_set_aside = make_opp(typeOfSetAsideDescription="Woman-Owned Small Business Set-Aside")
    without = make_opp(typeOfSetAsideDescription=None)
    pts_with, _ = score(with_set_aside, 7, 60)
    pts_without, _ = score(without, 7, 60)
    assert pts_with > pts_without


def test_score_unknown_set_aside_gets_no_bonus_but_is_flagged():
    opp = make_opp(typeOfSetAsideDescription="Some Future Set-Aside Program")
    pts, reasons = score(opp, 7, 60)
    assert "verify eligibility" in reasons


def test_score_keyword_matches_title():
    opp = make_opp(title="Independent Program Evaluation and Audit Services")
    pts, reasons = score(opp, 7, 60)
    assert "keyword match" in reasons


def test_score_home_state_bonus():
    tx_opp = make_opp(placeOfPerformance={"city": {"name": "Austin"}, "state": {"code": "TX"}})
    ks_opp = make_opp(placeOfPerformance={"city": {"name": "Wichita"}, "state": {"code": "KS"}})
    pts_tx, _ = score(tx_opp, 7, 60)
    pts_ks, _ = score(ks_opp, 7, 60)
    assert pts_tx > pts_ks


def test_score_deadline_window():
    from datetime import date, timedelta

    in_window = make_opp(responseDeadLine=(date.today() + timedelta(days=20)).isoformat())
    too_soon = make_opp(responseDeadLine=(date.today() + timedelta(days=1)).isoformat())
    pts_in, reasons_in = score(in_window, 7, 60)
    pts_soon, reasons_soon = score(too_soon, 7, 60)
    assert "deadline" in reasons_in
    assert pts_in > pts_soon


def test_slugify_handles_punctuation_and_length():
    assert slugify("Tax & Accounting: Support, Services!") == "tax-accounting-support-services"
    assert slugify(None) == "opportunity"
    assert len(slugify("x" * 200)) <= 50
