"""Ingest one document: OCR -> classify -> extract -> validate -> store.

Run: uv run python -m ingest.pipeline seed/warranty_lg.pdf [--dry-run]
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import boto3
import pymupdf
from sqlalchemy import delete

from ingest.prompts import CLASSIFY, EXTRACT, SYSTEM, format_pages
from ingest.schemas import SCHEMAS, Classification
from ingest.validate import AMOUNT_FIELDS, DATE_FIELDS, INT_FIELDS, validate
from server.config import AWS_REGION, BEDROCK_EXTRACT_MODEL_ID, DEMO_USER_ID
from server.db import Chunk, Document, Reminder, Session, init_db

CHUNK_CHARS = 3200  # ~800 tokens
CHUNK_OVERLAP = 400
RENDER_DPI = 200


def _client(service: str) -> Any:
    return boto3.client(service, region_name=AWS_REGION)


def page_images(path: Path) -> list[bytes]:
    """PNG bytes per page. Images pass through; PDFs are rendered page by page."""
    if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return [path.read_bytes()]
    with pymupdf.open(path) as pdf:
        return [page.get_pixmap(dpi=RENDER_DPI).tobytes("png") for page in pdf]


def ocr(path: Path) -> list[str]:
    """Textract AnalyzeDocument (FORMS, TABLES) per page; returns the LINE text of each page."""
    # ponytail: one sync call per page. Avoids the S3 + async job polling that StartDocumentAnalysis needs;
    # switch to async when documents run past ~20 pages.
    textract = _client("textract")
    pages = []
    for image in page_images(path):
        resp = textract.analyze_document(Document={"Bytes": image}, FeatureTypes=["FORMS", "TABLES"])
        pages.append("\n".join(b["Text"] for b in resp["Blocks"] if b["BlockType"] == "LINE"))
    return pages


def _converse_tool(prompt: str, name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Call Bedrock Converse forcing one tool call, and return the tool input (structured output)."""
    if not BEDROCK_EXTRACT_MODEL_ID:
        sys.exit("Set BEDROCK_EXTRACT_MODEL_ID (see `aws bedrock list-inference-profiles`).")
    resp = _client("bedrock-runtime").converse(
        modelId=BEDROCK_EXTRACT_MODEL_ID,
        system=[{"text": SYSTEM}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 4096},
        toolConfig={
            "tools": [{"toolSpec": {"name": name, "inputSchema": {"json": schema}}}],
            "toolChoice": {"tool": {"name": name}},
        },
    )
    return next(c["toolUse"]["input"] for c in resp["output"]["message"]["content"] if "toolUse" in c)


def classify(pages: list[str]) -> Classification:
    data = _converse_tool(CLASSIFY.format(pages=format_pages(pages)), "classify", Classification.model_json_schema())
    return Classification.model_validate(data)


def extract(pages: list[str], doc_type: str) -> dict[str, Any]:
    schema = SCHEMAS[doc_type]
    prompt = EXTRACT.format(doc_type=doc_type, hints=schema.__doc__ or "", pages=format_pages(pages))
    data = _converse_tool(prompt, f"record_{doc_type}", schema.model_json_schema())
    return schema.model_validate(data).model_dump()


def chunk(pages: list[str]) -> list[tuple[int, str]]:
    out = []
    for page_no, text in enumerate(pages, start=1):
        for start in range(0, max(len(text), 1), CHUNK_CHARS - CHUNK_OVERLAP):
            out.append((page_no, text[start : start + CHUNK_CHARS]))
            if start + CHUNK_CHARS >= len(text):
                break
    return out


def default_reminders(doc: Document) -> list[tuple[date, str]]:
    """30 and 7 days before the renewal/end date, and 7 days before the notice deadline; future dates only."""
    target = doc.renewal_date or doc.end_date
    if not target:
        return []
    due = [(target - timedelta(days=30), "30_days_before"), (target - timedelta(days=7), "7_days_before")]
    if doc.notice_days:
        due.append((target - timedelta(days=doc.notice_days + 7), "7_days_before_notice"))
    return [(d, kind) for d, kind in due if d >= date.today()]


def to_document(clean: dict[str, Any], issues: dict[str, str], doc_type: str, source: str) -> Document:
    def value(field: str) -> Any:
        return clean[field]["value"] if clean.get(field) else None

    grounded = (*DATE_FIELDS, *AMOUNT_FIELDS, *INT_FIELDS)
    columns = {"title", "vendor", "item_name", "item_category", "currency", "auto_renews"}
    fields: dict[str, Any] = {k: v for k, v in clean.items() if k not in columns and k not in grounded}
    fields["evidence"] = {f: {"page": clean[f]["page"], "quote": clean[f]["source_quote"]} for f in grounded if clean.get(f)}
    for f in ("deductible", "security_deposit"):
        if clean.get(f):
            fields[f] = str(clean[f]["value"])
    fields["validation_issues"] = issues
    return Document(
        user_id=DEMO_USER_ID, doc_type=doc_type, s3_key=source,
        **{c: clean.get(c) for c in columns},
        start_date=value("start_date"), end_date=value("end_date"), renewal_date=value("renewal_date"),
        notice_days=value("notice_days"), amount=value("amount"),
        fields=fields, status="needs_review" if issues else "ready",
    )


def run_extraction(path: Path) -> tuple[list[str], Classification, dict[str, Any], dict[str, str]]:
    pages = ocr(path)
    cls = classify(pages)
    clean, issues = validate(extract(pages, cls.doc_type), pages)
    return pages, cls, clean, issues


def store(path: Path, pages: list[str], doc_type: str, clean: dict[str, Any], issues: dict[str, str]) -> Document:
    """Insert the document, its chunks and default reminders. Replaces an earlier ingest of the same source."""
    source = path.as_posix()
    init_db()
    with Session.begin() as s:
        s.execute(delete(Document).where(Document.user_id == DEMO_USER_ID, Document.s3_key == source))
        doc = to_document(clean, issues, doc_type, source)
        s.add(doc)
        s.flush()
        s.add_all(Chunk(document_id=doc.id, page=p, text=t) for p, t in chunk(pages))
        s.add_all(
            Reminder(user_id=DEMO_USER_ID, document_id=doc.id, due_at=datetime.combine(d, time(9), UTC), kind=k)
            for d, k in default_reminders(doc)
        )
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print the validated extraction without storing it")
    args = parser.parse_args()

    pages, cls, clean, issues = run_extraction(args.path)
    print(json.dumps({"doc_type": cls.doc_type, "confidence": cls.confidence, "fields": clean, "issues": issues},
                     indent=2, default=str))
    if not args.dry_run:
        doc = store(args.path, pages, cls.doc_type, clean, issues)
        print(f"Stored {doc.id} ({doc.status}).")


if __name__ == "__main__":
    main()
