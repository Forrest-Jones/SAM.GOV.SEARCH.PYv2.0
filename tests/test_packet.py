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


def test_the_batch_never_prices_an_unbiddable_notice(tmp_path):
    # A Sources Sought gets a capability statement instead of being
    # dropped — it is often the best opening available — but it must never
    # get a price sheet, which was the original category error.
    ranked = [(9, "why", dict(OPP, noticeId="ss1", type="Sources Sought")),
              (8, "why", dict(OPP, noticeId="ok1", type="Solicitation"))]
    built, skipped = _batch(3, ranked, str(tmp_path))
    assert len(built) == 2
    by_id = {os.path.basename(out).split("-")[0]: out for out, _, _, _ in built}
    assert not os.path.exists(os.path.join(by_id["ss1"], "02-price-sheet.csv"))
    assert os.path.exists(os.path.join(by_id["ss1"], "01-capability-statement.md"))
    # The real solicitation still gets the full priced packet.
    assert os.path.exists(os.path.join(by_id["ok1"], "02-price-sheet.csv"))


def test_an_award_notice_is_still_dropped_entirely(tmp_path):
    ranked = [(9, "why", dict(OPP, noticeId="aw1", type="Award Notice"))]
    built, skipped = _batch(3, ranked, str(tmp_path))
    assert built == []
    assert len(skipped) == 1
    assert "already awarded" in skipped[0][1]


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
    assert "pass/fail before anything else" in text
    assert "the whole week after the proposal is" in text


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


# ---------- credentials on file, and what they do and do not cover ----------

EA_ONLY = {"credentials": [{"kind": "ea", "holder": "Randy White"}]}


def test_an_enrolled_agent_does_not_satisfy_a_cpa_requirement():
    # The most important assertion in this file. An EA is IRS-licensed
    # under Circular 230 with unlimited representation rights before the
    # IRS; audits and any opinion on financial statements are reserved to
    # CPAs licensed by a state board. Treating one as the other would put
    # a false representation on a federal submission.
    assert company_mod.satisfies(EA_ONLY, "a licensed CPA or CPA firm") is None


def test_an_enrolled_agent_is_still_recognised_as_held():
    # Not satisfying the CPA gate is different from being ignored — it has
    # to be on file so it can be cited where it IS the qualification.
    held = company_mod.held_credentials(EA_ONLY)
    assert len(held) == 1
    assert held[0]["kind"] == "ea"
    assert "Circular 230" in held[0]["label"]
    assert held[0]["holder"] == "Randy White"


def test_no_credential_satisfies_a_gate_it_is_not_mapped_to():
    # Nothing is inferred from adjacency: same field is not same licence.
    ea_gates = [g for g in company_mod.CREDENTIAL_SATISFIES.values() if g]
    for gate in ea_gates:
        holder = company_mod.satisfies(EA_ONLY, gate)
        assert holder is None or holder["kind"] != "ea", gate


def test_a_matching_credential_does_satisfy_its_gate():
    cpa = {"credentials": [{"kind": "cpa", "holder": "J. Doe", "identifier": "TX-12345"}]}
    holder = company_mod.satisfies(cpa, "a licensed CPA or CPA firm")
    assert holder and holder["identifier"] == "TX-12345"


def test_a_credential_with_no_holder_is_not_on_file():
    # The blank template row must not read as a held credential.
    assert company_mod.held_credentials({"credentials": [{"kind": "cpa", "holder": ""}]}) == []


