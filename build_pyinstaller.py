"""
PyInstaller build script for BoMination App
Enhanced version for sales team distribution
"""
import PyInstaller.__main__
from pathlib import Path
import sys
import subprocess
import os

def terminate_existing_app():
    """Terminate any running instances of BoMinationApp.exe."""
    print("🔍 Checking for running BoMinationApp instances...")
    
    try:
        # Check if BoMinationApp.exe is running
        result = subprocess.run(['tasklist', '/fi', 'imagename eq BoMinationApp.exe'], 
                              capture_output=True, text=True, shell=True)
        
        if 'BoMinationApp.exe' in result.stdout:
            print("⚠️  Found running BoMinationApp instances - terminating...")
            subprocess.run(['taskkill', '/f', '/im', 'BoMinationApp.exe'], 
                          capture_output=True, shell=True)
            print("✅ Terminated existing instances")
        else:
            print("✅ No running instances found")
            
    except Exception as e:
        print(f"⚠️  Could not check/terminate existing instances: {e}")
        print("   Please manually close any running BoMinationApp instances")

def check_dependencies():
    """Check if all required dependencies are installed."""
    print("🔍 Checking dependencies...")
    
    # Map package names to their import names
    required_packages = {
        'pyinstaller': 'PyInstaller',
        'pandas': 'pandas',
        'ttkbootstrap': 'ttkbootstrap',
        'tabula-py': 'tabula',
        'openpyxl': 'openpyxl',
        'matplotlib': 'matplotlib',
        'pandastable': 'pandastable'
    }
    
    missing = []
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"✅ {package_name}")
        except ImportError:
            missing.append(package_name)
            print(f"❌ {package_name}")
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        print("Please install them using: pip install -r requirements.txt")
        return False
    
    print("✅ All dependencies found!")
    return True

