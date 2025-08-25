# tools/extract_text.py
from pdfminer.high_level import extract_text
from pathlib import Path
import ujson as json
import re, sys

# If you pass a folder path, it uses that. Otherwise defaults to repo data/books
BOOKS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/books")
OUT = Path("data/book_text.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def main():
    pdfs = sorted(BOOKS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in: {BOOKS_DIR.resolve()}")
        return
    with OUT.open("w", encoding="utf-8") as w:
        for pdf in pdfs:
            text = extract_text(pdf)
            chunks = [c for c in re.split(r"\n{2,}", text) if c.strip()]
            for i, chunk in enumerate(chunks, start=1):
                rec = {
                    "book": pdf.stem,
                    "chapter": f"chunk-{i}",
                    "page": i,  # rough stand-in
                    "text": clean(chunk)[:6000]
                }
                w.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Wrote: {OUT} with text from {len(pdfs)} pdf(s).")

if __name__ == "__main__":
    main()