def test_the_checklist_resolves_a_gate_against_what_is_on_file(tmp_path):
    cpa = dict(FILLED, credentials=[{"kind": "cpa", "holder": "J. Doe", "identifier": "TX-12345"}])
    out, _, _ = packet.build_packet(
        OPP, "requires an independent licensed CPA to audit the statements",
        cpa, str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "Covered." in text
    assert "TX-12345" in text
    assert "this one is over" not in text


def test_the_checklist_blocks_when_nothing_on_file_covers_the_gate(tmp_path):
    ea = dict(FILLED, credentials=[{"kind": "ea", "holder": "Randy White"}])
    out, _, _ = packet.build_packet(
        OPP, "requires an independent licensed CPA to audit the statements",
        ea, str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "nothing on file covers this" in text
    assert "this one is over" in text


def test_the_real_fact_bank_holds_the_enrolled_agent_and_no_cpa():
    company = company_mod.load_company("p1821")
    kinds = {c["kind"] for c in company_mod.held_credentials(company)}
    assert "ea" in kinds
    assert "cpa" not in kinds, "no CPA licence is on file; packets must not claim one"
    assert company_mod.satisfies(company, "a licensed CPA or CPA firm") is None


def test_every_plain_key_of_a_profile_survives_the_toml_tables():
    # TOML footgun with teeth: the first [[p1821.xxx]] array-of-tables ends
    # the parent table, so a bare key written after it belongs to the
    # sub-table instead. That silently emptied packet_naics once already,
    # which turned the capability gate off without any error.
    company = company_mod.load_company("p1821")
    for key in ("legal_name", "uei", "cage", "address", "packet_naics"):
        assert company.get(key), f"{key} did not survive parsing"


# ---------- running on an older interpreter ----------

def test_the_toml_parser_is_optional_at_import_time():
    # Live failure on a Mac running Anaconda's Python: tomllib is standard
    # library only from 3.11, and assuming it broke startup with nothing
    # but a ModuleNotFoundError. company.py must import either way.
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def without_toml(name, *args, **kwargs):
        if name in ("tomllib", "tomli"):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    for name in ("company", "packet", "proposal"):
        sys.modules.pop(name, None)
    builtins.__import__ = without_toml
    try:
        module = importlib.import_module("company")
        assert module.tomllib is None
        loaded = module.load_company("p1821")
        # Degrades to visible blanks with an actionable message, rather
        # than taking the whole pipeline down.
        assert "pip install tomli" in loaded["_error"]
        required, _ = module.missing_fields(loaded)
        assert len(required) == len(module.REQUIRED_FIELDS)
        assert module.skip_reason(loaded, {"naicsCode": "541219"}) is None
    finally:
        builtins.__import__ = real_import
        for name in ("company", "packet", "proposal"):
            sys.modules.pop(name, None)
        importlib.import_module("company")


def test_requirements_pin_tomli_for_older_pythons():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "requirements.txt")).read()
    assert "tomli" in text
    assert 'python_version < "3.11"' in text, (
        "must be marked, or pip installs a redundant backport on 3.11+")


def test_the_launcher_checks_every_import_not_just_flask():
    # The launcher skipped its install step because Flask happened to be
    # present, and the app then died on the missing TOML parser.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = open(os.path.join(root, "start.command")).read()
    # Every module the app imports at startup has to be covered, however
    # the script spells the check.
    assert "for mod in flask requests" in script
    assert 'python3 -c "import tomllib"' in script
    assert 'python3 -c "import tomli"' in script
    # ...and the install must be driven by whatever is missing, not by
    # Flask alone, which is the bug this pins.
    assert 'if [ -n "$missing" ]' in script


# ---------- PSC families ----------

def test_psc_prefixes_keep_field_work_out_of_the_tray():
    # Live case: a gas leak survey at Luke AFB arrived coded NAICS 541990,
    # the "all other professional services" junk drawer, and would have
    # been prepared as a bid. Its PSC was H999 — inspection.
    cfg = {"packet_psc_prefixes": ["R", "B"]}
    assert company_mod.skip_reason(cfg, {"classificationCode": "R704"}) is None
    assert company_mod.skip_reason(cfg, {"classificationCode": "B505"}) is None
    for field_work in ("H999", "J041", "Z2AZ", "F108", "S222"):
        assert company_mod.skip_reason(cfg, {"classificationCode": field_work}), field_work


def test_an_empty_psc_prefix_list_allows_everything():
    assert company_mod.skip_reason({"packet_psc_prefixes": []}, {"classificationCode": "H999"}) is None
    assert company_mod.skip_reason({}, {"classificationCode": "H999"}) is None


def test_a_notice_with_no_psc_is_not_dropped():
    # Real notices come through with classificationCode absent; missing
    # data must never discard a solicitation.
    assert company_mod.skip_reason({"packet_psc_prefixes": ["R"]}, {}) is None
    assert company_mod.skip_reason({"packet_psc_prefixes": ["R"]},
                                   {"classificationCode": None}) is None


