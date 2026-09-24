"""
Google Gemini provider layer.

Everything Gemini-specific lives here: client construction, JSON Schema to
`types.Schema` conversion, and translation between our internal message
format and Gemini `Content`/`Part` objects. The orchestrator above it stays
provider-shaped rather than vendor-shaped, which is what made migrating the
platform from one model family to another a single-file change rather than a
rewrite.

Two deployment paths are supported and auto-detected:

  - **AI Studio**: a plain `GEMINI_API_KEY`. Zero setup, free tier, no GCP
    project. This is the path a hackathon team or a small FPO can actually
    use on day one.
  - **Vertex AI**: `GOOGLE_GENAI_USE_VERTEXAI=true` plus a project and
    location, using Application Default Credentials. This is the path a
    state agriculture department deploys on, because it brings VPC-SC, IAM,
    audit logging, regional data residency and committed-use pricing.

Same code, same tools, same prompts. Only the credentials differ.
"""

from __future__ import annotations

import os
import time
from typing import Any

from google import genai
from google.genai import types

# Gemini 2.5 Flash is the default: agronomic reasoning in this platform is
# done by validated models in `packages/agronomy`, not by the LLM, so the
# language model's job is routing, translation and explanation. Flash is
# markedly faster and cheaper at that job, which matters when the user is on
# a 2G connection paying per megabyte. Pro is available for harder
# multi-step diagnosis via AGRIN_MODEL.
DEFAULT_MODEL = os.environ.get("AGRIN_MODEL", "gemini-3.7-flash")
VISION_MODEL = os.environ.get("AGRIN_VISION_MODEL", "gemini-3.7-flash")

# Ordered fallback chain, tried when the preferred model returns 503
# (high demand) or 429 (rate limited).
#
# This is not defensive over-engineering. Capacity for a newly released
# flagship model is genuinely tight, and a public agricultural advisory
# service cannot answer "the model is busy" to a farmer deciding whether to
# irrigate today. Degrading to a slightly older Flash model produces an
# answer of nearly identical quality here, because the agronomy comes from
# validated models rather than from the LLM -- the language model is doing
# routing and translation, which every model in this chain does well.
# gemini-2.5-flash is deliberately absent: it is no longer served to newly
# issued API keys and returns 404. A 404 is not retryable, so having it in the
# chain meant that once the newer models were all busy the loop terminated on
# a hard error and the farmer saw a failure instead of a slightly older model.
# `gemini-flash-latest` anchors the end of the chain because it always
# resolves to a current model, so the chain cannot rot as versions retire.
MODEL_FALLBACK_CHAIN = [
    m.strip()
    for m in os.environ.get(
        "AGRIN_MODEL_FALLBACKS",
        "gemini-3.6-flash,gemini-3.5-flash,gemini-flash-latest",
    ).split(",")
    if m.strip()
]

# Status codes worth retrying on a different model rather than failing.
# Request timeouts in milliseconds.
#
# The SDK sets none by default, so a hanging model request hangs forever.
# Observed during a Gemini slowdown: a 150-second wait before the fallback
# chain gave up, because each of four models sat there with nothing to cut it
# short.
#
# The important detail is that this value reaches httpx, where it is a
# **per-read** timeout -- the maximum gap between bytes -- not a total budget
# for the response. That inverts the intuition for streaming: a long answer
# is safe because every token resets the clock, while a dead stream is caught
# after one quiet interval.
#
# So streaming gets the SHORTER value, not the longer one. A stream silent
# for twenty-five seconds is not slow, it is dead, and waiting ninety seconds
# to conclude that is ninety seconds a farmer spends looking at nothing.
# One-shot calls (speech, vision, transcription) get longer, because there
# the whole response arrives in a single read and genuinely can take a while.
REQUEST_TIMEOUT_MS = int(os.environ.get("AGRIN_LLM_TIMEOUT_MS", "45000"))
STREAM_TIMEOUT_MS = int(os.environ.get("AGRIN_LLM_STREAM_TIMEOUT_MS", "25000"))

# The SDK retries failed requests on its own, with exponential backoff,
# before an error ever reaches this code. Measured: a rate-limited speech
# request took 34.8 seconds to come back, against 3.4 for the same request
# with quota available -- nearly all of it spent in hidden SDK backoff. Chat
# requests paid the same hidden delay, and because the 429 surfaced so late
# the fallback chain and the cooldown tracking could not react to it.
#
# One attempt at the SDK level; this module decides what happens next, which
# is usually trying a different model immediately rather than waiting on the
# exhausted one.
NO_SDK_RETRY = types.HttpRetryOptions(attempts=1)

