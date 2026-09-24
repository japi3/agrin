"""
Tests for how the provider layer remembers an exhausted model.

The free tier meters per model, so when one is out of quota the right move is
to skip it and try the next rather than wait. What "out of quota" means, and
for how long, is the part that was wrong: the binding limit is twenty requests
per DAY per model, but its 429 carries a retryDelay of ten or twenty seconds,
describing when the rate limiter will next accept a request rather than when
the allowance returns.

Believing that delay meant a model exhausted until tomorrow was retried every
fifteen seconds all day. Each retry is a wasted round trip, and one farmer
question makes several model calls, so the same dead models were walked over
and over inside a single answer.
"""

import time

from agrin_api import llm


def _clear():
    llm._cooldowns.clear()


class TestDailyQuotaIsNotATransientPause:
    def test_a_per_day_429_is_written_off_for_far_longer_than_its_retry_delay(self):
        _clear()
        exc = Exception(
            "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
            "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
            "limit: 20, model: gemini-3.8-flash. Please retry in 13.9s. "
            "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        )
        llm.note_rate_limited("gemini-3.8-flash", exc)

        remaining = llm._cooldowns[(0, "gemini-3.8-flash")] - time.time()
        # Emphatically not the 14 seconds the error suggests.
        assert remaining > 600
        assert llm.is_cooling_down("gemini-3.8-flash")

    def test_a_genuine_short_pause_still_uses_the_supplied_delay(self):
        """Per-minute limits do free up quickly, and must not be over-punished."""
        _clear()
        exc = Exception("429 RESOURCE_EXHAUSTED. Please retry in 8.0s.")
        llm.note_rate_limited("gemini-3.7-flash", exc)

        remaining = llm._cooldowns[(0, "gemini-3.7-flash")] - time.time()
        assert 5 < remaining < 30

    def test_an_error_with_no_delay_falls_back_to_the_default(self):
        _clear()
        llm.note_rate_limited("gemini-3.5-flash", Exception("429 RESOURCE_EXHAUSTED"))

        remaining = llm._cooldowns[(0, "gemini-3.5-flash")] - time.time()
        assert 0 < remaining <= llm.DEFAULT_COOLDOWN_S + 1


class TestCoolingModelsAreDeprioritised:
    def test_an_exhausted_model_is_not_tried_first(self):
        """The whole point: stop paying to rediscover what we already know."""
        _clear()
        candidates = llm.model_candidates()
        assert len(candidates) > 1
        first = candidates[0]

        llm.note_rate_limited(first, Exception("429. quotaId: "
                                               "GenerateRequestsPerDayPerProjectPerModel"))
        after = llm.model_candidates()

        assert after[0] != first
        # Still reachable -- a model we believe is dead may not be, and the
        # cost of finding out is one failed request at the end of the chain.
        assert first in after
        _clear()

    def test_the_chain_survives_every_model_being_exhausted(self):
        """A farmer must get an answer attempt, not an empty candidate list."""
        _clear()
        for model in llm.model_candidates():
            llm.note_rate_limited(model, Exception("429. PerDay"))

        assert llm.model_candidates(), "chain must never be empty"
        _clear()


class TestASecondKeyIsASecondAllowance:
    """The free tier meters per project, so another key is another 20/day."""

    def test_running_out_on_one_key_does_not_write_off_the_model(self):
        _clear()
        llm.note_rate_limited("gemini-3.7-flash", Exception("429. PerDay"), key_index=0)

        assert llm.is_cooling_down("gemini-3.7-flash", 0)
        assert not llm.is_cooling_down("gemini-3.7-flash", 1)
        _clear()

    def test_the_best_model_is_tried_on_every_key_before_a_weaker_one(
        self, monkeypatch
    ):
        """Quality first.

        Exhausting one key down the whole chain would answer a farmer on a
        lite model while a better model sat unused on the second key.
        """
        _clear()
        monkeypatch.setenv("GEMINI_API_KEYS", "key-one,key-two")
        pairs = llm.request_candidates()

        best = pairs[0][1]
        assert pairs[0] == (0, best)
        assert pairs[1] == (1, best), "second key should be tried on the same model"
        assert pairs[2][1] != best, "only then drop to a weaker model"
        _clear()

    def test_a_single_key_still_yields_candidates(self, monkeypatch):
        """The common case -- one key, as the README describes -- must work."""
        _clear()
        monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "only-key")
        pairs = llm.request_candidates()

        assert pairs, "chain must never be empty"
        assert all(k == 0 for k, _ in pairs)
        _clear()

    def test_candidates_survive_no_key_at_all(self, monkeypatch):
        """Misconfiguration should surface as a clear error, not an empty loop."""
        _clear()
        monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        assert llm.request_candidates(), "must still offer something to try"
        _clear()


