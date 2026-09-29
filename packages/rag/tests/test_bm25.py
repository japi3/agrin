"""
Tests for lexical search and its fusion with the vectors.

BM25 is here for the case embeddings are worst at: an exact token that
carries no meaning of its own. A variety code is either in the passage or it
is not, and a model that has learned "PBW 725" and "HD 3086" are both wheat
things will return the wrong one confidently.

The tests that matter most are not about ranking quality, though. They are
the ones at the bottom, which check that adding a second retriever did not
quietly dissolve the abstention the whole feature rests on. BM25 will rank a
passage first for sharing one rare word with a question while being about
something else entirely, and if fusion could lift such a passage past the
cosine floor, every guarantee made elsewhere about refusing would be void.
"""

import numpy as np
import pytest

from rag.bm25 import BM25, fuse, tokenise
from rag.chunking import Chunk
from rag.index import AdvisoryIndex

DOCS = [
    "Treat wheat seed with Tebuconazole before sowing to prevent loose smut.",
    "Sow the PBW 725 variety of wheat in the first fortnight of November.",
    "Paddy nursery management and transplanting in puddled fields.",
    "Control aphids on mustard by spraying at the first sign of curling.",
]


class TestItFindsExactTokens:
    def test_a_molecule_name(self):
        assert BM25(DOCS).top("Tebuconazole", 1) == [0]

    def test_a_variety_code(self):
        """The case that motivated adding this: an embedding treats every
        wheat variety as roughly the same thing."""
        assert BM25(DOCS).top("PBW 725", 1) == [1]

    def test_a_rare_word_beats_a_common_one(self):
        top = BM25(DOCS).top("wheat Tebuconazole", 1)
        assert top == [0]

    def test_a_word_in_no_document_scores_nothing(self):
        assert BM25(DOCS).scores("helicopter") == {}

    def test_an_empty_corpus_does_not_divide_by_zero(self):
        assert BM25([]).scores("wheat") == {}


class TestTokenising:
    def test_it_lowercases_and_splits_on_punctuation(self):
        assert tokenise("Wheat, seed—treatment.") == ["wheat", "seed", "treatment"]

    def test_it_keeps_digits_with_their_letters(self):
        assert "725" in tokenise("PBW 725")

    def test_it_keeps_indic_script(self):
        """The corpus is English today and will not always be."""
        assert tokenise("ਕਣਕ ਦੀ ਬਿਜਾਈ") == ["ਕਣਕ", "ਦੀ", "ਬਿਜਾਈ"]

    def test_stop_words_are_dropped(self):
        assert "the" not in tokenise("the wheat in the field")


class TestFusion:
    def test_agreement_between_two_lists_wins(self):
        """A passage partway down both lists beats one that topped a single
        list — agreement between methods that fail differently is stronger
        evidence than confidence from either alone."""
        assert fuse([9, 1, 2], [8, 1, 3])[0] == 1

    def test_a_document_in_one_list_only_still_ranks(self):
        assert 9 in fuse([9], [8])

    def test_an_empty_list_is_harmless(self):
        assert fuse([3, 1], []) == [3, 1]


def index_of(rows) -> AdvisoryIndex:
    """rows: (vector, text)."""
    vectors = np.array([r[0] for r in rows], dtype=np.float32)
    chunks = [
        Chunk(text=r[1], title=r[1][:20], url="https://example.test/x",
              language="en")
        for r in rows
    ]
    return AdvisoryIndex(vectors, chunks, {})


def unit(*v):
    a = np.array(v, dtype=np.float32)
    return a / np.linalg.norm(a)


class TestHybridDoesNotDissolveTheFloor:
    """The property everything else depends on."""

    def test_a_lexical_match_below_the_floor_is_still_refused(self):
        """BM25 ranks it first for sharing a rare word. Its meaning is
        unrelated. It must not be quoted."""
        index = index_of([
            (unit(1, 0, 0), "Tebuconazole seed treatment for wheat"),
            (unit(0, 1, 0), "Tebuconazole is also a name in this unrelated text"),
        ])
        hits = index.search(unit(0, 1, 0) * 0.3 + unit(1, 0, 0) * 0.95,
                            k=4, query_text="Tebuconazole")
        for hit in hits:
            assert hit.score >= 0.62

    def test_an_entirely_off_topic_question_still_returns_nothing(self):
        index = index_of([(unit(1, 0, 0), "Wheat seed treatment")])
        assert index.search(unit(0, 1, 0), query_text="motorcycle gearbox") == []

    def test_the_score_reported_is_still_the_cosine(self):
        """Not a fused rank. The number shown beside a citation has to mean
        something, and 'reciprocal rank fusion score' means nothing to a
        reader deciding whether to trust it."""
        index = index_of([(unit(1, 0, 0), "Wheat seed treatment")])
        hit = index.search(unit(1, 0, 0), query_text="wheat", min_score=0.0)[0]
        assert hit.score == pytest.approx(1.0, abs=1e-3)


class TestHybridIsOptional:
    def test_without_query_text_nothing_changes(self):
        index = index_of([
            (unit(1, 0, 0), "Wheat seed treatment"),
            (unit(0, 1, 0), "Paddy nursery"),
        ])
        dense = index.search(unit(1, 0, 0), k=2, min_score=0.0)
        assert [h.chunk.text for h in dense] == ["Wheat seed treatment", "Paddy nursery"]

    def test_lexical_evidence_can_reorder_what_passed_the_floor(self):
        """Two passages both clear the floor; the one containing the typed
        token should come first."""
        index = index_of([
            (unit(1.0, 0.02, 0), "General wheat cultivation notes"),
            (unit(0.99, 0.14, 0), "Apply Tebuconazole to the seed before sowing"),
        ])
        query = unit(1.0, 0.05, 0)
        dense = index.search(query, k=2, min_score=0.0)
        hybrid = index.search(query, k=2, min_score=0.0, query_text="Tebuconazole")
        assert dense[0].chunk.text.startswith("General")
        assert hybrid[0].chunk.text.startswith("Apply Tebuconazole")
