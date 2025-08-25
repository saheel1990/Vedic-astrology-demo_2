# tools/extract_text_mupdf.py
from pathlib import Path
import ujson as json
import fitz  # PyMuPDF
import re, sys

ARG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/books")  # folder or a single PDF
OUT = Path("data/book_text.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def extract_pdf(pdf_path: Path):
    with fitz.open(pdf_path) as doc:
        for pno in range(len(doc)):
            page = doc.load_page(pno)
            txt = page.get_text("text")  # plain text layer
            yield pno + 1, clean(txt)

def main():
    if ARG.is_file() and ARG.suffix.lower() == ".pdf":
        pdfs = [ARG]
        base = ARG.parent
    else:
        base = ARG
        pdfs = sorted(base.rglob("*.pdf"))

    print(f"[info] Base: {base.resolve()}")
    print(f"[info] Found {len(pdfs)} PDF(s).")
    if not pdfs:
        print("[warn] No PDFs found.")
        return

    written = 0
    with OUT.open("w", encoding="utf-8") as w:
        for idx, pdf in enumerate(pdfs, start=1):
            try:
                print(f"[{idx}/{len(pdfs)}] {pdf}")
                for page_no, txt in extract_pdf(pdf):
                    # write only if some text found, else still keep a stub for visibility
                    rec = {
                        "book": pdf.stem,
                        "chapter": f"page-{page_no}",
                        "page": page_no,
                        "text": txt[:6000] if txt else ""
                    }
                    w.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    written += 1
            except Exception as e:
                print(f"[error] {pdf}: {e}")
                continue
    print(f"[done] wrote {written} page-chunk(s) -> {OUT.resolve()}")

if __name__ == "__main__":
    main()
