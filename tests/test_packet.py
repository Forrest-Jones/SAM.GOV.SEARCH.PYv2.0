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
    "naicsCode": "541219",
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
    out, blanks, status = packet.build_packet(OPP, "Scope: do the work.", FILLED, str(tmp_path), 4, "why")
    assert status == "new"
    for name in ("00-START-HERE.md", "01-proposal.md", "02-price-sheet.csv", "03-quote-email.txt"):
        assert os.path.exists(os.path.join(out, name)), name
    assert os.path.exists(os.path.join(out, "attachments", "MANIFEST.txt"))
    assert blanks > 0
    start = open(os.path.join(out, "00-START-HERE.md")).read()
    assert f"**{blanks} blanks**" in start, "the checklist must state the real count"
    assert "2026-09-22" in start


def test_rebuilding_never_clobbers_your_edits(tmp_path):
    out, _, _ = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    draft_path = os.path.join(out, "01-proposal.md")
    with open(draft_path, "w") as f:
        f.write("MY PRICED AND EDITED DRAFT")
    # Same facts, so there is nothing to refresh anyway.
    again, _, status = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert (again, status) == (out, "kept")
    assert open(draft_path).read() == "MY PRICED AND EDITED DRAFT"


def test_unchanged_facts_leave_the_packet_alone(tmp_path):
    out, blanks, _ = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    before = open(os.path.join(out, "01-proposal.md")).read()
    _, blanks_again, status = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert status == "kept"
    assert blanks_again == blanks
    assert open(os.path.join(out, "01-proposal.md")).read() == before


def test_filling_the_fact_bank_refreshes_an_untouched_packet(tmp_path):
    # The trap this exists to close: a packet built while company.toml was
    # empty must not stay empty forever once the facts are entered.
    out, blanks_empty, _ = packet.build_packet(OPP, "", {}, str(tmp_path), 4, "")
    assert "[[FILL: UEI" in open(os.path.join(out, "01-proposal.md")).read()

    same, blanks_filled, status = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert same == out
    assert status == "refreshed"
    assert blanks_filled < blanks_empty
    draft = open(os.path.join(out, "01-proposal.md")).read()
    assert "ABC123456789" in draft, "the newly entered UEI should now be in the draft"


def test_a_refresh_keeps_the_one_file_you_edited(tmp_path):
    out, _, _ = packet.build_packet(OPP, "", {}, str(tmp_path), 4, "")
    priced = os.path.join(out, "02-price-sheet.csv")
    with open(priced, "w") as f:
        f.write("MY PRICING WORK")

    _, _, status = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert status == "partial"
    assert open(priced).read() == "MY PRICING WORK", "priced sheet must survive"
    # ...while the files nobody touched do pick up the new facts.
    assert "ABC123456789" in open(os.path.join(out, "01-proposal.md")).read()


def test_an_edited_file_stays_protected_across_later_refreshes(tmp_path):
    out, _, _ = packet.build_packet(OPP, "", {}, str(tmp_path), 4, "")
    priced = os.path.join(out, "02-price-sheet.csv")
    with open(priced, "w") as f:
        f.write("MY PRICING WORK")
    packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")

    more = dict(FILLED, phone="713-555-9999")
    _, _, status = packet.build_packet(OPP, "", more, str(tmp_path), 4, "")
    assert status == "partial"
    assert open(priced).read() == "MY PRICING WORK"


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
    built = [("/x/b-later", later, 20, "new"), ("/x/a-soon", soon, 12, "new")]
    path = packet.write_batch_index(built, [(OPP, "PSC in skip_psc")], str(tmp_path), "Test")
    text = open(path).read()
    assert text.index("Closes soon") < text.index("Closes later")
    assert "Not built" in text and "skip_psc" in text


# ---------- attachment naming (every SAM.gov URL ends in "download") ----------

class FakeResp:
    def __init__(self, content=b"pdf", headers=None):
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        pass


class FakeSession:
    """Serves every URL, the way SAM.gov does: the path ends in /download
    and the real filename arrives in Content-Disposition."""

    def __init__(self, headers_per_url=None):
        self.headers_per_url = headers_per_url or {}

    def get(self, url, **kw):
        return FakeResp(headers=self.headers_per_url.get(url, {}))


