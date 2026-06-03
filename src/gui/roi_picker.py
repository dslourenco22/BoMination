# """
# ROI (Region of Interest) Picker for BoMination

# This module provides a graphical interface for manually selecting table areas
# in PDF pages using matplotlib's RectangleSelector. The selected areas are
# converted to PDF coordinates for use with Tabula.
# """

# import tkinter as tk
# from tkinter import messagebox, ttk
# import matplotlib.pyplot as plt
# from matplotlib.widgets import RectangleSelector
# from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
# import numpy as np
# from pathlib import Path
# import fitz  # PyMuPDF
# from PIL import Image, ImageTk
# import threading
# import time
# import tabula  # Add tabula import
# from typing import List, Tuple, Optional, Dict, Any

# class ROIPicker:
#     """GUI tool for manually selecting table areas in PDF pages."""
    
#     def __init__(self, pdf_path: str, pages: str, parent_window=None):
#         self.pdf_path = Path(pdf_path)
#         self.pages = pages
#         self.parent_window = parent_window
        
#         # Parse page range
#         self.page_numbers = self._parse_page_range(pages)
#         self.current_page_index = 0
        
#         # Results storage
#         self.selected_areas = {}  # page_num -> (x, y, w, h) in pixels
#         self.tabula_areas = {}    # page_num -> [top, left, bottom, right] in points
        
#         # PDF and image data
#         self.pdf_doc = None
#         self.current_page_image = None
#         self.page_dimensions = {}  # page_num -> (width, height) in points
        
#         # GUI components
#         self.root = None
#         self.fig = None
#         self.ax = None
#         self.canvas = None
#         self.selector = None
#         self.current_selection = None
        
#         # Status tracking
#         self.is_cancelled = False
#         self.is_completed = False
        
#     def _parse_page_range(self, pages: str) -> List[int]:
#         """Parse page range string into list of page numbers."""
#         page_numbers = []
        
#         for part in pages.split(','):
#             part = part.strip()
#             if '-' in part:
#                 start, end = part.split('-')
#                 start, end = int(start.strip()), int(end.strip())
#                 page_numbers.extend(range(start, end + 1))
#             else:
#                 page_numbers.append(int(part))
        
#         return sorted(set(page_numbers))  # Remove duplicates and sort
    
#     def show_picker(self) -> Optional[Dict[int, List[float]]]:
#         """
#         Show the ROI picker interface.
        
#         Returns:
#             Dict mapping page numbers to tabula areas [top, left, bottom, right] in points,
#             or None if cancelled.
#         """
#         print("ROI DEBUG: show_picker called")
#         try:
#             # Open PDF document
#             print("ROI DEBUG: Opening PDF document")
#             self.pdf_doc = fitz.open(self.pdf_path)
            
#             # Create the picker window
#             print("ROI DEBUG: Creating picker window")
#             self._create_picker_window()
            
#             # Start with the first page
#             print("ROI DEBUG: Loading current page")
#             self._load_current_page()
            
#             # Final window setup - ensure everything is properly sized
#             print("ROI DEBUG: Updating window layout")
#             self.root.update_idletasks()
            
#             # Force window to update layout before starting
#             self.root.geometry(self.root.geometry())  # Force geometry update
#             self._adjust_figure_size()
            
#             # Run the GUI
#             print("ROI DEBUG: Starting wait_window (modal dialog)")
#             self.root.wait_window()  # Use wait_window instead of mainloop for modal behavior
            
#             print("ROI DEBUG: wait_window ended")
            
#             # Clean up
#             if self.pdf_doc:
#                 self.pdf_doc.close()
            
#             # Return results
#             if self.is_cancelled:
#                 print("ROI DEBUG: Returning None (cancelled)")
#                 return None
#             else:
#                 print(f"ROI DEBUG: Returning tabula_areas: {self.tabula_areas}")
#                 return self.tabula_areas
                
#         except Exception as e:
#             print(f"ROI DEBUG: Exception in show_picker: {e}")
#             if self.pdf_doc:
#                 self.pdf_doc.close()
#             messagebox.showerror("Error", f"Failed to open PDF or create picker: {str(e)}")
#             return None
    
