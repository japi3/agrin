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
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)

# A 404 means the model does not exist for this key -- usually a retired
# version. It is not transient, but it IS worth trying the next model in the
# chain rather than failing the request, which is the opposite of how a 400
# (malformed request) should be treated.
_TRY_NEXT_MODEL_STATUS = (404,)


def model_candidates(preferred: str | None = None) -> list[str]:
    """The ordered list of models to try for one request."""
    first = preferred or DEFAULT_MODEL
    chain = [first] + [m for m in MODEL_FALLBACK_CHAIN if m != first]
    return chain


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
    text = str(exc)
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
    return bool(
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )


def build_client() -> genai.Client:
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
        return genai.Client(vertexai=True, project=project, location=location)

    api_key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if not api_key:
        raise LLMNotConfigured(
            "GEMINI_API_KEY is not set. Get a free key from "
            "https://aistudio.google.com/apikey and add it to the .env file "
            "at the repository root (see .env.example). Alternatively set "
            "GOOGLE_GENAI_USE_VERTEXAI=true with GOOGLE_CLOUD_PROJECT to use "
            "Vertex AI instead."
        )
    return genai.Client(api_key=api_key)


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


def build_config(
    system_instruction: str,
    tool_definitions: list[dict[str, Any]] | None = None,
    temperature: float = 0.4,
    max_output_tokens: int = 2048,
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
