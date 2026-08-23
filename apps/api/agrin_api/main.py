"""
AgriN HTTP API.

Streams assistant turns over Server-Sent Events. SSE rather than WebSockets
because it survives the proxies, captive portals and aggressive mobile
middleboxes common on rural connections, reconnects on its own, and needs no
special handling to work through a CDN.
"""

from __future__ import annotations

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
# Static frontend (production build)
# --------------------------------------------------------------------------

_WEB_DIST = _ROOT / "apps" / "web" / "dist"
if _WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """Serve the SPA, falling back to index.html for client-side routes."""
        candidate = _WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_WEB_DIST / "index.html")
