"""MCP tool handler tests against the seeded local DB (docker compose up -d)."""

import uuid

import pytest
from sqlalchemy import select, text

from seed import load
from server import mcp_tools as t
from server.db import Reminder, Session, engine


@pytest.fixture(scope="module", autouse=True)
def seeded() -> None:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres not reachable; run `docker compose up -d`")
    load.main()


def _doc_id(title_part: str) -> str:
    return next(d for d in t._docs() if title_part in d.title).id.hex


def test_coverage_washing_machine() -> None:
    r = t.check_coverage("washing machine")
    assert r["answer"] == "Yes, your LG washing machine warranty runs until March 2027. The motor is covered for ten years."
    assert r["evidence"][0]["page"] == 1


def test_coverage_alias_fridge() -> None:
    assert "Samsung refrigerator warranty runs until May 2028" in t.check_coverage("fridge")["answer"]


def test_coverage_excluded_issue() -> None:
    r = t.check_coverage("laptop", "it got water on it")
    assert r["answer"] == "Probably not. Your Dell laptop accidental-damage plan excludes liquid damage on page 2."
    assert "Liquid damage" in r["evidence"][0]["quote"]


def test_coverage_issue_not_excluded() -> None:
    assert t.check_coverage("laptop", "cracked screen")["answer"].startswith("Yes")


def test_coverage_ambiguous_asks() -> None:
    r = t.check_coverage("insurance")
    assert r["answer"].startswith("I found two:") and r["answer"].endswith("Which one?")


def test_coverage_unknown_item() -> None:
    assert t.check_coverage("treadmill")["answer"].startswith("I couldn't find")


def test_upcoming_deadlines() -> None:
    a = t.list_upcoming_deadlines(30)["answer"]
    assert "car insurance renews" in a and "StreamFlix streaming subscription auto-renews" in a
    assert "electricity" not in a and "lease" not in a  # bill already past, lease notice ~65 days out
    assert "notice on your Maple Residency apartment lease" in t.list_upcoming_deadlines(90)["answer"]


def test_ask_documents_found_and_refused() -> None:
    r = t.ask_documents("What is the deductible on my car insurance?")
    assert "2,000" in r["answer"] and r["evidence"][0]["title"].startswith("Acme")
    assert t.ask_documents("zebra quantum")["answer"] == "I couldn't find that in your documents."


def test_get_document_by_query_and_id() -> None:
    assert "60 days' notice" in t.get_document(query="lease")["answer"]
    assert "Dell laptop" in t.get_document(document_id=_doc_id("Dell"))["answer"]
    assert "doesn't look right" in t.get_document(document_id="nope")["answer"]


def test_set_reminder() -> None:
    doc_id = _doc_id("Acme")
    r = t.set_reminder(document_id=doc_id, days_before=7)
    assert r["answer"].startswith("Done. I'll remind you on") and "a week before your Acme car insurance renews" in r["answer"]
    with Session() as s:
        assert s.scalars(select(Reminder).where(Reminder.document_id == uuid.UUID(doc_id))).one()
    assert "already passed" in t.set_reminder(document_id=doc_id, days_before=60)["answer"]


def test_list_documents() -> None:
    assert t.list_documents()["answer"].startswith("You have eight documents:")
    assert t.list_documents("warranty")["answer"].startswith("You have three warranties:")
