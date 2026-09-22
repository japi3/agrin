"""
AgriN HTTP API.

Streams assistant turns over Server-Sent Events. SSE rather than WebSockets
because it survives the proxies, captive portals and aggressive mobile
middleboxes common on rural connections, reconnects on its own, and needs no
special handling to work through a CDN.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import storage
from .orchestrator import stream_turn
from .prompts import OPENING_SUGGESTIONS, SUPPORTED_LANGUAGES, ASSISTANT_NAMES
from .i18n import translate_strings
from .speech import synthesise, transcribe
from .vision import diagnose_crop_photo

# Load .env from the repository root before anything reads the environment.
_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Never let the file clobber a variable already set in the real
        # environment -- container orchestrators inject secrets that way.
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

app = FastAPI(
    title="AgriN API",
    description="Regenerative agricultural intelligence for the BRICS AgriN network",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("AGRIN_CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    storage.init_db()


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., description="What the farmer said or typed")
    conversation_id: str | None = None
    farmer_id: str | None = None
    field_id: str | None = None
    language: str | None = None
    # Location supplied inline when the farmer has not yet saved a field.
    latitude: float | None = None
    longitude: float | None = None


class FieldRequest(BaseModel):
    farmer_id: str
    latitude: float
    longitude: float
    name: str | None = None
    area_hectares: float | None = None
    boundary: dict | None = None


class SeasonRequest(BaseModel):
    field_id: str
    crop: str
    sowing_date: str | None = None
    harvest_date: str | None = None
    notes: str | None = None
    yield_reported: str | None = None


# --------------------------------------------------------------------------
# Meta
# --------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Liveness plus a readable report of what is and is not configured.

    Deliberately explicit about credentials: 'why is chat not working' is the
    first question anyone deploying this will have, and it should be
    answerable without reading logs.
    """
    from . import llm

    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {
        "1", "true", "yes"
    }
    return {
        "status": "ok",
        "google_ai": {
            "configured": llm.is_configured(),
            "mode": "vertex_ai" if use_vertex else "ai_studio",
            "model": llm.DEFAULT_MODEL,
            "vision_model": llm.VISION_MODEL,
            # Models currently rate limited, and for how many more seconds.
            # The commonest cause of "why is it slow" is an exhausted free
            # tier, and that should be visible without reading logs.
            "rate_limited": llm.cooldown_status(),
            "project": os.environ.get("GOOGLE_CLOUD_PROJECT") if use_vertex else None,
        },
        "data_sources": {
            "soil": "ISRIC SoilGrids 2.0 (no key required)",
            "weather": "Open-Meteo (no key required)",
        },
        "languages": len(SUPPORTED_LANGUAGES),
    }


@app.get("/api/languages")
async def languages() -> dict[str, Any]:
    return {
        "languages": [
            {
                "code": code,
                "name": name,
                "assistant_name": ASSISTANT_NAMES.get(code, "Saathi"),
                "suggestions": OPENING_SUGGESTIONS.get(code, OPENING_SUGGESTIONS["en"]),
            }
            for code, name in SUPPORTED_LANGUAGES.items()
        ]
    }


# --------------------------------------------------------------------------
# Farmers, fields, seasons
# --------------------------------------------------------------------------

@app.post("/api/farmer")
async def create_farmer(language: str = "en") -> dict[str, str]:
    return {"farmer_id": storage.create_farmer(language=language)}


@app.post("/api/field")
async def create_field(req: FieldRequest) -> dict[str, str]:
    if not (-90 <= req.latitude <= 90 and -180 <= req.longitude <= 180):
        raise HTTPException(400, "Coordinates out of range")
    fid = storage.add_field(
        req.farmer_id, req.latitude, req.longitude,
        name=req.name, area_hectares=req.area_hectares, boundary=req.boundary,
    )
    return {"field_id": fid}


@app.get("/api/field/{farmer_id}")
async def get_fields(farmer_id: str) -> dict[str, Any]:
    return {"fields": storage.list_fields(farmer_id)}


@app.post("/api/season")
async def create_season(req: SeasonRequest) -> dict[str, str]:
    sid = storage.record_season(
        req.field_id, req.crop, req.sowing_date, req.harvest_date,
        req.notes, req.yield_reported,
    )
    return {"season_id": sid}


