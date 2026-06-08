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
- Use the EXACT column headers from the document — do not rename them
- TWO-COLUMN LAYOUT: If the page has two BOM tables side-by-side with the same columns, treat them as ONE continuous table. Extract all rows from the LEFT side first, then all rows from the RIGHT side. Use the headers from the left side only.
- Extract ONLY rows that are part of the BOM table — ignore page headers, footers, legal text, disclaimers, notes, signature blocks, revision history, and any text that appears outside the table boundaries
- Include EVERY valid BOM data row — do not skip or summarize
- Preserve the exact row order as they appear in the document — do not reorder, sort, or group rows
- BLANK CELLS: If a cell is blank or empty, use "" for that position. NEVER shift the remaining values left to fill the gap. Every row must have exactly the same number of values as the headers list, with "" in every blank position.
- COMBINED FIELDS: If a column contains a combined value like "MANUFACTURER / PART_NUMBER", keep the full value intact as one string — do not split it across columns.

BLANK CELL EXAMPLE — if headers are ["ITEM","QTY","PART NUMBER","MFG / PART NUMBER","DESCRIPTION"] and a row has no PART NUMBER:
  CORRECT:   ["4", "5", "", "ALLEN BRADLEY / 700S-EFG20E3C", "Safety IEC Control Relay"]
  INCORRECT: ["4", "5", "ALLEN BRADLEY / 700S-EFG20E3C", "Safety IEC Control Relay", ""]

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
            options={'temperature': 0, 'num_ctx': 8192, 'num_predict': 4096},
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
        split_candidates = []
        for kw, positions in kw_positions.items():
            if len(positions) < 2:
                continue
            for i, xi in enumerate(sorted(positions)):
                for xj in sorted(positions)[i + 1:]:
                    if xj - xi >= page_w * 0.25:
                        split_candidates.append((xi + xj) / 2)
                        print(f'[SPLIT] "{kw}" at x={xi:.0f} and x={xj:.0f} — two-column signal')
                        break

        if not split_candidates:
            return [pdf_page]

        # Use the median candidate as the split line
        split_x = sorted(split_candidates)[len(split_candidates) // 2]

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


def _split_into_chunks(text, chunk_size=10000, overlap=500):
    """Split text into overlapping chunks snapped to newline boundaries. (LD)"""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if end < len(text):
            last_nl = chunk.rfind('\n')
            if last_nl > chunk_size // 2:
                chunk = chunk[:last_nl]
        chunks.append(chunk)
        start += len(chunk) - overlap
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
            for idx in page_indexes:
                page = pdf.pages[idx]

                # Split two-column pages at the PDF level before extracting text
                sub_pages = _split_two_column_page(page)

                for col_idx, sub_page in enumerate(sub_pages):
                    prefix = (
                        f'Page {idx + 1}' if len(sub_pages) == 1
                        else f'Page {idx + 1} col {col_idx + 1}'
                    )
                    try:
                        page_text = sub_page.extract_text(layout=True) or ''
                    except TypeError:
                        page_text = sub_page.extract_text() or ''
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

            # Drop rows that look like footer/legal/disclaimer text rather than BOM data
            junk_phrases = [
                'INFORMATION CONTAINED', 'THIS DOCUMENT', 'CORPORATION',
                'PROPRIETARY', 'CONFIDENTIAL', 'ALL RIGHTS RESERVED',
                'DO NOT REPRODUCE', 'WITHOUT WRITTEN', 'REVISION HISTORY',
                'DRAWING NO', 'APPROVED BY', 'CHECKED BY', 'DRAWN BY',
            ]
            def _is_junk_row(row):
                combined = ' '.join(str(v) for v in row).upper()
                # Long prose with no part-number-like token is likely junk
                if len(combined) > 80 and not re.search(r'[A-Z0-9]{4,}[-/][A-Z0-9]', combined):
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

            if customer_name:
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
