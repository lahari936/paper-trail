"""PaperTrail MCP tools. Every tool returns {answer, evidence, followups}; Alexa+ speaks `answer`."""

import math
import re
import uuid
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from rapidfuzz import fuzz, utils
from sqlalchemy import select

from server.config import DEMO_USER_ID
from server.db import Chunk, Document, Reminder, Session

DocType = Literal["warranty", "insurance", "lease", "subscription", "bill", "other"]
Result = dict[str, Any]

mcp = MCPServer(
    "PaperTrail",
    instructions="Answers questions about the user's household documents: warranties, insurance, leases, "
    "subscriptions and bills. Speak the `answer` field; `evidence` cites the source page.",
)

MATCH_THRESHOLD = 85
TIE_MARGIN = 5
PLURALS = {
    "warranty": "warranties",
    "insurance": "insurance policies",
    "lease": "leases",
    "subscription": "subscriptions",
    "bill": "bills",
    "other": "other documents",
}
SINGULARS = {"insurance": "insurance policy", "other": "other document"}
NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]

# ponytail: keyword synonyms for exclusion matching; Phase 3 hands this to the Q&A model.
ISSUE_SYNONYMS = {
    "water": "liquid", "wet": "liquid", "spill": "liquid", "spilled": "liquid", "coffee": "liquid",
    "juice": "liquid", "rain": "liquid", "flood": "liquid", "dropped": "drop", "fell": "drop",
    "cracked": "crack", "scratch": "cosmetic", "scratched": "cosmetic", "dent": "cosmetic",
    "stolen": "theft", "lost": "loss",
}
STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "from", "how", "i", "in", "is", "it", "me", "much", "my",
    "of", "on", "or", "say", "says", "the", "to", "what", "when", "where", "which", "who", "will", "with",
}
GENERIC_WORDS = {"damage", "damaged", "the", "and", "for", "from", "caused", "with", "got", "has", "was", "its", "it", "on"}


# ---------- helpers ----------

def _user() -> str:
    return DEMO_USER_ID  # Phase 4: user id from the validated Cognito token


def _number(n: int) -> str:
    return NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else str(n)


def _month_year(d: date) -> str:
    return d.strftime("%B %Y")


def _day(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}" + (f", {d.year}" if d.year != date.today().year else "")


def _name(doc: Document) -> str:
    """Spoken name, e.g. 'LG washing machine warranty'."""
    noun = doc.fields.get("plan_name") or doc.doc_type
    return " ".join(p for p in (doc.vendor, doc.item_name, noun) if p)


def _result(answer: str, evidence: list[Result] | None = None, followups: list[str] | None = None) -> Result:
    return {"answer": answer, "evidence": evidence or [], "followups": followups or []}


def _cite(doc: Document, page: int, quote: str) -> Result:
    return {"document_id": str(doc.id), "title": doc.title, "page": page, "quote": quote}


def _field_evidence(doc: Document, *names: str) -> list[Result]:
    ev = doc.fields.get("evidence", {})
    return [_cite(doc, ev[n]["page"], ev[n]["quote"]) for n in names if n in ev]


def _docs(doc_types: tuple[str, ...] | None = None) -> list[Document]:
    stmt = select(Document).where(Document.user_id == _user()).order_by(Document.title)
    if doc_types:
        stmt = stmt.where(Document.doc_type.in_(doc_types))
    with Session() as s:
        return list(s.scalars(stmt))


def _score(query: str, doc: Document) -> float:
    names = [doc.doc_type, doc.item_name, doc.item_category, doc.vendor, doc.title, *doc.fields.get("aliases", [])]
    return max(fuzz.token_set_ratio(query, n, processor=utils.default_process) for n in names if n)


def _resolve(query: str, doc_types: tuple[str, ...] | None = None) -> tuple[Document | None, list[Document]]:
    """Return (match, []) for one clear match, (None, candidates) when ambiguous, (None, []) for none."""
    scored = sorted(((_score(query, d), d) for d in _docs(doc_types)), key=lambda x: -x[0])
    scored = [(sc, d) for sc, d in scored if sc >= MATCH_THRESHOLD]
    if not scored:
        return None, []
    close = [d for sc, d in scored if sc >= scored[0][0] - TIE_MARGIN]
    return (close[0], []) if len(close) == 1 else (None, close)


def _which_one(candidates: list[Document]) -> Result:
    names = [f"your {_name(d)}" for d in candidates]
    listed = ", ".join(names[:-1]) + f" and {names[-1]}"
    return _result(
        f"I found {_number(len(candidates))}: {listed}. Which one?",
        [_cite(d, 1, d.title) for d in candidates],
        [f"The {d.item_name or d.title}" for d in candidates],
    )


