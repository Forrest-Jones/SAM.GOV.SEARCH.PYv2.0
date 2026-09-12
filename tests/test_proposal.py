import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proposal import (  # noqa: E402
    build_proposal_markdown,
    detect_pws_sections,
    extract_deliverable_lines,
    profile_value,
    write_proposal,
)

OPP = {
    "noticeId": "N1",
    "solicitationNumber": "FA3016-26-R-0042",
    "title": "VITA Tax Center Support Services",
    "naicsCode": "541213",
    "classificationCode": "R710",
    "typeOfSetAsideDescription": "Woman-Owned Small Business Set-Aside",
    "responseDeadLine": "2026-10-05T17:00:00-05:00",
    "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE AIR FORCE",
    "placeOfPerformance": {"city": {"name": "San Antonio"}, "state": {"code": "TX"}},
    "uiLink": "https://sam.gov/opp/N1",
    "pointOfContact": [{"email": "co@us.af.mil"}],
}

PWS = """
SCOPE: Provide tax center staffing.
BACKGROUND: Operated since 2009.
TASKS: The contractor shall:
 (a) Provide IRS-certified preparers.
 (b) Quality review every return.
DELIVERABLES: Weekly reports.
QUALITY CONTROL: Maintain a QC plan.
"""


def test_detect_sections_follows_solicitation_order():
    found = detect_pws_sections(PWS)
    assert found.index("scope") < found.index("background") < found.index("tasks")
    assert "quality control" in found


def test_detect_sections_empty_for_no_text():
    assert detect_pws_sections(None) == []
    assert detect_pws_sections("") == []


def test_extract_deliverables_pulls_government_wording():
    items = extract_deliverable_lines(PWS)
    assert "Provide IRS-certified preparers." in items
    assert "Quality review every return." in items


def test_extract_deliverables_returns_empty_rather_than_inventing():
    assert extract_deliverable_lines("One long prose paragraph with no list at all.") == []
    assert extract_deliverable_lines(None) == []


def test_profile_value_uses_real_value_when_present():
    assert profile_value({"uei": "ABC123"}, "uei", "UEI") == "ABC123"


def test_profile_value_marks_a_blank_when_absent():
    out = profile_value({"uei": "   "}, "uei", "UEI")
    assert out.startswith("[[FILL:") and "UEI" in out


def test_proposal_includes_real_notice_and_profile_data():
    md = build_proposal_markdown(OPP, PWS, {"legal_name": "Proverbs 1821 Consulting LLC"}, score=8)
    assert "FA3016-26-R-0042" in md
    assert "Proverbs 1821 Consulting LLC" in md
    assert "co@us.af.mil" in md
    assert "541213" in md
    assert "San Antonio, TX" in md


def test_proposal_never_invents_price_or_past_performance():
    md = build_proposal_markdown(OPP, PWS, {"legal_name": "X"})
    past_perf = md.split("## 6. Past performance")[1].split("## 7.")[0]
    price = md.split("## 7. Price proposal")[1].split("## 8.")[0]
    # Every data cell in these two sections must be an explicit blank —
    # a fabricated reference or rate on a federal submission is a false
    # statement, so the generator must leave them empty.
    assert "[[FILL:" in past_perf and "[[FILL:" in price
    assert "$" not in price.replace("[[FILL: $ value]]", "").replace("$rate", "").replace("$total", "").replace("$ total offered price", "")


def test_proposal_states_it_is_not_submitted():
    md = build_proposal_markdown(OPP, PWS, {})
    assert "NOT SUBMITTED" in md
    assert "cannot" in md.lower()


def test_proposal_flags_the_set_aside_for_verification():
    md = build_proposal_markdown(OPP, PWS, {})
    assert "Woman-Owned Small Business Set-Aside" in md
    assert "verify it yourself" in md


def test_proposal_falls_back_to_generic_outline_without_text():
    md = build_proposal_markdown(OPP, None, {})
    assert "Understanding of the requirement" in md


def test_write_proposal_does_not_clobber_an_edited_draft(tmp_path):
    first = write_proposal(OPP, PWS, {}, str(tmp_path))
    with open(first, "w") as f:
        f.write("MY EDITS")
    second = write_proposal(OPP, PWS, {}, str(tmp_path))
    assert first == second
    with open(second) as f:
        assert f.read() == "MY EDITS"