#     def _create_picker_window(self):
#         """Create the main picker window."""
#         self.root = tk.Toplevel(self.parent_window) if self.parent_window else tk.Tk()
#         self.root.title("BoMination - Table Area Selector")
#         self.root.geometry("1200x900")  # Restored larger initial size
#         self.root.resizable(True, True)
        
#         # Start maximized to fill the screen
#         self.root.state('zoomed')  # Windows maximized state
        
#         # Ensure window has proper minimize/maximize controls
#         self.root.wm_attributes('-toolwindow', False)
        
#         # Make it modal if parent exists
#         if self.parent_window:
#             self.root.transient(self.parent_window)
        
#         # Bring window to front and focus
#         self.root.lift()
#         self.root.focus_force()
        
#         # Make it modal if parent exists
#         if self.parent_window:
#             self.root.grab_set()
        
#         # Bind window resize event to adjust figure size
#         self.root.bind('<Configure>', self._on_window_resize)
        
#         # Handle window close
#         self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)
        
#         # Main frame with reduced padding
#         main_frame = ttk.Frame(self.root)
#         main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
#         # Title
#         title_label = ttk.Label(
#             main_frame, 
#             text="Table Area Selector", 
#             font=("Segoe UI", 16, "bold")
#         )
#         title_label.pack(pady=(0, 10))
        
#         # Page info frame
#         page_info_frame = ttk.Frame(main_frame)
#         page_info_frame.pack(fill=tk.X, pady=(0, 5))
        
#         self.page_info_label = ttk.Label(
#             page_info_frame, 
#             text="", 
#             font=("Segoe UI", 12, "bold")
#         )
#         self.page_info_label.pack(side=tk.LEFT)
        
#         # Progress info
#         self.progress_label = ttk.Label(
#             page_info_frame, 
#             text="", 
#             font=("Segoe UI", 10)
#         )
#         self.progress_label.pack(side=tk.RIGHT)
        
#         # Matplotlib figure frame with constrained size
#         fig_frame = ttk.Frame(main_frame)
#         fig_frame.pack(fill=tk.X, pady=(0, 5))  # Changed from fill=BOTH, expand=True
        
#         # Create matplotlib figure with conservative sizing to prevent double rendering
#         self.fig, self.ax = plt.subplots(figsize=(8, 5))  # Conservative initial size
#         self.fig.patch.set_facecolor('white')
        
#         # Minimize margins around the plot
#         self.fig.subplots_adjust(left=0.02, right=0.98, top=0.95, bottom=0.05)
        
#         # Create canvas with fixed height to prevent sizing issues
#         self.canvas = FigureCanvasTkAgg(self.fig, master=fig_frame)
#         canvas_widget = self.canvas.get_tk_widget()
#         canvas_widget.pack(fill=tk.X, pady=(0, 5))
#         canvas_widget.configure(height=450)  # Fixed conservative height
        
#         # Add matplotlib navigation toolbar in a compact frame
#         toolbar_frame = ttk.Frame(fig_frame)
#         toolbar_frame.pack(fill=tk.X, pady=(2, 0))
        
#         from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
#         self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
#         self.toolbar.update()
        
#         # Add a visual separator between PDF and buttons
#         separator = ttk.Separator(main_frame, orient='horizontal')
#         separator.pack(fill=tk.X, pady=(3, 3))
        
#         # Control buttons frame - positioned RIGHT UNDER the PDF/toolbar
#         button_frame = ttk.Frame(main_frame, height=60)  # Increased height
#         button_frame.pack(fill=tk.X, pady=(5, 10))  # More padding to ensure visibility
#         button_frame.pack_propagate(False)  # Prevent shrinking
        
#         # Left side buttons
#         left_buttons = ttk.Frame(button_frame)
#         left_buttons.pack(side=tk.LEFT, anchor=tk.W)
        
#         self.clear_button = ttk.Button(
#             left_buttons, 
#             text="Clear Selection", 
#             command=self._clear_selection,
#             state=tk.DISABLED
#         )
#         self.clear_button.pack(side=tk.LEFT, padx=(0, 10))
        
#         # Add fit to window button
#         self.fit_button = ttk.Button(
#             left_buttons, 
#             text="Fit to Window", 
#             command=self._fit_to_window
#         )
#         self.fit_button.pack(side=tk.LEFT, padx=(0, 10))
        