@app.get("/api/conversations/{farmer_id}")
async def conversations(farmer_id: str) -> dict[str, Any]:
    return {"conversations": storage.list_conversations(farmer_id)}


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Stream one assistant turn.

    The conversation is persisted around the stream: the farmer's message is
    written before generation starts so nothing is lost if the connection
    drops mid-answer, and the assistant's reply is written when the stream
    completes.
    """
    farmer_id = req.farmer_id
    if not farmer_id:
        farmer_id = storage.create_farmer(language=req.language or "en")

    conversation_id = req.conversation_id
    if not conversation_id:
        conversation_id = storage.create_conversation(
            farmer_id, req.field_id, title=req.message[:60]
        )

    # If a bare location came in with the message, persist it as a field so
    # the farmer is never asked twice.
    field_id = req.field_id
    if not field_id:
        with storage.connect() as conn:
            row = conn.execute("SELECT field_id FROM conversation WHERE id = ?",
                               (conversation_id,)).fetchone()
        field_id = row["field_id"] if row and row["field_id"] else None
    if not field_id and req.latitude is not None and req.longitude is not None:
        field_id = storage.add_field(farmer_id, req.latitude, req.longitude)

    history = storage.load_messages(conversation_id)

    user_content: list[dict[str, Any]] = [{"type": "text", "text": req.message}]

    # Give the model the coordinates as context rather than making it ask.
    if field_id:
        f = storage.get_field(field_id)
        if f:
            user_content.append({
                "type": "text",
                "text": (
                    f"[field location: latitude {f['latitude']}, "
                    f"longitude {f['longitude']}]"
                ),
            })

    storage.append_message(conversation_id, "user", user_content)
    history.append({"role": "user", "content": user_content})

    field_context = storage.build_field_context(field_id) if field_id else None
    season_memory = storage.build_season_memory(field_id) if field_id else None

    # Both are cached reads, so this costs far less than the model round trip
    # it saves. It is appended to the stored record rather than replacing it,
    # because the two say different things: one is what the farmer told us,
    # the other is what the ground is doing today.
    if field_id:
        conditions = await _live_conditions(field_id)
        if conditions:
            field_context = f"{field_context}\n{conditions}" if field_context else conditions

    def make_field(lat: float, lon: float, name: str | None) -> str:
        """Create the farmer's field from a place they named, once per conversation."""
        new_id = storage.add_field(farmer_id, lat, lon, name=name)
        with storage.connect() as conn:
            conn.execute("UPDATE conversation SET field_id = ? WHERE id = ?",
                         (new_id, conversation_id))
        return new_id

    async def event_source():
        # Tell the client its identifiers up front so a brand-new session can
        # persist them before the first token arrives.
        yield (
            "data: "
            + json.dumps({
                "type": "session",
                "conversation_id": conversation_id,
                "farmer_id": farmer_id,
                "field_id": field_id,
            })
            + "\n\n"
        )

        collected_text: list[str] = []
        collected_evidence: Any = None

        try:
            async for event in stream_turn(
                history,
                language=req.language,
                field_context=field_context,
                season_memory=season_memory,
                field_id=field_id,
                create_field=make_field,
            ):
                if event.type == "text":
                    collected_text.append(event.data.get("delta", ""))
                elif event.type == "done":
                    collected_evidence = event.data.get("evidence")
                yield event.to_sse()

                if await request.is_disconnected():
                    break
        except Exception as exc:  # noqa: BLE001
            yield (
                "data: "
                + json.dumps({
                    "type": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                })
                + "\n\n"
            )

        if collected_text:
            storage.append_message(
                conversation_id, "assistant",
                [{"type": "text", "text": "".join(collected_text)}],
                evidence=collected_evidence,
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx buffers SSE by default, which delays every token until the
            # response ends -- the exact opposite of what streaming is for.
            "X-Accel-Buffering": "no",
        },
    )


