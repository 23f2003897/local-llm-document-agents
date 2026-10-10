# Handwritten vs printed text: approach and observed failures

All extraction runs locally with a 7B vision-language model (`qwen2.5vl:7b` via Ollama). Plain OCR engines
such as Tesseract do badly on cursive and boxed handwriting, so a VLM reads both kinds of text.
The difference is in how many times we read, where we look, and how much we trust the result.

## Printed documents (Aadhaar, PAN, Driving Licence, Passport)
- **2 reads** of the full card with two prompt styles: a plain "extract these fields" prompt and a
  "character-by-character" prompt.
- Clean printed text almost always gives 2/2 agreement, so the deciding signal is **format and checksum rules**:
  - PAN must match `AAAAA9999A`.
  - The Aadhaar number must pass its Verhoeff check digit.
  - The DL number must match the state/RTO/year/serial pattern.
  - The passport MRZ line 2 must pass all ICAO 9303 check digits.
- Printed fields are not discounted for handwriting risk.

## Handwritten forms (NACH, FATCA and the four HDFC declarations)
1. **Zoom on the filled-in region.** Each form type has a fixed layout. The pipeline crops the band of the page
   holding the handwritten entries and upscales it 2x. This was the biggest single accuracy gain: in an
   early run, a crop that stopped just short of the Moral Hazard date line produced dates like `01/01/2026`.
2. **3 independent reads:** the full page, the zoomed region, and the zoomed region with a character-by-character
   prompt. That prompt warns about the usual confusions (1/7, 0/O, 5/S, 2/Z, 8/B).
3. **Field-level majority vote.** Confidence starts as the share of reads that agree. Handwritten fields are
   multiplied by 0.95, because three reads by the same model can share the same mistake.
4. **Format rules** (IFSC `AAAA0XXXXXX`, PAN-format TIN, 9-18 digit account number, valid dates).
5. **Cross-document reconciliation.** The same customer fills in all the forms, so the application number, name,
   signing date and place should match across forms. A value confirmed with high confidence on two or more
   documents is the consensus. A disagreeing read is corrected to it only when one of its alternative reads
   matches, or when it is one character away. A corrected value is capped at 0.70-0.75, so it **stays in the
   review queue**. The correction speeds up the reviewer; it doesn't replace them.

## Failure cases observed
| Document | Field | What went wrong | Outcome |
|---|---|---|---|
| Benefit Illustration | Application Number | Zoomed reads gave `1500137601005` (2 read as 0) and the full-page read gave `1500137401025` (6 read as 4). No two reads gave the true value. | Corrected to `1500137601025` by cross-document consensus (1 character away), flagged at 0.68 |
| Benefit Illustration | Place | Two reads gave `West Biba` (cursive "har" read as "ba") | Third read `West Bihar` chosen via consensus, flagged at 0.63 |
| Benefit Illustration | Date | Full-page read gave `06/04/2026`; the overwritten "26" is messy | Majority `26/04/2026`, flagged at 0.73 |
| Moral Hazard | Date | One read gave `26/04/2006` (handwritten 2 read as 0) | Majority `26/04/2026`, flagged at 0.73 |
| Suitability Profiler | Application Number | One read gave `1500131601025` (7 read as 1) | Majority correct, flagged at 0.73 |
| Driving Licence (printed) | Name | First version appended the "S/W/D of" value (`MR. ASHOK KUMAR`) | Fixed by making the field instruction explicit |

## Flags that are not reading errors
Each of these was read correctly but still needs a human:
- **Aadhaar number `1234 5678 9012`** fails the Verhoeff checksum, so it cannot be a genuine Aadhaar number.
  The card is labelled as a sample.
- **Passport MRZ line 2**: the date-of-birth and expiry check digits printed on the card are wrong
  (5 should be 2, 0 should be 9). A document like this would be rejected in production.
- **PAN vs TIN**: the PAN card says `ABCDE1234F`, while the TIN handwritten on the FATCA form is `BPQPD3051R`.
  For an Indian resident the TIN is the PAN, so one of the two is wrong. Neither value is confirmed by a second
  document, so both are flagged.
- **Father's name** (noted by hand, not compared automatically): the PAN card says `KUMAR`, the FATCA form
  `Arjun Das Kumar`. The two are compatible, but the fuller FATCA version is the one to keep on file.

## Limits
- The fixed crop regions assume these HDFC form layouts. A new form version would need its region updated in
  `config.py`; the full-page read still works without it, just less accurately.
- A 7B local model is the weakest link on messy cursive. Agreement voting catches *disagreement*, not errors
  where all reads make the same mistake. Checksums and cross-document consistency cover that gap for
  identifiers but not for free text such as names and places.
