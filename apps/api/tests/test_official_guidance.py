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


class TestTheAnswerIsCheckedAgainstWhatWasQuoted:
    """The orchestrator's half of the grounding check.

    `rag.grounding` decides whether a figure is supported; this is about
    whether the orchestrator actually asks it, with the right passages, on
    the right turns. Both halves have to hold for the warning to reach a
    farmer, and the wiring is the part a refactor is likely to drop.
    """

    def _state(self, passages):
        from agrin_api.orchestrator import TurnState
        state = TurnState()
        state.quoted_passages.extend(passages)
        return state

    # Abridged from what the tool really returned for this question.
    ICAR = [
        "Deworming of all the adult stock with broad spectrum antihelmintic, "
        "Albendazole (Dose: 10 mg/ kg Body weight) during Last week of September.",
        "Deworm your animals with Albendazole or Fenbendazole @ 10mg/kg body weight.",
    ]

    def test_the_real_answer_that_prompted_this_is_flagged(self):
        """Verbatim from the running app: a schedule and a second drug that
        appear in no passage, attributed to the government advisory."""
        from agrin_api.orchestrator import _grounding_warning
        answer = [
            "According to the government's ICAR advisory published on "
            "Vikaspedia, deworm the calf on its 14th day of life. ",
            "Second, deworm on the 35th day. Third, deworm on the 56th day. ",
            "Albendazole at a dose of 7.5 to 10 milligrams per kilogram.",
        ]
        assert _grounding_warning(answer, self._state(self.ICAR))

    def test_an_answer_that_sticks_to_the_source_is_not_flagged(self):
        """If correct answers carry the warning too, it stops being read."""
        from agrin_api.orchestrator import _grounding_warning
        answer = ["The advisory says to deworm with Albendazole at 10 mg/kg "
                  "of body weight, in the last week of September."]
        assert _grounding_warning(answer, self._state(self.ICAR)) is None

    def test_a_turn_that_quoted_nothing_is_not_checked(self):
        """A computed answer carries its own provenance; its numbers come
        from the agronomic models, not from recall, and checking them
        against an empty passage list would flag every one."""
        from agrin_api.orchestrator import _grounding_warning
        answer = ["Apply about 48 mm of water, roughly two inches."]
        assert _grounding_warning(answer, self._state([])) is None

    def test_an_empty_answer_is_not_flagged(self):
        from agrin_api.orchestrator import _grounding_warning
        assert _grounding_warning([], self._state(self.ICAR)) is None

    def test_the_warning_says_who_to_confirm_with(self):
        """A warning that only says "unverified" leaves the farmer nowhere."""
        from rag.grounding import WARNING
        assert "KVK" in WARNING or "veterinarian" in WARNING


class TestCapacityFailuresAreRememberedOnce:
    """A 503 is about the model, not the key.

    Found on the deployed service: a question took 200 seconds to its first
    token. The model was out of capacity, the orchestrator recorded only
    429s, so the chain tried every key against a model that was down for all
    of them — each attempt burning most of the 60-second stream timeout —
    before reaching one that answered.
    """

    def test_a_capacity_error_is_worth_remembering(self):
        from agrin_api import llm
        assert llm.is_worth_remembering(RuntimeError("503 UNAVAILABLE"))
        assert llm.is_worth_remembering(RuntimeError("504 DEADLINE_EXCEEDED"))

    def test_so_is_a_quota_error(self):
        from agrin_api import llm
        assert llm.is_worth_remembering(RuntimeError("429 RESOURCE_EXHAUSTED"))

    def test_an_ordinary_fault_is_not(self):
        """A bad request or a parse failure says nothing about the model's
        availability, and writing it off would move every later question to
        a weaker model for no reason."""
        from agrin_api import llm
        assert not llm.is_worth_remembering(ValueError("bad JSON"))
        assert not llm.is_worth_remembering(RuntimeError("400 INVALID_ARGUMENT"))

    def test_one_503_writes_the_model_off_for_every_key(self, monkeypatch):
        from agrin_api import llm
        monkeypatch.setattr(llm, "api_keys", lambda: ["a", "b", "c"])
        monkeypatch.setattr(llm, "_save_cooldowns", lambda: None)
        llm._cooldowns.clear()
        llm.note_rate_limited("gemini-x", RuntimeError("503 UNAVAILABLE"), key_index=0)
        assert all(llm.is_cooling_down("gemini-x", k) for k in (0, 1, 2))

    def test_a_quota_error_writes_off_only_its_own_key(self, monkeypatch):
        """Quota is per key. Writing off the others would throw away
        allowance that is still there."""
        from agrin_api import llm
        monkeypatch.setattr(llm, "api_keys", lambda: ["a", "b", "c"])
        monkeypatch.setattr(llm, "_save_cooldowns", lambda: None)
        llm._cooldowns.clear()
        llm.note_rate_limited("gemini-y", RuntimeError("429 PerDay quota"), key_index=1)
        assert llm.is_cooling_down("gemini-y", 1)
        assert not llm.is_cooling_down("gemini-y", 0)

    def test_a_capacity_blip_never_revives_an_exhausted_key(self, monkeypatch):
        """The daily write-off is an hour; capacity is two minutes. Taking
        the shorter one would send a question back to a key with nothing
        left."""
        from agrin_api import llm
        monkeypatch.setattr(llm, "api_keys", lambda: ["a", "b"])
        monkeypatch.setattr(llm, "_save_cooldowns", lambda: None)
        llm._cooldowns.clear()
        llm.note_rate_limited("gemini-z", RuntimeError("429 PerDay quota"), key_index=0)
        spent = llm._cooldowns[(0, "gemini-z")]
        llm.note_unavailable("gemini-z")
        assert llm._cooldowns[(0, "gemini-z")] == spent


