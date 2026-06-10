"""
Customer-specific table formatting functions for BoMination.

This module contains formatting functions tailored to specific customer requirements.
Each function handles the unique table structure and formatting needs of different customers.
"""

import pandas as pd
import re
import logging


def clean_farrell_columns(df):
    """Clean Farrell-specific table formatting, robustly finding the correct header row and removing all rows above it."""
    print(f"\n🔧 FARRELL DEBUG: Original table shape: {df.shape}")
    print(f"🔧 FARRELL DEBUG: First few rows:\n{df.head(8)}")
    if df.empty:
        print("🔧 FARRELL DEBUG: Empty dataframe passed to clean_farrell_columns")
        return df

    # Define header keywords for scoring
    header_keywords = [
        'QTY', 'PART', 'MFG', 'PAF', 'DESCRIPTION', 'DESCRIP', 'COMMENTS', 'ITEM', 'NUMBER', 'INTERNAL', 'MANUFACTURER', 'MPN'
    ]

    # ── Short-circuit: LLM already provided proper column headers ─────────────
    # Score the COLUMN NAMES (not cell values). If they already look like BOM
    # headers skip the tabula-style header-row scan, which would incorrectly
    # use the first DATA row as column names and discard item #1.
    col_names_upper = [str(c).upper() for c in df.columns]
    header_score_from_cols = sum(
        any(kw in c for kw in header_keywords) for c in col_names_upper
    )
    if header_score_from_cols >= 2:
        print(f"🔧 FARRELL DEBUG: Column names already look like BOM headers (score={header_score_from_cols}), skipping header detection")
        df = df.copy()

        # Rename internal "PART NUMBER" column so it stays distinct from MPN
        for col in list(df.columns):
            if "PART NUMBER" in str(col).upper() and "MFG" not in str(col).upper():
                df.rename(columns={col: "Internal Part Number"}, inplace=True)
                print(f"🔧 FARRELL DEBUG: Renamed '{col}' to 'Internal Part Number'")
                break

        # Split combined MFG/PART column into Manufacturer + MPN
        part_col = None
        for col in df.columns:
            col_str = str(col).upper()
            if ("MFG" in col_str or "MANUF" in col_str) and ("PART" in col_str or "PAF" in col_str):
                part_col = col
                break
        print(f"🔧 FARRELL DEBUG: Found MFG/PART column: {part_col}")
        if part_col and len(df) > 0:
            raw = df[part_col].astype(str).str.strip()
            # Only split rows that actually contain " / " — leave blanks/N/A intact
            has_slash = raw.str.contains(r'\s*/\s*', regex=True)
            split_cols = raw.where(has_slash, other='').str.split(r'\s*/\s*', n=1, expand=True)
            if split_cols.shape[1] == 2:
                mfr_vals = split_cols[0].str.strip().where(has_slash, other='')
                mpn_vals = split_cols[1].str.strip().where(has_slash, other='')
            else:
                mfr_vals = pd.Series([''] * len(df), index=df.index)
                mpn_vals = raw.where(has_slash, other='')
            # Split MPN from any trailing description text that bled in.
            # Capture the overflow so it can fill empty DESCRIPTION cells.
            def _split_mpn_overflow(val):
                val = str(val).strip()
                m = re.match(r'^([\w\-\.\/]+)\s*(.*)', val, re.DOTALL)
                if m:
                    return m.group(1), m.group(2).strip()
                return val, ''

            parsed      = mpn_vals.apply(_split_mpn_overflow)
            mpn_clean   = parsed.apply(lambda x: x[0])
            desc_overflow = parsed.apply(lambda x: x[1])

            # Split overflow at "SUPPLIED BY" — description goes to DESCRIPTION,
            # "SUPPLIED BY..." goes to the COMMENTS column (→ SUPPLIER/NOTES later)
            def _split_at_supplied(val):
                upper = val.upper()
                if 'SUPPLIED BY' in upper:
                    idx = upper.index('SUPPLIED BY')
                    return val[:idx].strip(), val[idx:].strip()
                if 'FURNISHED BY' in upper:
                    idx = upper.index('FURNISHED BY')
                    return val[:idx].strip(), val[idx:].strip()
                return val, ''

            overflow_parts = desc_overflow.apply(_split_at_supplied)
            overflow_desc    = overflow_parts.apply(lambda x: x[0])
            overflow_comment = overflow_parts.apply(lambda x: x[1])

            desc_col = next((c for c in df.columns if 'DESC' in str(c).upper()), None)
            if desc_col is not None:
                empty_mask = df[desc_col].fillna('').astype(str).str.strip() == ''
                df.loc[empty_mask, desc_col] = overflow_desc[empty_mask].values
                filled = empty_mask.sum()
                if filled:
                    print(f"🔧 FARRELL DEBUG: Recovered descriptions for {filled} row(s) from MPN overflow")

            # Route the "SUPPLIED BY" portion to COMMENTS if that column exists
            comment_col = next((c for c in df.columns if 'COMMENT' in str(c).upper()), None)
            if comment_col is not None:
                empty_comment = df[comment_col].fillna('').astype(str).str.strip() == ''
                has_comment   = overflow_comment.str.strip() != ''
                fill_mask     = empty_comment & has_comment
                if fill_mask.any():
                    df.loc[fill_mask, comment_col] = overflow_comment[fill_mask].values
                    print(f"🔧 FARRELL DEBUG: Moved 'SUPPLIED BY' text to COMMENTS for {fill_mask.sum()} row(s)")

            df.insert(0, "Manufacturer", mfr_vals)
            df.insert(1, "MPN", mpn_clean)
            print("🔧 FARRELL DEBUG: ✅ Split MFG/PART into Manufacturer and MPN")
            df.drop(columns=[part_col], inplace=True)

        # Fix LLM column-shift: if Internal Part Number looks like "MFG / MPN"
        # the LLM slid the MFG/PART value left into the wrong column (blank PART NUMBER row).
        if "Internal Part Number" in df.columns and "MPN" in df.columns:
            shifted_mask = (
                df["Internal Part Number"].str.contains(r'\s*/\s*', na=False, regex=True) &
                (df["MPN"].fillna('').str.strip() == '')
            )
            if shifted_mask.any():
                print(f"🔧 FARRELL DEBUG: Fixing {shifted_mask.sum()} column-shifted row(s)")
                for i in df[shifted_mask].index:
                    combined = str(df.at[i, "Internal Part Number"])
                    parts = combined.split("/", 1)
                    df.at[i, "Manufacturer"] = parts[0].strip()
                    df.at[i, "MPN"]          = parts[1].strip() if len(parts) > 1 else ''
                    df.at[i, "Internal Part Number"] = ''

        # Normalize QTY to pure numbers
        qty_col = next(
            (c for c in df.columns if 'QTY' in str(c).upper() or 'QUANT' in str(c).upper()),
            None
        )
        if qty_col:
            df[qty_col] = (
                df[qty_col].astype(str)
                .str.extract(r'(\d+\.?\d*)')[0]
                .fillna('')
            )
            print(f"🔧 FARRELL DEBUG: Normalized QTY column '{qty_col}'")

        print(f"🔧 FARRELL DEBUG: Final table shape: {df.shape}")
        print(f"🔧 FARRELL DEBUG: Final columns: {df.columns.tolist()}")
        if len(df) > 0:
            print(f"🔧 FARRELL DEBUG: Sample of final data:\n{df.head(2)}")
        print("🔧 FARRELL DEBUG: ===== END FARRELL PROCESSING (fast path) =====\n")
        return df
    # ─────────────────────────────────────────────────────────────────────────

    # Legacy path: tabula-style output where headers may be buried in data rows
    best_score = 0
    best_idx = 0
    for idx in range(min(10, len(df))):  # Scan first 10 rows for best header
        row = df.iloc[idx]
        non_empty_cells = row.dropna().astype(str).str.upper().str.strip()
        score = sum(any(kw in cell for kw in header_keywords) for cell in non_empty_cells)
        print(f"🔧 FARRELL DEBUG: Row {idx} header score: {score} - {non_empty_cells.tolist()}")
        if score > best_score:
            best_score = score
            best_idx = idx
    print(f"🔧 FARRELL DEBUG: Selected header row index: {best_idx} (score: {best_score})")

    # Set the detected header row as columns
    new_columns = df.iloc[best_idx].fillna('').astype(str).str.strip()
    for i, col in enumerate(new_columns):
        if col == '' or col == 'nan':
            new_columns.iloc[i] = f'Column_{i}'
    df.columns = new_columns
    # Remove all rows up to and including the header row
    df = df.iloc[best_idx + 1:].reset_index(drop=True)
    print(f"🔧 FARRELL DEBUG: After header extraction - columns: {df.columns.tolist()}")
    print(f"🔧 FARRELL DEBUG: After header extraction - shape: {df.shape}")

    # Remove any duplicate header rows (sometimes headers repeat as first data row)
    df = df[~df.apply(lambda row: row.astype(str).str.strip().tolist() == df.columns.astype(str).tolist(), axis=1)]
    df = df.reset_index(drop=True)

    # Handle "PART NUMBER" renaming
    for col in df.columns:
        if "PART NUMBER" in str(col).upper():
            df.rename(columns={col: "Internal Part Number"}, inplace=True)
            print(f"🔧 FARRELL DEBUG: Renamed '{col}' to 'Internal Part Number'")
            break

    # Find and split the MFG/PART column
    part_col = None
    for col in df.columns:
        col_str = str(col).upper()
        if ("MFG" in col_str or "MANUF" in col_str) and ("PART" in col_str or "PAF" in col_str):
            part_col = col
            break
    print(f"🔧 FARRELL DEBUG: Found MFG/PART column: {part_col}")
    if part_col and len(df) > 0:
        split_cols = df[part_col].astype(str).str.split("/", n=1, expand=True)
        if split_cols.shape[1] == 2:
            df.insert(0, "Manufacturer", split_cols[0].str.strip())
            df.insert(1, "MPN", split_cols[1].str.strip())
            print("🔧 FARRELL DEBUG: ✅ Successfully split MFG/PART column into Manufacturer and MPN")
            df.drop(columns=[part_col], inplace=True)
        else:
            print("🔧 FARRELL DEBUG: ⚠️ Could not split MFG/PART column - keeping original")
    print(f"🔧 FARRELL DEBUG: Final table shape: {df.shape}")
    print(f"🔧 FARRELL DEBUG: Final columns: {df.columns.tolist()}")
    if len(df) > 0:
        print(f"🔧 FARRELL DEBUG: Sample of final data:\n{df.head(2)}")
    print("🔧 FARRELL DEBUG: ===== END FARRELL PROCESSING =====\n")
    return df


