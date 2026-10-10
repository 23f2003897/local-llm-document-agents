"""Run the full pipeline on every document in a folder.

Usage:  python run.py [input_dir] [output_dir]
Writes one JSON per document, all_results.json and flag_report.md into output_dir.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import CONFIDENCE_THRESHOLD, OTHER  # noqa: E402
from pipeline import add_flags, cross_document_checks, process, save  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXTS = {".png", ".jpg", ".jpeg", ".pdf"}

RATIONALE = f"""**Threshold: {CONFIDENCE_THRESHOLD:.2f}**

Why 0.80:
- A field only clears 0.80 when **every independent read agrees** (3/3 for handwritten forms, 2/2 for printed
  cards) **and** the value does not fail its format/checksum rule. A single dissenting read drops a handwritten
  field to about 0.68 and sends it to review.
- In insurance onboarding the costs are lopsided: a wrong account number, IFSC or PAN means a failed debit,
  a KYC rejection or a compliance issue, while a human check costs seconds. So the threshold is set to catch
  every field with *any* disagreement, accepting some false alarms.
- Going higher (e.g. 0.95) would flag every handwritten field (they are capped at 0.95 by design) and make the
  report useless; going lower (e.g. 0.60) would let 2-of-3 majority votes through, which is exactly where
  misread digits hide.
"""


def write_report(results, issues, out_dir):
    lines = ["# Q3 Flagging Report", "", RATIONALE, "## How a confidence score is computed", "",
             "Per field: `share of reads that agree` +0.05 if it passes its format/checksum rule, capped at 0.50 if it "
             "fails, x0.95 if handwritten. Then a cross-document step compares values that must match across the "
             "customer's documents (application number, name, DOB, PAN, signing date/place): +0.05 when it agrees "
             "with the consensus; if it disagrees but an alternative read or a 1-character variant matches, the "
             "value is corrected and capped at 0.75/0.70 (so it is still reviewed); otherwise capped at 0.60.", "",
             "## Summary", "", "| File | Type | Fields | Flagged |", "|---|---|---|---|"]
    for r in results:
        n = len(r.get("fields", {}))
        flagged = len(r["flags"])
        lines.append(f"| {r['file']} | {r['document_type']} | {n} | {flagged} |")

    lines += ["", f"## Fields below threshold ({CONFIDENCE_THRESHOLD:.2f})", "",
              "| File | Field | Value | Confidence | Why |", "|---|---|---|---|---|"]
    for r in results:
        for fl in r["flags"]:
            if r["document_type"] == OTHER:
                continue
            lines.append(f"| {r['file']} | {fl['field']} | `{fl.get('value')}` | {fl.get('confidence')} | {fl['reason']} |")

    lines += ["", "## Documents routed to human review as a whole", ""]
    for r in results:
        if r["document_type"] == OTHER:
            lines.append(f"- **{r['file']}**: {r['flags'][0]['reason']} ({r['classification_reason']})")

    lines += ["", "## Cross-document consistency issues", ""]
    if issues:
        for i in issues:
            lines.append(f"- **{i['group']}**: `{i['value']}` in {i['file']} ({i['field']}) vs {i['others']} elsewhere")
    else:
        lines.append("- None found.")
    (out_dir / "flag_report.md").write_text("\n".join(lines) + "\n")


def main():
    in_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "q3"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "outputs"
    files = sorted(p for p in in_dir.iterdir() if p.suffix.lower() in EXTS)
    results = []
    for p in files:
        t = time.time()
        r = process(p)
        print(f"{p.name:48s} -> {r['document_type']:34s} ({time.time() - t:.0f}s)", flush=True)
        results.append(r)

    issues = cross_document_checks(results)
    for r in results:
        add_flags(r)
        save(r, out_dir)
    (out_dir / "all_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    write_report(results, issues, out_dir)
    print(f"\nWrote {len(results)} JSON files and flag_report.md to {out_dir}")


if __name__ == "__main__":
    main()
