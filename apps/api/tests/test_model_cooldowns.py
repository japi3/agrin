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

        remaining = llm._cooldowns["gemini-3.8-flash"] - time.time()
        # Emphatically not the 14 seconds the error suggests.
        assert remaining > 600
        assert llm.is_cooling_down("gemini-3.8-flash")

    def test_a_genuine_short_pause_still_uses_the_supplied_delay(self):
        """Per-minute limits do free up quickly, and must not be over-punished."""
        _clear()
        exc = Exception("429 RESOURCE_EXHAUSTED. Please retry in 8.0s.")
        llm.note_rate_limited("gemini-3.7-flash", exc)

        remaining = llm._cooldowns["gemini-3.7-flash"] - time.time()
        assert 5 < remaining < 30

    def test_an_error_with_no_delay_falls_back_to_the_default(self):
        _clear()
        llm.note_rate_limited("gemini-3.5-flash", Exception("429 RESOURCE_EXHAUSTED"))

        remaining = llm._cooldowns["gemini-3.5-flash"] - time.time()
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
