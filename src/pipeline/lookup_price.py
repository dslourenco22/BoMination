"""
LLM-powered price lookup using DuckDuckGo search + Ollama. (LD)
Replaces the legacy Selenium / ChromeDriver / OEMSecrets scraper. (LD)

Output DataFrame matches the OEMSecrets column schema so map_cost_sheet.py (LD)
works without any changes. (LD)
"""

import os
import json
import time
import traceback
from pathlib import Path

import pandas as pd

# ── Config ─────────────────────────────────────────────────────────────────── (LD)
MODEL = os.environ.get('BOM_LLM_MODEL', 'llama3.2')
OLLAMA_HOST = os.environ.get('BOM_LLM_ENDPOINT', 'http://127.0.0.1:11434')
SEARCH_DELAY = 1.0  # Seconds between DDG requests — be polite (LD)

# Column names that OEMSecrets used to export; map_cost_sheet.py reads these (LD)
OEM_COLUMNS = [
    'Internal Reference',
    'Part Number',
    'Quantity for Single BOM',
    'Extended Quantity for 1 BOM',
    'Manufacturer',
    'Distributor',
    'Minimum Order',
    'Unit Price in USD',
    'Lead Time on Additional Stock in Weeks',
    'Notes',
]

# ── Prompt ─────────────────────────────────────────────────────────────────── (LD)
PRICE_PROMPT = """You are an electronics component pricing specialist.

Extract pricing information for this part from the web search results below.

Part number: {part_number}
Quantity needed: {qty}

Search results:
{results}

Return ONLY this JSON — no explanation:
{{
  "unit_price": "12.50",
  "manufacturer": "Manufacturer Name",
  "distributor": "Distributor Name",
  "min_order": "1",
  "lead_time_weeks": "2-4",
  "notes": ""
}}

Rules:
- unit_price: numeric string (e.g. "3.75") — the lowest price found for the quantity
- All other fields: plain string — use "N/A" when not found
- Do NOT include currency symbols in unit_price
"""


# ── Helpers ────────────────────────────────────────────────────────────────── (LD)

def _find_part_number_col(df):
    """Return the column name that most likely holds MPNs, or None. (LD)"""
    candidates = ['MPN', 'PART NO', 'PART NUMBER', 'PART#', 'P/N', 'PN',
                  'MODEL NO', 'MODEL', 'Part Number', 'Part number']
    for name in candidates:
        if name in df.columns:
            return name
    # Case-insensitive fallback (LD)
    for col in df.columns:
        if any(kw in col.upper() for kw in ['MPN', 'PART', 'MODEL']):
            return col
    return None


def _find_qty_col(df):
    """Return the column name that holds quantities, or None. (LD)"""
    candidates = ['QTY', 'QUANTITY', 'QUANT.', 'AMOUNT', 'Quantity', 'Qty']
    for name in candidates:
        if name in df.columns:
            return name
    for col in df.columns:
        if 'QTY' in col.upper() or 'QUANT' in col.upper():
            return col
    return None


def _search_ddg(part_number):
    """Search DuckDuckGo for the part number and return formatted result text. (LD)"""
    try:
        from duckduckgo_search import DDGS
        query = f'"{part_number}" buy price USD electronics component distributor'
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return None
        lines = []
        for r in results:
            lines.append(
                f"Title: {r.get('title', '')}\n"
                f"URL: {r.get('href', '')}\n"
                f"Snippet: {r.get('body', '')}"
            )
        return '\n\n'.join(lines)
    except Exception as e:
        print(f'  [DDG] Search failed for {part_number}: {e}')
        return None


def _parse_price_with_ollama(part_number, qty, search_text):
    """
    Send search results to Ollama and parse the price JSON response. (LD)
    Returns a dict with keys matching OEM_COLUMNS. (LD)
    """
    empty = {
        'unit_price': 'N/A',
        'manufacturer': 'N/A',
        'distributor': 'N/A',
        'min_order': 'N/A',
        'lead_time_weeks': 'N/A',
        'notes': '',
    }
    try:
        import ollama
        prompt = PRICE_PROMPT.format(
            part_number=part_number,
            qty=qty,
            results=search_text[:3000],  # Limit context per lookup (LD)
        )
        client = ollama.Client(host=OLLAMA_HOST)
        response = client.chat(
            model=MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            options={'temperature': 0, 'num_ctx': 4096},
        )
        data = json.loads(response['message']['content'])
        return {
            'unit_price':       str(data.get('unit_price', 'N/A')),
            'manufacturer':     str(data.get('manufacturer', 'N/A')),
            'distributor':      str(data.get('distributor', 'N/A')),
            'min_order':        str(data.get('min_order', 'N/A')),
            'lead_time_weeks':  str(data.get('lead_time_weeks', 'N/A')),
            'notes':            str(data.get('notes', '')),
        }
    except Exception as e:
        print(f'  [PRICE] Ollama parse failed: {e}')
        return empty


