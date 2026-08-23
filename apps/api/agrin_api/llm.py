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
DEFAULT_MODEL = os.environ.get("AGRIN_MODEL", "gemini-2.5-flash")
VISION_MODEL = os.environ.get("AGRIN_VISION_MODEL", "gemini-2.5-flash")

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
