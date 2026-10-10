"""Classify -> extract -> score -> flag, for one document at a time, plus cross-document checks."""
import json
import re
from collections import Counter
from pathlib import Path

import vision
from config import CONFIDENCE_THRESHOLD, DOC_TYPES, OTHER
from validate import check, compare_key, normalise

# ---------------- classification ----------------

TITLE_PROMPT = ("Transcribe the printed titles, headings, logos' text and field labels of this document, "
                "exactly as written (not the filled-in values, not long paragraphs). Plain text only.")


def classify(page):
    """Two independent signals: keyword rules on the printed titles/labels, and the vision model's own choice."""
    header_text = vision.ask(page, TITLE_PROMPT).lower()

    rule_type = None
    best_hits = 0
    for name, spec in DOC_TYPES.items():
        hits = sum(kw in header_text for kw in spec["keywords"])
        if hits > best_hits:
            rule_type, best_hits = name, hits

    options = list(DOC_TYPES) + [OTHER]
    choice_prompt = (
        "Which ONE of these document types is this image? Answer with the exact type name only.\n- "
        + "\n- ".join(options)
        + f"\nIf it is an insurance form that is not listed (e.g. a proposal form or assignment form), answer '{OTHER}'."
    )
    reply = vision.ask(page, choice_prompt).strip().lower()
    model_type = next((o for o in options if o.lower() in reply), OTHER)

    if rule_type and rule_type == model_type:
        return rule_type, 0.99, f"keyword rule and vision model agree ({best_hits} keyword hit(s))"
    if rule_type and model_type == OTHER:
        return rule_type, 0.85, f"keyword rule only ({best_hits} hit(s)); vision model said '{OTHER}'"
    if rule_type:
        return rule_type, 0.6, f"keyword rule says '{rule_type}', vision model says '{model_type}'"
    if model_type != OTHER:
        return model_type, 0.6, "vision model only; no keyword in header matched"
    return OTHER, 0.9, "no known type matched by either keyword rule or vision model"


# ---------------- extraction ----------------

def _field_block(spec):
    return "\n".join(f'- "{f}": {hint}' for f, hint in spec["fields"].items())


def _prompt_standard(doc_type, spec):
    kind = "handwritten" if spec["handwritten"] else "printed"
    return (f"This is an Indian '{doc_type}' with {kind} entries. Extract these fields and return ONLY a JSON object "
            f"with exactly these keys:\n{_field_block(spec)}\n"
            "Copy values exactly as they appear. Use null if a field is empty or not visible.")


def _prompt_careful(doc_type, spec):
    return (f"Look closely at this '{doc_type}'. For each field below, find its label, then read the value next to it "
            "character by character (watch for 1 vs 7, 0 vs O, 5 vs S, 2 vs Z, 8 vs B). "
            f"Return ONLY a JSON object with exactly these keys:\n{_field_block(spec)}\n"
            "Use null for anything empty or illegible.")


def _reads(page, doc_type, spec):
    """Independent reads of the same document. Handwritten forms get three, printed cards get two."""
    zoomed = vision.crop(page, spec["region"], scale=2)
    if spec["handwritten"]:
        plan = [("full page", page, _prompt_standard),
                ("zoomed region", zoomed, _prompt_standard),
                ("zoomed region, char-by-char", zoomed, _prompt_careful)]
    else:
        plan = [("full page", page, _prompt_standard),
                ("full page, char-by-char", page, _prompt_careful)]
    reads = []
    for label, img, make_prompt in plan:
        raw = vision.ask_json(img, make_prompt(doc_type, spec))
        lowered = {re.sub(r"\W", "", k.lower()): v for k, v in raw.items()}
        values = {}
        for f in spec["fields"]:
            values[f] = normalise(f, raw.get(f, lowered.get(re.sub(r"\W", "", f.lower()))))
        reads.append({"read": label, "values": values})
    return reads


# ---------------- scoring ----------------

def score_field(field, candidates, handwritten):
    """Majority vote across reads, then adjust by format/checksum rules.

    confidence = share of reads agreeing with the chosen value
                 +0.05 if the value passes its format/checksum rule
                 capped at 0.50 if it fails the rule
                 x0.95 for handwritten fields (residual risk the reads share the same mistake)
    """
    keyed = [(compare_key(field, c), c) for c in candidates]
    non_empty = [k for k, _ in keyed if k]
    if not non_empty:
        return {"value": None, "confidence": 0.0, "agreement": f"0/{len(candidates)}",
                "rule": "no value extracted", "source": "handwritten" if handwritten else "printed"}
    winner, votes = Counter(non_empty).most_common(1)[0]
    value = next(c for k, c in keyed if k == winner)
    conf = votes / len(candidates)
    ok, note = check(field, value)
    if ok is True:
        conf = min(1.0, conf + 0.05)
    elif ok is False:
        conf = min(conf, 0.5)
    if handwritten:
        conf *= 0.95
    tally = Counter(c for k, c in keyed if k)
    return {"value": value, "confidence": round(conf, 2), "agreement": f"{votes}/{len(candidates)}",
            "rule": note, "source": "handwritten" if handwritten else "printed",
            "alternatives": sorted({c for k, c in keyed if k and k != winner}), "reads": dict(tally)}