def test_every_attachment_gets_its_own_file(tmp_path):
    # The live bug: thirteen documents on one notice, every URL ending in
    # "/download", all written to the same name — twelve files lost.
    urls = [f"https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{i:032x}/download"
            for i in range(13)]
    opp = dict(OPP, resourceLinks=urls)
    got, failed = packet.fetch_attachments(opp, str(tmp_path / "att"), session=FakeSession())
    assert failed == []
    names = [name for _, name in got]
    assert len(names) == 13
    assert len(set(names)) == 13, "each attachment must land in its own file"
    on_disk = {f for f in os.listdir(tmp_path / "att") if f != "MANIFEST.txt"}
    assert len(on_disk) == 13


def test_content_disposition_filename_is_preferred(tmp_path):
    url = "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/abc/download"
    opp = dict(OPP, resourceLinks=[url])
    session = FakeSession({url: {"content-disposition": 'attachment; filename="PWS Statement.pdf"'}})
    got, _ = packet.fetch_attachments(opp, str(tmp_path / "att"), session=session)
    assert got[0][1] == "PWS-Statement.pdf"


def test_content_type_supplies_an_extension_when_there_is_no_filename(tmp_path):
    url = "https://sam.gov/x/download"
    opp = dict(OPP, resourceLinks=[url])
    session = FakeSession({url: {"content-type": "application/pdf"}})
    got, _ = packet.fetch_attachments(opp, str(tmp_path / "att"), session=session)
    assert got[0][1].endswith(".pdf")


def test_duplicate_filenames_on_one_notice_do_not_collide(tmp_path):
    urls = ["https://sam.gov/a/download", "https://sam.gov/b/download"]
    opp = dict(OPP, resourceLinks=urls)
    headers = {u: {"content-disposition": 'attachment; filename="SOW.pdf"'} for u in urls}
    got, _ = packet.fetch_attachments(opp, str(tmp_path / "att"), session=FakeSession(headers))
    names = [n for _, n in got]
    assert names == ["SOW.pdf", "SOW-2.pdf"]


def test_a_kept_packet_still_recovers_missing_attachments(tmp_path):
    # The drafts may be current or hand-edited, but the government's own
    # documents are neither — missing ones are pure loss, so a rebuild
    # fetches them even when nothing else changes.
    url = "https://sam.gov/x/download"
    opp = dict(OPP, resourceLinks=[url])
    session = FakeSession({url: {"content-disposition": 'attachment; filename="SOW.pdf"'}})
    out, _, _ = packet.build_packet(opp, "", FILLED, str(tmp_path), 4, "", session=session)
    sow = os.path.join(out, "attachments", "SOW.pdf")
    assert os.path.exists(sow)

    os.remove(sow)
    _, _, status = packet.build_packet(opp, "", FILLED, str(tmp_path), 4, "", session=session)
    assert status == "kept"
    assert os.path.exists(sow), "a kept packet must re-fetch attachments it has lost"


def test_the_price_sheet_is_not_gitignored():
    # *.csv in .gitignore silently kept every price sheet out of the repo,
    # so the centrepiece of each packet never reached GitHub.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rules = open(os.path.join(root, ".gitignore")).read()
    assert "!packets/**/*.csv" in rules


# ---------- a generated file that is simply absent ----------

def test_a_missing_generated_file_is_rewritten(tmp_path):
    # The live failure: *.csv in .gitignore meant the price sheet was never
    # committed, so a fresh CI checkout had a packet with no price sheet at
    # all — while its recorded hashes claimed everything was accounted for.
    out, _, _ = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    priced = os.path.join(out, "02-price-sheet.csv")
    os.remove(priced)

    _, _, status = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert status == "repaired"
    assert os.path.exists(priced), "a missing price sheet must come back"
    assert "Senior Safety Assessor" in open(priced).read()


def test_repairing_a_missing_file_leaves_your_edits_alone(tmp_path):
    out, _, _ = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    draft = os.path.join(out, "01-proposal.md")
    with open(draft, "w") as f:
        f.write("MY EDITED DRAFT")
    os.remove(os.path.join(out, "02-price-sheet.csv"))

    _, _, status = packet.build_packet(OPP, "", FILLED, str(tmp_path), 4, "")
    assert status == "repaired"
    assert open(draft).read() == "MY EDITED DRAFT"


# ---------- pruning closed packets ----------

