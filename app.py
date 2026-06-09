"""
BoMination — Streamlit web frontend

Upload one or more BOM PDFs, configure extraction settings, and download the
filled OMNI cost sheet for each. Page ranges can be auto-detected per file.
"""

import streamlit as st
import sys
import os
import io
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
    if enable_prices:
        st.markdown("<span class='pill pill-on'>Live lookup enabled</span>", unsafe_allow_html=True)
        st.caption("Web search and AI estimate will run for every part.")
    else:
        st.markdown("<span class='pill pill-off'>Offline — prices blank</span>", unsafe_allow_html=True)
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
                            # de-dupe download keys if two PDFs share a stem
                            key = saved_path.name
                            if key in results:
                                key = f"{idx}_{key}"
                            results[key] = {
                                "name":  saved_path.name,
                                "bytes": saved_path.read_bytes(),
                                "source": up.name,
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
            st.caption(f"from {info['source']}")
            st.download_button(
                label="Download",
                data=info["bytes"],
                file_name=info["name"],
                mime=MIME_XLSX,
                use_container_width=True,
                key=f"dl_{key}",
            )
