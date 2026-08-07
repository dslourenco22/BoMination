"""
LLM-powered BOM extraction using Ollama + pdfplumber. (LD)
Replaces legacy Tabula/Camelot pipeline entirely. (LD)
"""

import os
import sys
import json
import re
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

# ── Ollama model config ─────────────────────────────────────────────────────── (LD)
MODEL = os.environ.get('BOM_LLM_MODEL', 'llama3.2')
OLLAMA_HOST = os.environ.get('BOM_LLM_ENDPOINT', 'http://127.0.0.1:11434')

# ── BOM extraction prompt ────────────────────────────────────────────────────── (LD)
EXTRACTION_PROMPT = """You are a BOM (Bill of Materials) extraction specialist.

TASK: Find the Bill of Materials table in the text below and extract every row.

Return ONLY this JSON — no explanation, no markdown fences:
{{
  "found": true,
  "headers": ["exact column name 1", "exact column name 2"],
  "rows": [
    ["value1", "value2"],
    ["value1", "value2"]
  ]
}}

If no BOM table is present return ONLY:
{{"found": false, "headers": [], "rows": []}}

RULES:
- HEADERS: Copy the column headers EXACTLY as they appear in this document's table. Read them off the actual header row. Do NOT invent headers, and do NOT reuse the placeholder names shown in the example below — those are only there to demonstrate formatting.
- COLUMN COUNT: Output one value per column for EVERY column in the document's header row. If the table has 7 columns, every row must have 7 values. Never drop or merge columns.
- TWO-COLUMN LAYOUT: If the page has two BOM tables side-by-side with the same columns, treat them as ONE continuous table. Extract all rows from the LEFT side first, then all rows from the RIGHT side. Use the headers from the left side only.
- Extract ONLY rows that are part of the BOM table — ignore page headers, footers, legal text, disclaimers, notes, signature blocks, revision history, and any text that appears outside the table boundaries
- Include EVERY valid BOM data row — do not skip or summarize
- Preserve the exact row order as they appear in the document — do not reorder, sort, or group rows
- BLANK CELLS: If a cell is blank or empty, use "" for that position. NEVER shift the remaining values left to fill the gap. Every row must have exactly the same number of values as the headers list, with "" in every blank position.
- COMBINED FIELDS: If a column contains a combined value like "MANUFACTURER / PART_NUMBER", keep the full value intact as one string — do not split it across columns.
- MULTI-LINE CELLS: If a description or other value wraps onto the next line (with no new item identifier), that continuation belongs to the current row — append it to that cell's value. Do not create a new row for wrapped text.

FORMATTING EXAMPLE (placeholder names — DO NOT copy these headers; use the document's real ones):
  If this document's headers were ["<col1>","<col2>","<col3>","<col4>"] and a row's third column is blank:
  CORRECT:   ["val1", "val2", "", "val4"]      (a "" placeholder keeps every column aligned)
  INCORRECT: ["val1", "val2", "val4"]          (dropping the blank shifts everything left)

DOCUMENT TEXT:
{text}
"""


def _parse_page_range(page_range, total_pages):
    """Convert '1-3,5' into a sorted list of 0-based page indexes. (LD)"""
    if not page_range or str(page_range).strip().lower() == 'all':
        return list(range(total_pages))

    indexes = []
    for part in str(page_range).replace(' ', '').split(','):
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                for n in range(int(start), int(end) + 1):
                    if 1 <= n <= total_pages:
                        indexes.append(n - 1)
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= total_pages:
                    indexes.append(n - 1)
            except ValueError:
                pass
    return sorted(set(indexes))


# Alias kept for callers that import parse_page_range directly (LD)
def parse_page_range(page_range, page_count):
    return _parse_page_range(page_range, page_count)


def detect_pdf_type(pdf_path):
    """Return 'text' if the PDF has searchable text, 'image' otherwise. (LD)"""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = ''
            for page in pdf.pages[:min(3, len(pdf.pages))]:
                text += page.extract_text() or ''
            result = 'text' if len(text.strip()) > 100 else 'image'
            print(f'[LLM] PDF type: {result} ({len(text)} chars extracted)')
            return result
    except ImportError:
        print('[LLM] pdfplumber not available — assuming text-based PDF')
        return 'text'
    except Exception as e:
        print(f'[LLM] PDF type detection failed: {e} — assuming text-based')
        return 'text'


def _pages_to_range(pages):
    """Convert a list of 1-based page numbers into a compact range string.
    e.g. [2, 3, 5] -> '2-3,5'. Returns '' for an empty list."""
    pages = sorted(set(int(p) for p in pages))
    if not pages:
        return ''
    parts, start, prev = [], pages[0], pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            parts.append(f'{start}-{prev}' if start != prev else f'{start}')
            start = prev = p
    parts.append(f'{start}-{prev}' if start != prev else f'{start}')
    return ','.join(parts)


