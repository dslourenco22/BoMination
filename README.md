# BoMination - Bill of Materials Processing Tool

A Python-based tool for extracting, processing, and managing Bill of Materials (BoM) data from PDF documents using a local LLM (Ollama) for intelligent, semantic table parsing.

## Features

- **AI-Powered Extraction**: Uses a local Ollama LLM (llama3.2 or llama3.2:1b for faster CPU-only machines) with pdfplumber for semantic BoM table parsing — no Tabula or Java required
- **OCR Support**: Automatically preprocesses scanned/image-based PDFs via OCRmyPDF before extraction
- **Multi-Customer Formatting**: Auto-detects and applies customer-specific column mappings and rules
- **Interactive GUI**: ttkbootstrap-based interface with tabbed layout, settings panel, and table preview
- **Review & Edit**: Pre-export review window for inspecting and editing extracted data before saving
- **Price Lookup**: Automated price matching against cost sheets (Excel)
- **Excel Export**: Exports processed BoM data to `.xlsx` format
- **Standalone Executable**: PyInstaller-based `.exe` for sales team deployment (no Python required)

## Project Structure

```
BoMination/
├── src/
│   ├── gui/
│   │   ├── BoMinationApp.py       # Main application entry point & GUI
│   │   ├── review_window.py       # Pre-export review/edit window
│   │   ├── roi_picker.py          # Region-of-interest picker
│   │   ├── settings_tab.py        # Settings & configuration tab
│   │   └── table_selector.py      # Interactive table selection GUI
│   ├── pipeline/
│   │   ├── extract_main.py        # LLM extraction engine (Ollama + pdfplumber)
│   │   ├── extract_bom_tab.py     # Tabula-based extractor (fallback)
│   │   ├── extract_bom_cam.py     # Camelot-based extractor (fallback)
│   │   ├── lookup_price.py        # Price lookup & matching
│   │   ├── main_pipeline.py       # Orchestrates the full extraction pipeline
│   │   ├── map_cost_sheet.py      # Cost sheet column mapping
│   │   ├── ocr_preprocessor.py    # OCRmyPDF preprocessing for scanned PDFs
│   │   ├── console_utils.py       # Console/logging utilities
│   │   └── validation_utils.py    # Input validation and error handling
│   └── omni_cust/
│       ├── customer_config.py     # Customer definitions & auto-detection keywords
│       └── customer_formatters.py # Per-customer column formatting logic
├── assets/
│   └── BoMination_black.ico       # Application icon
├── Files/                         # Sample input files and cost sheets
├── SalesTeam_Package/             # Deployment package for sales team
│   ├── QUICK_START.txt
│   └── deploy.bat
├── build_pyinstaller.py           # PyInstaller build script
├── create_sales_package.py        # Packages .exe for sales team distribution
├── BoMinationApp.spec             # PyInstaller spec file
└── requirements.txt               # Python dependencies
```

## Supported Customers

The application auto-detects the customer from document content and applies specialized formatting rules:

## Requirements

- Python 3.8+
- [Ollama](https://ollama.com/) running locally with `llama3.2` (recommended) or `llama3.2:1b` (faster on CPU-only machines) pulled
- Tesseract OCR (required by OCRmyPDF for scanned/image-based PDFs)

> **Note:** Java is no longer required. The primary extraction pipeline uses pdfplumber + Ollama and does not depend on Tabula.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/dslourenco22/BoMination
   cd BoMination
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install and start Ollama:**
   ```bash
   # Install from https://ollama.com, then:
   ollama pull llama3.2        # full model (recommended, requires GPU or is slow on CPU)
   ollama pull llama3.2:1b     # lightweight alternative — ~3x faster on CPU-only machines
   ollama serve
   ```

4. **(Optional) Install Tesseract for scanned PDF support:**
   - macOS: `brew install tesseract`
   - Windows: [UB-Mannheim Tesseract installer](https://github.com/UB-Mannheim/tesseract/wiki)

## Usage

### Running the Application

```bash
python src/gui/BoMinationApp.py
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BOM_LLM_MODEL` | Ollama model to use for extraction | `llama3.2` (use `llama3.2:1b` for CPU-only) |
| `BOM_LLM_ENDPOINT` | Ollama API endpoint | `http://127.0.0.1:11434` |
| `BOM_PDF_PATH` | Path to the PDF file to process | _(set via GUI)_ |
| `BOM_PAGE_RANGE` | Page range to extract (e.g. `1-3` or `all`) | `all` |
| `BOM_COMPANY` | Customer name for specialized formatting | `generic` |
| `BOM_OUTPUT_DIRECTORY` | Output directory for processed files | _(set via GUI)_ |

### Table Detection Modes

Configurable in the **Settings** tab:

- **Conservative** — fewer false positives; may miss some tables
- **Balanced** — recommended default
- **Aggressive** — detects more tables but may include non-table content

## Building the Executable

```bash
python build_pyinstaller.py
```

The output `.exe` is a self-contained portable application (~90 MB) that requires no Python installation.

## Sales Team Deployment

```bash
python create_sales_package.py
```

This generates the `SalesTeam_Package/` folder containing the `.exe`, quick-start guide, and deployment scripts. End users simply double-click `BoMinationApp.exe` — no installation required.

## License

Proprietary software. All rights reserved.

## Support

For support and questions, contact the development team.
