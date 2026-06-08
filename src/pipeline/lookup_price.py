"""
Price lookup for BOM components. (LD)
Strategy (in order, first hit wins per part):
  1. DuckDuckGo search → regex scan of snippets
  2. Direct Grainger/McMaster HTTP → regex scan of HTML
  3. Ollama knowledge estimate (guaranteed — model was trained on distributor catalogs)

Output matches OEMSecrets column schema so map_cost_sheet.py needs no changes. (LD)
"""

import os
import re
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────
MODEL      = os.environ.get('BOM_LLM_MODEL',      'llama3.2')
OLLAMA_HOST = os.environ.get('BOM_LLM_ENDPOINT', 'http://127.0.0.1:11434')
SEARCH_DELAY = 0.5   # seconds between parts (reduced — Ollama is local)

OEM_COLUMNS = [
    'Internal Reference', 'Part Number', 'Quantity for Single BOM',
    'Extended Quantity for 1 BOM', 'Manufacturer', 'Distributor',
    'Minimum Order', 'Unit Price in USD',
    'Lead Time on Additional Stock in Weeks', 'Notes',
]

# ── Prompts ──────────────────────────────────────────────────────────────────
_KNOWLEDGE_PROMPT = """You are an industrial electrical component pricing specialist.

Give your best estimated unit price in USD for this component based on your training knowledge of distributor pricing (Grainger, AutomationDirect, Galco, Mouser, Arrow, Digi-Key, etc.).

Manufacturer: {manufacturer}
Part Number:  {part_number}
Description:  {description}

Pricing guidance by component type:
- Small components (fuses, terminals, contacts, connectors, relays <10A): $1–$50
- Medium components (disconnects, pushbuttons, LED lights, small sensors): $20–$200
- Drives/VFDs (fractional to 10kW): $200–$2,000
- Drives/VFDs (11kW–100kW): $1,000–$15,000
- Transformers (< 1kVA): $50–$300
- Transformers (1–10kVA): $200–$2,000
- Cables and wiring duct (per unit): $5–$150
- Labels and marking (per unit): $5–$50
- PLCs and I/O modules: $100–$2,000
- Circuit breakers (molded case, <100A): $50–$500

Return ONLY this JSON — no explanation, no markdown:
{{"unit_price": "XX.XX", "distributor": "estimate", "notes": "training data estimate"}}

Rules:
- unit_price MUST be a positive number string — never "0.00" or "N/A" unless you truly have zero basis
- Round to 2 decimal places
- For completely unknown/custom parts use your best judgment based on similar components
"""


# ── Column finders ────────────────────────────────────────────────────────────

def _find_col(df, candidates, upper_kws=None):
    for name in candidates:
        if name in df.columns:
            return name
    if upper_kws:
        for col in df.columns:
            if any(kw in col.upper() for kw in upper_kws):
                return col
    return None

def _find_part_number_col(df):
    return _find_col(df,
        ['MPN', 'PART NO', 'PART NUMBER', 'PART#', 'P/N', 'PN', 'MODEL NO', 'MODEL',
         'Part Number', 'Part number'],
        ['MPN', 'PART', 'MODEL'])

def _find_qty_col(df):
    return _find_col(df,
        ['QTY', 'QTY.', 'QUANTITY', 'QUANT.', 'AMOUNT', 'Quantity', 'Qty'],
        ['QTY', 'QUANT'])

def _find_mfr_col(df):
    return _find_col(df,
        ['Manufacturer', 'MFR', 'MANUFACTURER', 'MFG', 'BRAND', 'MAKE'],
        ['MANUFACTURER', 'MFR', 'MFG'])

def _find_desc_col(df):
    return _find_col(df,
        ['DESCRIPTION', 'Description', 'DESC', 'Desc'],
        ['DESC'])


# ── Price regex ───────────────────────────────────────────────────────────────

_PRICE_RE = re.compile(
    r'\$\s*([\d,]{1,8}\.\d{2})'
    r'|USD\s*([\d,]{1,8}\.\d{2})'
    r'|([\d,]{1,8}\.\d{2})\s*USD'
    r'|"price"[:\s]*"([\d,]{1,8}\.\d{2})"'
    r'|"unitPrice"[:\s]*([\d,]{1,8}\.\d{2})'
    r'|data-unit-price=["\']?([\d,]{1,8}\.\d{2})'
    r'|(?:Price|Each|Unit|List|Net)[:\s]+\$?\s*([\d,]{1,8}\.\d{2})',
    re.IGNORECASE
)