_RETRYABLE_STATUS = (429, 500, 502, 503, 504)

# A 404 means the model does not exist for this key -- usually a retired
# version. It is not transient, but it IS worth trying the next model in the
# chain rather than failing the request, which is the opposite of how a 400
# (malformed request) should be treated.
_TRY_NEXT_MODEL_STATUS = (404,)


# Models known to be rate limited, with the time their cooldown expires.
#
# Without this every turn re-discovers the same exhausted quota from scratch.
# Measured on a rate-limited key: ten seconds of a farmer looking at a blank
# screen before the chain reached a model with quota left, repeated on every
# single message, because nothing remembered what had just happened.
#
# The free tier meters per model, so a 429 on one says nothing about the
# others -- which is exactly why skipping it and moving on is correct rather
# than backing off globally.
_cooldowns: dict[tuple[int, str], float] = {}

# ...and kept on disk, because otherwise every restart pays to rediscover it.
#
# A model exhausted for the day stays exhausted across a restart, but the
# knowledge did not survive one: the first question after any restart walked
# the whole graveyard again. Measured, that is the difference between a
# fifteen second first answer and a five second one -- and on a laptop where
# Docker starts fresh each morning, it was paid daily.
#
# Expiry times are absolute, so a file written before a restart still means
# what it said afterwards. Failure to read or write is ignored on purpose:
# this is an optimisation, and an unwritable cache directory must not stop
# the service answering.
_COOLDOWN_FILE = os.path.join(
    os.environ.get("AGRIN_CACHE_DIR", "/tmp"), "model_cooldowns.json"
)
_cooldowns_loaded = False


def _load_cooldowns() -> None:
    global _cooldowns_loaded
    if _cooldowns_loaded:
        return
    _cooldowns_loaded = True
    try:
        import json
        with open(_COOLDOWN_FILE) as handle:
            stored = json.load(handle)
    except Exception:  # noqa: BLE001
        return
    now = time.time()
    for key, expiry in stored.items():
        index, _, model = key.partition(":")
        if model and float(expiry) > now:
            _cooldowns[(int(index), model)] = float(expiry)


def _save_cooldowns() -> None:
    try:
        import json
        now = time.time()
        payload = {
            f"{index}:{model}": expiry
            for (index, model), expiry in _cooldowns.items()
            if expiry > now
        }
        os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
        tmp = _COOLDOWN_FILE + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(payload, handle)
        os.replace(tmp, _COOLDOWN_FILE)
    except Exception:  # noqa: BLE001
        pass

# Fallback when the API does not tell us how long to wait.
DEFAULT_COOLDOWN_S = 45.0

# How long to write off a model whose DAILY allowance is gone.
#
# The free tier's binding limit is GenerateRequestsPerDayPerProjectPerModel:
# twenty requests a day per model, not per minute. But the 429 for it still
# carries a retryDelay of ten or twenty seconds, so trusting that delay meant
# a model exhausted until tomorrow was retried every fifteen seconds for the
# rest of the day. Every retry is a wasted round trip, and the tool-calling
# loop makes several model calls per question, so a single farmer question
# walked the graveyard three or four times over.
#
# An hour rather than "until midnight Pacific" because the reset time needs
# timezone data this image does not carry, and because re-probing hourly is
# cheap insurance against having read the quota wrong.
DAILY_QUOTA_COOLDOWN_S = 3600.0


def note_rate_limited(model: str, exc: Exception, key_index: int = 0) -> None:
    """Record that a model is out of quota, and for how long.

    The API supplies a retry delay in the error body; using it rather than a
    fixed guess means quota that frees up in eight seconds is not written off
    for a minute.
    """
    import re
    text = str(exc)

    # A per-day exhaustion is not a pause, it is the end of the day for this
    # model. Its retryDelay describes when the rate limiter will next accept
    # a request, not when the allowance returns, so it must not be believed.
    if "PerDay" in text or "per day" in text.lower():
        _cooldowns[(key_index, model)] = time.time() + DAILY_QUOTA_COOLDOWN_S
        _save_cooldowns()
        return

    seconds = DEFAULT_COOLDOWN_S
    match = re.search(r"retry in ([\d.]+)s", text, re.IGNORECASE)
    if match:
        try:
            seconds = min(300.0, float(match.group(1)) + 1.0)
        except ValueError:
            pass
    _cooldowns[(key_index, model)] = time.time() + seconds
    _save_cooldowns()