def process(path):
    path = Path(path)
    pages = vision.load_pages(path)
    doc_type, type_conf, type_reason = classify(pages[0])
    result = {"file": path.name, "document_type": doc_type, "classification_confidence": type_conf,
              "classification_reason": type_reason, "pages": len(pages), "fields": {}, "reads": []}
    if doc_type == OTHER:
        result["flags"] = [{"field": "(document)", "reason": "Document type is not one of the 10 expected types; "
                                                           "no extraction schema - route to human review."}]
        return result
    spec = DOC_TYPES[doc_type]
    reads = _reads(pages[0], doc_type, spec)
    result["reads"] = reads
    for f in spec["fields"]:
        result["fields"][f] = score_field(f, [r["values"][f] for r in reads], spec["handwritten"])
    return result


# ---------------- cross-document consistency ----------------

def _person_key(name):
    n = re.sub(r"^(mr|mrs|ms|miss|shri|smt)\.?\s+", "", str(name).strip(), flags=re.I)
    return re.sub(r"[^a-z]", "", n.lower())


CROSS_GROUPS = {
    "application / policy number": (["Application Number", "Policy Number"], lambda v: re.sub(r"\D", "", v)),
    "customer name": (["Full Name", "Name", "Policyholder Name", "Name of Life Assured", "Proposer Name"], _person_key),
    "date of birth": (["Date of Birth"], str),
    "PAN": (["PAN Number", "TIN / PAN"], str),
    "signing place": (["Place"], lambda v: re.sub(r"[^a-z]", "", v.lower())),
    "signing date": (["Date"], str),
}


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cross_document_checks(results):
    """Use values that should be identical across documents (same customer, same application) to check and
    repair individual reads.

    Consensus = a value read with high confidence on at least two documents. For every other document:
      - agrees with consensus             -> +0.05 confidence
      - one of its alternative reads matches consensus -> switch to it, confidence capped at 0.75 (stays flagged)
      - a read is 1 character away from consensus      -> switch to consensus, capped at 0.70 (stays flagged)
      - otherwise                          -> conflict: confidence capped at 0.60 (handwritten side, or every side
                                              when there is no consensus at all)
    """
    issues = []
    for group, (fields, key) in CROSS_GROUPS.items():
        entries = [(r, f, r["fields"][f]) for r in results for f in fields
                   if f in r.get("fields", {}) and r["fields"][f]["value"]]
        if len(entries) < 2:
            continue
        strong = Counter(key(i["value"]) for _, _, i in entries if i["confidence"] >= CONFIDENCE_THRESHOLD)
        consensus = next((k for k, n in strong.most_common(1) if n >= 2), None)
        for r, f, info in entries:
            if consensus is None:
                info["cross_check"] = f"CONFLICT ({group}): documents disagree and no value is confirmed by two documents"
                info["confidence"] = round(min(info["confidence"], 0.6), 2)
                issues.append({"group": group, "file": r["file"], "field": f, "value": info["value"],
                               "others": sorted({i["value"] for _, _, i in entries if i is not info})})
                continue
            agreed = sorted({i["value"] for _, _, i in entries if key(i["value"]) == consensus})
            if key(info["value"]) == consensus:
                info["confidence"] = round(min(1.0, info["confidence"] + 0.05), 2)
                info["cross_check"] = f"agrees with other documents ({group})"
                continue
            candidates = [info["value"]] + info.get("alternatives", [])
            alt = next((c for c in candidates if key(c) == consensus), None)
            near = next((c for c in candidates if _edit_distance(key(c), consensus) == 1), None)
            if alt or near:
                chosen = alt or agreed[0]
                if alt:
                    info["cross_check"] = (f"RECONCILED ({group}): reads disagreed; chose '{alt}' over "
                                           f"'{info['value']}' because other documents say {agreed}")
                else:
                    info["cross_check"] = (f"RECONCILED ({group}): read '{near}' is 1 character from {agreed} on "
                                           f"other documents; corrected - verify")
                n_reads = sum(info["reads"].values())
                info["agreement"] = f"{info['reads'].get(chosen, 0)}/{n_reads}"
                info["alternatives"] = sorted(v for v in info["reads"] if key(v) != consensus)
                info["value"] = chosen
                info["confidence"] = round(min(info["confidence"], 0.75 if alt else 0.7), 2)
            else:
                info["cross_check"] = f"CONFLICT ({group}): other documents say {agreed}"
                if info["source"] == "handwritten":
                    info["confidence"] = round(min(info["confidence"], 0.6), 2)
                issues.append({"group": group, "file": r["file"], "field": f,
                               "value": info["value"], "others": agreed})
    return issues


def add_flags(result):
    flags = result.setdefault("flags", [])
    if result["document_type"] != OTHER and result["classification_confidence"] < CONFIDENCE_THRESHOLD:
        flags.append({"field": "(document type)", "confidence": result["classification_confidence"],
                      "reason": result["classification_reason"]})
    for f, info in result.get("fields", {}).items():
        if info["confidence"] < CONFIDENCE_THRESHOLD:
            reasons = [f"reads agreed {info['agreement']}"]
            if info.get("alternatives"):
                reasons.append(f"other readings: {info['alternatives']}")
            reasons.append(f"rule: {info['rule']}")
            if info.get("cross_check", "").startswith(("CONFLICT", "RECONCILED")):
                reasons.append(info["cross_check"])
            flags.append({"field": f, "value": info["value"], "confidence": info["confidence"],
                          "reason": "; ".join(reasons)})
    result["needs_human_review"] = bool(flags)
    return result


def save(result, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9]+", "_", Path(result["file"]).stem).strip("_") + ".json"
    (out_dir / name).write_text(json.dumps(result, indent=2, ensure_ascii=False))
