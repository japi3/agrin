"""
The guidance lookup tool, with the corpus and the embedding call stubbed.

Every other tool in this platform computes a number and is tested on the
arithmetic. This one hands the model somebody else's words, so what is under
test is the discipline around them: that the passages arrive with the page
they came from, that a weak match produces an abstention rather than a
plausible answer, and -- most of all -- that every failure path tells the
model in plain words not to fall back on its own recall.

That last one is the whole point. A tool that returns `{"ok": false}` and
nothing else invites the model to answer from memory, which is exactly the
behaviour the corpus was built to replace. So each refusal here carries an
instruction, and each of those instructions is pinned by a test.
"""

import numpy as np
import pytest

from agrin_api import tools
from rag.chunking import Chunk
from rag.index import AdvisoryIndex


def chunk(text="Use 100 kg of seed per hectare.", language="en") -> Chunk:
    return Chunk(
        text=text, title="Wheat cultivation",
        url="https://agriculture.vikaspedia.in/wheat?lgn=en",
        language=language, section=["Seed rate"], updated="2026-03-14",
        author="A. Researcher",
    )


@pytest.fixture
def corpus(monkeypatch):
    """A one-passage library, and an embedding call that never leaves."""
    vectors = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    index = AdvisoryIndex(vectors, [chunk()], {
        "source": "Vikaspedia (Government of India, C-DAC)",
        "model": "gemini-embedding-001", "built_on": "2026-09-28",
    })
    monkeypatch.setattr(tools, "load_advisory_index", lambda: index)
    monkeypatch.setattr(tools.llm, "api_keys", lambda: ["k"])
    monkeypatch.setattr(tools.llm, "client_for", lambda i: object())
    return index


def answer_with(monkeypatch, vector):
    async def embed_query(_client, _question, **_kw):
        return np.array(vector, dtype=np.float32)
    import rag.embedding
    monkeypatch.setattr(rag.embedding, "embed_query", embed_query)


class TestItHandsOverPassagesNotAnswers:
    async def test_a_match_returns_the_published_words(self, monkeypatch, corpus):
        answer_with(monkeypatch, [1.0, 0.0, 0.0])
        out = await tools.look_up_official_guidance("seed rate for wheat")
        assert out["ok"]
        assert out["passages"][0]["passage"] == "Use 100 kg of seed per hectare."

    async def test_every_passage_arrives_with_somewhere_to_check_it(
        self, monkeypatch, corpus
    ):
        answer_with(monkeypatch, [1.0, 0.0, 0.0])
        out = await tools.look_up_official_guidance("seed rate for wheat")
        passage = out["passages"][0]
        assert passage["url"].startswith("https://")
        assert passage["updated"] == "2026-03-14"
        assert "Vikaspedia" in passage["source"]

    async def test_it_does_not_summarise(self, monkeypatch, corpus):
        """Summarising is the model's job, and it can only do it honestly
        with the actual words in front of it."""
        answer_with(monkeypatch, [1.0, 0.0, 0.0])
        out = await tools.look_up_official_guidance("seed rate for wheat")
        assert "summary" not in out
        assert "answer" not in out

    async def test_the_evidence_records_how_the_passage_was_found(
        self, monkeypatch, corpus
    ):
        answer_with(monkeypatch, [1.0, 0.0, 0.0])
        out = await tools.look_up_official_guidance("seed rate for wheat")
        assert "gemini-embedding-001" in out["evidence"]["retrieval"]
        assert out["evidence"]["corpus_built_on"] == "2026-09-28"

    async def test_it_says_published_guidance_is_not_about_this_field(
        self, monkeypatch, corpus
    ):
        """The computed tools measure this field; this one does not, and the
        model has to be told which wins when they disagree."""
        answer_with(monkeypatch, [1.0, 0.0, 0.0])
        out = await tools.look_up_official_guidance("seed rate for wheat")
        limits = " ".join(out["evidence"]["limitations"]).lower()
        assert "not specific to this field" in limits
        assert "measurements" in limits

    async def test_a_weaker_match_is_reported_as_less_certain(
        self, monkeypatch, corpus
    ):
        answer_with(monkeypatch, [0.66, 0.75, 0.0])
        out = await tools.look_up_official_guidance("something adjacent")
        assert out["ok"] and out["confidence"] == "moderate"


