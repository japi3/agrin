"""
Tests that one question has an end.

Every timeout in this system used to be local. A model attempt had one, a
round of attempts had one, a tool call had ninety seconds. Nothing counted
the whole turn, so the limits multiplied instead of binding: six rounds,
each allowed a model budget and a fresh ninety seconds of tool time.

That is not a theoretical ceiling. With two withdrawn models at the head of
the fallback chain, a question on the deployed service took 252 seconds and
then returned "the service is very busy" -- four minutes of waiting that
bought nothing, because no model that worked was ever reached. A farmer will
not wait four minutes for advice about irrigation, and being made to wait
four minutes to be told the service is busy is worse than being told at
forty-five seconds, because the time is spent either way and only one of
them leaves time to try again.

Two things are checked here, and the second matters as much as the first: a
tool must not be allowed to outlive the turn it belongs to. A lookup still
running when the budget expires cannot have its answer used, so waiting on
it only delays telling the farmer something went wrong.
"""

import asyncio
import time

from agrin_api import orchestrator


class TestTheBudgetExists:
    def test_a_turn_is_bounded(self):
        assert orchestrator.TURN_BUDGET_S > 0

    def test_it_is_shorter_than_the_worst_case_it_replaces(self):
        """Six rounds of a model budget plus a tool wait each. If the turn
        budget is not well under that, it is decoration."""
        unbounded_worst_case = orchestrator.MAX_TOOL_ROUNDS * (
            orchestrator.MODEL_ATTEMPT_BUDGET_S + 90.0
        )
        assert orchestrator.TURN_BUDGET_S < unbounded_worst_case / 2

    def test_it_is_long_enough_for_a_real_question(self):
        """A question needing soil, weather and the water balance takes
        10-30 seconds on a good day. Cutting those off would trade a slow
        answer for no answer, which is not an improvement."""
        assert orchestrator.TURN_BUDGET_S >= 60


class TestAToolCannotOutliveItsTurn:
    """`_run_tool` takes a deadline and must not wait past it."""

    async def test_a_tool_is_cut_off_at_the_turn_deadline(self):
        async def never_returns(**_kwargs):
            await asyncio.sleep(60)

        original = orchestrator.TOOL_REGISTRY.get("get_weather")
        orchestrator.TOOL_REGISTRY["get_weather"] = never_returns
        try:
            started = time.time()
            result = await orchestrator._run_tool(
                "get_weather", {}, deadline=time.time() + 0.5
            )
            elapsed = time.time() - started
        finally:
            if original is not None:
                orchestrator.TOOL_REGISTRY["get_weather"] = original

        assert result["ok"] is False
        assert result["error"] == "timeout"
        # Well under the 90s a tool gets when no deadline is given.
        assert elapsed < 5, f"waited {elapsed:.1f}s past a 0.5s deadline"

    async def test_an_expired_deadline_does_not_wait_at_all(self):
        """A deadline already in the past must not become a negative or
        infinite timeout."""
        async def never_returns(**_kwargs):
            await asyncio.sleep(60)

        original = orchestrator.TOOL_REGISTRY.get("get_weather")
        orchestrator.TOOL_REGISTRY["get_weather"] = never_returns
        try:
            started = time.time()
            result = await orchestrator._run_tool(
                "get_weather", {}, deadline=time.time() - 30
            )
            elapsed = time.time() - started
        finally:
            if original is not None:
                orchestrator.TOOL_REGISTRY["get_weather"] = original

        assert result["ok"] is False
        assert elapsed < 5

    async def test_without_a_deadline_a_tool_still_runs_normally(self):
        """The deadline is optional; omitting it must not break the call."""
        async def quick(**_kwargs):
            return {"ok": True, "value": 42}

        original = orchestrator.TOOL_REGISTRY.get("get_weather")
        orchestrator.TOOL_REGISTRY["get_weather"] = quick
        try:
            result = await orchestrator._run_tool("get_weather", {})
        finally:
            if original is not None:
                orchestrator.TOOL_REGISTRY["get_weather"] = original

        assert result["ok"] is True

    async def test_the_farmer_is_told_to_retry_rather_than_given_a_guess(self):
        """What the model is handed when a lookup times out decides whether
        the farmer gets an honest failure or an invented number."""
        async def never_returns(**_kwargs):
            await asyncio.sleep(60)

        original = orchestrator.TOOL_REGISTRY.get("get_weather")
        orchestrator.TOOL_REGISTRY["get_weather"] = never_returns
        try:
            result = await orchestrator._run_tool(
                "get_weather", {}, deadline=time.time() + 0.5
            )
        finally:
            if original is not None:
                orchestrator.TOOL_REGISTRY["get_weather"] = original

        assert "estimating" in result["abstain_reason"].lower()
