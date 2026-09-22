"""
Interface translation.

The assistant's replies are generated in the farmer's language, but the
interface around them -- card headings, the farm panel, buttons -- was fixed
English. A farmer who chose Punjabi saw "Water your field today" and "Soil
holding 63% of its water" in a language they may not read, which defeats the
choice.

Hand-maintaining a hundred strings in twenty-four languages is not realistic
for this project, so the English strings are translated once per language by
Gemini, in a single request, and kept on disk for good. After the first
visitor in a language there is no further cost and no delay. Strings missing
from the cache fall back to English rather than blocking the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from google.genai import types

from . import llm
from .prompts import SUPPORTED_LANGUAGES

CACHE_DIR = Path(__import__("os").environ.get(
    "AGRIN_CACHE_DIR", Path.home() / ".cache" / "agrin")) / "ui_strings"

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _cache_path(language: str) -> Path:
    return CACHE_DIR / f"{language}.json"


def _load(language: str) -> dict[str, str]:
    try:
        return json.loads(_cache_path(language).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(language: str, table: dict[str, str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _cache_path(language).with_suffix(".tmp")
    tmp.write_text(json.dumps(table, ensure_ascii=False, indent=1))
    tmp.replace(_cache_path(language))


def _placeholders_intact(source: str, translated: str) -> bool:
    """A translation that drops or renames {n} would render as broken text."""
    return sorted(_PLACEHOLDER.findall(source)) == sorted(_PLACEHOLDER.findall(translated))


_locks: dict[str, "asyncio.Lock"] = {}


async def translate_strings(language: str, strings: list[str]) -> dict[str, Any]:
    """Return translations for `strings`, generating any that are missing.

    Serialised per language: each call reads the cache, translates what is
    missing and writes the whole table back, so two concurrent calls would
    each overwrite the other's additions.
    """
    import asyncio
    if language == "en" or language not in SUPPORTED_LANGUAGES:
        return {"ok": True, "translations": {}}
    lock = _locks.setdefault(language, asyncio.Lock())
    async with lock:
        return await _translate_locked(language, strings)


async def _translate_locked(language: str, strings: list[str]) -> dict[str, Any]:

    table = _load(language)
    wanted = [s for s in dict.fromkeys(strings) if s and s not in table][:300]
    if not wanted:
        return {"ok": True, "translations": {s: table[s] for s in strings if s in table}}

    name = SUPPORTED_LANGUAGES[language]
    prompt = (
        f"Translate these user-interface strings from a farming app into {name}, "
        f"written in its native script.\n"
        f"The readers are farmers, many with little schooling: use the plain "
        f"everyday words people actually say, not formal or bureaucratic "
        f"vocabulary. Keep them as short as the English. Keep units such as "
        f"mm, %, °, pH and crop names like bajra or kharif as a farmer would say "
        f"them. Keep every placeholder in curly braces, such as {{n}}, exactly as "
        f"it is.\n"
        f"Return a JSON object mapping each number to its translation.\n\n"
        + "\n".join(f"{i}: {s}" for i, s in enumerate(wanted))
    )

    try:
        client = llm.build_client()
    except llm.LLMNotConfigured as exc:
        return {"ok": False, "translations": {}, "reason": str(exc)}

    for key_index, model in llm.request_candidates():
        try:
            client = llm.client_for(key_index)
            response = await client.aio.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1, response_mime_type="application/json"),
            )
            result = json.loads(response.text)
            break
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                llm.note_rate_limited(model, exc, key_index)
            if llm.is_retryable(exc):
                continue
            return {"ok": False, "translations": {s: table[s] for s in strings if s in table}}
    else:
        return {"ok": False, "translations": {s: table[s] for s in strings if s in table}}

    for key, value in result.items():
        try:
            source = wanted[int(key)]
        except (ValueError, IndexError):
            continue
        if isinstance(value, str) and value.strip() and _placeholders_intact(source, value):
            table[source] = value.strip()
    _save(language, table)
    return {"ok": True, "translations": {s: table[s] for s in strings if s in table}}