def _parse_prices(text):
    """Extract all price values from text, return sorted list (lowest first)."""
    found = []
    for m in _PRICE_RE.finditer(text):
        for g in m.groups():
            if g:
                try:
                    v = float(g.replace(',', ''))
                    if 0 < v < 1_000_000:
                        found.append(v)
                except ValueError:
                    pass
    return sorted(found)


# ── Web price sources ─────────────────────────────────────────────────────────

def _ddg_price(pn, mfr):
    """DuckDuckGo search → regex. Returns (price_float, 'DDG') or None."""
    try:
        from duckduckgo_search import DDGS
        skip = {'', 'n/a', 'nan', 'none', 'generic'}
        prefix = f'{mfr} ' if mfr.lower() not in skip else ''
        queries = [
            f'{prefix}{pn} price buy distributor',
            f'"{pn}" price USD buy',
            f'{prefix}{pn} price',
        ]
        for q in queries:
            try:
                with DDGS(timeout=12) as ddgs:
                    results = list(ddgs.text(q, max_results=6))
                if results:
                    combined = ' '.join(
                        f"{r.get('title','')} {r.get('body','')}" for r in results
                    )
                    prices = _parse_prices(combined)
                    if prices:
                        return prices[0], 'web search'
            except Exception:
                pass
            time.sleep(0.5)
    except Exception as e:
        print(f'  [DDG] Error: {e}')
    return None


def _direct_price(pn, mfr):
    """Direct HTTP to Grainger / McMaster. Returns (price_float, site) or None."""
    try:
        import requests
        from urllib.parse import quote
        skip = {'', 'n/a', 'nan', 'none', 'generic'}
        mfr_clean = mfr.strip() if mfr.lower() not in skip else ''
        q = f'{mfr_clean} {pn}'.strip()
        hdrs = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        sites = [
            ('Grainger',  f'https://www.grainger.com/search?searchQuery={quote(q)}'),
            ('McMaster',  f'https://www.mcmaster.com/search/?query={quote(q)}'),
        ]
        for name, url in sites:
            try:
                r = requests.get(url, headers=hdrs, timeout=10)
                if r.status_code == 200:
                    prices = _parse_prices(r.text)
                    if prices:
                        return prices[0], name
            except Exception:
                pass
    except Exception:
        pass
    return None


def _ollama_knowledge_price(pn, mfr, desc, qty=1):
    """
    Ask Ollama to estimate the price from its training data. (LD)
    This is the guaranteed fallback — always returns a price.
    """
    try:
        import ollama
        prompt = _KNOWLEDGE_PROMPT.format(
            manufacturer=mfr or 'Unknown',
            part_number=pn,
            description=desc or 'N/A',
        )
        client = ollama.Client(host=OLLAMA_HOST)
        resp = client.chat(
            model=MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            options={'temperature': 0.1, 'num_ctx': 2048, 'num_predict': 256},
        )
        data = json.loads(resp['message']['content'])
        price_str = str(data.get('unit_price', '0')).strip()
        price = float(price_str)
        distributor = str(data.get('distributor', 'estimate'))
        notes = str(data.get('notes', 'training data estimate'))
        if price > 0:
            return price, distributor, notes
    except Exception as e:
        print(f'  [OLLAMA-EST] Failed: {e}')
    return None, 'estimate', 'training data estimate'


# ── Main lookup per part ──────────────────────────────────────────────────────

