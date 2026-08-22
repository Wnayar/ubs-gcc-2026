"""Rebuild app/data/study_materials.json from the challenge's study materials.

Development-time only. `tiktoken` is NOT a project dependency — the whole point
of this script is that it does the tokenising here, once, so the live server
never has to. Run it in a scratch venv:

    python -m venv /tmp/tk && /tmp/tk/bin/pip install tiktoken httpx
    /tmp/tk/bin/python tools/fetch_study_materials.py

Re-run it (and redeploy) only if the challenge changes the corpus — the five
documents were byte-identical across repeated fetches on 2026-08-22.

Why counts are baked in
-----------------------
The recall tool answers with a JSON array of strings and the budget is the sum
of `len(encoding.encode(chunk))` over the array's elements, with `o200k_base`
(tool-box-2, "HOW THE 900 TOKENS ARE COUNTED"). The run viewer states the same
rule from the grader's side: "The counts are summed rather than measured over
the joined text, so you can count each passage as you select it and get the
same number we do."

BPE counts are not additive across a concatenation, so the only way to know a
total exactly without a tokeniser at runtime is to precompute the count of each
string we might emit. Each passage is a section prefix glued to one paragraph
or sentence, and it is the *prefixed* string whose count is baked in here.
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import httpx
import tiktoken

HOST = "https://tool-box-2591eaa24fa3.herokuapp.com"
INDEX = f"{HOST}/study-materials"
OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "data" / "study_materials.json"

# "Dr. Ansel Kovrith" must not end a sentence; nor must "No. 4" or "e.g. this".
ABBREVIATIONS = ("Dr", "Mr", "Mrs", "Ms", "St", "No", "Nos", "vs", "approx", "Fig", "cf")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def split_sentences(paragraph: str) -> list[str]:
    pieces = SENTENCE_BREAK.split(paragraph.strip())
    merged: list[str] = []
    for piece in pieces:
        if merged:
            tail = merged[-1].rsplit(" ", 1)[-1].rstrip(".")
            if tail in ABBREVIATIONS:
                merged[-1] = f"{merged[-1]} {piece}"
                continue
        merged.append(piece)
    return [s for s in merged if s.strip()]


def split_sections(body: str) -> list[tuple[str, list[str]]]:
    """-> [(heading line, [paragraph, ...]), ...] preserving document order."""
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    paragraphs: list[str] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            if heading or paragraphs:
                sections.append((heading, paragraphs))
            heading, paragraphs = block, []
        else:
            paragraphs.append(" ".join(block.split()))
    if heading or paragraphs:
        sections.append((heading, paragraphs))
    return sections


def main() -> int:
    encode = tiktoken.get_encoding("o200k_base").encode

    def unit(text: str) -> dict:
        return {"text": text, "tokens": len(encode(text))}

    with httpx.Client(timeout=30.0) as http:
        index = http.get(INDEX).raise_for_status().json()
        documents = []
        for entry in index["documents"]:
            body = http.get(entry["url"]).raise_for_status().text
            sections = []
            for heading, paragraphs in split_sections(body):
                # Every passage carries its own source, so the android can tell
                # the Kesterline array from the Halberd sub-array without us
                # having to spend a separate array element on a heading. Fewer,
                # self-contained elements also serialise smaller, which is what
                # the 1,200-token response ceiling actually measures.
                prefix = f"[{entry['title']} — {heading.lstrip('# ').strip()}] "
                sections.append(
                    {
                        "heading": unit(heading),
                        "prefix": prefix,
                        "paragraphs": [
                            dict(
                                unit(paragraph),
                                passage_tokens=len(encode(prefix + paragraph)),
                                sentences=[
                                    dict(unit(s), passage_tokens=len(encode(prefix + s)))
                                    for s in split_sentences(paragraph)
                                ],
                            )
                            for paragraph in paragraphs
                        ],
                    }
                )
            documents.append(
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "url": entry["url"],
                    "header": unit(f"From: {entry['title']}"),
                    "sections": sections,
                }
            )

    payload = {
        "source": INDEX,
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "encoding": "o200k_base",
        "documents": documents,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")

    total = sum(
        paragraph["tokens"]
        for document in documents
        for section in document["sections"]
        for paragraph in section["paragraphs"]
    )
    print(f"wrote {OUT} — {len(documents)} documents, {total} paragraph tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
