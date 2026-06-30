"""
BoMination — Streamlit web frontend

Upload one or more BOM PDFs, configure extraction settings, and download the
filled OMNI cost sheet for each. Page ranges can be auto-detected per file.

NOTE: This file is the presentation layer only. All extraction, pricing, and
cost-sheet logic lives in src/pipeline/* and is called unchanged.
"""

import streamlit as st
import sys
import os
import io
import base64
import zipfile
import tempfile
import pandas as pd
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
SRC  = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ── Page config (must be the first Streamlit call) ─────────────────────────────
st.set_page_config(
    page_title="BoMination · OMNI",
    page_icon=str(ROOT / "logo.jpeg") if (ROOT / "logo.jpeg").exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brand assets ───────────────────────────────────────────────────────────────
_logo = ROOT / "logo.jpeg"
if _logo.exists():
    st.logo(str(_logo), size="large")


@st.cache_data
def _logo_data_uri():
    """Base64 data URI for the logo so it can be embedded in the header card."""
    if not _logo.exists():
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(_logo.read_bytes()).decode()


# ══════════════════════════════════════════════════════════════════════════════
#  DESIGN SYSTEM  (OMNI brand: cobalt #1E50E0, amber #F5A623, ink #0F1B33)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --brand:        #1E50E0;   /* OMNI cobalt           */
    --brand-strong: #1A45C7;
    --brand-soft:   #EAF0FE;
    --amber:        #F5A623;   /* OMNI ring accent      */
    --amber-soft:   #FEF3DD;
    --ink:          #0F1B33;   /* deep navy text        */
    --muted:        #5B6780;   /* secondary text        */
    --faint:        #8A94A8;
    --surface:      #FFFFFF;
    --canvas:       #F5F7FB;
    --border:       #E6EAF2;
    --border-strong:#D6DCE8;
    --shadow-sm: 0 1px 2px rgba(15,27,51,.06), 0 1px 3px rgba(15,27,51,.04);
    --shadow-md: 0 4px 12px rgba(15,27,51,.08), 0 2px 4px rgba(15,27,51,.04);
    --shadow-lg: 0 12px 32px rgba(15,27,51,.12);
    --radius: 14px;
    --radius-sm: 10px;
    --ease: cubic-bezier(.4,0,.2,1);
}

/* ── Typography ─────────────────────────────────────────────────────────────*/
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
    color: var(--ink);
}

/* ── App canvas ─────────────────────────────────────────────────────────────*/
[data-testid="stAppViewContainer"] { background: var(--canvas); }
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 4rem !important;
    max-width: 1200px;
    animation: fadeUp .5s var(--ease) both;
}
@keyframes fadeUp { from { opacity:0; transform: translateY(8px);} to {opacity:1; transform:none;} }

/* ── Branded header card ────────────────────────────────────────────────────*/
.brand-header {
    display: flex; align-items: center; gap: 18px;
    background: linear-gradient(135deg, #ffffff 0%, #fbfcff 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow-md);
    padding: 20px 26px;
    margin-bottom: 26px;
    position: relative; overflow: hidden;
}
.brand-header::before {
    content:""; position:absolute; left:0; top:0; bottom:0; width:5px;
    background: linear-gradient(180deg, var(--brand) 0%, var(--amber) 100%);
}
.brand-header img { height: 52px; width:auto; border-radius: 8px; }
.brand-titles { display:flex; flex-direction:column; }
.brand-title {
    font-size: 1.85rem; font-weight: 800; letter-spacing: -.025em;
    line-height: 1.1; color: var(--ink);
}
.brand-title .accent { color: var(--brand); }
.brand-sub { font-size: .95rem; color: var(--muted); font-weight: 450; margin-top: 2px; }
.brand-spacer { flex: 1; }
.brand-chip {
    font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: var(--brand); background: var(--brand-soft);
    padding: 6px 12px; border-radius: 999px; border: 1px solid #d7e2fd;
}

/* ── Eyebrow section labels ─────────────────────────────────────────────────*/
.eyebrow {
    font-size: .72rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .12em; color: var(--faint); margin: 2px 0 10px;
}

/* ── Cards / bordered containers ────────────────────────────────────────────*/
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface);
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow-sm);
    transition: box-shadow .2s var(--ease), transform .2s var(--ease), border-color .2s var(--ease);
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: var(--shadow-md);
    border-color: var(--border-strong) !important;
}

