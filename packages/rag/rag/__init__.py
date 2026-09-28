"""
Retrieval over India's public agricultural advisory material.

Everything else this platform says traces to a model it can name -- FAO-56
for evapotranspiration, FAO-33 for yield response, RothC for soil carbon.
That covers water, and it covers what the numbers imply, but it does not
cover the large part of farming that is written down as practice rather than
computed: which variety suits a district, what a seed treatment should be,
what the spacing is for a crop, what a scheme requires of an applicant.

Asking a language model those questions from memory produces fluent answers
with invented specifics, and a farmer cannot tell the difference. This
package is the alternative: retrieve the passage that actually says it,
quote it, and cite where it came from. When no passage matches, the honest
answer is that the platform does not know, and the score floor in
`rag.index` exists to make that outcome reachable.

    extract   -- one Vikaspedia page, as ordered blocks of text
    chunking  -- those blocks, cut into passages that can be quoted
    embedding -- passages and questions, as vectors, inside a free quota
    index     -- the corpus, searched by brute force
"""

from .chunking import Chunk, chunk_article
from .extract import Article, Block, article_from_page, blocks_from_html
from .index import AdvisoryIndex, Hit, load_index

__all__ = [
    "Article", "Block", "Chunk", "AdvisoryIndex", "Hit",
    "article_from_page", "blocks_from_html", "chunk_article", "load_index",
]