async def _live_conditions(field_id: str) -> str | None:
    """Today's soil and weather for a field, rendered as prompt facts.

    Why this is worth the tokens: answering "does my field need water" was
    three model round trips, not one. The model asked for weather, read it,
    asked for irrigation advice, read that, then wrote the reply -- and each
    round trip is the dominant cost of a reply, measured at roughly three
    seconds against essentially nothing for the tools themselves, which are
    served from cache. Questions like "will it rain this week" or "what is my
    soil" needed a round trip purely to fetch numbers the server already had
    in hand for the side panel.

    So the numbers the panel is already showing the farmer go into the prompt
    too, and those questions are answered directly.

    What is deliberately NOT injected is any irrigation verdict. Advice in
    this platform has to be traceable to the model that produced it, and a
    verdict arrived at from prompt context carries no evidence ledger and no
    card. The tool stays the only route to "water today", and it keeps its
    round trip. This shortens the cheap questions, not the consequential one.

    Failure is silent by design: no conditions block simply means the model
    asks for what it needs, exactly as before.
    """
    field = storage.get_field(field_id)
    if not field:
        return None

    from . import tools as tool_impl

    lat, lon = field["latitude"], field["longitude"]
    try:
        soil, weather = await asyncio.gather(
            tool_impl.get_soil_profile(lat, lon),
            tool_impl.get_weather(lat, lon, days_ahead=7),
            return_exceptions=True,
        )
    except Exception:  # noqa: BLE001
        return None

    lines: list[str] = []

    if not isinstance(soil, BaseException) and soil and soil.get("ok"):
        bits = [f"Soil: {soil['texture']['usda_class']}"]
        ph = soil["chemistry"].get("ph")
        if ph is not None:
            bits.append(f"pH {ph} ({soil['chemistry'].get('ph_class') or 'unclassified'})")
        awc = soil["water_holding"].get("available_water_mm_per_m")
        if awc is not None:
            bits.append(f"holds {awc} mm water per metre")
        if soil.get("confidence") == "low":
            # Stated so the assistant hedges rather than quoting a shaky
            # figure as though it were measured on this field.
            bits.append("soil map uncertain at this location")
        lines.append(", ".join(bits))

    if not isinstance(weather, BaseException) and weather and weather.get("ok"):
        forecast = weather.get("forecast", [])[:7]
        if forecast:
            today = forecast[0]
            lines.append(
                f"Today: {round(today['t_max_c'])}C max, "
                f"{round(today['t_min_c'])}C min, "
                f"reference ET {today.get('reference_et_mm')} mm"
            )
        past = weather.get("rain_last_14_days_mm")
        ahead = weather.get("rain_next_7_days_mm")
        if past is not None or ahead is not None:
            lines.append(
                f"Rain: {past if past is not None else '?'} mm in the last 14 days, "
                f"{ahead if ahead is not None else '?'} mm forecast for the next 7"
            )

    return "\n".join(lines) if lines else None


# --------------------------------------------------------------------------
# Field summary (side panel)
# --------------------------------------------------------------------------