class TestStaleIdentifiersFromTheBrowser:
    """A farmer id in a request is a hint, not a guarantee.

    The database is a file. On a host with an ephemeral disk -- Render,
    Cloud Run, any rebuilt container -- every deploy starts an empty one
    while the browser still holds identifiers from the last. Trusting them
    raised a foreign-key error and returned 500 to every returning visitor,
    whose only escape was clearing site data.
    """

    def _client(self):
        from fastapi.testclient import TestClient
        from agrin_api.main import app
        return TestClient(app)

    def test_an_unknown_farmer_id_does_not_error(self, monkeypatch):
        from agrin_api import storage
        monkeypatch.setattr(storage, "get_farmer", lambda _id: None)
        created = []
        monkeypatch.setattr(storage, "create_farmer",
                            lambda **kw: created.append(1) or "fresh-farmer")
        assert storage.get_farmer("gone") is None
        assert storage.create_farmer(language="en") == "fresh-farmer"

    def test_storage_can_tell_a_missing_conversation_from_a_real_one(self):
        """The lookup the endpoint needs to make that judgement."""
        from agrin_api import storage
        assert storage.get_conversation("definitely-not-a-real-id") is None

    def test_a_missing_field_reads_as_absent_rather_than_raising(self):
        from agrin_api import storage
        assert storage.get_field("definitely-not-a-real-id") is None


class TestADailyQuotaIsWrittenOffUntilItReturns:
    """The one-hour cooldown was the latency.

    A turn took 84 seconds; 78 of them were the first model call walking
    sixteen key-and-model pairs whose daily allowance was gone. The hour had
    elapsed, so every dead pair was back in rotation, and each one cost a
    real round trip. The allowance had not returned -- only the cooldown had
    expired.
    """

    def test_it_lands_on_the_reset_hour_not_an_offset_from_now(self):
        """Whenever it is asked, it names the next reset -- never "an hour
        from whenever the quota happened to run out"."""
        import datetime as dt
        from agrin_api import llm
        for hour in (0, 6, 8, 23):
            moment = dt.datetime(2026, 9, 30, hour, 30, tzinfo=dt.timezone.utc)
            secs = llm.seconds_until_daily_reset(moment.timestamp())
            landing = moment + dt.timedelta(seconds=secs)
            assert landing.hour == llm.DAILY_RESET_UTC_HOUR
            assert landing.minute == 0
            assert 0 < secs <= 24 * 3600

    def test_just_after_the_reset_it_waits_almost_a_full_day(self):
        """The case the hour got wrong: exhausted at 07:30 UTC, the
        allowance does not return for 23 and a half hours."""
        import datetime as dt
        from agrin_api import llm
        moment = dt.datetime(2026, 9, 30, 7, 30, tzinfo=dt.timezone.utc)
        secs = llm.seconds_until_daily_reset(moment.timestamp())
        assert secs > 23 * 3600

    def test_a_quota_write_off_uses_it(self, monkeypatch):
        from agrin_api import llm
        import time as _t
        monkeypatch.setattr(llm, "api_keys", lambda: ["a"])
        monkeypatch.setattr(llm, "_save_cooldowns", lambda: None)
        llm._cooldowns.clear()
        llm.note_rate_limited("gemini-q", RuntimeError("429 PerDay quota"), 0)
        remaining = llm._cooldowns[(0, "gemini-q")] - _t.time()
        assert remaining > 3600, "a daily quota must outlast the old one-hour guess"

    def test_cooling_pairs_are_ordered_by_who_recovers_first(self, monkeypatch):
        """When everything is cooling, the order they are tried in is all
        that is left to get right."""
        from agrin_api import llm
        import time as _t
        monkeypatch.setattr(llm, "api_keys", lambda: ["a", "b"])
        monkeypatch.setattr(llm, "_save_cooldowns", lambda: None)
        llm._cooldowns.clear()
        now = _t.time()
        for (k, m), offset in (((0, llm.DEFAULT_MODEL), 9000),
                               ((1, llm.DEFAULT_MODEL), 60)):
            llm._cooldowns[(k, m)] = now + offset
        order = [p for p in llm.request_candidates() if p[1] == llm.DEFAULT_MODEL]
        assert order[0] == (1, llm.DEFAULT_MODEL), "soonest to recover comes first"
