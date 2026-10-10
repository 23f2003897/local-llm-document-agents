"""Thin wrapper around the local vision model (Ollama) plus image helpers."""
import io
import json
import re

import pymupdf as fitz
import ollama
from PIL import Image

from config import VISION_MODEL


def load_pages(path):
    """Return a list of PIL images, one per page (PDFs are rendered at 150 dpi)."""
    if str(path).lower().endswith(".pdf"):
        doc = fitz.open(path)
        pages = []
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            pages.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        return pages
    return [Image.open(path).convert("RGB")]


def crop(img, box, scale=2):
    """Crop to a fractional box and upscale so small handwriting gets more pixels."""
    w, h = img.size
    region = img.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    if scale != 1:
        region = region.resize((region.width * scale, region.height * scale), Image.LANCZOS)
    return region


def _to_png(img, max_side=1600):
    if max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def ask(img, prompt, max_tokens=None):
    """Send one image + prompt to the vision model and return the raw text reply."""
    options = {"temperature": 0}
    if max_tokens:
        options.update(num_predict=max_tokens, repeat_penalty=1.1)
    reply = ollama.chat(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": prompt, "images": [_to_png(img)]}],
        options=options,
    )
    return reply["message"]["content"]


def ask_json(img, prompt):
    """Ask for JSON and parse the first {...} block in the reply. Returns {} if unparseable."""
    text = ask(img, prompt)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
