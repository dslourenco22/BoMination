import os
import sys
import subprocess
from pathlib import Path
from pipeline.validation_utils import validate_page_range, validate_pdf_file, handle_common_errors, generate_output_path
import logging

# Configure logging to reduce noise from third-party libraries
logging.getLogger('selenium').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

# Support both script and PyInstaller .exe paths
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = Path(sys._MEIPASS) / "src"
else:
    SCRIPT_DIR = Path(__file__).parent

# ============================================================================
# Core pipeline integration for local LLM text extraction stream (LD)
# ============================================================================
from pipeline.extract_main import extract_tables_from_pdf

def execute_extraction_step(pdf_path, pages, company):
    """
    Bypasses legacy manual ROI/Tabula selectors and passes text directly to Ollama.
    
    This function triggers the local LLM semantic parsing pipeline for table extraction.
    It uses pdfplumber + Ollama layout mapping engine for AI-powered extraction.
    
    Args:
        pdf_path (str): Path to the PDF file
        pages (str): Pages to extract from (e.g., "1-3" or "all")
        company (str): Company name for custom formatting
        
    Returns:
        DataFrame: Extracted table as pandas DataFrame, or None if extraction failed
    """
    print("[LLM] Triggering local LLM semantic parsing pipeline...")
    
    # This directly triggers your pdfplumber + ollama layout mapping engine (LD)
    extracted_dfs = extract_tables_from_pdf(pdf_path, pages=pages)
    
    if extracted_dfs and not extracted_dfs[0].empty:
        print(f"[OK] AI successfully extracted structured rows from the document.")
        return extracted_dfs[0]
    else:
        print("[ERROR] AI engine was unable to locate a valid parts list on the provided pages.")
        return None

def run_extract_bom_with_llm(pdf_path, pages, company):
    """
    Run BoM extraction using the local LLM engine (Ollama + pdfplumber).
    
    This is the new primary extraction method that bypasses Tabula entirely
    and uses semantic parsing via local LLM models.
    
    Args:
        pdf_path (str): Path to the PDF file
        pages (str): Pages to extract from
        company (str): Company name for formatting
        
    Returns:
        Path: Path to the merged output Excel file
    """
    print("=== Starting LLM-based BoM Extraction ===")
    print(f"Using local LLM engine for intelligent table extraction...")
    
    # Execute the LLM-based extraction (LD)
    extracted_df = execute_extraction_step(pdf_path, pages, company)
    
    if extracted_df is None:
        print("[ERROR] LLM extraction failed - no data returned")
        raise RuntimeError("LLM extraction failed to locate valid parts list")
    
    # Process and format the extracted data (LD)
    print(f"Processing extracted data (shape: {extracted_df.shape})...")
    
    try:
        from pipeline.extract_main import process_and_format_tables, merge_tables_and_export, save_tables_to_excel
        
        # Format the extracted table for the company (LD)
        formatted_tables = process_and_format_tables([extracted_df], company)
        
        if not formatted_tables:
            print("[ERROR] Customer formatting failed")
            raise RuntimeError("Failed to apply customer formatting")
        
        print(f"[OK] Formatted {len(formatted_tables)} table(s) successfully")
        
        # Generate output paths (save to PDF directory) (LD)
        pdf_dir = Path(pdf_path).parent
        pdf_name = Path(pdf_path).stem
        extracted_path = pdf_dir / f"{pdf_name}_extracted.xlsx"
        merged_path = pdf_dir / f"{pdf_name}_merged.xlsx"
        
        # Save individual extracted tables (LD)
        print(f"[SAVE] Saving individual extracted tables to: {extracted_path}")
        extracted_success = save_tables_to_excel(formatted_tables, str(extracted_path))
        
        if extracted_success:
            print(f"[OK] Individual tables saved: {extracted_path}")
        else:
            print(f"[WARNING] Warning: Failed to save individual tables to: {extracted_path}")
        
        # Save merged table (LD)
        print(f"[SAVE] Saving merged table to: {merged_path}")
        merge_success = merge_tables_and_export(formatted_tables, str(merged_path), "Combined_BoM", company)
        
        if not merge_success:
            print("[ERROR] Failed to save merged tables")
            raise RuntimeError("Failed to save merged tables")
        
        print(f"[OK] LLM extraction completed successfully!")
        print(f"   Output: {merged_path}")
        
        return merged_path
        
    except Exception as e:
        print(f"[ERROR] Processing error: {e}")
        raise