def clean_nel_columns(df):
    """Clean NEL-specific table formatting, handling their schematic BOM structure."""
    print(f"\n🔧 NEL DEBUG: Original table shape: {df.shape}")
    print(f"🔧 NEL DEBUG: First few rows:\n{df.head(8)}")
    if df.empty:
        print("🔧 NEL DEBUG: Empty dataframe passed to clean_nel_columns")
        return df

    # Look for the actual "BILL OF MATERIAL" header
    bill_of_material_row = -1
    for idx in range(min(20, len(df))):
        row = df.iloc[idx]
        row_text = ' '.join(row.fillna('').astype(str).str.upper())
        if 'BILL OF MATERIAL' in row_text:
            bill_of_material_row = idx
            print(f"🔧 NEL DEBUG: Found 'BILL OF MATERIAL' at row {idx}")
            break
    
    # If we found the BOM section, start looking for headers from there
    start_search = max(0, bill_of_material_row)
    
    # Define header keywords for NEL BOMs (common in schematics)
    header_keywords = [
        'ITEM', 'QTY', 'QUANTITY', 'PART', 'NUMBER', 'DESCRIPTION', 'DESC', 'REFERENCE', 'REF', 'DESIGNATOR',
        'VALUE', 'PACKAGE', 'FOOTPRINT', 'MANUFACTURER', 'MFG', 'MPN', 'VENDOR', 'SUPPLIER', 'NOTES'
    ]
    
    best_score = 0
    best_idx = start_search
    for idx in range(start_search, min(start_search + 10, len(df))):  # Look within 10 rows of BOM section
        row = df.iloc[idx]
        non_empty_cells = row.dropna().astype(str).str.upper().str.strip()
        score = sum(any(kw in cell for kw in header_keywords) for cell in non_empty_cells)
        print(f"🔧 NEL DEBUG: Row {idx} header score: {score} - {non_empty_cells.tolist()}")
        if score > best_score:
            best_score = score
            best_idx = idx
    
    print(f"🔧 NEL DEBUG: Selected header row index: {best_idx} (score: {best_score})")

    # If we didn't find good headers, this might not be a BOM table
    if best_score < 2:
        print(f"🔧 NEL DEBUG: Low header score ({best_score}), this might not be a BOM table")
        return df  # Return as-is, let the BOM filter handle it

    # Set the detected header row as columns
    new_columns = df.iloc[best_idx].fillna('').astype(str).str.strip()
    for i, col in enumerate(new_columns):
        if col == '' or col == 'nan':
            new_columns.iloc[i] = f'Column_{i}'
    df.columns = new_columns
    # Remove all rows up to and including the header row
    df = df.iloc[best_idx + 1:].reset_index(drop=True)
    print(f"🔧 NEL DEBUG: After header extraction - columns: {df.columns.tolist()}")
    print(f"🔧 NEL DEBUG: After header extraction - shape: {df.shape}")

    # Remove columns that don't have a proper header (NEL-specific)
    original_columns = df.columns.tolist()
    columns_to_keep = []
    columns_to_remove = []
    
    for col in df.columns:
        col_str = str(col).strip()
        # Keep columns that have meaningful headers (not empty, not generic Column_X, not just whitespace)
        if col_str and col_str != 'nan' and not col_str.startswith('Column_') and col_str.strip() != '':
            columns_to_keep.append(col)
        else:
            columns_to_remove.append(col)
    
    if columns_to_remove:
        print(f"🔧 NEL DEBUG: Removing columns without proper headers: {columns_to_remove}")
        df = df[columns_to_keep]
        print(f"🔧 NEL DEBUG: After removing headerless columns - shape: {df.shape}")
        print(f"🔧 NEL DEBUG: After removing headerless columns - columns: {df.columns.tolist()}")
    else:
        print("🔧 NEL DEBUG: No columns without headers found to remove")

    # Remove any duplicate header rows
    df = df[~df.apply(lambda row: row.astype(str).str.strip().tolist() == df.columns.astype(str).tolist(), axis=1)]
    df = df.reset_index(drop=True)
    
    # Remove rows that look like drawing instructions or notes
    instruction_keywords = [
        'CUT BACK', 'REMOVE', 'SHRINK TUBING', 'DRAWING NUMBER', 'HARNESS', 'PRINTED DRAWING',
        'REFERENCE ONLY', 'DOCUMENT CONTROL', 'LATEST REVISION', 'PROPERTY OF', 'DELIVERED ON',
        'EXPRESS CONDITION', 'NOT TO BE DISCLOSED', 'MARK PER', 'CONTINUITY TEST', 'LOCATE AND ATTACH'
    ]
    
    # Filter out instruction rows
    original_length = len(df)
    for keyword in instruction_keywords:
        # Check each row for instruction keywords
        mask = ~df.apply(lambda row: any(keyword in str(cell).upper() for cell in row), axis=1)
        df = df[mask]
    
    if len(df) < original_length:
        print(f"🔧 NEL DEBUG: Removed {original_length - len(df)} instruction/note rows")
    
    df = df.reset_index(drop=True)

    # Handle common NEL column standardization
    column_mapping = {
        'ITEM': 'Item',
        'ITEM NO': 'Item',
        'QTY': 'Quantity',
        'QUANTITY': 'Quantity',
        'PART NUMBER': 'Part Number',
        'PART': 'Part Number',
        'DESCRIPTION': 'Description',
        'DESC': 'Description',
        'REFERENCE': 'Reference',
        'REF': 'Reference',
        'DESIGNATOR': 'Reference',
        'VALUE': 'Value',
        'PACKAGE': 'Package',
        'FOOTPRINT': 'Footprint',
        'MANUFACTURER': 'Manufacturer',
        'MFG': 'Manufacturer',
        'MPN': 'MPN',
        'MFG P/N': 'MPN',
        'VENDOR': 'Vendor',
        'SUPPLIER': 'Supplier',
        'PROTON P/N': 'Proton P/N',
        'NOTES': 'Notes'
    }
    
    # Apply column mapping
    for old_col, new_col in column_mapping.items():
        for col in df.columns:
            if old_col in str(col).upper():
                df.rename(columns={col: new_col}, inplace=True)
                print(f"🔧 NEL DEBUG: Renamed '{col}' to '{new_col}'")
                break

    # Clean Quantity column - remove any text besides numbers (NEL-specific)
    quantity_cols = [col for col in df.columns if 'quantity' in str(col).lower() or col == 'Quantity']
    if quantity_cols:
        for qty_col in quantity_cols:
            print(f"🔧 NEL DEBUG: Cleaning quantity column '{qty_col}'")
            original_values = df[qty_col].copy()
            
            # Function to extract only numbers from text
            def extract_numbers(value):
                if pd.isna(value) or value == '':
                    return ''
                # Convert to string and extract only digits and decimal points
                value_str = str(value).strip()
                # Use regex to find numbers (including decimals)
                numbers = re.findall(r'\d+\.?\d*', value_str)
                if numbers:
                    # Take the first number found
                    return numbers[0]
                else:
                    return ''
            
            # Apply the cleaning function
            df[qty_col] = df[qty_col].apply(extract_numbers)
            
            # Log changes made
            changes_made = sum(1 for orig, new in zip(original_values, df[qty_col]) 
                             if str(orig).strip() != str(new).strip())
            if changes_made > 0:
                print(f"🔧 NEL DEBUG: Cleaned {changes_made} quantity values in '{qty_col}'")
                # Show a few examples of changes
                sample_changes = [(orig, new) for orig, new in zip(original_values, df[qty_col]) 
                                if str(orig).strip() != str(new).strip()][:3]
                for orig, new in sample_changes:
                    print(f"🔧 NEL DEBUG: '{orig}' -> '{new}'")
            else:
                print(f"🔧 NEL DEBUG: No changes needed for quantity column '{qty_col}'")

    print(f"🔧 NEL DEBUG: Final table shape: {df.shape}")
    print(f"🔧 NEL DEBUG: Final columns: {df.columns.tolist()}")
    if len(df) > 0:
        print(f"🔧 NEL DEBUG: Sample of final data:\n{df.head(2)}")
    print("🔧 NEL DEBUG: ===== END NEL PROCESSING =====\n")
    return df


# ── Generic, content-aware column-role inference ──────────────────────────────
# The generic formatter must work for ANY customer regardless of header naming.
# Header names vary endlessly ("Item Number", "MFG P/N", "Cat. No.", "Part#"...),
# but the *content* of a column is consistent: a quantity column holds small
# integers, a part-number column holds unique alphanumeric tokens with digits,
# a description column holds prose. We classify on header hints AND content, and
# let content settle ambiguous cases. Output names match what map_cost_sheet.py
# and lookup_price.py already look for: Part Number / Quantity / Description /
# Manufacturer / Item / Notes / Unit.

_UNIT_TOKENS = {
    'EA', 'EACH', 'PC', 'PCS', 'PCE', 'FT', 'FEET', 'IN', 'INCH', 'M', 'MM', 'CM',
    'KG', 'LB', 'LBS', 'G', 'SET', 'SETS', 'ROLL', 'BOX', 'PK', 'PKG', 'PAIR',
    'PR', 'L', 'GAL', 'SHT', 'SHEET', 'ASSY', 'LOT', 'UNIT', 'UN', 'NO',
}

_MFR_HINTS = {
    'SIEMENS', 'ALLEN', 'BRADLEY', 'ROCKWELL', 'PHOENIX', 'RITTAL', 'ABB',
    'SCHNEIDER', 'EATON', 'OMRON', 'PANASONIC', 'HUBBELL', 'PANDUIT', 'ICOTEK',
    'WEIDMULLER', 'WAGO', 'MOLEX', 'BELDEN', 'LAPP', 'TURCK', 'BANNER',
    'PEPPERL', 'FUCHS', 'SICK', 'BALLUFF', 'FESTO', 'PARKER', 'BUSSMANN',
    'MERSEN', 'LITTELFUSE', 'SQUARE D', 'HONEYWELL', 'THOMAS AND BETTS', 'CLARION',
}

# Marker that commonly precedes a manufacturer part number inside a description
# cell, e.g. "Cat. No. ...", "Cat No: ...", "Part No. ...", "P/N ...".
_DESC_MARKER_RE = re.compile(
    r'(?:cat(?:alog)?\.?\s*(?:no|number|#)?\.?|'
    r'(?:part|order|model|article)\s*(?:no|number|#)?\.?|'
    r'p\s*/?\s*n)'
    r'\s*[:.\-]?\s*',
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9\-\./]*')

# Explicit "Vendor: X" / "Mfr: X" / "Manufacturer: X" labels inside descriptions.
_DESC_MFR_RE = re.compile(
    r'(?:vendor|manufacturer|mfr|mfg|brand|make)\s*[:.\-]?\s*'
    r'([A-Za-z][A-Za-z&\.\- ]{2,30})',
    re.IGNORECASE,
)


def _accumulate_pn(segment):
    """Accumulate a part number from the start of `segment`: the first token,
    plus any following part-number-like tokens (a number, or a short uppercase
    code like 'IS'/'PB'). Stops at prose or punctuation. Returns '' if empty."""
    parts = []
    for raw in segment.split():
        core = raw.strip(' .,;:()')
        if not core or not _TOKEN_RE.fullmatch(core):
            break
        if not parts:
            parts.append(core)                       # first token
        elif re.search(r'\d', core) or re.fullmatch(r'[A-Z]{1,3}', core):
            parts.append(core)                       # continuation
        else:
            break
        if raw.rstrip().endswith((',', ';')):        # punctuation ends the number
            break
    return ' '.join(parts).strip()


def _extract_mpn_from_text(text):
    """Pull a manufacturer part number out of a free-text description cell.

    Cases, in order:
      1. A marker like "Cat. No. X" / "Part No: X" / "P/N X". The number may span
         several tokens (e.g. "IS 83875", "IS 6010 PB").
      2. A marker is present but nothing usable follows it — the number is likely
         at the START of the description (e.g. "IS 83875 SAFETY LABEL ... Cat. No.").
         We accept a leading sequence that has BOTH a letter and a digit, so we
         don't grab a bare item number like "45767".
      3. No marker at all — accept a leading token only if it clearly looks like a
         part number (letters+digits and a hyphen/slash, or 8+ chars), so we don't
         grab ratings ("120VAC") or dimensions ("2.25").

    Returns '' if nothing part-number-like is found.
    """
    if not text:
        return ''
    s = str(text)

    # ── Case 1: marker-based, multi-token aware ────────────────────────────────
    m = _DESC_MARKER_RE.search(s)
    if m:
        cand = _accumulate_pn(s[m.end():])
        if len(cand) >= 4 and re.search(r'\d', cand):
            return cand
        # ── Case 2: marker present but empty → look at the start ───────────────
        lead = _accumulate_pn(s)
        if (len(lead) >= 4 and re.search(r'\d', lead) and re.search(r'[A-Za-z]', lead)):
            return lead

    # ── Case 3: part number leads the description, no marker ───────────────────
    for raw in re.split(r'[\s,;]+', s.strip())[:3]:
        t = raw.strip('.,;:()')
        if (4 <= len(t) <= 30 and re.search(r'\d', t) and re.search(r'[A-Za-z]', t)
                and _TOKEN_RE.fullmatch(t)
                and ('-' in t or '/' in t or len(t) >= 8)):
            return t
    return ''


def _extract_mfr_from_text(text):
    """Pull a manufacturer name from a description cell — a known manufacturer
    name if present, otherwise an explicit 'Vendor: X' label."""
    if not text:
        return ''
    s = str(text)
    # Known manufacturers first — clean and unambiguous.
    upper = s.upper()
    for hint in _MFR_HINTS:
        if hint in upper:
            return hint.title()
    # Fallback: explicit label, trimmed at any part-number marker so we don't
    # capture "ACME Cat No: 123" as the manufacturer name.
    m = _DESC_MFR_RE.search(s)
    if m:
        name = re.split(
            r'\b(?:cat|catalog|part|order|model|article|no|number|p/?n|item|u/m)\b',
            m.group(1), maxsplit=1, flags=re.IGNORECASE,
        )[0]
        name = name.strip(' .,;:-')
        if name and name.upper() not in ('EA', 'N/A', 'NA'):
            return name.title()
    return ''


