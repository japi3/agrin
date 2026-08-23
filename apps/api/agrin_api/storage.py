"""
Persistence for farmers, fields, conversations and season history.

SQLite by default. That is a deliberate choice rather than a shortcut: the
realistic first deployment of this platform is a single container run by a
state agriculture department or an FPO with no database administrator, and a
system that needs a managed Postgres before it can answer one question does
not get deployed. The repository interface below is narrow enough that
swapping in Postgres with PostGIS is a driver change, not a rewrite — which
is what the multi-country federation deployment will want.

The schema carries one idea the rest of the platform depends on:
**longitudinal field memory**. A field is not a coordinate, it is a place
with a history — what was grown, when it was sown, what went wrong, what the
weather did. That history is what lets the assistant say "last kharif you
sowed late and lost three weeks to blast" instead of answering every question
from a cold start.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(
    __import__("os").environ.get(
        "AGRIN_DB", Path.home() / ".local" / "share" / "agrin" / "agrin.db"
    )
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmer (
    id            TEXT PRIMARY KEY,
    display_name  TEXT,
    language      TEXT NOT NULL DEFAULT 'en',
    country       TEXT,
    phone         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS field (
    id            TEXT PRIMARY KEY,
    farmer_id     TEXT NOT NULL REFERENCES farmer(id) ON DELETE CASCADE,
    name          TEXT,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    area_hectares REAL,
    -- GeoJSON polygon when the farmer drew a boundary rather than a pin.
    boundary_json TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_field_farmer ON field(farmer_id);

CREATE TABLE IF NOT EXISTS season (
    id            TEXT PRIMARY KEY,
    field_id      TEXT NOT NULL REFERENCES field(id) ON DELETE CASCADE,
    crop          TEXT NOT NULL,
    sowing_date   TEXT,
    harvest_date  TEXT,
    -- Free-text notes the farmer gave: what went wrong, what they observed.
    notes         TEXT,
    yield_reported TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_season_field ON season(field_id);

CREATE TABLE IF NOT EXISTS conversation (
    id            TEXT PRIMARY KEY,
    farmer_id     TEXT REFERENCES farmer(id) ON DELETE CASCADE,
    field_id      TEXT REFERENCES field(id) ON DELETE SET NULL,
    title         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_farmer ON conversation(farmer_id);

CREATE TABLE IF NOT EXISTS message (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    -- Anthropic content blocks, serialised.
    content_json    TEXT NOT NULL,
    -- Evidence Ledger entries produced by this turn.
    evidence_json   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON message(conversation_id, created_at);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection with foreign keys and row access by name."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL keeps readers from blocking on the writer, which matters as soon as
    # more than one farmer is talking to the same instance.
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.utcnow().isoformat()


def _uid() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------
# Farmers and fields
# --------------------------------------------------------------------------

def create_farmer(language: str = "en", display_name: str | None = None,
                  country: str | None = None) -> str:
    fid = _uid()
    with connect() as conn:
        conn.execute(
            "INSERT INTO farmer (id, display_name, language, country, created_at) "
            "VALUES (?,?,?,?,?)",
            (fid, display_name, language, country, _now()),
        )
    return fid


def get_farmer(farmer_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM farmer WHERE id = ?", (farmer_id,)
        ).fetchone()
    return dict(row) if row else None


def set_language(farmer_id: str, language: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE farmer SET language = ? WHERE id = ?", (language, farmer_id)
        )


def add_field(
    farmer_id: str, latitude: float, longitude: float,
    name: str | None = None, area_hectares: float | None = None,
    boundary: dict | None = None,
) -> str:
    fid = _uid()
    with connect() as conn:
        conn.execute(
            "INSERT INTO field (id, farmer_id, name, latitude, longitude, "
            "area_hectares, boundary_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                fid, farmer_id, name, latitude, longitude, area_hectares,
                json.dumps(boundary) if boundary else None, _now(),
            ),
        )
    return fid


def list_fields(farmer_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM field WHERE farmer_id = ? ORDER BY created_at",
            (farmer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_field(field_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM field WHERE id = ?", (field_id,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------
# Seasons -- the longitudinal memory
# --------------------------------------------------------------------------

def record_season(
    field_id: str, crop: str, sowing_date: str | None = None,
    harvest_date: str | None = None, notes: str | None = None,
    yield_reported: str | None = None,
) -> str:
    sid = _uid()
    with connect() as conn:
        conn.execute(
            "INSERT INTO season (id, field_id, crop, sowing_date, harvest_date, "
            "notes, yield_reported, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (sid, field_id, crop, sowing_date, harvest_date, notes,
             yield_reported, _now()),
        )
    return sid


def list_seasons(field_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM season WHERE field_id = ? ORDER BY sowing_date DESC",
            (field_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def current_season(field_id: str) -> dict[str, Any] | None:
    """The most recent season with no recorded harvest — the crop in the ground."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM season WHERE field_id = ? AND harvest_date IS NULL "
            "ORDER BY sowing_date DESC LIMIT 1",
            (field_id,),
        ).fetchone()
    return dict(row) if row else None


