"""The recurring-contract gate: what is kept, what is dropped, what is flagged."""
import os
import shutil
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import contract_fit as cf  # noqa: E402
import find_opportunities as fo  # noqa: E402

CRITERIA = cf.criteria_from_mapping()


def notice(**overrides):
    opp = {
        "noticeId": "N1",
        "title": "Services",
        "naicsCode": "561720",
        "classificationCode": "S201",
        "type": "Solicitation",
    }
    opp.update(overrides)
    return opp


def assess(title, description=None, **overrides):
    opp = notice(title=title, **overrides)
    return cf.assess_contract(opp, CRITERIA, description)


def test_one_off_jobs_are_excluded():
    for title in (
        "Roof repair at building 10",
        "Fence installation at the ranger station",
        "One-day crane lift for the HVAC unit",
        "Flooring replacement in building 4",
        "Lobby renovation",
    ):
        result = assess(title, naicsCode="238160", classificationCode="Z2JZ")
        assert result.disposition == "exclude", title


def test_a_one_off_stays_out_when_the_only_recurring_word_is_a_payment_term():
    # "billed monthly" on a roof repair is not a service contract.
    result = assess(
        "Roof repair",
        "The contractor shall complete the roof repair. Payment will be made monthly.",
        naicsCode="238160",
        classificationCode="Z2JZ",
    )
    assert result.disposition == "exclude"


def test_a_vehicle_in_a_construction_trade_is_kept():
    result = assess(
        "Roofing MATOC",
        "IDIQ. One base year and four (4) option years. Estimated value $1,200,000.",
        naicsCode="238160",
        classificationCode="Z2JZ",
    )
    assert result.disposition == "include"
    assert result.months == 60
    assert result.monthly_value == 20000


def test_janitorial_with_a_minor_repair_clause_is_not_a_one_off():
    result = assess(
        "Janitorial services, including minor repair",
        naicsCode="561720",
    )
    assert result.disposition == "needs_review"
    assert result.looks_recurring


def test_base_plus_options_and_a_stated_value_clear_the_floor():
    result = assess(
        "Custodial services",
        "One (1) base year and four (4) option years. The estimated value is $600,000.",
    )
    assert result.disposition == "include"
    assert result.months == 60
    assert result.monthly_value == 10000


def test_a_five_year_term_is_read_from_the_period_of_performance():
    result = assess(
        "Grounds maintenance",
        "Period of performance: 5-year ordering period. $2,000 per month.",
        naicsCode="561730",
        classificationCode="S208",
    )
    assert result.months == 60
    assert result.monthly_value == 2000
    assert result.disposition == "include"


def test_a_calendar_period_of_performance_is_read():
    result = assess(
        "Facilities support",
        "Period of performance from October 1, 2026 through September 30, 2031. "
        "Estimated value $600,000.",
        naicsCode="561210",
    )
    assert result.months == 60
    assert result.disposition == "include"


def test_structured_ceiling_and_dates_are_read_when_the_text_is_silent():
    result = assess(
        "Custodial services",
        awardCeiling="600000",
        popStartDate="2026-10-01",
        popEndDate="2031-09-30",
    )
    assert result.months == 60
    assert result.monthly_value == 10000
    assert result.disposition == "include"


def test_a_short_term_is_excluded_even_when_the_monthly_rate_is_high():
    result = assess(
        "Janitorial services",
        "Period of performance of 12 months. $5,000 per month.",
    )
    assert result.disposition == "exclude"


def test_a_low_monthly_rate_is_excluded_even_on_a_long_term():
    result = assess(
        "Janitorial services",
        "5-year period of performance. $500 per month.",
    )
    assert result.disposition == "exclude"


def test_a_total_that_cannot_clear_the_floor_is_excluded():
    result = assess("Janitorial services", "Estimated value $10,000.")
    assert result.disposition == "exclude"


def test_missing_value_or_duration_is_flagged_needs_review():
    no_numbers = assess("Janitorial services IDIQ")
    assert no_numbers.disposition == "needs_review"

    duration_only = assess(
        "Custodial services",
        "Base year and four option years. Value not stated.",
    )
    assert duration_only.disposition == "needs_review"
    assert duration_only.months == 60

    value_only = assess(
        "Grounds maintenance",
        "$2,500 per month. Ordering period to be determined.",
        naicsCode="561730",
    )
    assert value_only.disposition == "needs_review"
    assert value_only.monthly_value == 2500

    # A vague recurring code, with nothing in the title, is still kept.
    by_code = assess("Building services", naicsCode="561720", classificationCode="S201")
    assert by_code.disposition == "needs_review"