def test_psc_matching_is_case_insensitive():
    cfg = {"packet_psc_prefixes": ["r"]}
    assert company_mod.skip_reason(cfg, {"classificationCode": "R704"}) is None


def test_the_shipped_psc_filter_matches_the_profile_priorities():
    import find_opportunities as fo
    company = company_mod.load_company("p1821")
    prefixes = company.get("packet_psc_prefixes") or []
    assert prefixes, "p1821 should ship a PSC filter"
    # Every PSC the profile already scores as a priority must survive it.
    for psc in fo.PROFILES["p1821"]["priority_psc"]:
        assert any(psc.upper().startswith(p.upper()) for p in prefixes), psc


# ---------- environmental authority ----------

def test_rcra_hazardous_waste_authority_is_a_gate():
    # The DLA Charleston solicitation: removal, transport and disposal of
    # RCRA hazardous waste, using facilities and transporters from DLA's
    # Qualified Facilities and Transporters Lists. None of that was caught
    # before — the detector knew about CPAs and engineers and nothing about
    # the permits that gate environmental work.
    gates = packet.credential_gates(
        "Work will consist primarily of the removal, transportation, and disposal "
        "of Resource Conservation and Recovery Act (RCRA) hazardous wastes")
    assert any("EPA / RCRA" in g for g in gates)


def test_tsdf_and_qualified_lists_trip_the_same_gate():
    for text in (
        "the Contractor's Treatment, Storage and Disposal Facility (TSDF) of choice",
        "only utilize facilities and transporters listed on the Qualified Facilities List",
        "fees associated with the EPA national electronic manifest (e-Manifest) system",
        "Universal Treatment Standards per 40 Code of Federal Regulation (CFR) 268.48",
    ):
        assert any("EPA / RCRA" in g for g in packet.credential_gates(text)), text


def test_dot_hazmat_certification_is_its_own_gate():
    gates = packet.credential_gates(
        "DOT regulations, including Proper Shipping Name (PSN) and Hazard Class")
    assert any("DOT hazardous materials" in g for g in gates)


def test_environmental_gates_stay_quiet_on_office_work():
    for benign in (
        "Provide monthly bookkeeping and reconciliation services.",
        "Prepare quarterly financial statements and management reports.",
        "Administrative support for the program office.",
    ):
        assert packet.credential_gates(benign) == [], benign


# ---------- the closing time, not just the date ----------

def test_the_closing_time_is_shown_with_its_zone():
    # A date alone hides the half of the deadline that catches people: the
    # NAFI audit closed at 08:00, not end of business.
    assert packet._deadline_clock({"responseDeadLine": "2026-09-22T08:00:00-04:00"}) == "08:00 (UTC-04)"
    assert packet._deadline_clock({"responseDeadLine": "2026-09-30T12:00:00Z"}) == "12:00 (UTC)"


def test_a_date_with_no_time_says_so_rather_than_guessing():
    assert packet._deadline_clock({"responseDeadLine": "2026-09-30"}) == ""
    assert packet._deadline_clock({}) == ""


