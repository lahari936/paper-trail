"""grounded_answer citation checks, with the Bedrock call stubbed out."""

from typing import Any

import pytest

from server import retrieval
from server.db import Chunk, Document
from server.retrieval import Hit

HITS = [
    Hit(Document(title="Acme Car Policy"), Chunk(page=1, text="Compulsory deductible: INR 2,000 per claim."), ""),
    Hit(Document(title="Evergreen Health Card"), Chunk(page=1, text="Member ID SYN-HL-880021."), ""),
]


def _stub(monkeypatch: pytest.MonkeyPatch, out: dict[str, Any]) -> None:
    monkeypatch.setattr(retrieval, "converse_tool", lambda *a, **k: out)


def test_keeps_verified_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {"found": True, "answer": "It's 2,000 rupees.", "citations": [
        {"source": 1, "quote": "deductible: INR 2,000 per claim"},
        {"source": 2, "quote": "Member ID SYN-HL-999999"},  # not in source 2
        {"source": 7, "quote": "anything"},  # no such source
    ]})
    answer, cited = retrieval.grounded_answer("deductible?", HITS)
    assert answer == "It's 2,000 rupees."
    assert [h.doc.title for h in cited] == ["Acme Car Policy"]


def test_refuses_without_valid_citation(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {"found": True, "answer": "It's 5,000.", "citations": [{"source": 1, "quote": "INR 5,000"}]})
    assert retrieval.grounded_answer("deductible?", HITS) is None


def test_refuses_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, {"found": False, "answer": "Not stated.", "citations": [{"source": 1, "quote": "deductible"}]})
    assert retrieval.grounded_answer("wifi password?", HITS) is None
    assert retrieval.grounded_answer("anything", []) is None