def _doc_by_id_or_query(document_id: str | None, query: str | None) -> tuple[Document | None, Result | None]:
    """Resolve a document, or return the Result to send back instead."""
    if document_id:
        try:
            doc_uuid = uuid.UUID(document_id)
        except ValueError:
            return None, _result("That document ID doesn't look right.")
        with Session() as s:
            doc = s.get(Document, doc_uuid)
        if doc and doc.user_id == _user():
            return doc, None
        return None, _result("I couldn't find that document.")
    if not query:
        return None, _result("Which document do you mean?")
    doc, candidates = _resolve(query)
    if candidates:
        return None, _which_one(candidates)
    if not doc:
        return None, _result(f"I couldn't find a document about {query}.", followups=["What documents do I have?"])
    return doc, None


def _terms(s: str) -> set[str]:
    """Lowercase keywords with a crude plural strip, for ask_documents ranking."""
    return {w.removesuffix("s") if len(w) > 3 else w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOPWORDS}


def _tokens(s: str) -> set[str]:
    words = re.findall(r"[a-z]+", s.lower())
    return {ISSUE_SYNONYMS.get(w, w) for w in words if len(w) > 2 and w not in GENERIC_WORDS}


# ---------- tools ----------

@mcp.tool()
def check_coverage(item: str, issue: str | None = None) -> Result:
    """Use when the user asks whether a product, appliance, vehicle or person is still under warranty, covered,
    or insured, optionally for a specific problem ("my laptop got water on it, is that covered?").
    `item` is the thing (e.g. "washing machine", "laptop", "car"); `issue` is the problem, if any."""
    doc, candidates = _resolve(item, ("warranty", "insurance"))
    if candidates:
        return _which_one(candidates)
    if not doc:
        return _result(
            f"I couldn't find a warranty or policy for your {item}.",
            followups=["What documents do I have?"],
        )

    name = _name(doc)
    evidence = _field_evidence(doc, "end_date")
    today = date.today()
    if doc.end_date and doc.end_date < today:
        return _result(f"No, your {name} ended on {_day(doc.end_date)}.", evidence)

    if issue:
        issue_tokens = _tokens(issue)
        for ex in doc.fields.get("exclusions", []):
            if issue_tokens & _tokens(ex["text"]):
                return _result(
                    f"Probably not. Your {name} excludes {ex['text']} on page {ex['page']}.",
                    [_cite(doc, ex["page"], ex["quote"]), *evidence],
                    ["What does it cover?", "Who do I contact for a claim?"],
                )

    until = f" runs until {_month_year(doc.end_date)}" if doc.end_date else " is active"
    answer = f"Yes, your {name}{until}."
    if issue:
        answer += " I didn't see an exclusion for that, but check with the provider before you claim."
    if doc.start_date and doc.end_date:
        for part in doc.fields.get("covered_parts", []):
            years = part.get("term_years")
            if years and years * 365.25 > (doc.end_date - doc.start_date).days:
                answer += f" The {part['part']} is covered for {_number(years)} years."
                evidence.append(_cite(doc, part["page"], part["quote"]))
                break
    return _result(answer, evidence, ["Remind me before it expires", "Who do I contact for a claim?"])


@mcp.tool()
def list_upcoming_deadlines(days: int = 30) -> Result:
    """Use when the user asks what's coming up, due, renewing, expiring or ending soon ("what's coming up
    in the next month?"). Covers renewals, auto-renewals, expiries, bill due dates and the last day to give notice.
    `days` is how far ahead to look."""
    today = date.today()
    horizon = today + timedelta(days=days)
    events: list[tuple[date, str, Document, str]] = []
    for doc in _docs():
        name = _name(doc)
        if doc.renewal_date:
            verb = "auto-renews" if doc.auto_renews else "renews"
            events.append((doc.renewal_date, f"your {name} {verb} on", doc, "renewal_date"))
        if doc.end_date and doc.end_date != doc.renewal_date:
            verb = "is due on" if doc.doc_type == "bill" else "ends on"
            events.append((doc.end_date, f"your {name} {verb}", doc, "end_date"))
        target = doc.renewal_date or doc.end_date
        if doc.notice_days and target:
            notice_by = target - timedelta(days=doc.notice_days)
            events.append((notice_by, f"the last day to give notice on your {name} is", doc, "notice_days"))

    upcoming = sorted((e for e in events if today <= e[0] <= horizon), key=lambda e: e[0])
    if not upcoming:
        return _result(f"Nothing is due in the next {days} days.")
    phrases = [f"{text_} {_day(d)}" for d, text_, _, _ in upcoming]
    joined = phrases[0] if len(phrases) == 1 else ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
    evidence = [ev for _, _, doc, field in upcoming for ev in _field_evidence(doc, field)]
    return _result(
        f"In the next {days} days, {joined}.",
        evidence,
        [f"Remind me a week before my {_name(upcoming[0][2])} date"],
    )


