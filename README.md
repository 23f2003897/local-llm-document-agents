# Data Science Internship - First Round Evaluation

Solutions to the three assignment questions. **Everything runs locally and for free.** Models are served by
[Ollama](https://ollama.com); no paid API keys are needed.

**For a quick review, open [`evaluation.ipynb`](evaluation.ipynb).** It runs all three solutions and its outputs
are saved inline.

| | Question | Solution | Key outputs |
|---|---|---|---|
| Q1 | Agent that answers questions about an Excel dataset | [`q1_excel_agent/`](q1_excel_agent) | Streamlit chat app; demo in notebook |
| Q2 | Document-aware support assistant with multi-turn memory | [`q2_support_bot/`](q2_support_bot) | Streamlit chat app; [12-turn demo transcript](q2_support_bot/demo_transcript.md) |
| Q3 | Classify, extract and flag 10+ identity/insurance documents | [`q3_doc_pipeline/`](q3_doc_pipeline) | [JSON per document](q3_doc_pipeline/outputs), [flag report](q3_doc_pipeline/outputs/flag_report.md), [handwriting notes](q3_doc_pipeline/handwriting_notes.md) |

## Models used (all local, via Ollama)
| Model | Size | Used for |
|---|---|---|
| `qwen3:8b` | 5.2 GB | Q1 agent (tool calling), Q2 chat |
| `qwen2.5vl:7b` | 6.0 GB | Q3 document reading (printed and handwritten); Q2 draft transcription of the forms |
| `nomic-embed-text` | 0.3 GB | Q2 embeddings for retrieval |

Tested on an Apple M5 laptop with 16 GB RAM.

## Setup
```bash
# 1. Install Ollama (https://ollama.com/download), start it, then pull the models
ollama pull qwen3:8b
ollama pull qwen2.5vl:7b
ollama pull nomic-embed-text

# 2. Python 3.10+ environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## How to run
```bash
# Q1 - Excel agent (chat UI)
streamlit run q1_excel_agent/app.py
python q1_excel_agent/agent.py          # same agent in the terminal

# Q2 - Support assistant
python q2_support_bot/ingest.py         # build the vector index from kb/*.md (seconds)
streamlit run q2_support_bot/app.py     # chat UI
python q2_support_bot/demo.py           # regenerate the 12-turn demo transcript

# Q3 - Document pipeline (about 4 minutes for all 12 files)
python q3_doc_pipeline/run.py           # writes q3_doc_pipeline/outputs/

# Everything, end to end
jupyter notebook evaluation.ipynb
```

---

## Q1 - Excel data agent
**Goal:** answer questions about `Inventory-Records-Sample-Data.xlsx` (46 products) in a chat interface.

**Design.** `qwen3:8b` runs a tool-calling loop with two tools:
- **`run_python(code)`** executes Python with the sheet preloaded as a pandas DataFrame `df`. The sheet has a
  title block above the table, so the loader finds the header row automatically and cleans the column names.
- **`web_search(query)`** runs a DuckDuckGo search (free, no key) for definitions and business context.

The system prompt includes the schema and requires the model to:
- compute every number with code, never by mental arithmetic;
- state only values that appear in the tool output;
- fix and retry its code on errors;
- finish with a 2-5 sentence plain-English summary.

The Streamlit UI shows the code the agent ran under each answer, so every result can be checked.

**What we learned while testing (8-question regression run, answers checked against pandas).** Early versions
made up IDs and numbers. Each cause had its own fix:
| Cause | Fix |
|---|---|
| Code selected only product names, so no IDs were printed | Prompt requires printing Product ID + Product Name. (Indexing by Product ID was tried first, but it broke pandas alignment in the model's own code.) |
| Pandas truncated wide tables with "...", hiding values | The tool prints full tables |
| The model sometimes answered without running code, or only searched the web for a two-part question and guessed the data part | Code bounces any answer with no tool call, or one that quotes data values without running code that turn |
| The model read answers off long printouts and missed rows | Prompt rule to filter in code; tool outputs longer than 25 lines come back with a note to filter instead |
| Ties for highest/lowest were missed | Prompt rule to check for ties |
| Ollama's default 4k context overflowed | Context raised to 12k tokens; only the last 2 exchanges are sent |
| General reliability | Rule to state only values the tool printed; qwen3's reasoning mode | The agent also discovered that *Opening Stock + Purchases - Units Sold != Hand-In-Stock* for 12
products, a data-quality issue in the sample sheet.

## Q2 - Support assistant over the HDFC Life forms
**Knowledge base ("own documents"):** the eight HDFC Life onboarding forms supplied with Q3 (proposal declaration,
assignment form, NACH mandate, FATCA annexure, benefit illustration, moral hazard questionnaire, multiple-policy
consent, suitability profiler).
- They are scans, so `ingest.py --transcribe` drafts a Markdown transcription of each page with the local
  vision model.
- The drafts were then **reviewed and corrected against the scans** ([`kb/`](q2_support_bot/kb)). The 7B model
  duplicated text where page strips overlap and, on blank parts of pages, invented content such as a
  fictitious "John Doe" policy. A support assistant must never cite invented text, so only reviewed files are
  indexed.
- Each file is split by its section headings into 63 sections and stored in Chroma with a section path such as
  `NACH Mandate > Declaration - Clauses 7 to 12`.

**How each turn is handled (`bot.py`):**
| Requirement | How it is handled |
|---|---|
| Remember what was asked | Full chat history goes to the model. A *standalone query* step rewrites "can I cancel **it**?" into "can I cancel the NACH mandate?" before searching. |
| Avoid repeating information | An "already told" ledger (a one-line note per cited section). When a retrieved section was already used, the turn says so explicitly and the model must say "As I mentioned earlier" with a one-line recap instead of re-explaining. |
| Handle topic switches | The query rewrite searches only for the new topic, and the prompt tells the model not to carry details over from the old one. |
| Questions about the chat itself | "What have we discussed?" is answered from the session ledger, not from a document search, so it cannot list forms that never came up. |
| Cite the section in every answer | The model cites retrieved sources by ID (`S1`, `S2`); code maps the IDs to exact section paths, so a citation can never be a misspelled or invented section name. |

See the [12-turn demo transcript](q2_support_bot/demo_transcript.md). It covers follow-ups, four topic switches,
a repeated question, a back-reference to an earlier topic, and a memory question.

## Q3 - Document pipeline
**Input:** 12 files: Aadhaar, PAN, driving licence, passport, NACH mandate, FATCA annexure, four handwritten
declarations, plus two PDFs (proposal form, assignment form) that are not among the 10 listed types.

**Pipeline (`run.py`):**
1. **Classify** with two independent signals: keyword rules on the printed titles and labels, and the vision
   model's own choice. Agreement gives confidence 0.99. Documents of an unlisted type are labelled
   `Other / Unknown` and routed to human review as a whole.
2. **Extract.** Printed cards get 2 reads. Handwritten forms get 3 reads: full page, a 2x zoom of the filled-in
   region, and that zoom read character by character.
3. **Score every field:**
   - agreement across reads;
   - format and checksum rules (PAN, IFSC, Aadhaar Verhoeff, DL pattern, passport MRZ ICAO check digits, valid dates);
   - a 0.95 factor for handwriting;
   - **cross-document consistency** (application number, name, DOB, PAN, signing date and place must match across
     the customer's documents). This also repairs a misread when an alternative read, or a 1-character variant,
     matches the consensus; the repaired field stays flagged.
4. **Flag** every field below **0.80**. The threshold and its rationale are in the flag report.

**Deliverables:**
- [one JSON per document](q3_doc_pipeline/outputs) with value, confidence, source (printed/handwritten), number
  of agreeing reads, rule result and alternative readings for every field;
- [`all_results.json`](q3_doc_pipeline/outputs/all_results.json);
- [`flag_report.md`](q3_doc_pipeline/outputs/flag_report.md) with the threshold, rationale, flagged fields and
  cross-document issues;
- [`handwriting_notes.md`](q3_doc_pipeline/handwriting_notes.md) on the printed vs handwritten approach and the
  failure cases observed.

**Things the pipeline caught:**
- The passport's MRZ line has wrong date-of-birth and expiry check digits.
- The Aadhaar number fails its Verhoeff checksum (it is a sample card).
- The PAN on the PAN card (`ABCDE1234F`) differs from the TIN written on the FATCA form (`BPQPD3051R`).

## Repository layout
```
evaluation.ipynb            notebook that runs and shows all three solutions
data/q1, data/q3            the provided input files (unchanged)
q1_excel_agent/             agent.py (tools + loop), app.py (Streamlit)
q2_support_bot/             ingest.py, bot.py, app.py, demo.py, kb/ (reviewed form transcriptions), demo_transcript.md
q3_doc_pipeline/            config.py (types, fields, regions), vision.py, validate.py, pipeline.py, run.py,
                            handwriting_notes.md, outputs/
```

## Limitations
- Local 7-8B models are much weaker than frontier models. The design makes up for this with code execution
  (Q1), retrieval with ID-based citations (Q2), and multiple reads, validators and cross-document checks (Q3).
  Answers can still occasionally be imprecise, so Q1 shows its code and Q3 flags uncertain fields.
- Q1 can still miss a tie in a highest/lowest question despite the tie rule. In testing it reported P101 as the
  highest total cost without mentioning that P105 is tied at $72,000.
- Q1 executes model-written Python in-process, without a sandbox. That is fine for a local demo on a read-only copy of the
  data, but a production version would run code in an isolated sandbox.
- The Q3 zoom regions are tuned to these HDFC form layouts; a new form layout needs its region set in `config.py`.
- Run times on a 16 GB laptop: Q1 about 20-60 s per question with reasoning on; Q2 about 1 minute per turn;
  Q3 about 4 minutes for all 12 documents.
