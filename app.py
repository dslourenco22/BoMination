"""
BoMination — Streamlit web frontend

Upload a BOM PDF, configure extraction settings, and download up to three
Excel outputs: the extracted BOM, the BOM with prices, and the filled OMNI
cost sheet template.
"""

import streamlit as st
import sys
import os
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
    page_title="BoMination",
    page_icon=str(ROOT / "logo.jpeg") if (ROOT / "logo.jpeg").exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Logo ───────────────────────────────────────────────────────────────────────
_logo = ROOT / "logo.jpeg"
if _logo.exists():
    st.logo(str(_logo), size="large")

# ── Theme / CSS ────────────────────────────────────────────────────────────────
# A restrained, corporate palette: deep slate text, a single steel-blue accent,
# generous whitespace, and soft card borders. No decorative emojis.
ACCENT = "#2F6FED"

st.markdown(f"""
<style>
    :root {{ --accent: {ACCENT}; }}

    .block-container {{
        padding-top: 2rem !important;
        max-width: 1180px;
    }}

    /* Masthead */
    .app-title {{
        font-size: 2.4rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin-bottom: 0.15rem;
    }}
    .app-subtitle {{
        font-size: 1.02rem;
        opacity: 0.62;
        font-weight: 400;
        margin-bottom: 0.25rem;
    }}
    .accent-rule {{
        height: 3px;
        width: 64px;
        background: var(--accent);
        border-radius: 2px;
        margin: 0.65rem 0 1.4rem 0;
    }}

    /* Section eyebrow labels */
    .eyebrow {{
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        opacity: 0.55;
        margin-bottom: 0.5rem;
    }}

    /* Pipeline step list */
    .step-list {{
        margin: 0;
        padding-left: 1.15rem;
        line-height: 2.05;
        font-size: 0.95rem;
    }}
    .step-skip {{ opacity: 0.45; }}

    /* Status pills */
    .pill {{
        display: inline-block;
        padding: 3px 12px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.01em;
    }}
    .pill-on  {{ background: rgba(47,111,237,0.14);  color: #2F6FED; }}
    .pill-off {{ background: rgba(120,120,120,0.16); color: #9aa0a6; }}

    /* Primary button */
    .stButton > button[kind="primary"] {{
        background: var(--accent);
        border: none;
        font-weight: 600;
        letter-spacing: 0.02em;
        border-radius: 8px;
        padding: 0.55rem 0;
    }}

    hr {{ border-color: rgba(140,140,140,0.18) !important; }}
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
for key in ("run_results", "run_error"):
    if key not in st.session_state:
        st.session_state[key] = None

# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR — settings
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("<div class='eyebrow'>Configuration</div>", unsafe_allow_html=True)

    company = st.selectbox(
        "Company / Format",
        options=["", "Farrell", "NEL", "Primetals", "Riley Power", "Shanklin", "901D", "Amazon"],
        help="Selects the column mapping used for the cost sheet. Leave blank for the generic Farrell layout.",
    )

    page_range = st.text_input(
        "Page range",
        placeholder="e.g.  1-3   |   5   |   2,4,6",
        help="Which PDF pages contain the BOM table.",
    )

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
    if enable_prices:
        st.markdown(
            "<span class='pill pill-on'>Live lookup enabled</span>",
            unsafe_allow_html=True,
        )
        st.caption("Web search and AI estimate will run for every part.")
    else:
        st.markdown(
            "<span class='pill pill-off'>Offline — prices blank</span>",
            unsafe_allow_html=True,
        )
        st.caption("No web requests. Cost columns are left empty.")

    st.divider()
    st.caption("BoMination · OMNI Internal")

# ══════════════════════════════════════════════════════════════════════════════
#  MASTHEAD
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div class='app-title'>BoMination</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='app-subtitle'>AI-powered Bill of Materials extraction from technical PDFs</div>",
    unsafe_allow_html=True,
)
st.markdown("<div class='accent-rule'></div>", unsafe_allow_html=True)

# ── Upload + overview ──────────────────────────────────────────────────────────
col_upload, col_info = st.columns([3, 2], gap="large")

with col_upload:
    st.markdown("<div class='eyebrow'>Source document</div>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Upload BOM PDF",
        type="pdf",
        label_visibility="collapsed",
        help="The Ollama model locates and parses the BOM table automatically.",
    )
    if uploaded_file:
        st.caption(f"{uploaded_file.name} · {uploaded_file.size / 1024:.1f} KB")

with col_info:
    st.markdown("<div class='eyebrow'>Pipeline</div>", unsafe_allow_html=True)
    with st.container(border=True):
        step2 = (
            "<li>Look up part prices</li>"
            if enable_prices
            else "<li class='step-skip'>Look up part prices — skipped</li>"
        )
        st.markdown(
            "<ol class='step-list'>"
            "<li>Extract BOM tables with Ollama</li>"
            f"{step2}"
            "<li>Map to OMNI cost sheet template</li>"
            "</ol>",
            unsafe_allow_html=True,
        )
        st.divider()
        if not page_range.strip():
            st.caption("Enter a page range to continue.")
        elif not uploaded_file:
            st.caption("Upload a PDF to continue.")
        else:
            st.caption("Ready to run.")

st.write("")

# ── Run ────────────────────────────────────────────────────────────────────────
run_disabled = not uploaded_file or not page_range.strip()

if st.button(
    "Run Pipeline",
    type="primary",
    use_container_width=True,
    disabled=run_disabled,
):
    st.session_state.run_results = None
    st.session_state.run_error   = None

    with st.status("Running BoMination pipeline…", expanded=True) as pipeline_status:
        try:
            from pipeline.main_pipeline import run_extract_bom_with_llm
            from pipeline.lookup_price  import lookup_prices_for_bom, _build_empty_output
            from pipeline.map_cost_sheet import map_and_insert_data

            with tempfile.TemporaryDirectory() as _tmpdir:
                tmpdir = Path(_tmpdir)

                # Save uploaded PDF to a working directory
                pdf_path = tmpdir / uploaded_file.name
                pdf_path.write_bytes(uploaded_file.getvalue())
                pdf_stem = pdf_path.stem

                # ── Step 1: Extract ────────────────────────────────────────
                st.write("Step 1 of 3 — Extracting BOM tables with Ollama…")
                merged_path = run_extract_bom_with_llm(
                    str(pdf_path), page_range.strip(), company
                )
                st.write("Extraction complete.")

                # ── Step 2: Price lookup (gated by the toggle) ─────────────
                df_merged = pd.read_excel(
                    str(merged_path), keep_default_na=False, na_values=[""]
                )

                if enable_prices:
                    st.write("Step 2 of 3 — Looking up part prices…")
                    df_priced = lookup_prices_for_bom(df_merged)
                    priced_count = (df_priced["Unit Price in USD"] != "").sum()
                    st.write(f"Prices retrieved — {priced_count} of {len(df_priced)} parts priced.")
                else:
                    st.write("Step 2 of 3 — Price lookup skipped (toggle off).")
                    df_priced = _build_empty_output(df_merged)
                    st.write("Cost columns left blank.")

                # Persist the OEMSecrets-schema frame for the mapper
                prices_path = tmpdir / f"{pdf_stem}_merged_with_prices.xlsx"
                df_priced.to_excel(str(prices_path), index=False)

                # ── Step 3: Cost sheet ─────────────────────────────────────
                st.write("Step 3 of 3 — Generating OMNI cost sheet…")
                os.environ["BOM_COMPANY"] = company
                map_and_insert_data(str(prices_path), str(merged_path))
                st.write("Cost sheet generated.")

                # ── Collect output bytes before the tmpdir is removed ──────
                cost_sheet_path = tmpdir / f"{pdf_stem}_cost_sheet.xlsx"
                output_files = {
                    "extracted":     {"label": "Extracted BOM",   "path": merged_path},
                    "merged_prices": {"label": "BOM with Prices",  "path": prices_path},
                    "cost_sheet":    {"label": "OMNI Cost Sheet",  "path": cost_sheet_path},
                }

                results = {}
                for key, meta in output_files.items():
                    p = Path(meta["path"])
                    if p.exists():
                        results[key] = {
                            "label": meta["label"],
                            "name":  p.name,
                            "bytes": p.read_bytes(),
                        }

                st.session_state.run_results = results
                st.session_state.run_error   = None

            pipeline_status.update(
                label="Pipeline complete — files ready to download.",
                state="complete",
                expanded=False,
            )

        except Exception as exc:
            import traceback as _tb
            st.session_state.run_error = f"{exc}\n\n{_tb.format_exc()}"
            pipeline_status.update(label="Pipeline failed.", state="error", expanded=True)
            st.error(str(exc))

# ── Error detail ────────────────────────────────────────────────────────────────
if st.session_state.run_error:
    with st.expander("Error details", expanded=True):
        st.code(st.session_state.run_error, language="text")

# ── Results ─────────────────────────────────────────────────────────────────────
if st.session_state.run_results:
    st.divider()
    st.markdown("<div class='eyebrow'>Downloads</div>", unsafe_allow_html=True)

    results = st.session_state.run_results
    dl_cols = st.columns(len(results), gap="medium")

    for col, (key, info) in zip(dl_cols, results.items()):
        with col:
            with st.container(border=True):
                st.markdown(f"**{info['label']}**")
                st.caption(info["name"])
                st.download_button(
                    label="Download",
                    data=info["bytes"],
                    file_name=info["name"],
                    mime=(
                        "application/vnd.openxmlformats-officedocument"
                        ".spreadsheetml.sheet"
                    ),
                    use_container_width=True,
                    key=f"dl_{key}",
                )