def test_the_checklist_carries_the_closing_time(tmp_path):
    out, _, _ = packet.build_packet(
        dict(OPP, responseDeadLine="2026-09-28T14:00:00-04:00"),
        "", FILLED, str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "14:00 (UTC-04)" in text


def test_a_packet_with_no_published_time_says_to_confirm(tmp_path):
    out, _, _ = packet.build_packet(
        dict(OPP, responseDeadLine="2026-09-28"), "", FILLED, str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "confirm on the listing" in text


# ---------- a profile that cannot submit is not searched ----------

def test_both_profiles_bid_under_the_one_registration():
    # Ares Robotics is in-house to Proverbs 1821, not a separate offeror.
    # Both lanes submit under the same legal entity, so neither can be
    # blocked for want of an identity it was never going to have.
    p1821 = company_mod.load_company("p1821")
    ares = company_mod.load_company("ares")
    for key in ("legal_name", "uei", "cage", "address"):
        assert ares[key] == p1821[key], key
    assert company_mod.missing_fields(ares)[0] == []


def test_a_lane_can_be_switched_off_without_pretending_it_cannot_bid():
    # The reason a lane goes quiet is now a deliberate choice, not a
    # missing UEI: opportunities that will not be acted on this month are
    # noise, and noise in a daily email costs an afternoon.
    active = company_mod.load_company("p1821").get("active_profiles")
    assert active == ["p1821"]
    assert "ares" not in active


def test_the_bench_is_on_file_with_what_each_person_brings():
    team = {p["name"]: p for p in company_mod.personnel(company_mod.load_company("p1821"))}
    assert {"Forrest A. Jones", "Richard Starr", "Randy White", "Jason Teal"} <= set(team)
    assert "1985" in team["Richard Starr"]["brings"], "robotics since 1985"
    assert "Enrolled Agent" in team["Randy White"]["brings"]
    # Randy's entry must say what it is not, because the whole file exists
    # to stop an EA being offered against a CPA requirement.
    assert "Not a CPA" in team["Randy White"]["brings"]


def test_an_affiliation_is_labelled_as_one():
    allies = company_mod.affiliations(company_mod.load_company("p1821"))
    assert len(allies) == 1
    assert "Blackwater" in allies[0]["name"]
    assert allies[0]["cite_as"] == "affiliation and teaming resource"


def test_the_ares_lane_carries_the_robotics_capability():
    ares = company_mod.load_company("ares")
    cap = ares["capability_statement"]
    for fact in ("Manway Cannon", "SLOFEC", "Exxon", "1998"):
        assert fact in cap, fact
    # And the deployment record stays attributed rather than restated as
    # this entity's own contract history.
    assert "in-house" in cap.lower()


def test_p1821_does_have_one():
    required, _ = company_mod.missing_fields(company_mod.load_company("p1821"))
    assert required == []


def test_the_identity_check_blocks_only_on_identity_fields():
    # A missing capability statement or rate card is a nuisance. A missing
    # legal name means nothing found could be submitted by anyone.
    partial = {"legal_name": "X Co", "uei": "ABC123456789", "cage": "9XYZ1"}
    required, _ = company_mod.missing_fields(partial)
    blocking = [f for f in required
                if f in ("legal business name", "UEI (12 chars, from SAM.gov)", "CAGE code")]
    assert blocking == [], "identity present, so the search should run"
    assert required, "other fields are still reported as missing"


def test_a_commercial_engagement_with_no_contract_number_still_counts():
    # For a firm with no federal record, commercial work is the entire
    # relevant-experience section — and commercial engagements routinely
    # have no contract number. Requiring one discarded them silently.
    commercial = {"past_performance": [
        {"customer": "Blackwater Investment Group, Inc.", "contract": "",
         "scope": "Investor reporting and capitalization records"}]}
    assert len(company_mod.filled_rows(commercial, "past_performance")) == 1


def test_a_row_with_no_customer_is_still_not_a_reference():
    blank = {"past_performance": [{"customer": "", "contract": "W912-001"}]}
    assert company_mod.filled_rows(blank, "past_performance") == []


# ---------- the gate that decides the bid is usually in an attachment ----------

def test_attachment_text_is_scanned_for_gates(tmp_path):
    # Both real misses came from scanning only the notice body: NAFI's
    # "independent CPA firm or licensed CPA" sat on page two of an
    # evaluation attachment, and the HQMC Secret facility clearance in
    # section 10 of a draft work statement. Both were found by hand, after
    # time had gone into the packet.
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "PWS.txt").write_text(
        "10.0 SECURITY REQUIREMENTS All tasks shall be conducted in full "
        "compliance with DoD security regulations. At time of contract award, "
        "all of the Contractor's staff assigned to this contract shall have and "
        "maintain a Secret clearance and the Contractor shall have and maintain "
        "a Secret facility clearance.")
    text = packet.attachment_text(str(att))
    assert "Secret facility clearance" in text
    assert packet.credential_gates(text) == ["a security clearance or facility clearance"]


def test_the_manifest_is_not_scanned_as_a_requirement(tmp_path):
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "MANIFEST.txt").write_text("Attachments listed on SAM.gov notice")
    (att / "PRUNED.txt").write_text("Deadline passed, files removed")
    assert packet.attachment_text(str(att)) == ""


def test_a_missing_attachments_folder_is_harmless():
    assert packet.attachment_text("/nonexistent/attachments") == ""