#         # Right side buttons
#         right_buttons = ttk.Frame(button_frame)
#         right_buttons.pack(side=tk.RIGHT, anchor=tk.E)
        
#         # Make the confirm button more prominent and ensure it's visible
#         self.confirm_button = ttk.Button(
#             right_buttons, 
#             text="✓ Confirm Selection", 
#             command=self._confirm_selection,
#             state=tk.DISABLED,
#             width=18
#         )
#         self.confirm_button.pack(side=tk.LEFT, padx=(0, 10))
        
#         ttk.Button(
#             right_buttons, 
#             text="Cancel", 
#             command=self._on_cancel,
#             width=10
#         ).pack(side=tk.LEFT)
        
#         # Make confirm button more prominent with style
#         try:
#             style = ttk.Style()
#             style.configure('Confirm.TButton', font=('Segoe UI', 11, 'bold'))
#             self.confirm_button.configure(style='Confirm.TButton')
#         except:
#             pass  # Fallback if style configuration fails
        
#         # Add a spacer frame to push everything up and leave space at bottom
#         spacer_frame = ttk.Frame(main_frame, height=30)  # Fixed height spacer
#         spacer_frame.pack(fill=tk.X, pady=(5, 5))
#         spacer_frame.pack_propagate(False)
    
#     def _on_window_resize(self, event):
#         """Handle window resize events to adjust figure size."""
#         # Only handle resize events for the main window
#         if event.widget == self.root:
#             # Cancel any pending resize adjustments
#             if hasattr(self, '_resize_after_id'):
#                 self.root.after_cancel(self._resize_after_id)
            
#             # Schedule adjustment with delay to avoid rapid successive calls
#             self._resize_after_id = self.root.after(200, self._adjust_figure_size)
    
#     def _fit_to_window(self):
#         """Fit the current image to the window size."""
#         try:
#             # Reset the view to show the entire image
#             if self.ax.get_images():
#                 img = self.ax.get_images()[0]
#                 img_array = img.get_array()
                
#                 # Set view to show entire image
#                 self.ax.set_xlim(0, img_array.shape[1])
#                 self.ax.set_ylim(img_array.shape[0], 0)
                
#                 # Adjust figure size to fit window with constraints
#                 self._adjust_figure_size()
                
#                 # Use matplotlib's tight_layout to optimize spacing
#                 self.fig.tight_layout(pad=0.02)  # Reduced padding
                
#                 # Single draw call to prevent double rendering
#                 self.canvas.draw_idle()
                
#         except Exception as e:
#             print(f"Error fitting to window: {e}")
    
#     def _adjust_figure_size(self):
#         """Adjust the matplotlib figure size based on current window size."""
#         try:
#             # Get current window dimensions
#             window_width = self.root.winfo_width()
#             window_height = self.root.winfo_height()
            
#             # Calculate available space for the figure (accounting for UI elements)
#             # Reserve space for: title (40px), page info (30px), 
#             # buttons (60px), toolbar (40px), spacer (30px), padding (40px)
#             available_height = window_height - 240  # Total reserved space
#             available_width = window_width - 40     # Side padding
            
#             # Apply strict maximum limits to prevent rendering issues
#             # These limits prevent the double-rendering bug at large sizes
#             max_width = 1000   # Maximum 1000px width
#             max_height = 600   # Maximum 600px height
            
#             # Apply constraints
#             available_height = min(max_height, max(300, available_height))  # 300-600px range
#             available_width = min(max_width, max(500, available_width))    # 500-1000px range
            
#             # Convert to inches (assuming 100 DPI)
#             fig_width = available_width / 100
#             fig_height = available_height / 100
            
#             # Only update if size actually changed (prevent unnecessary redraws)
#             current_width, current_height = self.fig.get_size_inches()
#             width_diff = abs(current_width - fig_width)
#             height_diff = abs(current_height - fig_height)
            
#             # Only redraw if there's a significant change (>0.5 inches)
#             if width_diff > 0.5 or height_diff > 0.5:
#                 # Update figure size
#                 self.fig.set_size_inches(fig_width, fig_height)
                
#                 # Ensure tight layout to minimize whitespace
#                 self.fig.tight_layout(pad=0.02)  # Even tighter layout
                
#                 # Use draw_idle to prevent excessive redraws
#                 self.canvas.draw_idle()
            