def check_all_dependencies():
    """
    Check all required dependencies for the LLM pipeline. (LD)
    Returns (can_run, dependency_status, missing_critical, warnings). (LD)
    """
    dependency_status = {}
    missing_critical = []
    warnings = []

    print("[INFO] Checking critical dependencies...")

    # ── Ollama (critical — replaces Java/Tabula) ───────────────────────────── (LD)
    try:
        from pipeline.validation_utils import check_ollama_connection
        ok, info, err = check_ollama_connection()
        dependency_status['Ollama'] = {'available': ok, 'version': info, 'error': err}
        if ok:
            print(f"[OK] Ollama: {info}")
            if info and 'not found' in info:
                warnings.append(info)
        else:
            missing_critical.append('Ollama')
            warnings.append(f"Ollama not available: {err}")
            print(f"[ERROR] Ollama check failed: {err}")
    except Exception as e:
        dependency_status['Ollama'] = {'available': False, 'version': None, 'error': str(e)}
        missing_critical.append('Ollama')
        warnings.append(f"Ollama check error: {e}")
        print(f"[ERROR] Ollama check error: {e}")

    # ── OCR (optional — needed only for image-based PDFs) ─────────────────── (LD)
    try:
        from pipeline.ocr_preprocessor import check_ocr_dependencies
        has_ocr, missing_ocr, dep_msgs, _ = check_ocr_dependencies()
        dependency_status['OCR'] = {
            'available': has_ocr,
            'missing': missing_ocr,
            'messages': dep_msgs,
        }
        if not has_ocr:
            warnings.append(f"OCR dependencies missing: {', '.join(missing_ocr)}")
            warnings.append("Image-based PDFs will not be supported without OCR tools")
            print(f"[WARNING] OCR dependencies missing: {', '.join(missing_ocr)}")
        else:
            print("[OK] All OCR dependencies available")
    except Exception as e:
        dependency_status['OCR'] = {'available': False, 'error': str(e)}
        warnings.append(f"OCR check failed: {e}")
        print(f"[WARNING] OCR check failed: {e}")

    can_run = len(missing_critical) == 0
    if can_run:
        print("[OK] All critical dependencies satisfied — application can run")
    else:
        print(f"[CRITICAL ERROR] Missing: {', '.join(missing_critical)}")

    return can_run, dependency_status, missing_critical, warnings

def run_extract_bom_with_roi_orchestration():
    """
    ROI extraction replaced by Ollama — routes directly to the LLM pipeline. (LD)
    The LLM locates the BOM table from text without needing a drawn ROI region. (LD)
    """
    print("[LLM] ROI mode ignored — using Ollama LLM extraction instead")
    return run_extract_bom()

def run_extract_bom():
    """
    Extract BoM tables using the Ollama LLM pipeline. (LD)
    Replaces the legacy Tabula subprocess invocation. (LD)
    """
    pdf_path = os.environ.get("BOM_PDF_PATH")
    pages = os.environ.get("BOM_PAGE_RANGE", "all")
    company = os.environ.get("BOM_COMPANY", "")

    print("=== Starting LLM BoM Extraction ===")
    return run_extract_bom_with_llm(pdf_path, pages, company)