def build_field_context(field_id: str) -> str:
    """Render a field and its current crop as prompt context.

    Deliberately terse. This goes into every request, so verbosity here is a
    per-message tax paid on a farmer's data connection.
    """
    f = get_field(field_id)
    if not f:
        return ""
    lines = [
        f"Field: {f['name'] or 'unnamed'} at {f['latitude']:.4f}, "
        f"{f['longitude']:.4f}"
    ]
    if f.get("area_hectares"):
        lines.append(f"Area: {f['area_hectares']} hectares")
    season = current_season(field_id)
    if season:
        lines.append(
            f"Currently growing: {season['crop']}"
            + (f", sown {season['sowing_date']}" if season.get("sowing_date") else "")
        )
        if season.get("notes"):
            lines.append(f"Notes this season: {season['notes']}")
    return "\n".join(lines)


def build_season_memory(field_id: str, limit: int = 6) -> str:
    """Render past seasons as prompt context."""
    seasons = [s for s in list_seasons(field_id) if s.get("harvest_date")][:limit]
    if not seasons:
        return ""
    lines = []
    for s in seasons:
        bit = f"- {s['crop']}"
        if s.get("sowing_date"):
            bit += f", sown {s['sowing_date']}"
        if s.get("yield_reported"):
            bit += f", yield {s['yield_reported']}"
        if s.get("notes"):
            bit += f" — {s['notes']}"
        lines.append(bit)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------

def create_conversation(farmer_id: str | None, field_id: str | None = None,
                        title: str | None = None) -> str:
    cid = _uid()
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversation (id, farmer_id, field_id, title, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (cid, farmer_id, field_id, title, now, now),
        )
    return cid


def append_message(conversation_id: str, role: str, content: Any,
                   evidence: Any = None) -> str:
    mid = _uid()
    with connect() as conn:
        conn.execute(
            "INSERT INTO message (id, conversation_id, role, content_json, "
            "evidence_json, created_at) VALUES (?,?,?,?,?,?)",
            (mid, conversation_id, role, json.dumps(content, default=str),
             json.dumps(evidence, default=str) if evidence else None, _now()),
        )
        conn.execute(
            "UPDATE conversation SET updated_at = ? WHERE id = ?",
            (_now(), conversation_id),
        )
    return mid


def load_messages(conversation_id: str) -> list[dict[str, Any]]:
    """Load a conversation in Anthropic message format."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content_json FROM message WHERE conversation_id = ? "
            "ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
    return [
        {"role": r["role"], "content": json.loads(r["content_json"])} for r in rows
    ]


def list_conversations(farmer_id: str, limit: int = 30) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversation WHERE farmer_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (farmer_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
