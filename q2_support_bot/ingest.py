"""Build the knowledge base from the HDFC Life forms.

Step 1 (transcribe, optional): the forms are scans, so each page is cut into overlapping horizontal strips and the
        local vision model drafts a Markdown transcription of each strip. Output: kb/raw/<document>.md.
        The drafts were then reviewed against the scans and corrected by hand into kb/<document>.md: the 7B model
        duplicated text where strips overlap and, on blank parts of a page, invented content that is not on the
        form (e.g. a fictitious "John Doe" policy). A knowledge base must not contain invented text, so only the
        reviewed files are indexed.
Step 2 (index):  every Markdown file is split by heading into sections; each section is embedded and stored in
        a Chroma collection with its section path (e.g. "NACH Mandate > Declaration") for citations.

Usage:  python ingest.py            # index only (uses existing kb/*.md)
        python ingest.py --transcribe  # also regenerate the raw drafts in kb/raw/ (slow; does not touch kb/*.md)
"""
import re
import sys
from pathlib import Path

import chromadb
import ollama

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "q3_doc_pipeline"))
import vision  # noqa: E402  (reuse the image helpers from Q3)

DATA = ROOT.parent / "data" / "q3"
KB_DIR = ROOT / "kb"
RAW_DIR = KB_DIR / "raw"
DB_DIR = ROOT / ".chroma"
EMBED_MODEL = "nomic-embed-text"
COLLECTION = "hdfc_forms"

SOURCES = {
    "Proposal Form Declaration": "Proposal Ashok.pdf",
    "Policy Assignment Form": "Assignment Ashok.pdf",
    "NACH Mandate": "ECS.jpeg",
    "FATCA Annexure": "Fatca.jpeg",
    "Benefit Illustration Declaration": "Illustration.jpeg",
    "Moral Hazard Questionnaire": "Moral.jpeg",
    "Multiple Policies Consent": "split.jpeg",
    "Suitability Profiler Declaration": "suitability.jpeg",
}

STRIP_PROMPT = (
    "Transcribe ALL text in this part of an insurance form into Markdown. Rules: "
    "use '## ' for printed section headings (shaded bars or bold titles); keep clause numbers like 1., 2., i., ii.; "
    "for filled-in values write 'Label: value'; skip logos and signatures. "
    "Transcribe exactly - do not summarise and do not add anything that is not printed or written."
)


def _strips(page, n=4, overlap=0.04):
    step = 1 / n
    for i in range(n):
        top = max(0, i * step - overlap)
        bottom = min(1, (i + 1) * step + overlap)
        yield vision.crop(page, (0, top, 1, bottom), scale=1)


def transcribe():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for title, fname in SOURCES.items():
        pages = vision.load_pages(DATA / fname)
        parts = [f"# {title}\n", f"_Source file: {fname}_\n"]
        for p_no, page in enumerate(pages, 1):
            if len(pages) > 1:
                parts.append(f"\n<!-- page {p_no} -->\n")
            for strip in _strips(page):
                text = vision.ask(strip, STRIP_PROMPT, max_tokens=1200).strip()
                text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text)
                parts.append(text + "\n")
        out = RAW_DIR / (re.sub(r"\W+", "_", title).strip("_").lower() + ".md")
        out.write_text("\n".join(parts))
        print(f"transcribed {fname} -> {out.name}")


def split_sections(md_text, doc_title):
    """Split a Markdown document on headings. Returns [(section_path, text)]."""
    sections, current, buf = [], "Header", []
    for line in md_text.splitlines():
        m = re.match(r"^(#{2,4})\s+(.*)", line)
        if m:
            if "".join(buf).strip():
                sections.append((current, "\n".join(buf).strip()))
            current, buf = m.group(2).strip(" *:"), []
        elif not line.startswith("# ") and not line.startswith("<!--"):
            buf.append(line)
    if "".join(buf).strip():
        sections.append((current, "\n".join(buf).strip()))
    # Long sections are split at line breaks into ~1200-char parts so retrieval stays precise; each part keeps
    # its section path. The "Header" block before the first heading only holds the source-file line - skipped.
    out = []
    for name, text in sections:
        if name == "Header":
            continue
        chunks, cur = [], ""
        for line in text.splitlines():
            if cur and len(cur) + len(line) > 1200:
                chunks.append(cur.strip())
                cur = ""
            cur += line + "\n"
        chunks.append(cur.strip())
        for k, chunk in enumerate(chunks, 1):
            label = f"{doc_title} > {name}" + (f" (part {k})" if len(chunks) > 1 else "")
            out.append((label, chunk))
    return out


def embed(texts, prefix):
    return ollama.embed(model=EMBED_MODEL, input=[prefix + t for t in texts])["embeddings"]


def build_index():
    client = chromadb.PersistentClient(path=str(DB_DIR))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    ids, docs, metas = [], [], []
    for md in sorted(KB_DIR.glob("*.md")):
        text = md.read_text()
        title = re.search(r"^# (.+)$", text, re.M).group(1).strip()
        for i, (section, chunk) in enumerate(split_sections(text, title)):
            ids.append(f"{md.stem}-{i}")
            docs.append(chunk)
            metas.append({"section": section, "document": title, "file": md.name})
    col.add(ids=ids, documents=docs, metadatas=metas,
            embeddings=embed([f"{m['section']}\n{d}" for m, d in zip(metas, docs)], "search_document: "))
    print(f"indexed {len(ids)} sections from {len(list(KB_DIR.glob('*.md')))} documents")


if __name__ == "__main__":
    if "--transcribe" in sys.argv:
        transcribe()
    build_index()