def test_closed_packets_give_up_their_attachments(tmp_path):
    from datetime import date, timedelta
    url = "https://sam.gov/x/download"
    opp = dict(OPP, resourceLinks=[url])
    session = FakeSession({url: {"content-disposition": 'attachment; filename="PWS.pdf"'}})
    out, _, _ = packet.build_packet(opp, "", FILLED, str(tmp_path), 4, "", session=session)
    pws = os.path.join(out, "attachments", "PWS.pdf")
    assert os.path.exists(pws)

    # OPP closes 2026-09-22; well past it plus the grace period.
    pruned, freed = packet.prune_closed_packets(
        str(tmp_path), grace_days=7, today=date(2026, 10, 15))
    assert len(pruned) == 1
    assert not os.path.exists(pws)
    # The paperwork and the record of what was there both survive.
    assert os.path.exists(os.path.join(out, "01-proposal.md"))
    assert os.path.exists(os.path.join(out, "attachments", "MANIFEST.txt"))
    assert "MANIFEST.txt still lists every URL" in open(
        os.path.join(out, "attachments", "PRUNED.txt")).read()


def test_open_packets_keep_their_attachments(tmp_path):
    from datetime import date
    url = "https://sam.gov/x/download"
    opp = dict(OPP, resourceLinks=[url])
    session = FakeSession({url: {"content-disposition": 'attachment; filename="PWS.pdf"'}})
    out, _, _ = packet.build_packet(opp, "", FILLED, str(tmp_path), 4, "", session=session)

    pruned, freed = packet.prune_closed_packets(
        str(tmp_path), grace_days=7, today=date(2026, 9, 20))
    assert pruned == []
    assert freed == 0
    assert os.path.exists(os.path.join(out, "attachments", "PWS.pdf"))


def test_a_packet_inside_the_grace_period_is_left_alone(tmp_path):
    from datetime import date
    url = "https://sam.gov/x/download"
    opp = dict(OPP, resourceLinks=[url])
    session = FakeSession({url: {"content-disposition": 'attachment; filename="PWS.pdf"'}})
    out, _, _ = packet.build_packet(opp, "", FILLED, str(tmp_path), 4, "", session=session)

    # Three days past the 2026-09-22 deadline: a debrief or a late
    # modification is still plausible, so nothing is thrown away yet.
    pruned, _ = packet.prune_closed_packets(
        str(tmp_path), grace_days=7, today=date(2026, 9, 25))
    assert pruned == []
    assert os.path.exists(os.path.join(out, "attachments", "PWS.pdf"))


def test_pruning_an_empty_or_missing_tray_is_harmless(tmp_path):
    assert packet.prune_closed_packets(str(tmp_path / "nope")) == ([], 0)
    assert packet.prune_closed_packets(str(tmp_path)) == ([], 0)


# ---------- identifier format ----------

def test_a_well_formed_uei_and_cage_pass():
    assert company_mod.format_warnings({"uei": "GD83PAK36818", "cage": "22ND2"}) == []


def test_a_malformed_uei_is_flagged():
    # Worse than a blank: a blank is obviously unfinished, a typo reaches a
    # contracting officer looking legitimate and identifies nobody.
    assert company_mod.format_warnings({"uei": "GD83PAK3681"})   # 11 chars
    assert company_mod.format_warnings({"uei": "GD83-PAK36818"})  # punctuation
    assert company_mod.format_warnings({"cage": "22ND"})          # 4 chars


def test_a_blank_identifier_is_not_a_format_error():
    # Blanks are already reported as missing; flagging them twice is noise.
    assert company_mod.format_warnings({"uei": "", "cage": None}) == []


def test_the_real_fact_bank_has_no_format_problems():
    loaded = company_mod.load_company("p1821")
    assert company_mod.format_warnings(loaded) == []


def test_p1821_is_submission_ready():
    # The eight fields without which a packet cannot be submitted at all.
    required, _ = company_mod.missing_fields(company_mod.load_company("p1821"))
    assert required == [], f"still missing: {required}"


# ---------- the daily target ----------

def _batch(count, ranked, root, tmpdescs=None):
    """Runs the real batch stage with the network pre-empted: every notice
    already has its description, and none has attachments, so no HTTP
    happens."""
    import find_opportunities as fo
    profile = {"label": "Test profile", "draft_min_score": 3}
    descriptions = tmpdescs if tmpdescs is not None else {
        opp.get("noticeId"): "Scope: do the work." for _, _, opp in ranked}
    return fo.build_batch(count, "p1821", profile, ranked, descriptions,
                          "dummy-key", root, log=lambda m: None)


def _ranked(n, score=5):
    return [(score, "why", dict(OPP, noticeId=f"n{i}", title=f"Notice {i}")) for i in range(n)]


