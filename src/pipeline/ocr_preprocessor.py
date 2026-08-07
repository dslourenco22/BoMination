"""
OCR Preprocessing Module for BoMination

This module handles OCR preprocessing of PDF files to make them searchable
and compatible with table extraction tools like Tabula and Camelot.
"""

import os
import sys
import tempfile
import subprocess
from pathlib import Path
import logging
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_ocrmypdf_installation():
    """
    Check if ocrmypdf is available and properly installed.
    Returns (success, version_info, error_message)
    """
    try:
        import ocrmypdf
        # Test if we can run ocrmypdf
        result = subprocess.run([sys.executable, '-m', 'ocrmypdf', '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version_info = result.stdout.strip()
            logger.info(f"[OK] OCRmyPDF available: {version_info}")
            return True, version_info, None
        else:
            error_msg = f"OCRmyPDF command failed: {result.stderr}"
            logger.error(f"❌ {error_msg}")
            return False, None, error_msg
    except ImportError:
        error_msg = "OCRmyPDF not installed. Install with: pip install ocrmypdf"
        logger.error(f"❌ {error_msg}")
        return False, None, error_msg
    except subprocess.TimeoutExpired:
        error_msg = "OCRmyPDF check timed out"
        logger.error(f"❌ {error_msg}")
        return False, None, error_msg
    except Exception as e:
        error_msg = f"OCRmyPDF check failed: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return False, None, error_msg

def check_tesseract_installation():
    """
    Check if Tesseract OCR is available (required by OCRmyPDF).
    Returns (success, version_info, error_message)
    """
    # List of common Tesseract installation paths on Windows
    common_paths = [
        'tesseract',  # From PATH
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        r'C:\ProgramData\chocolatey\bin\tesseract.exe',
        r'C:\ProgramData\chocolatey\lib\tesseract\tools\tesseract.exe',
        r'C:\tools\tesseract\tesseract.exe',
    ]
    
    for tesseract_path in common_paths:
        try:
            # Try to run tesseract --version
            result = subprocess.run([tesseract_path, '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_info = result.stdout.split('\n')[0]  # First line has version
                logger.info(f"[OK] Tesseract available: {version_info}")
                return True, version_info, None
            else:
                continue  # Try next path
        except FileNotFoundError:
            continue  # Try next path
        except subprocess.TimeoutExpired:
            continue  # Try next path
        except Exception:
            continue  # Try next path
    
    # If we get here, Tesseract was not found in any of the common locations
    error_msg = "Tesseract not found. Please install Tesseract OCR engine."
    logger.error(f"[ERROR] {error_msg}")
    return False, None, error_msg

def check_ocr_dependencies():
    """
    Comprehensive check for all OCR dependencies.
    Returns (has_all_deps, missing_deps, install_instructions)
    """
    missing_deps = []
    messages = []
    
    # Check OCRmyPDF
    ocr_available, ocr_version, ocr_error = check_ocrmypdf_installation()
    if not ocr_available:
        missing_deps.append("OCRmyPDF")
        messages.append(f"OCRmyPDF: {ocr_error}")
    else:
        messages.append(f"OCRmyPDF: {ocr_version}")
    
    # Check Tesseract
    tesseract_available, tesseract_version, tesseract_error = check_tesseract_installation()
    if not tesseract_available:
        missing_deps.append("Tesseract")
        messages.append(f"Tesseract: {tesseract_error}")
    else:
        messages.append(f"Tesseract: {tesseract_version}")
    
    # Check Ghostscript (needed by OCRmyPDF)
    gs_available, gs_version, gs_error = check_ghostscript_installation()
    if not gs_available:
        missing_deps.append("Ghostscript")
        messages.append(f"Ghostscript: {gs_error}")
    else:
        messages.append(f"Ghostscript: {gs_version}")
    
    has_all_deps = len(missing_deps) == 0
    install_instructions = get_ocr_installation_instructions() if missing_deps else None
    
    return has_all_deps, missing_deps, messages, install_instructions

def check_ghostscript_installation():
    """
    Check if Ghostscript is available (required by OCRmyPDF).
    Returns (success, version_info, error_message)
    """
    # List of common Ghostscript installation paths on Windows
    common_paths = [
        'gs',  # From PATH
        'gswin64c',  # 64-bit console version
        'gswin32c',  # 32-bit console version
        r'C:\Program Files\gs\gs*\bin\gswin64c.exe',
        r'C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe',
        r'C:\ProgramData\chocolatey\bin\gs.exe',
    ]
    
    import glob
    
    for gs_pattern in common_paths:
        try:
            # Handle glob patterns
            if '*' in gs_pattern:
                matching_paths = glob.glob(gs_pattern)
                if matching_paths:
                    gs_path = matching_paths[0]  # Use first match
                else:
                    continue
            else:
                gs_path = gs_pattern
            
            # Try to run ghostscript --version
            result = subprocess.run([gs_path, '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_info = result.stdout.strip()
                logger.info(f"[OK] Ghostscript available: {version_info}")
                return True, version_info, None
            else:
                continue  # Try next path
        except FileNotFoundError:
            continue  # Try next path
        except subprocess.TimeoutExpired:
            continue  # Try next path
        except Exception:
            continue  # Try next path
    
    # If we get here, Ghostscript was not found
    error_msg = "Ghostscript not found. Please install Ghostscript."
    logger.error(f"[ERROR] {error_msg}")
    return False, None, error_msg
    """
    Check if Tesseract OCR is available (required by OCRmyPDF).
    Returns (success, version_info, error_message)
    """
    # List of common Tesseract installation paths on Windows
    common_paths = [
        'tesseract',  # From PATH
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        r'C:\ProgramData\chocolatey\bin\tesseract.exe',
        r'C:\ProgramData\chocolatey\lib\tesseract\tools\tesseract.exe',
        r'C:\tools\tesseract\tesseract.exe',
    ]
    
    for tesseract_path in common_paths:
        try:
            # Try to run tesseract --version
            result = subprocess.run([tesseract_path, '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version_info = result.stdout.split('\n')[0]  # First line has version
                logger.info(f"✅ Tesseract available: {version_info}")
                return True, version_info, None
            else:
                continue  # Try next path
        except FileNotFoundError:
            continue  # Try next path
        except subprocess.TimeoutExpired:
            continue  # Try next path
        except Exception:
            continue  # Try next path
    
    # If we get here, Tesseract was not found in any of the common locations
    error_msg = "Tesseract not found. Please install Tesseract OCR engine."
    logger.error(f"[ERROR] {error_msg}")
    return False, None, error_msg

def is_pdf_searchable(pdf_path):
    """
    Check if a PDF already has searchable text.
    Returns True if the PDF contains searchable text, False otherwise.
    """
    # Try multiple PDF reading approaches
    
    # Method 1: Try with PyPDF2
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            
            # Check if PDF has pages and we can access them
            if hasattr(pdf_reader, 'pages') and len(pdf_reader.pages) > 0:
                # Check first few pages for text content
                text_found = False
                pages_to_check = min(3, len(pdf_reader.pages))
                
                for page_num in range(pages_to_check):
                    try:
                        # Try to access the page
                        page = pdf_reader.pages[page_num]
                        
                        # Try to extract text
                        text = page.extract_text()
                        if text:
                            text = text.strip()
                            if len(text) > 10:  # Meaningful text content
                                text_found = True
                                break
                    except (IndexError, AttributeError, TypeError) as e:
                        logger.warning(f"Could not access page {page_num}: {e}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error extracting text from page {page_num}: {e}")
                        continue
                
                if text_found:
                    logger.info(f"✅ PDF appears to have searchable text")
                    return True
                    
    except ImportError:
        logger.warning("PyPDF2 not available for text detection")
    except Exception as e:
        logger.warning(f"PyPDF2 method failed: {e}")
    
    # Method 2: Try with pdfplumber (often better for text extraction)
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if pdf.pages:
                pages_to_check = min(3, len(pdf.pages))
                for page_num in range(pages_to_check):
                    try:
                        page = pdf.pages[page_num]
                        text = page.extract_text()
                        if text and len(text.strip()) > 10:
                            logger.info(f"✅ PDF appears to have searchable text (pdfplumber)")
                            return True
                    except Exception as e:
                        logger.warning(f"pdfplumber error on page {page_num}: {e}")
                        continue
                        
    except ImportError:
        logger.warning("pdfplumber not available for text detection")
    except Exception as e:
        logger.warning(f"pdfplumber method failed: {e}")
    
    # Method 3: Try with pymupdf (fitz) - often most robust
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        if doc.page_count > 0:
            pages_to_check = min(3, doc.page_count)
            for page_num in range(pages_to_check):
                try:
                    page = doc.load_page(page_num)
                    text = page.get_text()
                    if text and len(text.strip()) > 10:
                        logger.info(f"✅ PDF appears to have searchable text (PyMuPDF)")
                        doc.close()
                        return True
                except Exception as e:
                    logger.warning(f"PyMuPDF error on page {page_num}: {e}")
                    continue
        doc.close()
                    
    except ImportError:
        logger.warning("PyMuPDF not available for text detection")
    except Exception as e:
        logger.warning(f"PyMuPDF method failed: {e}")
    
    # If all methods fail, assume it's image-based
    logger.info(f"[WARNING] PDF appears to be image-based or has no searchable text")
    return False

def process_pdf_with_ocr(pdf_path, output_path=None, force_ocr=False):
    """
    Alias for preprocess_pdf_with_ocr to maintain compatibility.
    Process a PDF file with OCR to make it searchable.
    
    Args:
        pdf_path (str): Path to the input PDF file
        output_path (str, optional): Path for the output OCR'd PDF. If None, uses temp file.
        force_ocr (bool): Force OCR even if PDF appears to have text
    
    Returns:
        str or None: Path to the OCR'd PDF if successful, None if failed
    """
    success, ocr_pdf_path, error_message = preprocess_pdf_with_ocr(pdf_path, output_path, force_ocr)
    
    if success:
        return ocr_pdf_path
    else:
        logger.error(f"OCR processing failed: {error_message}")
        return None

def preprocess_pdf_for_table_extraction(pdf_path, output_path=None, enhance_for_tables=True):
    """
    Preprocess a PDF specifically for table extraction with enhanced OCR settings.
    
    Args:
        pdf_path: Path to input PDF
        output_path: Path for output PDF (optional)
        enhance_for_tables: Apply table-specific enhancements
    """
    logger.info(f"🔍 Starting table-optimized OCR preprocessing for: {pdf_path}")
    
    if output_path is None:
        output_path = pdf_path.replace('.pdf', '_ocr_table_enhanced.pdf')
    
    # Check if OCRmyPDF is available
    ocr_available, _, ocr_error = check_ocrmypdf_installation()
    tesseract_available, _, tesseract_error = check_tesseract_installation()
    
    if not ocr_available or not tesseract_available:
        logger.warning("OCR tools not available - skipping table enhancement")
        return False, pdf_path, "OCR tools not available"
    
    try:
        import ocrmypdf
        
        logger.info("Applying table-optimized OCR settings...")
        logger.info("   • Force OCR: True")
        logger.info("   • Deskew: True") 
        logger.info("   • Clean: True")
        logger.info("   • Remove background: True")
        logger.info("   • High DPI (600): True")
        if enhance_for_tables:
            logger.info("   • Table-specific Tesseract settings enabled")
        
        # Table-specific OCR configuration
        tesseract_config = []
        if enhance_for_tables:
            # Tesseract PSM (Page Segmentation Mode) for tables
            # PSM 6: Uniform block of text (good for tables)
            tesseract_config = [
                '--psm', '6',           # Uniform block of text
                '-c', 'preserve_interword_spaces=1',  # Preserve spacing
                '-c', 'textord_heavy_nr=1',          # Better table detection
                '-c', 'textord_tabfind_show_vlines=1', # Show vertical lines
                '-c', 'textord_tabfind_show_columns=1', # Show columns
                '-c', 'load_system_dawg=0',          # Disable dictionary
                '-c', 'load_freq_dawg=0',            # Disable frequency dictionary
                '-c', 'load_punc_dawg=0',            # Disable punctuation dictionary
                '-c', 'load_number_dawg=0',          # Disable number dictionary
                '-c', 'load_unambig_dawg=0',         # Disable unambiguous dictionary
                '-c', 'load_bigram_dawg=0',          # Disable bigram dictionary
                '-c', 'load_fixed_length_dawgs=0',   # Disable fixed length dictionary
                '-c', 'wordrec_enable_assoc=0',      # Disable word association
                '-c', 'textord_single_height_mode=1' # Single height mode for tables
            ]
        
        # Run OCR preprocessing
        ocrmypdf.ocr(
            pdf_path,
            output_path,
            language='eng',
            deskew=True,
            clean=True,
            clean_final=True,
            remove_background=True,
            force_ocr=True,  # Force OCR even if text exists
            redo_ocr=True,   # Redo OCR on existing text
            optimize=1,      # Light optimization
            oversample=600,  # High DPI for better table lines
            image_dpi=600,   # High DPI for embedded images
            jpeg_quality=95, # High quality
            png_quality=95,  # High quality
            tesseract_config=tesseract_config,
            progress_bar=False
        )                         # NOTE: no `quiet=` — dropped in OCRmyPDF 17
        
        if os.path.exists(output_path):
            logger.info(f"[OK] Table-optimized OCR preprocessing completed: {output_path}")
            return True, output_path, None
        else:
            logger.error("[ERROR] OCR preprocessing failed - output file not created")
            return False, pdf_path, "Output file not created"
            
    except Exception as e:
        error_msg = f"Table-optimized OCR preprocessing failed: {e}"
        logger.error(f"[ERROR] {error_msg}")
        return False, pdf_path, error_msg


def preprocess_pdf_with_ocr(pdf_path, output_path=None, force_ocr=False):
    """
    Preprocess a PDF file with OCR to make it searchable.
    
    Args:
        pdf_path (str): Path to the input PDF file
        output_path (str, optional): Path for the output OCR'd PDF. If None, uses temp file.
        force_ocr (bool): Force OCR even if PDF appears to have text
    
    Returns:
        tuple: (success, ocr_pdf_path, error_message)
    """
    pdf_path = Path(pdf_path)
    
    # Validate input
    if not pdf_path.exists():
        error_msg = f"PDF file not found: {pdf_path}"
        logger.error(f"[ERROR] {error_msg}")
        return False, None, error_msg
    
    # Check if OCR is available
    ocr_available, ocr_version, ocr_error = check_ocrmypdf_installation()
    if not ocr_available:
        return False, None, ocr_error
    
    # Check if Tesseract is available
    tesseract_available, tesseract_version, tesseract_error = check_tesseract_installation()
    if not tesseract_available:
        return False, None, tesseract_error
    
    # Check if PDF already has searchable text (unless forced)
    if not force_ocr and is_pdf_searchable(pdf_path):
        logger.info("[INFO] PDF already appears to have searchable text, skipping OCR")
        return True, str(pdf_path), None
    
    # Setup output path
    if output_path is None:
        # Create a temporary file for OCR'd PDF
        temp_dir = tempfile.mkdtemp(prefix="bomination_ocr_")
        output_path = Path(temp_dir) / f"{pdf_path.stem}_ocr.pdf"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"[INFO] Starting OCR preprocessing: {pdf_path.name}")
    logger.info(f"[INFO] Input: {pdf_path}")
    logger.info(f"[INFO] Output: {output_path}")

    try:
        # Import ocrmypdf here to avoid import issues if not available
        import ocrmypdf
        
        # OCR the PDF with optimized settings for table extraction
        # Input/output are passed positionally: OCRmyPDF 17 renamed the first
        # parameter to `input_file_or_options`, so `input_file=` no longer binds.
        # Positional works on every version.
        ocrmypdf.ocr(
            str(pdf_path),
            str(output_path),
            deskew=True,          # Correct page rotation
            remove_background=False,  # Keep backgrounds for table detection
            optimize=1,           # Light optimization to keep structure
            force_ocr=force_ocr,  # Force OCR even if text detected
            skip_text=False,      # Don't skip existing text
            redo_ocr=False,       # Don't redo OCR if already done
            language='eng',       # English language for OCR
            oversample=600,       # Rasterize at 600 DPI instead of 400 for better table lines
            image_dpi=600,        # Ensure embedded images use 600 DPI
            progress_bar=False    # Disable progress bar for cleaner output
        )                         # NOTE: no `quiet=` — dropped in OCRmyPDF 17
        
        if output_path.exists():
            logger.info(f"[OK] OCR preprocessing completed successfully")
            logger.info(f"[INFO] OCR'd PDF saved to: {output_path}")
            return True, str(output_path), None
        else:
            error_msg = "OCR completed but output file not found"
            logger.error(f"[ERROR] {error_msg}")
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"OCR preprocessing failed: {str(e)}"
        logger.error(f"[ERROR] {error_msg}")
        
        # Clean up partial output
        if output_path.exists():
            try:
                output_path.unlink()
            except:
                pass
        
        return False, None, error_msg

def cleanup_ocr_temp_files(ocr_pdf_path):
    """
    Clean up temporary OCR files.
    
    Args:
        ocr_pdf_path (str): Path to the OCR'd PDF file to clean up
    """
    if not ocr_pdf_path:
        return
        
    try:
        ocr_path = Path(ocr_pdf_path)
        
        # If it's in a temp directory we created, remove the entire directory
        if "bomination_ocr_" in str(ocr_path.parent):
            temp_dir = ocr_path.parent
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.info(f"🧹 Cleaned up OCR temp directory: {temp_dir}")
        else:
            # Just remove the file
            if ocr_path.exists():
                ocr_path.unlink()
                logger.info(f"🧹 Cleaned up OCR file: {ocr_path}")
                
    except Exception as e:
        logger.warning(f"[WARNING] Could not clean up OCR temp files: {e}")

def get_ocr_installation_instructions():
    """
    Get platform-specific installation instructions for OCR dependencies.
    """
    import platform
    
    system = platform.system().lower()
    
    if system == "windows":
        return """
To install OCR support on Windows:

1. Install OCRmyPDF:
   pip install ocrmypdf

2. Install Tesseract OCR engine:
   - Download from: https://github.com/UB-Mannheim/tesseract/wiki
   - Or use chocolatey: choco install tesseract
   - Or use conda: conda install -c conda-forge tesseract

3. Make sure Tesseract is in your PATH
   - Add the Tesseract installation directory to your system PATH
   - Default location: C:\\Program Files\\Tesseract-OCR\\

4. Restart your application after installation
"""
    elif system == "darwin":  # macOS
        return """
To install OCR support on macOS:

1. Install OCRmyPDF:
   pip install ocrmypdf

2. Install Tesseract OCR engine:
   brew install tesseract

3. Restart your application after installation
"""
    else:  # Linux
        return """
To install OCR support on Linux:

1. Install OCRmyPDF:
   pip install ocrmypdf

2. Install Tesseract OCR engine:
   # Ubuntu/Debian:
   sudo apt-get install tesseract-ocr
   
   # CentOS/RHEL:
   sudo yum install tesseract
   
   # Arch Linux:
   sudo pacman -S tesseract

3. Restart your application after installation
"""

# Test function for development
def test_ocr_functionality():
    """Test OCR functionality with a sample PDF."""
    print("Testing OCR functionality...")
    
    # Check installations
    print("\n1. Checking OCRmyPDF installation...")
    ocr_ok, ocr_version, ocr_error = check_ocrmypdf_installation()
    if not ocr_ok:
        print(f"[ERROR] OCRmyPDF: {ocr_error}")
        print(get_ocr_installation_instructions())
        return False
    print(f"[OK] OCRmyPDF: {ocr_version}")

    print("\n2. Checking Tesseract installation...")
    tesseract_ok, tesseract_version, tesseract_error = check_tesseract_installation()
    if not tesseract_ok:
        print(f"[ERROR] Tesseract: {tesseract_error}")
        print(get_ocr_installation_instructions())
        return False
    print(f"[OK] Tesseract: {tesseract_version}")

    print("\n[INFO] All OCR components are available!")
    return True

if __name__ == "__main__":
    # Run test when module is executed directly
    test_ocr_functionality()