def test_unreadable_formats_are_skipped_not_fatal(tmp_path):
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "drawing.dwg").write_bytes(b"\x00\x01binary")
    (att / "broken.docx").write_bytes(b"not a zip file")
    (att / "notes.txt").write_text("Contractor shall hold a Secret clearance.")
    text = packet.attachment_text(str(att))
    assert "Secret clearance" in text


def test_the_scan_is_capped(tmp_path):
    att = tmp_path / "attachments"
    att.mkdir()
    (att / "huge.txt").write_text("x" * (packet.ATTACHMENT_SCAN_LIMIT * 2))
    assert len(packet.attachment_text(str(att))) <= packet.ATTACHMENT_SCAN_LIMIT


def test_a_packets_gate_block_reflects_its_attachments(tmp_path):
    att = packet.packet_dir(OPP, str(tmp_path))
    os.makedirs(os.path.join(att, "attachments"), exist_ok=True)
    with open(os.path.join(att, "attachments", "PWS.txt"), "w") as f:
        f.write("The Contractor shall maintain a Secret facility clearance.")
    out, _, _ = packet.build_packet(OPP, "Provide bookkeeping support.", FILLED,
                                   str(tmp_path), 4, "")
    text = open(os.path.join(out, "00-START-HERE.md")).read()
    assert "a security clearance or facility clearance" in text
    assert "nothing on file covers this" in text


# ---------- certifications live in exactly one place ----------

def test_certifications_are_not_a_saved_setting():
    # A WOSB sole source kept reading "Great Match — eligible" in the web
    # UI for two days after the code stopped claiming WOSB, because
    # settings.json still said the certification was held. Two copies of a
    # fact is one copy too many.
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp"))
    import app as webapp
    assert "certifications" not in webapp.PER_PROFILE_KEYS
    assert "certifications" not in webapp.default_profile_settings("p1821")
    assert "certifications" not in webapp.DEFAULT_SHARED


def test_the_web_ui_reads_held_certs_from_the_one_constant():
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp"))
    import app as webapp
    import find_opportunities as fo
    held = webapp.held_certifications()
    assert held["held"] == list(fo.DEFAULT_HELD_CERTS)
    assert "wosb" not in held["held"]
    assert "edwosb" not in held["held"]
    # Every program is still listed, so the page can show what is NOT held.
    assert set(held["labels"]) == set(fo.CERTIFICATION_HINTS)


def test_a_stale_settings_file_claiming_wosb_is_stripped(tmp_path, monkeypatch):
    import json
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp"))
    import app as webapp

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "active_profile": "p1821",
        "profiles": {"p1821": {"certifications": ["wosb", "edwosb"],
                               "naics_codes": ["541611"]}},
    }))
    monkeypatch.setattr(webapp, "SETTINGS_PATH", str(path))

    loaded = webapp.load_store()
    assert "certifications" not in loaded["profiles"]["p1821"]
    # ...and removed from the file, so nothing reads it again.
    assert "certifications" not in json.loads(path.read_text())["profiles"]["p1821"]
    # The unrelated setting survives.
    assert loaded["profiles"]["p1821"]["naics_codes"] == ["541611"]


# ---------- company facts live in exactly one place, too ----------

def _webapp():
    import sys
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp"))
    import app as webapp
    return webapp


def test_company_facts_are_not_a_saved_setting():
    # Same drift as the certifications: settings.json carried its own empty
    # company_profile, the Settings form showed blank identity fields, and
    # the old proposal builder produced drafts with blank UEI while
    # company.toml had it all along.
    webapp = _webapp()
    assert "company_profile" not in webapp.DEFAULT_SHARED
    assert "company_profile" not in webapp.PER_PROFILE_KEYS


def test_a_stale_company_profile_in_settings_is_stripped(tmp_path, monkeypatch):
    import json
    webapp = _webapp()
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "active_profile": "p1821",
        "company_profile": {"legal_name": "", "uei": ""},
        "profiles": {"p1821": {"naics_codes": ["541611"]}},
    }))
    monkeypatch.setattr(webapp, "SETTINGS_PATH", str(path))
    loaded = webapp.load_store()
    assert "company_profile" not in loaded
    assert "company_profile" not in json.loads(path.read_text())


