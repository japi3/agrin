"""
Tests for searching the corpus.

The arithmetic is a dot product and needs little defending. What these tests
pin down is the refusal.

A similarity search always returns its k best matches. For a question the
corpus says nothing about, those k are simply the k least-irrelevant
passages, ranked with exactly the same confidence as a real answer. Handed to
a language model and read out with a government citation attached, that is
worse than having no corpus at all, because the citation is what makes the
answer look checked. So the score floor is the safety property here, and most
of what follows exists to keep someone from quietly raising it away.
"""

import json

import numpy as np
import pytest

from rag.chunking import Chunk
from rag.index import MIN_SCORE, AdvisoryIndex, load_index


def chunk(text="Sow wheat in November.", language="en", **kw) -> Chunk:
    return Chunk(
        text=text, title=kw.get("title", "Wheat"),
        url=kw.get("url", "https://example.test/wheat"),
        language=language, section=kw.get("section", ["Sowing"]),
        updated=kw.get("updated", "2026-03-14"), author="A. Researcher",
    )


def unit(*values) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def index_of(*rows) -> AdvisoryIndex:
    """Rows of (vector, chunk)."""
    vectors = np.array([r[0] for r in rows], dtype=np.float32)
    return AdvisoryIndex(vectors, [r[1] for r in rows], {"source": "Test"})


class TestItReturnsTheClosestPassages:
    def test_the_best_match_comes_first(self):
        index = index_of(
            (unit(1, 0, 0), chunk("about wheat")),
            (unit(0, 1, 0), chunk("about rice")),
        )
        hits = index.search(unit(0.9, 0.1, 0), k=2, min_score=0.0)
        assert hits[0].chunk.text == "about wheat"
        assert hits[0].score > hits[1].score

    def test_k_limits_how_much_comes_back(self):
        """More than a handful stops being evidence and becomes a second
        document for the model to summarise."""
        index = index_of(*[(unit(1, 0, 0), chunk(f"passage {i}")) for i in range(10)])
        assert len(index.search(unit(1, 0, 0), k=3)) == 3

    def test_asking_for_more_than_exists_is_not_an_error(self):
        index = index_of((unit(1, 0, 0), chunk()))
        assert len(index.search(unit(1, 0, 0), k=50)) == 1

    def test_an_unnormalised_query_is_normalised(self):
        """Callers should not have to know that cosine needs unit vectors."""
        index = index_of((unit(1, 0, 0), chunk()))
        hits = index.search(np.array([7.0, 0.0, 0.0], dtype=np.float32), min_score=0.0)
        assert hits[0].score == pytest.approx(1.0, abs=1e-5)


class TestItRefusesRatherThanReaching:
    def test_a_weak_match_returns_nothing_at_all(self):
        """The property this module exists to preserve."""
        index = index_of((unit(1, 0, 0), chunk()))
        assert index.search(unit(0.2, 1, 0)) == []

    def test_the_floor_is_strict_enough_to_reject_a_half_match(self):
        """0.5 cosine is where an off-topic question lands against this
        corpus. It must not be quotable."""
        assert MIN_SCORE > 0.55

    def test_an_empty_index_returns_nothing(self):
        empty = AdvisoryIndex(np.zeros((0, 3), dtype=np.float32), [], {})
        assert empty.search(unit(1, 0, 0)) == []

    def test_a_zero_query_returns_nothing_rather_than_dividing_by_zero(self):
        index = index_of((unit(1, 0, 0), chunk()))
        assert index.search(np.zeros(3, dtype=np.float32)) == []


class TestLanguageFiltering:
    def test_filtering_restricts_to_that_language(self):
        index = index_of(
            (unit(1, 0, 0), chunk("english", language="en")),
            (unit(1, 0, 0), chunk("hindi", language="hi")),
        )
        hits = index.search(unit(1, 0, 0), k=5, language="hi")
        assert [h.chunk.text for h in hits] == ["hindi"]

    def test_by_default_nothing_is_filtered(self):
        """The embedding model is multilingual: a Punjabi question matches an
        English passage about the same crop, and excluding those would hide
        most of the corpus from most of its users."""
        index = index_of(
            (unit(1, 0, 0), chunk("english", language="en")),
            (unit(1, 0, 0), chunk("hindi", language="hi")),
        )
        assert len(index.search(unit(1, 0, 0), k=5)) == 2

    def test_a_language_with_no_passages_returns_nothing(self):
        index = index_of((unit(1, 0, 0), chunk(language="en")))
        assert index.search(unit(1, 0, 0), language="ta") == []


class TestCitations:
    def test_a_hit_can_say_where_it_came_from(self):
        index = index_of((unit(1, 0, 0), chunk()))
        hit = index.search(unit(1, 0, 0), min_score=0.0)[0]
        assert "Wheat" in hit.citation()
        assert "2026-03-14" in hit.citation()

    def test_the_passage_handed_over_carries_its_url_and_date(self):
        index = index_of((unit(1, 0, 0), chunk()))
        payload = index.search(unit(1, 0, 0), min_score=0.0)[0].as_dict()
        assert payload["url"].startswith("https://")
        assert payload["updated"] == "2026-03-14"
        assert payload["section"].startswith("Wheat")


class TestLoading:
    def test_a_missing_index_is_a_normal_deployment_not_an_error(self):
        """Without the corpus the assistant loses one tool and keeps the
        rest, so callers get None rather than an exception."""
        assert load_index("/nonexistent/advisory") is None

    def test_a_round_trip_through_disk_preserves_everything(self, tmp_path):
        vectors = np.array([unit(1, 0, 0), unit(0, 1, 0)], dtype=np.float32)
        np.save(tmp_path / "vectors.npy", vectors.astype(np.float16))
        with open(tmp_path / "chunks.jsonl", "w", encoding="utf-8") as handle:
            for text in ("about wheat", "about rice"):
                handle.write(json.dumps(chunk(text).as_dict(), ensure_ascii=False) + "\n")
        (tmp_path / "manifest.json").write_text(json.dumps({"source": "Test"}))

        index = load_index(tmp_path)
        assert index is not None and len(index) == 2
        assert index.dimensions == 3
        hits = index.search(unit(1, 0, 0), min_score=0.0)
        assert hits[0].chunk.text == "about wheat"
        # float16 storage must not disturb the ranking.
        assert hits[0].score == pytest.approx(1.0, abs=1e-3)

    def test_a_truncated_index_refuses_to_load_rather_than_misattributing(self):
        """Vectors and passages are matched by row. If they disagree, every
        citation after the mismatch points at the wrong page."""
        with pytest.raises(ValueError):
            AdvisoryIndex(np.zeros((3, 4), dtype=np.float32), [chunk()], {})