def lookup_prices_for_bom(df):
    """
    Main price-lookup loop. (LD)
    For every row in the BOM DataFrame, queries DDG + Ollama and appends (LD)
    pricing columns. Returns a new DataFrame with OEMSecrets-compatible columns. (LD)
    """
    pn_col = _find_part_number_col(df)
    qty_col = _find_qty_col(df)

    if pn_col is None:
        print('[PRICE] No part-number column found — skipping price lookup')
        return _build_empty_output(df)

    print(f'[PRICE] Looking up prices for {len(df)} parts '
          f'(part col: {pn_col}, qty col: {qty_col or "none"})')

    rows_out = []
    for idx, row in df.iterrows():
        pn = str(row[pn_col]).strip()
        qty = str(row[qty_col]).strip() if qty_col else '1'

        # Build the output row with OEMSecrets column names (LD)
        out_row = {
            'Internal Reference':               '',
            'Part Number':                       pn,
            'Quantity for Single BOM':           qty,
            'Extended Quantity for 1 BOM':       qty,
            'Manufacturer':                      'N/A',
            'Distributor':                       'N/A',
            'Minimum Order':                     'N/A',
            'Unit Price in USD':                 0.0,
            'Lead Time on Additional Stock in Weeks': 'N/A',
            'Notes':                             '',
        }

        # Skip blank / placeholder part numbers (LD)
        if not pn or pn.lower() in ('n/a', 'nan', 'none', ''):
            rows_out.append(out_row)
            continue

        print(f'  [{idx + 1}/{len(df)}] Searching: {pn}')
        search_text = _search_ddg(pn)

        if search_text:
            price_data = _parse_price_with_ollama(pn, qty, search_text)
            out_row['Manufacturer'] = price_data['manufacturer']
            out_row['Distributor'] = price_data['distributor']
            out_row['Minimum Order'] = price_data['min_order']
            out_row['Lead Time on Additional Stock in Weeks'] = price_data['lead_time_weeks']
            out_row['Notes'] = price_data['notes']
            try:
                val = price_data['unit_price']
                out_row['Unit Price in USD'] = float(val) if val not in ('N/A', 'n/a', '', None) else ''
            except (ValueError, TypeError):
                out_row['Unit Price in USD'] = ''
        else:
            print(f'  [SKIP] No search results for {pn}')

        rows_out.append(out_row)
        time.sleep(SEARCH_DELAY)

    result_df = pd.DataFrame(rows_out, columns=OEM_COLUMNS)
    print(f'[PRICE] Price lookup complete — {len(result_df)} rows')
    return result_df


def _build_empty_output(df):
    """Return a zero-price DataFrame with OEMSecrets columns when lookup is skipped. (LD)"""
    n = len(df)
    return pd.DataFrame({
        'Internal Reference':               [''] * n,
        'Part Number':                       [''] * n,
        'Quantity for Single BOM':           ['1'] * n,
        'Extended Quantity for 1 BOM':       ['1'] * n,
        'Manufacturer':                      ['N/A'] * n,
        'Distributor':                       ['N/A'] * n,
        'Minimum Order':                     ['N/A'] * n,
        'Unit Price in USD':                 [0.0] * n,
        'Lead Time on Additional Stock in Weeks': ['N/A'] * n,
        'Notes':                             [''] * n,
    })


def main():
    """Entry point called by main_pipeline.py. (LD)"""
    input_path = os.environ.get('BOM_EXCEL_PATH')

    if not input_path:
        print('[PRICE] BOM_EXCEL_PATH not set')
        return

    if not Path(input_path).exists():
        print(f'[PRICE] Input file not found: {input_path}')
        return

    print(f'[PRICE] Loading BOM from: {input_path}')
    try:
        df = pd.read_excel(input_path, keep_default_na=False, na_values=[''])
    except Exception as e:
        print(f'[PRICE] Failed to read input file: {e}')
        return

    print(f'[PRICE] Loaded {len(df)} rows, columns: {df.columns.tolist()}')

    try:
        df_priced = lookup_prices_for_bom(df)
    except Exception as e:
        print(f'[PRICE] Price lookup failed: {e}')
        traceback.print_exc()
        df_priced = _build_empty_output(df)

    # Save with the same filename convention OEMSecrets used (LD)
    input_path_obj = Path(input_path)
    base = input_path_obj.stem.replace('_merged', '')
    output_path = input_path_obj.parent / f'{base}_merged_with_prices.xlsx'

    df_priced.to_excel(output_path, index=False)
    print(f'[PRICE] Saved: {output_path}')