def test_the_target_counts_new_packets_not_reused_ones(tmp_path):
    # The bug this pins: counting reused packets meant a stable top 3 would
    # fill the quota with packets you already had, and the tray would stop
    # growing while every log line still looked healthy.
    ranked = _ranked(10)
    root = str(tmp_path)

    first, _ = _batch(3, ranked, root)
    assert sum(1 for b in first if b[3] == "new") == 3

    second, _ = _batch(3, ranked, root)
    new_second = [b for b in second if b[3] == "new"]
    assert len(new_second) == 3, "a second run must still produce three NEW packets"
    # ...and they must be different notices from the first run's.
    assert {b[0] for b in new_second}.isdisjoint({b[0] for b in first})


def test_low_scoring_notices_are_never_packeted_to_hit_the_target(tmp_path):
    # Better to deliver fewer than the target than to prepare bids on work
    # the profile does not really match.
    ranked = _ranked(2, score=5) + _ranked(8, score=1)
    built, _ = _batch(5, ranked, str(tmp_path))
    assert sum(1 for b in built if b[3] == "new") == 2


def test_the_target_is_a_ceiling_not_a_quota_to_fill(tmp_path):
    built, _ = _batch(3, _ranked(1), str(tmp_path))
    assert len(built) == 1


def test_skip_rules_do_not_consume_the_target(tmp_path):
    # A skipped notice should not cost you one of the day's three.
    import company as cm
    ranked = _ranked(5)
    ranked[0][2]["title"] = "Foundation Repair at Building 7"
    original = cm.skip_reason
    cm.skip_reason = lambda c, o: "matches skip_keywords" if "Foundation" in (o.get("title") or "") else None
    try:
        built, skipped = _batch(3, ranked, str(tmp_path))
    finally:
        cm.skip_reason = original
    assert len(skipped) == 1
    assert sum(1 for b in built if b[3] == "new") == 3, "the skip must not cost a slot"


def test_a_current_packet_costs_no_api_call(tmp_path):
    # needs_work is what keeps a re-run from spending the description budget
    # on packets that would not use it.
    company = company_mod.load_company("p1821")
    root = str(tmp_path)
    assert packet.needs_work(OPP, company, root) is True
    packet.build_packet(OPP, "Scope.", company, root, 4, "")
    assert packet.needs_work(OPP, company, root) is False
    # A changed fact bank, or a deleted file, makes it work again.
    assert packet.needs_work(OPP, dict(company, phone="+1-000"), root) is True
    os.remove(os.path.join(packet.packet_dir(OPP, root), "02-price-sheet.csv"))
    assert packet.needs_work(OPP, company, root) is True


# ---------- what cannot be bid ----------

def test_a_sources_sought_notice_is_not_biddable():
    import find_opportunities as fo
    # The live trap: HQMC "M95494-26-SSN-ADCFAS" got a full priced packet,
    # cover email and all, for a notice whose own text says in capitals
    # that it is not a solicitation of any kind.
    reason = fo.not_biddable_reason({"type": "Sources Sought"})
    assert reason and "capability statement" in reason


def test_real_solicitation_types_are_biddable():
    import find_opportunities as fo
    for good in ("Solicitation", "Combined Synopsis/Solicitation",
                 "combined synopsis/solicitation"):
        assert fo.not_biddable_reason({"type": good}) is None, good


def test_award_and_presolicitation_notices_are_not_biddable():
    import find_opportunities as fo
    assert fo.not_biddable_reason({"type": "Award Notice"})
    assert fo.not_biddable_reason({"type": "Presolicitation"})


def test_an_unknown_type_is_left_biddable():
    import find_opportunities as fo
    # SAM adds notice types over time. Hiding a real solicitation because
    # of a label we have not seen is the worse failure.
    assert fo.not_biddable_reason({"type": "Some Future Notice Type"}) is None
    assert fo.not_biddable_reason({}) is None


def test_basetype_is_used_when_type_is_absent():
    import find_opportunities as fo
    assert fo.not_biddable_reason({"baseType": "Sources Sought"})


def test_the_batch_refuses_to_packet_an_unbiddable_notice(tmp_path):
    ranked = [(9, "why", dict(OPP, noticeId="ss1", type="Sources Sought")),
              (8, "why", dict(OPP, noticeId="ok1", type="Solicitation"))]
    built, skipped = _batch(3, ranked, str(tmp_path))
    assert len(built) == 1
    assert len(skipped) == 1
    assert "capability statement" in skipped[0][1]


# ---------- credential gates ----------