def detect_bom_pages(pdf_path):
    """
    Scan a PDF and return the pages most likely to contain a BOM table.

    Scores each page on BOM-ish signals — header keywords (QTY, PART,
    DESCRIPTION, ITEM, …) and the density of part-number-like tokens — then
    keeps pages at or above half the best page's score (with a small floor).
    Header naming varies by customer, so this is intentionally content-based.

    Returns (range_string, page_list) with 1-based page numbers. Falls back to
    ('all', [...all pages...]) if nothing scores high enough or on any error.
    """
    header_kws = [
        'QTY', 'QUANTITY', 'PART', 'DESCRIPTION', 'ITEM', 'MODEL', 'MFG',
        'MANUFACTURER', 'MPN', 'CATALOG', 'CAT NO', 'CAT.', 'UNIT', 'U/M',
        'SUPPLIER', 'VENDOR', 'REF', 'BILL OF MATERIAL', 'PARTS LIST',
    ]
    try:
        import pdfplumber
        scores, total = {}, 0
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for i, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or '').upper()
                if not text.strip():
                    continue
                kw_hits = sum(1 for kw in header_kws if kw in text)
                # part-number-like tokens: 4+ char alnum containing a digit
                pn_hits = len(re.findall(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{4,}\b', text))
                scores[i] = kw_hits + min(pn_hits, 30) * 0.3

        if not scores:
            print('[AUTO-PAGES] No text found — defaulting to all pages')
            return 'all', list(range(1, (total or 0) + 1))

        max_score = max(scores.values())
        threshold = max(3.0, max_score * 0.5)
        pages = sorted(p for p, s in scores.items() if s >= threshold)
        if not pages:  # nothing cleared the bar — take the single best page
            pages = [max(scores, key=scores.get)]

        rng = _pages_to_range(pages)
        print(f'[AUTO-PAGES] Detected BOM pages: {rng} (of {total}) | '
              f'scores={ {p: round(s, 1) for p, s in scores.items()} }')
        return rng, pages
    except Exception as e:
        print(f'[AUTO-PAGES] Detection failed ({e}) — defaulting to all pages')
        return 'all', []


def prepare_searchable_pdf(pdf_path):
    """Run OCR if the PDF is image-based; return (path_to_use, ocr_was_run). (LD)"""
    if detect_pdf_type(pdf_path) == 'text':
        return pdf_path, False

    print('[LLM] Image-based PDF — running OCR preprocessing...')
    try:
        from pipeline.ocr_preprocessor import process_pdf_with_ocr
        ocr_path = process_pdf_with_ocr(pdf_path, force_ocr=True)
        if ocr_path and Path(ocr_path).exists():
            print(f'[LLM] OCR complete: {ocr_path}')
            return ocr_path, True
        print('[LLM] OCR did not produce a usable file — using original')
    except Exception as e:
        print(f'[LLM] OCR failed: {e} — using original PDF')
    return pdf_path, False


def extract_text_from_pdf_pages(pdf_path, pages):
    """Extract text from the requested pages using pdfplumber. (LD)"""
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError(f'pdfplumber is required for LLM extraction: {e}')

    with pdfplumber.open(pdf_path) as pdf:
        page_indexes = _parse_page_range(pages, len(pdf.pages))
        if not page_indexes:
            page_indexes = list(range(len(pdf.pages)))

        page_texts = []
        for idx in page_indexes:
            page = pdf.pages[idx]
            text = page.extract_text() or ''
            page_texts.append(f'--- PAGE {idx + 1} ---\n{text}')

        combined = '\n\n'.join(page_texts).strip()
        if not combined:
            raise RuntimeError('No searchable text found on the requested pages')
        return combined


def call_local_ollama(prompt):
    """Send prompt to the local Ollama model and return the raw response string. (LD)"""
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_HOST)
        response = client.chat(
            model=MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            # Bigger context + output so dense pages aren't truncated mid-table
            # (a too-small num_predict silently cuts the row list short).
            options={'temperature': 0, 'num_ctx': 16384, 'num_predict': 8192},
        )
        return response['message']['content']
    except Exception as e:
        raise RuntimeError(f'Ollama call failed ({OLLAMA_HOST}, model={MODEL}): {e}')


def parse_ollama_response_as_tables(response_text):
    """Parse the JSON response from Ollama into a list of DataFrames. (LD)"""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f'[LLM] JSON parse error: {e}')
        # Attempt to extract embedded JSON object (LD)
        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return []
        else:
            return []

    if not data.get('found', True):
        print('[LLM] Model reported no BOM table found')
        return []

    headers = data.get('headers', [])
    rows = data.get('rows', [])

    if not headers or not rows:
        return []

    # Pad or trim rows so they match header count (LD)
    n = len(headers)
    clean_rows = []
    for row in rows:
        if not isinstance(row, list):
            continue
        if len(row) < n:
            row = row + [''] * (n - len(row))
        clean_rows.append(row[:n])

    if not clean_rows:
        return []

    df = pd.DataFrame(clean_rows, columns=headers)
    df = df.fillna('').astype(str)
    df = df.replace('nan', '').replace('None', '')
    return [df]