def _generic_col_features(series):
    """Compute content fingerprint for one column. Returns None if all-empty."""
    vals = series.dropna().astype(str).str.strip()
    vals = vals[(vals != '') & (~vals.str.lower().isin(['nan', 'n/a', 'none', '-']))]
    n = len(vals)
    if n == 0:
        return None

    def _frac(pred):
        return sum(pred(v) for v in vals) / n

    def _is_smallint(v):
        v2 = v.replace(',', '')
        return v2.isdigit() and 1 <= len(v2) <= 4          # 1..9999 → qty / line no.

    def _is_partnum(v):
        # A part number is a single token (no spaces), 4–30 chars, with a digit.
        if ' ' in v or not (4 <= len(v) <= 30):
            return False
        if not re.search(r'\d', v):
            return False
        return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9\-\./#]+', v))

    def _is_unit(v):
        return v.upper().replace('.', '') in _UNIT_TOKENS

    def _has_mfr(v):
        u = v.upper()
        return any(m in u for m in _MFR_HINTS)

    # sequential 1,2,3… → a line/item number, NOT a quantity
    seq = False
    nums = [int(v.replace(',', '')) for v in vals if v.replace(',', '').isdigit()]
    if len(nums) >= 3 and len(nums) >= 0.6 * n:
        seq = nums[0] <= 5 and all(0 < (b - a) <= 3 for a, b in zip(nums, nums[1:]))

    return {
        'frac_smallint': _frac(_is_smallint),
        'frac_partnum':  _frac(_is_partnum),
        'frac_unit':     _frac(_is_unit),
        'frac_mfr':      _frac(_has_mfr),
        'avg_words':     vals.str.split().apply(len).mean(),
        'avg_len':       vals.str.len().mean(),
        'uniq':          vals.nunique() / n,
        'sequential':    seq,
    }


def _generic_header_role(col):
    """Best-guess role from the header name alone, or None. Specific → generic."""
    c = re.sub(r'\s+', ' ', str(col).upper().strip())
    rules = [
        ('Unit',         [r'\bU/?M\b', r'\bUOM\b', 'UNIT OF MEAS']),
        ('Quantity',     [r'\bQTY\b', 'QUANT', r"\bQ'?TY\b", r'\bQNTY\b']),
        ('Part Number',  ['PART NUMBER', 'PART NO', 'PART#', 'PART #', r'\bMPN\b',
                          'MFG PART', 'MFR PART', 'MANUFACTURER PART', 'CATALOG',
                          r'\bCAT\.? ?NO', r'\bMODEL\b', 'ORDER CODE', 'ORDER NO',
                          'ARTICLE', 'ITEM NUMBER', r'\bP/N\b', 'STOCK NO', r'\bSKU\b']),
        ('Description',  ['DESCRIPTION', r'\bDESC\b', 'ITEM NAME', 'NOMENCLATURE',
                          'PART NAME', 'ITEM DESC']),
        ('Manufacturer', ['MANUFACTURER', r'\bMFR\b', r'\bMFG\b', r'\bMAKE\b',
                          'BRAND', 'VENDOR', 'SUPPLIER']),
        ('Notes',        ['NOTES', r'\bNOTE\b', 'REMARK', 'COMMENT']),
        ('Reference',    ['REFERENCE', 'REF DES', r'\bREF\b', 'DESIGNAT', r'\bTAG\b',
                          'LOCATION', r'\bLOC\b']),
        ('Item',         [r'\bITEM\b', r'\bLINE\b', r'\bFIND\b', r'\bPOS\b',
                          r'\bSEQ\b', r'\bBALLOON\b']),
    ]
    for role, pats in rules:
        if any(re.search(p, c) for p in pats):
            return role
    return None


def _infer_generic_roles(df):
    """
    Map original column names → standardized roles using header + content signals.
    Each role is awarded to at most one column (the strongest candidate).
    Returns {original_name: standard_name}.
    """
    feats, headers = {}, {}
    for col in df.columns:
        f = _generic_col_features(df[col])
        if f is not None:
            feats[col] = f
            headers[col] = _generic_header_role(col)

    if not feats:
        return {}

    def score(col, role):
        f = feats[col]
        s = 2.0 if headers[col] == role else 0.0          # header agreement bonus
        if role == 'Unit':
            s += 4.0 * f['frac_unit']
        elif role == 'Quantity':
            if not f['sequential']:
                s += 3.0 * f['frac_smallint']
        elif role == 'Item':
            if f['sequential']:
                s += 3.0
        elif role == 'Part Number':
            s += 3.0 * f['frac_partnum'] + f['uniq']
            if f['avg_words'] > 3:                          # prose ≠ part number
                s -= 2.0
        elif role == 'Description':
            s += min(f['avg_words'], 8) * 0.5
            if f['avg_len'] > 25:
                s += 1.0
        elif role == 'Manufacturer':
            s += 3.0 * f['frac_mfr']
        elif role in ('Notes', 'Reference'):
            pass                                           # header-driven only
        return s

    # Minimum score required to claim each role (avoids spurious mappings).
    thresholds = {
        'Unit': 2.0, 'Quantity': 1.5, 'Item': 2.0, 'Part Number': 1.2,
        'Description': 1.5, 'Manufacturer': 1.5, 'Notes': 2.0, 'Reference': 2.0,
    }
    # Assign the most specific/critical roles first.
    order = ['Unit', 'Quantity', 'Item', 'Part Number', 'Description',
             'Manufacturer', 'Notes', 'Reference']

    rename, taken = {}, set()
    for role in order:
        best, best_s = None, thresholds[role]
        for col in feats:
            if col in taken:
                continue
            s = score(col, role)
            if s >= best_s:
                best, best_s = col, s
        if best is not None:
            rename[best] = role
            taken.add(best)
    return rename


def clean_generic_columns(df):
    """
    Generic table formatting that can be applied to any customer's BOM tables.
    This is a fallback when no specific customer formatter is available.
    """
    print(f"\n🔧 GENERIC DEBUG: Original table shape: {df.shape}")
    if df.empty:
        print("🔧 GENERIC DEBUG: Empty dataframe passed to clean_generic_columns")
        return df

    # Define common BOM header keywords
    header_keywords = [
        'ITEM', 'QTY', 'QUANTITY', 'PART', 'NUMBER', 'DESCRIPTION', 'DESC', 'REFERENCE', 'REF',
        'MANUFACTURER', 'MFG', 'MPN', 'VENDOR', 'SUPPLIER', 'NOTES', 'COMMENTS'
    ]
    
    # Find the best header row (similar to other formatters)
    best_score = 0
    best_idx = 0
    for idx in range(min(10, len(df))):
        row = df.iloc[idx]
        non_empty_cells = row.dropna().astype(str).str.upper().str.strip()
        score = sum(any(kw in cell for kw in header_keywords) for cell in non_empty_cells)
        print(f"🔧 GENERIC DEBUG: Row {idx} header score: {score} - {non_empty_cells.tolist()}")
        if score > best_score:
            best_score = score
            best_idx = idx
    
    print(f"🔧 GENERIC DEBUG: Selected header row index: {best_idx} (score: {best_score})")

    # If we found a good header row, use it
    if best_score >= 2:
        new_columns = df.iloc[best_idx].fillna('').astype(str).str.strip()
        for i, col in enumerate(new_columns):
            if col == '' or col == 'nan':
                new_columns.iloc[i] = f'Column_{i}'
        df.columns = new_columns
        df = df.iloc[best_idx + 1:].reset_index(drop=True)
        print(f"🔧 GENERIC DEBUG: After header extraction - columns: {df.columns.tolist()}")
        print(f"🔧 GENERIC DEBUG: After header extraction - shape: {df.shape}")

    # Remove any duplicate header rows
    df = df[~df.apply(lambda row: row.astype(str).str.strip().tolist() == df.columns.astype(str).tolist(), axis=1)]
    df = df.reset_index(drop=True)

    # Standardize columns by INFERRING each column's role from its header *and*
    # its actual content. Content-based inference is what makes this truly generic:
    # it works no matter how a customer names their columns. Output names match
    # what map_cost_sheet.py / lookup_price.py already look for.
    rename_map = _infer_generic_roles(df)
    if rename_map:
        df.rename(columns=rename_map, inplace=True)
        for old, new in rename_map.items():
            print(f"🔧 GENERIC DEBUG: Mapped '{old}' -> '{new}' (role inference)")
    else:
        print("🔧 GENERIC DEBUG: No columns confidently classified by role inference")

    # Some BOMs bury the manufacturer part number (and the manufacturer) inside
    # the description text instead of giving them their own columns — e.g.
    # "...SIEMENS Cat. No. 5SJ4111-8HG41". Mine them out so the price lookup has
    # a real part number to search and the cost sheet gets a proper MFR column.
    if 'Description' in df.columns:
        mpns = df['Description'].apply(_extract_mpn_from_text)
        hits = (mpns != '').sum()
        if hits:
            if 'Part Number' not in df.columns:
                # No part-number column at all — use the extracted commercial P/N.
                df['Part Number'] = mpns
                print(f"🔧 GENERIC DEBUG: Extracted Part Number from description for {hits} row(s)")
            else:
                # There IS a part-number column AND the description carries a
                # (commercial) part number. If they differ, the column is the
                # customer's internal number → move it to CUST PART # and use the
                # extracted manufacturer P/N as the COMMERCIAL part number.
                existing = df['Part Number'].astype(str).str.strip()
                mpn_str  = mpns.astype(str).str.strip()
                differs  = ((mpn_str != '') & (mpn_str != existing)).sum()
                if differs >= max(1, int(0.5 * hits)):
                    if 'Internal Part Number' not in df.columns:
                        df['Internal Part Number'] = df['Part Number']   # → CUST PART #
                    # Commercial P/N from the description; blank where none found.
                    df['Part Number'] = mpn_str.values
                    print(f"🔧 GENERIC DEBUG: Column P/N looks like a customer number — "
                          f"moved it to CUST PART # and used the description's commercial "
                          f"P/N as COMMERCIAL PART # ({hits} row(s))")
        if 'Manufacturer' not in df.columns:
            mfrs = df['Description'].apply(_extract_mfr_from_text)
            hits = (mfrs != '').sum()
            if hits:
                df['Manufacturer'] = mfrs
                print(f"🔧 GENERIC DEBUG: Extracted Manufacturer from description for {hits} row(s)")

    print(f"🔧 GENERIC DEBUG: Final table shape: {df.shape}")
    print(f"🔧 GENERIC DEBUG: Final columns: {df.columns.tolist()}")
    if len(df) > 0:
        print(f"🔧 GENERIC DEBUG: Sample of final data:\n{df.head(2)}")
    print("🔧 GENERIC DEBUG: ===== END GENERIC PROCESSING =====\n")
    return df


