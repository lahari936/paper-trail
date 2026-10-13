from datetime import date
from decimal import Decimal

from ingest.pipeline import chunk, default_reminders
from ingest.validate import dates_in, numbers_in, quote_on_page, validate
from server.db import Document

PAGES = [
    "LG Electronics Warranty Card. Date of purchase: 15 March 2025. Warranty valid until: 14 March 2027.",
    "Exclusions. Liquid damage is excluded. Plan fee: INR 4,999.00. Give two months' (60 days) written notice.",
]


def g(value: str, quote: str, page: int = 1) -> dict:
    return {"value": value, "source_quote": quote, "page": page}


def test_dates_in_formats() -> None:
    assert dates_in("valid until 14 March 2027") == {date(2027, 3, 14)}
    assert date(2028, 5, 31) in dates_in("ends May 31st, 2028")
    assert date(2025, 6, 1) in dates_in("start 2025-06-01")
    assert dates_in("on 05/04/2026") == {date(2026, 4, 5), date(2026, 5, 4)}  # d/m and m/d both read
    assert dates_in("no date here") == set()


def test_numbers_in() -> None:
    assert Decimal("4999") in numbers_in("INR 4,999.00")
    assert Decimal(2) in numbers_in("two months")


def test_quote_on_page_tolerates_ocr_noise() -> None:
    assert quote_on_page("Warranty valid untl: 14 March 2027", 1, PAGES)  # one OCR typo
    assert not quote_on_page("Warranty valid until: 14 March 2027", 2, PAGES)  # wrong page
    assert not quote_on_page("Warranty valid until: 14 March 2027", 9, PAGES)  # page out of range
    assert not quote_on_page(None, 1, PAGES)


def test_validate_keeps_grounded_values() -> None:
    clean, issues = validate(
        {
            "start_date": g("2025-03-15", "Date of purchase: 15 March 2025"),
            "end_date": g("2027-03-14", "Warranty valid until: 14 March 2027"),
            "amount": g("4999.00", "Plan fee: INR 4,999.00", 2),
            "notice_days": g("60", "two months' (60 days) written notice", 2),
            "exclusions": [{"text": "liquid damage", "page": 2, "quote": "Liquid damage is excluded"}],
        },
        PAGES,
    )
    assert issues == {}
    assert clean["end_date"]["value"] == date(2027, 3, 14)
    assert clean["amount"]["value"] == Decimal("4999.00")
    assert clean["notice_days"]["value"] == 60
    assert len(clean["exclusions"]) == 1


def test_validate_nulls_ungrounded_values() -> None:
    clean, issues = validate(
        {
            "start_date": g("2025-03-15", "Date of purchase: 15 March 2025"),
            "end_date": g("2028-03-14", "Warranty valid until: 14 March 2027"),  # value not in quote
            "renewal_date": g("2026-01-01", "Renews on 1 January 2026"),  # quote not on page
            "amount": g("lots", "Plan fee: INR 4,999.00", 2),  # unparseable
            "exclusions": [{"text": "fire", "page": 2, "quote": "Fire damage is excluded"}],
        },
        PAGES,
    )
    assert clean["end_date"] is None and "not stated" in issues["end_date"]
    assert clean["renewal_date"] is None and "not found" in issues["renewal_date"]
    assert clean["amount"] is None and "unparseable" in issues["amount"]
    assert clean["exclusions"] == [] and "exclusions" in issues
    assert clean["start_date"]["value"] == date(2025, 3, 15)


def test_validate_rejects_end_before_start() -> None:
    clean, issues = validate(
        {
            "start_date": g("2027-03-14", "Warranty valid until: 14 March 2027"),
            "end_date": g("2025-03-15", "Date of purchase: 15 March 2025"),
        },
        PAGES,
    )
    assert clean["end_date"] is None and "before" in issues["end_date"]


def test_chunk_keeps_pages_and_overlaps() -> None:
    chunks = chunk(["a" * 7000, "short"])
    assert [p for p, _ in chunks] == [1, 1, 1, 2]
    assert chunks[0][1][-400:] == chunks[1][1][:400]


def test_default_reminders() -> None:
    today = date.today()
    doc = Document(end_date=date.fromordinal(today.toordinal() + 100), notice_days=60)
    kinds = {k for _, k in default_reminders(doc)}
    assert kinds == {"30_days_before", "7_days_before", "7_days_before_notice"}
    assert default_reminders(Document(end_date=date.fromordinal(today.toordinal() + 3))) == []