def _split_two_column_page(pdf_page):
    """
    Contextually detect two side-by-side BOM tables on a page.

    Works by checking whether strong BOM header words (ITEM, QTY, DESCRIPTION,
    COMMENTS) appear at two x-positions separated by ≥25% of the page width.
    On a single-column BOM those words appear once; on a schematic they may not
    appear at all. Only a genuine two-column BOM layout triggers a split.
    Falls back to [pdf_page] for everything else.
    """
    try:
        words = pdf_page.extract_words()
        if not words:
            return [pdf_page]

        page_w = pdf_page.width

        # Anchor keywords: short, distinctive, unlikely to appear in part data
        anchor_keys = {'ITEM', 'QTY', 'DESCRIPTION', 'COMMENTS'}
        kw_positions = {}
        for w in words:
            key = w['text'].upper().strip().rstrip('.')
            if key in anchor_keys:
                kw_positions.setdefault(key, []).append(w['x0'])

        # For each keyword, check if it appears at two x-positions far enough apart
        left_anchors, right_anchors = [], []
        for kw, positions in kw_positions.items():
            if len(positions) < 2:
                continue
            for i, xi in enumerate(sorted(positions)):
                for xj in sorted(positions)[i + 1:]:
                    if xj - xi >= page_w * 0.25:
                        left_anchors.append(xi)
                        right_anchors.append(xj)
                        print(f'[SPLIT] "{kw}" at x={xi:.0f} and x={xj:.0f} — two-column signal')
                        break

        if not left_anchors:
            return [pdf_page]

        # The boundary lies right of every left-table anchor and left of every
        # right-table one. Midpointing a keyword pair lands inside a table when
        # the columns are unevenly spaced, so search that window for the widest
        # word-free gap — the actual gutter between the two tables.
        # Restrict to the middle of the sheet as well: a gap between two columns
        # of the SAME table can be wider than the gutter, but the gutter of a
        # two-column layout always sits near the centre.
        lo = max(max(left_anchors), page_w * 0.30)
        hi = min(min(right_anchors), page_w * 0.70)
        if hi <= lo:
            lo, hi = max(left_anchors), min(right_anchors)
        spans = sorted((w['x0'], w['x1']) for w in words if w['x1'] > lo and w['x0'] < hi)
        best_gap, split_x = 0.0, (lo + hi) / 2
        cursor = lo
        for x0, x1 in spans:
            if x0 - cursor > best_gap:
                best_gap, split_x = x0 - cursor, (cursor + x0) / 2
            cursor = max(cursor, x1)
        if hi - cursor > best_gap:
            best_gap, split_x = hi - cursor, (cursor + hi) / 2
        print(f'[SPLIT] gutter search in x=[{lo:.0f},{hi:.0f}] — widest gap {best_gap:.0f}px')

        # Both sides must have meaningful content (not just whitespace)
        left_count  = sum(1 for w in words if w['x1'] <= split_x)
        right_count = sum(1 for w in words if w['x0'] >= split_x)
        if left_count < 15 or right_count < 15:
            return [pdf_page]

        print(f'[SPLIT] Two-column BOM confirmed — splitting at x={split_x:.1f}')
        return [
            pdf_page.crop((0,       0, split_x,      pdf_page.height)),
            pdf_page.crop((split_x, 0, pdf_page.width, pdf_page.height)),
        ]

    except Exception as e:
        print(f'[SPLIT] Column detection failed, using full page: {e}')
        return [pdf_page]


def _extract_native_tables(pdf_page, label=''):
    """
    Use pdfplumber's built-in table detection as the primary extraction path.
    Handles multi-line cells correctly because it reads cell boundaries rather
    than raw text. Falls back gracefully by returning [] when no table is found.
    """
    try:
        raw_tables = pdf_page.extract_tables()
        if not raw_tables:
            return []

        results = []
        bom_kw = ['ITEM', 'QTY', 'PART', 'MFG', 'MFR', 'DESCRIPTION', 'MANUFACTURER',
                  'MPN', 'CATEGORY', 'PACKAGE', 'MODEL', 'CATALOG']

        def _clean_hdr(cells):
            # Collapse wrap-newlines so "INTERNAL\nPART #\n(IPN)" → "INTERNAL PART # (IPN)"
            return [re.sub(r'\s+', ' ', str(c or '').replace('\n', ' ')).strip() for c in cells]

        for t in raw_tables:
            if not t or len(t) < 2:
                continue

            # FIND the header row among the first few rows — the first page often
            # has a title/metadata preamble that pdfplumber lumps into the table
            # above the real header. (Assuming row 0 is the header dropped page 1.)
            hdr_idx = None
            for ri in range(min(6, len(t))):
                cleaned = _clean_hdr(t[ri])
                if sum(1 for h in cleaned if h) < 2:
                    continue
                if sum(1 for kw in bom_kw if kw in ' '.join(cleaned).upper()) >= 2:
                    hdr_idx = ri
                    break
            if hdr_idx is None:
                continue  # Doesn't look like a BOM table

            headers = _clean_hdr(t[hdr_idx])

            rows = []
            for row in t[hdr_idx + 1:]:
                # Normalize each cell: join multi-line content, strip whitespace
                clean = [' '.join(str(c or '').split()) for c in row]
                if any(v for v in clean):  # skip all-blank rows
                    rows.append(clean)

            if not rows:
                continue

            df = pd.DataFrame(rows, columns=headers)
            df = df.fillna('').astype(str).replace('nan', '').replace('None', '')
            results.append(df)
            print(f'[NATIVE] {label}: extracted {len(df)} rows via pdfplumber table detection')

        return results
    except Exception as e:
        print(f'[NATIVE] {label}: table detection failed ({e}), falling back to LLM')
        return []