def backoff_seconds(exc: Exception, attempt: int) -> float:
    """How long to pause before trying the next candidate after `exc`.

    Zero for a rate limit. A 429 means an allowance is spent -- usually the
    daily one -- and pausing does not bring it back; the next candidate is on
    a different model or key with its own allowance, so the right move is to
    go straight to it.

    A short, capped pause for anything else retryable. A 503 is a capacity
    spike on the provider's side and does clear within seconds, so a moment's
    wait is worth it -- but capped, because the uncapped version grew with
    every attempt: 0.6s, 1.2s, 1.8s and on. Summed over a walk, that is
    quadratic in the number of candidates, which was harmless across four
    models and ruinous across twenty key-and-model pairs -- up to two minutes
    of sleeping per turn, spent entirely on errors that sleeping cannot fix.
    """
    text = str(exc)
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return 0.0
    return min(BACKOFF_CAP_S, 0.6 * (attempt + 1))


# Longest single pause between candidates. See backoff_seconds.
BACKOFF_CAP_S = 2.0


def is_cooling_down(model: str, key_index: int = 0) -> bool:
    _load_cooldowns()
    expiry = _cooldowns.get((key_index, model))
    if expiry is None:
        return False
    if time.time() >= expiry:
        del _cooldowns[(key_index, model)]
        return False
    return True


def cooldown_status() -> dict[str, float]:
    """Remaining cooldown per key and model, for the health endpoint.

    Loads from disk first. Without that, health reported nothing exhausted
    after a restart while the file said otherwise -- the map is filled
    lazily, and health was reading it before anything had asked a question.
    A diagnostic that under-reports is worse than none.
    """
    _load_cooldowns()
    now = time.time()
    return {
        f"{index}:{model}": round(expiry - now, 1)
        for (index, model), expiry in _cooldowns.items() if expiry > now
    }