def test_a_cpa_requirement_is_caught():
    # Verbatim from the NAFI Audit RFQ that cost a day before anyone read
    # far enough into the attachment to find it.
    gates = packet.credential_gates(
        "requires the services of an independent Certified Public Accountant "
        "firm or licensed CPA to perform financial statement audits")
    assert gates == ["a licensed CPA or CPA firm"]


def test_a_clearance_requirement_is_caught():
    assert packet.credential_gates(
        "All personnel shall hold a TS/SCI clearance") == [
        "a security clearance or facility clearance"]
    assert packet.credential_gates("A facility clearance (FCL) is required")


def test_ordinary_work_trips_no_gate():
    assert packet.credential_gates(
        "The contractor shall provide monthly bookkeeping and reconciliation.") == []
    assert packet.credential_gates("") == []
    assert packet.credential_gates(None) == []


def test_several_gates_are_all_reported():
    gates = packet.credential_gates(
        "Work shall be sealed by a Professional Engineer and performed by "
        "cleared personnel holding a SECRET clearance.")
    assert len(gates) == 2


def test_the_gates_reach_the_checklist_where_the_decision_is_made(tmp_path):
    out, _, _ = packet.build_packet(
        OPP,
        "The Government requires an independent CPA firm to perform the audit.",
        FILLED, str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "a licensed CPA or CPA firm" in text
    assert "pass/fail" in text
    assert "costs you the week" in text


def test_a_packet_with_no_gates_says_nothing_about_them(tmp_path):
    out, _, _ = packet.build_packet(
        OPP, "The contractor shall provide monthly bookkeeping.",
        FILLED, str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "pass/fail" not in text


def test_the_notice_type_is_recorded_in_the_checklist(tmp_path):
    out, _, _ = packet.build_packet(
        dict(OPP, type="Combined Synopsis/Solicitation"), "", FILLED,
        str(tmp_path), 4, "")
    assert "Combined Synopsis/Solicitation" in open(
        os.path.join(out, "00-START-HERE.md")).read()


def test_safety_training_requirements_are_caught():
    # Missed on the first pass: the USDA confined-space PWS says the
    # contractor "shall provide service personnel with OSHA and NFPA
    # confined space" qualifications. Not a licence, but just as pass/fail
    # for a firm that does not employ trained confined-space assessors.
    assert packet.credential_gates(
        "The contractor shall provide service personnel with OSHA and NFPA "
        "confined space training") == [
        "documented OSHA / NFPA safety training for the crew"]
    assert packet.credential_gates("assessment per 29 CFR 1910.146")
    assert packet.credential_gates("a competent person shall evaluate each space")


def test_named_standard_assessor_requirements_are_caught():
    assert packet.credential_gates(
        "vendor shall audit the laboratory against ISO/IEC 17025") == [
        "accredited assessor or auditor competence for a named standard"]


def test_the_new_patterns_do_not_fire_on_office_work():
    # These run on every packet, so a false positive on ordinary
    # professional services would train the user to ignore the block.
    for benign in (
        "Provide monthly bookkeeping, payroll processing and reconciliation.",
        "The contractor shall prepare quarterly financial reports.",
        "Administrative support including scheduling and correspondence.",
    ):
        assert packet.credential_gates(benign) == [], benign


# ---------- which codes get packets ----------

def test_packet_naics_narrows_packets_without_hiding_anything():
    cfg = {"packet_naics": ["541219", "541611"]}
    assert company_mod.skip_reason(cfg, {"naicsCode": "541611"}) is None
    reason = company_mod.skip_reason(cfg, {"naicsCode": "541620"})
    assert reason and "still shown in the digest" in reason


def test_an_empty_packet_naics_allows_every_code():
    assert company_mod.skip_reason({"packet_naics": []}, {"naicsCode": "541620"}) is None
    assert company_mod.skip_reason({}, {"naicsCode": "541620"}) is None


def test_a_notice_with_no_naics_is_not_dropped_by_the_allow_list():
    # Missing data must not silently discard a real solicitation.
    assert company_mod.skip_reason({"packet_naics": ["541219"]}, {}) is None


def test_the_shipped_allow_list_matches_the_profile_it_belongs_to():
    import find_opportunities as fo
    company = company_mod.load_company("p1821")
    allowed = set(company.get("packet_naics") or [])
    assert allowed, "p1821 should ship an allow-list"
    registered = set(fo.PROFILES["p1821"]["naics"])
    assert allowed <= registered, "cannot build packets for codes not registered"
    # The two codes that produced real but unperformable work are excluded.
    assert "541620" not in allowed
    assert "541720" not in allowed