#         except Exception as e:
#             print(f"Error adjusting figure size: {e}")
    
#     def _load_current_page(self):
#         """Load and display the current page."""
#         if self.current_page_index >= len(self.page_numbers):
#             self._on_finish()
#             return
        
#         page_num = self.page_numbers[self.current_page_index]
        
#         # Update page info
#         self.page_info_label.config(text=f"Page {page_num}")
#         self.progress_label.config(
#             text=f"Page {self.current_page_index + 1} of {len(self.page_numbers)}"
#         )
        
#         try:
#             # Load page
#             page = self.pdf_doc.load_page(page_num - 1)  # PyMuPDF uses 0-based indexing
            
#             # Store page dimensions in points
#             rect = page.rect
#             self.page_dimensions[page_num] = (rect.width, rect.height)
            
#             # Convert page to image
#             mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
#             pix = page.get_pixmap(matrix=mat)
#             img_data = pix.tobytes("ppm")
            
#             # Convert to PIL Image
#             from io import BytesIO
#             img = Image.open(BytesIO(img_data))
#             self.current_page_image = np.array(img)
            
#             # Display image
#             self.ax.clear()
#             self.ax.imshow(self.current_page_image)
#             self.ax.set_title(f"Page {page_num}", fontsize=12, pad=10)  # Simplified title
#             self.ax.axis('off')  # Hide axes for cleaner look
            
#             # Remove any extra margins/padding around the image
#             self.ax.set_xlim(0, self.current_page_image.shape[1])
#             self.ax.set_ylim(self.current_page_image.shape[0], 0)
            
#             # Adjust figure size to fit window
#             self._adjust_figure_size()
            
#             # Apply tight layout to minimize whitespace
#             self.fig.tight_layout(pad=0.1)
            
#             # Create new rectangle selector
#             self.selector = RectangleSelector(
#                 self.ax, 
#                 self._on_rectangle_select,
#                 useblit=True,
#                 button=[1],  # Only left mouse button
#                 minspanx=5, 
#                 minspany=5,
#                 spancoords='pixels',
#                 interactive=True
#             )
            
#             # Reset selection state
#             self.current_selection = None
#             self.confirm_button.config(state=tk.DISABLED)
#             self.clear_button.config(state=tk.DISABLED)
            
#             # Update canvas ONCE at the end
#             self.canvas.draw_idle()  # Use draw_idle instead of draw to prevent double rendering
            
#         except Exception as e:
#             messagebox.showerror("Error", f"Failed to load page {page_num}: {str(e)}")
#             self._on_cancel()
    
#     def _on_rectangle_select(self, eclick, erelease):
#         """Handle rectangle selection."""
#         # Get selection coordinates in pixels
#         x1, y1 = eclick.xdata, eclick.ydata
#         x2, y2 = erelease.xdata, erelease.ydata
        
#         if None in (x1, y1, x2, y2):
#             return
        
#         # Normalize coordinates
#         x = min(x1, x2)
#         y = min(y1, y2)
#         w = abs(x2 - x1)
#         h = abs(y2 - y1)
        
#         # Store selection
#         self.current_selection = (x, y, w, h)
        
#         # Enable buttons
#         self.confirm_button.config(state=tk.NORMAL)
#         self.clear_button.config(state=tk.NORMAL)
    
#     def _clear_selection(self):
#         """Clear the current selection."""
#         if self.selector:
#             self.selector.set_active(False)
#             self.selector.set_active(True)
        
#         self.current_selection = None
#         self.confirm_button.config(state=tk.DISABLED)
#         self.clear_button.config(state=tk.DISABLED)
        
#         # Redraw canvas
#         self.canvas.draw_idle()  # Use draw_idle to prevent double rendering
    
#     def _confirm_selection(self):
#         """Confirm the current selection and move to next page."""
#         if not self.current_selection:
#             messagebox.showwarning("Warning", "Please select a table area first.")
#             return
        
#         page_num = self.page_numbers[self.current_page_index]
        
#         # Store pixel coordinates
#         self.selected_areas[page_num] = self.current_selection
        
#         # Convert to PDF coordinates for Tabula
#         tabula_area = self._convert_to_tabula_coordinates(
#             self.current_selection, 
#             page_num
#         )
#         self.tabula_areas[page_num] = tabula_area
        
