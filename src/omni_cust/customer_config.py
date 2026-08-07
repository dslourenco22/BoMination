# Customer Configuration for BoMination
# This file can be used to easily configure the application for different deployments

# Default customer to use when none is specified
DEFAULT_CUSTOMER = "generic"

# Customer display names for the UI
CUSTOMER_DISPLAY_NAMES = {
    "farrell": "Farrell",
    "nel": "NEL",
    "primetals": "Primetals",
    "riley_power": "Riley Power",
    "shanklin": "Shanklin",
    "901d": "901D",
    "amazon": "Amazon",
    "eos": "EOS",
    "generic": "Generic/Other"
}

# Auto-detection keywords for each customer
# These are used to automatically detect the customer from document content
AUTO_DETECTION_KEYWORDS = {
    "nel": ["NEL HYDROGEN", "PROTON ENERGY", "PROTON P/N"],
    "farrell": ["FARRELL"],
    "primetals": ["PRIMETALS", "PRIMETALS TECHNOLOGIES"],
    "riley_power": ["RILEY POWER", "RILEY TRANSMISSION"],
    "shanklin": ["SHANKLIN", "SHANKLIN CORPORATION"],
    "901d": ["901D", "901-D"],
    "amazon": ["AMAZON", "DEVICE TAG", "LIFECYCLE", "PRODUCTIO"],
    "eos": ["EOS ENERGY", "EOS ENERGY ENTERPRISES", "EOS ENERGY STORAGE"],
    # Add more customers here as needed
}

# Customer-specific settings
CUSTOMER_SETTINGS = {
    "farrell": {
        "split_mfg_part": True,
        "header_keywords": ["QTY", "PART", "MFG", "PAF", "DESCRIPTION", "INTERNAL"],
        "reject_keywords": ["PRINTED DRAWING", "REFERENCE ONLY"]
    },
    "nel": {
        "remove_instruction_rows": True,
        "header_keywords": ["ITEM", "QTY", "PART", "DESCRIPTION", "REFERENCE", "MFG"],
        "reject_keywords": ["CUT BACK", "REMOVE", "SHRINK TUBING", "DRAWING NUMBER"]
    },
    "primetals": {
        "split_dual_column": True,
        "header_keywords": ["ITEM", "MFG", "MFGPART", "DESCRIPTION", "QTY"],
        "reject_keywords": ["PRIMETALS TECHNOLOGIES", "CONFIDENTIAL", "PROPRIETARY"]
    },
    "riley_power": {
        "merge_split_descriptions": True,
        "header_keywords": ["ITEM", "QTY", "MANUFACTURER", "MODEL NO", "ITEM DES", "RIPTION"],
        "reject_keywords": ["PROPRIETARY", "CONFIDENTIAL"]
    },
    "shanklin": {
        "reverse_row_order": True,
        "header_at_bottom": True,
        "header_keywords": ["ITEM", "PART", "NUMBER", "DESCRIPTION", "SPC"],
        "reject_keywords": []
    },
    "901d": {
        "force_ocr": True,  # Special case: Always force OCR preprocessing for 901D
        "header_keywords": ["ITEM", "QTY", "PART", "DESCRIPTION", "MANUFACTURER"],
        "reject_keywords": []
    },
    "amazon": {
        "header_keywords": ["DEVICE TAG", "QTY", "MANUFACTURER", "PART NUMBER", "DESCRIPTION", "UL CAT", "CSA"],
        "reject_keywords": ["REVISION", "RELEASED", "LIFECYCLE", "DESIGNED BY", "CHECKED BY", "APPROVED BY"]
    },
    "eos": {
        # Engineering drawings: image-based, two side-by-side BOM tables, and the
        # header sits at the BOTTOM of each table with rows numbered upward.
        "force_ocr": True,
        "header_at_bottom": True,
        "split_dual_column": True,
        "header_keywords": ["PN", "MANUFACTURER", "DESCRIPTION", "QTY", "UOM"],
        "reject_keywords": ["PROPRIETARY AND CONFIDENTIAL", "DO NOT SCALE DRAWING",
                            "FOR APPROVAL", "FOR REFERENCE ONLY", "SEE SEPARATE PARTS LIST",
                            "THIRD ANGLE PROJECTION", "REVISIONS", "INITIAL RELEASE"]
    },
    "generic": {
        "header_keywords": ["ITEM", "QTY", "PART", "DESCRIPTION", "MANUFACTURER"]
    }
}

# For new company deployments, you can:
# 1. Change DEFAULT_CUSTOMER to the most common customer
# 2. Update CUSTOMER_DISPLAY_NAMES for the UI
# 3. Add new customers to AUTO_DETECTION_KEYWORDS
# 4. Configure CUSTOMER_SETTINGS for each customer
# 5. Add new customer formatters to customer_formatters.py