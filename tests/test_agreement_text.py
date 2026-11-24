"""The agreement's words are the 2014 PDF's, apart from the approved change list
(owner, 2026-11-23). The PDF is in tests/fixtures/agreements/; its text is read
with pypdf, the change list is applied to it, and the result must be the
template's words exactly. Any other difference fails.

Set AGREEMENT_TEXT_OUT to a path to keep the comparison table."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from apps.agreements import render, texts, textcheck
from apps.agreements.texts import rental_management_changes as changes

PDF = Path(__file__).resolve().parent / "fixtures" / "agreements" / \
    "skyrun_rental_management_2014_blank.pdf"
PDF_SHA256 = "cef0aab9755a6594167f659b69e8afee143ad08509f580c742bbe6ae2184d80e"


@pytest.fixture(scope="module")
def applied():
    text = textcheck.pdf_text(PDF)
    return textcheck.apply(text, changes.CHANGES)


def test_the_pdf_is_the_2014_original():
    import hashlib

    assert hashlib.sha256(PDF.read_bytes()).hexdigest() == PDF_SHA256


def test_the_template_file_is_the_one_pinned():
    tpl = texts.get("rental_management")
    assert tpl.file_sha256() == tpl.sha256, (
        "The agreement's words changed. If the change is approved, add it to the change list "
        "and pin the file's new SHA-256 in apps/agreements/texts/__init__.py.")


def test_every_entry_is_found_in_the_pdf(applied):
    _, report = applied
    table = textcheck.table(report)
    if os.environ.get("AGREEMENT_TEXT_OUT"):
        Path(os.environ["AGREEMENT_TEXT_OUT"]).write_text(table + "\n")
    print("\n" + table)
    missing = [r.change.id for r in report if r.found == 0]
    assert missing == [], f"not found in the PDF, so not applied: {missing}"
    found = {r.change.find: r.found for r in report if r.change.find}
    assert found["hottub"] == 3 and found["Hottub"] == 1          # C15, every occurrence
    assert found["it’s best efforts"] == 2                       # C25, twice


def test_the_template_is_the_pdf_with_the_changes_and_nothing_else(applied):
    expected, _ = applied
    differences = textcheck.compare(expected, render.compare_text("rental_management"))
    assert differences == [], "\n".join(differences)


def test_a_difference_off_the_list_fails(applied):
    expected, _ = applied
    tampered = render.compare_text("rental_management").replace("$75/hour", "$80/hour")
    assert textcheck.compare(expected, tampered)
    dropped = render.compare_text("rental_management").replace("at no rental fee", "")
    assert any("at no rental fee" in d for d in textcheck.compare(expected, dropped))


def test_matching_ignores_quote_style_spacing_and_line_breaks():
    text = "the Owner’s   \n  portal, and “Unit”"
    assert textcheck.pattern("the Owner's portal , and \"Unit\"").search(text)


def test_an_entry_the_pdf_does_not_have_is_listed_and_not_applied():
    text, report = textcheck.apply("Owner shall pay.", [
        textcheck.Change("X1", "nowhere", find="no such words", to="anything")])
    assert text == "Owner shall pay." and report[0].found == 0
    assert "NOT FOUND, not applied" in textcheck.table(report)


def test_the_owner_page_asks_nothing_it_must_not():
    words = render.compare_text("rental_management").upper()
    for gone in ("SOCIAL SECURITY", "TAX ID", "ROUTING", "ACCOUNT NO", "BANK NAME", "WIFI",
                 "BUSINESS FAX", "PLEASE PRINT CLEARLY", "OWNER(S) TO SIGN ON NEXT PAGE",
                 "ADDITIONAL COPIES OF THIS PAGE"):
        assert gone not in words, gone
    assert "HOME PHONE" not in words and "PHONE: [PHONE]" in words
    assert "(ALL OWNERS OF UNIT MUST SIGN)" in words and "OWNERS OF CONDO" not in words
    assert "NAME: MICHAEL LECLERC, PRESIDENT" in words
    assert "UNIT INFORMATION PROPERTY ADDRESS: [PROPERTY ADDRESS]" in words
    assert "SLEEPS: [SLEEPS] OWNER INFORMATION OWNER OF RECORD" in words
    assert "ALTERNATE PHONE (OPTIONAL): [ALTERNATE PHONE]" in words
    assert "BUSINESS PHONE" not in words and "TELEPHONE:" not in words
    assert "NAME: [EMERGENCY CONTACT NAME] MAILING ADDRESS: [EMERGENCY CONTACT ADDRESS] PHONE:" \
        in words


def _section_30(terms):
    blocks = render.document("rental_management", terms, None)
    return next(b for b in blocks if b["type"] == "section_30")["paras"]


def test_the_fee_clause_word_for_word_and_only_periods_with_a_fee():
    paras = _section_30({"fees": {
        "winter": {"threshold": "4000", "fee": "250"},
        "summer": {"threshold": "1500", "fee": "0"},
        "fall": {"threshold": "2500.5", "fee": "125.25"}}})
    assert paras == [
        changes.FEE_CLAUSE,
        "December 1 – March 31: revenue threshold $4,000 per month; fee $250 per month",
        "August 1 – November 30: revenue threshold $2,500.50 per month; fee $125.25 per month"]
    assert paras[0].startswith("MINIMUM REVENUE MANAGEMENT FEE: For each calendar month")


def test_section_30_is_none_when_empty_and_carries_the_items_after_the_clause():
    zero = {"winter": {"threshold": "4000", "fee": "0"}}
    assert _section_30({"fees": zero}) == ["None."]
    assert _section_30({}) == ["None."]
    paras = _section_30({"fees": {"summer": {"threshold": "1000", "fee": "50"}},
                         "additional_items": "Hot tub cover replaced by Owner.\n\nNo pets."})
    assert paras[0] == changes.FEE_CLAUSE
    assert paras[1] == "April 1 – July 31: revenue threshold $1,000 per month; fee $50 per month"
    assert paras[2:] == ["Hot tub cover replaced by Owner.", "No pets."]
    assert _section_30({"additional_items": "  "}) == ["None."]


def test_the_split_and_the_address_fill_their_places():
    blocks = render.document("rental_management", {
        "owner_percent": "72.5", "manager_percent": "27.5",
        "property_address": {"street": "12 Example Lane", "unit": "#3", "city": "Park City",
                             "state": "UT", "zip": "84060"}}, None)
    words = " ".join("".join(s["v"] for s in b["spans"]) for b in blocks if b["type"] == "para")
    assert "Owner shall receive 72.5% of the rental revenue, and Manager shall receive 27.5%" \
        in words
    assert "the property located at 12 Example Lane, #3, Park City, UT 84060 (hereafter" in words


def test_the_date_line_reads_as_dated_on_skyruns_signature_until_countersigned():
    def opening(day):
        blocks = render.document("rental_management", {}, None, agreement_date=day)
        return next("".join(s["v"] for s in b["spans"]) for b in blocks
                    if b["type"] == "para" and "THIS AGREEMENT" in b["spans"][0]["v"])
    assert "made and entered into on the date of Manager’s signature below, by and" \
        in opening(None)
    assert "made and entered into this 24th day of November, 2026, by and" \
        in opening(date(2026, 11, 24))
    assert "this 1st day of December, 2026" in opening(date(2026, 12, 1))
    assert "this 11th day of" in opening(date(2026, 12, 11))


def test_the_signed_hash_leaves_the_date_out_and_holds_everything_else():
    terms = {"owner_percent": 70, "manager_percent": 30}
    details = {"first_name": "Alex", "last_name": "Sample", "phone": "555-0100"}
    one = render.signed_sha256("rental_management", terms, details)
    assert one == render.signed_sha256("rental_management", dict(terms), dict(details))
    assert one != render.signed_sha256("rental_management", {**terms, "owner_percent": 71,
                                                              "manager_percent": 29}, details)
    assert one != render.signed_sha256("rental_management", terms, {**details, "phone": "555-0101"})
    assert render.UNDATED in render.signed_text("rental_management", terms, details)


# ------------------------------------------------------------ Exhibit A from Sleeps

def _exhibit(details):
    blocks = render.document("rental_management", {}, details)
    start = next(i for i, b in enumerate(blocks) if b.get("text") == "EXHIBIT A")
    return " ".join(render._words_of(b, False) for b in blocks[start:])


@pytest.mark.parametrize("sleeps, p, m", [(1, 8, 4), (2, 8, 4), (5, 8, 6), (6, 12, 6),
                                          (8, 12, 8), (10, 16, 10), (11, 20, 12),
                                          (16, 24, 16)])
def test_the_quantities_follow_sleeps(sleeps, p, m):
    from apps.agreements import exhibit_a

    found = exhibit_a.numbers(sleeps)
    assert (found["place_settings"], found["place_mats"]) == (p, m)
    assert found["dinnerware_pieces"] == 5 * p and found["teaspoons"] == p + 4
    words = _exhibit({"sleeps": str(sleeps)})
    assert f"Dinnerware {p} place settings ({5 * p} pieces) Dinner Plate" in words
    assert f"Flatware {p} place settings Dinner Knife" in words
    assert f"Teaspoons ({p + 4}) Serving Spoons" in words
    for glass in ("Juice", "Wine", "Highball", "Old Fashioned"):
        assert f"{glass} ({p})" in words
    assert f"Place mats (set of {m})" in words
    # Every other line stays as written.
    assert "Humidifier (1 per bedroom)" in words
    assert "Vanity Wastebasket (1 per bathroom)" in words
    assert "Twin White Duvet Insert (1 per bed)" in words
    assert "Studios" not in words and "bedrooms)" not in words


def test_before_sleeps_is_answered_the_numbers_are_a_plain_placeholder():
    words = _exhibit({})
    assert "Dinnerware [from Sleeps] place settings ([from Sleeps] pieces)" in words
    assert "Teaspoons ([from Sleeps])" in words and "Place mats (set of [from Sleeps])" in words


def test_other_features_reads_as_written():
    assert _exhibit({}).endswith(
        "Other Features: After signing, you will be able to list your Unit's amenities and "
        "unique features on the onboarding form, and send any photos you would like us to use "
        "in addition to the ones we take.")


def test_the_rules_are_one_small_table():
    from apps.agreements import exhibit_a

    assert exhibit_a.RULES == {"place_settings": (1.5, 4, 8), "place_mats": (1, 2, 4)}


def test_one_signature_block_per_owner_each_named():
    owners = [{"name": "Alex Sample"}, {"name": "Pat Sample", "title": "Trustee"},
              {"name": "Lee Sample"}]
    words = render.signed_text("rental_management", {}, {}, owners)
    assert words.count("OWNER BY: [Owner signature] Signature DATE: [Owner date]") == 3
    assert ("NAME: Alex Sample OWNER BY: [Owner signature] Signature DATE: [Owner date] "
            "NAME: Pat Sample, Trustee OWNER BY") in words
    assert "NAME: Lee Sample (ALL owners of Unit must sign)" in words
