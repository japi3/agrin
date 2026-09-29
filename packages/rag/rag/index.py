"""
Finding the right passage, with no database.

The whole corpus is about twenty thousand passages. At 768 dimensions that
is a matrix of roughly sixty megabytes, and scoring a query against all of it
is one matrix-vector multiply -- a few milliseconds in NumPy, on a machine
that is already doing more expensive arithmetic for the water balance. A
vector database would add a service to run, a format to keep in step, and an
index whose approximations would have to be justified, in exchange for
nothing measurable at this size. So: a flat file and a dot product.

Vectors are stored L2-normalised, which makes cosine similarity the dot
product and takes the per-query normalisation out of the loop. They are
stored as float16 and widened on load: the file halves to about thirty
megabytes, and the rounding error is far below the gap between a passage
that answers the question and one that does not.

The one substantive decision here is `MIN_SCORE`. Similarity search always
returns its k best matches, and for a question the corpus has nothing to say
about, those k are simply the k least-irrelevant passages -- confidently
ranked and completely wrong. An assistant that reads them out as official
guidance is worse than one that has no corpus at all, because the citation
makes the answer look checked. So a score floor applies, and returning
nothing is a normal, expected outcome rather than a failure.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .chunking import Chunk

# Built by scripts/build_advisory_index.py and shipped in the image beside the
# soil map, so that a running instance embeds only the question.
ADVISORY_INDEX_DIR = Path(os.environ.get("AGRIN_ADVISORY_INDEX", "/app/advisory"))

VECTORS_FILE = "vectors.npy"
CHUNKS_FILE = "chunks.jsonl"
MANIFEST_FILE = "manifest.json"

# Cosine similarity below which a passage is treated as not an answer.
#
# Calibrated by hand against this corpus: questions it genuinely covers land
# their best passage around 0.72-0.85, while deliberately off-topic questions
# ("how do I rebuild a gearbox") top out in the mid 0.5s. 0.62 sits in the
# gap. It is deliberately on the strict side -- a missing citation costs a
# farmer nothing, and a confident wrong one can cost them a season.
MIN_SCORE = 0.62

# More than a handful of passages stops being evidence and starts being a
# second document for the model to summarise, which is where invented
# specifics come from.
DEFAULT_K = 4

# How much deeper than k to look before fusing. Fusing only the final k would
# let the dense ranking pick the answer before the lexical one was asked.
FUSION_DEPTH = 8


@dataclass
class Hit:
    """One retrieved passage and how well it matched."""
    chunk: Chunk
    score: float

    def citation(self) -> str:
        """How this passage should be attributed if it is used."""
        bits = [self.chunk.heading]
        if self.chunk.updated:
            bits.append(f"updated {self.chunk.updated}")
        return f"Vikaspedia -- {' -- '.join(bits)}"

    def as_dict(self) -> dict:
        return {
            "passage": self.chunk.text,
            "source": "Vikaspedia (Government of India, C-DAC)",
            "title": self.chunk.title,
            "section": self.chunk.heading,
            "url": self.chunk.url,
            "updated": self.chunk.updated,
            "score": round(self.score, 3),
        }


class AdvisoryIndex:
    """The corpus, held in memory, searched by brute force."""

    def __init__(self, vectors: np.ndarray, chunks: list[Chunk], manifest: dict):
        if len(vectors) != len(chunks):
            raise ValueError(
                f"index is inconsistent: {len(vectors)} vectors, {len(chunks)} chunks"
            )
        self.vectors = vectors
        self.chunks = chunks
        self.manifest = manifest
        self._bm25 = None

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def dimensions(self) -> int:
        return int(self.vectors.shape[1]) if len(self.vectors) else 0

    @property
    def lexical(self):
        """The BM25 index, built on first use.

        Built rather than shipped: it costs well under a second on this
        corpus and saves carrying a second artifact that could fall out of
        step with the passages, which is a mismatch that has already cost
        one broken image.
        """
        if self._bm25 is None:
            from .bm25 import BM25
            self._bm25 = BM25([c.for_embedding() for c in self.chunks])
        return self._bm25

    def search(
        self,
        query_vector: np.ndarray,
        k: int = DEFAULT_K,
        min_score: float = MIN_SCORE,
        language: str | None = None,
        query_text: str | None = None,
    ) -> list[Hit]:
        """The best passages for one embedded question, or none at all.

        `language` restricts to passages written in that language. It is left
        None by default: the embedding model is multilingual, so a question
        asked in Punjabi matches an English passage about the same crop, and
        excluding those would hide most of the corpus from most of its users.

        `query_text` turns on hybrid retrieval. The question is also run
        through BM25, and the two rankings are combined by reciprocal rank
        fusion, because the two methods fail in different places: an
        embedding is good at meaning and poor at exact tokens like "PBW 725"
        or "Tebuconazole", and BM25 is the reverse.

        **The cosine floor still decides what may be quoted.** Fusion
        reorders the passages that clear it; it can never lift one that does
        not. That is deliberate. BM25 will happily rank a passage first for
        sharing a rare word with the question while being about something
        else entirely, and the floor is the only thing standing between a
        farmer and a confidently cited irrelevance. Hybrid retrieval is a
        ranking improvement here, not a recall one.
        """
        if not len(self.vectors):
            return []

        query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(query))
        if norm == 0.0:
            return []
        query /= norm

        scores = self.vectors @ query

        if language:
            mask = np.array(
                [c.language == language for c in self.chunks], dtype=bool
            )
            if not mask.any():
                return []
            scores = np.where(mask, scores, -1.0)

        if query_text:
            return self._hybrid(scores, query_text, k, min_score)

        # argpartition finds the top k without sorting sixty thousand scores.
        k = max(1, min(k, len(scores)))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]

        return [
            Hit(chunk=self.chunks[i], score=float(scores[i]))
            for i in top
            if scores[i] >= min_score
        ]

    def _hybrid(
        self, scores: np.ndarray, query_text: str, k: int, min_score: float
    ) -> list[Hit]:
        from .bm25 import fuse

        # Fuse over a deeper slice than is returned, so that BM25 has room to
        # promote something the vectors ranked poorly. Fusing only the final
        # k would let the dense ranking decide the answer before the lexical
        # one was consulted.
        depth = max(k * FUSION_DEPTH, k)
        depth = min(depth, len(scores))
        dense_top = np.argpartition(-scores, depth - 1)[:depth]
        dense_top = list(dense_top[np.argsort(-scores[dense_top])])
        lexical_top = self.lexical.top(query_text, depth)

        ordered = fuse([int(i) for i in dense_top], lexical_top)
        return [
            Hit(chunk=self.chunks[i], score=float(scores[i]))
            for i in ordered
            if scores[i] >= min_score
        ][:k]


_index: AdvisoryIndex | None = None
_unavailable = False


def load_index(directory: Path | str | None = None) -> AdvisoryIndex | None:
    """Load the shipped index once, or return None if it was not built.

    A missing index is a normal deployment, not an error: the assistant keeps
    every other tool it has and simply stops offering to quote official
    guidance. Callers must handle None rather than assume a corpus.
    """
    global _index, _unavailable
    if directory is None:
        if _index is not None or _unavailable:
            return _index
        directory = ADVISORY_INDEX_DIR

    path = Path(directory)
    try:
        vectors = np.load(path / VECTORS_FILE).astype(np.float32, copy=False)
        with open(path / CHUNKS_FILE, encoding="utf-8") as handle:
            chunks = [Chunk.from_dict(json.loads(line)) for line in handle if line.strip()]
        manifest_path = path / MANIFEST_FILE
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists() else {}
        )
        index = AdvisoryIndex(vectors, chunks, manifest)
    except (OSError, ValueError, KeyError):
        if directory == ADVISORY_INDEX_DIR:
            _unavailable = True
        return None

    if directory == ADVISORY_INDEX_DIR:
        _index = index
    return index
