"""
Lexical search, to sit beside the vectors.

Dense retrieval matches meaning, which is what makes a Punjabi question find
an English passage. It is correspondingly weak at the thing meaning does not
help with: an exact token that carries no semantics of its own. "PBW 725",
"Tebuconazole", "Pusa 44", "Ranikhet" — a variety code or a molecule name is
either in the passage or it is not, and an embedding that has learned these
are all "wheat things" will happily return a passage about a different
variety, confidently.

BM25 has the opposite shape. It has no idea what a word means and cannot
match across languages at all, but if the farmer typed PBW 725 it will find
the passages containing PBW 725 and rank them by how unusual that token is.

The two fail in different places, which is the only good reason to run both.

**Reciprocal rank fusion** combines them (Cormack et al., 2009): each result
scores 1/(k + rank) in each list, and the scores add. It is used here rather
than a weighted sum of the raw scores because cosine similarity and BM25 are
not on the same scale and never will be — one is bounded in [-1, 1] and the
other is unbounded and corpus-dependent. Ranks are comparable; scores are
not. There is no weight to tune and therefore no weight to get wrong.

Built at load rather than shipped. On this corpus it costs well under a
second and saves carrying a second artifact that could fall out of step with
the passages — the kind of mismatch that already caused one broken image.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

# Words, in any script.
#
# \w alone is wrong here, and quietly so. It matches Indic *letters* but not
# the combining vowel signs that sit on them, so Gurmukhi ਦੀ came apart into
# ਦ and Devanagari ਬਿਜਾਈ into four fragments -- tokens that match nothing and
# occasionally match the wrong thing. English was unaffected, so nothing
# would have looked broken until the corpus grew a Hindi half.
#
# The added range covers Devanagari through Sinhala (U+0900-U+0DFF), which is
# every script this platform speaks in: Hindi, Bengali, Punjabi, Gujarati,
# Odia, Tamil, Telugu, Kannada, Malayalam.
_TOKEN = re.compile(r"[\w\u0900-\u0DFF]+", re.UNICODE)

# Okapi BM25's usual constants. k1 controls how fast term frequency
# saturates, b how much a long passage is penalised. These are the standard
# values and this project has no evidence for better ones; changing them
# without measuring would be decoration.
K1 = 1.5
B = 0.75

# Tokens too common to discriminate. Deliberately short: a stop list tuned by
# hand is a way of encoding assumptions about what farmers ask, and BM25's
# IDF already discounts common words. These are only the ones that appear in
# a large fraction of an agricultural corpus and carry no signal there.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "be",
    "for", "on", "with", "as", "by", "at", "from", "it", "this", "that",
    "should", "may", "can", "will", "should", "which", "not",
}


def tokenise(text: str) -> list[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in _STOP]


class BM25:
    """Okapi BM25 over a fixed set of documents."""

    def __init__(self, documents: list[str]):
        self.count = len(documents)
        self.lengths: list[int] = []
        # term -> list of (document index, term frequency)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)

        for index, text in enumerate(documents):
            tokens = tokenise(text)
            self.lengths.append(len(tokens))
            frequencies: dict[str, int] = defaultdict(int)
            for token in tokens:
                frequencies[token] += 1
            for token, frequency in frequencies.items():
                self.postings[token].append((index, frequency))

        self.average_length = (
            sum(self.lengths) / self.count if self.count else 0.0
        )
        self.idf = {
            token: math.log(
                1.0 + (self.count - len(posting) + 0.5) / (len(posting) + 0.5)
            )
            for token, posting in self.postings.items()
        }

    def scores(self, query: str) -> dict[int, float]:
        """Non-zero BM25 scores by document index.

        A dict rather than a dense array because a query touches a handful of
        postings and the corpus has thousands of documents; scoring only what
        a query term appears in is the whole point of an inverted index.
        """
        out: dict[int, float] = defaultdict(float)
        if not self.average_length:
            return out
        for token in set(tokenise(query)):
            posting = self.postings.get(token)
            if not posting:
                continue
            idf = self.idf[token]
            for index, frequency in posting:
                norm = 1.0 - B + B * (self.lengths[index] / self.average_length)
                out[index] += idf * (frequency * (K1 + 1.0)) / (
                    frequency + K1 * norm
                )
        return out

    def top(self, query: str, k: int) -> list[int]:
        scores = self.scores(query)
        return sorted(scores, key=lambda i: -scores[i])[:k]


# The constant in 1/(k + rank). 60 is the value the original paper used and
# what everyone has used since; it is large enough that the difference
# between rank 1 and rank 2 does not swamp a second list's opinion.
RRF_K = 60


def fuse(*rankings: list[int], k: int = RRF_K) -> list[int]:
    """Reciprocal rank fusion of several ranked lists of document indices.

    Returns one ranking, best first. A document appearing partway down both
    lists can finish above one that topped a single list, which is the
    behaviour worth having: agreement between two methods that fail
    differently is stronger evidence than confidence from either alone.
    """
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, index in enumerate(ranking):
            scores[index] += 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda i: -scores[i])
