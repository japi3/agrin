"""
Turning text into vectors, within a free quota.

One model, `gemini-embedding-001`, chosen for two reasons. It keeps the
platform on Google AI, which this project is built around. And it is
genuinely multilingual, which matters more here than any benchmark score: the
corpus is largely English, the farmers asking are not, and a question typed
in Punjabi has to find the English passage that answers it. A local
sentence-transformer would have meant a model download, a PyTorch dependency
and worse cross-lingual behaviour.

The quota is the thing that shapes this module. Embedding is metered
differently from generation, and the difference is the reason a corpus of
this size is affordable at all:

    generation:  20 requests per day, per model, per key
    embedding:  100 requests per minute, per model, per key -- no daily cap

So the corpus is not limited by budget, only by patience. What matters is
staying under a *per-minute* ceiling, which is why the pacing below is a
sliding window rather than a fixed sleep.

One detail that is easy to get wrong and expensive to discover: a batched
call does not count as one request. Each text in `contents` is metered
separately, so a batch of 100 spends the whole minute's allowance at once.
Batching still helps -- it saves round trips, not quota -- and the window
here counts texts, not calls, because that is what the service counts.

Vectors come back at 768 dimensions rather than the default 3072. The model
is trained so that its leading dimensions stand on their own, the smaller
vector is four times cheaper to ship and to search, and the difference in
retrieval quality on a corpus of twenty thousand passages is not something
this project could honestly claim to have measured. Google's own guidance is
that anything other than 3072 must be re-normalised by the caller, and that
is done here rather than left to whoever loads the file.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np

EMBEDDING_MODEL = "gemini-embedding-001"

# See the module docstring: leading dimensions are meaningful on their own.
DIMENSIONS = 768

# The free-tier ceiling, in texts per minute per key, with a margin. The
# service reports this as EmbedContentRequestsPerMinutePerProjectPerModel.
TEXTS_PER_MINUTE = 90

# Round trips are the cost batching actually saves. Kept well under the
# per-minute ceiling so a single batch can never exhaust it outright.
BATCH_SIZE = 32

# What the model is told the text is for. Documents and queries are embedded
# into the same space but with different instructions, and using the wrong one
# measurably weakens matching.
DOCUMENT = "RETRIEVAL_DOCUMENT"
QUERY = "RETRIEVAL_QUERY"


class RateWindow:
    """A sliding window over the last minute of texts embedded.

    A fixed sleep between calls would either waste the allowance or overrun
    it depending on how long the service takes to answer, which varies by
    more than the gap would. Recording when each text was sent and waiting
    only when the window is genuinely full spends the quota as fast as it is
    allowed to be spent and no faster.
    """

    def __init__(self, limit: int = TEXTS_PER_MINUTE, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._sent: list[float] = []

    async def take(self, count: int) -> None:
        while True:
            now = time.monotonic()
            self._sent = [t for t in self._sent if now - t < self.window_s]
            if len(self._sent) + count <= self.limit:
                self._sent.extend([now] * count)
                return
            oldest = self._sent[0]
            await asyncio.sleep(max(0.1, self.window_s - (now - oldest) + 0.1))


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


async def embed_texts(
    client,
    texts: list[str],
    task_type: str = DOCUMENT,
    dimensions: int = DIMENSIONS,
) -> np.ndarray:
    """Embed a batch, returning one L2-normalised row per text.

    `client` is a google-genai client, passed in rather than built here so
    that this package stays independent of the API's key rotation and so the
    builder script can spread a long run across several keys.
    """
    from google.genai import types

    if not texts:
        return np.zeros((0, dimensions), dtype=np.float32)

    response = await client.aio.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=dimensions,
        ),
    )
    vectors = np.array(
        [e.values for e in response.embeddings], dtype=np.float32
    )
    if vectors.shape != (len(texts), dimensions):
        raise ValueError(
            f"expected {len(texts)}x{dimensions} vectors, got {vectors.shape}"
        )
    return _normalise(vectors)


async def embed_query(client, question: str, dimensions: int = DIMENSIONS) -> np.ndarray:
    """Embed one question, ready to search with."""
    vectors = await embed_texts(client, [question], task_type=QUERY, dimensions=dimensions)
    return vectors[0]