def test_the_factbank_endpoint_returns_the_identity_on_file():
    webapp = _webapp()
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        data = c.get("/api/factbank?profile=p1821").get_json()
    assert data["identity"]["legal_name"] == "Proverbs 1821 Consulting LLC"
    assert data["identity"]["uei"] == "GD83PAK36818"
    assert data["identity"]["cage"] == "22ND2"
    assert data["identity"]["signatory_name"] == "Forrest Andrew Jones"
    names = {p["name"] for p in data["personnel"]}
    assert {"Forrest A. Jones", "Richard Starr", "Randy White"} <= names
    assert data["held_certs"]["held"] == ["small_business"]
    assert any(r["customer"].startswith("Blackwater") for r in data["references"])
    assert data["source"] == "company.toml"


def test_the_web_proposal_builder_uses_the_fact_bank(tmp_path, monkeypatch):
    # The path a user reaches from Review Packets. It used to read the
    # empty settings copy and draft a proposal with [[FILL: UEI]] on it.
    import json
    webapp = _webapp()
    notices = tmp_path / "notices" / "p1821"
    notices.mkdir(parents=True)
    (notices / "n1.json").write_text(json.dumps({
        "opp": dict(OPP, noticeId="n1"), "description": "Scope.", "score": 4, "reasons": ""}))
    monkeypatch.setattr(webapp, "notices_dir_for", lambda p: str(notices))
    monkeypatch.setattr(webapp, "proposals_dir_for", lambda p: str(tmp_path / "proposals"))
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        data = c.post("/api/proposals/n1?profile=p1821").get_json()
    assert data["ok"]
    assert "GD83PAK36818" in data["content"]
    assert "[[FILL: UEI" not in data["content"]


# ---------- the desk handles a Sources Sought folder ----------

def _capability_tray(tmp_path, monkeypatch):
    """A packets tray holding one capability response, served by the app."""
    webapp = _webapp()
    root = tmp_path / "packets" / "p1821" / "abc123-hqmc-financial"
    root.mkdir(parents=True)
    (root / "00-START-HERE.md").write_text("# HQMC Financial\n\n| | |\n|---|---|\n| **Due** | **2099-01-01** |\n")
    (root / "01-capability-statement.md").write_text(
        "# Capability Statement — HQMC\n\n## Cover page\n\n| Field | Value |\n|---|---|\n"
        "| Company | Proverbs 1821 Consulting LLC |\n| Accounting system | [[FILL: accounting system]] |\n\n"
        "## Company profile\n\nWe do the work.\n\n## Answers\n\n"
        "**[DRAFT — your review]** Subcontractor.\n\n**[DRAFT — your review]** Yes.\n")
    (root / "02-response-email.txt").write_text(
        "To:      a@usmc.mil, b@usmc.mil\nSubject: SSN — Response\n\nSir,\n\nAttached.\n\n"
        "--------------------------------------------------------------------\nBEFORE SENDING:\n  [ ] x\n")
    monkeypatch.setattr(webapp, "DATA_DIR", str(tmp_path))
    webapp.app.config["TESTING"] = True
    return webapp, "abc123-hqmc-financial"


def test_the_desk_reads_blanks_from_a_capability_statement(tmp_path, monkeypatch):
    # Live failure: the desk only knew 01-proposal.md, so the one packet
    # actually being submitted showed "Nothing left to fill", a dead
    # download link and a price step for a notice that forbids a price.
    webapp, folder = _capability_tray(tmp_path, monkeypatch)
    with webapp.app.test_client() as c:
        tray = c.get("/api/packets?profile=p1821").get_json()["packets"]
        d = c.get(f"/api/packets/{folder}?profile=p1821").get_json()
    assert tray[0]["kind"] == "capability"
    assert tray[0]["blanks"] == 1 and tray[0]["drafts"] == 2
    assert d["kind"] == "capability"
    assert d["response_file"] == "01-capability-statement.md"
    assert [b["label"] for b in d["blanks"]] == ["accounting system"]
    assert d["price_rows"] == []
    assert d["email"].startswith("To:      a@usmc.mil")


