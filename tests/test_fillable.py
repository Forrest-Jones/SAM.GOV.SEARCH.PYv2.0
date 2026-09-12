"""Tests for turning a packet's blanks into an editable form.

The property that matters: an answer must land in the blank the user meant.
The browser holds a snapshot that can go stale, so a write that would land
somewhere else has to fail loudly instead of quietly corrupting a federal
submission.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fillable

DOC = """# Proposal Draft — NAFI Audit

## 2. Offeror information

| Legal business name | Proverbs 1821 Consulting LLC |
| Authorized signatory | [[FILL: signatory name]] |

## 7. Price proposal

| Senior Auditor | [[FILL: hours]] | hr | 145.00 | [[FILL: $total]] |
| **Total** | | | | **[[FILL: $ total offered price]]** |
"""


def test_blanks_are_listed_in_document_order_with_labels():
    found = fillable.blanks(DOC)
    assert [b["label"] for b in found] == [
        "signatory name", "hours", "$total", "$ total offered price"]
    assert [b["index"] for b in found] == [0, 1, 2, 3]


def test_each_blank_knows_which_section_it_is_in():
    found = fillable.blanks(DOC)
    assert found[0]["section"] == "2. Offeror information"
    assert found[1]["section"] == "7. Price proposal"


def test_context_makes_a_bare_label_intelligible():
    # "hours" alone means nothing; "Senior Auditor | ____ | hr | 145.00" does.
    hours = fillable.blanks(DOC)[1]
    assert "Senior Auditor" in hours["context"]
    assert "[[FILL:" not in hours["context"], "the marker itself is noise in a form label"


def test_filling_one_blank_leaves_the_others_marked():
    out = fillable.fill(DOC, {1: {"label": "hours", "value": "120"}})
    assert "| Senior Auditor | 120 | hr |" in out
    assert "[[FILL: signatory name]]" in out
    assert out.count("[[FILL:") == 3


def test_filling_several_blanks_at_once():
    out = fillable.fill(DOC, {
        0: {"label": "signatory name", "value": "Forrest Andrew Jones"},
        1: {"label": "hours", "value": "120"},
        3: {"label": "$ total offered price", "value": "$17,400.00"},
    })
    assert "Forrest Andrew Jones" in out
    assert "$17,400.00" in out
    assert out.count("[[FILL:") == 1


def test_a_stale_page_cannot_write_into_the_wrong_blank():
    # The single most important guarantee here: if the document changed
    # since the form was rendered, the answer is refused, not misplaced.
    with pytest.raises(fillable.FillMismatch):
        fillable.fill(DOC, {1: {"label": "signatory name", "value": "oops"}})


def test_a_refused_write_changes_nothing():
    try:
        fillable.fill(DOC, {1: {"label": "wrong label", "value": "x"}})
    except fillable.FillMismatch:
        pass
    # fill is pure — the caller still holds the original and writes nothing.
    assert DOC.count("[[FILL:") == 4


def test_an_empty_answer_does_not_erase_the_marker():
    # A half-finished form must not destroy the blanks it did not touch.
    out = fillable.fill(DOC, {
        0: {"label": "signatory name", "value": ""},
        1: {"label": "hours", "value": "   "},
    })
    assert out == DOC


def test_values_are_trimmed_but_kept_intact():
    out = fillable.fill(DOC, {1: {"label": "hours", "value": "  120  "}})
    assert "| Senior Auditor | 120 | hr |" in out


def test_an_index_that_does_not_exist_is_ignored():
    assert fillable.fill(DOC, {99: {"label": "x", "value": "y"}}) == DOC


def test_string_keys_work_because_json_has_no_integer_keys():
    out = fillable.fill(DOC, {"1": {"label": "hours", "value": "120"}})
    assert "| Senior Auditor | 120 | hr |" in out


def test_filling_without_a_label_is_allowed_but_unverified():
    # Scripted use where the caller already knows the document.
    out = fillable.fill(DOC, {1: {"value": "120"}})
    assert "| Senior Auditor | 120 | hr |" in out


def test_progress_counts_what_is_left():
    assert fillable.progress(DOC) == 4
    once = fillable.fill(DOC, {0: {"label": "signatory name", "value": "F. Jones"}})
    assert fillable.progress(once) == 3


def test_a_long_label_is_marked_for_a_textarea():
    doc = "[[FILL: how you will perform the work, task by task, citing the PWS paragraph you answer]]"
    assert fillable.blanks(doc)[0]["multiline"] is True
    assert fillable.blanks("[[FILL: phone]]")[0]["multiline"] is False


def test_a_real_packet_proposal_parses():
    # The actual NAFI draft in the repo, so the form cannot break on the
    # document it exists to edit.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(
        root, "packets", "p1821",
        "f76ec48896914f22ab27ab3059083b4d-nafi-audit", "01-proposal.md")
    if not os.path.exists(path):
        pytest.skip("NAFI packet not present")
    found = fillable.blanks(open(path).read())
    assert len(found) > 20
    assert all(b["label"] for b in found), "every blank needs a label to render"
    assert all(b["section"] for b in found), "every blank needs a section to group under"


# ---------- the price table ----------

PRICED_DOC = """## 7. Price proposal