def _group_words_into_lines(words):
    """Cluster words into visual rows by vertical overlap. (LD)

    Replaces a fixed grid — round(top / 3.0) — which was a bucket, not a
    tolerance: two rows up to 3px apart could share one bucket, and sorting
    that merged bucket by x0 interleaved both rows character by character
    ('120VAC' + 'QUICKC' -> '1Q2U0IVCAKC'). Digital PDFs have exact baselines
    so the grid held up; OCR'd scans jitter and it did not.

    A word joins a row when its vertical span overlaps the row's band by at
    least half the word's height. The band expands to follow gradual skew but
    is capped, so it can never grow until it swallows the row below.
    """
    if not words:
        return []

    heights = sorted(w['bottom'] - w['top'] for w in words)
    med_h = heights[len(heights) // 2] or 1.0
    max_band = med_h * 1.6          # a single row never spans more than this

    rows = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        w_h = w['bottom'] - w['top']
        placed = False
        # Words arrive top-down, so only the most recent rows can still be open.
        for row in reversed(rows[-3:]):
            overlap = min(w['bottom'], row['bottom']) - max(w['top'], row['top'])
            if overlap >= 0.5 * w_h:
                new_top = min(row['top'], w['top'])
                new_bottom = max(row['bottom'], w['bottom'])
                if new_bottom - new_top <= max_band:
                    row['words'].append(w)
                    row['top'], row['bottom'] = new_top, new_bottom
                    placed = True
                    break
        if not placed:
            rows.append({'top': w['top'], 'bottom': w['bottom'], 'words': [w]})

    rows.sort(key=lambda r: r['top'])
    return [sorted(r['words'], key=lambda w: w['x0']) for r in rows]


def _page_text_by_rows(page):
    """Rebuild page text as one visual row per line, for the LLM path. (LD)

    extract_text(layout=True) has the same flaw the old row grid had: it merges
    tightly-spaced lines — notably the wrapped lines inside one description
    cell — then orders the merged row by x, interleaving them character by
    character ('CONNECTOR' + 'TIN-PLATED' -> 'CTONNPNLAECTTEODR'). Clustering
    rows by vertical overlap keeps wrapped lines apart. Column gaps are kept as
    proportional padding so the model still sees the table's shape.
    """
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return page.extract_text() or ''
    if not words:
        return ''

    # Median character width, to convert x-gaps into space counts.
    widths = sorted((w['x1'] - w['x0']) / max(len(w['text']), 1) for w in words)
    char_w = widths[len(widths) // 2] or 1.0

    lines = []
    for row in _group_words_into_lines(words):
        parts, prev_x1 = [], None
        for w in row:
            if prev_x1 is not None:
                pad = int(round((w['x0'] - prev_x1) / char_w))
                parts.append(' ' * max(1, min(pad, 12)))   # cap runaway padding
            parts.append(w['text'])
            prev_x1 = w['x1']
        line = ''.join(parts).rstrip()
        if line:
            lines.append(line)
    return '\n'.join(lines)


def _extract_text_aligned_table(page, label='', prev=None):
    """Parse a GRIDLESS, text-aligned BOM table using word x-positions.

    pdfplumber's line-based detection needs ruling lines; most real BOMs are just
    columns of aligned text. This finds the header row by BOM keywords, derives
    column boundaries from the header word x-positions, then bins each following
    line's words into those columns. It naturally skips any title/metadata
    preamble above the header — which is what makes a small LLM choke.

    `prev` = (names, anchors) carried from a previous page, so continuation pages
    that repeat data but not the header still parse. Returns (df, names, anchors)
    or (None, None, None).
    """
    BOM_KW = ['PART', 'QTY', 'QUANTITY', 'DESCRIPTION', 'MANUFACTURER', 'MFR',
              'MFG', 'ITEM', 'MPN', 'PACKAGE', 'CATEGORY', 'UOM', 'MODEL', 'VENDOR',
              'SUPPLIER', 'REF']
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return None, None, None
    if not words:
        return None, None, None

    # Group words into visual rows (overlap-based; tolerates OCR baseline jitter).
    line_items = _group_words_into_lines(words)

    # Locate the header line (the one with the most BOM keywords).
    names, anchors, data_rows = None, None, []
    best_i, best_score = None, 1
    for i, ln in enumerate(line_items):
        t = ' '.join(w['text'] for w in ln).upper()
        score = sum(1 for kw in BOM_KW if kw in t)
        if score > best_score:
            best_score, best_i = score, i

    if best_i is not None:
        hw = line_items[best_i]
        anchors, names = [hw[0]['x0']], [hw[0]['text']]
        for prev_w, cur in zip(hw, hw[1:]):
            if cur['x0'] - prev_w['x1'] > 12:          # big gap = new column
                anchors.append(cur['x0'])
                names.append(cur['text'])
            else:
                names[-1] += ' ' + cur['text']         # same column (multi-word header)
        # Engineering-drawing BOMs (EOS, and drawings generally) put the header
        # at the BOTTOM of the table and number rows upward from it. When almost
        # nothing follows the header but plenty precedes it, read upward instead
        # — otherwise there are no data rows and the whole page falls to the LLM.
        # Pick the side by which one actually holds table rows, not by row count:
        # a title block below the table and a metadata preamble above it both
        # inflate a naive count. A real data row spreads across >=3 columns.
        def _table_like(lines):
            n = 0
            for ln in lines:
                bins = {min(range(len(anchors)), key=lambda i: abs(anchors[i] - w['x0']))
                        for w in ln}
                if len(bins) >= 3:
                    n += 1
            return n

        above_rows, below_rows = line_items[:best_i], line_items[best_i + 1:]
        n_above, n_below = _table_like(above_rows), _table_like(below_rows)
        if n_above > n_below:
            data_rows = above_rows           # keep visual top-to-bottom order
            print(f'[ALIGNED] {label}: header at bottom — {n_above} rows above it')
        else:
            data_rows = below_rows
    elif prev:
        names, anchors = prev                          # continuation page — reuse columns
        data_rows = line_items
    else:
        return None, None, None

    if len(anchors) < 3:
        return None, None, None                        # not a real multi-column table

    # The leftmost column's header is often on a line ABOVE the main keyword line
    # (wrapped headers like "INTERNAL PART #\n(IPN)"), so the main line's anchors
    # start at column 2. If the DATA rows consistently have content to the LEFT of
    # the first anchor, recover that missed leading column (the classifier will
    # name it by content). Likewise catch one missed column on the right.
    left_xs = [w['x0'] for ln in data_rows[:12] for w in ln if w['x0'] < anchors[0] - 12]
    if len(left_xs) >= 3:
        anchors.insert(0, min(left_xs))
        names.insert(0, 'Column_L')

    bounds = anchors + [float('inf')]

    def _col_of(x):
        if x < anchors[0] - 6:
            return 0                                    # left of everything → first column
        for i in range(len(anchors)):
            if anchors[i] - 6 <= x < bounds[i + 1] - 6:
                return i
        return len(anchors) - 1

    rows = []
    for ln in data_rows:
        cells = [''] * len(anchors)
        for w in ln:
            cells[_col_of(w['x0'])] = (cells[_col_of(w['x0'])] + ' ' + w['text']).strip()
        if not any(cells):
            continue
        joined = ' '.join(cells).upper()
        # drop page footers like "Page 1 of 8" / "Confidential ..."
        if (('PAGE ' in joined and ' OF ' in joined) or 'CONFIDENTIAL' in joined) \
                and sum(1 for c in cells if c) <= 2:
            continue
        rows.append(cells)

    if len(rows) < 2:
        return None, None, None
    df = pd.DataFrame(rows, columns=names).fillna('').astype(str)
    print(f'[ALIGNED] {label}: {len(df)} rows × {len(names)} cols via text-position parsing')
    return df, names, anchors


def _split_into_chunks(text, chunk_size=10000, overlap=500):
    """Split text into overlapping chunks snapped to newline boundaries. (LD)"""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # Final chunk reaches the end — emit it and stop. Without this the
        # tail keeps getting re-sliced at start = len(text) - overlap forever. (LD)
        if end >= len(text):
            chunks.append(chunk)
            break
        last_nl = chunk.rfind('\n')
        if last_nl > chunk_size // 2:
            chunk = chunk[:last_nl]
        chunks.append(chunk)
        start += max(len(chunk) - overlap, 1)   # never stall or move backwards (LD)
    return chunks


def _merge_same_schema_tables(tables):
    """Concatenate tables that share the same column set (multi-page BOMs). (LD)"""
    if not tables:
        return []
    groups = {}
    for t in tables:
        key = tuple(t.columns.tolist())
        groups.setdefault(key, []).append(t)
    result = []
    for group in groups.values():
        merged = pd.concat(group, ignore_index=True).drop_duplicates().reset_index(drop=True) if len(group) > 1 else group[0]
        result.append(merged)
    return result


def extract_tables_from_pdf(pdf_path, pages='all'):
    """
    Core LLM extraction entry point. (LD)
    Processes each page separately so no page is ever truncated away. (LD)
    Returns a list of DataFrames (usually one merged table). (LD)
    """
    print(f'\n[LLM] Starting extraction — PDF: {pdf_path}, pages: {pages}')

    searchable_path = pdf_path
    ocr_generated = False
    try:
        searchable_path, ocr_generated = prepare_searchable_pdf(pdf_path)

        try:
            import pdfplumber
        except ImportError as e:
            raise RuntimeError(f'pdfplumber is required for LLM extraction: {e}')

        with pdfplumber.open(searchable_path) as pdf:
            page_indexes = _parse_page_range(pages, len(pdf.pages))
            if not page_indexes:
                page_indexes = list(range(len(pdf.pages)))

            all_raw_tables = []
            last_table_meta = None   # (names, anchors) for headerless continuation pages
            for idx in page_indexes:
                page = pdf.pages[idx]

                # Split two-column pages at the PDF level before extracting text
                # ── Primary: native table detection on the FULL page ──────
                # Run BEFORE splitting so pdfplumber can find both side-by-side
                # tables as separate objects (cropping cuts shared borders).
                native = _extract_native_tables(page, f'Page {idx + 1}')
                if native:
                    all_raw_tables.extend(native)
                    continue  # both columns captured — skip split + LLM

                # ── Secondary: text-position parsing for GRIDLESS tables ──
                # Reliable for borderless BOMs (and skips metadata preamble),
                # where a small LLM tends to hallucinate or collapse columns.
                aligned_df, a_names, a_anchors = _extract_text_aligned_table(
                    page, f'Page {idx + 1}', prev=last_table_meta)
                if aligned_df is not None and len(aligned_df) >= 2:
                    last_table_meta = (a_names, a_anchors)
                    all_raw_tables.append(aligned_df)
                    continue  # parsed positionally — skip LLM

                # ── Fallback: split + LLM ─────────────────────────────────
                sub_pages = _split_two_column_page(page)

                for col_idx, sub_page in enumerate(sub_pages):
                    prefix = (
                        f'Page {idx + 1}' if len(sub_pages) == 1
                        else f'Page {idx + 1} col {col_idx + 1}'
                    )
                    page_text = _page_text_by_rows(sub_page)
                    if not page_text.strip():
                        print(f'[LLM] {prefix}: no text, skipping')
                        continue

                    page_content = f'--- {prefix} ---\n{page_text}'
                    if len(page_content) > 32000:
                        page_content = page_content[:32000]

                    chunks = _split_into_chunks(page_content)
                    n = len(chunks)
                    labels = [
                        prefix if n == 1
                        else f'{prefix} chunk {i + 1}/{n}'
                        for i in range(n)
                    ]
                    print(f'[LLM] {prefix}: {len(page_content)} chars → {n} chunk(s), running parallel')

                    def _run_chunk(args):
                        chunk, label = args
                        print(f'[LLM] {label}: {len(chunk)} chars — sending to Ollama...')
                        prompt = EXTRACTION_PROMPT.format(text=chunk)
                        response_text = call_local_ollama(prompt)
                        print(f'[LLM] {label}: {len(response_text)} chars response')
                        return parse_ollama_response_as_tables(response_text)

                    with ThreadPoolExecutor(max_workers=n) as executor:
                        for chunk_tables in executor.map(_run_chunk, zip(chunks, labels)):
                            all_raw_tables.extend(chunk_tables)

        if not all_raw_tables:
            print('[LLM] No tables parsed from any page')
            return []

        # Merge pages that belong to the same BOM (same column schema)
        merged = _merge_same_schema_tables(all_raw_tables)
        cleaned = clean_and_filter_tables(merged, 'Ollama')
        print(f'[LLM] Returning {len(cleaned)} clean table(s)')
        return cleaned

    except Exception as e:
        print(f'[LLM] Extraction failed: {e}')
        traceback.print_exc()
        return []
    finally:
        if ocr_generated and searchable_path != pdf_path:
            # BOM_KEEP_OCR=1 keeps the OCR'd PDF on disk so its text layer can be
            # inspected after a bad extraction. Debug only — these are large. (LD)
            if os.environ.get('BOM_KEEP_OCR', '').strip() not in ('', '0', 'false', 'False'):
                print(f'[LLM] BOM_KEEP_OCR set — keeping OCR output: {searchable_path}')
            else:
                try:
                    from pipeline.ocr_preprocessor import cleanup_ocr_temp_files
                    cleanup_ocr_temp_files(searchable_path)
                except Exception:
                    pass


def clean_and_filter_tables(tables, method_name):
    """Remove empty/tiny tables and sanitise cell content. (LD)"""
    print(f'[CLEAN] Cleaning {len(tables)} table(s) from {method_name}...')
    cleaned = []
    for i, table in enumerate(tables):
        if table is None or table.empty:
            continue
        try:
            table = table.fillna('').astype(str)
            table = table.replace('nan', '').replace('None', '')
            table = table.loc[:, (table != '').any(axis=0)]
            table = table.loc[(table != '').any(axis=1)]
            table = table.reset_index(drop=True)

            table = table.apply(lambda s: s
                               .str.replace(r'[^\w\s\-\.\,\/\(\)\:\#\+]', ' ', regex=True)
                               .str.replace(r'\s+', ' ', regex=True)
                               .str.strip())

            rows, cols = table.shape
            if rows < 2 or cols < 2:
                print(f'  [SKIP] Table {i + 1}: too small ({rows}x{cols})')
                continue
            if rows > 500 or cols > 50:
                print(f'  [SKIP] Table {i + 1}: too large ({rows}x{cols})')
                continue

            non_empty = (table != '').sum().sum()
            ratio = non_empty / (rows * cols)
            if ratio < 0.1:
                print(f'  [SKIP] Table {i + 1}: low content ratio ({ratio:.2f})')
                continue

            # Drop rows that are clearly legal/disclaimer text, not BOM data.
            # Keep phrases very specific so manufacturer names never match.
            junk_phrases = [
                'ALL RIGHTS RESERVED',
                'DO NOT REPRODUCE',
                'WITHOUT WRITTEN PERMISSION',
                'WRITTEN PERMISSION OF',
                'PROPRIETARY AND CONFIDENTIAL',
                'PROPRIETARY INFORMATION',
                'CONFIDENTIAL PROPERTY',
                'SUBJECT TO RECALL',
                'INFORMATION CONTAINED HEREIN IS THE PROPERTY',
                'APPROVED BY', 'CHECKED BY', 'DRAWN BY',
            ]
            def _is_junk_row(row):
                combined = ' '.join(str(v) for v in row).upper()
                # A real part number ALWAYS contains a digit (e.g. 6ES7155-6AU00,
                # 5SJ4111-8HG41, 1034250). Match either a hyphen/slash-joined
                # alphanumeric token, or any 3+ char token that contains a digit.
                # Plain English words (GILLETTE, COMPANY, PERMISSION) have no digit
                # and must NOT be mistaken for part numbers — that is what let the
                # proprietary/legal notice survive previously.
                has_pn = bool(re.search(
                    r'[A-Z0-9]{2,}[-/][A-Z0-9]'          # hyphen/slash part numbers
                    r'|\b(?=[A-Z0-9]*\d)[A-Z0-9]{3,}\b', # 3+ char token with a digit
                    combined))
                if len(combined) > 100 and not has_pn:
                    return True
                return any(phrase in combined for phrase in junk_phrases)

            before = len(table)
            table = table[~table.apply(_is_junk_row, axis=1)].reset_index(drop=True)
            if len(table) < before:
                print(f'  [FILTER] Table {i + 1}: removed {before - len(table)} junk row(s)')
            if table.empty:
                continue

            cleaned.append(table)
            print(f'  [OK] Table {i + 1}: {rows}x{cols}, fill={ratio:.2f}')
        except Exception as e:
            print(f'  [ERR] Table {i + 1}: {e}')
    return cleaned


def is_likely_bom_table(df):
    """Score a DataFrame for BOM-likeness; return True if it passes the threshold. (LD)"""
    if df is None or df.empty:
        return False

    HEADER_SYNONYMS = {
        'item':         ['ITEM', 'ITEM NO', 'ITEM NO.', 'ITEM NUMBER', 'NO', 'POS', 'POSITION'],
        'quantity':     ['QTY', 'QUANTITY', 'QUANT.', 'AMOUNT'],
        'description':  ['DESCRIPTION', 'DESC', 'DETAILS', 'PART DESCRIPTION', 'PART NAME',
                         'ITEM DESCRIPTION', 'DEVICE'],
        'manufacturer': ['MANUFACTURER', 'MFG', 'MFR', 'MAKE', 'BRAND'],
        'part_number':  ['PART NO', 'PART NUMBER', 'P/N', 'PN', 'MODEL NO', 'MODEL', 'MPN'],
    }

    def _has_synonym(cells, variants):
        for cell in cells:
            if any(v in str(cell).upper().strip() for v in variants):
                return True
        return False

    try:
        header_cells = [str(c).upper().strip() for c in df.iloc[0]]
        non_empty = sum(1 for c in header_cells if c not in ('', 'NAN'))
        if non_empty / max(len(header_cells), 1) < 0.5:
            return False

        for field in ('item', 'quantity'):
            if not _has_synonym(header_cells, HEADER_SYNONYMS[field]):
                return False

        return True
    except Exception:
        return False


def extract_tables_from_pdf_auto(pdf_path, pages='all', extraction_method='auto'):
    """
    Public entry point used by run_main_extraction_workflow. (LD)
    Always routes through the Ollama LLM path. (LD)
    """
    print(f'[AUTO] extract_tables_from_pdf_auto — method={extraction_method}')
    return extract_tables_from_pdf(pdf_path, pages)


def process_and_format_tables(tables, customer_name=''):
    """Apply customer-specific column formatting to each extracted table. (LD)"""
    if not tables:
        return []

    print(f'\n[FORMAT] Processing {len(tables)} table(s) for customer: {customer_name or "generic"}')
    processed = []
    for i, table in enumerate(tables):
        try:
            cleaned = clean_and_filter_tables([table], f'table_{i + 1}')
            if not cleaned:
                print(f'  [SKIP] Table {i + 1} failed cleaning')
                continue
            table = cleaned[0]

            # Always run a formatter. apply_customer_formatter() routes a blank /
            # unknown company to the generic content-aware formatter, which is what
            # standardizes column names (Part Number / Quantity / Description / …)
            # so the cost sheet can be populated. Previously this was gated on
            # `if customer_name:`, so the no-company path skipped formatting entirely
            # and the cost sheet came out empty.
            try:
                from omni_cust.customer_formatters import apply_customer_formatter
                formatted = apply_customer_formatter(table, customer_name)
                if formatted is not None:
                    table = formatted
            except Exception as fmt_err:
                print(f'  [WARN] Customer formatter failed: {fmt_err}')

            processed.append(table)
            print(f'  [OK] Table {i + 1} ready ({table.shape[0]}x{table.shape[1]})')
        except Exception as e:
            print(f'  [ERR] Table {i + 1}: {e}')
    return processed


def _autofit_columns(ws, max_width=60):
    """Set column widths based on the longest cell value in each column. (LD)"""
    for col in ws.columns:
        max_len = max((len(str(cell.value or '')) for cell in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, max_width)


def save_tables_to_excel(tables, output_path):
    """Save each table to its own sheet in an Excel workbook. (LD)"""
    if not tables:
        print('[SAVE] No tables to save')
        return False
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for i, table in enumerate(tables):
                sheet_name = f'Table_{i + 1}'
                table.to_excel(writer, sheet_name=sheet_name, index=False)
                _autofit_columns(writer.sheets[sheet_name])
        print(f'[SAVE] {len(tables)} table(s) saved: {output_path}')
        return True
    except Exception as e:
        print(f'[SAVE] Failed to save Excel: {e}')
        traceback.print_exc()
        return False


def merge_tables_and_export(tables, output_path, sheet_name='Combined_BoM', company=''):
    """Concatenate all tables into one sheet and save. (LD)"""
    if not tables:
        print('[MERGE] No tables to merge')
        return False
    try:
        merged = pd.concat(tables, ignore_index=True)
        merged = merged.fillna('').replace('nan', '')
        merged = merged.loc[(merged != '').any(axis=1)]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            merged.to_excel(writer, sheet_name=sheet_name, index=False)
            _autofit_columns(writer.sheets[sheet_name])

        print(f'[MERGE] Merged {merged.shape[0]}x{merged.shape[1]} table saved: {output_path}')
        return True
    except Exception as e:
        print(f'[MERGE] Failed: {e}')
        traceback.print_exc()
        return False


def run_main_extraction_workflow():
    """
    Called by main_pipeline when running in subprocess / direct mode. (LD)
    Reads env vars, runs Ollama extraction, shows table selector, saves output. (LD)
    """
    print('[WORKFLOW] run_main_extraction_workflow() started')

    pdf_path = os.environ.get('BOM_PDF_PATH')
    pages = os.environ.get('BOM_PAGE_RANGE', 'all')
    company = os.environ.get('BOM_COMPANY', '')
    output_directory = os.environ.get('BOM_OUTPUT_DIRECTORY', '')

    if not pdf_path or not Path(pdf_path).exists():
        print(f'[WORKFLOW] PDF not found: {pdf_path}')
        sys.exit(1)

    print(f'[WORKFLOW] PDF={pdf_path} | pages={pages} | company={company}')

    # ── Step 1: Extract tables via Ollama ──────────────────────────────────── (LD)
    extracted_tables = extract_tables_from_pdf(pdf_path, pages)

    if not extracted_tables:
        print('[WORKFLOW] No tables extracted — aborting')
        sys.exit(1)

    print(f'[WORKFLOW] Extracted {len(extracted_tables)} table(s)')

    # ── Step 2: Let the user pick the right table ──────────────────────────── (LD)
    try:
        from gui.table_selector import show_table_selector
        selected_tables = show_table_selector(extracted_tables)
    except Exception as e:
        print(f'[WORKFLOW] Table selector unavailable ({e}) — using all tables')
        selected_tables = extracted_tables

    if not selected_tables:
        print('[WORKFLOW] No tables selected — aborting')
        sys.exit(1)

    # ── Step 3: Apply customer formatting ─────────────────────────────────── (LD)
    processed_tables = process_and_format_tables(selected_tables, company)

    if not processed_tables:
        print('[WORKFLOW] All tables failed processing — aborting')
        sys.exit(1)

    # ── Step 4: Save extracted + merged Excel files ────────────────────────── (LD)
    pdf_dir = Path(pdf_path).parent
    pdf_stem = Path(pdf_path).stem
    if output_directory:
        out_dir = Path(output_directory)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = pdf_dir

    extracted_path = out_dir / f'{pdf_stem}_extracted.xlsx'
    merged_path = out_dir / f'{pdf_stem}_merged.xlsx'

    save_tables_to_excel(processed_tables, str(extracted_path))
    ok = merge_tables_and_export(processed_tables, str(merged_path), 'Combined_BoM', company)

    if not ok:
        print('[WORKFLOW] Failed to save merged table — aborting')
        sys.exit(1)

    print('[WORKFLOW] Extraction workflow completed successfully')


# ── Legacy aliases kept for any remaining callers ─────────────────────────── (LD)
def extract_tables_with_tabula(*args, **kwargs):
    return extract_tables_from_pdf(*args, **kwargs)

def clean_table_headers(table):
    return table

def has_any_synonym(header_cells, variants):
    for cell in header_cells:
        if any(v in str(cell).upper().strip() for v in variants):
            return True
    return False

# Kept so map_cost_sheet.py import doesn't fail (LD)
MIN_ROWS, MIN_COLS = 3, 3
HEADER_SYNONYMS = {
    'item':         ['ITEM', 'ITEM NO', 'ITEM NO.', 'ITEM NUMBER', 'NO', 'POS', 'POSITION'],
    'quantity':     ['QTY', 'QUANTITY', 'QUANT.', 'AMOUNT'],
    'description':  ['DESCRIPTION', 'DESC', 'DETAILS', 'PART DESCRIPTION', 'PART NAME',
                     'ITEM DESCRIPTION', 'DEVICE'],
    'manufacturer': ['MANUFACTURER', 'MFG', 'MFR', 'MAKE', 'BRAND'],
    'part_number':  ['PART NO', 'PART NUMBER', 'P/N', 'PN', 'MODEL NO', 'MODEL', 'MPN'],
}
