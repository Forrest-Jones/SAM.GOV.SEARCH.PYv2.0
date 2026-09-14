import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from find_opportunities import (  # noqa: E402
    DEFAULT_HELD_CERTS,
    DEFAULT_NAICS,
    KEYWORDS,
    PROFILES,
    classify_set_aside,
    days_until_deadline,
    eligibility,
    is_supply_notice,
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


def test_vosb_set_aside_is_not_read_as_a_generic_small_business_set_aside():
    # Verbatim from a live SAM.gov run (notice: "Repair Bonham Walk-in
    # Freezer"). Every program's official name contains the words "small
    # business", so this string also matched the generic small-business hint
    # and the notice was reported as eligible to a WOSB-only holder.
    opp = make_opp(typeOfSetAsideDescription=(
        "Veteran-Owned Small Business Set-Aside "
        "(specific to Department of Veterans Affairs)"))
    assert classify_set_aside(opp) == {"vosb"}
    assert eligibility(opp, WOSB_HOLDER) == "restricted"
    assert eligibility(opp, ["vosb"]) == "eligible_set_aside"


def test_named_program_set_asides_never_fall_back_to_generic_small_business():
    # The same shadowing applies to every program whose spelled-out name ends
    # in "Small Business Set-Aside", not just the VA's veteran-owned wording.
    for text, expected in [
        ("Service-Disabled Veteran-Owned Small Business Set-Aside", "sdvosb"),
        ("HUBZone Small Business Set-Aside", "hubzone"),
        ("8(a) Small Business Set-Aside", "8a"),
    ]:
        opp = make_opp(typeOfSetAsideDescription=text)
        assert classify_set_aside(opp) == {expected}, text
        assert eligibility(opp, WOSB_HOLDER) == "restricted", text


def test_generic_small_business_set_aside_still_classifies_as_generic():
    # The fix above must not swallow the real generic case, which is the one
    # a WOSB holder is genuinely entitled to bid.
    for text in (REAL_TOTAL_SB, "Total Small Business Set-Aside"):
        opp = make_opp(typeOfSetAsideDescription=text)
        assert classify_set_aside(opp) == {"small_business"}, text
        assert eligibility(opp, WOSB_HOLDER) == "eligible_set_aside", text


def test_the_default_certification_set_does_not_claim_wosb():
    # The business is male-owned as of September 2026, with an ownership
    # transition planned but not executed. WOSB is not self-certifiable:
    # FAR 19.15 requires certification in SBA's system at the time of
    # quote submission. Claiming it would be a false certification on a
    # federal submission, so it must not be in the defaults.
    assert "wosb" not in DEFAULT_HELD_CERTS
    assert "edwosb" not in DEFAULT_HELD_CERTS
    assert DEFAULT_HELD_CERTS == ("small_business",)


def test_wosb_set_asides_are_restricted_by_default():
    for text in (
        "SBA Certified Women-Owned Small Business (WOSB) Program Set-Aside (FAR 19.15)",
        "SBA Certified Women-Owned Small Business (WOSB) Program Sole Source (FAR 19.15)",
        "Women-Owned Small Business Set-Aside",
        "Economically Disadvantaged Women-Owned Small Business (EDWOSB) Set-Aside",
    ):
        opp = make_opp(typeOfSetAsideDescription=text)
        assert eligibility(opp) == "restricted", text


def test_generic_small_business_work_is_still_ours_by_default():
    # The point of removing WOSB is not to exclude everything: a small
    # business self-certifies its size in SAM.gov, so these remain open.
    for text in (REAL_TOTAL_SB, "Total Small Business Set-Aside"):
        assert eligibility(make_opp(typeOfSetAsideDescription=text)) == "eligible_set_aside", text
    assert eligibility(make_opp(typeOfSetAsideDescription=REAL_NO_SET_ASIDE)) == "full_open"


def test_a_wosb_set_aside_scores_nothing_by_default():
    # It must not merely be labelled restricted — it must stop earning the
    # set-aside points that put it at the top of the digest.
    wosb = make_opp(typeOfSetAsideDescription=REAL_WOSB_SOLE_SOURCE)
    points, reasons = score(wosb, 7, 60)
    assert "eligible" not in reasons


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


# ---------- services vs. supply buys ----------
# Regression: adding the industrial NAICS codes pulled in dozens of commodity
# purchases ("43 Filter Element Fluid", "47 Strainer Element Sedim", "43 Parts
# Kit Fluid Pressu"), which generated review packets for parts orders. PSCs are
# digit-prefixed for supplies and letter-prefixed for services.

def test_digit_prefixed_psc_is_a_supply_buy():
    assert is_supply_notice(make_opp(classificationCode="4330")) is True
    assert is_supply_notice(make_opp(classificationCode="4730")) is True


def test_letter_prefixed_psc_is_a_service():
    for psc in ("R499", "B505", "F108", "J039", "R710", "S208"):
        assert is_supply_notice(make_opp(classificationCode=psc)) is False


def test_missing_psc_is_not_treated_as_a_supply_buy():
    # No PSC at all shouldn't silently drop a notice — several real service
    # notices in the live run came back with classificationCode None.
    assert is_supply_notice(make_opp(classificationCode=None)) is False
    assert is_supply_notice(make_opp(classificationCode="")) is False


def test_keywords_exclude_terms_that_matched_parts_orders():
    # "repair"/"machinery"/"disposal" scored commodity buys as real work.
    for term in ("repair", "machinery", "disposal"):
        assert term not in KEYWORDS


def test_keywords_still_cover_the_environmental_service_lane():
    for term in ("remediation", "environmental", "abatement"):
        assert term in KEYWORDS


# ---------- profiles ----------
# The two businesses share a registration but not a scoring model: searching
# them together buried a WOSB financial-analysis RFP among salt-bath
# maintenance jobs.

def test_both_profiles_exist_with_required_keys():
    assert set(PROFILES) == {"p1821", "ares"}
    for spec in PROFILES.values():
        for key in ("label", "naics", "priority_psc", "keywords", "home_states", "draft_min_score"):
            assert key in spec, key


def test_profiles_cover_every_registered_code():
    covered = set()
    for spec in PROFILES.values():
        covered |= set(spec["naics"])
    # Every registered code is searched; the lanes may carry more than the
    # registration does (the construction trades, added 9/14 for the
    # in-house general contractor, are not yet on the SAM record).
    assert covered >= set(DEFAULT_NAICS)


def test_profiles_split_professional_from_industrial():
    p = set(PROFILES["p1821"]["naics"])
    a = set(PROFILES["ares"]["naics"])
    assert {"541211", "541213", "541219"} <= p
    assert {"562998", "811310", "238190"} <= a
    assert {"238160", "236220", "238120"} <= p, "construction trades ride the 1821 lane"
    # Environmental consulting serves both lanes; welding and structural
    # work moved into the 1821 lane when the Ares lane was switched off.
    assert p & a == {"541620", "811310", "238190"}


def test_ares_holds_a_higher_draft_bar_than_p1821():
    # Industrial codes return far more volume, mostly small maintenance jobs.
    assert PROFILES["ares"]["draft_min_score"] > PROFILES["p1821"]["draft_min_score"]


def test_score_uses_the_profile_keywords_not_the_module_default():
    ares = PROFILES["ares"]
    opp = make_opp(title="Hazardous Waste Disposal and Decontamination", classificationCode="F108")
    _, ares_reasons = score(opp, 7, 60, WOSB_HOLDER,
                            keywords=ares["keywords"],
                            priority_psc=ares["priority_psc"],
                            home_states=ares["home_states"])
    assert "keyword match" in ares_reasons
    assert "PSC match" in ares_reasons

    p1821 = PROFILES["p1821"]
    _, p_reasons = score(opp, 7, 60, WOSB_HOLDER,
                         keywords=p1821["keywords"],
                         priority_psc=p1821["priority_psc"],
                         home_states=p1821["home_states"])
    # F108 is an Ares PSC, so the professional-services profile must not
    # award it a PSC point.
    assert "PSC match" not in p_reasons


def test_score_reports_the_matched_home_state():
    _, reasons = score(make_opp(), 7, 60, WOSB_HOLDER, home_states={"TX"})
    assert "TX" in reasons


# ---------- the digest must not recommend unwinnable work ----------

def test_the_digest_does_not_list_a_blocked_notice_as_a_top_match(monkeypatch):
    # The failure this pins: the Coast Guard NAFI audit says "independent
    # Certified Public Accountant firm or licensed CPA" in its own
    # description. It was reported blocked inside its packet, and still
    # arrived as the first entry in the daily email three days running,
    # which reads as a recommendation.
    import find_opportunities as fo

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def sendmail(self, frm, to, text):
            # MIMEText base64-encodes a utf-8 body, so decode it rather
            # than asserting against transfer encoding.
            import email as email_mod
            sent["body"] = email_mod.message_from_string(text).get_payload(
                decode=True).decode("utf-8")

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    nafi = {"noticeId": "n1", "title": "NAFI Audit",
            "responseDeadLine": "2026-09-22T08:00:00-04:00",
            "uiLink": "https://sam.gov/nafi", "naicsCode": "541211"}
    good = {"noticeId": "n2", "title": "Bookkeeping Support Services",
            "responseDeadLine": "2026-09-30T12:00:00-04:00",
            "uiLink": "https://sam.gov/good", "naicsCode": "541219"}

    fo.send_email_digest(
        new_ones=[(6, "set-aside eligible", nafi)],
        to_addr="x@example.com", from_addr="y@example.com", app_password="pw",
        ranked=[(6, "set-aside eligible", nafi), (4, "9d to deadline", good)],
        blocked=[(nafi, "a licensed CPA or CPA firm")],
    )
    body = sent["body"]

    # It appears once, under its own heading, below everything else.
    assert "CANNOT BID — QUALIFICATION NOT HELD" in body
    assert "needs a licensed CPA or CPA firm" in body
    assert body.index("Bookkeeping Support Services") < body.index("CANNOT BID")
    # And never as new, or as a top match.
    assert "NEW SINCE YESTERDAY" not in body
    top = body[body.index("STILL OPEN"):body.index("CANNOT BID")]
    assert "NAFI" not in top


def test_an_unblocked_digest_has_no_cannot_bid_section(monkeypatch):
    import find_opportunities as fo
    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def sendmail(self, frm, to, text):
            # MIMEText base64-encodes a utf-8 body, so decode it rather
            # than asserting against transfer encoding.
            import email as email_mod
            sent["body"] = email_mod.message_from_string(text).get_payload(
                decode=True).decode("utf-8")

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    good = {"noticeId": "n2", "title": "Bookkeeping Support",
            "responseDeadLine": "2026-09-30T12:00:00-04:00", "uiLink": "u"}
    fo.send_email_digest([], "x@e.com", "y@e.com", "pw",
                         ranked=[(4, "why", good)], blocked=[])
    assert "CANNOT BID" not in sent["body"]
    assert "Bookkeeping Support" in sent["body"]