def test_filling_writes_into_the_capability_statement(tmp_path, monkeypatch):
    webapp, folder = _capability_tray(tmp_path, monkeypatch)
    with webapp.app.test_client() as c:
        res = c.post(f"/api/packets/{folder}/fill?profile=p1821",
                     json={"answers": {"0": {"label": "accounting system", "value": "QuickBooks Online"}}}).get_json()
    assert res["ok"] and res["remaining"] == 0
    text = (tmp_path / "packets" / "p1821" / folder / "01-capability-statement.md").read_text()
    assert "| Accounting system | QuickBooks Online |" in text


def test_approving_drafts_removes_every_marker_and_nothing_else(tmp_path, monkeypatch):
    webapp, folder = _capability_tray(tmp_path, monkeypatch)
    with webapp.app.test_client() as c:
        res = c.post(f"/api/packets/{folder}/approve-drafts?profile=p1821", json={}).get_json()
    assert res["ok"] and res["drafts"] == 0
    text = (tmp_path / "packets" / "p1821" / folder / "01-capability-statement.md").read_text()
    assert "[DRAFT" not in text
    assert "Subcontractor.\n\nYes.\n" in text
    assert "[[FILL: accounting system]]" in text, "approval must not touch blanks"


def test_the_print_view_pages_the_statement_and_flags_what_is_left(tmp_path, monkeypatch):
    webapp, folder = _capability_tray(tmp_path, monkeypatch)
    with webapp.app.test_client() as c:
        page = c.get(f"/api/packets/{folder}/print?profile=p1821")
        html = page.get_data(as_text=True)
    assert page.status_code == 200 and "text/html" in page.content_type
    assert "Not ready to send" in html and "1 blank" in html and "2 draft" in html
    assert html.count(' page-break"') == 2
    assert "<li>Company profile</li>" in html and "<li>Answers</li>" in html
    assert 'mark class="fill"' in html and 'mark class="draft"' in html
    assert "<table>" in html and "<td>Proverbs 1821 Consulting LLC</td>" in html
    with webapp.app.test_client() as c:
        c.post(f"/api/packets/{folder}/approve-drafts?profile=p1821", json={})
        c.post(f"/api/packets/{folder}/fill?profile=p1821",
               json={"answers": {"0": {"label": "accounting system", "value": "QuickBooks Online"}}})
        html = c.get(f"/api/packets/{folder}/print?profile=p1821").get_data(as_text=True)
    assert "Ready." in html and "Not ready" not in html


def test_a_fact_bank_change_refreshes_only_untouched_capability_files(tmp_path):
    import packet
    from tests.test_capability import SSN, NOTICE_TEXT, BANK
    out, _, _ = packet.build_capability_response(
        SSN, NOTICE_TEXT, BANK, str(tmp_path), notice_kind="Sources Sought")
    answered = os.path.join(out, "01-capability-statement.md")
    with open(answered, "w") as f:
        f.write("MY ANSWERS [[FILL: one]]")
    # A new alternate contact in the fact bank must reach the cover email
    # and the checklist, and must never touch the edited statement.
    richer = dict(BANK, secondary_contact_name="Randy White",
                  secondary_contact_title="Enrolled Agent",
                  secondary_contact_phone="(555) 000-0000")
    again, blanks, status = packet.build_capability_response(
        SSN, NOTICE_TEXT, richer, str(tmp_path), notice_kind="Sources Sought")
    assert (again, status) == (out, "partial")
    assert open(answered).read() == "MY ANSWERS [[FILL: one]]"
    assert blanks == 1, "the checklist counts what is left in the edited file"
    email = open(os.path.join(out, "02-response-email.txt")).read()
    assert "Also:     Randy White, Enrolled Agent — (555) 000-0000" in email
    assert "**1 blanks**" in open(os.path.join(out, "00-START-HERE.md")).read()


def test_new_lane_codes_reach_a_settings_file_saved_before_them(tmp_path, monkeypatch):
    import json
    webapp = _webapp()
    path = tmp_path / "settings.json"
    store = webapp.load_store()
    store["profiles"]["p1821"]["naics_codes"] = ["541219"]
    path.write_text(json.dumps(store))
    monkeypatch.setattr(webapp, "SETTINGS_PATH", str(path))
    codes = webapp.load_settings("p1821")["naics_codes"]
    assert codes[0] == "541219"
    assert "238160" in codes, "roofing, added to the lane after this file was saved"