def build_app():
    """Build the BoMination app using PyInstaller."""
    
    if not check_dependencies():
        sys.exit(1)
    
    # Terminate any existing instances before building
    terminate_existing_app()
    
    # Clean up existing build artifacts
    current_dir = Path(__file__).parent
    exe_path = current_dir / "dist" / "BoMinationApp.exe"
    if exe_path.exists():
        try:
            exe_path.unlink()
            print("✅ Removed existing executable")
        except PermissionError:
            print("⚠️  Could not remove existing executable - it may still be in use")
            print("   Please manually delete dist/BoMinationApp.exe and try again")
            sys.exit(1)
    
    # Get the current directory
    src_dir = current_dir / "src"
    
    # Main script path - use the main BoMinationApp.py directly
    main_script = str(src_dir / "gui" / "BoMinationApp.py")
    
    # Chromedriver path
    chromedriver_path = str(src_dir / "chromedriver.exe")
    
    # Files directory path (contains cost sheet template)
    files_dir = current_dir / "Files"
    cost_sheet_path = str(files_dir / "OCTF-1539-COST SHEET.xlsx")
    
    # Assets directory path (contains icon)
    assets_dir = current_dir / "assets"
    icon_path = str(assets_dir / "BoMination_black.ico")
    
    # Verify critical files exist
    critical_files = [main_script, chromedriver_path, cost_sheet_path]
    missing_files = [f for f in critical_files if not Path(f).exists()]
    
    # Check if icon exists (optional)
    icon_exists = Path(icon_path).exists()
    if not icon_exists:
        print(f"⚠️ Icon file not found: {icon_path}")
        print("   Place your icon as 'bomination_icon.ico' in the 'assets' folder")
    
    if missing_files:
        print(f"❌ Missing critical files:")
        for f in missing_files:
            print(f"   - {f}")
        sys.exit(1)
    
    print("✅ All critical files found!")
    
    # All Python source files organized by subdirectory
    pipeline_files = [
        str(src_dir / "pipeline" / "main_pipeline.py"),
        str(src_dir / "pipeline" / "extract_main.py"),
        str(src_dir / "pipeline" / "extract_bom_tab.py"),
        str(src_dir / "pipeline" / "extract_bom_cam.py"),
        str(src_dir / "pipeline" / "lookup_price.py"),
        str(src_dir / "pipeline" / "map_cost_sheet.py"),
        str(src_dir / "pipeline" / "validation_utils.py"),
        str(src_dir / "pipeline" / "ocr_preprocessor.py"),
    ]
    
    gui_files = [
        str(src_dir / "gui" / "review_window.py"),
        str(src_dir / "gui" / "roi_picker.py"),
        str(src_dir / "gui" / "table_selector.py"),
        str(src_dir / "gui" / "settings_tab.py"),  # New settings tab
    ]
    
    customer_files = [
        str(src_dir / "omni_cust" / "customer_config.py"),
        str(src_dir / "omni_cust" / "customer_formatters.py"),
    ]
    
    all_src_files = pipeline_files + gui_files + customer_files
    
    # Build arguments for PyInstaller
    args = [
        main_script,
        '--name=BoMinationApp',
        '--onefile',  # Create a single executable
        '--windowed',  # Don't show console window
        '--noconfirm',  # Overwrite output directory without confirmation
        f'--paths={src_dir}',  # Add src directory to Python path
        f'--paths={src_dir}/pipeline',  # Add pipeline directory to Python path
        f'--paths={src_dir}/gui',  # Add gui directory to Python path
        f'--paths={src_dir}/omni_cust',  # Add omni_cust directory to Python path
        f'--add-data={chromedriver_path};.',  # Include chromedriver
        f'--add-data={cost_sheet_path};Files',  # Include cost sheet template
        f'--add-data={src_dir};src',  # Include all source files
        f'--add-data={assets_dir};assets',  # Include assets (icon)
        f'--add-data={current_dir / "logo.jpeg"};.',  # Include brand logo for the header
        '--hidden-import=PIL._tkinter_finder',  # PIL/Tk image loading for the logo
        '--hidden-import=ttkbootstrap',
        '--hidden-import=selenium',
        '--hidden-import=pandas',
        '--hidden-import=numpy',
        '--hidden-import=matplotlib',
        '--hidden-import=openpyxl',
        '--hidden-import=xlrd',
        '--hidden-import=tabula',
        '--hidden-import=pandastable',
        '--hidden-import=PIL',
        '--hidden-import=tkinter',
        '--hidden-import=jpype1',
        '--hidden-import=jpype1._jvmfinder',
        '--hidden-import=packaging',
        '--hidden-import=packaging.version',
        '--hidden-import=packaging.specifiers',
        '--hidden-import=packaging.requirements',
        '--hidden-import=pipeline',
        '--hidden-import=pipeline.main_pipeline',
        '--hidden-import=pipeline.extract_main',
        '--hidden-import=pipeline.extract_bom_tab',
        '--hidden-import=pipeline.extract_bom_cam',
        '--hidden-import=pipeline.lookup_price',
        '--hidden-import=pipeline.map_cost_sheet',
        '--hidden-import=pipeline.validation_utils',
        '--hidden-import=pipeline.ocr_preprocessor',
        '--hidden-import=gui',
        '--hidden-import=gui.review_window',
        '--hidden-import=gui.roi_picker',
        '--hidden-import=gui.table_selector',
        '--hidden-import=gui.settings_tab',  # New settings tab
        '--hidden-import=omni_cust',
        '--hidden-import=omni_cust.customer_config',
        '--hidden-import=omni_cust.customer_formatters',
        '--collect-submodules=selenium',
        '--collect-submodules=ttkbootstrap',
        '--collect-submodules=pandas',
        '--collect-submodules=tabula',
        '--collect-submodules=packaging',
        '--collect-submodules=pipeline',
        '--collect-submodules=gui',
        '--collect-submodules=omni_cust',
        '--collect-data=ttkbootstrap',
        '--collect-data=tabula',
        '--additional-hooks-dir=.',  # Include our custom hooks
        '--distpath=dist',
        '--workpath=build',
        '--specpath=.',
        '--exclude-module=matplotlib.tests',
        '--exclude-module=numpy.tests',
        '--exclude-module=pandas.tests',
        '--exclude-module=PIL.tests',
    ]
    
    # Add icon if available
    if icon_exists:
        args.append(f'--icon={icon_path}')
        print(f"✅ Icon will be included: {icon_path}")
    else:
        print("⚠️ Building without icon")
    
    print("\n🚀 Starting PyInstaller build...")
    print(f"📄 Main script: {main_script}")
    print(f"🌐 Chromedriver: {chromedriver_path}")
    print(f"📊 Cost sheet: {cost_sheet_path}")
    print(f"📁 Source files: {len(all_src_files)} files")
    print(f"🎯 Output: dist/BoMinationApp.exe")
    print()
    
    # Run PyInstaller
    try:
        PyInstaller.__main__.run(args)
        print("\n✅ Build completed successfully!")
        print("📦 Check the 'dist' folder for BoMinationApp.exe")
        
        # Check if the executable was created
        exe_path = current_dir / "dist" / "BoMinationApp.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"📏 Executable size: {size_mb:.1f} MB")
        else:
            print("⚠️  Executable not found - check build logs for errors")
            
    except Exception as e:
        print(f"\n❌ Build failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    build_app()