class TestBackoffOnlyWhereItHelps:
    """Sleeping between candidates cost up to two minutes per turn."""

    def test_no_pause_after_a_rate_limit(self):
        """Pausing does not bring a spent allowance back."""
        exc = Exception("429 RESOURCE_EXHAUSTED. Please retry in 13.9s.")
        for attempt in range(20):
            assert llm.backoff_seconds(exc, attempt) == 0.0

    def test_a_capacity_error_gets_a_short_pause(self):
        """A 503 clears within seconds, so a moment's wait is worth it."""
        exc = Exception("503 UNAVAILABLE. The model is overloaded.")
        assert 0 < llm.backoff_seconds(exc, 0) <= llm.BACKOFF_CAP_S

    def test_the_pause_never_grows_past_the_cap(self):
        """Uncapped, the pause grew with every attempt and the total grew
        quadratically: harmless over four models, ruinous over twenty pairs."""
        exc = Exception("503 UNAVAILABLE")
        for attempt in range(50):
            assert llm.backoff_seconds(exc, attempt) <= llm.BACKOFF_CAP_S

    def test_walking_every_candidate_sleeps_for_bounded_time(self):
        """The property that actually matters to a farmer."""
        rate_limited = Exception("429 RESOURCE_EXHAUSTED")
        overloaded = Exception("503 UNAVAILABLE")
        # The realistic worst case: most candidates out of quota, a few busy.
        total = sum(
            llm.backoff_seconds(overloaded if i % 5 == 0 else rate_limited, i)
            for i in range(20)
        )
        assert total <= 4 * llm.BACKOFF_CAP_S


class TestCooldownsSurviveARestart:
    """Otherwise every restart pays to rediscover the same exhausted models."""

    def test_what_was_learned_is_written_and_read_back(self, tmp_path, monkeypatch):
        _clear()
        monkeypatch.setattr(llm, "_COOLDOWN_FILE", str(tmp_path / "cooldowns.json"))

        llm.note_rate_limited("gemini-3.7-flash", Exception("429. PerDay"), 1)

        # A fresh process: nothing in memory, the file is all there is.
        llm._cooldowns.clear()
        monkeypatch.setattr(llm, "_cooldowns_loaded", False)

        assert llm.is_cooling_down("gemini-3.7-flash", 1)
        assert not llm.is_cooling_down("gemini-3.7-flash", 0)
        _clear()

    def test_an_expired_cooldown_is_not_resurrected(self, tmp_path, monkeypatch):
        """Yesterday's exhaustion must not write off today's allowance."""
        import json
        path = tmp_path / "cooldowns.json"
        path.write_text(json.dumps({"0:gemini-3.7-flash": time.time() - 10}))
        monkeypatch.setattr(llm, "_COOLDOWN_FILE", str(path))
        _clear()
        monkeypatch.setattr(llm, "_cooldowns_loaded", False)

        assert not llm.is_cooling_down("gemini-3.7-flash", 0)
        _clear()

    def test_an_unreadable_file_is_not_fatal(self, tmp_path, monkeypatch):
        """This is an optimisation; it must never stop the service answering."""
        path = tmp_path / "cooldowns.json"
        path.write_text("{ not json")
        monkeypatch.setattr(llm, "_COOLDOWN_FILE", str(path))
        _clear()
        monkeypatch.setattr(llm, "_cooldowns_loaded", False)

        assert llm.is_cooling_down("gemini-3.7-flash", 0) is False
        assert llm.request_candidates(), "must still offer something to try"
        _clear()