def api_keys() -> list[str]:
    """Every AI Studio key available, in preference order.

    The free tier meters per project, so a second key on a different account
    is a second full allowance -- twenty requests a day per model again. That
    is the cheapest way to make this service usable, and it is why more than
    one is supported at all.

    GEMINI_API_KEYS takes a comma-separated list; GEMINI_API_KEY stays valid
    for the single-key case, which is what anyone following the README has.
    """
    raw = (
        os.environ.get("GEMINI_API_KEYS", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    return [k.strip() for k in raw.split(",") if k.strip()]


def model_candidates(preferred: str | None = None) -> list[str]:
    """The ordered list of models to try for one request.

    Models still cooling down are moved to the back rather than dropped: if
    every model is rate limited we must still attempt something, and the
    freshest cooldown is the likeliest to have expired.
    """
    first = preferred or DEFAULT_MODEL
    chain = [first] + [m for m in MODEL_FALLBACK_CHAIN if m != first]
    ready = [m for m in chain if not is_cooling_down(m)]
    cooling = [m for m in chain if is_cooling_down(m)]
    return ready + cooling


def request_candidates(preferred: str | None = None) -> list[tuple[int, str]]:
    """Every (key, model) pair to try, best first.

    Ordered model-major: the strongest model is tried on every key before
    dropping to a weaker one. The alternative -- exhausting one key down the
    whole chain first -- would answer a farmer on a lite model while a better
    model sat unused on the second key, and the quality difference matters
    more than which allowance gets spent.

    As with models alone, exhausted pairs are moved to the back rather than
    dropped. Everything we believe about quota is inference from an error
    message, and being wrong must cost a slow answer, never no answer.
    """
    first = preferred or DEFAULT_MODEL
    chain = [first] + [m for m in MODEL_FALLBACK_CHAIN if m != first]
    keys = range(max(1, len(api_keys())))
    pairs = [(k, m) for m in chain for k in keys]
    ready = [p for p in pairs if not is_cooling_down(p[1], p[0])]
    cooling = [p for p in pairs if is_cooling_down(p[1], p[0])]
    return ready + cooling


def is_retryable(exc: Exception) -> bool:
    """Whether an exception warrants falling back to another model.

    Matches on the numeric status where the SDK exposes one, falling back to
    a string check. Deliberately conservative: a 400 (bad request, e.g. a
    malformed tool schema) must NOT be retried against every model in the
    chain, because it will fail identically each time while burning quota
    and adding seconds to the farmer's wait.
    """
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    codes = _RETRYABLE_STATUS + _TRY_NEXT_MODEL_STATUS
    if isinstance(status, int):
        return status in codes
    # Timeouts are transient by definition and should advance the chain: a
    # different model may be served by healthier capacity.
    if isinstance(exc, (TimeoutError,)) or "timeout" in type(exc).__name__.lower():
        return True
    text = str(exc)
    if "timeout" in text.lower() or "timed out" in text.lower():
        return True
    return any(str(code) in text for code in codes)

_JSON_TYPE_TO_GENAI = {
    "string": types.Type.STRING,
    "number": types.Type.NUMBER,
    "integer": types.Type.INTEGER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


class LLMNotConfigured(RuntimeError):
    """Raised when no usable Google AI credentials are present."""


def is_configured() -> bool:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes"}:
        return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    return bool(api_keys())


# Clients are stateless and cheap to hold, but not free to build, and a
# request may switch keys mid-turn when one runs out.
_clients: dict[int, genai.Client] = {}


def client_for(key_index: int) -> genai.Client:
    """The client for one key, built once and reused."""
    if key_index not in _clients:
        _clients[key_index] = build_client(key_index)
    return _clients[key_index]


def build_client(key_index: int = 0) -> genai.Client:
    """Construct a Gemini client for whichever path is configured.

    The error message names the exact variable to set and where to get it.
    'Why is chat not working' is the first question anyone deploying this
    will have, and it should be answerable without reading a stack trace.
    """
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {
        "1", "true", "yes"
    }

    if use_vertex:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
        if not project:
            raise LLMNotConfigured(
                "Vertex AI mode is enabled but GOOGLE_CLOUD_PROJECT is not set. "
                "Set it to your GCP project id, ensure Application Default "
                "Credentials are available (`gcloud auth application-default "
                "login`), and enable the Vertex AI API."
            )
        return genai.Client(
            vertexai=True, project=project, location=location,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS, retry_options=NO_SDK_RETRY),
        )

    keys = api_keys()
    if not keys:
        raise LLMNotConfigured(
            "GEMINI_API_KEY is not set. Get a free key from "
            "https://aistudio.google.com/apikey and add it to the .env file "
            "at the repository root (see .env.example). Alternatively set "
            "GOOGLE_GENAI_USE_VERTEXAI=true with GOOGLE_CLOUD_PROJECT to use "
            "Vertex AI instead."
        )
    return genai.Client(
        api_key=keys[min(key_index, len(keys) - 1)],
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS, retry_options=NO_SDK_RETRY),
    )


def json_schema_to_genai(schema: dict[str, Any]) -> types.Schema:
    """Convert a JSON Schema fragment into a Gemini `types.Schema`.

    Written as a converter rather than maintaining two parallel sets of tool
    definitions. Duplicated schemas drift: a parameter gets added to one and
    not the other, and the failure appears as the model passing an argument
    the implementation does not accept, which is tedious to trace back.

    Gemini's schema dialect is a subset of JSON Schema, so unsupported
    keywords are dropped rather than passed through -- sending an unknown
    field makes the API reject the whole tool list, disabling every tool
    rather than degrading one.
    """
    json_type = schema.get("type", "string")
    genai_type = _JSON_TYPE_TO_GENAI.get(json_type, types.Type.STRING)

    kwargs: dict[str, Any] = {"type": genai_type}

    if description := schema.get("description"):
        kwargs["description"] = description

    if enum := schema.get("enum"):
        kwargs["enum"] = [str(v) for v in enum]

    if genai_type == types.Type.OBJECT:
        properties = schema.get("properties") or {}
        if properties:
            kwargs["properties"] = {
                name: json_schema_to_genai(sub) for name, sub in properties.items()
            }
        if required := schema.get("required"):
            kwargs["required"] = list(required)

    if genai_type == types.Type.ARRAY:
        items = schema.get("items")
        # Gemini requires an item schema for arrays; default to string rather
        # than emitting an array with no items, which the API rejects.
        kwargs["items"] = json_schema_to_genai(items or {"type": "string"})

    return types.Schema(**kwargs)


def build_tools(tool_definitions: list[dict[str, Any]]) -> list[types.Tool]:
    """Convert our tool definitions into a Gemini `Tool` with declarations.

    All declarations go into a single Tool: Gemini treats each Tool as a
    separate group and parallel function calling works within a group, which
    is what lets the model fetch soil and weather in one round instead of two.
    """
    declarations = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=json_schema_to_genai(t["input_schema"]),
        )
        for t in tool_definitions
    ]
    return [types.Tool(function_declarations=declarations)]