class TestEveryRefusalTellsTheModelNotToGuess:
    async def test_nothing_close_enough_abstains(self, monkeypatch, corpus):
        answer_with(monkeypatch, [0.0, 1.0, 0.0])
        out = await tools.look_up_official_guidance("how do I rebuild a gearbox")
        assert out["ok"] is False
        assert "passages" not in out

    async def test_and_says_so_in_words_the_model_must_act_on(
        self, monkeypatch, corpus
    ):
        answer_with(monkeypatch, [0.0, 1.0, 0.0])
        out = await tools.look_up_official_guidance("how do I rebuild a gearbox")
        reason = out["abstain_reason"].lower()
        assert "do not answer from your own knowledge" in reason
        assert "invented" in reason

    async def test_a_deployment_without_the_corpus_is_not_an_error(
        self, monkeypatch
    ):
        """A build that skipped the index keeps every other tool. It must not
        look like "nothing is published about this"."""
        monkeypatch.setattr(tools, "load_advisory_index", lambda: None)
        out = await tools.look_up_official_guidance("seed rate for wheat")
        assert out["ok"] is False
        assert "not installed" in out["abstain_reason"]
        assert "cannot cite a source" in out["abstain_reason"]

    async def test_an_unreachable_embedding_service_abstains_loudly(
        self, monkeypatch, corpus
    ):
        async def boom(_client, _question, **_kw):
            raise RuntimeError("quota")
        import rag.embedding
        monkeypatch.setattr(rag.embedding, "embed_query", boom)
        out = await tools.look_up_official_guidance("seed rate for wheat")
        assert out["ok"] is False
        assert "do not answer from memory" in out["abstain_reason"].lower()

    async def test_a_failing_key_is_retried_on_the_next_one(
        self, monkeypatch, corpus
    ):
        """Retrieval must not be taken out by a key that a chat request has
        already pushed into cooldown."""
        monkeypatch.setattr(tools.llm, "api_keys", lambda: ["a", "b"])
        seen = []

        async def flaky(_client, _question, **_kw):
            seen.append(1)
            if len(seen) == 1:
                raise RuntimeError("429")
            return np.array([1.0, 0.0, 0.0], dtype=np.float32)

        import rag.embedding
        monkeypatch.setattr(rag.embedding, "embed_query", flaky)
        out = await tools.look_up_official_guidance("seed rate for wheat")
        assert out["ok"] and len(seen) == 2

    async def test_an_empty_question_asks_rather_than_searching(self, corpus):
        out = await tools.look_up_official_guidance("   ")
        assert out["ok"] is False


class TestItIsWiredIn:
    def test_the_model_is_offered_the_tool(self):
        from agrin_api.schemas import tool_names
        assert "look_up_official_guidance" in tool_names()

    def test_the_orchestrator_can_dispatch_it(self):
        from agrin_api.orchestrator import TOOL_REGISTRY
        assert "look_up_official_guidance" in TOOL_REGISTRY

    def test_the_schema_steers_it_away_from_the_computed_tools(self):
        """Retrieved general guidance must never displace a measurement of
        this particular field."""
        from agrin_api.schemas import TOOL_DEFINITIONS
        described = next(t for t in TOOL_DEFINITIONS
                         if t["name"] == "look_up_official_guidance")["description"]
        assert "Do NOT use it" in described
        assert "irrigation" in described

    def test_a_used_source_becomes_a_card_the_farmer_can_open(self):
        from agrin_api.orchestrator import _card_for
        card = _card_for("look_up_official_guidance", {
            "ok": True,
            "passages": [{"title": "Wheat cultivation", "section": "Wheat > Seed rate",
                          "url": "https://example.test/wheat", "updated": "2026-03-14"}],
            "evidence": {"source": "Vikaspedia"},
        })
        assert card["card"] == "sources"
        assert card["sources"][0]["url"] == "https://example.test/wheat"

    def test_an_abstention_shows_no_card(self):
        from agrin_api.orchestrator import _card_for
        assert _card_for("look_up_official_guidance", {"ok": False}) is None