def _lookup_one(pn, mfr, desc, qty, label):
    """
    Try web sources in parallel, fall back to Ollama knowledge. (LD)
    Always returns (price, distributor, notes).
    """
    # Run DDG and direct-site in parallel
    web_price, web_source = None, None
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_ddg    = ex.submit(_ddg_price,    pn, mfr)
        f_direct = ex.submit(_direct_price, pn, mfr)
        for f in as_completed([f_ddg, f_direct], timeout=20):
            try:
                result = f.result()
                if result:
                    web_price, web_source = result
                    break
            except Exception:
                pass

    if web_price:
        print(f'  [WEB:{web_source}] ${web_price:.2f} for {label}')
        return web_price, web_source, ''

    # Guaranteed fallback: Ollama knowledge
    print(f'  [OLLAMA-EST] Estimating price for {label}...')
    price, distributor, notes = _ollama_knowledge_price(pn, mfr, desc, qty)
    if price:
        print(f'  [OLLAMA-EST] ~${price:.2f} for {label} (estimate)')
    else:
        print(f'  [MISS] No estimate possible for {label}')
    return price, distributor, notes


# ── BOM-level loop ────────────────────────────────────────────────────────────

def lookup_prices_for_bom(df):
    """Look up prices for every part in the BOM DataFrame. (LD)"""
    pn_col   = _find_part_number_col(df)
    qty_col  = _find_qty_col(df)
    mfr_col  = _find_mfr_col(df)
    desc_col = _find_desc_col(df)

    if pn_col is None:
        print('[PRICE] No MPN column found — skipping')
        return _build_empty_output(df)

    print(f'[PRICE] {len(df)} parts | MPN={pn_col} MFR={mfr_col} DESC={desc_col} QTY={qty_col}')

    rows_out = []
    for i, (_, row) in enumerate(df.iterrows()):
        pn   = str(row[pn_col]).strip()
        qty  = str(row[qty_col]).strip()  if qty_col  else '1'
        mfr  = str(row[mfr_col]).strip()  if mfr_col  else ''
        desc = str(row[desc_col]).strip() if desc_col else ''

        skip_vals = {'', 'n/a', 'nan', 'none'}
        mfr_disp  = mfr  if mfr.lower()  not in skip_vals else ''
        label     = f'{mfr_disp} {pn}'.strip() or f'row {i+1}'

        out = {
            'Internal Reference':                    '',
            'Part Number':                            pn,
            'Quantity for Single BOM':                qty,
            'Extended Quantity for 1 BOM':            qty,
            'Manufacturer':                           mfr or 'N/A',
            'Distributor':                            'N/A',
            'Minimum Order':                          'N/A',
            'Unit Price in USD':                      '',
            'Lead Time on Additional Stock in Weeks': 'N/A',
            'Notes':                                  '',
        }

        if not pn or pn.lower() in skip_vals:
            rows_out.append(out)
            continue

        print(f'  [{i+1}/{len(df)}] {label}')
        price, dist, notes = _lookup_one(pn, mfr_disp, desc, qty, label)

        if price:
            out['Unit Price in USD'] = round(price, 2)
            out['Distributor']       = dist or 'N/A'
            out['Notes']             = notes

        rows_out.append(out)
        time.sleep(SEARCH_DELAY)

    result_df = pd.DataFrame(rows_out, columns=OEM_COLUMNS)
    found = (result_df['Unit Price in USD'] != '').sum()
    print(f'[PRICE] Done — {found}/{len(result_df)} parts priced')
    return result_df


def _build_empty_output(df):
    n = len(df)
    return pd.DataFrame({c: [''] * n for c in OEM_COLUMNS})


def main():
    """Entry point called by main_pipeline.py via BOM_EXCEL_PATH env var. (LD)"""
    input_path = os.environ.get('BOM_EXCEL_PATH')
    if not input_path or not Path(input_path).exists():
        print(f'[PRICE] Input not found: {input_path}')
        return

    print(f'[PRICE] Loading: {input_path}')
    try:
        df = pd.read_excel(input_path, keep_default_na=False, na_values=[''])
    except Exception as e:
        print(f'[PRICE] Read failed: {e}')
        return

    print(f'[PRICE] {len(df)} rows, columns: {df.columns.tolist()}')

    try:
        df_priced = lookup_prices_for_bom(df)
    except Exception as e:
        print(f'[PRICE] Lookup failed: {e}')
        traceback.print_exc()
        df_priced = _build_empty_output(df)

    input_obj = Path(input_path)
    base      = input_obj.stem.replace('_merged', '')
    out_path  = input_obj.parent / f'{base}_merged_with_prices.xlsx'
    df_priced.to_excel(out_path, index=False)
    print(f'[PRICE] Saved: {out_path}')


if __name__ == '__main__':
    main()
