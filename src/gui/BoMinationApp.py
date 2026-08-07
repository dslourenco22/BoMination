import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
try:
    from ttkbootstrap.scrolled import ScrolledFrame
except Exception:
    ScrolledFrame = None
import subprocess
import os
import threading
import sys
import time
import webbrowser
import json
from pathlib import Path
from datetime import datetime
import warnings

# Add the src directory to Python path so we can import modules
src_dir = Path(__file__).parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Enable DPI awareness on Windows for better icon quality
try:
    import ctypes
    from ctypes import wintypes
    
    # Safe print function for executables
    def safe_print(msg):
        try:
            print(msg)
        except UnicodeEncodeError:
            # Replace Unicode with ASCII
            ascii_msg = (msg.replace('✅', '[OK]').replace('❌', '[ERROR]')
                        .replace('⚠️', '[WARNING]').replace('🔧', '[DEBUG]'))
            print(ascii_msg)
    
    # Try to set DPI awareness for Windows 10/11
    try:
        # Windows 10, version 1703 and later
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        safe_print("[OK]DPI awareness enabled (Per-Monitor V2)")
    except (AttributeError, OSError):
        try:
            # Windows 8.1 and later
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            safe_print("[OK] DPI awareness enabled (Per-Monitor)")
        except (AttributeError, OSError):
            try:
                # Windows Vista and later
                ctypes.windll.user32.SetProcessDPIAware()
                safe_print("[OK] DPI awareness enabled (System)")
            except (AttributeError, OSError):
                safe_print("[WARNING] Could not enable DPI awareness")
except ImportError:
    print("[WARNING] DPI awareness not available (not Windows)")

# Import the pipeline modules directly for PyInstaller compatibility
try:
    from pipeline.main_pipeline import run_main_pipeline_direct
except ImportError:
    # Fallback for development mode
    def run_main_pipeline_direct(*args, **kwargs):
        raise ImportError("Pipeline modules not available")

# Import the review window module
try:
    from gui.review_window import show_review_window
except ImportError:
    # Fallback for development mode
    def show_review_window(*args, **kwargs):
        raise ImportError("Review window module not available")

# Import the settings tab module
try:
    from gui.settings_tab import SettingsTab
except ImportError:
    # Fallback for development mode
    class SettingsTab:
        def __init__(self, *args, **kwargs):
            raise ImportError("Settings tab module not available")

# Suppress known Tkinter destructor warnings in Python 3.12
warnings.filterwarnings("ignore", category=DeprecationWarning, module="tkinter")

# Monkey patch to fix Tkinter Image destructor issue in Python 3.12
try:
    import tkinter
    original_image_del = tkinter.Image.__del__
    
    def safe_image_del(self):
        try:
            original_image_del(self)
        except (TypeError, Exception):
            pass  # Ignore destructor errors
    
    tkinter.Image.__del__ = safe_image_del
except (AttributeError, ImportError):
    pass  # Skip if not available
from pipeline.validation_utils import (
    validate_page_range, 
    validate_pdf_file, 
    check_java_installation, 
    check_chromedriver_availability,
    handle_common_errors,
    open_help_url,
    validate_output_directory
)

# Import OCR functionality
from pipeline.ocr_preprocessor import (
    check_ocrmypdf_installation,
    check_tesseract_installation,
    get_ocr_installation_instructions
)

# Default path to cost sheet template
# Support both script and PyInstaller .exe paths
if getattr(sys, 'frozen', False):
    # Running as PyInstaller executable
    SCRIPT_DIR = Path(sys._MEIPASS) / "src"
    COST_SHEET_TEMPLATE = Path(sys._MEIPASS) / "Files" / "OCTF-1539-COST SHEET.xlsx"
else:
     # Running as script - go up two levels from src/gui/ to root, then to Files/
    SCRIPT_DIR = Path(__file__).parent.parent.parent  # Go from src/gui to root
    COST_SHEET_TEMPLATE = SCRIPT_DIR / "Files" / "OCTF-1539-COST SHEET.xlsx"

# Adding debug logging to trace imports
import logging
logging.basicConfig(level=logging.DEBUG)

# Suppress verbose third-party library logging
logging.getLogger('selenium').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('fontTools').setLevel(logging.WARNING)

try:
    import numpy
    logging.debug("NumPy imported successfully.")
    import PIL
    logging.debug("PIL imported successfully.")
    from ttkbootstrap import Style
    logging.debug("ttkbootstrap imported successfully.")
except Exception as e:
    logging.error(f"Error during imports: {e}")