def test_a_professional_services_notice_with_no_term_is_not_kept():
    result = assess(
        "Tax and accounting support services",
        "Provide bookkeeping for the finance office.",
        naicsCode="541213",
        classificationCode="R710",
    )
    assert result.disposition == "unconfirmed"


def test_higher_monthly_value_and_longer_terms_rank_higher():
    long_rich = assess(
        "Janitorial services",
        "10-year period of performance. $10,000 per month.",
    )
    mid = assess(
        "Janitorial services",
        "5-year period of performance. $10,000 per month.",
    )
    short_thin = assess(
        "Janitorial services",
        "Base year and one option year. $1,000 per month.",
    )
    unknown = assess("Janitorial services IDIQ")
    rich_pts, rich_why = cf.score_contract_fit(long_rich, CRITERIA)
    mid_pts, mid_why = cf.score_contract_fit(mid, CRITERIA)
    thin_pts, _ = cf.score_contract_fit(short_thin, CRITERIA)
    unknown_pts, unknown_why = cf.score_contract_fit(unknown, CRITERIA)
    assert rich_pts > mid_pts > thin_pts > unknown_pts
    assert any("portfolio target" in reason for reason in rich_why)
    assert any("preferred range" in reason for reason in mid_why)
    assert "needs review" in " ".join(unknown_why)


def test_thresholds_are_configurable():
    strict = cf.criteria_from_mapping(CRITERIA, {"min_monthly_value": 5000, "min_months": 60})
    result = cf.assess_contract(
        notice(title="Janitorial services"),
        strict,
        "5-year period of performance. $2,000 per month.",
    )
    # 60 months clears the new term floor; $2,000 does not clear $5,000.
    assert result.disposition == "exclude"
    loosened = cf.criteria_from_mapping({"min_monthly_value": 500, "min_months": 12})
    assert loosened["preferred_months"] >= loosened["min_months"]
    # A preferred band written backwards is pulled up, not inverted.
    backwards = cf.criteria_from_mapping({
        "min_months": 36,
        "preferred_months": 12,
        "preferred_months_max": 6,
    })
    assert backwards["preferred_months"] == 36
    assert backwards["preferred_months_max"] == 36


def test_shipped_thresholds_match_the_strategy():
    criteria = cf.load_criteria("p1821")
    assert criteria["min_monthly_value"] == 1000
    assert criteria["min_months"] == 24
    assert criteria["preferred_months"] == 60
    assert criteria["preferred_months_max"] == 120
    assert criteria["target_monthly_portfolio"] == 10000


def test_saving_thresholds_creates_the_block_when_the_file_has_none(tmp_path):
    dest = tmp_path / "company.toml"
    dest.write_text("[shared]\nemail = \"a@b.com\"\n\n[p1821]\nlegal_name = \"Proverbs 1821 Consulting LLC\"\n")
    saved = cf.save_contract_criteria({"min_monthly_value": 1500}, path=str(dest))
    assert saved["min_monthly_value"] == 1500
    assert saved["min_months"] == 24
    text = dest.read_text()
    assert "[shared.contract_criteria]" in text
    assert "min_monthly_value = 1500" in text
    assert "target_monthly_portfolio = 10000" in text


def test_saving_thresholds_rewrites_the_numbers_and_keeps_the_comment(tmp_path):
    import company
    source = os.path.join(os.path.dirname(__file__), "..", "company.toml")
    dest = tmp_path / "company.toml"
    shutil.copy(source, dest)
    saved = cf.save_contract_criteria({"min_monthly_value": 2500}, path=str(dest))
    assert saved["min_monthly_value"] == 2500
    assert saved["min_months"] == 24
    text = dest.read_text()
    assert "min_monthly_value = 2500" in text
    assert "min_months = 24" in text
    # The real file is untouched.
    assert "min_monthly_value = 1000" in open(source).read()
    assert company.load_company("p1821", str(dest))["contract_criteria"]["min_monthly_value"] == 2500