@app.get("/api/field/{field_id}/summary")
async def field_summary(
    field_id: str, include_irrigation: bool = False
) -> dict[str, Any]:
    """Everything the side panel shows about a field, in one call.

    Soil and weather are fetched concurrently and both are cached, so for a
    returning farmer this is effectively instant. Satellite is deliberately
    excluded: a cold NDVI read takes 30-60 seconds and would make the panel
    feel broken every time someone opens the app. It stays available on
    request through the conversation.

    Any part that fails returns null rather than failing the whole call --
    a farmer opening the app should never see an error page because one
    upstream service is slow.
    """
    field = storage.get_field(field_id)
    if not field:
        raise HTTPException(404, "No such field")

    lat, lon = field["latitude"], field["longitude"]
    season = storage.current_season(field_id)

    from . import tools as tool_impl

    soil_task = tool_impl.get_soil_profile(lat, lon)
    weather_task = tool_impl.get_weather(lat, lon, days_ahead=7)
    results = await asyncio.gather(soil_task, weather_task, return_exceptions=True)
    soil, weather = [None if isinstance(r, BaseException) else r for r in results]

    # Everything the farmer told us, kept distinct from what the models
    # computed. A returning farmer should be able to see at a glance what the
    # system actually knows versus what it inferred.
    farm = await tool_impl.get_my_farm(field_id)
    area_ha = field.get("area_hectares")

    summary: dict[str, Any] = {
        "field": {
            "id": field_id,
            "name": field.get("name"),
            "latitude": lat,
            "longitude": lon,
            "area_hectares": area_ha,
            "area_acres": round(area_ha / 0.404686, 2) if area_ha else None,
        },
        "season": season,
        "crops_growing": farm.get("crops_growing", []) if farm.get("ok") else [],
        "last_irrigation": farm.get("last_irrigation") if farm.get("ok") else None,
        "farmer_said": farm.get("farmer_said", []) if farm.get("ok") else [],
        "missing": farm.get("missing", []) if farm.get("ok") else [],
        "photos_on_record": farm.get("photos_on_record", 0) if farm.get("ok") else 0,
        "soil": None,
        "weather": None,
    }

    if soil and soil.get("ok"):
        summary["soil"] = {
            "texture": soil["texture"]["usda_class"],
            "ph": soil["chemistry"]["ph"],
            "ph_class": soil["chemistry"]["ph_class"],
            "organic_carbon_g_per_kg": soil["chemistry"]["organic_carbon_g_per_kg"],
            "available_water_mm_per_m": soil["water_holding"]["available_water_mm_per_m"],
            "confidence": soil.get("confidence"),
        }

    if weather and weather.get("ok"):
        forecast = weather.get("forecast", [])[:7]
        summary["weather"] = {
            "rain_last_14_days_mm": weather.get("rain_last_14_days_mm"),
            "rain_next_7_days_mm": weather.get("rain_next_7_days_mm"),
            "today": forecast[0] if forecast else None,
            "forecast": forecast,
        }

    # Irrigation is the most useful line on the panel and also the slowest to
    # compute -- it runs a full season water balance. Off by default so soil
    # and weather paint immediately; the panel requests it separately and
    # fills it in when it arrives. Blocking the whole panel on it made the
    # app look broken for thirteen seconds on every open.
    if include_irrigation:
        growing = [
            c for c in summary["crops_growing"]
            if c.get("crop") and c.get("sowing_date")
        ]
        if growing:
            advices = await asyncio.gather(*[
                tool_impl.get_irrigation_advice(lat, lon, c["crop"], c["sowing_date"])
                for c in growing
            ], return_exceptions=True)

            per_crop = []
            for crop_entry, advice in zip(growing, advices):
                if isinstance(advice, BaseException) or not advice.get("ok"):
                    continue
                per_crop.append({
                    "crop": crop_entry["crop"],
                    "name": crop_entry.get("name", crop_entry["crop"]),
                    "verdict": advice.get("verdict"),
                    "soil_moisture_percent": advice.get("soil_moisture_percent"),
                    "days_until_stress": advice.get("days_until_stress"),
                    "gross_depth_mm": advice.get("gross_depth_mm"),
                    "growth_stage": advice.get("growth_stage"),
                    "days_after_sowing": advice.get("days_after_sowing"),
                })
            summary["irrigation_by_crop"] = per_crop
            # The most urgent crop drives the headline, since that is the one
            # that needs a decision today.
            urgency = {"irrigate_now": 3, "irrigate_in_days": 2,
                       "wait_for_rain": 1, "no_irrigation_needed": 0}
            if per_crop:
                summary["irrigation"] = max(
                    per_crop, key=lambda c: urgency.get(c["verdict"], 0)
                )

    return summary


# --------------------------------------------------------------------------
# Crop disease diagnosis
# --------------------------------------------------------------------------

