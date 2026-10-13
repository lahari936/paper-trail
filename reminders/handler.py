"""Daily reminder job: email every due, unsent reminder via SES, then mark it sent.

Runs as a scheduled ECS task (same image as the server): python -m reminders.handler
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from server.bedrock import client
from server.config import COGNITO_USER_POOL_ID, SES_FROM
from server.db import Document, Reminder, Session

Sender = Callable[[str, str, str], None]  # (to, subject, body)


def email_for(user_id: str) -> str | None:
    """The verified email of the Cognito user whose `sub` is user_id."""
    if not COGNITO_USER_POOL_ID:
        return None
    users = client("cognito-idp").list_users(UserPoolId=COGNITO_USER_POOL_ID, Filter=f'sub = "{user_id}"', Limit=1)
    attrs = {a["Name"]: a["Value"] for u in users["Users"] for a in u["Attributes"]}
    return attrs.get("email") if attrs.get("email_verified") == "true" else None


def ses_send(to: str, subject: str, body: str) -> None:
    client("ses").send_email(
        Source=SES_FROM, Destination={"ToAddresses": [to]},
        Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
    )


def message(doc: Document) -> tuple[str, str]:
    target = doc.renewal_date or doc.end_date
    event = "renews" if doc.renewal_date else ("is due" if doc.doc_type == "bill" else "ends")
    subject = f"Reminder: {doc.title} {event} on {target:%d %B %Y}"
    lines = [f"Your {doc.title} {event} on {target:%A, %d %B %Y}."]
    if doc.notice_days:
        lines.append(f"It needs {doc.notice_days} days' notice to cancel or not renew.")
    lines.append("\nAsk PaperTrail on Alexa for details.")
    return subject, "\n".join(lines)


def run(send: Sender = ses_send, lookup: Callable[[str], str | None] = email_for) -> int:
    now = datetime.now(UTC)
    sent = 0
    with Session.begin() as s:
        due = s.execute(
            select(Reminder, Document).join(Document, Document.id == Reminder.document_id)
            .where(Reminder.due_at <= now, Reminder.sent.is_(False))
        ).all()
        for reminder, doc in due:
            to = lookup(reminder.user_id)
            if not to:
                continue  # no verified email: leave unsent so a later run can retry
            send(to, *message(doc))
            reminder.sent = True
            sent += 1
    return sent


if __name__ == "__main__":
    print(f"Sent {run()} reminder(s).")