async def probe_models() -> list[tuple[int, str, str]]:
    """Ask every key and model whether it still has quota, and remember.

    The cooldown map is only ever filled by a farmer's question failing, so
    the first question of the day pays to discover which models are spent --
    fifteen seconds against five, measured. Run before a demo, this moves
    that cost off the person asking.

    It is not free: a probe against a model that still has quota spends one
    of that model's twenty daily requests. Against one already exhausted it
    costs nothing that was not already gone. Twenty probes to save the first
    real question is a trade worth making before a demo and not worth making
    casually, which is why this is a script step rather than something that
    runs at startup.
    """
    findings: list[tuple[int, str, str]] = []
    for key_index, model in request_candidates():
        try:
            client = client_for(key_index)
            await client.aio.models.generate_content(
                model=model,
                contents="ok",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            findings.append((key_index, model, "ready"))
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "429" in text or "RESOURCE_EXHAUSTED" in text:
                note_rate_limited(model, exc, key_index)
                findings.append((key_index, model, "out of quota"))
            else:
                code = "503" if "503" in text else type(exc).__name__
                findings.append((key_index, model, code))
    return findings


def build_config(
    system_instruction: str,
    tool_definitions: list[dict[str, Any]] | None = None,
    temperature: float = 0.4,
    max_output_tokens: int = 2048,
    streaming: bool = False,
) -> types.GenerateContentConfig:
    """Assemble the generation config.

    Temperature is held low. This assistant's job is to convey numbers that
    came from validated models accurately and in the farmer's own language,
    not to be inventive. Creative variance here shows up as paraphrased
    quantities and hedged advice.
    """
    kwargs: dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        # Safety settings are left at defaults. Agricultural chemistry
        # questions -- pesticide dosages, herbicide handling -- are legitimate
        # and must not be filtered as harmful content, but they are also
        # genuinely dangerous to get wrong, so the prompt requires the model
        # to defer to label instructions and local extension advice rather
        # than improvising a rate.
    }
    if streaming:
        # Deliberately shorter than the client default. This is a per-read
        # timeout, so it bounds the silence between tokens rather than the
        # length of the answer: a genuinely long reply keeps resetting it,
        # and a stalled one fails in twenty-five seconds instead of ninety.
        kwargs["http_options"] = types.HttpOptions(timeout=STREAM_TIMEOUT_MS, retry_options=NO_SDK_RETRY)

    if tool_definitions:
        kwargs["tools"] = build_tools(tool_definitions)
        # Let the model decide when to call a tool. Forcing ANY would make it
        # call a tool for "hello", which is both slow and absurd.
        kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable=True  # We run the tool loop ourselves, for streaming + evidence.
        )
    return types.GenerateContentConfig(**kwargs)


# --------------------------------------------------------------------------
# Message conversion
# --------------------------------------------------------------------------

def user_text(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def user_image(image_bytes: bytes, mime_type: str, caption: str = "") -> types.Content:
    """Build a multimodal turn carrying a photograph.

    This is the crop-disease path: a farmer photographs a leaf and Gemini's
    vision capability reads it. Passing the image inline (rather than via
    Files API) keeps the round trip short for the common case of a single
    small phone photo.
    """
    parts: list[types.Part] = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    ]
    if caption:
        parts.append(types.Part(text=caption))
    return types.Content(role="user", parts=parts)


def function_response(name: str, payload: dict[str, Any]) -> types.Part:
    """Wrap a tool result as a Gemini function response part."""
    return types.Part.from_function_response(name=name, response=payload)


