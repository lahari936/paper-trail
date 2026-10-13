SYSTEM = (
    "You read household documents (warranties, insurance policies, leases, subscriptions, bills) from OCR text "
    "and record facts exactly as written. Never guess: if a value is not stated, leave it null. "
    "For every date, amount and notice period, copy the exact source text into source_quote and give its page."
)

CLASSIFY = """Classify this document.
warranty: product warranties, extended warranties, protection or accidental-damage plans.
insurance: insurance policies, schedules and cards (car, health, home).
lease: rental or lease agreements. subscription: recurring services. bill: utility or service bills.
other: anything else.

{pages}"""

EXTRACT = """Extract the fields for this {doc_type} document. {hints}
Dates must be YYYY-MM-DD. source_quote must be copied verbatim from the page text, short (one line).

{pages}"""


def format_pages(pages: list[str]) -> str:
    return "\n\n".join(f"<page number=\"{i}\">\n{text}\n</page>" for i, text in enumerate(pages, start=1))
