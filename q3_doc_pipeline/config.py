"""Document types, the fields to extract for each, and the hints the pipeline uses.

`keywords`  - printed phrases that identify the form (used by the rule-based classifier).
`handwritten` - True for HDFC forms filled by hand; these get extra reads and stricter scoring.
`region`    - (left, top, right, bottom) as fractions of the page where the filled-in fields sit.
              The page is cropped to this box and upscaled before the "zoomed" reads.
`hints`     - short per-field instructions given to the vision model.
"""

VISION_MODEL = "qwen2.5vl:7b"
CONFIDENCE_THRESHOLD = 0.80

DOC_TYPES = {
    "Aadhaar Card": {
        "keywords": ["aadhaar", "unique identification authority", "uidai", "आधार"],
        "handwritten": False,
        "region": (0, 0, 1, 1),
        "fields": {
            "Aadhaar Number": "12-digit number, e.g. 1234 5678 9012",
            "Full Name": "name of the card holder",
            "Date of Birth": "DD/MM/YYYY",
            "Address": "full address on one line",
        },
    },
    "PAN Card": {
        "keywords": ["permanent account number", "income tax department"],
        "handwritten": False,
        "region": (0, 0, 1, 1),
        "fields": {
            "PAN Number": "10 characters: 5 letters, 4 digits, 1 letter",
            "Full Name": "name of the card holder",
            "Father's Name": "father's name as printed (drop any S/O prefix)",
            "Date of Birth": "DD/MM/YYYY",
        },
    },
    "Driving Licence": {
        "keywords": ["driving licence", "driving license", "licencing authority"],
        "handwritten": False,
        "region": (0, 0, 1, 1),
        "fields": {
            "DL Number": "licence number exactly as printed",
            "Name": "the holder's own name only, from the 'Name' line (do not append the S/W/D of value)",
            "Date of Issue": "DD/MM/YYYY",
            "Valid Till": "DD/MM/YYYY",
        },
    },
    "Passport": {
        "keywords": ["passport", "republic of india", "p<ind"],
        "handwritten": False,
        "region": (0, 0, 1, 1),
        "fields": {
            "Passport Number": "letter followed by 7 digits",
            "Date of Birth": "DD/MM/YYYY",
            "Date of Expiry": "DD/MM/YYYY",
            "MRZ Line 2": "second machine-readable line at the bottom, exactly 44 characters including every '<'",
        },
    },
    "NACH / ECS Mandate": {
        "keywords": ["nach mandate", "mandate instruction", "umrn", "sponsor bank code"],
        "handwritten": True,
        "region": (0, 0.03, 1, 0.26),
        "fields": {
            "Bank Account Number": "digits written in the 'Bank a/c number' boxes",
            "IFSC Code": "11 characters in the IFSC boxes: 4 letters, then 0, then 6 letters/digits",
            "Bank Name": "handwritten bank name after 'with bank'",
            "Amount (figures)": "amount in figures next to the rupee sign, digits only",
            "Frequency": "label of the ticked frequency checkbox",
        },
    },
    "FATCA Annexure Form": {
        "keywords": ["285ba", "annexure form", "tax residency", "fatca"],
        "handwritten": True,
        "region": (0, 0.17, 1, 0.5),
        "fields": {
            "Policy Number": "handwritten digits in the 'Policy No' box",
            "TIN / PAN": "value in the 'Tax Identification Number (TIN)' column of the table",
            "Father's Name": "handwritten after 'Father's Name'",
            "Place of Birth": "handwritten after 'Place of birth'",
            "Nationality": "handwritten after 'Nationality'",
        },
    },
    "Benefit Illustration Declaration": {
        "keywords": ["benefit illustration"],
        "handwritten": True,
        "region": (0, 0.12, 1, 0.42),
        "fields": {
            "Application Number": "handwritten digits next to 'Application/Proposal Form Number'",
            "Policyholder Name": "handwritten next to 'Name of Policyholder'",
            "Date": "handwritten date near the signature, DD/MM/YYYY",
            "Place": "handwritten place near the signature",
        },
    },
    "Moral Hazard Questionnaire": {
        "keywords": ["moral hazard"],
        "handwritten": True,
        "region": (0, 0.1, 1, 0.68),
        "fields": {
            "Application Number": "handwritten digits next to 'Application No.'",
            "Name of Life Assured": "handwritten next to 'Name of the Life to be Assured'",
            "Nominee Relationship": "handwritten answer to question 5 'exact relationship of nominee'",
            "Date": "handwritten date in the 'Declaration of Life to be Assured' section, DD/MM/YYYY",
            "Place": "handwritten place in the 'Declaration of Life to be Assured' section",
        },
    },
    "Multiple Policies Consent Form": {
        "keywords": ["multiple policies", "split & multiple", "customer consent form"],
        "handwritten": True,
        "region": (0, 0.1, 1, 0.7),
        "fields": {
            "Proposer Name": "handwritten next to 'Proposer / Life Assured Name'",
            "Reason for Multiple Policies": "label of the ticked checkbox only (short label, e.g. the first words)",
            "Date": "handwritten date at the bottom, DD/MM/YYYY",
            "Place": "handwritten place at the bottom",
        },
    },
    "Suitability Profiler Declaration": {
        "keywords": ["suitability profiler"],
        "handwritten": True,
        "region": (0, 0.12, 1, 0.4),
        "fields": {
            "Application Number": "handwritten digits next to 'Application/Proposal Form Number'",
            "Name of Life Assured": "handwritten next to 'Name of Life Assured'",
            "Name of Agent/SP": "handwritten next to 'Name of Agent/SP'",
            "Date": "handwritten date next to the life assured's signature, DD/MM/YYYY",
            "Place": "handwritten place next to the life assured's signature",
        },
    },
}

OTHER = "Other / Unknown"