/* ── Sidebar ────────────────────────────────────────────────────────────────*/
[data-testid="stSidebar"] {
    background: var(--surface);
    border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] .block-container { padding-top: 1rem !important; }

/* ── Pipeline step list ─────────────────────────────────────────────────────*/
.step-list { margin: 0; padding-left: 1.15rem; line-height: 2.1; font-size: .94rem; color: var(--ink); }
.step-list li::marker { color: var(--brand); font-weight: 700; }
.step-skip { opacity: .42; }

/* ── Status pills ───────────────────────────────────────────────────────────*/
.pill {
    display:inline-flex; align-items:center; gap:7px;
    padding: 5px 13px; border-radius: 999px;
    font-size: .8rem; font-weight: 650; letter-spacing: .005em;
}
.pill::before { content:""; width:7px; height:7px; border-radius:50%; }
.pill-on  { background: var(--brand-soft); color: var(--brand-strong); }
.pill-on::before  { background: var(--brand); box-shadow: 0 0 0 3px rgba(30,80,224,.15); }
.pill-off { background: #EEF1F6; color: var(--muted); }
.pill-off::before { background: var(--faint); }

/* ── Buttons ────────────────────────────────────────────────────────────────*/
.stButton > button, .stDownloadButton > button {
    border-radius: var(--radius-sm) !important;
    font-weight: 650 !important;
    letter-spacing: .01em;
    transition: all .18s var(--ease) !important;
    border: 1px solid var(--border-strong);
    box-shadow: var(--shadow-sm);
}
.stButton > button:hover, .stDownloadButton > button:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-md);
}
.stButton > button:active, .stDownloadButton > button:active { transform: translateY(0); }

/* Primary action — brand gradient */
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--brand) 0%, var(--brand-strong) 100%) !important;
    border: none !important;
    color: #fff !important;
    padding: .62rem 0 !important;
    box-shadow: 0 4px 14px rgba(30,80,224,.30) !important;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
    box-shadow: 0 8px 22px rgba(30,80,224,.38) !important;
}
.stButton > button[kind="primary"]:disabled {
    background: #C7D0E4 !important; box-shadow:none !important; color:#fff !important;
}

/* ── Inputs ─────────────────────────────────────────────────────────────────*/
.stTextInput input, [data-baseweb="select"] > div {
    border-radius: var(--radius-sm) !important;
    border-color: var(--border-strong) !important;
    transition: border-color .15s var(--ease), box-shadow .15s var(--ease);
}
.stTextInput input:focus, [data-baseweb="select"] > div:focus-within {
    border-color: var(--brand) !important;
    box-shadow: 0 0 0 3px rgba(30,80,224,.14) !important;
}

/* ── File uploader (dropzone) ───────────────────────────────────────────────*/
[data-testid="stFileUploaderDropzone"] {
    background: var(--brand-soft) !important;
    border: 1.5px dashed #B9CBF8 !important;
    border-radius: var(--radius) !important;
    transition: all .18s var(--ease);
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--brand) !important;
    background: #E3ECFE !important;
}

/* ── Expander ───────────────────────────────────────────────────────────────*/
[data-testid="stExpander"] details {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    background: var(--surface);
    box-shadow: var(--shadow-sm);
}

/* ── Progress + toggle accents ──────────────────────────────────────────────*/
[data-testid="stProgress"] > div > div > div { background: var(--brand) !important; }

/* ── Misc ───────────────────────────────────────────────────────────────────*/
hr { border-color: var(--border) !important; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--muted) !important; }

/* Hide Streamlit's default chrome for a clean internal-app shell. Hide ONLY the
   Deploy button + decoration — NOT the whole toolbar, because the sidebar
   expand arrow lives inside the toolbar and we need it to reopen the sidebar. */