@mcp.tool()
def ask_documents(question: str, doc_type: DocType | None = None) -> Result:
    """Use for any other question about what the user's documents say: deductibles, claim contacts, policy
    numbers, terms, notice clauses, amounts ("what's my car insurance deductible?"). Optionally filter by
    `doc_type`. Answers only from the documents and says so when the answer isn't there."""
    # ponytail: scans every chunk of the user's and ranks sentences by IDF-weighted keyword overlap. Fine for a
    # household's few dozen documents; Phase 3 swaps in hybrid vector retrieval and a Haiku answer.
    query_terms = _terms(question)
    stmt = select(Chunk, Document).join(Document).where(Document.user_id == _user())
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    with Session() as s:
        sentences = [
            (doc, chunk.page, sent)
            for chunk, doc in s.execute(stmt)
            for sent in re.split(r"(?<=[.!?])\s+", chunk.text)
        ]
    sentence_terms = [_terms(sent) for _, _, sent in sentences]
    df = Counter(t for terms in sentence_terms for t in terms)
    scored = sorted(
        (
            (sum(math.log(len(sentences) / df[t]) for t in query_terms & terms), i)
            for i, terms in enumerate(sentence_terms)
            if query_terms & terms
        ),
        reverse=True,
    )
    if not scored:
        return _result("I couldn't find that in your documents.", followups=["What documents do I have?"])
    hits = [sentences[i] for _, i in scored[:3]]
    doc, page, quote = hits[0]
    return _result(f"Your {_name(doc)} says, on page {page}: {quote}", [_cite(d, p, q) for d, p, q in hits])


@mcp.tool()
def get_document(document_id: str | None = None, query: str | None = None) -> Result:
    """Use when the user asks for a summary or the details of one specific document ("tell me about my lease").
    Pass `document_id` if known from earlier evidence, otherwise a `query` naming the document."""
    doc, reply = _doc_by_id_or_query(document_id, query)
    if not doc:
        return reply  # type: ignore[return-value]
    parts = [f"Your {_name(doc)}" + (f" is with {doc.vendor}." if doc.vendor else ".")]
    if doc.start_date and doc.end_date:
        parts.append(f"It runs from {_day(doc.start_date)} to {_day(doc.end_date)}.")
    elif doc.end_date:
        parts.append(f"It ends on {_day(doc.end_date)}.")
    if doc.renewal_date:
        parts.append(f"It {'auto-renews' if doc.auto_renews else 'renews'} on {_day(doc.renewal_date)}.")
    if doc.notice_days:
        parts.append(f"You need to give {doc.notice_days} days' notice.")
    if doc.amount is not None:
        parts.append(f"The amount is {doc.amount:,.2f} {doc.currency or ''}".rstrip() + ".")
    evidence = _field_evidence(doc, *doc.fields.get("evidence", {}).keys())
    return _result(" ".join(parts), evidence, ["Remind me before it renews"])


@mcp.tool()
def set_reminder(document_id: str | None = None, days_before: int = 7, query: str | None = None) -> Result:
    """Use when the user asks to be reminded before a document renews, expires or is due ("remind me a week
    before the insurance renews"). Pass `document_id` from earlier evidence when possible, otherwise `query`.
    `days_before` is how many days ahead of the renewal or end date to remind."""
    doc, reply = _doc_by_id_or_query(document_id, query)
    if not doc:
        return reply  # type: ignore[return-value]
    target = doc.renewal_date or doc.end_date
    if not target:
        return _result(f"Your {_name(doc)} doesn't have a renewal or end date to remind you about.")
    due = target - timedelta(days=days_before)
    if due < date.today():
        return _result(f"That would be {_day(due)}, which has already passed. Your {_name(doc)} date is {_day(target)}.")
    with Session.begin() as s:
        # ponytail: fixed 09:00 UTC send time; per-user timezone when reminders go multi-region.
        s.add(Reminder(user_id=_user(), document_id=doc.id, due_at=datetime.combine(due, time(9), UTC), kind="custom"))
    lead = "a week" if days_before == 7 else f"{_number(days_before)} day{'s' if days_before != 1 else ''}"
    event = "renews" if doc.renewal_date else ("is due" if doc.doc_type == "bill" else "ends")
    return _result(
        f"Done. I'll remind you on {_day(due)}, {lead} before your {_name(doc)} {event}.",
        _field_evidence(doc, "renewal_date" if doc.renewal_date else "end_date"),
    )


@mcp.tool()
def list_documents(doc_type: DocType | None = None) -> Result:
    """Use when the user asks what documents they have, or for an overview of their warranties, policies,
    leases, subscriptions or bills ("what warranties do I have?")."""
    docs = _docs((doc_type,) if doc_type else None)
    if not docs:
        return _result(f"You don't have any {PLURALS[doc_type] if doc_type else 'documents'} yet.")
    if doc_type:
        names = [_name(d) for d in docs]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
        answer = f"You have {_number(len(docs))} {PLURALS[doc_type] if len(docs) > 1 else SINGULARS.get(doc_type, doc_type)}: {listed}."
    else:
        counts: dict[str, int] = {}
        for d in docs:
            counts[d.doc_type] = counts.get(d.doc_type, 0) + 1
        groups = [f"{_number(n)} {PLURALS[t] if n > 1 else SINGULARS.get(t, t)}" for t, n in counts.items()]
        listed = groups[0] if len(groups) == 1 else ", ".join(groups[:-1]) + f" and {groups[-1]}"
        answer = f"You have {_number(len(docs))} documents: {listed}."
    return _result(answer, [_cite(d, 1, d.title) for d in docs], ["What's coming up this month?"])