def test_profile_keywords_boost_recurring_work_and_not_one_off_trades():
    words = set(fo.PROFILES["p1821"]["keywords"])
    for term in ("janitorial", "custodial", "landscaping", "facilities", "idiq", "bpa"):
        assert term in words
    for term in ("roof", "roofing", "repair", "renovation", "remodel", "demolition", "flooring"):
        assert term not in words
    assert "561720" in fo.PROFILES["p1821"]["naics"]
    assert "S201" in fo.PROFILES["p1821"]["priority_psc"]


def test_a_sample_day_ranks_the_long_contract_and_drops_the_one_offs(monkeypatch, tmp_path):
    """What a day of notices looks like after the gate.

    Before this gate the roof repair and the fence install scored on the
    same scale as everything else and could take a slot in the top two.
    After it, the top two are the ten-year janitorial contract and the
    five-year grounds contract. The fence is gone. The IDIQ with no
    stated value is still on the full list, marked needs review, and it
    does not outrank a contract that clears the floor.
    """
    deadline = (date.today() + timedelta(days=20)).isoformat() + "T17:00:00-06:00"

    def opp(notice_id, title, naics, psc):
        return {
            "noticeId": notice_id,
            "title": title,
            "naicsCode": naics,
            "classificationCode": psc,
            "type": "Solicitation",
            "typeOfSetAsideDescription": "Small Business Set Aside - Total",
            "responseDeadLine": deadline,
            "placeOfPerformance": {"city": {"name": "Houston"}, "state": {"code": "TX"}},
            "uiLink": f"https://sam.gov/{notice_id}",
            "description": f"https://api.sam.gov/noticedesc?noticeid={notice_id}",
        }

    opps = [
        opp("roof", "Single roof repair, building 12", "238160", "Z2JZ"),
        opp("fence", "Fence install at the housing area", "238990", "Z2JZ"),
        opp("crane", "One-day crane lift", "238990", "Z2JZ"),
        opp("jan", "Base janitorial services", "561720", "S201"),
        opp("grounds", "Grounds maintenance services", "561730", "S208"),
        opp("idiq", "Custodial services IDIQ", "561720", "S201"),
    ]
    texts = {
        "roof": "Replace the roof on building 12. One-time.",
        "fence": "Install approximately 400 feet of fence.",
        "crane": "Provide a crane and operator for one day.",
        "jan": "Janitorial services. Period of performance of 10 years. $12,000 per month.",
        "grounds": "Grounds maintenance. One base year and four option years. Estimated value $360,000.",
        "idiq": "Indefinite delivery janitorial services. Value and term to be set at the task order.",
    }
    monkeypatch.setattr(fo, "fetch", lambda *a, **k: opps)
    monkeypatch.setattr(fo, "fetch_description", lambda item, *a, **k: texts[item["noticeId"]])
    result = fo.run_search({
        "profile": "p1821",
        "naics_codes": ["561720"],
        "keywords": fo.PROFILES["p1821"]["keywords"],
        "priority_psc": fo.PROFILES["p1821"]["priority_psc"],
        "home_states": {"TX"},
        "posted_days": 45,
        "deadline_min": 7,
        "deadline_max": 60,
        "limit": 10,
        "max_retries": 1,
        "held_certs": ["small_business"],
        "include_restricted": False,
        "include_expired": False,
        "include_supplies": False,
        "db_path": str(tmp_path / "state.sqlite3"),
        "drafts_dir": str(tmp_path / "drafts"),
        "draft_min_score": 4,
        "generate_drafts": False,
        "send_email": False,
        "digest_top_n": 2,
    }, "fixture-key", log=lambda m: None)

    titles = [item[2]["title"] for item in result["ranked"]]
    assert titles[:2] == ["Base janitorial services", "Grounds maintenance services"]
    assert "Custodial services IDIQ" in titles
    assert result["ranked"][-1][2]["title"] == "Custodial services IDIQ"
    assert "needs review" in result["ranked"][-1][1]
    for gone in ("roof repair", "Fence install", "crane lift"):
        assert not any(gone.lower() in title.lower() for title in titles)
    assert result["excluded_one_off"] == 3
    shown = fo.format_ranked_stdout(result["ranked"], 2, result["descriptions"])
    assert "Base janitorial services" in shown
    assert "$12,000/mo" in shown
    assert "Fence" not in shown
