"""Grounding checks: every stored date, amount and notice period must be backed by text on its cited page."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from rapidfuzz import fuzz, utils

QUOTE_MATCH_MIN = 90
DATE_FIELDS = ("start_date", "end_date", "renewal_date")
AMOUNT_FIELDS = ("amount", "deductible", "security_deposit")
INT_FIELDS = ("notice_days",)

_DATE_PATTERNS = [
    r"\d{4}-\d{1,2}-\d{1,2}",
    r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}",
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}",
    r"[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}",
]
_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y",
    "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y",
]
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "twelve": 12}


def quote_on_page(quote: str | None, page: int | None, pages: list[str]) -> bool:
    if not quote or not page or not 1 <= page <= len(pages):
        return False
    return fuzz.partial_ratio(quote, pages[page - 1], processor=utils.default_process) >= QUOTE_MATCH_MIN


def dates_in(text: str) -> set[date]:
    """Every date written in `text`. Ambiguous d/m vs m/d forms yield both readings."""
    found: set[date] = set()
    for pattern in _DATE_PATTERNS:
        for raw in re.findall(pattern, text):
            cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw).replace(",", " ").replace(".", " ")
            cleaned = " ".join(cleaned.split()) if not re.fullmatch(r"[\d/.-]+", raw) else raw
            for fmt in _DATE_FORMATS:
                try:
                    found.add(datetime.strptime(cleaned, fmt).date())
                except ValueError:
                    pass
    return found


def numbers_in(text: str) -> set[Decimal]:
    out = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            out.add(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            pass
    for word, n in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text, re.I):
            out.add(Decimal(n))
    return out


def _parse(field: str, value: str) -> date | Decimal | int:
    if field in DATE_FIELDS:
        return date.fromisoformat(value)
    if field in INT_FIELDS:
        return int(Decimal(value))
    return Decimal(value.replace(",", ""))


def _supported(field: str, parsed: date | Decimal | int, quote: str) -> bool:
    if field in DATE_FIELDS:
        return parsed in dates_in(quote)
    return Decimal(parsed) in numbers_in(quote)


def validate(extraction: dict[str, Any], pages: list[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (cleaned, issues). Ungrounded values become None; `issues` maps field -> reason.

    Cleaned grounded fields become {"value": <date|Decimal|int>, "source_quote", "page"}.
    """
    clean = dict(extraction)
    issues: dict[str, str] = {}

    for field in (*DATE_FIELDS, *AMOUNT_FIELDS, *INT_FIELDS):
        g = clean.get(field)
        if not g or g.get("value") in (None, ""):
            clean[field] = None
            continue
        try:
            parsed = _parse(field, str(g["value"]))
        except (ValueError, InvalidOperation):
            issues[field] = f"unparseable value {g['value']!r}"
        else:
            if not quote_on_page(g.get("source_quote"), g.get("page"), pages):
                issues[field] = "source_quote not found on cited page"
            elif not _supported(field, parsed, g["source_quote"]):
                issues[field] = "value not stated in source_quote"
            else:
                clean[field] = {"value": parsed, "source_quote": g["source_quote"], "page": g["page"]}
                continue
        clean[field] = None

    start, end = clean.get("start_date"), clean.get("end_date")
    if start and end and end["value"] < start["value"]:
        issues["end_date"] = "end_date is before start_date"
        clean["end_date"] = None

    for list_field in ("covered_parts", "exclusions"):
        kept = [c for c in clean.get(list_field, []) if quote_on_page(c.get("quote"), c.get("page"), pages)]
        if len(kept) < len(clean.get(list_field, [])):
            issues[list_field] = f"dropped {len(clean[list_field]) - len(kept)} ungrounded item(s)"
        if list_field in clean:
            clean[list_field] = kept

    return clean, issues
