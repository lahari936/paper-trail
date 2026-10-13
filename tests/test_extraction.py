"""Extraction eval against seed/labels.json. Calls Textract and Bedrock, so it needs AWS credentials and
BEDROCK_EXTRACT_MODEL_ID. Run: uv run pytest tests/test_extraction.py -s
"""

import json
from pathlib import Path

import boto3
import pytest

from ingest.pipeline import run_extraction
from ingest.validate import DATE_FIELDS, quote_on_page
from server.config import BEDROCK_EXTRACT_MODEL_ID

LABELS = json.loads(Path("seed/labels.json").read_text())
SCORED = ("start_date", "end_date", "renewal_date", "notice_days", "amount")  # dates and amounts
TARGET = 0.85

pytestmark = pytest.mark.skipif(
    not BEDROCK_EXTRACT_MODEL_ID or boto3.Session().get_credentials() is None,
    reason="needs AWS credentials and BEDROCK_EXTRACT_MODEL_ID",
)


def _same(expected: str | None, got: dict | None) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    try:
        return float(expected) == float(got["value"])
    except ValueError:
        return expected == str(got["value"])


def test_extraction_accuracy() -> None:
    correct = {f: 0 for f in ("doc_type", *SCORED)}
    ungrounded = []
    for path, label in LABELS.items():
        pages, cls, clean, issues = run_extraction(Path(path))
        correct["doc_type"] += cls.doc_type == label["doc_type"]
        misses = []
        for f in SCORED:
            ok = _same(label[f], clean.get(f))
            correct[f] += ok
            if not ok:
                misses.append(f"{f}: want {label[f]} got {clean[f] and clean[f]['value']}")
        for f in DATE_FIELDS:
            if clean.get(f) and not quote_on_page(clean[f]["source_quote"], clean[f]["page"], pages):
                ungrounded.append(f"{path}:{f}")
        print(f"{path}: {cls.doc_type} ({cls.confidence:.2f}) {'; '.join(misses) or 'all correct'}"
              + (f"  issues={issues}" if issues else ""))

    n = len(LABELS)
    print("\nPer-field accuracy:")
    for f, c in correct.items():
        print(f"  {f:13} {c}/{n}  {c / n:.0%}")
    overall = sum(correct[f] for f in SCORED) / (n * len(SCORED))
    print(f"  dates+amounts {overall:.0%} (target {TARGET:.0%}); ungrounded dates stored: {len(ungrounded)}")

    assert overall >= TARGET
    assert ungrounded == []
