# Q3 Flagging Report

**Threshold: 0.80**

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

## How a confidence score is computed

Per field: `share of reads that agree` +0.05 if it passes its format/checksum rule, capped at 0.50 if it fails, x0.95 if handwritten. Then a cross-document step compares values that must match across the customer's documents (application number, name, DOB, PAN, signing date/place): +0.05 when it agrees with the consensus; if it disagrees but an alternative read or a 1-character variant matches, the value is corrected and capped at 0.75/0.70 (so it is still reviewed); otherwise capped at 0.60.

## Summary

| File | Type | Fields | Flagged |
|---|---|---|---|
| Aadhar.png | Aadhaar Card | 4 | 1 |
| Assignment Ashok.pdf | Other / Unknown | 0 | 1 |
| ChatGPT Image May 2, 2026, 03_43_11 PM.png | Driving Licence | 4 | 0 |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | Passport | 4 | 1 |
| ECS.jpeg | NACH / ECS Mandate | 5 | 0 |
| Fatca.jpeg | FATCA Annexure Form | 5 | 1 |
| ID.png | PAN Card | 4 | 1 |
| Illustration.jpeg | Benefit Illustration Declaration | 4 | 3 |
| Moral.jpeg | Moral Hazard Questionnaire | 5 | 1 |
| Proposal Ashok.pdf | Other / Unknown | 0 | 1 |
| split.jpeg | Multiple Policies Consent Form | 4 | 0 |
| suitability.jpeg | Suitability Profiler Declaration | 5 | 1 |

## Fields below threshold (0.80)

| File | Field | Value | Confidence | Why |
|---|---|---|---|---|
| Aadhar.png | Aadhaar Number | `123456789012` | 0.5 | reads agreed 2/2; rule: 12 digits but Verhoeff check digit fails (number cannot be a real Aadhaar) |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | MRZ Line 2 | `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<08` | 0.5 | reads agreed 2/2; rule: date of birth check digit is 5, computed 2; date of expiry check digit is 0, computed 9 |
| Fatca.jpeg | TIN / PAN | `BPQPD3051R` | 0.6 | reads agreed 3/3; rule: matches PAN format AAAAA9999A; CONFLICT (PAN): documents disagree and no value is confirmed by two documents |
| ID.png | PAN Number | `ABCDE1234F` | 0.6 | reads agreed 2/2; rule: matches PAN format AAAAA9999A; CONFLICT (PAN): documents disagree and no value is confirmed by two documents |
| Illustration.jpeg | Application Number | `1500137601025` | 0.68 | reads agreed 0/3; other readings: ['1500137401025', '1500137601005']; rule: digits only; RECONCILED (application / policy number): read '1500137601005' is 1 character from ['1500137601025'] on other documents; corrected - verify |
| Illustration.jpeg | Date | `26/04/2026` | 0.73 | reads agreed 2/3; other readings: ['06/04/2026']; rule: valid date |
| Illustration.jpeg | Place | `West Bihar` | 0.63 | reads agreed 1/3; other readings: ['West Biba']; rule: no format rule; RECONCILED (signing place): reads disagreed; chose 'West Bihar' over 'West Biba' because other documents say ['West Bihar'] |
| Moral.jpeg | Date | `26/04/2026` | 0.73 | reads agreed 2/3; other readings: ['26/04/2006']; rule: valid date |
| suitability.jpeg | Application Number | `1500137601025` | 0.73 | reads agreed 2/3; other readings: ['1500131601025']; rule: digits only |

## Documents routed to human review as a whole

- **Assignment Ashok.pdf**: Document type is not one of the 10 expected types; no extraction schema - route to human review. (no known type matched by either keyword rule or vision model)
- **Proposal Ashok.pdf**: Document type is not one of the 10 expected types; no extraction schema - route to human review. (no known type matched by either keyword rule or vision model)

## Cross-document consistency issues

- **PAN**: `BPQPD3051R` in Fatca.jpeg (TIN / PAN) vs ['ABCDE1234F'] elsewhere
- **PAN**: `ABCDE1234F` in ID.png (PAN Number) vs ['BPQPD3051R'] elsewhere
