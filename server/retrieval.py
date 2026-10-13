"""Hybrid retrieval over a user's chunks, and grounded answers with citations.

Backfill embeddings for chunks that lack them (e.g. after seed.load): uv run python -m server.retrieval
"""

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz, utils
from sqlalchemy import select

from ingest.validate import QUOTE_MATCH_MIN
from server.bedrock import converse_tool, embed
from server.config import BEDROCK_QA_MODEL_ID
from server.db import Chunk, Document, Session

TOP_K = 6
STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "from", "how", "i", "in", "is", "it", "me", "much", "my",
    "of", "on", "or", "say", "says", "the", "to", "what", "when", "where", "which", "who", "will", "with",
}
QA_SYSTEM = (
    "You answer questions about a household's documents for a voice assistant, using only the numbered sources. "
    "If the sources don't answer the question, set found to false. Never use outside knowledge or guess."
)
QA_PROMPT = """Question: {question}

Sources:
{sources}

Answer in one or two short spoken sentences (no lists, no markdown) and name the document naturally,
e.g. "Your car insurance deductible is 2,000 rupees per claim." Cite every source you used with a quote
copied verbatim from it."""
QA_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean", "description": "true only if the sources answer the question"},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "integer"}, "quote": {"type": "string"}},
                "required": ["source", "quote"],
            },
        },
    },
    "required": ["found", "answer", "citations"],
}


@dataclass
class Hit:
    doc: Document
    chunk: Chunk
    quote: str  # best sentence (keyword hits) or chunk text (vector hits)


def _filtered(stmt, user_id: str, doc_type: str | None, doc_ids: list[uuid.UUID] | None):  # type: ignore[no-untyped-def]
    stmt = stmt.join(Document).where(Document.user_id == user_id)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if doc_ids:
        stmt = stmt.where(Document.id.in_(doc_ids))
    return stmt


def terms(s: str) -> set[str]:
    """Lowercase keywords with a crude plural strip."""
    return {w.removesuffix("s") if len(w) > 3 else w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOPWORDS}


def keyword_search(question: str, user_id: str, doc_type: str | None = None,
                   doc_ids: list[uuid.UUID] | None = None, k: int = 3) -> list[Hit]:
    """Sentences ranked by IDF-weighted keyword overlap. Catches exact terms (policy numbers, names) embeddings miss."""
    # ponytail: scans every chunk of the user's; fine for a household's few dozen documents.
    query_terms = terms(question)
    with Session() as s:
        sentences = [
            (doc, chunk, sent)
            for chunk, doc in s.execute(_filtered(select(Chunk, Document), user_id, doc_type, doc_ids))
            for sent in re.split(r"(?<=[.!?])\s+", chunk.text)
        ]
    sentence_terms = [terms(sent) for _, _, sent in sentences]
    df = Counter(t for ts in sentence_terms for t in ts)
    scored = sorted(
        ((sum(math.log(len(sentences) / df[t]) for t in query_terms & ts), i)
         for i, ts in enumerate(sentence_terms) if query_terms & ts),
        reverse=True,
    )
    return [Hit(*sentences[i]) for _, i in scored[:k]]


def vector_search(question: str, user_id: str, doc_type: str | None = None,
                  doc_ids: list[uuid.UUID] | None = None, k: int = TOP_K) -> list[Hit]:
    query = embed(question)
    stmt = _filtered(select(Chunk, Document), user_id, doc_type, doc_ids).where(Chunk.embedding.is_not(None))
    stmt = stmt.order_by(Chunk.embedding.cosine_distance(query)).limit(k)
    with Session() as s:
        return [Hit(doc, chunk, chunk.text) for chunk, doc in s.execute(stmt)]


def hybrid_search(question: str, user_id: str, doc_type: str | None = None,
                  doc_ids: list[uuid.UUID] | None = None) -> list[Hit]:
    """Vector top-k plus the chunks behind the best keyword sentences, deduplicated."""
    hits, seen = [], set()
    for hit in vector_search(question, user_id, doc_type, doc_ids) + keyword_search(question, user_id, doc_type, doc_ids):
        if hit.chunk.id not in seen:
            seen.add(hit.chunk.id)
            hits.append(hit)
    return hits


def grounded_answer(question: str, hits: list[Hit]) -> tuple[str, list[Hit]] | None:
    """Ask the Q&A model; return (answer, cited hits), or None unless at least one citation checks out."""
    if not hits:
        return None
    sources = "\n\n".join(
        f"[{i}] {h.doc.title} (page {h.chunk.page}):\n{h.chunk.text}" for i, h in enumerate(hits, start=1)
    )
    out = converse_tool(BEDROCK_QA_MODEL_ID, QA_SYSTEM, QA_PROMPT.format(question=question, sources=sources),
                        "answer", QA_SCHEMA)
    cited = []
    for c in out.get("citations", []):
        n, quote = c.get("source"), c.get("quote", "")
        if isinstance(n, int) and 1 <= n <= len(hits) and quote and \
                fuzz.partial_ratio(quote, hits[n - 1].chunk.text, processor=utils.default_process) >= QUOTE_MATCH_MIN:
            cited.append(Hit(hits[n - 1].doc, hits[n - 1].chunk, quote))
    if not out.get("found") or not cited:
        return None
    return out["answer"], cited


def embed_missing() -> int:
    with Session.begin() as s:
        chunks = list(s.scalars(select(Chunk).where(Chunk.embedding.is_(None))))
        for c in chunks:
            c.embedding = embed(c.text)
    return len(chunks)


if __name__ == "__main__":
    print(f"Embedded {embed_missing()} chunks.")
