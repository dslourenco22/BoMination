"""
Dump what the extraction pipeline actually sees, straight off an OCR'd PDF. (LD)

Purpose: tell us whether garbled/interleaved text originates in the OCR text
layer or is produced downstream by the local LLM. Run it against the _ocr.pdf
that BOM_KEEP_OCR leaves behind:

    python debug_ocr_text.py "C:\\path\\to\\..._ocr.pdf"

If the output here is clean, extraction is fine and the LLM is mangling it.
If the output here is already interleaved, the problem is the OCR text layer.
"""
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).parent / "src"))
from pipeline.extract_main import _group_words_into_lines, _page_text_by_rows


def dump(pdf_path, page_no=0):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_no]
        print(f"page {page_no + 1}/{len(pdf.pages)}  "
              f"size={page.width:.0f}x{page.height:.0f}")

        words = page.extract_words()
        chars = page.chars
        print(f"words={len(words)}  chars={len(chars)}")

        # 1. Is any text superimposed? Two chars at the same spot means the
        #    text layer itself is doubled, which no parser can untangle.
        seen, dupes = {}, 0
        for c in chars:
            key = (round(c["x0"], 1), round(c["top"], 1))
            if key in seen and seen[key] != c["text"]:
                dupes += 1
                if dupes <= 10:
                    print(f"  OVERLAP at x={key[0]} top={key[1]}: "
                          f"{seen[key]!r} vs {c['text']!r}")
            seen[key] = c["text"]
        print(f"overlapping chars: {dupes}")

        # 2. OLD grouping: the fixed round(top / 3.0) grid.
        print("\n--- OLD row grid, first 25 rows ---")
        rows = {}
        for w in words:
            rows.setdefault(round(w["top"] / 3.0), []).append(w)
        for _, ws in sorted(rows.items())[:25]:
            line = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))
            print(f"  {line[:160]}")

        # 3. NEW grouping: overlap-based clustering, same code the pipeline uses.
        print("\n--- NEW row clustering, first 25 rows ---")
        for row in _group_words_into_lines(words)[:25]:
            print(f"  {' '.join(w['text'] for w in row)[:160]}")

        # 4. Old vs new text for the LLM.
        print("\n--- OLD extract_text(layout=True), first 15 non-blank ---")
        txt = page.extract_text(layout=True) or ""
        for line in [l for l in txt.split("\n") if l.strip()][:15]:
            print(f"  {line[:160]}")

        print("\n--- NEW _page_text_by_rows, first 15 non-blank ---")
        new_txt = _page_text_by_rows(page)
        for line in [l for l in new_txt.split("\n") if l.strip()][:15]:
            print(f"  {line[:160]}")
        print(f"\nchars: layout=True {len(txt)} -> row-based {len(new_txt)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(f"usage: python {Path(__file__).name} <path-to-ocr.pdf> [page]")
    dump(sys.argv[1], int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 0)