def to_contents(messages: list[dict[str, Any]]) -> list[types.Content]:
    """Convert stored conversation history into Gemini `Content` objects.

    Our stored format is provider-neutral: a list of {role, content} where
    content is a list of typed blocks. Gemini uses 'model' where we store
    'assistant', and function calls/responses are Parts rather than separate
    block types.
    """
    contents: list[types.Content] = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        blocks = message["content"]
        if isinstance(blocks, str):
            contents.append(types.Content(role=role, parts=[types.Part(text=blocks)]))
            continue

        parts: list[types.Part] = []
        for block in blocks:
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                parts.append(types.Part(text=block["text"]))
            elif btype == "function_call":
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            name=block["name"], args=block.get("args") or {}
                        )
                    )
                )
            elif btype == "function_response":
                parts.append(
                    function_response(block["name"], block.get("response") or {})
                )
            elif btype == "image" and block.get("data"):
                parts.append(
                    types.Part.from_bytes(
                        data=block["data"],
                        mime_type=block.get("mime_type", "image/jpeg"),
                    )
                )
        if parts:
            contents.append(types.Content(role=role, parts=parts))
    return contents


def friendly_error(exc: Exception) -> tuple[str, str]:
    """Turn an upstream failure into something a farmer can act on.

    Returns (message, kind).

    Raw API errors are unusable here. A farmer standing in a field sees a
    JSON blob about `generativelanguage.googleapis.com` quota metrics and
    learns nothing except that the tool is broken. Worse, it leaks internal
    detail that means nothing to them and everything to nobody.

    Each case says what happened in plain words and what to do next.
    """
    # Inspect the chained causes too. httpx and the SDK both wrap errors, and
    # a 429 raised inside a stream can surface as a transport error whose own
    # string carries no status -- which is exactly how a rate limit ended up
    # reported to farmers as the generic "something went wrong".
    chain = [exc]
    seen = {id(exc)}
    cursor = exc
    for _ in range(5):
        cursor = getattr(cursor, "__cause__", None) or getattr(cursor, "__context__", None)
        if cursor is None or id(cursor) in seen:
            break
        seen.add(id(cursor))
        chain.append(cursor)

    text = " ".join(str(e) for e in chain)
    # A timeout carries no HTTP status, so it must be matched on type or text
    # or it falls through to the generic "something went wrong" -- which is
    # exactly what a farmer saw during a Gemini slowdown.
    if any(
        type(e).__name__ in {"ReadTimeout", "ConnectTimeout", "TimeoutException",
                             "PoolTimeout", "WriteTimeout", "TimeoutError"}
        for e in chain
    ):
        return (
            "The AI service is not responding right now. Please try again in "
            "a moment — your field details are saved.",
            "timeout",
        )
    status = None
    for e in chain:
        status = getattr(e, "code", None) or getattr(e, "status_code", None)
        if isinstance(status, int):
            break

    def has(code: int) -> bool:
        return status == code or str(code) in text

    if has(429):
        # Extract the retry delay the API supplies, so the wait is concrete
        # rather than an open-ended "try later".
        import re
        match = re.search(r"retry in ([\d.]+)s", text, re.IGNORECASE)
        wait = ""
        if match:
            seconds = int(float(match.group(1))) + 1
            wait = f" Please try again in about {seconds} seconds."
        return (
            "Too many questions have come in at once and the service is "
            "briefly rate limited." + wait,
            "rate_limited",
        )
    if has(503) or has(504):
        return (
            "The service is very busy right now. Please try again in a "
            "moment — your field details are saved.",
            "busy",
        )
    if has(401) or has(403):
        return (
            "This installation is not set up correctly: the Google AI key is "
            "missing or not authorised. Whoever runs this service needs to "
            "check it.",
            "auth",
        )
    if has(404):
        return (
            "The configured AI model is unavailable. Whoever runs this "
            "service needs to update the model setting.",
            "config",
        )
    if has(400):
        return (
            "Something in that request could not be processed. Please try "
            "rephrasing your question.",
            "bad_request",
        )
    # Timeouts and connection resets are common on rural links and are worth
    # distinguishing from a genuine service failure, because the advice
    # differs: wait and retry versus report it to whoever runs the service.
    lowered = text.lower()
    if any(w in lowered for w in ("timeout", "timed out", "connect", "reset")):
        return (
            "The connection to the AI service dropped. Please try again — "
            "your field details are saved.",
            "network",
        )
    return (
        "Something went wrong reaching the AI service. Please try again.",
        "upstream",
    )
