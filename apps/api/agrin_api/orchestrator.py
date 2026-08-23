"""
The agent loop: streaming conversation with Gemini function calling.

Responsibilities, in order of importance:

1. Stream text to the farmer as it is generated, so the first words appear in
   under a second even when a tool call behind them takes ten. On a slow
   rural connection, perceived latency is the difference between a tool that
   gets used and one that does not.
2. Execute tool calls concurrently when Gemini requests several at once. Soil
   and weather are independent; fetching them serially doubles the wait for
   no reason.
3. Accumulate an Evidence Ledger across the whole turn, so the interface can
   show exactly which soil survey, weather model and satellite pass produced
   the answer.
4. Fail visibly. A tool that errors reports the error to the model *and* to
   the ledger; it never silently returns empty and lets the model improvise.

Automatic function calling is deliberately disabled in the config. The SDK
can run the tool loop itself, but doing so hides tool execution from the
stream -- we would lose the ability to show "checking your soil..." while it
happens, and lose the evidence records entirely. Running the loop here costs
a little more code and buys both.

The loop is bounded. A model that keeps calling tools without concluding is
a bug, not a feature, and an unbounded loop against a metered API is how a
demo becomes an invoice.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from google.genai import types

from . import llm
from . import tools as tool_impl
from .prompts import build_system_prompt
from .schemas import TOOL_DEFINITIONS

MAX_TOOL_ROUNDS = 6

# Maps tool names to implementations. Kept explicit rather than resolved by
# getattr so that a model hallucinating a plausible tool name gets a clean
# error instead of reaching an arbitrary module attribute.
TOOL_REGISTRY: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "get_soil_profile": tool_impl.get_soil_profile,
    "get_weather": tool_impl.get_weather,
    "get_irrigation_advice": tool_impl.get_irrigation_advice,
    "assess_crop_suitability": tool_impl.assess_crop_suitability,
    "compare_regenerative_practices": tool_impl.compare_regenerative_practices,
}


@dataclass
class Event:
    """One server-sent event to the browser."""
    type: str
    data: dict[str, Any]

    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': self.type, **self.data}, default=str)}\n\n"


@dataclass
class TurnState:
    evidence: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    started_at: float = field(default_factory=time.time)


async def _run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute one tool, converting any failure into a structured result.

    Exceptions are caught and returned as data rather than propagated. The
    model needs to *see* that the soil service timed out so it can tell the
    farmer honestly; a raised exception would abort the turn and show a blank
    screen instead.
    """
    impl = TOOL_REGISTRY.get(name)
    if impl is None:
        return {
            "ok": False,
            "error": f"No such tool: {name}",
            "abstain_reason": (
                "That capability does not exist. Do not attempt to answer the "
                "question from your own knowledge if it requires "
                "field-specific numbers."
            ),
        }
    try:
        return await asyncio.wait_for(impl(**args), timeout=90.0)
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "error": "timeout",
            "abstain_reason": (
                "The data service did not respond in time. Tell the farmer the "
                "lookup failed and offer to try again, rather than estimating "
                "the answer yourself."
            ),
        }
    except TypeError as exc:
        return {"ok": False, "error": f"Invalid arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - surface everything to the model
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "abstain_reason": "This lookup failed. Say so plainly rather than guessing.",
        }