@app.post("/api/diagnose")
async def diagnose(
    image: UploadFile = File(...),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    crop: str | None = Form(None),
    sowing_date: str | None = Form(None),
    note: str = Form(""),
    language: str = Form("en"),
    field_id: str | None = Form(None),
    conversation_id: str | None = Form(None),
    farmer_id: str | None = Form(None),
) -> dict[str, Any]:
    """Diagnose a crop photograph.

    Multipart rather than base64-in-JSON: phone photos run 2-5 MB and
    base64 inflates them by a third, which is a real cost on a metered
    rural connection.

    Field details are filled in from stored records when the client does not
    supply them, so a farmer who has already told us their crop and sowing
    date never has to repeat it to get a photo diagnosed.
    """
    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty image")

    # Fall back to the stored field and current season.
    if field_id and (latitude is None or crop is None):
        f = storage.get_field(field_id)
        if f:
            latitude = latitude if latitude is not None else f["latitude"]
            longitude = longitude if longitude is not None else f["longitude"]
            season = storage.current_season(field_id)
            if season:
                crop = crop or season["crop"]
                sowing_date = sowing_date or season.get("sowing_date")

    result = await diagnose_crop_photo(
        image_bytes=data,
        mime_type=image.content_type or "image/jpeg",
        latitude=latitude,
        longitude=longitude,
        crop=crop,
        sowing_date=sowing_date,
        farmer_note=note,
        language=language,
        language_name=SUPPORTED_LANGUAGES.get(language, "English"),
    )

    # Record the diagnosis in the conversation so later questions have it in
    # context -- "is it getting worse?" only means something if we remember.
    if conversation_id and result.get("ok"):
        summary = result.get("farmer_summary", "")
        top = (result.get("candidates") or [{}])[0].get("name", "unknown")
        storage.append_message(
            conversation_id, "user",
            [{"type": "text",
              "text": f"[sent a photo of the crop{': ' + note if note else ''}]"}],
        )
        storage.append_message(
            conversation_id, "assistant",
            [{"type": "text",
              "text": f"[photo diagnosis — most likely {top}] {summary}"}],
            evidence=result.get("evidence"),
        )

    return result


# --------------------------------------------------------------------------
# Speech
# --------------------------------------------------------------------------

class UiStringsRequest(BaseModel):
    language: str
    strings: list[str]


@app.post("/api/ui-strings")
async def ui_strings(req: UiStringsRequest) -> dict[str, Any]:
    """Interface labels in the farmer's chosen language, generated once and cached."""
    return await translate_strings(req.language, req.strings)


class SpeakRequest(BaseModel):
    text: str
    language: str = "en"
    voice: str = "Kore"


@app.post("/api/speak")
async def speak(req: SpeakRequest):
    """Read a reply aloud.

    Returns WAV audio rather than JSON, so the browser can play it directly
    from the response. Deliberately a separate endpoint invoked by the Listen
    button rather than audio streamed alongside every reply: synthesised
    speech is orders of magnitude larger than the text, and a farmer paying
    per megabyte should choose when to spend it.
    """
    from fastapi.responses import Response

    result = await synthesise(
        req.text,
        voice=req.voice,
        language_name=SUPPORTED_LANGUAGES.get(req.language, ""),
    )
    if not result.get("ok"):
        raise HTTPException(503, result.get("abstain_reason", "Speech unavailable"))
    return Response(
        content=result["audio"],
        media_type="audio/wav",
        headers={
            "X-Speech-Model": result.get("model_used", ""),
            # Identical advisory text recurs constantly across farmers, so
            # letting the browser and any CDN cache it is worth real money on
            # a metered connection.
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.post("/api/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form("en"),
) -> dict[str, Any]:
    """Transcribe a recording of the farmer speaking."""
    data = await audio.read()
    result = await transcribe(
        data,
        mime_type=(audio.content_type or "audio/webm").split(";")[0].strip(),
        language_name=SUPPORTED_LANGUAGES.get(language, ""),
    )
    return result


# --------------------------------------------------------------------------
# Static frontend (production build)
# --------------------------------------------------------------------------

_WEB_DIST = _ROOT / "apps" / "web" / "dist"

# Cache policy, which decides whether a deployed fix actually reaches anyone.
#
# Files under /assets carry a content hash in the name, so a given URL never
# changes meaning and can be cached for a year. Everything else -- index.html,
# the service worker, the manifest, the translation bundles -- keeps its name
# across releases, so it must be revalidated. Served without an explicit
# header, index.html only has a Last-Modified date, and browsers are then free
# to guess how long it stays fresh: a browser here went on serving the previous
# build after a rebuild, and no amount of reloading picked up the new one. For
# an app whose users are on patchy rural connections and will never be told to
# hard-refresh, the new build has to arrive on its own.
_IMMUTABLE = "public, max-age=31536000, immutable"
_REVALIDATE = "no-cache"


class _HashedAssets(StaticFiles):
    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = _IMMUTABLE
        return response


if _WEB_DIST.exists():
    app.mount("/assets", _HashedAssets(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """Serve the SPA, falling back to index.html for client-side routes."""
        candidate = _WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate, headers={"Cache-Control": _REVALIDATE})
        return FileResponse(
            _WEB_DIST / "index.html", headers={"Cache-Control": _REVALIDATE}
        )
