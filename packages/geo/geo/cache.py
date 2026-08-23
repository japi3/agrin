"""
Disk-backed cache for upstream geospatial queries.

The public data services this platform depends on have very different
freshness and reliability profiles, and treating them identically is what
makes naive integrations slow and fragile:

  - SoilGrids is effectively static. A soil profile does not change between
    seasons, and ISRIC's REST service is slow (multi-second, occasionally
    tens of seconds) and unmetered-but-fair-use. Cache for a year.
  - Weather forecasts change every few hours. Cache briefly.
  - Historical weather is immutable once the day has passed. Cache forever.
  - Satellite scene metadata is append-only. Cache for a day.

Caching is not an optimisation here, it is a correctness property: without it
a farmer's first question issues forty sequential ISRIC round-trips and times
out, which is exactly what happened during development of the ring search.

The cache is content-addressed by a hash of the query, stored as JSON on
disk. Disk rather than Redis so that a single-container deployment on a cheap
VPS -- the realistic deployment target for a national extension service --
works with no external dependency.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CACHE_DIR = Path(
    os.environ.get("AGRIN_CACHE_DIR", Path.home() / ".cache" / "agrin")
)

# Time-to-live by logical dataset, in seconds.
TTL = {
    "soilgrids": 365 * 24 * 3600,     # static
    "weather_forecast": 3 * 3600,      # refreshed by the model every few hours
    "weather_archive": 365 * 24 * 3600,  # immutable once observed
    "elevation": 365 * 24 * 3600,      # static
    "stac_search": 24 * 3600,          # append-only scene index
    "geocode": 30 * 24 * 3600,
}


@dataclass
class CacheEntry:
    value: Any
    stored_at: float
    namespace: str

    def is_fresh(self, ttl: float) -> bool:
        return (time.time() - self.stored_at) < ttl


class DiskCache:
    """A small, dependency-free JSON cache keyed by query hash."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or DEFAULT_CACHE_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        sub = self.directory / namespace
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{digest}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        """Return a cached value, or None if absent or stale."""
        path = self._path(namespace, key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            # A truncated cache file (interrupted write, full disk) must not
            # take down a request. Treat it as a miss and let it be rewritten.
            return None

        entry = CacheEntry(
            value=payload.get("value"),
            stored_at=payload.get("stored_at", 0.0),
            namespace=namespace,
        )
        ttl = TTL.get(namespace, 3600)
        if not entry.is_fresh(ttl):
            return None
        return entry.value

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Store a value. Writes atomically so a crash cannot leave a partial file."""
        path = self._path(namespace, key)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"value": value, "stored_at": time.time()})
            )
            tmp.replace(path)
        except OSError:
            # Caching is best-effort; a read-only or full filesystem should
            # degrade to uncached operation rather than fail the request.
            pass

    def stats(self) -> dict[str, int]:
        """Entry count per namespace, for the operations dashboard."""
        out: dict[str, int] = {}
        for sub in self.directory.iterdir():
            if sub.is_dir():
                out[sub.name] = len(list(sub.glob("*.json")))
        return out


_default_cache: DiskCache | None = None


def get_cache() -> DiskCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = DiskCache()
    return _default_cache


def cache_key(**parts: Any) -> str:
    """Build a stable cache key from keyword parts.

    Coordinates are rounded to 4 decimal places (~11 m) so that two taps on
    the same field do not miss the cache, while genuinely different fields
    still get distinct entries.
    """
    normalised = {}
    for k, v in sorted(parts.items()):
        if isinstance(v, float):
            normalised[k] = round(v, 4)
        elif isinstance(v, (list, tuple)):
            normalised[k] = list(v)
        else:
            normalised[k] = v
    return json.dumps(normalised, sort_keys=True, default=str)