class CopyableErrorDialog:
    """Custom dialog that allows copying error messages with modern styling."""
    
    def __init__(self, parent, title, message, technical_details=None):
        self.result = None
        
        # Create the dialog window
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("700x500")
        self.dialog.resizable(True, True)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (700 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (500 // 2)
        self.dialog.geometry(f"700x500+{x}+{y}")
        
        # Main frame with padding
        main_frame = ttk.Frame(self.dialog)
        
        
        # Title with icon
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=X, pady=(0, 15))
        
        ttk.Label(
            title_frame, 
            text=f"{title}",
            font=("Segoe UI", 16, "bold"),
            bootstyle="danger"
        ).pack(anchor=W)
        
        # Error message section
        msg_frame = ttk.LabelFrame(main_frame, text="Error Message", padding=10)
        msg_frame.pack(fill=BOTH, expand=True, pady=(0, 10))
        
        # Scrollable text widget for the message
        msg_scroll_frame = ttk.Frame(msg_frame)
        msg_scroll_frame.pack(fill=BOTH, expand=True)
        
        msg_text = tk.Text(
            msg_scroll_frame, 
            wrap=tk.WORD, 
            height=8, 
            font=("Segoe UI", 10),
            relief="flat",
            borderwidth=0
        )
        msg_scrollbar = ttk.Scrollbar(msg_scroll_frame, orient=VERTICAL, command=msg_text.yview)
        msg_text.configure(yscrollcommand=msg_scrollbar.set)
        
        msg_text.pack(side=LEFT, fill=BOTH, expand=True)
        msg_scrollbar.pack(side=RIGHT, fill=Y)
        
        msg_text.insert(tk.END, message)
        msg_text.config(state=tk.DISABLED)
        
        # Technical details (if provided)
        if technical_details:
            tech_frame = ttk.LabelFrame(main_frame, text="Technical Details", padding=10)
            tech_frame.pack(fill=BOTH, expand=True, pady=(0, 15))
            
            tech_scroll_frame = ttk.Frame(tech_frame)
            tech_scroll_frame.pack(fill=BOTH, expand=True)
            
            tech_text = tk.Text(
                tech_scroll_frame, 
                wrap=tk.WORD, 
                height=6, 
                font=("Consolas", 9),
                relief="flat",
                borderwidth=0
            )
            tech_scrollbar = ttk.Scrollbar(tech_scroll_frame, orient=VERTICAL, command=tech_text.yview)
            tech_text.configure(yscrollcommand=tech_scrollbar.set)
            
            tech_text.pack(side=LEFT, fill=BOTH, expand=True)
            tech_scrollbar.pack(side=RIGHT, fill=Y)
            
            tech_text.insert(tk.END, technical_details)
            tech_text.config(state=tk.DISABLED)
            
            # Store references for copying
            self.msg_text = msg_text
            self.tech_text = tech_text
        else:
            self.msg_text = msg_text
            self.tech_text = None
        
        # Button frame with modern styling
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=X)
        
        # Left side buttons
        left_buttons = ttk.Frame(button_frame)
        left_buttons.pack(side=LEFT)
        
        ttk.Button(
            left_buttons, 
            text="Copy Error Message", 
            command=self.copy_message,
            bootstyle="primary-outline",
            width=20
        ).pack(side=LEFT, padx=(0, 10))
        
        if technical_details:
            ttk.Button(
                left_buttons, 
                text="Copy Technical Details", 
                command=self.copy_technical,
                bootstyle="secondary-outline",
                width=22
            ).pack(side=LEFT, padx=(0, 10))
            
            ttk.Button(
                left_buttons, 
                text="Copy All", 
                command=self.copy_all,
                bootstyle="info-outline",
                width=12
            ).pack(side=LEFT, padx=(0, 10))
        
        # Close button on the right
        ttk.Button(
            button_frame, 
            text="Close", 
            command=self.close,
            bootstyle="secondary",
            width=12
        ).pack(side=RIGHT)
        
        # Bind escape key to close
        self.dialog.bind('<Escape>', lambda e: self.close())
        
        # Focus on the dialog
        self.dialog.focus_set()
        
    def copy_message(self):
        """Copy the error message to clipboard."""
        self.msg_text.config(state=tk.NORMAL)
        message = self.msg_text.get(1.0, tk.END).strip()
        self.msg_text.config(state=tk.DISABLED)
        
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(message)
        self.dialog.update()
        
        # Show brief confirmation
        self.show_copy_confirmation("Error message copied to clipboard!")
        
    def copy_technical(self):
        """Copy technical details to clipboard."""
        if self.tech_text:
            self.tech_text.config(state=tk.NORMAL)
            technical = self.tech_text.get(1.0, tk.END).strip()
            self.tech_text.config(state=tk.DISABLED)
            
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(technical)
            self.dialog.update()
            
            self.show_copy_confirmation("Technical details copied to clipboard!")
    
    def copy_all(self):
        """Copy both error message and technical details."""
        self.msg_text.config(state=tk.NORMAL)
        message = self.msg_text.get(1.0, tk.END).strip()
        self.msg_text.config(state=tk.DISABLED)
        
        full_text = f"ERROR MESSAGE:\n{message}\n"
        
        if self.tech_text:
            self.tech_text.config(state=tk.NORMAL)
            technical = self.tech_text.get(1.0, tk.END).strip()
            self.tech_text.config(state=tk.DISABLED)
            full_text += f"\nTECHNICAL DETAILS:\n{technical}"
        
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(full_text)
        self.dialog.update()
        
        self.show_copy_confirmation("All error information copied to clipboard!")
    
    def show_copy_confirmation(self, message):
        """Show a brief confirmation message with modern styling."""
        # Create a temporary label that fades out
        temp_frame = ttk.Frame(self.dialog, relief="solid", borderwidth=1)
        temp_frame.place(relx=0.5, rely=0.95, anchor=tk.CENTER)
        
        temp_label = ttk.Label(
            temp_frame, 
            text=f"{message}", 
            bootstyle="success",
            font=("Segoe UI", 10)
        )
        temp_label.pack(padx=15, pady=8)
        
        # Remove the label after 3 seconds
        self.dialog.after(3000, lambda: temp_frame.destroy())
    
    def close(self):
        """Close the dialog."""
        self.dialog.destroy()
    
    def show(self):
        """Show the dialog and wait for it to close."""
        self.dialog.wait_window()


class BoMApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BoMination - BoM Processing Pipeline")
        self.root.geometry("700x600")  # Reduced height since log panel removed
        self.root.resizable(True, True)

        self.pdf_path = tk.StringVar()
        self.page_range = tk.StringVar()
        self.company_name = tk.StringVar(value="")  # default to blank
        self.output_directory = tk.StringVar()  # Output directory selection
        self.tabula_mode = tk.StringVar(value="balanced")  # Default to balanced mode

        # Add ROI selection variable
        self.use_roi = tk.BooleanVar(value=False)  # Default to automatic mode

        # Live price lookup toggle (ON = web search + AI estimate; OFF = blank prices)
        self.enable_prices = tk.BooleanVar(value=True)

        # Purchasing discount % taken off every looked-up price (0 = none)
        self.discount_pct = tk.StringVar(value="0")

        # Cost sheet output: custom file name and destination folder
        self.cost_sheet_name = tk.StringVar()  # e.g. "Main Panel Cost Sheet.xlsx"

        # Batch processing: list of selected PDFs (one cost sheet each)
        self.selected_pdfs = []

        # Auto-detect BOM pages (skip manual page range entry)
        self.auto_detect_pages = tk.BooleanVar(value=True)

        # Progress components
        self.progress_var = tk.StringVar(value="Ready to process your BoM files")
        self.progress_bar = None
        
        self.build_gui()

    def build_gui(self):
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=BOTH, expand=True, padx=10, pady=10)
        
        # Main tab
        main_tab = ttk.Frame(notebook)
        notebook.add(main_tab, text="Main")
        
        # Settings tab
        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="Settings")
        
        # Build main tab content
        self.build_main_tab(main_tab)
        
        # Build settings tab content
        self.settings_tab_instance = SettingsTab(settings_tab, self)

    def _build_brand_header(self, parent):
        """OMNI-branded header: logo + product title + subtitle + accent rule."""
        header = ttk.Frame(parent)
        header.pack(fill=X, pady=(0, 12))

        # Locate the logo (works both in dev and inside the frozen .exe)
        candidates = []
        if getattr(sys, 'frozen', False):
            candidates += [Path(sys._MEIPASS) / "logo.jpeg",
                           Path(sys._MEIPASS) / "assets" / "logo.jpeg"]
        root_dir = Path(__file__).parent.parent.parent
        candidates += [root_dir / "logo.jpeg", root_dir / "assets" / "logo.jpeg"]

        logo_path = next((c for c in candidates if c.exists()), None)
        if logo_path is not None:
            try:
                from PIL import Image, ImageTk
                img = Image.open(str(logo_path))
                target_h = 50
                w, h = img.size
                img = img.resize((int(w * target_h / h), target_h), Image.Resampling.LANCZOS)
                self._brand_logo_img = ImageTk.PhotoImage(img)   # keep a ref alive
                ttk.Label(header, image=self._brand_logo_img).pack(side=LEFT, padx=(0, 16))
            except Exception as e:
                print(f"[BRAND] Could not load logo: {e}")

        titles = ttk.Frame(header)
        titles.pack(side=LEFT, anchor=W)
        ttk.Label(
            titles, text="BoMination",
            font=("Segoe UI Semibold", 22, "bold")
        ).pack(anchor=W)
        ttk.Label(
            titles,
            text="Bill of Materials extraction · OMNI Control Technology",
            font=("Segoe UI", 10), bootstyle="secondary"
        ).pack(anchor=W)

        # Brand accent rule under the header
        ttk.Separator(parent, bootstyle="info").pack(fill=X, pady=(0, 18))

    def build_main_tab(self, main_container):
        """Build the main tab interface."""
        # Use a scrollable container so every step AND the Run button stay
        # reachable even when the window is short (otherwise the added Pricing/
        # Output panels push the Run button off the bottom with no way to scroll).
        if ScrolledFrame is not None:
            main_container_padded = ScrolledFrame(main_container, autohide=True, padding=20)
            main_container_padded.pack(fill=BOTH, expand=True)
        else:
            main_container_padded = ttk.Frame(main_container)
            main_container_padded.pack(fill=BOTH, expand=True, padx=20, pady=20)
        
        # Branded header: OMNI logo + product title + subtitle, with an accent rule
        self._build_brand_header(main_container_padded)

        # Step 1: PDF File Selection (one or many)
        pdf_frame = ttk.LabelFrame(main_container_padded, text="Step 1: Select BoM PDF File(s)", padding=15)
        pdf_frame.pack(fill=X, pady=(0, 15))

        pdf_entry_frame = ttk.Frame(pdf_frame)
        pdf_entry_frame.pack(fill=X, pady=5)

        ttk.Entry(
            pdf_entry_frame,
            textvariable=self.pdf_path,
            font=("Segoe UI", 10),
            width=50
        ).pack(side=LEFT, fill=X, expand=True, padx=(0, 10))

        ttk.Button(
            pdf_entry_frame,
            text="Browse",
            command=self.browse_pdf,
            bootstyle="outline-primary",
            width=10
        ).pack(side=RIGHT)

        ttk.Label(
            pdf_frame,
            text="Select multiple PDFs to batch-process — each produces its own cost sheet.",
            font=("Segoe UI", 9),
            bootstyle="secondary"
        ).pack(anchor=W, pady=(5, 0))

        # Step 2: Page Range (optional when auto-detect is on)
        page_frame = ttk.LabelFrame(main_container_padded, text="Step 2: BOM Pages", padding=15)
        page_frame.pack(fill=X, pady=(0, 15))

        # Auto-detect toggle
        ttk.Checkbutton(
            page_frame,
            text="Auto-detect BOM pages",
            variable=self.auto_detect_pages,
            bootstyle="success-round-toggle",
            command=self.on_auto_pages_toggle
        ).pack(anchor=W, pady=(0, 8))

        page_entry_frame = ttk.Frame(page_frame)
        page_entry_frame.pack(fill=X, pady=5)

        self.page_entry = ttk.Entry(
            page_entry_frame,
            textvariable=self.page_range,
            font=("Segoe UI", 10),
            width=20
        )
        self.page_entry.pack(side=LEFT, padx=(0, 10))

        # Help button with modern styling
        ttk.Button(
            page_entry_frame,
            text="Help",
            command=self.show_page_range_help,
            bootstyle="outline-info",
            width=8
        ).pack(side=RIGHT)

        # Examples label with better styling
        examples_label = ttk.Label(
            page_frame,
            text="Examples: 1-3 (pages 1 to 3), 5 (page 5), 2,4,6 (pages 2, 4, and 6)",
            font=("Segoe UI", 9),
            bootstyle="secondary"
        )
        examples_label.pack(anchor=W, pady=(5, 0))

        # Reflect the initial auto-detect state on the entry
        if self.auto_detect_pages.get():
            self.page_entry.configure(state="disabled")

        # Step 3: Company Selection
        company_frame = ttk.LabelFrame(main_container_padded, text="Step 3: Select Company (Optional)", padding=15)
        company_frame.pack(fill=X, pady=(0, 15))
        
        company_dropdown = ttk.Combobox(
            company_frame,
            textvariable=self.company_name,
            values=["", "Farrell", "NEL", "Primetals", "Riley Power", "Shanklin", "901D", "Amazon", "EOS"],
            state="readonly",
            font=("Segoe UI", 10),
            width=30
        )
        company_dropdown.pack(anchor=W, pady=5)
        company_dropdown.current(0)  # default to blank
        
        # Info label for company
        company_info_label = ttk.Label(
            company_frame,
            text="Select if your PDF requires company-specific formatting",
            font=("Segoe UI", 9),
            bootstyle="secondary"
        )
        company_info_label.pack(anchor=W, pady=(5, 0))

        # Step 4: Price lookup toggle
        price_frame = ttk.LabelFrame(main_container_padded, text="Step 4: Pricing", padding=15)
        price_frame.pack(fill=X, pady=(0, 15))

        price_toggle = ttk.Checkbutton(
            price_frame,
            text="Enable Live Price Lookup",
            variable=self.enable_prices,
            bootstyle="success-round-toggle",
            command=self.on_price_toggle
        )
        price_toggle.pack(anchor=W, pady=5)

        self.price_info_label = ttk.Label(
            price_frame,
            text="ON: searches the web and estimates prices.  OFF: skips all web "
                 "requests and leaves cost columns blank (faster, fully offline).",
            font=("Segoe UI", 9),
            bootstyle="secondary",
            wraplength=560,
            justify="left"
        )
        self.price_info_label.pack(anchor=W, pady=(5, 0))

        # Purchasing discount — subtracted from every looked-up price
        discount_row = ttk.Frame(price_frame)
        discount_row.pack(fill=X, pady=(10, 0))
        ttk.Label(discount_row, text="Purchasing discount:", font=("Segoe UI", 10)).pack(side=LEFT)
        ttk.Entry(
            discount_row, textvariable=self.discount_pct, width=6, font=("Segoe UI", 10)
        ).pack(side=LEFT, padx=(8, 4))
        ttk.Label(
            discount_row, text="%   (taken off each price before the cost sheet)",
            font=("Segoe UI", 9), bootstyle="secondary"
        ).pack(side=LEFT)

        # Step 5: Output (cost sheet file name + destination folder)
        output_frame = ttk.LabelFrame(main_container_padded, text="Step 5: Output Cost Sheet", padding=15)
        output_frame.pack(fill=X, pady=(0, 15))

        # File name row
        name_row = ttk.Frame(output_frame)
        name_row.pack(fill=X, pady=5)
        ttk.Label(name_row, text="File name:", font=("Segoe UI", 10), width=12).pack(side=LEFT)
        ttk.Entry(
            name_row,
            textvariable=self.cost_sheet_name,
            font=("Segoe UI", 10)
        ).pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        ttk.Label(name_row, text=".xlsx", font=("Segoe UI", 10), bootstyle="secondary").pack(side=LEFT)

        # Destination folder row (reuses self.output_directory)
        dir_row = ttk.Frame(output_frame)
        dir_row.pack(fill=X, pady=5)
        ttk.Label(dir_row, text="Save to:", font=("Segoe UI", 10), width=12).pack(side=LEFT)
        ttk.Entry(
            dir_row,
            textvariable=self.output_directory,
            font=("Segoe UI", 10)
        ).pack(side=LEFT, fill=X, expand=True, padx=(0, 10))
        ttk.Button(
            dir_row,
            text="Browse",
            command=self.browse_output_dir,
            bootstyle="outline-primary",
            width=10
        ).pack(side=RIGHT)

        ttk.Label(
            output_frame,
            text="Only the cost sheet is saved. Leave blank to use the PDF's name and folder.",
            font=("Segoe UI", 9),
            bootstyle="secondary"
        ).pack(anchor=W, pady=(5, 0))

        # Action buttons frame
        button_frame = ttk.Frame(main_container_padded)
        button_frame.pack(fill=X, pady=20)
        
        # Run Button with modern styling
        run_button = ttk.Button(
            button_frame, 
            text="Run Automation", 
            command=self.run_pipeline,
            bootstyle="success",
            width=20
        )
        run_button.pack(side=LEFT, padx=(0, 10))
        
        # Status/Progress area with modern card styling
        status_frame = ttk.Frame(main_container_padded)
        status_frame.pack(fill=X, pady=(20, 0))
        
        # Progress card
        progress_card = ttk.LabelFrame(status_frame, text="Status & Progress", padding=15)
        progress_card.pack(fill=X, pady=(0, 10))
        
        # Status text
        self.status_label = ttk.Label(
            progress_card,
            textvariable=self.progress_var,
            font=("Segoe UI", 10),
            bootstyle="info"
        )
        self.status_label.pack(anchor=W, pady=(0, 10))
        
        # Progress bar (initially hidden)
        self.progress_bar = ttk.Progressbar(
            progress_card,
            mode="indeterminate",
            bootstyle="primary",
            length=400
        )
        self.progress_bar.pack(fill=X, pady=(0, 5))
        
        # Add initial status message
        self.add_log_message("Welcome to BoMination! Select a PDF file and configure settings to begin.", "info")

    def start_progress(self, message="Processing..."):
        """Start the progress bar with indeterminate mode."""
        def _start():
            self.progress_var.set(f"🔄 {message}")
            self.progress_bar.start(10)  # Update every 10ms for smooth animation
        
        # Ensure GUI update happens on main thread with error handling
        try:
            self.root.after(0, _start)
        except RuntimeError as e:
            # If main thread is not in main loop, print to console instead
            print(f"[GUI UPDATE] start_progress: {message} (GUI update failed: {e})")
            # Try direct update as fallback
            try:
                _start()
            except:
                pass
    
    def stop_progress(self, message="Ready"):
        """Stop the progress bar and update status."""
        def _stop():
            self.progress_bar.stop()
            self.progress_var.set(f"{message}")
        
        # Ensure GUI update happens on main thread with error handling
        try:
            self.root.after(0, _stop)
        except RuntimeError as e:
            # If main thread is not in main loop, print to console instead
            print(f"[GUI UPDATE] stop_progress: {message} (GUI update failed: {e})")
            # Try direct update as fallback
            try:
                _stop()
            except:
                pass
    
    def complete_progress(self):
        """Complete the progress and reset to ready state."""
        def _complete():
            self.progress_bar.stop()
            self.progress_var.set("[OK] Ready for next operation")
        
        # Ensure GUI update happens on main thread with error handling
        try:
            self.root.after(0, _complete)
        except RuntimeError as e:
            # If main thread is not in main loop, print to console instead
            print(f"[GUI UPDATE] complete_progress (GUI update failed: {e})")
            # Try direct update as fallback
            try:
                _complete()
            except:
                pass
    
    def update_status(self, message):
        """Update the status message without affecting progress bar."""
        def _update():
            self.progress_var.set(message)
        
        # Ensure GUI update happens on main thread with error handling
        try:
            self.root.after(0, _update)
        except RuntimeError as e:
            # If main thread is not in main loop, print to console instead
            print(f"[GUI UPDATE] update_status: {message} (GUI update failed: {e})")
            # Try direct update as fallback
            try:
                _update()
            except:
                pass
    
    def add_log_message(self, message, level="info"):
        """Print a timestamped message to console (log panel removed)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Color coding based on level
        level_icons = {
            "info": "[INFO]",
            "success": "[OK]", 
            "warning": "[WARNING]",
            "error": "[ERROR]",
            "step": "[STEP]"
        }
        
        icon = level_icons.get(level, "•")
        formatted_message = f"[{timestamp}] {icon} {message}"
        
        # Print to console instead of GUI log
        print(formatted_message)

    def show_page_range_help(self):
        """Show detailed help for page range format."""
        help_text = """
