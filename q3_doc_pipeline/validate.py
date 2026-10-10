"""Normalisation and rule-based checks for extracted field values.

Each check returns (ok, note) where ok is True (passes), False (fails) or None (no rule for this field).
"""
import re
from datetime import datetime

# ---------- normalisation ----------

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def normalise_date(value):
    """Return DD/MM/YYYY when the value can be parsed as a date, else the cleaned input."""
    v = str(value).strip()
    digits = re.sub(r"\D", "", v)
    parts = re.split(r"[/\-.\s]+", v)
    try:
        if len(parts) == 3 and all(parts):
            d, m, y = parts
            m = MONTHS.get(m[:3].lower(), m)
            d, m, y = int(d), int(m), int(y)
            if y < 100:
                y += 2000 if y < 50 else 1900
            return f"{d:02d}/{m:02d}/{y:04d}"
        if len(digits) == 8:  # DDMMYYYY written in boxes
            return f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"
    except ValueError:
        pass
    return v


def normalise(field, value):
    if value is None:
        return ""
    v = str(value).strip().strip(".,;").strip()
    if v.lower() in {"", "null", "none", "n/a", "na", "not found", "not visible"}:
        return ""
    f = field.lower()
    if "date" in f or f == "valid till":
        return normalise_date(v)
    if f in {"aadhaar number", "bank account number", "application number", "policy number"}:
        return re.sub(r"\D", "", v)
    if f in {"pan number", "tin / pan", "ifsc code", "passport number"}:
        return re.sub(r"[^A-Za-z0-9]", "", v).upper()
    if f == "amount (figures)":
        return re.sub(r"[^\d]", "", v.split(".")[0])
    if f == "dl number":
        return re.sub(r"\s+", " ", v.upper())
    if f == "mrz line 2":
        return re.sub(r"\s+", "", v.upper()).replace("«", "<")
    return re.sub(r"\s+", " ", v)


def compare_key(field, value):
    """Key used to decide whether two reads agree (ignores case and spacing)."""
    return re.sub(r"[\s.,]", "", normalise(field, value)).lower()


# ---------- checksums ----------

_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(number):
    """Aadhaar numbers end in a Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


def mrz_check_digit(text):
    """ICAO 9303 check digit: weights 7,3,1; digits as-is, A-Z = 10-35, '<' = 0."""
    total = 0
    for i, ch in enumerate(text):
        if ch.isdigit():
            val = int(ch)
        elif ch.isalpha():
            val = ord(ch) - 55
        else:
            val = 0
        total += val * (7, 3, 1)[i % 3]
    return str(total % 10)


def mrz_line2_problems(line):
    """Return a list of failed checks for a TD3 (passport) MRZ line 2."""
    if len(line) != 44:
        return [f"length is {len(line)}, expected 44"]
    problems = []
    checks = [("passport number", line[0:9], line[9]),
              ("date of birth", line[13:19], line[19]),
              ("date of expiry", line[21:27], line[27])]
    for name, data, digit in checks:
        if mrz_check_digit(data) != digit:
            problems.append(f"{name} check digit is {digit}, computed {mrz_check_digit(data)}")
    composite = line[0:10] + line[13:20] + line[21:43]
    if mrz_check_digit(composite) != line[43]:
        problems.append(f"composite check digit is {line[43]}, computed {mrz_check_digit(composite)}")
    return problems


# ---------- per-field rules ----------

def _valid_date(v):
    try:
        datetime.strptime(v, "%d/%m/%Y")
        return True
    except ValueError:
        return False


def check(field, value):
    f = field.lower()
    v = value
    if not v:
        return False, "no value extracted"
    if "date" in f or f == "valid till":
        return (True, "valid date") if _valid_date(v) else (False, "not a valid DD/MM/YYYY date")
    if f == "aadhaar number":
        if not re.fullmatch(r"\d{12}", v):
            return False, "must be 12 digits"
        if not verhoeff_ok(v):
            return False, "12 digits but Verhoeff check digit fails (number cannot be a real Aadhaar)"
        return True, "12 digits, Verhoeff checksum OK"
    if f in {"pan number", "tin / pan"}:
        return (True, "matches PAN format AAAAA9999A") if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", v) \
            else (False, "does not match PAN format AAAAA9999A")
    if f == "ifsc code":
        return (True, "matches IFSC format AAAA0XXXXXX") if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v) \
            else (False, "does not match IFSC format AAAA0XXXXXX")
    if f == "bank account number":
        return (True, "9-18 digits") if re.fullmatch(r"\d{9,18}", v) else (False, "must be 9-18 digits")
    if f == "passport number":
        return (True, "matches A9999999") if re.fullmatch(r"[A-Z]\d{7}", v) else (False, "expected letter + 7 digits")
    if f == "dl number":
        compact = v.replace(" ", "").replace("-", "")
        return (True, "matches SS99 YYYY NNNNNNN") if re.fullmatch(r"[A-Z]{2}\d{13}", compact) \
            else (False, "does not match Indian DL format (2 letters + 13 digits)")
    if f == "mrz line 2":
        problems = mrz_line2_problems(v)
        return (True, "all ICAO check digits OK") if not problems else (False, "; ".join(problems))
    if f in {"application number", "policy number"}:
        return (True, "digits only") if re.fullmatch(r"\d{8,16}", v) else (False, "expected 8-16 digits")
    if f == "amount (figures)":
        return (True, "numeric") if re.fullmatch(r"\d+", v) else (False, "not numeric")
    return None, "no format rule"
