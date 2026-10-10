"""Document-aware support assistant over the HDFC Life forms.

Per user turn:
  1. Rewrite the question into a standalone search query using recent turns (handles "what about that one?"
     and notices topic switches).
  2. Retrieve the most relevant form sections from Chroma.
  3. Answer with the chat history, the retrieved sections and a ledger of what has already been told,
     citing the section used.
  4. Update the ledger (which sections were cited, and a one-line note of what was said).
"""
import re
from pathlib import Path

import chromadb
import ollama

ROOT = Path(__file__).resolve().parent
CHAT_MODEL = "qwen3:8b"
EMBED_MODEL = "nomic-embed-text"
DB_DIR = ROOT / ".chroma"
COLLECTION = "hdfc_forms"
TOP_K = 4
NUM_CTX = 12288  # Ollama defaults to 4096 tokens, too small for history + 4 retrieved sections

SYSTEM_PROMPT = """You are a customer-support assistant for HDFC Life insurance onboarding forms.
Answer ONLY from the SOURCES provided in each turn. Each source has an ID like [S1] and a section path.

Rules:
- End every answer with ONE tag listing the IDs of the sources you actually used, exactly like: (Source: S2) or
  (Source: S1, S3). Put it at the very end. Never mention S-IDs anywhere else in the answer text.
- MEMORY: You can see the whole conversation. If the user refers to something earlier ("that form", "the
  first thing you told me"), resolve it from the conversation.
- NO REPETITION: The ALREADY TOLD list shows what you have already explained. If the user asks about one of
  those points again, start with "As I mentioned earlier," give a one-sentence recap, and add only information
  that was not given before. Never repeat a full earlier explanation.
- TOPIC SWITCH: If the question is about a different form or topic than the previous turn, answer the new
  question directly (you may note the switch in a few words). Do not carry over details from the old topic.
- Only state what the sources say. Do not add consequences, steps or details that are not written in them.
  If the sources do not contain the answer, say you could not find it in the documents.
- Keep answers short: 2-5 sentences.
"""

REWRITE_PROMPT = """Rewrite the user's latest message as a standalone search query for an insurance-forms knowledge
base, resolving pronouns and references using the conversation. Output only the query.
If the message is about the conversation itself (e.g. "what have we discussed?", "summarise our chat"),
output exactly: CONVERSATION

Conversation so far:
{history}

Latest message: {question}
Standalone query:"""


class SupportBot:
    def __init__(self):
        client = chromadb.PersistentClient(path=str(DB_DIR))
        self.col = client.get_collection(COLLECTION)
        self.history = []          # what the model sees: [{'role','content'}], answers without the source line
        self.transcript = []       # what the user sees: same turns, answers with their sources
        self.told = []             # ledger: [{'section', 'note'}]

    # ---------- helpers ----------
    def _llm(self, messages, think=False):
        r = ollama.chat(model=CHAT_MODEL, messages=messages, think=think, options={"temperature": 0, "num_ctx": NUM_CTX})
        return r["message"]["content"].strip()

    def _standalone_query(self, question):
        if not self.history:
            return question
        recent = "\n".join(f"{m['role']}: {m['content']}" for m in self.history[-6:])
        q = self._llm([{"role": "user", "content": REWRITE_PROMPT.format(history=recent, question=question)}])
        return q.strip().strip('"') or question

    def _retrieve(self, query):
        emb = ollama.embed(model=EMBED_MODEL, input=["search_query: " + query])["embeddings"]
        res = self.col.query(query_embeddings=emb, n_results=TOP_K)
        return [{"section": m["section"], "text": d} for m, d in zip(res["metadatas"][0], res["documents"][0])]

    def _ledger_text(self):
        if not self.told:
            return "(nothing yet)"
        return "\n".join(f"- {t['note']} (from {t['section']})" for t in self.told)

    _SOURCE_TAG = re.compile(r"\(Sources?:?\s*((?:[^()]|\([^()]*\))*)\)")

    @classmethod
    def _resolve_citations(cls, answer, sources):
        """Split the model's "(Source: S1, S3)" markers off the answer and map them to exact section paths.

        Citing by ID and expanding in code guarantees the cited section names match the documents exactly.
        Returns (answer_without_markers, cited_paths).
        """
        cited = []
        for group in cls._SOURCE_TAG.findall(answer):
            for n in re.findall(r"S(\d+)", group):
                i = int(n) - 1
                if 0 <= i < len(sources) and sources[i]["section"] not in cited:
                    cited.append(sources[i]["section"])
        answer = cls._SOURCE_TAG.sub("", answer)
        answer = re.sub(r"\s*\[S\d+(?:\s*,\s*S\d+)*\]", "", answer)
        answer = re.sub(r"\s*\((?:see |from |as per )?S\d+(?:\s*,\s*S\d+)*\)", "", answer)
        answer = re.sub(r"\s+(?:of|in|from) S\d+\b", "", answer)
        answer = re.sub(r"[ \t]+([.,;])", r"\1", re.sub(r"[ \t]{2,}", " ", answer)).strip()
        if not cited and "could not find" not in answer.lower():
            cited = [sources[0]["section"]]  # the model must cite; if it forgot, use the top source it was given
        return answer, cited

    # ---------- main entry ----------
    def ask(self, question):
        query = self._standalone_query(question)
        if query.strip().upper().startswith("CONVERSATION") and self.told:
            # Questions about the chat itself are answered from session memory, not from a document search:
            # the "sources" are the sections already cited, with the note of what was said from each.
            sections = list(dict.fromkeys(t["section"] for t in self.told))
            sources = [{"section": sec, "text": " / ".join(t["note"] for t in self.told if t["section"] == sec)}
                       for sec in sections]
        else:
            sources = self._retrieve(query)
        src_text = "\n\n".join(f"[S{i}] Section: {s['section']}\n{s['text']}" for i, s in enumerate(sources, 1))
        # Deterministic repeat signal: tell the model which retrieved sections it already used in this session.
        told_sections = {t["section"] for t in self.told}
        reused = [f"S{i}" for i, s in enumerate(sources, 1) if s["section"] in told_sections]
        repeat_note = (f"\nNOTE: {', '.join(reused)} were already used to answer earlier in this conversation. "
                       "If this question asks for the same information again, follow the NO REPETITION rule."
                       if reused else "")
        turn_context = (f"SOURCES:\n{src_text}\n\nALREADY TOLD:\n{self._ledger_text()}{repeat_note}\n\n"
                        f"USER QUESTION: {question}")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history + \
                   [{"role": "user", "content": turn_context}]
        body, cited = self._resolve_citations(self._llm(messages, think=True), sources)
        answer = body + ("\n(Source: " + "; ".join(cited) + ")" if cited else "")

        note = self._llm([{"role": "user", "content":
                           f"In at most 15 words, state the key fact this answer gave:\n{body}"}])
        for c in cited:
            self.told.append({"section": c, "note": note})

        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": body}]
        self.transcript += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        return {"answer": answer, "query": query, "cited": cited, "retrieved": [s["section"] for s in sources]}

    def reset(self):
        self.history, self.transcript, self.told = [], [], []