def run_price_lookup(merged_path):
    print("STEP 2: Running price lookup...")
    env = os.environ.copy()
    env["BOM_EXCEL_PATH"] = str(merged_path or "")

    command = [sys.executable, str(SCRIPT_DIR / "lookup_price.py")]
    
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    
    print(result.stdout)
    if result.returncode != 0:
        print("ERROR: Price lookup failed:")
        print(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    
    # Match the filename that lookup_price.py actually saves
    merged_path_obj = Path(merged_path)
    base = merged_path_obj.stem.replace('_merged', '')
    prices_path = merged_path_obj.parent / f'{base}_merged_with_prices.xlsx'

    print(f"SUCCESS: Expected prices file: {prices_path}")
    return prices_path

def run_cost_sheet_mapping(prices_path, merged_path):
    print("STEP 3: Mapping to cost sheet template...")
    env = os.environ.copy()
    env["OEM_INPUT_PATH"] = str(prices_path or "")  # File with prices from OEMSecrets
    env["MERGED_BOM_PATH"] = str(merged_path or "")  # Original merged file for descriptions

    command = [sys.executable, str(SCRIPT_DIR / "map_cost_sheet.py")]
    
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    
    print(result.stdout)
    if result.returncode != 0:
        print("ERROR: Cost sheet mapping failed:")
        print(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)

def main():
    """Main pipeline with comprehensive validation and error handling."""
    print("Starting BoMination Pipeline...")
    
    # Validate inputs before starting
    pdf_path = os.environ.get("BOM_PDF_PATH")
    pages = os.environ.get("BOM_PAGE_RANGE") 
    company = os.environ.get("BOM_COMPANY")
    
    print(f"PDF Path: {pdf_path}")
    print(f"Page Range: {pages}")
    print(f"Company: {company or 'None specified'}")
    
    # Input validation
    pdf_valid, pdf_error = validate_pdf_file(pdf_path)
    if not pdf_valid:
        print(f"ERROR: PDF Validation Failed: {pdf_error}")
        sys.exit(1)
    
    pages_valid, pages_error, parsed_ranges = validate_page_range(pages)
    if not pages_valid:
        print(f"ERROR: Page Range Validation Failed: {pages_error}")
        sys.exit(1)
    
    print("SUCCESS: Input validation passed")
    
    try:
        # Step 1: Extract tables from PDF
        print("\n" + "="*50)
        print("STEP 1: EXTRACTING TABLES FROM PDF")
        print("="*50)
        merged_path = run_extract_bom()
        
        if not os.path.exists(merged_path):
            raise Exception(f"Table extraction failed: Expected output file {merged_path} was not created")
        
        print(f"SUCCESS: Step 1 completed successfully")
        
        # Step 2: Price lookup
        print("\n" + "="*50)
        print("STEP 2: RUNNING PRICE LOOKUP")
        print("="*50)
        prices_path = run_price_lookup(merged_path)
        print(f"SUCCESS: Step 2 completed successfully")
        
        # Step 3: Cost sheet mapping
        print("\n" + "="*50)
        print("STEP 3: MAPPING TO COST SHEET")
        print("="*50)
        run_cost_sheet_mapping(prices_path, merged_path)
        print(f"SUCCESS: Step 3 completed successfully")
        
        print("\n" + "="*50)
        print("SUCCESS: BoM AUTOMATION PIPELINE COMPLETED SUCCESSFULLY!")
        print("="*50)
        
    except subprocess.CalledProcessError as e:
        error_msg = handle_common_errors(e.stderr + "\n" + e.stdout if e.stderr else e.stdout)
        print(f"\nERROR: Pipeline step failed:\n{error_msg}")
        print(f"\nTechnical details:")
        print(f"Command: {' '.join(e.cmd)}")
        print(f"Return code: {e.returncode}")
        print(f"Output: {e.stdout}")
        print(f"Errors: {e.stderr}")
        sys.exit(1)
        
    except Exception as e:
        error_msg = handle_common_errors(str(e))
        print(f"\nERROR: Pipeline failed with unexpected error:\n{error_msg}")
        sys.exit(1)

def run_main_pipeline_direct(pdf_path, pages, company, output_directory, tabula_mode="balanced"):
    """
    Direct function call version of the main pipeline for PyInstaller compatibility.
    Sets environment variables and calls the main pipeline functions directly.
    
    Args:
        pdf_path (str): Path to the PDF file
        pages (str): Pages to extract from
        company (str): Company name for custom formatting
        output_directory (str): Output directory for results
        tabula_mode (str): Tabula extraction mode - 'conservative', 'balanced', or 'aggressive'
    """
    print("=== BoMination Dependency Check (Direct Mode) ===")
    can_run, dependency_status, missing_critical, warnings = check_all_dependencies()
    
    # Show warnings for missing optional dependencies
    for warning in warnings:
        print(f"[WARNING] {warning}")
    
    # If critical dependencies are missing, exit gracefully
    if not can_run:
        print(f"[CRITICAL ERROR] Cannot continue due to missing critical dependencies.")
        print(f"[CRITICAL ERROR] Application will now exit.")
        # Instead of sys.exit(), raise an exception that can be caught by the GUI
        raise RuntimeError(f"Missing critical dependencies: {', '.join(missing_critical)}")
    
    print("=== Starting Direct BoM Extraction ===")
    # Import the main functions from other modules
    from pipeline.extract_bom_tab import main as extract_main
    from pipeline.lookup_price import main as lookup_main  
    from pipeline.map_cost_sheet import main as map_main
    
    # Set environment variables for the pipeline steps
    os.environ["BOM_PDF_PATH"] = str(pdf_path)
    os.environ["BOM_PAGE_RANGE"] = str(pages)
    os.environ["BOM_COMPANY"] = str(company)
    os.environ["BOM_OUTPUT_DIRECTORY"] = str(output_directory)
    os.environ["BOM_TABULA_MODE"] = str(tabula_mode)
    
    # Check if this customer requires forced OCR preprocessing
    from omni_cust.customer_config import CUSTOMER_SETTINGS
    customer_key = company.lower().replace(" ", "_").replace("-", "_") if company else "generic"
    customer_settings = CUSTOMER_SETTINGS.get(customer_key, {})
    force_ocr = customer_settings.get("force_ocr", False)
    
    processed_pdf_path = pdf_path
    if force_ocr:
        print(f"[SPECIAL] SPECIAL CASE: Customer {company} requires forced OCR preprocessing")
        
        # Check OCR dependencies before attempting to use them
        try:
            from pipeline.ocr_preprocessor import check_ocr_dependencies
            has_ocr_deps, missing_deps, dep_messages, install_instructions = check_ocr_dependencies()
            
            if not has_ocr_deps:
                print(f"[WARNING] OCR dependencies missing: {', '.join(missing_deps)}")
                print(f"[WARNING] OCR will be skipped. Application will continue with regular extraction.")
                for msg in dep_messages:
                    print(f"[INFO] {msg}")
                # Continue with original PDF instead of failing
                print(f"[INFO] Continuing with original PDF: {pdf_path}")
            else:
                print(f"[OK] All OCR dependencies available")
                try:
                    from pipeline.ocr_preprocessor import preprocess_pdf_with_ocr
                    
                    # Create OCR processed version of the PDF
                    pdf_dir = Path(pdf_path).parent
                    pdf_name = Path(pdf_path).stem
                    ocr_pdf_path = pdf_dir / f"{pdf_name}_ocr.pdf"
                    
                    print(f"[OCR] OCR: Processing {pdf_path} -> {ocr_pdf_path}")
                    success, processed_path, error_msg = preprocess_pdf_with_ocr(
                        pdf_path=pdf_path,
                        output_path=str(ocr_pdf_path),
                        force_ocr=True
                    )
                    
                    if success and processed_path and Path(processed_path).exists():
                        processed_pdf_path = processed_path
                        print(f"[OK] OCR: Successfully processed PDF, using {processed_pdf_path}")
                        
                        # Update the environment variable to use the OCR-processed PDF
                        os.environ["BOM_PDF_PATH"] = str(processed_pdf_path)
                    else:
                        print(f"[WARNING] OCR: Failed to process PDF, using original {pdf_path}")
                        if error_msg:
                            print(f"[WARNING] OCR: Error details: {error_msg}")
                        
                except Exception as ocr_error:
                    print(f"[ERROR] OCR: Error during preprocessing: {ocr_error}")
                    print(f"[WARNING] OCR: Continuing with original PDF {pdf_path}")
                
        except ImportError as import_error:
            print(f"[WARNING] OCR: Could not import OCR modules: {import_error}")
            print(f"[WARNING] OCR: Continuing with original PDF {pdf_path}")
        except Exception as e:
            print(f"[ERROR] OCR: Unexpected error during OCR dependency check: {e}")
            print(f"[WARNING] OCR: Continuing with original PDF {pdf_path}")
    
    try:
        print("=== BoMination Pipeline Starting ===")
        print(f"PDF: {pdf_path}")
        print(f"Pages: {pages}")
        print(f"Company: {company}")
        print(f"Output: {output_directory}")
        print(f"Tabula mode: {tabula_mode}")
        print()
        
        # Step 1: Extract BoM tables using appropriate method
        print("STEP 1: Extracting BoM tables from PDF...")
        
        # Check if ROI is enabled to use orchestration
        use_roi = os.environ.get("BOM_USE_ROI", "false").lower() == "true"
        
        if use_roi:
            print("🎯 Using ROI-based extraction with orchestration...")
            merged_path = run_extract_bom_with_roi_orchestration()
        else:
            print("🔄 Using standard extraction workflow...")
            merged_path = run_extract_bom()
            
        print("✓ BoM extraction completed")
        
        # Verify the merged file exists
        if not merged_path.exists():
            print(f"[ERROR] ERROR: Expected merged file not found: {merged_path}")
            raise FileNotFoundError(f"Merged file not found: {merged_path}")
        
        print(f"[OK] Merged file found: {merged_path}")
        
        print(f"Looking for merged file in PDF directory: {merged_path}")
        print(f"(Output directory setting: {output_directory or 'None - using PDF directory'})")
        
        # Step 2: Lookup prices
        print("\nSTEP 2: Looking up supplier prices...")
        # Set the BOM_EXCEL_PATH for the price lookup step
        os.environ["BOM_EXCEL_PATH"] = str(merged_path)
        
        # Check if merged file exists before price lookup
        if not os.path.exists(merged_path):
            raise Exception(f"Cannot proceed with price lookup: merged file not found at {merged_path}")
        
        print(f"Input file for price lookup: {merged_path}")
        print(f"File exists: {os.path.exists(merged_path)}")
        print(f"File size: {os.path.getsize(merged_path)} bytes")
        
        try:
            print("Attempting to start price lookup process...")
            lookup_main()
            print("✓ Price lookup completed successfully")
        except Exception as lookup_error:
            print(f" Price lookup failed with error: {lookup_error}")
            print("This error prevents price data from being retrieved.")
            print("The pipeline will continue with the merged file, but prices will not be available.")
            
            # Log the full error for debugging
            import traceback
            print(f"Full error traceback:")
            print(traceback.format_exc())
            
            # Provide specific guidance based on error type
            error_str = str(lookup_error).lower()
            if "chromedriver" in error_str or "chrome" in error_str:
                print("\n🔧 ChromeDriver Issue Detected:")
                print("- Ensure Chrome browser is installed and up to date")
                print("- Verify chromedriver.exe is in the src folder")
                print("- Check that antivirus isn't blocking chromedriver.exe")
                print("- Try updating ChromeDriver to match your Chrome version")
            elif "timeout" in error_str:
                print("\n🔧 Timeout Issue Detected:")
                print("- Check your internet connection")
                print("- The website might be temporarily unavailable")
                print("- Try running the pipeline again in a few minutes")
            elif "connection" in error_str:
                print("\n🔧 Connection Issue Detected:")
                print("- Check your internet connection")
                print("- Corporate firewall might be blocking the connection")
                print("- Try running from a different network")
            
            print("\nContinuing without price data...")
        
        # Generate the expected prices file path
        # IMPORTANT: Price lookup saves files to PDF directory, not output directory
        # The lookup_price.py saves files next to the input file (merged_path)
        _mp = Path(merged_path)
        prices_path = str(_mp.parent / f'{_mp.stem.replace("_merged", "")}_merged_with_prices.xlsx')
        
        print(f"Looking for prices file: {prices_path}")
        
        # If price lookup failed, use the merged file as fallback
        if not os.path.exists(prices_path):
            print(f"⚠️ Price file not found: {prices_path}")
            print(f"Using merged file as fallback: {merged_path}")
            prices_path = merged_path
        else:
            print(f"✅ Price file found: {prices_path}")
        
        # Step 3: Map to cost sheet
        print("\nSTEP 3: Mapping to OMNI cost sheet template...")
        # Set the environment variables for the cost sheet mapping step
        os.environ["OEM_INPUT_PATH"] = str(prices_path)  # File with prices from OEMSecrets
        os.environ["MERGED_BOM_PATH"] = str(merged_path)  # Original merged file for descriptions
        os.environ["BOM_COMPANY"] = str(company)  # Ensure company parameter is available for mapping
        map_main()
        print("✓ Cost sheet mapping completed")
        
        print("\n=== Pipeline completed successfully! ===")
        return True
        
    except Exception as e:
        error_msg = handle_common_errors(str(e))
        print(f"\nERROR: Pipeline failed:\n{error_msg}")
        raise

def run_main_pipeline_with_gui_review(pdf_path, pages, company, output_directory, review_callback=None, tabula_mode="balanced"):
    """
    Direct function call version of the main pipeline with GUI review callback.
    The review_callback function will be called when the merged table is ready for review.
    
    Args:
        pdf_path (str): Path to the PDF file
        pages (str): Pages to extract from
        company (str): Company name for custom formatting
        output_directory (str): Output directory for results
        review_callback (callable): Function to call for GUI review
        tabula_mode (str): Tabula extraction mode - 'conservative', 'balanced', or 'aggressive'
    """
    print("=== BoMination Dependency Check ===")
    can_run, dependency_status, missing_critical, warnings = check_all_dependencies()
    
    # Show warnings for missing optional dependencies
    for warning in warnings:
        print(f"[WARNING] {warning}")
    
    # If critical dependencies are missing, exit gracefully
    if not can_run:
        print(f"[CRITICAL ERROR] Cannot continue due to missing critical dependencies.")
        print(f"[CRITICAL ERROR] Application will now exit.")
        # Instead of sys.exit(), raise an exception that can be caught by the GUI
        raise RuntimeError(f"Missing critical dependencies: {', '.join(missing_critical)}")
    
    print("=== Starting BoM Extraction with GUI Review ===")
    # Import the main functions from other modules
    from pipeline.extract_main import run_main_extraction_workflow
    from pipeline.extract_main import merge_tables_and_export
    from pipeline.lookup_price import main as lookup_main  
    from pipeline.map_cost_sheet import main as map_main
    
    # Set environment variables for the pipeline steps
    os.environ["BOM_PDF_PATH"] = str(pdf_path)
    os.environ["BOM_PAGE_RANGE"] = str(pages)
    os.environ["BOM_COMPANY"] = str(company)
    os.environ["BOM_OUTPUT_DIRECTORY"] = str(output_directory)
    os.environ["BOM_TABULA_MODE"] = str(tabula_mode)
    
    # Set BOM_SKIP_REVIEW to prevent double review windows
    # The GUI review callback will handle the review instead
    os.environ["BOM_SKIP_REVIEW"] = "true"
    
    print(f"[PIPELINE] PIPELINE: Starting pipeline with GUI review for {company}")
    print(f"[PIPELINE] PIPELINE: Review callback provided: {review_callback is not None}")
    print(f"[PIPELINE] PIPELINE: BOM_SKIP_REVIEW set to prevent double review")
    
    # Check if this customer requires forced OCR preprocessing
    from omni_cust.customer_config import CUSTOMER_SETTINGS
    customer_key = company.lower().replace(" ", "_").replace("-", "_") if company else "generic"
    customer_settings = CUSTOMER_SETTINGS.get(customer_key, {})
    force_ocr = customer_settings.get("force_ocr", False)
    
    processed_pdf_path = pdf_path
    if force_ocr:
        print(f"[SPECIAL] SPECIAL CASE: Customer {company} requires forced OCR preprocessing")
        
        # Check OCR dependencies before attempting to use them
        try:
            from pipeline.ocr_preprocessor import check_ocr_dependencies
            has_ocr_deps, missing_deps, dep_messages, install_instructions = check_ocr_dependencies()
            
            if not has_ocr_deps:
                print(f"[WARNING] OCR dependencies missing: {', '.join(missing_deps)}")
                print(f"[WARNING] OCR will be skipped. Application will continue with regular extraction.")
                for msg in dep_messages:
                    print(f"[INFO] {msg}")
                # Continue with original PDF instead of failing
                print(f"[INFO] Continuing with original PDF: {pdf_path}")
            else:
                print(f"[OK] All OCR dependencies available")
                try:
                    from pipeline.ocr_preprocessor import preprocess_pdf_with_ocr
                    
                    # Create OCR processed version of the PDF
                    pdf_dir = Path(pdf_path).parent
                    pdf_name = Path(pdf_path).stem
                    ocr_pdf_path = pdf_dir / f"{pdf_name}_ocr.pdf"
                    
                    print(f"[OCR] OCR: Processing {pdf_path} -> {ocr_pdf_path}")
                    success, processed_path, error_msg = preprocess_pdf_with_ocr(
                        pdf_path=pdf_path,
                        output_path=str(ocr_pdf_path),
                        force_ocr=True
                    )
                    
                    if success and processed_path and Path(processed_path).exists():
                        processed_pdf_path = processed_path
                        print(f"[OK] OCR: Successfully processed PDF, using {processed_pdf_path}")
                        
                        # Update the environment variable to use the OCR-processed PDF
                        os.environ["BOM_PDF_PATH"] = str(processed_pdf_path)
                    else:
                        print(f"[WARNING] OCR: Failed to process PDF, using original {pdf_path}")
                        if error_msg:
                            print(f"[WARNING] OCR: Error details: {error_msg}")
                        
                except Exception as ocr_error:
                    print(f"[ERROR] OCR: Error during preprocessing: {ocr_error}")
                    print(f"[WARNING] OCR: Continuing with original PDF {pdf_path}")
                
        except ImportError as import_error:
            print(f"[WARNING] OCR: Could not import OCR modules: {import_error}")
            print(f"[WARNING] OCR: Continuing with original PDF {pdf_path}")
        except Exception as e:
            print(f"[ERROR] OCR: Unexpected error during OCR dependency check: {e}")
            print(f"[WARNING] OCR: Continuing with original PDF {pdf_path}")
    
    try:
        print("=== BoMination Pipeline Starting (GUI Review Mode) ===")
        print(f"PDF: {pdf_path}")
        print(f"Pages: {pages}")
        print(f"Company: {company}")
        print(f"Output: {output_directory}")
        print()
        
        # Step 1: Extract BoM tables
        print("STEP 1: Extracting BoM tables from PDF...")
        
        # Check if ROI is enabled to use orchestration
        use_roi = os.environ.get("BOM_USE_ROI", "false").lower() == "true"
        
        if use_roi:
            print("🎯 Using ROI-based extraction with orchestration...")
            # ROI orchestration returns the merged path directly
            merged_path = run_extract_bom_with_roi_orchestration()
        else:
            print("🔄 Using standard extraction workflow...")
            run_main_extraction_workflow()
        
        print("✓ BoM extraction completed")
        
        # Generate the expected merged file path after extraction (if not using ROI)
        if not use_roi:
            pdf_dir = Path(pdf_path).parent
            pdf_name = Path(pdf_path).stem
            merged_path = pdf_dir / f"{pdf_name}_merged.xlsx"
        
        print(f"Looking for merged file: {merged_path}")
        
        if not merged_path.exists():
            raise FileNotFoundError(f"Merged file not found: {merged_path}")
        
        # If we have a review callback, read the merged data and call it
        if review_callback:
            print("Loading merged data for GUI review...")
            import pandas as pd
            # Read Excel file with keep_default_na=False to prevent "N/A" from being converted to NaN
            merged_df = pd.read_excel(merged_path, keep_default_na=False, na_values=[''])
            
            # Call the review callback with the merged data
            print("Calling GUI review callback...")
            print(f"About to call review callback with dataframe shape: {merged_df.shape}")
            reviewed_df = review_callback(merged_df)
            print(f"Review callback completed, returned dataframe shape: {reviewed_df.shape if reviewed_df is not None else 'None'}")
            
            # Save the reviewed data back to the file
            if reviewed_df is not None:
                print("Saving reviewed data...")
                # Apply final "N/A" filling before saving to ensure consistency
                reviewed_df = reviewed_df.fillna('N/A')
                reviewed_df = reviewed_df.replace(['', 'nan', 'None', 'NaN'], 'N/A')
                reviewed_df.to_excel(merged_path, index=False)
                print("✓ Reviewed data saved with N/A filling")
            else:
                print("No changes made during review")
            
            print("Review process completed, proceeding to price lookup...")
        else:
            print("No review callback provided, skipping review step")
        
        # Continue with the rest of the pipeline
        print("\nSTEP 2: Looking up part prices...")
        
        # Set the BOM_EXCEL_PATH for the price lookup step
        os.environ["BOM_EXCEL_PATH"] = str(merged_path)
        print(f"Setting BOM_EXCEL_PATH to: {merged_path}")
        
        # Check if merged file exists before price lookup
        if not merged_path.exists():
            raise Exception(f"Cannot proceed with price lookup: merged file not found at {merged_path}")
        
        print(f"Input file for price lookup: {merged_path}")
        print(f"File exists: {merged_path.exists()}")
        print(f"File size: {merged_path.stat().st_size} bytes")
        
        try:
            print("Attempting to start price lookup process...")
            lookup_main()
            print("✓ Price lookup completed successfully")
        except Exception as lookup_error:
            print(f"❌ Price lookup failed with error: {lookup_error}")
            print("This error prevents price data from being retrieved.")
            print("The pipeline will continue with the merged file, but prices will not be available.")
            
            # Log the full error for debugging
            import traceback
            print(f"Full error traceback:")
            print(traceback.format_exc())
        
        # Generate the expected priced file path
        priced_path = pdf_dir / f"{pdf_name}_merged_with_prices.xlsx"
        
        # Check if price lookup was successful
        if not priced_path.exists():
            print(f"⚠️  Warning: Priced file not found at {priced_path}")
            print("Price lookup may have failed, but continuing with cost sheet mapping...")
            print(f"Using merged file as fallback: {merged_path}")
            # Use merged file as fallback for cost sheet mapping
            prices_path = merged_path
        else:
            print(f"✅ Price file found: {priced_path}")
            prices_path = priced_path
        
        print("\nSTEP 3: Mapping to cost sheet...")
        
        # Set the environment variables for the cost sheet mapping step
        os.environ["OEM_INPUT_PATH"] = str(prices_path)  # File with prices (or merged file as fallback)
        os.environ["MERGED_BOM_PATH"] = str(merged_path)  # Original merged file for descriptions
        os.environ["BOM_COMPANY"] = str(company)  # Ensure company parameter is available for mapping
        
        print(f"Setting OEM_INPUT_PATH to: {prices_path}")
        print(f"Setting MERGED_BOM_PATH to: {merged_path}")
        print(f"Setting BOM_COMPANY to: {company}")
        
        map_main()
        print("✓ Cost sheet mapping completed")
        
        # Generate the expected cost sheet file path
        cost_sheet_path = pdf_dir / f"{pdf_name}_cost_sheet.xlsx"
        
        if not cost_sheet_path.exists():
            print(f"⚠️  Warning: Cost sheet not found at {cost_sheet_path}")
            print("Cost sheet mapping may have failed.")
        
        print("\n=== BoMination Pipeline Completed Successfully ===")
        
        # Return information about the generated files
        return {
            "success": True,
            "merged_file": str(merged_path),
            "priced_file": str(prices_path) if prices_path.exists() and prices_path != merged_path else None,
            "cost_sheet_file": str(cost_sheet_path) if cost_sheet_path.exists() else None,
            "pdf_directory": str(pdf_dir)
        }
        
    except Exception as e:
        print(f"❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    
    finally:
        # Clean up environment variable
        if "BOM_SKIP_REVIEW" in os.environ:
            del os.environ["BOM_SKIP_REVIEW"]


if __name__ == "__main__":
    main()