#         # Move to next page
#         self.current_page_index += 1
        
#         # Check if we're done
#         if self.current_page_index >= len(self.page_numbers):
#             self.finish_button.config(state=tk.NORMAL)
#             self.confirm_button.config(state=tk.DISABLED)
#             # Automatically finish so show_picker() returns immediately
#             self._on_finish()
#         else:
#             self._load_current_page()
    
#     def _convert_to_tabula_coordinates(self, pixel_coords: Tuple[float, float, float, float], page_num: int) -> List[float]:
#         """
#         Convert pixel coordinates to PDF coordinates for Tabula.
        
#         Args:
#             pixel_coords: (x, y, w, h) in pixels
#             page_num: Page number
            
#         Returns:
#             [top, left, bottom, right] in points for Tabula
#         """
#         x, y, w, h = pixel_coords
        
#         # Get page dimensions
#         page_width_pts, page_height_pts = self.page_dimensions[page_num]
        
#         # Get image dimensions (remember we used 2x zoom)
#         img_height, img_width = self.current_page_image.shape[:2]
        
#         # Calculate scaling factors
#         scale_x = page_width_pts / img_width
#         scale_y = page_height_pts / img_height
        
#         # Convert pixel coordinates to PDF coordinates
#         # Note: PDF coordinate system has origin at bottom-left
#         # Image coordinate system has origin at top-left
#         left = x * scale_x
#         right = (x + w) * scale_x
#         top = y * scale_y
#         bottom = (y + h) * scale_y
        
#         # Tabula expects [top, left, bottom, right]
#         return [top, left, bottom, right]
    
#     def _on_cancel(self):
#         """Handle cancel button click."""
#         print("ROI DEBUG: _on_cancel called")
#         self.is_cancelled = True
#         self.root.destroy()  # This will end the wait_window()
    
#     def _on_finish(self):
#         """Handle finish button click."""
#         print("ROI DEBUG: _on_finish called")
#         if not self.tabula_areas:
#             print("ROI DEBUG: No table areas selected, showing warning")
#             messagebox.showwarning("Warning", "No table areas selected.")
#             return
        
#         # Show summary
#         summary = "Selected table areas:\n\n"
#         for page_num in sorted(self.tabula_areas.keys()):
#             area = self.tabula_areas[page_num]
#             summary += f"Page {page_num}: [{area[0]:.1f}, {area[1]:.1f}, {area[2]:.1f}, {area[3]:.1f}]\n"
        
#         print(f"ROI DEBUG: Showing confirmation dialog with summary: {summary}")
#         result = messagebox.askyesno(
#             "Confirm Selections", 
#             summary + "\nProceed with these selections?"
#         )
        
#         print(f"ROI DEBUG: User confirmation result: {result}")
#         if result:
#             print("ROI DEBUG: Setting is_completed=True and destroying window")
#             self.is_completed = True
#             self.root.destroy()  # This will end the wait_window()
#         else:
#             print("ROI DEBUG: User clicked No, keeping window open")
#         # If user clicks "No", keep the window open for more selections


# def show_roi_picker(pdf_path: str, pages: str, parent_window=None) -> Optional[Dict[int, List[float]]]:
#     """
#     Show the ROI picker interface for manual table area selection.
    
#     Args:
#         pdf_path: Path to the PDF file
#         pages: Page range string (e.g., "1-3,5,7-9")
#         parent_window: Parent window for modal behavior
    
#     Returns:
#         Dict mapping page numbers to tabula areas [top, left, bottom, right] in points,
#         or None if cancelled.
#     """
#     picker = ROIPicker(pdf_path, pages, parent_window)
#     return picker.show_picker()


# # Example usage for testing
# if __name__ == "__main__":
#     import sys
    
#     if len(sys.argv) != 3:
#         print("Usage: python roi_picker.py <pdf_path> <pages>")
#         sys.exit(1)
    
#     pdf_path = sys.argv[1]
#     pages = sys.argv[2]
    
#     # Test the picker
#     areas = show_roi_picker(pdf_path, pages)
    
#     if areas:
#         print("Selected areas:")
#         for page_num, area in areas.items():
#             print(f"Page {page_num}: {area}")
#     else:
#         print("Selection cancelled or no areas selected")
