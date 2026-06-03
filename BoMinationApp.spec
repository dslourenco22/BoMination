# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BoMination — LLM edition (LD)
# NOTE: Ollama itself cannot be bundled here — it must be installed separately. (LD)
# The ollama Python package below is just the HTTP client that talks to it. (LD)
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    # Cost sheet template bundled with the exe (LD)
    ('C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\Files\\OCTF-1539-COST SHEET.xlsx', 'Files'),
    ('C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\src', 'src'),
    ('C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\assets', 'assets'),
]

hiddenimports = [
    # GUI (LD)
    'ttkbootstrap', 'tkinter',
    # Data (LD)
    'pandas', 'numpy', 'openpyxl', 'xlrd', 'pandastable',
    # PDF + OCR (LD)
    'pdfplumber', 'PIL', 'PyMuPDF',
    # Local LLM client — talks to the Ollama server over localhost (LD)
    'ollama',
    # Price lookup (LD)
    'duckduckgo_search',
    # App modules (LD)
    'pipeline', 'pipeline.main_pipeline', 'pipeline.extract_main',
    'pipeline.lookup_price', 'pipeline.map_cost_sheet',
    'pipeline.validation_utils', 'pipeline.ocr_preprocessor',
    'pipeline.extract_bom_tab', 'pipeline.extract_bom_cam',
    'gui', 'gui.settings_tab', 'gui.review_window',
    'gui.roi_picker', 'gui.table_selector',
    'omni_cust', 'omni_cust.customer_config', 'omni_cust.customer_formatters',
    # Supporting (LD)
    'packaging', 'packaging.version', 'packaging.specifiers', 'packaging.requirements',
]

datas += collect_data_files('ttkbootstrap')
hiddenimports += collect_submodules('ttkbootstrap')
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('packaging')
hiddenimports += collect_submodules('pipeline')
hiddenimports += collect_submodules('gui')
hiddenimports += collect_submodules('omni_cust')
hiddenimports += collect_submodules('ollama')
hiddenimports += collect_submodules('pdfplumber')
hiddenimports += collect_submodules('duckduckgo_search')

a = Analysis(
    ['C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\src\\gui\\BoMinationApp.py'],
    pathex=[
        'C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\src',
        'C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\src\\pipeline',
        'C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\src\\gui',
        'C:\\Users\\Luke Malkasian\\Documents\\OMNI\\BoMination\\src\\omni_cust',
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib.tests', 'numpy.tests', 'pandas.tests', 'PIL.tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BoMinationApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep True so Ollama output is visible during testing (LD)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