def _card_for(name: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """Derive a renderable UI card from a tool result.

    This is what keeps the interface conversational rather than a dashboard:
    visuals appear inline, in the flow of the answer, only when a tool
    produced something worth seeing. Nothing is rendered speculatively.
    """
    if not result.get("ok"):
        return None

    if name == "get_weather":
        return {
            "card": "weather",
            "days": result.get("forecast", [])[:10],
            "rain_next_7_days_mm": result.get("rain_next_7_days_mm"),
            "rain_last_14_days_mm": result.get("rain_last_14_days_mm"),
        }
    if name == "get_soil_profile":
        return {
            "card": "soil",
            "texture": result.get("texture"),
            "chemistry": result.get("chemistry"),
            "water_holding": result.get("water_holding"),
            "confidence": result.get("confidence"),
        }
    if name == "get_irrigation_advice":
        return {
            "card": "irrigation",
            "verdict": result.get("verdict"),
            "net_depth_mm": result.get("net_depth_mm"),
            "gross_depth_mm": result.get("gross_depth_mm"),
            "soil_moisture_percent": result.get("soil_moisture_percent"),
            "days_until_stress": result.get("days_until_stress"),
            "growth_stage": result.get("growth_stage"),
            "crop_name": result.get("crop_name"),
            "forecast_effective_rain_mm": result.get("forecast_effective_rain_mm"),
        }
    if name == "assess_crop_suitability":
        return {
            "card": "suitability",
            "site": result.get("site"),
            "assessments": result.get("assessments", [])[:6],
        }
    if name == "compare_regenerative_practices":
        return {
            "card": "carbon",
            "initial_soc_t_per_ha": result.get("initial_soc_t_per_ha"),
            "scenarios": result.get("scenarios"),
            "years_projected": result.get("years_projected"),
            "best_scenario": result.get("best_scenario"),
        }
    return None


def _split_evidence(result: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Split a tool result into the payload the model sees and the evidence.

    Provenance blocks are large and the model does not need them to reason --
    it needs the numbers. Sending them anyway wastes context on every turn and
    tempts the model into reciting citations aloud, which is exactly the
    dashboard-flavoured output we are avoiding. The ledger keeps them.
    """
    evidence = result.get("evidence")
    payload = {k: v for k, v in result.items() if k != "evidence"}
    return payload, evidence


async def stream_turn(
    messages: list[dict[str, Any]],
    language: str | None = None,
    field_context: str | None = None,
    season_memory: str | None = None,
    model: str | None = None,
) -> AsyncIterator[Event]:
    """Run one assistant turn, yielding events as they occur."""
    state = TurnState()

    try:
        client = llm.build_client()
    except llm.LLMNotConfigured as exc:
        yield Event("error", {"message": str(exc), "kind": "not_configured"})
        return

    system = build_system_prompt(language, field_context, season_memory)
    config = llm.build_config(system, TOOL_DEFINITIONS)
    contents = llm.to_contents(messages)
    model_id = model or llm.DEFAULT_MODEL

    for _round in range(MAX_TOOL_ROUNDS):
        collected_text: list[str] = []
        function_calls: list[types.FunctionCall] = []
        stream = None

        # Try the preferred model, falling back down the chain on transient
        # capacity errors.
        #
        # The retry wraps stream *consumption*, not just creation: the SDK
        # issues the request lazily, so a 503 surfaces while iterating rather
        # than at the await. Wrapping only the call looks correct and silently
        # never fires.
        #
        # Fallback is allowed only while nothing has been shown to the farmer
        # this round. Once words are on screen we do not restart the answer
        # under a different model mid-sentence -- a reply that visibly rewrites
        # itself is worse than one that errors honestly.
        model_parts: list[types.Part] = []
        succeeded = False
        last_error: Exception | None = None

        for attempt, candidate in enumerate(llm.model_candidates(model_id)):
            model_parts = []
            collected_text = []
            function_calls = []
            emitted_this_round = False

            try:
                stream = await client.aio.models.generate_content_stream(
                    model=candidate, contents=contents, config=config
                )
                async for chunk in stream:
                    # Text and function calls can both appear across chunks,
                    # so walk parts explicitly rather than relying on
                    # chunk.text, which is None when a function call is
                    # present.
                    for cand in chunk.candidates or []:
                        content = cand.content
                        if not content or not content.parts:
                            continue
                        for part in content.parts:
                            # Parts are preserved verbatim, never rebuilt.
                            #
                            # Gemini 3.x thinking models attach an encrypted
                            # `thought_signature` to function-call parts,
                            # carrying reasoning state across turns.
                            # Reconstructing a Part from name and args drops
                            # it, and the next request fails with "Function
                            # call is missing a thought_signature". The docs
                            # are explicit: resend blocks exactly as received.
                            model_parts.append(part)

                            # Thought summaries stay in history but are never
                            # shown to the farmer as the answer.
                            if getattr(part, "thought", False):
                                continue

                            if getattr(part, "text", None):
                                collected_text.append(part.text)
                                emitted_this_round = True
                                yield Event("text", {"delta": part.text})
                            if getattr(part, "function_call", None):
                                function_calls.append(part.function_call)

                if candidate != model_id:
                    yield Event(
                        "model_fallback",
                        {"requested": model_id, "using": candidate},
                    )
                    model_id = candidate
                succeeded = True
                break

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if llm.is_retryable(exc) and not emitted_this_round:
                    # Brief backoff before the next model; capacity spikes
                    # are usually short.
                    await asyncio.sleep(0.6 * (attempt + 1))
                    continue
                break

        if not succeeded:
            yield Event(
                "error",
                {
                    "message": (
                        f"Gemini request failed: {type(last_error).__name__}: "
                        f"{last_error}"
                    ),
                    "kind": "upstream",
                },
            )
            return

        if model_parts:
            contents.append(types.Content(role="model", parts=model_parts))

        if not function_calls:
            yield Event(
                "done",
                {
                    "evidence": state.evidence,
                    "cards": state.cards,
                    "tool_calls": state.tool_calls,
                    "elapsed_ms": int((time.time() - state.started_at) * 1000),
                    "stop_reason": "end_turn",
                },
            )
            return

        # Announce every tool before running, so the UI can show progress.
        for fc in function_calls:
            yield Event(
                "tool_start", {"name": fc.name, "input": dict(fc.args or {})}
            )

        results = await asyncio.gather(
            *(_run_tool(fc.name, dict(fc.args or {})) for fc in function_calls)
        )
        state.tool_calls += len(function_calls)

        response_parts: list[types.Part] = []
        for fc, result in zip(function_calls, results):
            payload, evidence = _split_evidence(result)

            if evidence:
                state.evidence.append(
                    {
                        "tool": fc.name,
                        "input": dict(fc.args or {}),
                        "evidence": evidence,
                    }
                )

            card = _card_for(fc.name, result)
            if card:
                state.cards.append(card)
                yield Event("card", card)

            yield Event(
                "tool_result",
                {
                    "name": fc.name,
                    "ok": bool(result.get("ok")),
                    "abstain_reason": result.get("abstain_reason"),
                    "error": result.get("error"),
                },
            )

            response_parts.append(llm.function_response(fc.name, payload))

        contents.append(types.Content(role="user", parts=response_parts))

    yield Event(
        "done",
        {
            "evidence": state.evidence,
            "cards": state.cards,
            "tool_calls": state.tool_calls,
            "elapsed_ms": int((time.time() - state.started_at) * 1000),
            "stop_reason": "max_tool_rounds",
            "note": (
                f"Stopped after {MAX_TOOL_ROUNDS} rounds of tool use to avoid "
                f"an unbounded loop."
            ),
        },
    )
