"""
Input validation and error handling utilities for BoMination pipeline. (LD)
"""
import re
import os
import subprocess
import webbrowser
import sys
from pathlib import Path

# winreg is Windows-only; safe here because the app targets Windows (LD)
try:
    import winreg
except ImportError:
    winreg = None  # Non-Windows dev environment (LD)

# Selenium is legacy; make import conditional so it can be removed safely (LD)
try:
    from selenium.common.exceptions import WebDriverException
except ImportError:
    WebDriverException = Exception


def validate_page_range(page_range_str):
    """
    Validate page range format and return parsed ranges.
    
    Args:
        page_range_str (str): Page range string (e.g., "1-3", "5", "2,4,6", "1-3,5,7-9")
    
    Returns:
        tuple: (is_valid, error_message, parsed_ranges)
    """
    if not page_range_str or not page_range_str.strip():
        return False, "Page range cannot be empty.", None
    
    page_range_str = page_range_str.strip()
    
    # Pattern to match valid page ranges: numbers, commas, hyphens, and spaces
    pattern = r'^[\d\s,\-]+$'
    if not re.match(pattern, page_range_str):
        return False, "Invalid characters in page range. Use only numbers, commas, and hyphens (e.g., '1-3,5,7-9').", None
    
    # Split by commas and validate each part
    parts = [part.strip() for part in page_range_str.split(',')]
    parsed_ranges = []
    
    for part in parts:
        if not part:
            continue
            
        if '-' in part:
            # Range like "1-3"
            try:
                start, end = part.split('-', 1)
                start_num = int(start.strip())
                end_num = int(end.strip())
                
                if start_num <= 0 or end_num <= 0:
                    return False, f"Page numbers must be positive integers. Found: {part}", None
                
                if start_num > end_num:
                    return False, f"Invalid range '{part}': start page cannot be greater than end page.", None
                
                parsed_ranges.append((start_num, end_num))
                
            except ValueError:
                return False, f"Invalid range format: '{part}'. Use format like '1-3'.", None
        else:
            # Single page like "5"
            try:
                page_num = int(part)
                if page_num <= 0:
                    return False, f"Page numbers must be positive integers. Found: {part}", None
                parsed_ranges.append(page_num)
            except ValueError:
                return False, f"Invalid page number: '{part}'. Must be a positive integer.", None
    
    if not parsed_ranges:
        return False, "No valid page numbers found in the range.", None
    
    return True, None, parsed_ranges