| Labor category | Qty / hours | Unit | Rate | Extended |
|---|---|---|---|---|
| [[FILL: category]] | [[FILL: hours]] | [[FILL: hr/ea]] | [[FILL: $rate]] | [[FILL: $total]] |
| [[FILL: category]] | [[FILL: hours]] | [[FILL: hr/ea]] | [[FILL: $rate]] | [[FILL: $total]] |
| **Total** | | | | **[[FILL: $ total offered price]]** |

- Other direct costs: [[FILL: travel, materials, ODCs — or state none]]
"""

ROWS = [
    {"category": "Engagement Partner (CPA)", "unit": "hr", "rate": "225", "hours": "40"},
    {"category": "Senior Auditor", "unit": "hr", "rate": "145", "hours": "160"},
]


def test_saving_the_price_answers_the_whole_price_section():
    # Otherwise the fill-in form shows two dozen bare boxes labelled
    # "category", "hours", "$rate" — a second, worse copy of the price
    # sheet the user just filled in.
    out = fillable.write_price_table(PRICED_DOC, ROWS)
    assert "| Engagement Partner (CPA) | 40 | hr | 225 | $9,000.00 |" in out
    assert "| Senior Auditor | 160 | hr | 145 | $23,200.00 |" in out
    assert "[[FILL: category]]" not in out
    assert "[[FILL: $ total offered price]]" not in out


def test_the_total_is_computed_not_asked_for():
    out = fillable.write_price_table(PRICED_DOC, ROWS)
    assert "**$32,200.00**" in out


def test_blanks_outside_the_table_survive():
    out = fillable.write_price_table(PRICED_DOC, ROWS)
    assert "[[FILL: travel, materials, ODCs — or state none]]" in out


def test_a_row_missing_a_number_shows_no_extended_rather_than_a_guess():
    out = fillable.write_price_table(
        PRICED_DOC, [{"category": "Analyst", "unit": "hr", "rate": "145", "hours": ""}])
    assert "| Analyst |  | hr | 145 |  |" in out
    assert "$" not in out.split("- Other direct")[0].split("| Analyst")[1]


def test_a_document_with_no_price_table_is_returned_untouched():
    assert fillable.write_price_table(DOC, ROWS) == DOC


def test_currency_and_comma_formatting_in_rates_is_tolerated():
    out = fillable.write_price_table(
        PRICED_DOC, [{"category": "Partner", "unit": "hr", "rate": "$1,250.00", "hours": "2"}])
    assert "$2,500.00" in out


def test_rewriting_the_table_twice_does_not_duplicate_rows():
    once = fillable.write_price_table(PRICED_DOC, ROWS)
    twice = fillable.write_price_table(once, ROWS)
    assert twice.count("Engagement Partner (CPA)") == 1
    assert twice.count("**Total**") == 1
