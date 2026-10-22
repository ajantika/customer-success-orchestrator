"""Lightweight documentation retrieval.

Method: section-level TF-IDF with cosine similarity, implemented in pure Python.
There are no embeddings and no semantic matching, so paraphrases that share no
vocabulary with the docs will not be found. Unsupported questions are detected
with a score threshold and handled by an explicit fallback.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "kb"
SUPPORT_THRESHOLD = 0.25  # below this top score the question is treated as unsupported

STOP = set(
    "a an and are as at be but by can do does for from has have how i if in into is it its me my of on or our so that the "
    "their them then there these this those to up we what when where which will with you your please hi hello".split()
)


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    product: str
    section: str
    text: str


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def _parse(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        for line in fm.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    chunks = []
    for block in re.split(r"^## ", body, flags=re.M)[1:]:
        heading, _, text = block.partition("\n")
        chunks.append(Chunk(meta["id"], meta["title"], meta.get("product", "all"), heading.strip(), text.strip()))
    return chunks


class Retriever:
    def __init__(self, kb_dir: Path = KB_DIR):
        self.chunks: list[Chunk] = []
        for p in sorted(kb_dir.glob("DOC-*.md")):
            self.chunks.extend(_parse(p))
        docs = [Counter(tokenize(c.title + " " + c.section + " " + c.section + " " + c.text)) for c in self.chunks]
        n = len(docs)
        df: Counter = Counter()
        for d in docs:
            df.update(d.keys())
        self.idf = {t: math.log((1 + n) / (1 + f)) + 1 for t, f in df.items()}
        self.vecs = [self._vec(d) for d in docs]

    def _vec(self, counts: Counter) -> dict[str, float]:
        # words missing from the knowledge base still count in the query norm, so off-topic questions score low
        top = max(self.idf.values(), default=1.0)
        v = {t: (1 + math.log(c)) * self.idf.get(t, top) for t, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def doc_ids(self) -> set[str]:
        return {c.doc_id for c in self.chunks}

    def get(self, doc_id: str) -> list[Chunk]:
        return [c for c in self.chunks if c.doc_id == doc_id]

    def search(self, query: str, top_k: int = 3, product: str | None = None, exclude: set[str] | None = None) -> list[dict]:
        q = self._vec(Counter(tokenize(query)))
        scored = []
        for c, v in zip(self.chunks, self.vecs):
            if exclude and c.doc_id in exclude:
                continue
            if product and c.product not in (product, "all"):
                continue
            s = sum(w * v.get(t, 0.0) for t, w in q.items())
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [
            {"doc_id": c.doc_id, "title": c.title, "section": c.section, "score": round(s, 3), "excerpt": c.text[:500]}
            for s, c in scored[:top_k]
        ]


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever()
