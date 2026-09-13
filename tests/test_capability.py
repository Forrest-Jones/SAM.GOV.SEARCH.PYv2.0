"""Tests for Sources Sought / RFI capability statement responses.

A market research notice is not a solicitation. The load-bearing property
is that a response to one never contains or implies a price, and never
claims a certification or an experience record the business does not have.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import capability
import company as company_mod
import packet

SSN = {
    "noticeId": "ssn1",
    "title": "HQMC Financial and Administrative Support Services",
    "solicitationNumber": "M95494-26-SSN-ADCFAS",
    "type": "Sources Sought",
    "fullParentPathName": "USMC MARINE CORPS INSTALLATIONS COMMAND",
    "naicsCode": "541219",
    "classificationCode": "R499",
    "responseDeadLine": "2026-09-30T17:00:00-04:00",
    "uiLink": "https://sam.gov/x",
    "pointOfContact": [{"fullName": "David Godfrey", "email": "david.godfrey@usmc.mil"}],
}

# Close to the real notice's wording, including its lettered list.
NOTICE_TEXT = """
II. BACKGROUND: MCICOM is conducting baseline market research.
a. Does your company believe there is one or more specific NAICS and PSC code
combinations that would be better suited to this requirement than the anticipated code?
b. Does your company have current experience providing financial and administrative
support services of the type and scope described in the draft PWS?
c. Would your company propose as a prime contractor or as a subcontractor?
d. Does your company hold any contract vehicles under which these services could be ordered?
"""

BANK = {
    "legal_name": "Proverbs 1821 Consulting LLC",
    "uei": "GD83PAK36818", "cage": "22ND2",
    "address": "12103 Hawthorne Dr, Montgomery, TX 77356",
    "phone": "(832) 562-1355", "email": "owner@example.com",
    "signatory_name": "Forrest Andrew Jones", "signatory_title": "Owner / Managing Member",
    "credentials": [{"kind": "ea", "holder": "Randy White"}],
}


# ---------- the notice's own questions ----------

def test_the_notices_questions_are_extracted_in_its_own_order():
    questions = capability.extract_questions(NOTICE_TEXT)
    assert len(questions) == 4
    assert questions[0].startswith("Does your company believe")
    assert questions[2].startswith("Would your company propose")


def test_lettering_is_stripped_but_the_question_is_intact():
    questions = capability.extract_questions(NOTICE_TEXT)
    assert not questions[0].startswith("a.")
    assert questions[0].endswith("?")


def test_duplicate_questions_are_not_repeated():
    doubled = NOTICE_TEXT + NOTICE_TEXT
    assert len(capability.extract_questions(doubled)) == 4


def test_no_questions_is_reported_honestly_not_invented():
    # A response answering questions the government never asked reads as
    # boilerplate, which is what these notices screen out.
    assert capability.extract_questions("Plain prose with no questions at all.") == []
    assert capability.extract_questions("") == []
    assert capability.extract_questions(None) == []


def test_a_document_with_no_detectable_questions_says_to_go_look():
    text = capability.build_capability_markdown(SSN, "No questions here.", BANK)
    assert "inside an attachment" in text
    assert "paste each question from the notice" in text


# ---------- no price, ever ----------

def test_a_capability_statement_contains_no_price_and_says_so():
    text = capability.build_capability_markdown(SSN, NOTICE_TEXT, BANK, "Sources Sought")
    assert "not a bid" in text.lower()
    assert "no price is offered" in text.lower()
    for priced in ("$rate", "Extended", "hours", "Labor category"):
        assert priced not in text, priced


def test_the_response_folder_has_no_price_sheet(tmp_path):
    out, blanks, status = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    names = set(os.listdir(out))
    assert "01-capability-statement.md" in names
    assert "02-response-email.txt" in names
    assert not any(n.endswith(".csv") for n in names), "market research has no price sheet"


def test_the_checklist_has_four_steps_and_no_pricing_step(tmp_path):
    out, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "Your four steps" in text
    assert "Price it" not in text
    assert "No price belongs in this response" in text
    # And it must not tell the user to sign reps and certs for a non-offer.
    assert "certifies your reps & certs" not in text


def test_the_response_email_does_not_offer_a_quote(tmp_path):
    out, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    text = open(os.path.join(out, "02-response-email.txt")).read()
    assert "capability statement" in text.lower()
    assert "attached quote" not in text.lower()
    assert "contains no price" in text.lower()


# ---------- nothing invented ----------

def test_real_identity_is_used_and_missing_facts_stay_blank():
    text = capability.build_capability_markdown(SSN, NOTICE_TEXT, BANK)
    assert "GD83PAK36818" in text
    assert "Proverbs 1821 Consulting LLC" in text
    # No past performance on file, so all three rows stay visibly empty.
    assert text.count("[[FILL: customer]]") == 3


def test_held_credentials_are_listed_and_nothing_else_is():
    text = capability.build_capability_markdown(SSN, NOTICE_TEXT, BANK)
    assert "Enrolled Agent" in text
    assert "Randy White" in text
    assert "Certified Public Accountant (state-licensed)" not in text


def test_socioeconomic_status_is_left_blank_not_assumed():
    # The business is not WOSB certified; the field must never be
    # pre-filled with a status it does not hold.
    text = capability.build_capability_markdown(SSN, NOTICE_TEXT, BANK)
    assert "state only what is actually certified" in text
    assert "WOSB" not in text


def test_small_business_size_is_stated_as_self_certified():
    text = capability.build_capability_markdown(SSN, NOTICE_TEXT, BANK)
    assert "self-certified in SAM.gov" in text
    assert "541219" in text


# ---------- routing ----------

def test_sources_sought_is_routed_to_capability_not_dropped(tmp_path):
    import find_opportunities as fo
    ranked = [(9, "why", dict(SSN, noticeId="s1"))]
    profile = {"label": "Test", "draft_min_score": 3}
    built, skipped = fo.build_batch(
        1, "p1821", profile, ranked, {"s1": NOTICE_TEXT}, "key",
        str(tmp_path), log=lambda m: None)
    assert skipped == [], "a market research notice in our lane is not a skip"
    assert len(built) == 1
    assert os.path.exists(os.path.join(built[0][0], "01-capability-statement.md"))


def test_award_notices_are_still_dropped(tmp_path):
    import find_opportunities as fo
    ranked = [(9, "why", dict(SSN, noticeId="a1", type="Award Notice"))]
    profile = {"label": "Test", "draft_min_score": 3}
    built, skipped = fo.build_batch(
        1, "p1821", profile, ranked, {"a1": NOTICE_TEXT}, "key",
        str(tmp_path), log=lambda m: None)
    assert built == []
    assert len(skipped) == 1


def test_rebuilding_a_capability_response_keeps_your_answers(tmp_path):
    out, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    answered = os.path.join(out, "01-capability-statement.md")
    with open(answered, "w") as f:
        f.write("MY ANSWERS")
    again, _, status = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    assert (again, status) == (out, "kept")
    assert open(answered).read() == "MY ANSWERS"


# ---------- requirements this notice asks for explicitly ----------

REAL_NOTICE = """
1) Identify/define your company profile.
h. Status of the company's accounting system including the last adequacy/acceptability review date.
2) Describe your interest in this effort as a potential Prime Contractor.
3) Describe your company's recent relevant experience. Responses shall:
a. Detail your company's specific technical skills that ensure the capability to meet the objectives in Enclosure 1 DRAFT PWS.
b. Describe similar work to include: i. the relevant contract number and involvement as a prime or subcontractor, and
ii. The percentage and dollar amount of the work your company performed.
4) Provide feedback in the form of responses to the following questions:
a. Does your company believe there is one or more specific NAICS and PSC code combinations that would be better suited? If so, which one(s) and why?
b. Does your company see any risk areas or any concerns with this overall effort? If so, what are they and how would you mitigate them?
"""


def test_a_conditional_follow_up_stays_with_its_question():
    # "If so, which one(s) and why?" is a conditional on the question
    # before it, not a question of its own.
    questions = capability.extract_questions(REAL_NOTICE)
    assert len(questions) == 2
    assert "If so, which one(s) and why?" in questions[0]
    assert "how would you mitigate them?" in questions[1]


def test_a_heading_ending_before_a_question_is_not_itself_a_question():
    # "Provide feedback in the form of responses to the following
    # questions:" was being captured as question one, which pushed the
    # first real question out of the list.
    questions = capability.extract_questions(REAL_NOTICE)
    assert not any(q.lower().startswith("provide feedback") for q in questions)


def test_a_definition_preceding_a_question_is_not_captured():
    text = ("Market prices means current prices established in the course of "
            "ordinary trade. Does your company sell these services commercially?")
    questions = capability.extract_questions(text)
    assert len(questions) == 1
    assert questions[0].startswith("Does your company")


def test_accounting_system_status_is_asked_for():
    # Asked on effectively every DoD services notice, and a small firm
    # with no DCAA review has to answer it honestly rather than skip it.
    text = capability.build_capability_markdown(SSN, REAL_NOTICE, BANK)
    assert "Accounting system" in text
    assert "adequacy review has ever been performed" in text


def test_prime_or_subcontractor_intent_has_its_own_section():
    text = capability.build_capability_markdown(SSN, REAL_NOTICE, BANK)
    assert "## Interest as a prime contractor" in text


def test_experience_asks_for_role_and_dollar_share():
    # The notice wants what THIS company performed, not what its team did.
    text = capability.build_capability_markdown(SSN, REAL_NOTICE, BANK)
    assert "Prime or sub" in text
    assert "percentage and dollar amount YOUR company performed" in text


def test_technical_skills_are_tied_to_the_pws():
    text = capability.build_capability_markdown(SSN, REAL_NOTICE, BANK)
    assert "Technical skills against the draft PWS" in text
    assert "cite" in text and "PWS paragraph" in text


# ---------- one folder, one response kind ----------

def test_switching_a_folder_to_capability_removes_the_bid_files(tmp_path):
    # Live case: IS3 was packeted as a bid before notice types were read.
    # Once re-routed it held both — a capability statement beside a price
    # sheet and a signed-quote email for a notice that cannot be quoted.
    out, _, _ = packet.build_packet(
        dict(SSN, type="Solicitation"), "Scope.", BANK, str(tmp_path), 4, "")
    assert os.path.exists(os.path.join(out, "02-price-sheet.csv"))

    again, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    assert again == out
    names = set(os.listdir(out))
    assert "01-capability-statement.md" in names
    for priced in ("01-proposal.md", "02-price-sheet.csv", "03-quote-email.txt"):
        assert priced not in names, f"{priced} must not survive the switch"


def test_a_kept_capability_folder_still_loses_stale_bid_files(tmp_path):
    # The dangerous variant: the fact bank has not changed, so the builder
    # returns "kept" — which must not mean "kept holding a price sheet".
    out, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    stale = os.path.join(out, "02-price-sheet.csv")
    with open(stale, "w") as f:
        f.write("stale price sheet")

    _, _, status = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    assert status == "kept"
    assert not os.path.exists(stale)


def test_switching_back_to_a_bid_removes_the_capability_files(tmp_path):
    out, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    again, _, _ = packet.build_packet(
        dict(SSN, type="Solicitation"), "Scope.", BANK, str(tmp_path), 4, "")
    assert again == out
    names = set(os.listdir(out))
    assert "02-price-sheet.csv" in names
    assert "01-capability-statement.md" not in names
    assert "02-response-email.txt" not in names
