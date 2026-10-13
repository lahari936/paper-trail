"""Render the synthetic seed documents to PDF/PNG and write seed/labels.json (ground truth for the eval).

Run: uv run python -m seed.make_docs

Some dates are relative to the day this runs, so files and labels are regenerated together.
"""

import json
from datetime import date
from pathlib import Path

import pymupdf

from seed.load import seed_documents

SEED_DIR = Path(__file__).parent
LABEL_FIELDS = ("doc_type", "start_date", "end_date", "renewal_date", "notice_days", "amount")


def render(title: str, pages: list[str]) -> pymupdf.Document:
    pdf = pymupdf.open()
    for i, text in enumerate(pages):
        page = pdf.new_page(width=595, height=842)  # A4
        if i == 0:
            page.insert_text((50, 70), title, fontsize=16, fontname="helv")
        page.insert_textbox(pymupdf.Rect(50, 100, 545, 790), text, fontsize=11, fontname="helv")
        page.insert_text((50, 815), f"Page {i + 1} of {len(pages)}  ·  SYNTHETIC SAMPLE, NOT A REAL DOCUMENT",
                         fontsize=8, fontname="helv")
    return pdf


def main() -> None:
    labels = {}
    for item in seed_documents(date.today()):
        doc, path = item["doc"], Path(item["doc"]["s3_key"])
        pdf = render(doc["title"], item["pages"])
        if path.suffix == ".png":
            pdf[0].get_pixmap(dpi=150).save(path)
        else:
            pdf.save(path)
        labels[path.as_posix()] = {f: None if doc.get(f) is None else str(doc[f]) for f in LABEL_FIELDS}
        print(f"wrote {path}")
    (SEED_DIR / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    print(f"wrote {SEED_DIR / 'labels.json'}")


if __name__ == "__main__":
    main()
