"""Scripted Q&A eval for ask_documents: each answer must cite the right document, or refuse when it should.

Needs AWS (Titan embeddings + BEDROCK_QA_MODEL_ID). Seeds the DB and backfills embeddings first.
Run: uv run --env-file .env python -m tests.qa_eval
"""

import sys

from seed import load
from server import mcp_tools, retrieval
from server.config import BEDROCK_QA_MODEL_ID
from server.db import Document, Session

REFUSAL = "I couldn't find that in your documents."
CASES: list[tuple[str, str | None]] = [  # (question, expected source file, or None to expect a refusal)
    ("What's the deductible on my car insurance?", "seed/insurance_car.pdf"),
    ("Who do I call to make a claim on my fridge?", "seed/warranty_samsung.pdf"),
    ("How much notice do I have to give to end my rental agreement?", "seed/lease_maple.pdf"),
    ("How do I cancel StreamFlix?", "seed/subscription_streamflix.pdf"),
    ("How much do I owe on the electricity bill?", "seed/bill_electricity.pdf"),
    ("How long is the washing machine motor covered?", "seed/warranty_lg.pdf"),
    ("What's my health insurance member ID?", "seed/insurance_health.png"),
    ("Am I allowed to keep a pet in my flat?", "seed/lease_maple.pdf"),
    ("What's my home Wi-Fi password?", None),
    ("When is my next dentist appointment?", None),
]


def main() -> int:
    if not BEDROCK_QA_MODEL_ID:
        sys.exit("Set BEDROCK_QA_MODEL_ID (and AWS credentials) first.")
    load.main()
    print(f"Embedded {retrieval.embed_missing()} chunks.\n")
    with Session() as s:
        source_of = {str(d.id): d.s3_key for d in s.query(Document)}

    passed = 0
    for question, expected in CASES:
        r = mcp_tools.ask_documents(question)
        cited = {source_of.get(e["document_id"]) for e in r["evidence"]}
        ok = r["answer"] == REFUSAL if expected is None else (r["answer"] != REFUSAL and expected in cited)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {question}\n      -> {r['answer']}\n      cited: {sorted(map(str, cited))}")
    print(f"\n{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