def validate_pdf_file(pdf_path):
    """
    Validate PDF file exists and is accessible.
    
    Args:
        pdf_path (str): Path to PDF file
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not pdf_path or not pdf_path.strip():
        return False, "PDF file path cannot be empty."
    
    pdf_path = pdf_path.strip()
    
    if not os.path.exists(pdf_path):
        return False, f"PDF file does not exist: {pdf_path}"
    
    if not pdf_path.lower().endswith('.pdf'):
        return False, f"File must be a PDF. Found: {os.path.splitext(pdf_path)[1]}"
    
    try:
        # Check if file is readable
        with open(pdf_path, 'rb') as f:
            f.read(4)  # Just read first 4 bytes to check accessibility
    except PermissionError:
        return False, f"Permission denied: Cannot access PDF file at {pdf_path}"
    except Exception as e:
        return False, f"Error accessing PDF file: {str(e)}"
    
    return True, None


def check_ollama_connection():
    """
    Verify that a local Ollama instance is reachable and has the required model. (LD)
    Returns (is_ok, version_info, error_message) to match legacy dependency-check callers. (LD)
    """
    host = os.environ.get('BOM_LLM_ENDPOINT', 'http://127.0.0.1:11434')
    model = os.environ.get('BOM_LLM_MODEL', 'llama3.2')
    try:
        import ollama
        client = ollama.Client(host=host)
        models_response = client.list()
        # models_response.models is a list of ModelResponse objects (LD)
        available = [m.model for m in models_response.models]
        # Accept if the configured model (with or without tag) is in the list (LD)
        match = any(model.split(':')[0] in m for m in available)
        if match:
            return True, f'Ollama {host} | model: {model}', None
        # Model not pulled yet — still report OK so the user sees a clear warning (LD)
        return (
            True,
            f'Ollama running at {host} but model "{model}" not found. '
            f'Run: ollama pull {model}',
            None,
        )
    except Exception as e:
        return (
            False,
            None,
            f'Ollama not reachable at {host}: {e}  —  '
            f'Install Ollama from https://ollama.com and run: ollama pull {model}',
        )


def check_java_installation():
    """
    Java is no longer required — the LLM pipeline replaced Tabula. (LD)
    Kept so existing GUI imports do not break. (LD)
    Returns (is_ok, version_info, error_message). (LD)
    """
    return True, 'Java not required (LLM mode active)', None


def check_chromedriver_availability():
    """
    ChromeDriver is no longer required — price lookup uses DuckDuckGo + Ollama. (LD)
    Kept so existing GUI imports do not break. (LD)
    Returns (is_ok, version_info, error_message). (LD)
    """
    return True, 'ChromeDriver not required (LLM price lookup active)', None


def handle_common_errors(error_message, error_type=None):
    """
    Handle common errors with helpful user guidance.
    
    Args:
        error_message (str): The error message
        error_type (str): Type of error for specific handling
    
    Returns:
        str: User-friendly error message with guidance
    """
    error_lower = error_message.lower()
    
    # Java-related errors
    if 'java' in error_lower and ('not found' in error_lower or 'command not found' in error_lower):
        return (
            "❌ Java Not Found\n\n"
            "The PDF table extraction requires Java to be installed.\n\n"
            "Solutions:\n"
            "1. Install Java from: https://www.java.com/download/\n"
            "2. Restart your computer after installation\n"
            "3. Verify installation by opening Command Prompt and typing 'java -version'\n\n"
            "Would you like to open the Java download page?"
        )
    
    # ChromeDriver related errors
    if 'chromedriver' in error_lower or 'chrome' in error_lower:
        if 'not found' in error_lower or 'no such file' in error_lower:
            return (
                "❌ ChromeDriver Not Found\n\n"
                "The price lookup feature requires ChromeDriver.\n\n"
                "Solutions:\n"
                "1. Ensure chromedriver.exe is in the application folder\n"
                "2. Download ChromeDriver from: https://chromedriver.chromium.org/\n"
                "3. Make sure ChromeDriver version matches your Chrome browser version\n\n"
                "Original error: " + error_message
            )
        elif 'version' in error_lower or 'compatibility' in error_lower:
            return (
                "❌ ChromeDriver Version Mismatch\n\n"
                "ChromeDriver version doesn't match your Chrome browser.\n\n"
                "Solutions:\n"
                "1. Check your Chrome version (Chrome menu > Help > About Google Chrome)\n"
                "2. Download matching ChromeDriver from: https://chromedriver.chromium.org/\n"
                "3. Replace the existing chromedriver.exe with the new version\n\n"
                "Original error: " + error_message
            )
    
    # Selenium WebDriver errors
    if 'webdriver' in error_lower or isinstance(error_type, WebDriverException):
        return (
            "❌ Browser Automation Error\n\n"
            "There was a problem with the browser automation.\n\n"
            "Solutions:\n"
            "1. Close all Chrome browser windows and try again\n"
            "2. Check that Chrome browser is installed and up to date\n"
            "3. Restart the application\n"
            "4. Check your internet connection\n\n"
            "Original error: " + error_message
        )
    
    # Permission errors
    if 'permission' in error_lower or 'access' in error_lower:
        return (
            "❌ File Access Error\n\n"
            "Cannot access the required file or folder.\n\n"
            "Solutions:\n"
            "1. Close the PDF file if it's open in another application\n"
            "2. Run the application as Administrator\n"
            "3. Check that the file is not read-only\n"
            "4. Ensure you have write permissions to the output folder\n\n"
            "Original error: " + error_message
        )
    
    # Network errors
    if 'network' in error_lower or 'connection' in error_lower or 'timeout' in error_lower:
        return (
            "❌ Network Connection Error\n\n"
            "Cannot connect to the required online services.\n\n"
            "Solutions:\n"
            "1. Check your internet connection\n"
            "2. Try again in a few minutes\n"
            "3. Check if your firewall or antivirus is blocking the application\n"
            "4. Verify that https://www.oemsecrets.com is accessible in your browser\n\n"
            "Original error: " + error_message
        )
    
    # Return the original error if no specific handling is available
    return f"❌ An error occurred:\n\n{error_message}\n\nPlease check the details above and try again."


def open_help_url(url):
    """
    Open a help URL in the default browser.
    
    Args:
        url (str): URL to open
    """
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def validate_extracted_tables(tables):
    """
    Validate that tables were successfully extracted.
    
    Args:
        tables (list): List of extracted tables
    
    Returns:
        tuple: (is_valid, warning_message)
    """
    if not tables or len(tables) == 0:
        return False, (
            "⚠️ No Tables Extracted\n\n"
            "No tables were found in the specified PDF pages.\n\n"
            "Suggestions:\n"
            "1. Verify the page range contains tables\n"
            "2. Check if the PDF has text-based tables (not images)\n"
            "3. Try a different page range\n"
            "4. Consider using OCR for image-based tables"
        )
    
    # Check if tables are empty or contain only headers
    non_empty_tables = []
    for i, table in enumerate(tables):
        if hasattr(table, 'shape') and table.shape[0] > 1:  # More than just header
            non_empty_tables.append(table)
        elif hasattr(table, '__len__') and len(table) > 0:
            non_empty_tables.append(table)
    
    if not non_empty_tables:
        return False, (
            "⚠️ Empty Tables Found\n\n"
            "Tables were detected but appear to be empty or contain only headers.\n\n"
            "Suggestions:\n"
            "1. Check if the correct pages were specified\n"
            "2. Verify the PDF contains actual data tables\n"
            "3. Try adjusting the extraction settings"
        )
    
    if len(non_empty_tables) < len(tables):
        return True, (
            f"⚠️ Partial Success\n\n"
            f"Found {len(tables)} tables, but {len(tables) - len(non_empty_tables)} appear to be empty.\n"
            f"Proceeding with {len(non_empty_tables)} non-empty tables."
        )
    
    return True, None


def generate_output_path(input_file_path, suffix, output_directory=None, extension=".xlsx"):
    """
    Generate output file path based on input file and optional output directory.
    
    Args:
        input_file_path (str): Path to the input file
        suffix (str): Suffix to add to the filename (e.g., "_merged", "_extracted")
        output_directory (str, optional): Directory to save the output file
        extension (str): File extension (default: ".xlsx")
    
    Returns:
        str: Generated output file path
    """
    # Get the base filename without extension
    input_path = Path(input_file_path)
    base_name = input_path.stem
    
    # Generate output filename
    output_filename = f"{base_name}{suffix}{extension}"
    
    # Use output directory if provided, otherwise use input file's directory
    if output_directory and output_directory.strip():
        output_dir = Path(output_directory)
        # Create directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / output_filename
    else:
        # Save in the same directory as the input file
        output_path = input_path.parent / output_filename
    
    return str(output_path)


def validate_output_directory(output_directory):
    """
    Validate output directory exists and is writable.
    
    Args:
        output_directory (str): Path to output directory
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not output_directory or not output_directory.strip():
        return True, None  # Empty is valid (will use input file directory)
    
    try:
        output_dir = Path(output_directory)
        
        # Check if directory exists
        if not output_dir.exists():
            # Try to create it
            output_dir.mkdir(parents=True, exist_ok=True)
            return True, None
        
        # Check if it's actually a directory
        if not output_dir.is_dir():
            return False, f"Path exists but is not a directory: {output_directory}"
        
        # Check if we can write to it by creating a test file
        test_file = output_dir / ".bomination_write_test"
        try:
            test_file.touch()
            test_file.unlink()  # Delete the test file
            return True, None
        except PermissionError:
            return False, f"Permission denied: Cannot write to directory {output_directory}"
            
    except Exception as e:
        return False, f"Error accessing output directory: {str(e)}"