#MainMenu, footer { visibility: hidden; }
[data-testid="stAppDeployButton"] { display: none !important; }
[data-testid="stDecoration"], [data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHeader"] { background: transparent !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
for key in ("run_results", "run_error"):
    if key not in st.session_state:
        st.session_state[key] = None

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — settings
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("<div class='eyebrow'>Configuration</div>", unsafe_allow_html=True)

    company = st.selectbox(
        "Company / Format",
        options=["", "Farrell", "NEL", "Primetals", "Riley Power", "Shanklin", "901D", "Amazon"],
        help="Selects the column mapping used for the cost sheet. Leave blank for the generic, format-agnostic layout.",
    )

    auto_pages = st.toggle(
        "Auto-detect BOM pages",
        value=True,
        help="Scan each PDF and find the pages that contain the BOM table automatically. "
             "Turn off to specify pages manually.",
    )

    page_range = st.text_input(
        "Page range",
        placeholder="e.g.  1-3   |   5   |   2,4,6",
        help="Used when auto-detect is off. Applies to every file in a batch.",
        disabled=auto_pages,
    )

    if not auto_pages:
        with st.expander("Page range syntax"):
            st.markdown("""
| Format | Meaning |
|--------|---------|
| `5` | Page 5 only |
| `1-3` | Pages 1 through 3 |
| `2,4,6` | Pages 2, 4 and 6 |
| `1-3,5` | Pages 1–3 plus 5 |
""")

    st.divider()

    st.markdown("<div class='eyebrow'>Pricing</div>", unsafe_allow_html=True)
    enable_prices = st.toggle(
        "Enable Live Price Lookup",
        value=True,
        help=(
            "ON: searches DuckDuckGo and Grainger/McMaster, then falls back to an "
            "Ollama knowledge estimate. OFF: skips all web requests and leaves the "
            "cost columns blank — faster and fully offline."
        ),
    )
    discount_pct = 0.0
    if enable_prices:
        st.markdown("<span class='pill pill-on'>Live lookup enabled</span>", unsafe_allow_html=True)
        st.caption("Web search and AI estimate will run for every part.")
        discount_pct = st.number_input(
            "Purchasing discount %",
            min_value=0.0, max_value=95.0, value=0.0, step=1.0,
            help="Subtracted from every looked-up price before it reaches the cost sheet. "
                 "e.g. enter 18 if purchasing averages 18% off list price.",
        )
        if discount_pct:
            st.caption(f"Each price reduced by {discount_pct:.0f}% before the cost sheet.")
    else:
        st.markdown("<span class='pill pill-off'>Offline — prices blank</span>", unsafe_allow_html=True)
        st.caption("No web requests. Cost columns are left empty.")

    st.divider()
    st.caption("BoMination · OMNI Control Technology")

# ══════════════════════════════════════════════════════════════════════════════
#  BRANDED HEADER
# ══════════════════════════════════════════════════════════════════════════════
_logo_uri = _logo_data_uri()
_logo_img = f"<img src='{_logo_uri}' alt='OMNI'/>" if _logo_uri else ""
st.markdown(
    f"""
    <div class="brand-header">
        {_logo_img}
        <div class="brand-titles">
            <div class="brand-title">Bo<span class="accent">Mination</span></div>
            <div class="brand-sub">AI-powered Bill of Materials extraction · OMNI Control Technology</div>
        </div>
        <div class="brand-spacer"></div>
        <div class="brand-chip">Internal Tool</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Upload + overview ──────────────────────────────────────────────────────────
col_upload, col_info = st.columns([3, 2], gap="large")

with col_upload:
    st.markdown("<div class='eyebrow'>Source documents</div>", unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "Upload BOM PDFs",
        type="pdf",
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="Upload one or many PDFs. Each produces its own cost sheet.",
    )
    n_files = len(uploaded_files) if uploaded_files else 0
    if n_files == 1:
        f = uploaded_files[0]
        st.caption(f"{f.name} · {f.size / 1024:.1f} KB")
    elif n_files > 1:
        total_kb = sum(f.size for f in uploaded_files) / 1024
        st.caption(f"{n_files} files · {total_kb:.1f} KB total — one cost sheet each")

    # ── Output file name (single-file only) ────────────────────────────────────
    cost_sheet_name = ""
    if n_files <= 1:
        if "cost_sheet_name" not in st.session_state:
            st.session_state["cost_sheet_name"] = "cost_sheet"
        if n_files == 1 and st.session_state.get("_last_pdf") != uploaded_files[0].name:
            st.session_state["cost_sheet_name"] = f"{Path(uploaded_files[0].name).stem}_cost_sheet"
            st.session_state["_last_pdf"] = uploaded_files[0].name
        cost_sheet_name = st.text_input(
            "Cost sheet file name",
            key="cost_sheet_name",
            help="Name for the downloaded cost sheet. The .xlsx extension is added automatically.",
        )
        st.caption("Only the cost sheet is produced. It downloads to your browser's default folder.")
    else:
        st.caption("In batch mode each cost sheet is named `<pdf name>_cost_sheet.xlsx`.")

with col_info:
    st.markdown("<div class='eyebrow'>Pipeline</div>", unsafe_allow_html=True)
    with st.container(border=True):
        step1 = (
            "<li>Auto-detect BOM pages, then extract with Ollama</li>"
            if auto_pages
            else "<li>Extract BOM tables with Ollama</li>"
        )
        step2 = (
            "<li>Look up part prices</li>"
            if enable_prices
            else "<li class='step-skip'>Look up part prices — skipped</li>"
        )
        st.markdown(
            "<ol class='step-list'>"
            f"{step1}{step2}"
            "<li>Map to OMNI cost sheet template</li>"
            "</ol>",
            unsafe_allow_html=True,
        )
        st.divider()
        if n_files == 0:
            st.caption("Upload one or more PDFs to continue.")
        elif not auto_pages and not page_range.strip():
            st.caption("Enter a page range, or turn on auto-detect.")
        else:
            st.caption(f"Ready to run — {n_files} file{'s' if n_files != 1 else ''}.")

st.write("")

# ── Run ────────────────────────────────────────────────────────────────────────
run_disabled = (n_files == 0) or (not auto_pages and not page_range.strip())

if st.button("Run Pipeline", type="primary", use_container_width=True, disabled=run_disabled):
    st.session_state.run_results = None
    st.session_state.run_error   = None

    with st.status(f"Processing {n_files} file{'s' if n_files != 1 else ''}…", expanded=True) as pipeline_status:
        try:
            from pipeline.main_pipeline import run_extract_bom_with_llm
            from pipeline.lookup_price   import lookup_prices_for_bom, _build_empty_output
            from pipeline.map_cost_sheet import map_and_insert_data
            from pipeline.extract_main   import detect_bom_pages

            results, errors = {}, []
            progress = st.progress(0.0)

            # Purchasing discount → applied to every looked-up price by the backend
            os.environ["BOM_DISCOUNT_PCT"] = str(discount_pct)

            with tempfile.TemporaryDirectory() as _tmpdir:
                tmpdir = Path(_tmpdir)

                for idx, up in enumerate(uploaded_files, start=1):
                    st.markdown(f"**[{idx}/{n_files}] {up.name}**")
                    try:
                        pdf_path = tmpdir / up.name
                        pdf_path.write_bytes(up.getvalue())
                        pdf_stem = pdf_path.stem

                        # ── Resolve page range (auto or manual) ────────────
                        if auto_pages:
                            rng, _pages = detect_bom_pages(str(pdf_path))
                            rng = rng or "all"
                            st.write(f"Auto-detected pages: {rng}")
                        else:
                            rng = page_range.strip()

                        # ── Step 1: Extract ────────────────────────────────
                        st.write("Extracting BOM tables with Ollama…")
                        merged_path = run_extract_bom_with_llm(str(pdf_path), rng, company)

                        df_merged = pd.read_excel(str(merged_path), keep_default_na=False, na_values=[""])

                        # ── Step 2: Pricing ────────────────────────────────
                        if enable_prices:
                            st.write("Looking up part prices…")
                            df_priced = lookup_prices_for_bom(df_merged)
                            priced = (df_priced["Unit Price in USD"] != "").sum()
                            st.write(f"Priced {priced} of {len(df_priced)} parts.")
                        else:
                            df_priced = _build_empty_output(df_merged)
                            st.write("Price lookup skipped — cost columns blank.")

                        prices_path = tmpdir / f"{pdf_stem}_merged_with_prices.xlsx"
                        df_priced.to_excel(str(prices_path), index=False)

                        # ── Step 3: Cost sheet ─────────────────────────────
                        if n_files == 1 and cost_sheet_name.strip():
                            fname = cost_sheet_name.strip()
                        else:
                            fname = f"{pdf_stem}_cost_sheet"
                        if not fname.lower().endswith(".xlsx"):
                            fname += ".xlsx"

                        os.environ["BOM_COMPANY"] = company
                        saved = map_and_insert_data(
                            str(prices_path), str(merged_path),
                            output_path=str(tmpdir / fname),
                        )
                        saved_path = Path(saved)
                        if saved_path.exists():
                            # ── Quality check: flag rows that may need review ──
                            def _qcol(df, opts):
                                return next((c for c in opts if c in df.columns), None)
                            def _blank(v):
                                return str(v).strip().upper() in ("", "N/A", "NAN", "NONE")
                            n_rows = len(df_merged)
                            pn_c  = _qcol(df_merged, ["Part Number", "MPN", "PART NUMBER"])
                            qty_c = _qcol(df_merged, ["Quantity", "QTY", "QUANTITY"])
                            miss_pn  = sum(_blank(v) for v in df_merged[pn_c])  if pn_c  else n_rows
                            miss_qty = sum(_blank(v) for v in df_merged[qty_c]) if qty_c else n_rows
                            est = int((df_priced["Distributor"] == "estimate").sum()) \
                                  if enable_prices and "Distributor" in df_priced.columns else 0

                            # de-dupe download keys if two PDFs share a stem
                            key = saved_path.name
                            if key in results:
                                key = f"{idx}_{key}"
                            results[key] = {
                                "name":  saved_path.name,
                                "bytes": saved_path.read_bytes(),
                                "source": up.name,
                                "rows": n_rows,
                                "miss_pn": int(miss_pn),
                                "miss_qty": int(miss_qty),
                                "estimates": est,
                            }
                            st.write(f"✓ Cost sheet ready: {saved_path.name}")
                        else:
                            errors.append(f"{up.name}: cost sheet not produced")
                            st.write("✗ Cost sheet was not produced.")

                    except Exception as file_exc:
                        errors.append(f"{up.name}: {file_exc}")
                        st.write(f"✗ Failed: {file_exc}")

                    progress.progress(idx / n_files)

                st.session_state.run_results = results

            n_ok = len(results)
            if n_ok == n_files:
                pipeline_status.update(label=f"Done — {n_ok} cost sheet{'s' if n_ok != 1 else ''} ready.",
                                       state="complete", expanded=False)
            elif n_ok > 0:
                pipeline_status.update(label=f"Finished with issues — {n_ok}/{n_files} succeeded.",
                                       state="complete", expanded=True)
            else:
                pipeline_status.update(label="All files failed.", state="error", expanded=True)

            if errors:
                st.session_state.run_error = "\n".join(errors)

        except Exception as exc:
            import traceback as _tb
            st.session_state.run_error = f"{exc}\n\n{_tb.format_exc()}"
            pipeline_status.update(label="Pipeline failed.", state="error", expanded=True)
            st.error(str(exc))

# ── Error detail ────────────────────────────────────────────────────────────────
if st.session_state.run_error:
    with st.expander("Issues / error details", expanded=True):
        st.code(st.session_state.run_error, language="text")

# ── Results ─────────────────────────────────────────────────────────────────────
if st.session_state.run_results:
    results = st.session_state.run_results
    st.divider()
    st.markdown("<div class='eyebrow'>Downloads</div>", unsafe_allow_html=True)

    # Batch: offer a single ZIP of all cost sheets
    if len(results) > 1:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for info in results.values():
                z.writestr(info["name"], info["bytes"])
        st.download_button(
            f"⬇ Download all {len(results)} cost sheets (ZIP)",
            data=buf.getvalue(),
            file_name="cost_sheets.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary",
            key="dl_zip",
        )
        st.write("")

    # Individual download cards
    for key, info in results.items():
        with st.container(border=True):
            st.markdown(f"**{info['name']}**")
            st.caption(f"from {info['source']} · {info.get('rows', 0)} parts")

            # ── Confidence / review banner ─────────────────────────────────────
            miss_pn  = info.get("miss_pn", 0)
            miss_qty = info.get("miss_qty", 0)
            est      = info.get("estimates", 0)
            flags = []
            if miss_pn:
                flags.append(f"{miss_pn} missing a part number")
            if miss_qty:
                flags.append(f"{miss_qty} missing a quantity")
            if flags:
                st.warning("⚠ Review recommended — " + "; ".join(flags)
                           + ". Open the sheet and check these rows.", icon="⚠️")
            else:
                st.success("✓ Every row has a part number and quantity.", icon="✅")
            if est:
                st.caption(f"💡 {est} price(s) are AI estimates (no web match) — verify before quoting.")

            st.download_button(
                label="Download",
                data=info["bytes"],
                file_name=info["name"],
                mime=MIME_XLSX,
                use_container_width=True,
                key=f"dl_{key}",
            )