📖 Page Range Format Help

Valid formats:
• Single page: 5
• Page range: 1-3 (pages 1, 2, and 3)
• Multiple pages: 2,4,6 (pages 2, 4, and 6)
• Mixed format: 1-3,5,7-9 (pages 1, 2, 3, 5, 7, 8, and 9)

Rules:
• Use only numbers, commas, and hyphens
• Page numbers must be positive integers
• In ranges, start page must be ≤ end page
• Spaces are allowed around commas and hyphens

Examples:
• "1" → Extract page 1 only
• "1-5" → Extract pages 1 through 5
• "2,4,7" → Extract pages 2, 4, and 7
• "1-3, 6, 8-10" → Extract pages 1, 2, 3, 6, 8, 9, and 10

Invalid formats:
• Empty or blank
• Letters: "a-b" 
• Negative numbers: "-1"
• Invalid ranges: "5-3"
        """
        messagebox.showinfo("Page Range Help", help_text.strip())

    def browse_pdf(self):
        paths = filedialog.askopenfilenames(filetypes=[("PDF Files", "*.pdf")])
        if paths:
            self.selected_pdfs = list(paths)
            if len(paths) == 1:
                self.pdf_path.set(paths[0])
                # Pre-fill a sensible default cost-sheet name from the PDF name
                if not self.cost_sheet_name.get().strip():
                    self.cost_sheet_name.set(f"{Path(paths[0]).stem}_cost_sheet")
            else:
                self.pdf_path.set(f"{len(paths)} PDFs selected")
            self.add_log_message(f"Selected {len(paths)} PDF(s)", "info")

    def on_auto_pages_toggle(self):
        """Enable/disable the manual page-range entry based on the auto toggle."""
        if self.auto_detect_pages.get():
            self.page_entry.configure(state="disabled")
            self.add_log_message("Auto-detect BOM pages enabled", "info")
        else:
            self.page_entry.configure(state="normal")
            self.add_log_message("Manual page range enabled", "info")

    def browse_output_dir(self):
        """Choose the folder where the cost sheet will be saved."""
        directory = filedialog.askdirectory()
        if directory:
            self.output_directory.set(directory)
            self.add_log_message(f"Output folder: {directory}", "info")

    def on_price_toggle(self):
        """Update the helper text and log when the price lookup toggle changes."""
        if self.enable_prices.get():
            self.add_log_message("Live price lookup enabled", "info")
            self.price_info_label.configure(
                text="ON: searches the web and estimates prices.  OFF: skips all web "
                     "requests and leaves cost columns blank (faster, fully offline)."
            )
        else:
            self.add_log_message("Live price lookup disabled - cost columns will be blank", "info")
            self.price_info_label.configure(
                text="OFF: web requests skipped. Cost columns will be left blank in the "
                     "merged file and cost sheet."
            )

    def run_pipeline(self):
        """Run the pipeline with comprehensive input validation."""
        pdf = self.pdf_path.get()
        pages = self.page_range.get()
        company = self.company_name.get()
        output_dir = self.output_directory.get()
        auto_pages = self.auto_detect_pages.get()

        # Build the list of PDFs to process (batch-aware). Fall back to a single
        # path typed into the entry if Browse wasn't used.
        pdfs = self.selected_pdfs if self.selected_pdfs else ([pdf] if pdf.strip() else [])
        if not pdfs:
            Messagebox.show_error("No PDF Selected", "Please select at least one PDF file.", parent=self.root)
            return

        # Step 1: Validate every PDF file
        for p in pdfs:
            pdf_valid, pdf_error = validate_pdf_file(p)
            if not pdf_valid:
                Messagebox.show_error("Invalid PDF File", f"{Path(p).name}: {pdf_error}", parent=self.root)
                return

        # Step 2: Validate page range (only when not auto-detecting)
        if not auto_pages:
            pages_valid, pages_error, parsed_ranges = validate_page_range(pages)
            if not pages_valid:
                Messagebox.show_error("Invalid Page Range", pages_error, parent=self.root)
                return

        # Step 3: Validate output directory
        output_valid, output_error = validate_output_directory(output_dir)
        if not output_valid:
            Messagebox.show_error("Invalid Output Directory", output_error, parent=self.root)
            return

        # Step 4: Check system requirements (silent mode for pipeline)
        self.check_system_requirements(silent=True)

        # Add template validation logging
        if COST_SHEET_TEMPLATE.exists():
            self.add_log_message(f"Cost sheet template found: {COST_SHEET_TEMPLATE.name}", "success")
        else:
            self.add_log_message(f"Cost sheet template not found: {COST_SHEET_TEMPLATE}", "warning")

        # Step 5: Handle ROI selection BEFORE starting background thread
        # ROI is single-file + manual-pages only; skip it for batch / auto-detect.
        roi_areas = None
        if self.use_roi.get() and len(pdfs) == 1 and not auto_pages:
            self.add_log_message("ROI mode enabled - showing table area selection", "step")
            self.add_log_message(f"🐛 DEBUG: About to call show_roi_picker with PDF: {pdf}, pages: {pages}", "info")
            self.update_status("⏳ Waiting for user to select table areas...")
            
            try:
                # Import and show ROI picker on main thread
                from gui.roi_picker import show_roi_picker
                self.add_log_message("[DEBUG] ROI picker imported successfully", "info")
                
                self.add_log_message("🐛 DEBUG: Calling show_roi_picker now...", "info")
                roi_areas = show_roi_picker(pdf, pages, parent_window=self.root)
                self.add_log_message("🐛 DEBUG: show_roi_picker call completed", "info")
                
                self.add_log_message(f"🐛 DEBUG: ROI picker returned: {roi_areas}", "info")
                self.add_log_message(f"🐛 DEBUG: ROI picker returned type: {type(roi_areas)}", "info")
                
                if roi_areas:
                    self.add_log_message(f"ROI selection completed - selected {len(roi_areas)} table areas", "success")
                    self.add_log_message(f"🐛 DEBUG: ROI areas data: {roi_areas}", "info")
                    # Store ROI areas in environment for background thread
                    import json
                    roi_json = json.dumps(roi_areas)
                    os.environ["BOM_ROI_AREAS"] = roi_json
                    self.add_log_message(f"🐛 DEBUG: Stored ROI areas in environment: {roi_json}", "info")
                else:
                    self.add_log_message("🐛 DEBUG: ROI picker returned None or empty result", "warning")
                    self.add_log_message("ROI selection cancelled", "warning")
                    Messagebox.show_info("ROI Selection Cancelled", "ROI selection was cancelled. Please try again.", parent=self.root)
                    return
                    
            except Exception as e:
                self.add_log_message(f"🐛 DEBUG: Exception in ROI selection: {e}", "error")
                self.add_log_message(f"ROI selection error: {e}", "error")
                Messagebox.show_error("ROI Selection Error", f"Failed to show ROI selector: {e}", parent=self.root)
                return

        # If all validations pass, proceed with pipeline
        self.add_log_message("🐛 DEBUG: Setting environment variables for pipeline", "info")
        os.environ["BOM_PDF_PATH"] = pdf
        os.environ["BOM_PAGE_RANGE"] = pages
        os.environ["BOM_COMPANY"] = company
        os.environ["BOM_OUTPUT_DIRECTORY"] = self.output_directory.get() or ""
        os.environ["BOM_USE_ROI"] = str(self.use_roi.get()).lower()
        os.environ["BOM_DISCOUNT_PCT"] = (self.discount_pct.get().strip() or "0")

        self.add_log_message(f"[DEBUG] Environment variables set:", "info")
        self.add_log_message(f"[DEBUG] BOM_PDF_PATH: {os.environ.get('BOM_PDF_PATH')}", "info")
        self.add_log_message(f"[DEBUG] BOM_PAGE_RANGE: {os.environ.get('BOM_PAGE_RANGE')}", "info")
        self.add_log_message(f"[DEBUG] BOM_COMPANY: {os.environ.get('BOM_COMPANY')}", "info")
        self.add_log_message(f"[DEBUG] BOM_USE_ROI: {os.environ.get('BOM_USE_ROI')}", "info")
        self.add_log_message(f"[DEBUG] BOM_ROI_AREAS: {os.environ.get('BOM_ROI_AREAS', 'NOT SET')}", "info")

        # Log the start of pipeline
        self.add_log_message("Starting BoM processing pipeline...", "step")
        self.add_log_message(f"Files: {len(pdfs)}", "info")
        self.add_log_message(f"Pages: {'auto-detect' if auto_pages else pages}", "info")
        self.add_log_message(f"Table detection mode: {self.tabula_mode.get()}", "info")
        if company:
            self.add_log_message(f"Company: {company}", "info")
        if output_dir:
            self.add_log_message(f"Output directory: {output_dir}", "info")

        def background_task():
            try:
                self.start_progress("Initializing LLM extraction pipeline...")

                # Detailed error log lives next to the first PDF
                error_log_path = Path(pdfs[0]).parent / "bomination_error_log.txt"

                def log_to_file(message):
                    """Log message to both console and file for debugging."""
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_entry = f"[{timestamp}] {message}"
                    try:
                        with open(error_log_path, "a", encoding="utf-8") as f:
                            f.write(log_entry + "\n")
                    except:
                        pass
                    print(log_entry)

                total = len(pdfs)
                log_to_file("=== BoMination LLM Pipeline Started ===")
                log_to_file(f"Files: {total} | Auto-detect pages: {auto_pages} | Company: {company}")

                # Import pipeline pieces once
                try:
                    from pipeline.main_pipeline import run_extract_bom_with_llm
                    from pipeline.map_cost_sheet import main as map_main
                    from pipeline.extract_main import detect_bom_pages
                    from pipeline.lookup_price import main as lookup_main, _build_empty_output
                    import pandas as pd
                    log_to_file("Pipeline modules imported successfully")
                except Exception as import_error:
                    error_msg = f"Failed to import pipeline modules: {import_error}"
                    log_to_file(f"CRITICAL: {error_msg}")
                    self.add_log_message(error_msg, "error")
                    raise Exception(f"Import Error: {error_msg}")

                saved_sheets = []   # (source_pdf_name, saved_path)
                failures = []       # (source_pdf_name, error_str)

                for idx, current_pdf in enumerate(pdfs, start=1):
                    pdf_name = Path(current_pdf).name
                    label = f"[{idx}/{total}] {pdf_name}"
                    self.add_log_message(f"Processing {label}", "step")
                    log_to_file(f"--- {label} ---")
                    try:
                        # Resolve the page range for this file (auto or manual)
                        if auto_pages:
                            self.start_progress(f"{label}: detecting BOM pages...")
                            rng, _detected = detect_bom_pages(current_pdf)
                            rng = rng or "all"
                            log_to_file(f"Auto-detected pages: {rng}")
                            self.add_log_message(f"Auto-detected pages: {rng}", "info")
                        else:
                            rng = pages

                        # Step 1: LLM extraction
                        self.start_progress(f"{label}: extracting tables (LLM)...")
                        merged_path = run_extract_bom_with_llm(
                            pdf_path=current_pdf, pages=rng, company=company
                        )
                        log_to_file(f"Extraction completed: {merged_path}")

                        # Step 2: Price lookup (gated by toggle)
                        _mp = Path(str(merged_path))
                        _base = _mp.stem.replace('_merged', '')
                        prices_path = _mp.parent / f'{_base}_merged_with_prices.xlsx'

                        if self.enable_prices.get():
                            self.start_progress(f"{label}: looking up prices...")
                            try:
                                os.environ["BOM_EXCEL_PATH"] = str(merged_path)
                                lookup_main()
                            except Exception as lookup_error:
                                log_to_file(f"Price lookup failed: {lookup_error}")
                            if not prices_path.exists():
                                prices_path = _mp
                        else:
                            self.start_progress(f"{label}: skipping prices...")
                            try:
                                df_merged = pd.read_excel(str(merged_path), keep_default_na=False, na_values=[''])
                                _build_empty_output(df_merged).to_excel(str(prices_path), index=False)
                            except Exception as blank_error:
                                log_to_file(f"Blank-price generation failed: {blank_error}")
                                if not prices_path.exists():
                                    prices_path = _mp

                        # Step 3: Cost sheet
                        self.start_progress(f"{label}: building cost sheet...")
                        os.environ["OEM_INPUT_PATH"] = str(prices_path)
                        os.environ["MERGED_BOM_PATH"] = str(merged_path)
                        os.environ["BOM_COMPANY"] = str(company)
                        os.environ["BOM_COST_SHEET_DIR"] = (output_dir or "").strip()
                        # Honour a custom name only for a single file; batch uses per-file defaults
                        if total == 1:
                            _name = self.cost_sheet_name.get().strip()
                            if _name and not _name.lower().endswith(".xlsx"):
                                _name += ".xlsx"
                            os.environ["BOM_COST_SHEET_NAME"] = _name
                        else:
                            os.environ["BOM_COST_SHEET_NAME"] = ""
                        cost_sheet_saved = map_main()
                        log_to_file(f"Cost sheet saved: {cost_sheet_saved}")

                        # Clean up this file's intermediates — only the cost sheet is kept
                        pdf_dir = Path(current_pdf).parent
                        stem = Path(current_pdf).stem
                        intermediates = {
                            pdf_dir / f"{stem}_extracted.xlsx",
                            pdf_dir / f"{stem}_merged.xlsx",
                            Path(str(merged_path)),
                            Path(str(prices_path)),
                        }
                        saved_resolved = Path(cost_sheet_saved).resolve() if cost_sheet_saved else None
                        for f in intermediates:
                            try:
                                if f.exists() and (saved_resolved is None or f.resolve() != saved_resolved):
                                    f.unlink()
                            except Exception as del_err:
                                log_to_file(f"Could not remove intermediate {f}: {del_err}")

                        if cost_sheet_saved and Path(cost_sheet_saved).exists():
                            saved_sheets.append((pdf_name, cost_sheet_saved))
                            self.add_log_message(f"{label}: cost sheet ready", "success")
                        else:
                            failures.append((pdf_name, "cost sheet not produced"))
                            self.add_log_message(f"{label}: cost sheet not produced", "warning")

                    except Exception as file_error:
                        log_to_file(f"{label} FAILED: {file_error}")
                        self.add_log_message(f"{label} failed: {file_error}", "error")
                        failures.append((pdf_name, str(file_error)))

                log_to_file("=== Batch Completed ===")
                self.stop_progress("Done")
                self.complete_progress()

                # Build a summary dialog
                n_ok = len(saved_sheets)
                created = "\n".join(f"• {Path(p).name}" for _, p in saved_sheets)
                failed = "\n".join(f"• {name}: {err}" for name, err in failures)
                where = Path(saved_sheets[0][1]).parent if saved_sheets else (output_dir or Path(pdfs[0]).parent)
                if n_ok and not failures:
                    success_message = (
                        f"{n_ok} cost sheet{'s' if n_ok != 1 else ''} created successfully!\n\n"
                        f"{created}\n\nLocation: {where}\n\nDetailed log: {error_log_path}"
                    )
                elif n_ok and failures:
                    success_message = (
                        f"Finished with issues — {n_ok}/{total} succeeded.\n\n"
                        f"Created:\n{created}\n\nFailed:\n{failed}\n\n"
                        f"Location: {where}\n\nDetailed log: {error_log_path}"
                    )
                else:
                    success_message = (
                        "No cost sheets were produced.\n\n"
                        f"Failed:\n{failed}\n\nDetailed log: {error_log_path}"
                    )

                def show_success():
                    try:
                        Messagebox.show_info("Done", success_message, parent=self.root)
                    except Exception as gui_error:
                        print(f"Could not show success dialog: {gui_error}")
                        print(f"SUCCESS: {success_message}")

                try:
                    self.root.after(0, show_success)
                except RuntimeError as e:
                    print(f"Could not schedule success dialog: {e}")
                    print(f"SUCCESS: {success_message}")

            except RuntimeError as runtime_error:
                # Handle dependency errors specifically
                error_message = str(runtime_error)
                if "Missing critical dependencies" in error_message:
                    # Stop progress on dependency error
                    self.stop_progress("Missing dependencies")
                    self.add_log_message(f"Dependency error: {error_message}", "error")
                    
                    # Schedule the dependency error dialog on the main thread
                    def show_dependency_error():
                        try:
                            CopyableErrorDialog(
                                self.root,
                                "Missing Dependencies",
                                "The application cannot run due to missing dependencies.\n\n" +
                                "Most likely cause:\n" +
                                "• Java is not installed or not in your system PATH\n\n" +
                                "Java is required for PDF table extraction (Tabula library).\n\n" +
                                "To fix this:\n" +
                                "1. Install Java JRE or JDK from https://java.com\n" +
                                "2. Ensure Java is added to your system PATH\n" +
                                "3. Restart the application\n\n" +
                                "You can test Java installation by opening Command Prompt and typing: java -version\n\n" +
                                f"Technical details:\n{error_message}",
                                error_message
                            )
                        except Exception as gui_error:
                            # Fallback if GUI fails
                            messagebox.showerror(
                                "Missing Dependencies", 
                                f"Critical dependencies missing: {error_message}"
                            )
                    
                    try:
                        self.root.after(0, show_dependency_error)
                    except RuntimeError as e:
                        print(f"[GUI UPDATE] Could not schedule dependency error dialog: {e}")
                        print(f"DEPENDENCY ERROR: {error_message}")
                else:
                    # Handle other runtime errors normally
                    self.stop_progress("Runtime error")
                    self.add_log_message(f"Runtime error: {error_message}", "error")
                    
                    def show_runtime_error():
                        try:
                            CopyableErrorDialog(
                                self.root,
                                "Runtime Error",
                                f"A runtime error occurred:\n\n{error_message}",
                                error_message
                            )
                        except Exception as gui_error:
                            messagebox.showerror("Runtime Error", f"Runtime error: {error_message}")
                    
                    try:
                        self.root.after(0, show_runtime_error)
                    except RuntimeError as e:
                        print(f"[GUI UPDATE] Could not schedule runtime error dialog: {e}")
                        print(f"RUNTIME ERROR: {error_message}")
                        
            except Exception as e:
                # Stop progress on error
                self.stop_progress("Pipeline failed")
                
                # Log comprehensive error information
                error_message = str(e)
                try:
                    log_to_file(f"=== PIPELINE FAILED ===")
                    log_to_file(f"Error: {error_message}")
                    log_to_file(f"Error type: {type(e).__name__}")
                    
                    # Add stack trace to log file
                    import traceback
                    log_to_file("=== STACK TRACE ===")
                    log_to_file(traceback.format_exc())
                    log_to_file("=== END ERROR LOG ===")
                except:
                    pass  # Don't let logging errors prevent error handling
                
                self.add_log_message(f"Pipeline failed: {str(e)}", "error")
                
                print("=== Pipeline failed ===")
                print("Error:", str(e))
                
                # Capture error information before creating nested function
                error_message = str(e)
                error_str = error_message.lower()
                
                # Schedule the error dialog on the main thread
                def show_error():
                    try:
                        if "chromedriver" in error_str or "chrome" in error_str or "browser" in error_str:
                            # ChromeDriver specific error
                            CopyableErrorDialog(
                                self.root,
                                "ChromeDriver Error",
                                "The price lookup failed due to a ChromeDriver issue.\n\n" +
                                "This usually means:\n" +
                                "• ChromeDriver is not installed or not in the correct location\n" +
                                "• ChromeDriver version doesn't match your Chrome browser version\n" +
                                "• Chrome browser is not installed\n" +
                                "• Antivirus software is blocking ChromeDriver\n\n" +
                                "The pipeline completed the PDF extraction and table merging steps successfully, " +
                                "but could not retrieve pricing data from the web.\n\n" +
                                "To resolve this:\n" +
                                "1. Ensure Chrome browser is installed and up to date\n" +
                                "2. Download the matching ChromeDriver from: https://chromedriver.chromium.org/\n" +
                                "3. Place chromedriver.exe in the application's src folder\n" +
                                "4. Check that antivirus software isn't blocking the application\n\n" +
                                f"Detailed error log saved to: {error_log_path}",
                                f"Full error details:\n{error_message}"
                            ).show()
                        elif "java" in error_str or "system requirements" in error_str:
                            # System requirements error
                            CopyableErrorDialog(
                                self.root,
                                "System Requirements Error",
                                "The pipeline failed due to missing system requirements.\n\n" +
                                "This usually means:\n" +
                                "• Java is not installed (required for PDF table extraction)\n" +
                                "• ChromeDriver is not available (required for price lookup)\n" +
                                "• Required Python packages are missing\n\n" +
                                "To resolve this:\n" +
                                "1. Install Java from: https://www.java.com/download/\n" +
                                "2. Download ChromeDriver from: https://chromedriver.chromium.org/\n" +
                                "3. Place chromedriver.exe in the application's src folder\n" +
                                "4. Restart the application and try again\n\n" +
                                f"Detailed error log saved to: {error_log_path}",
                                f"Full error details:\n{error_message}"
                            ).show()
                        else:
                            # Generic error dialog
                            CopyableErrorDialog(
                                self.root,
                                "Pipeline Error",
                                f"The BoM processing pipeline encountered an error and could not complete.\n\n" +
                                f"Error: {error_message}\n\n" +
                                f"A detailed error log has been saved to:\n{error_log_path}\n\n" +
                                "Please share this log file with support for assistance.",
                                f"Full error details:\n{error_message}"
                            ).show()
                    except Exception as gui_error:
                        print(f"[GUI UPDATE] Could not show error dialog: {gui_error}")
                        print(f"ERROR: {error_message}")
                        print(f"ERROR LOG: Check {error_log_path} for details")
                
                try:
                    self.root.after(0, show_error)
                except RuntimeError as e:
                    print(f"[GUI UPDATE] Could not schedule error dialog: {e}")
                    print(f"ERROR: {error_message}")

        threading.Thread(target=background_task).start()

    def check_system_requirements(self, silent=False):
        """Check and warn about system requirements.
        
        Args:
            silent (bool): If True, only log warnings without showing popup dialogs
        """
        warnings = []
        
        # Check Java
        java_installed, java_version, java_error = check_java_installation()
        if not java_installed:
            self.add_log_message("Java not detected - required for PDF extraction", "warning")
            if not silent:
                response = Messagebox.show_question(
                    "Java Not Found",
                    "Java is required for PDF table extraction.\n\n" + 
                    (java_error or "Java not detected.") + 
                    "\n\nWould you like to download Java now?",
                    parent=self.root
                )
                if response == "Yes":
                    open_help_url("https://www.java.com/download/")
            warnings.append("Java not installed")
        else:
            self.add_log_message(f"Java detected: {java_version}", "success")
        
        # Check ChromeDriver
        chrome_available, chrome_version, chrome_error = check_chromedriver_availability()
        if not chrome_available:
            self.add_log_message("ChromeDriver not available - required for price lookup", "warning")
            self.add_log_message(f"ChromeDriver error: {chrome_error}", "error")
            if not silent:
                response = Messagebox.show_question(
                    "ChromeDriver Not Found",
                    "ChromeDriver is required for price lookup.\n\n" + 
                    (chrome_error or "ChromeDriver not detected.") + 
                    "\n\nWould you like to open the ChromeDriver download page?",
                    parent=self.root
                )
                if response == "Yes":
                    open_help_url("https://chromedriver.chromium.org/downloads")
            warnings.append("ChromeDriver not available")
        else:
            self.add_log_message(f"ChromeDriver detected: {chrome_version}", "success")
        
        # Check OCR (optional but recommended)
        ocr_available, ocr_version, ocr_error = check_ocrmypdf_installation()
        tesseract_available, tesseract_version, tesseract_error = check_tesseract_installation()
        
        if ocr_available and tesseract_available:
            self.add_log_message(f"OCR available: {ocr_version}", "success")
            self.add_log_message(f"Tesseract available: {tesseract_version}", "success")
        else:
            self.add_log_message("OCR not available - recommended for image-based PDFs", "warning")
            if not ocr_available:
                self.add_log_message(f"OCRmyPDF: {ocr_error}", "warning")
            if not tesseract_available:
                self.add_log_message(f"Tesseract: {tesseract_error}", "warning")
            
            # Only show OCR popup if not in silent mode
            if not silent:
                response = Messagebox.show_question(
                    "OCR Recommended",
                    "OCR (Optical Character Recognition) is recommended for better table extraction from image-based PDFs.\n\n" +
                    "Without OCR, some PDFs may fail to extract tables properly.\n\n" +
                    "Would you like to see installation instructions?",
                    parent=self.root
                )
                if response == "Yes":
                    # Show installation instructions
                    instructions = get_ocr_installation_instructions()
                    CopyableErrorDialog(
                        self.root,
                        "OCR Installation Instructions",
                        instructions,
                        None
                    ).show()
            warnings.append("OCR not available (optional but recommended)")
        
        # Show summary if there are warnings (only in non-silent mode)
        if warnings and not silent:
            warning_text = "System Requirements Warning:\n\n" + "\n".join([f"• {w}" for w in warnings])
            warning_text += "\n\nYou can still try to run the pipeline, but some features may not work properly."
            Messagebox.show_warning("System Requirements", warning_text, parent=self.root)
        elif not warnings:
            self.add_log_message("All system requirements met", "success")

# Review window functionality has been moved to review_window.py
# Use show_review_window(merged_df, parent_window) from the imported module

if __name__ == "__main__":
    try:
        # Create the main window with ttkbootstrap's darkly theme
        root = ttk.Window(themename="darkly")
        
        # Set application icon with improved quality handling
        try:
            if getattr(sys, 'frozen', False):
                # Running as PyInstaller executable
                icon_path = Path(sys._MEIPASS) / "assets" / "BoMination_black.ico"
            else:
                # Running as script - go up two levels from src/gui/ to root, then to assets/
                icon_path = Path(__file__).parent.parent.parent / "assets" / "BoMination_black.ico"
            
            if icon_path.exists():
                # Method 1: Use iconbitmap for basic compatibility
                root.iconbitmap(str(icon_path))
                
                # Method 2: Try to set higher quality icon using photoimage
                try:
                    from PIL import Image, ImageTk
                    import tkinter as tk
                    
                    # Load the icon as a PhotoImage for better quality
                    # We'll use a 32x32 version for the window
                    icon_image = Image.open(str(icon_path))
                    icon_image = icon_image.resize((32, 32), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(icon_image)
                    root.iconphoto(False, photo)
                    
                    # Store reference to prevent garbage collection
                    root._icon_photo = photo
                    print(f"[OK] High-quality icon loaded from: {icon_path}")
                except ImportError:
                    print(f"[OK] Basic icon loaded from: {icon_path} (PIL not available for high-quality mode)")
                except Exception as e:
                    print(f"[OK] Basic icon loaded from: {icon_path} (high-quality mode failed: {e})")
            else:
                print(f"[WARNING] Icon not found at: {icon_path}")
        except Exception as e:
            print(f"[WARNING] Could not load application icon: {e}")

        # Add proper cleanup handler
        def on_closing():
            try:
                root.quit()
                root.destroy()
            except:
                pass  # Ignore cleanup errors
        
        root.protocol("WM_DELETE_WINDOW", on_closing)
        
        app = BoMApp(root)
        
        # Start maximized
        root.state('zoomed')  # Windows-specific maximized state
        root.mainloop()
        
    except Exception as e:
        print(f"Application error: {e}")
    finally:
        # Force cleanup
        try:
            if 'root' in locals():
                root.quit()
                root.destroy()
        except:
            pass