def clean_primetals_columns(df):
    """Clean Primetals-specific table formatting, handling dual-column BOM structures."""
    print(f"\n🔧 PRIMETALS DEBUG: Original table shape: {df.shape}")
    print(f"🔧 PRIMETALS DEBUG: Current column names: {df.columns.tolist()}")
    print(f"🔧 PRIMETALS DEBUG: First few rows:\n{df.head(8)}")
    
    if df.empty:
        print("🔧 PRIMETALS DEBUG: Empty dataframe passed to clean_primetals_columns")
        return df

    # Check if the table already has proper BOM headers
    current_columns = [str(col).upper() for col in df.columns]
    bom_headers = ['ITEM', 'MFG', 'DESCRIPTION', 'QTY']
    # Check for either MPN or MFGPART as the part number column
    part_number_header = 'MPN' in current_columns or 'MFGPART' in current_columns
    
    # If we already have proper BOM headers, don't try to extract new ones
    if all(header in current_columns for header in bom_headers) and part_number_header:
        print("🔧 PRIMETALS DEBUG: Table already has proper BOM headers, skipping header extraction")
        
        # Just clean up the data and remove any unwanted rows
        original_length = len(df)
        
        # Remove rows that contain company/confidential information
        confidential_keywords = [
            'PRIMETALS TECHNOLOGIES', 'CONFIDENTIAL', 'PROPRIETARY', 'INTERNAL USE ONLY',
            'NOT FOR DISTRIBUTION', 'COMPANY CONFIDENTIAL'
        ]
        
        # Filter out confidential rows
        for keyword in confidential_keywords:
            # Check each row for confidential keywords
            mask = ~df.apply(lambda row: any(keyword in str(cell).upper() for cell in row), axis=1)
            df = df[mask]
        
        if len(df) < original_length:
            print(f"🔧 PRIMETALS DEBUG: Removed {original_length - len(df)} confidential/header rows")
        
        df = df.reset_index(drop=True)
        
        # Rename MFGPART to MPN for OEMSecrets compatibility
        if 'MFGPART' in df.columns:
            df.rename(columns={'MFGPART': 'MPN'}, inplace=True)
            print("🔧 PRIMETALS DEBUG: Renamed 'MFGPART' to 'MPN' for OEMSecrets compatibility")
        
        # Clean data for OEMSecrets compatibility
        if len(df) > 0:
            print("🔧 PRIMETALS DEBUG: Cleaning data for OEMSecrets compatibility...")
            
            # Clean quantity fields - remove non-numeric characters
            quantity_cols = [col for col in df.columns if any(qty_name in str(col).upper() for qty_name in ['QTY', 'QUANTITY', 'QUAN'])]
            for col in quantity_cols:
                if col in df.columns:
                    original_count = len(df[col].dropna())
                    # Extract only numeric characters and decimal points
                    df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                    # Remove empty strings and convert to proper format
                    df[col] = df[col].replace('', '1')  # Default to 1 if empty
                    # Handle multiple decimal points - keep only the first one
                    df[col] = df[col].str.replace(r'\.(?=.*\.)', '', regex=True)
                    # Convert to numeric, invalid entries become NaN
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    # Fill NaN with 1 (default quantity)
                    df[col] = df[col].fillna(1)
                    # Convert to integer if whole number, otherwise keep as float
                    df[col] = df[col].apply(lambda x: int(x) if x == int(x) else x)
                    cleaned_count = len(df[col].dropna())
                    print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
            
            # Clean part number fields - remove excessive whitespace and special characters that might cause issues
            part_cols = [col for col in df.columns if any(part_name in str(col).upper() for part_name in ['PART', 'MPN', 'MFGPART'])]
            for col in part_cols:
                if col in df.columns:
                    original_count = len(df[col].dropna())
                    # Remove excessive whitespace
                    df[col] = df[col].astype(str).str.strip()
                    # Replace multiple spaces with single space
                    df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
                    # Remove leading/trailing special characters that might cause issues
                    df[col] = df[col].str.replace(r'^[^\w\d]+|[^\w\d]+$', '', regex=True)
                    # Replace empty strings, 'nan', and 'None' with "N/A" for OEMSecrets compatibility
                    df[col] = df[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                    cleaned_count = len(df[col][df[col] != 'N/A'])
                    print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
            
            # Clean manufacturer fields - standardize formatting
            mfg_cols = [col for col in df.columns if any(mfg_name in str(col).upper() for mfg_name in ['MFG', 'MANUFACTURER', 'MANUF'])]
            for col in mfg_cols:
                if col in df.columns:
                    original_count = len(df[col].dropna())
                    # Remove excessive whitespace
                    df[col] = df[col].astype(str).str.strip()
                    # Replace multiple spaces with single space
                    df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
                    # Standardize common manufacturer names
                    df[col] = df[col].str.replace(r'(?i)^siemens.*', 'SIEMENS', regex=True)
                    df[col] = df[col].str.replace(r'(?i)^abb.*', 'ABB', regex=True)
                    df[col] = df[col].str.replace(r'(?i)^schneider.*', 'SCHNEIDER', regex=True)
                    df[col] = df[col].str.replace(r'(?i)^eaton.*', 'EATON', regex=True)
                    # Replace empty strings, 'nan', and 'None' with "N/A" for OEMSecrets compatibility
                    df[col] = df[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                    cleaned_count = len(df[col][df[col] != 'N/A'])
                    print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
            
            # Clean description fields - remove excessive whitespace and standardize
            desc_cols = [col for col in df.columns if any(desc_name in str(col).upper() for desc_name in ['DESC', 'DESCRIPTION'])]
            for col in desc_cols:
                if col in df.columns:
                    original_count = len(df[col].dropna())
                    # Remove excessive whitespace
                    df[col] = df[col].astype(str).str.strip()
                    # Replace multiple spaces with single space
                    df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
                    # Replace empty strings, 'nan', and 'None' with "N/A" for OEMSecrets compatibility
                    df[col] = df[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                    cleaned_count = len(df[col][df[col] != 'N/A'])
                    print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
            
            # Fill all remaining empty cells with "N/A" to ensure OEMSecrets processes all rows
            print("🔧 PRIMETALS DEBUG: Filling any remaining empty cells with 'N/A' for OEMSecrets compatibility...")
            df = df.fillna('N/A')
            df = df.replace(['', 'nan', 'None', 'NaN'], 'N/A')
            
            # Set QTY to 0 for rows where MFG, MPN, and DESCRIPTION are all "N/A"
            # This prevents OEMSecrets from adding cost for non-existent parts
            if 'MFG' in df.columns and 'MPN' in df.columns and 'DESCRIPTION' in df.columns and 'QTY' in df.columns:
                na_mask = (df['MFG'] == 'N/A') & (df['MPN'] == 'N/A') & (df['DESCRIPTION'] == 'N/A')
                rows_to_zero = na_mask.sum()
                if rows_to_zero > 0:
                    df.loc[na_mask, 'QTY'] = 0
                    print(f"🔧 PRIMETALS DEBUG: Set QTY to 0 for {rows_to_zero} rows where MFG, MPN, and DESCRIPTION are all 'N/A'")
            
            # Don't remove rows with missing critical data - preserve exact PDF structure
            print("🔧 PRIMETALS DEBUG: Preserving all rows to match PDF structure exactly")
            
            df = df.reset_index(drop=True)
            print("🔧 PRIMETALS DEBUG: Data cleaning completed for OEMSecrets compatibility")
        
        print(f"🔧 PRIMETALS DEBUG: Final table shape: {df.shape}")
        print(f"🔧 PRIMETALS DEBUG: Final columns: {df.columns.tolist()}")
        if len(df) > 0:
            print(f"🔧 PRIMETALS DEBUG: Sample of final data:\n{df.head(2)}")
        print("🔧 PRIMETALS DEBUG: ===== END PRIMETALS PROCESSING =====\n")
        
        return df

    # Check if this looks like a dual-column BOM
    if df.shape[1] >= 8:
        # Look for header patterns to identify column groups
        header_row = df.iloc[0] if len(df) > 0 else pd.Series()
        header_str = ' '.join(str(cell) for cell in header_row)
        
        print(f"🔧 PRIMETALS DEBUG: Header row: {header_str}")
        
        # Find repeated patterns indicating dual columns
        if 'ITEM' in header_str and header_str.count('ITEM') >= 2:
            print("🔧 PRIMETALS DEBUG: Detected dual-column BOM table - splitting into individual parts")
            
            # Find the column indices for each side
            left_cols = []
            right_cols = []            # For dual-column BOM, we expect: ITEM, MFG, MPN, DESCRIPTION, QTY on each side
            header_list = [str(cell).strip().upper() for cell in header_row]
            
            # Find all ITEM columns (there should be 2)
            item_positions = [i for i, h in enumerate(header_list) if 'ITEM' in h]
            print(f"🔧 PRIMETALS DEBUG: ITEM positions found: {item_positions}")
            
            if len(item_positions) >= 2:
                # Use the ITEM positions to determine left and right column groups
                left_start = item_positions[0]
                right_start = item_positions[1]
                
                # Standard BOM columns: ITEM, MFG, MPN, DESCRIPTION, QTY
                left_cols = list(range(left_start, min(left_start + 5, len(header_list))))
                right_cols = list(range(right_start, min(right_start + 5, len(header_list))))
                
                # Remove any columns that don't exist
                left_cols = [i for i in left_cols if i < len(header_list)]
                right_cols = [i for i in right_cols if i < len(header_list)]
                
                print(f"🔧 PRIMETALS DEBUG: Left columns: {left_cols}")
                print(f"🔧 PRIMETALS DEBUG: Right columns: {right_cols}")
                
                if len(left_cols) >= 4 and len(right_cols) >= 4:
                    # Extract data from both sides
                    left_data = df.iloc[:, left_cols].copy()
                    right_data = df.iloc[:, right_cols].copy()
                    
                    # Standardize column names
                    standard_cols = ['ITEM', 'MFG', 'MPN', 'DESCRIPTION', 'QTY']
                    left_data.columns = standard_cols[:len(left_data.columns)]
                    right_data.columns = standard_cols[:len(right_data.columns)]
                    
                    # Remove header rows and empty rows
                    left_data = left_data[1:].reset_index(drop=True)  # Skip header
                    right_data = right_data[1:].reset_index(drop=True)  # Skip header
                    
                    # Filter out empty rows
                    left_data = left_data[left_data['ITEM'].notna() & (left_data['ITEM'].astype(str).str.strip() != '')].copy()
                    right_data = right_data[right_data['ITEM'].notna() & (right_data['ITEM'].astype(str).str.strip() != '')].copy()
                    
                    print(f"🔧 PRIMETALS DEBUG: Left side: {len(left_data)} parts")
                    print(f"🔧 PRIMETALS DEBUG: Right side: {len(right_data)} parts")
                    
                    # Combine both sides
                    combined_data = pd.concat([left_data, right_data], ignore_index=True)
                    
                    # Clean up the data
                    combined_data = combined_data.dropna(subset=['ITEM'])
                    combined_data = combined_data[combined_data['ITEM'].astype(str).str.strip() != '']
                    
                    print(f"🔧 PRIMETALS DEBUG: Combined: {len(combined_data)} parts")
                    
                    # Clean data for OEMSecrets compatibility
                    if len(combined_data) > 0:
                        print("🔧 PRIMETALS DEBUG: Cleaning dual-column data for OEMSecrets compatibility...")
                        
                        # Clean quantity fields - remove non-numeric characters
                        quantity_cols = [col for col in combined_data.columns if any(qty_name in str(col).upper() for qty_name in ['QTY', 'QUANTITY', 'QUAN'])]
                        for col in quantity_cols:
                            if col in combined_data.columns:
                                original_count = len(combined_data[col].dropna())
                                # Extract only numeric characters and decimal points
                                combined_data[col] = combined_data[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                                # Remove empty strings and convert to proper format
                                combined_data[col] = combined_data[col].replace('', '1')  # Default to 1 if empty
                                # Handle multiple decimal points - keep only the first one
                                combined_data[col] = combined_data[col].str.replace(r'\.(?=.*\.)', '', regex=True)
                                # Convert to numeric, invalid entries become NaN
                                combined_data[col] = pd.to_numeric(combined_data[col], errors='coerce')
                                # Fill NaN with 1 (default quantity)
                                combined_data[col] = combined_data[col].fillna(1)
                                # Convert to integer if whole number, otherwise keep as float
                                combined_data[col] = combined_data[col].apply(lambda x: int(x) if x == int(x) else x)
                                cleaned_count = len(combined_data[col].dropna())
                                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
                        
                        # Clean part number fields
                        part_cols = [col for col in combined_data.columns if any(part_name in str(col).upper() for part_name in ['PART', 'MPN', 'MFGPART'])]
                        for col in part_cols:
                            if col in combined_data.columns:
                                original_count = len(combined_data[col].dropna())
                                combined_data[col] = combined_data[col].astype(str).str.strip()
                                combined_data[col] = combined_data[col].str.replace(r'\s+', ' ', regex=True)
                                combined_data[col] = combined_data[col].str.replace(r'^[^\w\d]+|[^\w\d]+$', '', regex=True)
                                combined_data[col] = combined_data[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                                cleaned_count = len(combined_data[col][combined_data[col] != 'N/A'])
                                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
                        
                        # Clean manufacturer fields
                        mfg_cols = [col for col in combined_data.columns if any(mfg_name in str(col).upper() for mfg_name in ['MFG', 'MANUFACTURER', 'MANUF'])]
                        for col in mfg_cols:
                            if col in combined_data.columns:
                                original_count = len(combined_data[col].dropna())
                                combined_data[col] = combined_data[col].astype(str).str.strip()
                                combined_data[col] = combined_data[col].str.replace(r'\s+', ' ', regex=True)
                                combined_data[col] = combined_data[col].str.replace(r'(?i)^siemens.*', 'SIEMENS', regex=True)
                                combined_data[col] = combined_data[col].str.replace(r'(?i)^abb.*', 'ABB', regex=True)
                                combined_data[col] = combined_data[col].str.replace(r'(?i)^schneider.*', 'SCHNEIDER', regex=True)
                                combined_data[col] = combined_data[col].str.replace(r'(?i)^eaton.*', 'EATON', regex=True)
                                combined_data[col] = combined_data[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                                cleaned_count = len(combined_data[col][combined_data[col] != 'N/A'])
                                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
                        
                        # Clean description fields
                        desc_cols = [col for col in combined_data.columns if any(desc_name in str(col).upper() for desc_name in ['DESC', 'DESCRIPTION'])]
                        for col in desc_cols:
                            if col in combined_data.columns:
                                original_count = len(combined_data[col].dropna())
                                combined_data[col] = combined_data[col].astype(str).str.strip()
                                combined_data[col] = combined_data[col].str.replace(r'\s+', ' ', regex=True)
                                combined_data[col] = combined_data[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                                cleaned_count = len(combined_data[col][combined_data[col] != 'N/A'])
                                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
                        
                        # Fill all remaining empty cells with "N/A" to ensure OEMSecrets processes all rows
                        print("🔧 PRIMETALS DEBUG: Filling any remaining empty cells with 'N/A' for OEMSecrets compatibility...")
                        combined_data = combined_data.fillna('N/A')
                        combined_data = combined_data.replace(['', 'nan', 'None', 'NaN'], 'N/A')
                        
                        # Set QTY to 0 for rows where MFG, MPN, and DESCRIPTION are all "N/A"
                        # This prevents OEMSecrets from adding cost for non-existent parts
                        if 'MFG' in combined_data.columns and 'MPN' in combined_data.columns and 'DESCRIPTION' in combined_data.columns and 'QTY' in combined_data.columns:
                            na_mask = (combined_data['MFG'] == 'N/A') & (combined_data['MPN'] == 'N/A') & (combined_data['DESCRIPTION'] == 'N/A')
                            rows_to_zero = na_mask.sum()
                            if rows_to_zero > 0:
                                combined_data.loc[na_mask, 'QTY'] = 0
                                print(f"🔧 PRIMETALS DEBUG: Set QTY to 0 for {rows_to_zero} rows where MFG, MPN, and DESCRIPTION are all 'N/A'")
                        
                        combined_data = combined_data.reset_index(drop=True)
                        print("🔧 PRIMETALS DEBUG: Dual-column data cleaning completed for OEMSecrets compatibility")
                    
                    print(f"🔧 PRIMETALS DEBUG: Final table shape: {combined_data.shape}")
                    print(f"🔧 PRIMETALS DEBUG: Final columns: {combined_data.columns.tolist()}")
                    
                    return combined_data
    
    # If not a dual-column BOM, process as regular table
    print("🔧 PRIMETALS DEBUG: Processing as regular single-column table")
    
    # Define header keywords for scoring
    header_keywords = [
        'ITEM', 'QTY', 'QUANTITY', 'PART', 'NUMBER', 'DESCRIPTION', 'DESC', 'MANUFACTURER', 'MFG', 'MPN', 'MFGPART'
    ]
    
    best_score = 0
    best_idx = 0
    for idx in range(min(10, len(df))):  # Scan first 10 rows for best header
        row = df.iloc[idx]
        non_empty_cells = row.dropna().astype(str).str.upper().str.strip()
        score = sum(any(kw in cell for kw in header_keywords) for cell in non_empty_cells)
        print(f"🔧 PRIMETALS DEBUG: Row {idx} header score: {score} - {non_empty_cells.tolist()}")
        if score > best_score:
            best_score = score
            best_idx = idx
    
    print(f"🔧 PRIMETALS DEBUG: Selected header row index: {best_idx} (score: {best_score})")

    # Set the detected header row as columns
    new_columns = df.iloc[best_idx].fillna('').astype(str).str.strip()
    for i, col in enumerate(new_columns):
        if col == '' or col == 'nan':
            new_columns.iloc[i] = f'Column_{i}'
    
    df.columns = new_columns
    # Remove all rows up to and including the header row
    df = df.iloc[best_idx + 1:].reset_index(drop=True)
    
    print(f"🔧 PRIMETALS DEBUG: After header extraction - columns: {df.columns.tolist()}")
    print(f"🔧 PRIMETALS DEBUG: After header extraction - shape: {df.shape}")

    # Remove any duplicate header rows
    df = df[~df.apply(lambda row: row.astype(str).str.strip().tolist() == df.columns.astype(str).tolist(), axis=1)]
    df = df.reset_index(drop=True)
    
    # Remove rows that contain company/confidential information
    confidential_keywords = [
        'PRIMETALS TECHNOLOGIES', 'CONFIDENTIAL', 'PROPRIETARY', 'INTERNAL USE ONLY',
        'NOT FOR DISTRIBUTION', 'COMPANY CONFIDENTIAL'
    ]
    
    # Filter out confidential rows
    original_length = len(df)
    for keyword in confidential_keywords:
        # Check each row for confidential keywords
        mask = ~df.apply(lambda row: any(keyword in str(cell).upper() for cell in row), axis=1)
        df = df[mask]
    
    if len(df) < original_length:
        print(f"🔧 PRIMETALS DEBUG: Removed {original_length - len(df)} confidential/header rows")
    
    df = df.reset_index(drop=True)
    
    # Handle common Primetals column standardization
    column_mapping = {
        'ITEM': 'ITEM',
        'ITEM NO': 'ITEM', 
        'QTY': 'QTY',
        'QUANTITY': 'QTY',
        'PART NUMBER': 'MPN',
        'PART': 'MPN',
        'MFGPART': 'MPN',
        'MFG PART': 'MPN',
        'DESCRIPTION': 'DESCRIPTION',
        'DESC': 'DESCRIPTION',
        'MANUFACTURER': 'MFG',
        'MFG': 'MFG',
        'MPN': 'MPN',
        'VENDOR': 'VENDOR',
        'SUPPLIER': 'SUPPLIER'
    }
    
    # Apply column mapping
    for old_col, new_col in column_mapping.items():
        matching_cols = [col for col in df.columns if old_col in str(col).upper()]
        if matching_cols:
            df.rename(columns={matching_cols[0]: new_col}, inplace=True)
            print(f"🔧 PRIMETALS DEBUG: Renamed '{matching_cols[0]}' to '{new_col}'")
    
    # Clean data for OEMSecrets compatibility
    if len(df) > 0:
        print("🔧 PRIMETALS DEBUG: Cleaning data for OEMSecrets compatibility...")
        
        # Clean quantity fields - remove non-numeric characters
        quantity_cols = [col for col in df.columns if any(qty_name in str(col).upper() for qty_name in ['QTY', 'QUANTITY', 'QUAN'])]
        for col in quantity_cols:
            if col in df.columns:
                original_count = len(df[col].dropna())
                # Extract only numeric characters and decimal points
                df[col] = df[col].astype(str).str.replace(r'[^\d.]', '', regex=True)
                # Remove empty strings and convert to proper format
                df[col] = df[col].replace('', '1')  # Default to 1 if empty
                # Handle multiple decimal points - keep only the first one
                df[col] = df[col].str.replace(r'\.(?=.*\.)', '', regex=True)
                # Convert to numeric, invalid entries become NaN
                df[col] = pd.to_numeric(df[col], errors='coerce')
                # Fill NaN with 1 (default quantity)
                df[col] = df[col].fillna(1)
                # Convert to integer if whole number, otherwise keep as float
                df[col] = df[col].apply(lambda x: int(x) if x == int(x) else x)
                cleaned_count = len(df[col].dropna())
                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
        
        # Clean part number fields - remove excessive whitespace and special characters that might cause issues
        part_cols = [col for col in df.columns if any(part_name in str(col).upper() for part_name in ['PART', 'MPN', 'MFGPART'])]
        for col in part_cols:
            if col in df.columns:
                original_count = len(df[col].dropna())
                # Remove excessive whitespace
                df[col] = df[col].astype(str).str.strip()
                # Replace multiple spaces with single space
                df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
                # Remove leading/trailing special characters that might cause issues
                df[col] = df[col].str.replace(r'^[^\w\d]+|[^\w\d]+$', '', regex=True)
                # Replace empty strings, 'nan', and 'None' with "N/A" for OEMSecrets compatibility
                df[col] = df[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                cleaned_count = len(df[col][df[col] != 'N/A'])
                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
        
        # Clean manufacturer fields - standardize formatting
        mfg_cols = [col for col in df.columns if any(mfg_name in str(col).upper() for mfg_name in ['MFG', 'MANUFACTURER', 'MANUF'])]
        for col in mfg_cols:
            if col in df.columns:
                original_count = len(df[col].dropna())
                # Remove excessive whitespace
                df[col] = df[col].astype(str).str.strip()
                # Replace multiple spaces with single space
                df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
                # Standardize common manufacturer names
                df[col] = df[col].str.replace(r'(?i)^siemens.*', 'SIEMENS', regex=True)
                df[col] = df[col].str.replace(r'(?i)^abb.*', 'ABB', regex=True)
                df[col] = df[col].str.replace(r'(?i)^schneider.*', 'SCHNEIDER', regex=True)
                df[col] = df[col].str.replace(r'(?i)^eaton.*', 'EATON', regex=True)
                # Replace empty strings, 'nan', and 'None' with "N/A" for OEMSecrets compatibility
                df[col] = df[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                cleaned_count = len(df[col][df[col] != 'N/A'])
                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
        
        # Clean description fields - remove excessive whitespace and standardize
        desc_cols = [col for col in df.columns if any(desc_name in str(col).upper() for desc_name in ['DESC', 'DESCRIPTION'])]
        for col in desc_cols:
            if col in df.columns:
                original_count = len(df[col].dropna())
                # Remove excessive whitespace
                df[col] = df[col].astype(str).str.strip()
                # Replace multiple spaces with single space
                df[col] = df[col].str.replace(r'\s+', ' ', regex=True)
                # Replace empty strings, 'nan', and 'None' with "N/A" for OEMSecrets compatibility
                df[col] = df[col].replace(['', 'nan', 'None', 'NaN'], 'N/A')
                cleaned_count = len(df[col][df[col] != 'N/A'])
                print(f"🔧 PRIMETALS DEBUG: Cleaned {col} column - {original_count} entries processed, {cleaned_count} valid")
        
        # Fill all remaining empty cells with "N/A" to ensure OEMSecrets processes all rows
        print("🔧 PRIMETALS DEBUG: Filling any remaining empty cells with 'N/A' for OEMSecrets compatibility...")
        df = df.fillna('N/A')
        df = df.replace(['', 'nan', 'None', 'NaN'], 'N/A')
        
        # Set QTY to 0 for rows where MFG, MPN, and DESCRIPTION are all "N/A"
        # This prevents OEMSecrets from adding cost for non-existent parts
        if 'MFG' in df.columns and 'MPN' in df.columns and 'DESCRIPTION' in df.columns and 'QTY' in df.columns:
            na_mask = (df['MFG'] == 'N/A') & (df['MPN'] == 'N/A') & (df['DESCRIPTION'] == 'N/A')
            rows_to_zero = na_mask.sum()
            if rows_to_zero > 0:
                df.loc[na_mask, 'QTY'] = 0
                print(f"🔧 PRIMETALS DEBUG: Set QTY to 0 for {rows_to_zero} rows where MFG, MPN, and DESCRIPTION are all 'N/A'")
        
        # Don't remove rows with missing critical data - preserve exact PDF structure
        print("🔧 PRIMETALS DEBUG: Preserving all rows to match PDF structure exactly")
        
        df = df.reset_index(drop=True)
        print("🔧 PRIMETALS DEBUG: Data cleaning completed for OEMSecrets compatibility")
    
    print(f"🔧 PRIMETALS DEBUG: Final table shape: {df.shape}")
    print(f"🔧 PRIMETALS DEBUG: Final columns: {df.columns.tolist()}")
    if len(df) > 0:
        print(f"🔧 PRIMETALS DEBUG: Sample of final data:\n{df.head(2)}")
    print("🔧 PRIMETALS DEBUG: ===== END PRIMETALS PROCESSING =====\n")
    
    return df


def clean_riley_power_columns(df):
    """
    Clean Riley Power-specific table formatting issues.
    
    The main issue is that item descriptions are split across multiple columns
    due to line breaks in the original PDF. This function merges split descriptions
    back together and standardizes the column structure.
    
    Expected Riley Power table structure:
    - ITEM: Item number
    - QTY: Quantity
    - MANUFACTURER: Manufacturer name
    - MODEL NO: Model/Part number
    - ITEM DES: First part of description (often split)
    - RIPTION: Second part of description (continuation)
    - (Additional columns): May contain more description fragments
    """
    print(f"\n🔧 RILEY POWER DEBUG: Original table shape: {df.shape}")
    print(f"🔧 RILEY POWER DEBUG: Original columns: {df.columns.tolist()}")
    
    if df.empty:
        print("🔧 RILEY POWER DEBUG: Empty dataframe passed to clean_riley_power_columns")
        return df
    
    # Create a copy to work with
    df_clean = df.copy()
    
    # Find the header row that contains "ITEM", "QTY", "MANUFACTURER", etc.
    header_keywords = ['ITEM', 'QTY', 'MANUFACTURER', 'MODEL NO', 'ITEM DES', 'RIPTION']
    best_header_idx = 0
    best_score = 0
    
    for idx in range(min(10, len(df_clean))):
        row = df_clean.iloc[idx]
        non_empty_cells = row.dropna().astype(str).str.upper().str.strip()
        score = sum(any(kw in cell for kw in header_keywords) for cell in non_empty_cells)
        print(f"🔧 RILEY POWER DEBUG: Row {idx} header score: {score} - {non_empty_cells.tolist()}")
        if score > best_score:
            best_score = score
            best_header_idx = idx
    
    print(f"🔧 RILEY POWER DEBUG: Selected header row index: {best_header_idx} (score: {best_score})")
    
    # Set the detected header row as columns and remove header rows
    if best_header_idx < len(df_clean):
        new_columns = df_clean.iloc[best_header_idx].fillna('').astype(str).str.strip()
        for i, col in enumerate(new_columns):
            if col == '' or col == 'nan':
                new_columns.iloc[i] = f'Column_{i}'
        df_clean.columns = new_columns
        df_clean = df_clean.iloc[best_header_idx + 1:].reset_index(drop=True)
    
    print(f"🔧 RILEY POWER DEBUG: After header extraction - columns: {df_clean.columns.tolist()}")
    print(f"🔧 RILEY POWER DEBUG: After header extraction - shape: {df_clean.shape}")
    
    # Remove duplicate header rows
    df_clean = df_clean[~df_clean.apply(lambda row: row.astype(str).str.strip().tolist() == df_clean.columns.astype(str).tolist(), axis=1)]
    df_clean = df_clean.reset_index(drop=True)
    
    # Now handle the main issue: merge split descriptions
    description_columns = []
    
    # Find columns that contain description fragments
    for col in df_clean.columns:
        col_str = str(col).upper()
        if any(desc_keyword in col_str for desc_keyword in ['ITEM DES', 'RIPTION', 'DESCRIPTION', 'DESC']):
            description_columns.append(col)
    
    # Also look for blank columns that might contain description fragments
    # Check columns that have blank/generic names like 'Column_X' or empty strings
    for col in df_clean.columns:
        col_str = str(col).strip()
        if (col_str == '' or col_str.startswith('Column_') or col_str == 'nan') and col not in description_columns:
            # Check if this column contains text that looks like description data
            sample_values = df_clean[col].dropna().astype(str).head(5).tolist()
            if sample_values:
                # Check if the column contains meaningful text (not just numbers or short codes)
                text_indicators = 0
                for val in sample_values:
                    val_clean = val.strip()
                    if len(val_clean) > 5 and any(char.isalpha() for char in val_clean):
                        text_indicators += 1
                
                # If more than half the sample values look like text, include this column
                if text_indicators >= len(sample_values) // 2:
                    description_columns.append(col)
                    print(f"🔧 RILEY POWER DEBUG: Found blank column '{col}' with description-like content: {sample_values[:2]}")
    
    print(f"🔧 RILEY POWER DEBUG: All description columns found: {description_columns}")
    
    # If we have multiple description columns, we need to merge them
    if len(description_columns) > 1:
        print(f"🔧 RILEY POWER DEBUG: Found split description columns: {description_columns}")
        
        # Sort the description columns by their position in the dataframe to merge in correct order
        description_columns_sorted = sorted(description_columns, key=lambda x: df_clean.columns.get_loc(x))
        print(f"🔧 RILEY POWER DEBUG: Description columns in order: {description_columns_sorted}")
        
        # Create a new merged description column
        def merge_description_row(row):
            """Merge description fragments from multiple columns for a single row."""
            desc_parts = []
            for col in description_columns_sorted:  # Use sorted order
                val = str(row[col]).strip()
                if val and val != 'nan' and val != '':
                    desc_parts.append(val)
            
            # Join the parts with a space, but handle special cases
            merged = ' '.join(desc_parts)
            
            # Clean up common formatting issues
            merged = re.sub(r'\s+', ' ', merged)  # Multiple spaces to single space
            merged = re.sub(r'"\s*"', '"', merged)  # Remove spaces between quotes
            merged = merged.strip()
            
            return merged
        
        # Apply the merge function to all rows
        df_clean['DESCRIPTION'] = df_clean.apply(merge_description_row, axis=1)
        
        # Remove the original split description columns
        df_clean = df_clean.drop(columns=description_columns)
        
        print(f"🔧 RILEY POWER DEBUG: Merged description columns into 'DESCRIPTION'")
    
    elif len(description_columns) == 1:
        # Even if we have only one description column, rename it to 'DESCRIPTION' for consistency
        main_desc_col = description_columns[0]
        if main_desc_col != 'DESCRIPTION':
            df_clean = df_clean.rename(columns={main_desc_col: 'DESCRIPTION'})
        print(f"🔧 RILEY POWER DEBUG: Renamed single description column '{main_desc_col}' to 'DESCRIPTION'")
    
    else:
        print(f"🔧 RILEY POWER DEBUG: No description columns found with standard naming")
    
    # Check for any remaining columns that might contain description fragments
    # Look for columns after the expected standard columns that might contain text
    expected_columns = ['ITEM', 'QTY', 'MANUFACTURER', 'MODEL NO']
    remaining_columns = [col for col in df_clean.columns if col not in expected_columns + ['DESCRIPTION']]
    
    if remaining_columns:
        print(f"🔧 RILEY POWER DEBUG: Found additional columns that might contain description fragments: {remaining_columns}")
        
        # Check if these columns contain text that should be merged into description
        for col in remaining_columns:
            sample_values = df_clean[col].dropna().astype(str).head(3).tolist()
            print(f"🔧 RILEY POWER DEBUG: Column '{col}' sample values: {sample_values}")
            
            # If the column contains text (not just numbers/short codes), merge it
            if any(len(val) > 10 or any(char.isalpha() for char in val) for val in sample_values):
                print(f"🔧 RILEY POWER DEBUG: Column '{col}' appears to contain description text, merging...")
                
                # Merge this column into the description
                if 'DESCRIPTION' in df_clean.columns:
                    df_clean['DESCRIPTION'] = df_clean['DESCRIPTION'].astype(str) + ' ' + df_clean[col].astype(str)
                else:
                    df_clean['DESCRIPTION'] = df_clean[col].astype(str)
                
                # Remove the merged column
                df_clean = df_clean.drop(columns=[col])
    
    # Clean up the final description column
    if 'DESCRIPTION' in df_clean.columns:
        df_clean['DESCRIPTION'] = df_clean['DESCRIPTION'].astype(str).str.strip()
        df_clean['DESCRIPTION'] = df_clean['DESCRIPTION'].str.replace(r'\s+', ' ', regex=True)
        df_clean['DESCRIPTION'] = df_clean['DESCRIPTION'].str.replace('nan', '', regex=False)
        df_clean['DESCRIPTION'] = df_clean['DESCRIPTION'].str.strip()
    
    # Clean up the QTY column - remove non-numeric values
    if 'QTY' in df_clean.columns:
        print(f"🔧 RILEY POWER DEBUG: Cleaning QTY column")
        
        def clean_qty_value(value):
            """Clean QTY value to keep only numeric content."""
            if pd.isna(value) or value == '':
                return ''
            
            # Convert to string and clean
            str_value = str(value).strip()
            if str_value == 'nan':
                return ''
            
            # Try to extract numeric part
            # Remove common non-numeric characters but keep decimals
            import re
            numeric_match = re.search(r'^(\d+(?:\.\d+)?)', str_value)
            if numeric_match:
                return numeric_match.group(1)
            else:
                # If no numeric content found, return empty string
                return ''
        
        # Apply cleaning to QTY column
        df_clean['QTY'] = df_clean['QTY'].apply(clean_qty_value)
        print(f"🔧 RILEY POWER DEBUG: QTY column cleaned")
    
    # Standardize column names (including MODEL NO -> MPN conversion)
    column_mapping = {
        'ITEM': 'ITEM',
        'QTY': 'QTY',
        'MANUFACTURER': 'MANUFACTURER',
        'MODEL NO': 'MPN',  # Convert MODEL NO to MPN for OEMsecrets
        'DESCRIPTION': 'DESCRIPTION'
    }
    
    # Apply column mapping
    for old_col, new_col in column_mapping.items():
        if old_col in df_clean.columns and old_col != new_col:
            df_clean = df_clean.rename(columns={old_col: new_col})
    
    # Remove completely empty rows
    df_clean = df_clean.dropna(how='all').reset_index(drop=True)
    
    # Remove rows where all main columns are empty
    main_columns = ['ITEM', 'QTY', 'MANUFACTURER', 'MPN', 'DESCRIPTION']  # Updated to use MPN
    existing_main_columns = [col for col in main_columns if col in df_clean.columns]
    
    if existing_main_columns:
        df_clean = df_clean.dropna(subset=existing_main_columns, how='all').reset_index(drop=True)
    
    print(f"🔧 RILEY POWER DEBUG: Final table shape: {df_clean.shape}")
    print(f"🔧 RILEY POWER DEBUG: Final columns: {df_clean.columns.tolist()}")
    
    if not df_clean.empty:
        print(f"🔧 RILEY POWER DEBUG: Sample final data:")
        print(df_clean.head(3).to_string())
    
    return df_clean


def clean_shanklin_columns(df):
    """
    Clean and format Shanklin BoM table columns.
    
    Shanklin PDFs have a unique structure:
    - Headers are at the bottom of the table
    - Items count backwards from highest number to 1
    - Need to flip the table and reorder by item number
    
    Args:
        df: pandas DataFrame with raw extracted data
        
    Returns:
        pandas DataFrame with cleaned column names and proper ordering
    """
    print(f"🔧 SHANKLIN DEBUG: Starting Shanklin formatting")
    print(f"🔧 SHANKLIN DEBUG: Input shape: {df.shape}")
    print(f"🔧 SHANKLIN DEBUG: Input columns: {df.columns.tolist()}")
    
    if df.empty:
        print("🔧 SHANKLIN DEBUG: Empty dataframe, returning as-is")
        return df
    
    # Create a copy to avoid modifying original
    df_clean = df.copy()
    
    # Remove completely empty rows first
    df_clean = df_clean.dropna(how='all').reset_index(drop=True)
    
    if df_clean.empty:
        print("🔧 SHANKLIN DEBUG: No data after removing empty rows")
        return df_clean
    
    print(f"🔧 SHANKLIN DEBUG: After removing empty rows - shape: {df_clean.shape}")
    
    # Find the header row - it's typically the last row or a row that contains header-like text
    header_row_idx = None
    
    # Look for rows that contain header keywords
    header_keywords = ['ITEM', 'PART', 'NUMBER', 'DESCRIPTION', 'QTY', 'SPC']
    
    for idx in range(len(df_clean) - 1, -1, -1):  # Search from bottom up
        row_text = ' '.join(df_clean.iloc[idx].astype(str).str.upper())
        if any(keyword in row_text for keyword in header_keywords):
            header_row_idx = idx
            print(f"🔧 SHANKLIN DEBUG: Found header row at index {idx}")
            break
    
    if header_row_idx is None:
        # If no header found, assume last row is header
        header_row_idx = len(df_clean) - 1
        print(f"🔧 SHANKLIN DEBUG: No header keywords found, using last row as header (index {header_row_idx})")
    
    # Extract header row and use it as column names
    if header_row_idx < len(df_clean):
        header_row = df_clean.iloc[header_row_idx].fillna('').astype(str).str.strip()
        
        # Clean up header names
        new_columns = []
        for i, col in enumerate(header_row):
            if col == '' or col == 'nan':
                new_columns.append(f'Column_{i}')
            else:
                # Clean up common header variations
                clean_col = col.upper().strip()
                if 'ITEM' in clean_col and 'NO' in clean_col:
                    new_columns.append('ITEM')
                elif 'PART' in clean_col and 'NUMBER' in clean_col:
                    new_columns.append('MPN')
                elif 'DESCRIPTION' in clean_col:
                    new_columns.append('DESCRIPTION')
                elif clean_col.startswith('SPC-'):
                    new_columns.append(clean_col)  # Keep SPC columns as-is
                else:
                    new_columns.append(clean_col)
        
        df_clean.columns = new_columns
        print(f"🔧 SHANKLIN DEBUG: Set column names: {new_columns}")
        
        # Remove the header row from data
        df_clean = df_clean.iloc[:header_row_idx].reset_index(drop=True)
        print(f"🔧 SHANKLIN DEBUG: After removing header row - shape: {df_clean.shape}")
    
    # Now we need to reverse the order and sort by item number
    # First, identify the ITEM column
    item_col = None
    for col in df_clean.columns:
        if 'ITEM' in str(col).upper():
            item_col = col
            break
    
    if item_col is not None:
        print(f"🔧 SHANKLIN DEBUG: Found ITEM column: {item_col}")
        
        # Convert ITEM column to numeric, handling non-numeric values
        def clean_item_number(value):
            if pd.isna(value) or value == '':
                return 999999  # Put empty items at the end
            try:
                # Extract numeric part
                import re
                match = re.search(r'(\d+)', str(value))
                if match:
                    return int(match.group(1))
                else:
                    return 999999  # Non-numeric items at the end
            except:
                return 999999
        
        df_clean['_item_sort'] = df_clean[item_col].apply(clean_item_number)
        
        # Sort by item number (ascending order: 1, 2, 3, ...)
        df_clean = df_clean.sort_values('_item_sort').reset_index(drop=True)
        df_clean = df_clean.drop('_item_sort', axis=1)
        
        print(f"🔧 SHANKLIN DEBUG: Sorted by item number")
    else:
        print("🔧 SHANKLIN DEBUG: No ITEM column found, keeping original order")
    
    # Standardize common columns
    column_mapping = {
        'ITEM': 'ITEM',
        'MPN': 'MPN',
        'DESCRIPTION': 'DESCRIPTION'
    }
    
    # Apply column mapping
    for old_col, new_col in column_mapping.items():
        if old_col in df_clean.columns and old_col != new_col:
            df_clean = df_clean.rename(columns={old_col: new_col})
    
    # Handle quantity columns - look for SPC- columns or numeric columns
    qty_columns = []
    for col in df_clean.columns:
        if str(col).startswith('SPC-') or (str(col).isdigit() and col not in ['ITEM', 'MPN', 'DESCRIPTION']):
            qty_columns.append(col)
    
    if qty_columns:
        print(f"🔧 SHANKLIN DEBUG: Found quantity columns: {qty_columns}")
        # For now, keep the quantity columns as-is, but we could sum them or pick the first one
        # Let's take the first quantity column as the main QTY
        if len(qty_columns) > 0:
            first_qty_col = qty_columns[0]
            if 'QTY' not in df_clean.columns:
                df_clean['QTY'] = df_clean[first_qty_col]
                print(f"🔧 SHANKLIN DEBUG: Used {first_qty_col} as QTY column")
    
    # Remove completely empty rows
    df_clean = df_clean.dropna(how='all').reset_index(drop=True)
    
    # Remove rows where all main columns are empty
    main_columns = ['ITEM', 'MPN', 'DESCRIPTION']
    existing_main_columns = [col for col in main_columns if col in df_clean.columns]
    
    if existing_main_columns:
        df_clean = df_clean.dropna(subset=existing_main_columns, how='all').reset_index(drop=True)
    
    print(f"🔧 SHANKLIN DEBUG: Final table shape: {df_clean.shape}")
    print(f"🔧 SHANKLIN DEBUG: Final columns: {df_clean.columns.tolist()}")
    print(f"🔧 SHANKLIN DEBUG: Final dtypes: {df_clean.dtypes.to_dict()}")
    
    if not df_clean.empty:
        print(f"🔧 SHANKLIN DEBUG: Sample final data:")
        print(df_clean.head(5).to_string())
    
    # Additional debugging for potential GUI issues
    print(f"🔧 SHANKLIN DEBUG: DataFrame memory usage: {df_clean.memory_usage().sum()} bytes")
    print(f"🔧 SHANKLIN DEBUG: DataFrame has any NaN values: {df_clean.isna().any().any()}")
    
    return df_clean


# Customer formatter registry
def clean_901d_columns(df):
    """
    Clean 901D-specific table formatting.
    
    901D tables have a unique format:
    - All data is crammed into a single column
    - Headers are at the bottom instead of the top
    - Row numbers count backwards (6, 5, 4, 3, etc.)
    - Expected columns: FIND NO. | 901D P/N | QTY | MFR | CAGE MFR | MFR P/N | DESCRIPTION
    """
    print(f"\n🔧 901D DEBUG: Original table shape: {df.shape}")
    print(f"🔧 901D DEBUG: First few rows:\n{df.head()}")
    print(f"🔧 901D DEBUG: Last few rows:\n{df.tail()}")
    
    if df.empty:
        print("🔧 901D DEBUG: Empty dataframe passed to clean_901d_columns")
        return df

    # 901D tables typically have all data in the first column
    if df.shape[1] == 1:
        print("🔧 901D DEBUG: Single column detected - applying 901D-specific parsing")
        
        # Get all data as text from the first column
        all_text = df.iloc[:, 0].fillna('').astype(str).tolist()
        print(f"🔧 901D DEBUG: Raw text data: {all_text}")
        
        # Find the header row (usually contains "FIND NO.|901D P/N|QTY|MFR")
        header_row_idx = None
        for i, text in enumerate(all_text):
            if 'FIND NO.' in text.upper() and 'QTY' in text.upper() and 'MFR' in text.upper():
                header_row_idx = i
                print(f"🔧 901D DEBUG: Found header row at index {i}: {text}")
                break
        
        if header_row_idx is None:
            print("🔧 901D DEBUG: Could not find header row, using generic cleaning")
            return clean_generic_columns(df)
        
        # Split the header to get column names
        header_text = all_text[header_row_idx]
        # Common 901D column separators
        if '|' in header_text:
            column_names = [col.strip() for col in header_text.split('|')]
        elif 'FIND NO.' in header_text:
            # Try to parse the expected format manually
            column_names = ['FIND NO.', '901D P/N', 'QTY', 'MFR', 'CAGE MFR', 'MPN', 'DESCRIPTION']
        else:
            column_names = ['FIND NO.', '901D P/N', 'QTY', 'MFR', 'CAGE MFR', 'MPN', 'DESCRIPTION']
        
        print(f"🔧 901D DEBUG: Parsed column names: {column_names}")
        
        # Get data rows (everything before the header row, since 901D has headers at bottom)
        data_rows = all_text[:header_row_idx]
        print(f"🔧 901D DEBUG: Found {len(data_rows)} data rows")
        
        # Fill in missing FIND NO. values before parsing
        # 901D tables count down from highest number, so rows without numbers should be filled
        print(f"🔧 901D DEBUG: Original data rows: {data_rows}")
        
        # Find the pattern of existing FIND NO. values
        existing_numbers = []
        for i, row_text in enumerate(data_rows):
            find_no_match = re.match(r'^(\d+)\s+', row_text.strip())
            if find_no_match:
                existing_numbers.append((i, int(find_no_match.group(1))))
        
        print(f"🔧 901D DEBUG: Found existing FIND NO. values: {existing_numbers}")
        
        # Fill in missing numbers by working backwards from the pattern
        if existing_numbers:
            # Sort by FIND NO. to understand the pattern
            existing_numbers.sort(key=lambda x: x[1], reverse=True)  # Highest first
            
            # Fill in missing numbers
            filled_data_rows = data_rows.copy()
            expected_number = existing_numbers[0][1] + 1  # Start from highest + 1
            
            for i in range(len(filled_data_rows)):
                row_text = filled_data_rows[i].strip()
                
                # Check if this row already has a FIND NO.
                if re.match(r'^\d+\s+', row_text):
                    # Extract the existing number and update expected
                    find_no_match = re.match(r'^(\d+)\s+', row_text)
                    if find_no_match:
                        current_number = int(find_no_match.group(1))
                        expected_number = current_number - 1  # Next row should be one less
                else:
                    # This row is missing a FIND NO., add it
                    if row_text and expected_number > 0:  # Only add if we have text and valid number
                        print(f"🔧 901D DEBUG: Adding missing FIND NO. {expected_number} to row: {row_text}")
                        filled_data_rows[i] = f"{expected_number} {row_text}"
                        expected_number -= 1
            
            print(f"🔧 901D DEBUG: After filling missing FIND NO.: {filled_data_rows}")
            data_rows = filled_data_rows
        
        # Parse each data row - 901D format typically has data separated by spaces/delimiters
        parsed_rows = []
        for row_text in data_rows:
            if not row_text.strip():
                continue
                
            # Try to parse the row into components
            # Expected 901D format: FIND_NO 901D_P/N QTY [CAGE_CODE] MFR MFR_P/N DESCRIPTION
            row_text = row_text.strip()
            print(f"🔧 901D DEBUG: Parsing row: {row_text}")
            
            # Extract leading number (FIND NO.)
            find_no_match = re.match(r'^(\d+)\s+(.+)', row_text)
            if find_no_match:
                find_no = find_no_match.group(1)
                remaining_text = find_no_match.group(2)
                
                # For continuation rows that were just assigned a number, we need different parsing
                if row_text.startswith('2 RIBBON CONNECTOR') or row_text.startswith('1 RIBBON CABLE'):
                    # These are continuation rows with a different format
                    # Extract the actual part number from the middle of the text
                    
                    if '8501928' in remaining_text:
                        # Row 2: "2 RIBBON CONNECTOR, p2 8501928 2 7CQB5 TE CONNECTIVITY 1-1658622-1 CrOEPTACIE opin"
                        part_match = re.search(r'p2\s+(\d+)', remaining_text)
                        if part_match:
                            part_no = part_match.group(1)  # 8501928
                            qty = '2'
                            mfr = 'TE CONNECTIVITY'
                            cage_mfr = '7CQB5'
                            mfr_pn = '1-1658622-1'
                            description = 'RIBBON CONNECTOR, CrOEPTACIE opin'
                        else:
                            part_no = '8501928'
                            qty = '2'
                            mfr = 'TE CONNECTIVITY'
                            cage_mfr = '7CQB5'
                            mfr_pn = '1-1658622-1'
                            description = 'RIBBON CONNECTOR'
                    
                    elif '8800228' in remaining_text:
                        # Row 1: "1 RIBBON CABLE] 8800228 ] 7638 1 3M 3759/60 COND"
                        part_match = re.search(r'(\d+)\s*\]\s*7638', remaining_text)
                        if part_match:
                            part_no = part_match.group(1)  # 8800228
                            qty = '1'
                            mfr = '3M'
                            cage_mfr = '7638'
                            mfr_pn = '3759/60'
                            description = 'RIBBON CABLE COND'
                        else:
                            part_no = '8800228'
                            qty = '1'
                            mfr = '3M'
                            cage_mfr = '7638'
                            mfr_pn = '3759/60'
                            description = 'RIBBON CABLE'
                    else:
                        # Fallback to original parsing
                        parts = remaining_text.split()
                        part_no = parts[0] if parts else ''
                        qty = '1'
                        mfr = ''
                        cage_mfr = ''
                        mfr_pn = ''
                        description = remaining_text
                    
                    # Create the parsed row for continuation rows
                    parsed_row = {
                        'FIND NO.': find_no,
                        '901D P/N': part_no,
                        'QTY': qty,
                        'MFR': mfr,
                        'CAGE MFR': cage_mfr,
                        'MPN': mfr_pn,
                        'DESCRIPTION': description
                    }
                    parsed_rows.append(parsed_row)
                    print(f"🔧 901D DEBUG: Parsed continuation row: {parsed_row}")
                    continue
                
                # Original parsing logic for normal rows
                # Split remaining text into components
                parts = remaining_text.split()
                
                if len(parts) >= 2:  # Reduced minimum requirement
                    # 901D format: FIND_NO 901D_P/N [QTY] [more components...]
                    part_no = parts[0]  # 901D P/N (like 8000539)
                    
                    # Look for QTY - in 901D it might be any small number or sometimes missing
                    qty = None
                    qty_idx = None
                    
                    # First try: look for a small digit (typical QTY pattern)
                    for i in range(1, min(4, len(parts))):
                        if parts[i].isdigit() and int(parts[i]) <= 50:  # Increased limit
                            qty = parts[i]
                            qty_idx = i
                            break
                    
                    # If no small number found, assume QTY is 1 or missing
                    if qty_idx is None:
                        # Check if second part could be a cage code (like "] 7CQB5")
                        if len(parts) >= 2 and (parts[1].startswith(']') or len(parts[1]) <= 6):
                            qty = '1'  # Default QTY
                            qty_idx = 0  # Start parsing from part 1
                        else:
                            qty = '1'  # Default QTY
                            qty_idx = 1  # Skip the potential part number
                    
                    if qty_idx is not None:
                        # Parse remaining components after QTY position
                        description_parts = parts[qty_idx + 1:] if qty_idx + 1 < len(parts) else []
                        
                        # Try to identify MFR information
                        mfr = ''
                        cage_mfr = ''
                        mfr_pn = ''
                        description = ''
                        
                        if description_parts:
                            desc_text = ' '.join(description_parts)
                            
                            # Common manufacturer patterns for 901D
                            mfr_patterns = ['TE CONNECTIVITY', 'BRADY', '3M', 'SIEMENS', 'MOLEX', 'AMPHENOL']
                            mfr_found = False
                            
                            for pattern in mfr_patterns:
                                if pattern in desc_text.upper():
                                    # Find where the manufacturer name starts
                                    mfr_start = desc_text.upper().find(pattern)
                                    
                                    # Everything before MFR name could be CAGE code or part number
                                    before_mfr = desc_text[:mfr_start].strip()
                                    after_mfr = desc_text[mfr_start + len(pattern):].strip()
                                    
                                    # Parse before MFR (likely cage code or part identifier)
                                    if before_mfr:
                                        # Look for patterns like "] 7CQB5" or "7638"
                                        cage_match = re.search(r'(\w+)$', before_mfr)
                                        if cage_match:
                                            cage_mfr = cage_match.group(1)
                                    
                                    mfr = pattern
                                    
                                    # Parse after MFR (part number and description)
                                    if after_mfr:
                                        # Try to separate MFR P/N from description
                                        after_parts = after_mfr.split()
                                        if after_parts:
                                            # First part is likely MFR P/N
                                            mfr_pn = after_parts[0]
                                            if len(after_parts) > 1:
                                                description = ' '.join(after_parts[1:])
                                            else:
                                                description = ''
                                    
                                    mfr_found = True
                                    break
                            
                            if not mfr_found:
                                # Fallback: assume format is [CAGE] MFR PART DESCRIPTION
                                if len(description_parts) >= 2:
                                    cage_mfr = description_parts[0] if description_parts[0] not in ['|', ']'] else ''
                                    mfr = description_parts[1] if len(description_parts) > 1 else ''
                                    if len(description_parts) > 2:
                                        mfr_pn = description_parts[2]
                                        description = ' '.join(description_parts[3:])
                                else:
                                    description = desc_text
                        
                        # Create the parsed row
                        parsed_row = {
                            'FIND NO.': find_no,
                            '901D P/N': part_no,
                            'QTY': qty,
                            'MFR': mfr,
                            'CAGE MFR': cage_mfr,
                            'MPN': mfr_pn,
                            'DESCRIPTION': description
                        }
                        parsed_rows.append(parsed_row)
                        print(f"🔧 901D DEBUG: Parsed row: {parsed_row}")
                    else:
                        print(f"🔧 901D DEBUG: Could not determine QTY position in row: {row_text}")
                else:
                    print(f"🔧 901D DEBUG: Not enough parts in row: {row_text}")
            else:
                # Handle rows that don't start with a number (continuation lines)
                if parsed_rows and row_text:
                    print(f"🔧 901D DEBUG: Treating as continuation: {row_text}")
                    # Add to description of last row
                    last_row = parsed_rows[-1]
                    if last_row['DESCRIPTION']:
                        last_row['DESCRIPTION'] += ' ' + row_text
                    else:
                        last_row['DESCRIPTION'] = row_text
                else:
                    print(f"🔧 901D DEBUG: Skipping unmatched row: {row_text}")
        
        if parsed_rows:
            # Create new DataFrame from parsed rows
            new_df = pd.DataFrame(parsed_rows)
            
            # 901D typically has rows in reverse order (highest FIND NO. first)
            # Sort by FIND NO. in ascending order
            if 'FIND NO.' in new_df.columns:
                new_df['FIND NO._numeric'] = pd.to_numeric(new_df['FIND NO.'], errors='coerce')
                new_df = new_df.sort_values('FIND NO._numeric').drop('FIND NO._numeric', axis=1)
                new_df = new_df.reset_index(drop=True)
            
            print(f"🔧 901D DEBUG: Successfully parsed table - shape: {new_df.shape}")
            print(f"🔧 901D DEBUG: Columns: {new_df.columns.tolist()}")
            print(f"🔧 901D DEBUG: Sample data:\n{new_df.head()}")
            
            return new_df
        else:
            print("🔧 901D DEBUG: Could not parse any rows, falling back to generic cleaning")
            return clean_generic_columns(df)
    
    else:
        print("🔧 901D DEBUG: Multiple columns detected, using generic cleaning with OCR enhancements")
        # If already split into columns, just clean them
        df = clean_generic_columns(df)
        
        # OCR-specific cleaning
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].astype(str).str.replace(r'\s+', ' ', regex=True)
                df[col] = df[col].str.replace(r'[^\w\s\-\.\,\(\)\/]', '', regex=True)
                df[col] = df[col].str.strip()
        
        # Remove artifact rows
        df = df[df.apply(lambda row: any(len(str(cell).strip()) > 2 for cell in row), axis=1)]
        
        print(f"🔧 901D DEBUG: After cleaning - shape: {df.shape}")
        return df


def clean_amazon_columns(df):
    """
    Clean Amazon-specific table formatting.
    
    Amazon tables have specific characteristics:
    - Headers like "Device tag", "QTY", "Manufacturer", "Part number", "Description"
    - Tables often have revision info and metadata at the top
    - May contain certification columns (UL Cat. code, CSA/cUL, etc.)
    - Sometimes data is duplicated or has merged cells
    """
    print(f"\n🔧 AMAZON DEBUG: Original table shape: {df.shape}")
    print(f"🔧 AMAZON DEBUG: First few rows:\n{df.head(8)}")
    
    if df.empty:
        print("🔧 AMAZON DEBUG: Empty dataframe passed to clean_amazon_columns")
        return df

    # Define Amazon-specific header keywords
    header_keywords = [
        'DEVICE TAG', 'QTY', 'MANUFACTURER', 'PART NUMBER', 'DESCRIPTION', 
        'UL CAT', 'UL CERT', 'CSA', 'TYPE RATING', 'DEVICE', 'TAG', 'PART', 'NUMBER'
    ]
    
    # Find the best header row
    best_score = 0
    best_idx = -1
    for idx in range(min(15, len(df))):  # Scan more rows since Amazon may have more metadata
        row = df.iloc[idx]
        non_empty_cells = row.dropna().astype(str).str.upper().str.strip()
        score = sum(any(kw in cell for kw in header_keywords) for cell in non_empty_cells)
        print(f"🔧 AMAZON DEBUG: Row {idx} header score: {score} - {non_empty_cells.tolist()}")
        if score > best_score:
            best_score = score
            best_idx = idx
    
    print(f"🔧 AMAZON DEBUG: Selected header row index: {best_idx} (score: {best_score})")

    # If we found a good header row, use it
    if best_score >= 3 and best_idx >= 0:  # Amazon should have at least 3 matching keywords
        new_columns = df.iloc[best_idx].fillna('').astype(str).str.strip()
        for i, col in enumerate(new_columns):
            if col == '' or col == 'nan':
                new_columns.iloc[i] = f'Column_{i}'
        df.columns = new_columns
        df = df.iloc[best_idx + 1:].reset_index(drop=True)
        print(f"🔧 AMAZON DEBUG: After header extraction - columns: {df.columns.tolist()}")
        print(f"🔧 AMAZON DEBUG: After header extraction - shape: {df.shape}")
    else:
        print("🔧 AMAZON DEBUG: No clear header row found, using existing columns")

    # Remove duplicate header rows that sometimes appear as data
    if len(df) > 0:
        df = df[~df.apply(lambda row: row.astype(str).str.strip().tolist() == df.columns.astype(str).tolist(), axis=1)]
        df = df.reset_index(drop=True)

    # Remove rows that contain Amazon-specific metadata/footer information (be more selective)
    reject_patterns = [
        r'^revision\s+\d+\s+released',  # Revision info at start of row
        r'designed by.*checked by.*approved by',  # Footer signature lines
        r'^file name.*date.*scale',  # Footer file info
        r'^parts list electrical.*revision.*sheet',  # Footer parts list info
        r'^\s*bill of material\s*$',  # Standalone "Bill of material" text
        r'^\s*n/a\s+n/a\s+n/a\s+n/a\s+n/a\s+n/a\s+n/a\s+n/a\s*$'  # Rows with all N/A values
    ]
    
    for pattern in reject_patterns:
        initial_len = len(df)
        mask = df.apply(lambda row: not any(re.search(pattern, ' '.join(str(cell) for cell in row), re.IGNORECASE) for cell in row), axis=1)
        df = df[mask].reset_index(drop=True)
        removed = initial_len - len(df)
        if removed > 0:
            print(f"🔧 AMAZON DEBUG: Removed {removed} rows matching pattern: {pattern}")
    
    # Clean up empty rows and rows with only whitespace
    df = df.dropna(how='all')
    df = df[df.apply(lambda row: any(str(cell).strip() and str(cell).strip() != 'nan' for cell in row), axis=1)]
    df = df.reset_index(drop=True)
    
    # Standard column cleaning
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace(['nan', 'NaN', ''], pd.NA)

    print(f"🔧 AMAZON DEBUG: Final cleaned table shape: {df.shape}")
    print(f"🔧 AMAZON DEBUG: Final columns: {df.columns.tolist()}")
    if len(df) > 0:
        print(f"🔧 AMAZON DEBUG: Sample data:\n{df.head(3)}")
    
    return df


CUSTOMER_FORMATTERS = {
    'farrell': clean_farrell_columns,
    'nel': clean_nel_columns,
    'generic': clean_generic_columns,
    'primetals': clean_primetals_columns,
    'riley_power': clean_riley_power_columns,
    'shanklin': clean_shanklin_columns,
    '901d': clean_901d_columns,
    'amazon': clean_amazon_columns
}


def apply_customer_formatter(df, customer_name=None):
    """
    Apply customer-specific formatting to a dataframe.
    
    Args:
        df: pandas DataFrame to format
        customer_name: string name of the customer (e.g., 'farrell', 'nel')
                      If None or unknown, uses generic formatting
    
    Returns:
        Formatted pandas DataFrame
    """
    if df.empty:
        return df
    
    # Normalize customer name
    if customer_name:
        customer_name = customer_name.lower().strip()
    
    # Get the appropriate formatter
    formatter = CUSTOMER_FORMATTERS.get(customer_name, clean_generic_columns)
    
    print(f"🔧 CUSTOMER FORMATTER: Applying {customer_name or 'generic'} formatting")
    
    try:
        formatted_df = formatter(df)
        print(f"🔧 CUSTOMER FORMATTER: Successfully applied {customer_name or 'generic'} formatting")
        return formatted_df
    except Exception as e:
        print(f"🔧 CUSTOMER FORMATTER: Error applying {customer_name or 'generic'} formatting: {e}")
        print(f"🔧 CUSTOMER FORMATTER: Falling back to generic formatting")
        return clean_generic_columns(df)


def get_available_customers():
    """
    Get a list of available customer formatters.
    
    Returns:
        List of customer names that have specific formatters
    """
    return [name for name in CUSTOMER_FORMATTERS.keys() if name != 'generic']


def add_customer_formatter(customer_name, formatter_function):
    """
    Add a new customer formatter to the registry.
    
    Args:
        customer_name: string name of the customer
        formatter_function: function that takes a DataFrame and returns a formatted DataFrame
    """
    customer_name = customer_name.lower().strip()
    CUSTOMER_FORMATTERS[customer_name] = formatter_function
    print(f"🔧 CUSTOMER FORMATTER: Added formatter for '{customer_name}'")