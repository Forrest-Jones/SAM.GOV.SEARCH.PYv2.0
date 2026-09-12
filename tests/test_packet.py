"""Tests for the fact bank and the packet conveyor belt.

The load-bearing property here is the one that protects the user legally:
a fact that was never entered must never appear as a plausible value. Most
of these tests exist to prove nothing is invented.
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import company as company_mod
import packet
import proposal

OPP = {
    "noticeId": "n1",
    "title": "Confined Space Assessment",
    "solicitationNumber": "12445826Q0091",
    "fullParentPathName": "AGRICULTURE, DEPARTMENT OF",
    "naicsCode": "541620",
    "classificationCode": "R428",
    "typeOfSetAsideDescription": "Small Business Set Aside - Total",
    "responseDeadLine": "2026-09-22T14:00:00-04:00",
    "uiLink": "https://sam.gov/x",
    "placeOfPerformance": {"city": {"name": "Beltsville"}, "state": {"code": "MD"}},
    "pointOfContact": [{"fullName": "Dana Whitfield", "email": "dana.whitfield@usda.gov"}],
}

FILLED = {
    "legal_name": "Proverbs 1821 LLC",
    "uei": "ABC123456789",
    "cage": "9XYZ1",
    "address": "1200 Main St, Houston, TX 77002",
    "phone": "713-555-0100",
    "email": "owner@example.com",
    "signatory_name": "F. Jones",
    "signatory_title": "Managing Member",
    "past_performance": [
        {"customer": "GSA Region 7", "contract": "47QX-24-C-0011", "value": "$180,000",
         "period": "2024-2025", "scope": "Facility safety assessment",
         "ref_name": "J. Smith", "ref_phone": "202-555-0101", "ref_email": "j@gsa.gov"},
    ],
    "rate_card": [
        {"category": "Senior Safety Assessor", "unit": "hr", "rate": "145.00"},
        {"category": "Field Technician", "unit": "hr", "rate": "85.00"},
    ],
}


# ---------- the fact bank ----------

def test_shipped_blank_rows_do_not_count_as_real_entries():
    # company.toml ships a placeholder rate-card row carrying unit = "hr".
    # Without identity checking that row reads as a real labor category and
    # an empty priced line reaches a packet.
    blank = {"rate_card": [{"category": "", "unit": "hr", "rate": ""}],
             "past_performance": [{"customer": "", "contract": "", "ref_email": ""}]}
    assert company_mod.filled_rows(blank, "rate_card") == []
    assert company_mod.filled_rows(blank, "past_performance") == []


def test_partial_rate_row_is_not_used():
    # A category with no rate cannot be priced, so it must not be offered.
    half = {"rate_card": [{"category": "Analyst", "unit": "hr", "rate": ""}]}
    assert company_mod.filled_rows(half, "rate_card") == []


def test_missing_required_fields_are_reported():
    required, _ = company_mod.missing_fields({"legal_name": "X"})
    assert "UEI (12 chars, from SAM.gov)" in required
    assert "legal business name" not in required


def test_a_complete_bank_reports_nothing_required_missing():
    required, _ = company_mod.missing_fields(FILLED)
    assert required == []


def test_unreadable_fact_bank_is_survivable():
    # No company.toml must not stop the pipeline — it just means every
    # offeror field shows up as a visible blank.
    loaded = company_mod.load_company("p1821", path="/nonexistent/company.toml")
    assert loaded.get("_error")
    required, _ = company_mod.missing_fields(loaded)
    assert len(required) == len(company_mod.REQUIRED_FIELDS)


def test_the_shipped_company_toml_parses():
    loaded = company_mod.load_company("p1821")
    assert not loaded.get("_error"), "company.toml in the repo must stay parseable"
    assert "email" in loaded, "the [shared] block should merge into every profile"


# ---------- the skip rules (the brake on the conveyor belt) ----------

def test_skip_psc_blocks_work_we_do_not_perform():
    cfg = {"skip_psc": ["Z2AZ"]}
    assert company_mod.skip_reason(cfg, {"classificationCode": "Z2AZ"})
    assert company_mod.skip_reason(cfg, {"classificationCode": "z2az"}), "case must not matter"
    assert company_mod.skip_reason(cfg, {"classificationCode": "R428"}) is None


def test_skip_keywords_block_by_title():
    cfg = {"skip_keywords": ["foundation repair"]}
    assert company_mod.skip_reason(cfg, {"title": "Foundation Repair at Building 7"})
    assert company_mod.skip_reason(cfg, {"title": "Confined Space Assessment"}) is None


def test_no_skip_rules_blocks_nothing():
    assert company_mod.skip_reason({}, OPP) is None


# ---------- nothing invented ----------

def test_empty_fact_bank_leaves_identity_blank_not_guessed():
    draft = proposal.build_proposal_markdown(OPP, "", {}, 4, "")
    assert "[[FILL: UEI from your SAM.gov registration]]" in draft
    assert "[[FILL: CAGE code]]" in draft


def test_filled_fact_bank_puts_real_identity_in_the_draft():
    draft = proposal.build_proposal_markdown(OPP, "", FILLED, 4, "")
    assert "ABC123456789" in draft
    assert "[[FILL: CAGE code]]" not in draft


def test_past_performance_comes_from_the_bank_and_relevance_stays_blank():
    draft = proposal.build_proposal_markdown(OPP, "", FILLED, 4, "")
    assert "47QX-24-C-0011" in draft
    # One real reference on file, three rows asked for: the other two stay
    # visibly empty rather than being padded out.
    assert draft.count("[[FILL: customer]]") == 2
    # Relevance is per-solicitation, so it is never carried over as answered.
    assert "[[FILL: why it is relevant to THIS requirement]]" in draft


def test_price_is_never_pre_filled_even_with_a_rate_card():
    # A rate is a standing fact; a price is a binding offer. Hours and the
    # total must always be the human's.
    draft = proposal.build_proposal_markdown(OPP, "", FILLED, 4, "")
    assert "145.00" in draft
    assert "[[FILL: hours]]" in draft
    assert "[[FILL: $ total offered price]]" in draft


# ---------- the packet ----------

def test_price_sheet_has_rates_blank_hours_and_a_live_total(tmp_path):
    path = packet.write_price_sheet(OPP, FILLED, str(tmp_path / "p.csv"))
    rows = list(csv.reader(open(path)))
    header = next(i for i, r in enumerate(rows) if r and r[0] == "Labor category")
    first = rows[header + 1]
    assert first[0] == "Senior Safety Assessor"
    assert first[2] == "145.00"
    assert first[3] == "", "hours must be empty"
    assert first[4].startswith("="), "extended column should total itself"
    assert any(r and r[0] == "TOTAL" and r[4].startswith("=SUM") for r in rows)


def test_price_sheet_without_a_rate_card_still_produces_a_usable_skeleton(tmp_path):
    path = packet.write_price_sheet(OPP, {}, str(tmp_path / "p.csv"))
    text = open(path).read()
    assert "TOTAL" in text
    assert "company.toml" in text, "should say how to make it fill itself next time"


def test_quote_email_is_addressed_from_the_notice(tmp_path):
    text = packet.build_quote_email(OPP, FILLED)
    assert "dana.whitfield@usda.gov" in text
    assert "12445826Q0091" in text
    assert "Dana Whitfield" in text
    assert "Proverbs 1821 LLC" in text
    # The submission method is the single most common way a compliant quote
    # gets thrown out, so the warning has to be in the file itself.
    assert "Do not assume email" in text


def test_quote_email_blanks_the_officer_when_the_notice_has_none():
    text = packet.build_quote_email({"noticeId": "x"}, FILLED)
    assert "[[FILL: contracting officer email" in text


def test_packet_contains_every_piece_and_counts_its_own_blanks(tmp_path):
    out, blanks = packet.build_packet(OPP, "Scope: do the work.", FILLED, str(tmp_path), 4, "why")
    for name in ("00-START-HERE.md", "01-proposal.md", "02-price-sheet.csv", "03-quote-email.txt"):
        assert os.path.exists(os.path.join(out, name)), name
    assert os.path.exists(os.path.join(out, "attachments", "MANIFEST.txt"))
    assert blanks > 0
    start = open(os.path.join(out, "00-START-HERE.md")).read()
    assert f"**{blanks} blanks**" in start, "the checklist must state the real count"
    assert "2026-09-22" in start


def test_rebuilding_never_clobbers_a_packet_in_progress(tmp_path):
    out, _ = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    draft_path = os.path.join(out, "01-proposal.md")
    with open(draft_path, "w") as f:
        f.write("MY PRICED AND EDITED DRAFT")
    again, blanks = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert again == out
    assert blanks is None, "a reused packet reports no blank count"
    assert open(draft_path).read() == "MY PRICED AND EDITED DRAFT"


def test_manifest_records_attachments_it_could_not_download(tmp_path):
    # The download host is not reachable from every environment, and a
    # blocked file must never read as "this notice had no attachments".
    opp = dict(OPP, resourceLinks=["https://api.sam.gov/x/PWS.pdf"])

    class Boom:
        def get(self, url, **kw):
            raise OSError("blocked by egress policy")

    got, failed = packet.fetch_attachments(opp, str(tmp_path / "att"), session=Boom())
    assert got == []
    assert len(failed) == 1
    text = open(tmp_path / "att" / "MANIFEST.txt").read()
    assert "NOT downloaded" in text
    assert "PWS.pdf" in text


def test_manifest_says_so_when_the_notice_lists_nothing(tmp_path):
    got, failed = packet.fetch_attachments(OPP, str(tmp_path / "att"), session=None)
    assert (got, failed) == ([], [])
    text = open(tmp_path / "att" / "MANIFEST.txt").read()
    assert "no attachments" in text
    assert "Open the listing anyway" in text


def test_oversized_attachment_is_refused_not_written(tmp_path):
    opp = dict(OPP, resourceLinks=["https://api.sam.gov/x/huge.pdf"])

    class Huge:
        def get(self, url, **kw):
            class R:
                content = b"x" * (packet.MAX_ATTACHMENT_BYTES + 1)

                def raise_for_status(self):
                    pass
            return R()

    got, failed = packet.fetch_attachments(opp, str(tmp_path / "att"), session=Huge())
    assert got == []
    assert "15MB" in failed[0][1]
    assert not os.path.exists(tmp_path / "att" / "huge.pdf")


def test_batch_index_sorts_by_soonest_deadline(tmp_path):
    soon = dict(OPP, noticeId="a", title="Closes soon", responseDeadLine="2026-09-14T00:00:00-04:00")
    later = dict(OPP, noticeId="b", title="Closes later", responseDeadLine="2026-10-30T00:00:00-04:00")
    built = [("/x/b-later", later, 20), ("/x/a-soon", soon, 12)]
    path = packet.write_batch_index(built, [(OPP, "PSC in skip_psc")], str(tmp_path), "Test")
    text = open(path).read()
    assert text.index("Closes soon") < text.index("Closes later")
    assert "Not built" in text and "skip_psc" in text
