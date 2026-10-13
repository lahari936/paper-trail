from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from reminders.handler import run
from seed import load
from server.db import Document, Reminder, Session, engine


@pytest.fixture(autouse=True)
def seeded() -> None:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres not reachable; run `docker compose up -d`")
    load.main()


def test_sends_due_reminders_once() -> None:
    now = datetime.now(UTC)
    with Session.begin() as s:
        car = s.scalars(select(Document).where(Document.title.startswith("Acme"))).one()
        s.add_all([
            Reminder(user_id="demo", document_id=car.id, due_at=now - timedelta(hours=1), kind="custom"),
            Reminder(user_id="demo", document_id=car.id, due_at=now + timedelta(days=3), kind="custom"),
        ])
    outbox: list[tuple[str, str, str]] = []
    send = lambda to, subject, body: outbox.append((to, subject, body))  # noqa: E731

    assert run(send, lambda _user: None) == 0  # no email on file: stays unsent
    assert run(send, lambda _user: "demo@example.com") == 1
    assert outbox[0][0] == "demo@example.com" and "Acme Mutual Private Car Policy Schedule renews" in outbox[0][1]
    assert run(send, lambda _user: "demo@example.com") == 0  # already sent; future one not due
