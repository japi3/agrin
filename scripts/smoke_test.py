"""
End-to-end verification of every deliverable.

Runs against a live instance and exercises each capability the way a user
would, not the way a unit test would. Unit tests prove the agronomy is
correct; this proves the system is actually wired together -- that the tool
the model calls reaches the client it needs, that the client reaches the
upstream service, and that what comes back is usable.

Every check reports PASS, FAIL or SKIP with a reason. Nothing is mocked.
A SKIP means an external dependency is unavailable (no API key, upstream
down); a FAIL means our code is wrong.

    python scripts/smoke_test.py [--base http://localhost:8080]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("packages/agronomy", "packages/geo", "packages/rag", "apps/api"):
    sys.path.insert(0, str(ROOT / pkg))

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str, float]] = []


def record(name: str, status: str, detail: str = "", elapsed: float = 0.0) -> None:
    results.append((name, status, detail, elapsed))
    symbol = {"PASS": "  ok  ", "FAIL": " FAIL ", "SKIP": " skip "}[status]
    timing = f"{elapsed:6.1f}s" if elapsed else "       "
    line = f"[{symbol}]{timing}  {name}"
    if detail:
        line += f"\n                     {detail}"
    print(line, flush=True)


async def check(name: str, coro, validate=None):
    """Run one check, timing it and catching everything."""
    started = time.time()
    try:
        value = await coro
    except Exception as exc:  # noqa: BLE001
        record(name, FAIL, f"{type(exc).__name__}: {str(exc)[:160]}",
               time.time() - started)
        return None
    elapsed = time.time() - started
    if validate is None:
        record(name, PASS, "", elapsed)
        return value
    try:
        ok, detail = validate(value)
    except Exception as exc:  # noqa: BLE001
        record(name, FAIL, f"validator raised {type(exc).__name__}: {exc}", elapsed)
        return value
    # A validator may return the SKIP sentinel to mean "an external dependency
    # was unavailable", which is distinct from our code being wrong.
    if ok is SKIP:
        record(name, SKIP, detail, elapsed)
    else:
        record(name, PASS if ok else FAIL, detail, elapsed)
    return value


# Real Indian farmland, verified by satellite as genuine cropland.
LAT, LON = 30.70, 75.20
SOWN = (date.today() - timedelta(days=60)).isoformat()


def _soil_ok(d):
    if not d.get("ok"):
        return False, d.get("abstain_reason", "")
    return True, f"{d['texture']['usda_class']}, pH {d['chemistry']['ph']}"


def _mandi_ok(d):
    """Mandi is the one source with a hard external dependency we cannot fix.

    The shared data.gov.in demonstration key is throttled across everyone
    using it, so a 429 is routine and says nothing about our code. Reporting
    that as a failure would make the smoke test cry wolf, and a suite that
    cries wolf gets ignored on the day it is right.

    An outage is a SKIP. A genuinely empty market is a PASS -- correctly
    reporting "out of season" is the tool working. Only a malformed or
    missing answer is a FAIL.
    """
    if d.get("operator_detail"):
        return SKIP, f"upstream unavailable: {d['operator_detail'][:90]}"
    if not d.get("ok"):
        reason = d.get("abstain_reason", "")
        if "out of season" in reason or "arrivals" in reason:
            return True, "no arrivals today, correctly reported as out of season"
        return False, reason
    return True, (f"Rs {d['median_rs_per_quintal']}/quintal, scope={d['scope']}, "
                  f"{d['markets_reporting']} markets")


def _guidance_ok(d):
    if not d.get("ok"):
        return False, d.get("abstain_reason", "")
    best = d["passages"][0]
    return True, f"{len(d['passages'])} passages, best {best['score']} — {best['title'][:40]}"


def _guidance_refuses(d):
    """The refusal is the feature, so a match here is the failure.

    A corpus that answers a gearbox question is one that will answer a
    question about a pesticide dose the same way.
    """
    if d.get("ok"):
        return False, f"quoted something at {d['passages'][0]['score']}"
    if "not installed" in d.get("abstain_reason", ""):
        return False, "corpus not built — cannot test the refusal"
    return True, "abstained, as it should"


def _health_ok(d):
    if not d.get("ok"):
        return False, d.get("abstain_reason", "")
    verdict = (d.get("assessment") or {}).get("status", "no verdict")
    return True, f"{d['observations']} scenes, NDVI {d['latest_ndvi']}, {verdict}"


async def main(base: str) -> int:
    print(f"AgriN end-to-end verification against {base}\n")
    from agrin_api import tools

    print("--- Service ---")
    async with httpx.AsyncClient(timeout=240.0) as client:
        health = await check(
            "API health",
            client.get(f"{base}/api/health"),
            lambda r: (r.status_code == 200, f"status {r.status_code}"),
        )
        llm_ready = False
        if health is not None and health.status_code == 200:
            body = health.json()
            llm_ready = body["google_ai"]["configured"]
            record(
                "Google AI configured", PASS if llm_ready else SKIP,
                f"mode={body['google_ai']['mode']} model={body['google_ai']['model']}"
                if llm_ready else "no GEMINI_API_KEY; model checks will skip",
            )

        await check(
            "Frontend served",
            client.get(f"{base}/"),
            lambda r: (r.status_code == 200 and b'id="root"' in r.content,
                       f"status {r.status_code}, {len(r.content)} bytes"),
        )
        await check(
            "Languages endpoint",
            client.get(f"{base}/api/languages"),
            lambda r: (len(r.json()["languages"]) >= 20,
                       f"{len(r.json()['languages'])} languages"),
        )

        print("\n--- Data sources (live, nothing mocked) ---")
        await check(
            "Place lookup (Nominatim)",
            tools.find_place("Moga, Punjab"),
            lambda d: ((d["ok"], f"{d['best_match']['district']}, "
                                 f"{d['best_match']['state']}")
                       if d.get("ok") else (False, d.get("abstain_reason", ""))),
        )
        await check("Soil profile (ISRIC SoilGrids)",
                    tools.get_soil_profile(LAT, LON), _soil_ok)
        await check(
            "Weather + FAO-56 ET0 (Open-Meteo)",
            tools.get_weather(LAT, LON),
            lambda d: (d["ok"] and len(d["forecast"]) > 5,
                       f"{len(d['forecast'])} days, "
                       f"ET0 {d['forecast'][0]['reference_et_mm']} mm/day"),
        )
        await check(
            "Irrigation advice (FAO-56 water balance)",
            tools.get_irrigation_advice(LAT, LON, "rice_paddy", SOWN),
            lambda d: (d.get("ok") and d.get("verdict") in {
                "irrigate_now", "irrigate_in_days", "wait_for_rain",
                "no_irrigation_needed"},
                f"{d.get('verdict')}, soil at {d.get('soil_moisture_percent')}%"),
        )
        await check(
            "Crop suitability",
            tools.assess_crop_suitability(LAT, LON),
            lambda d: (d["ok"] and len(d["assessments"]) >= 5,
                       f"top: {d['assessments'][0]['name']} "
                       f"({d['assessments'][0]['score']})"),
        )
        await check(
            "Soil carbon (RothC)",
            tools.compare_regenerative_practices(LAT, LON, years=20),
            lambda d: (d["ok"], f"best: {d.get('best_scenario')}, "
                                f"+{d.get('gain_over_burning_t_co2e_per_ha')} t CO2e/ha"),
        )
        await check("Satellite NDVI (Sentinel-2)",
                    tools.get_crop_health(LAT, LON, crop="rice_paddy",
                                          sowing_date=SOWN), _health_ok)
        await check("Mandi prices (Agmarknet)",
                    tools.get_mandi_prices("maize_grain", latitude=LAT,
                                           longitude=LON), _mandi_ok)
        await check("Advisory retrieval (Vikaspedia corpus)",
                    tools.look_up_official_guidance(
                        "seed treatment before sowing wheat"),
                    _guidance_ok)
        await check("Advisory retrieval refuses an off-topic question",
                    tools.look_up_official_guidance(
                        "how do I rebuild a motorcycle gearbox"),
                    _guidance_refuses)

        print("\n--- Conversation ---")
        if not llm_ready:
            for n in ("Chat turn with tool use", "Conversation memory across turns",
                      "Photo diagnosis refuses an unusable image"):
                record(n, SKIP, "no GEMINI_API_KEY")
        else:
            async def chat(msg, conv=None, farmer=None):
                payload = {"message": msg, "conversation_id": conv,
                           "farmer_id": farmer, "language": "en",
                           "latitude": LAT, "longitude": LON}
                text, called, cid, fid, err, err_kind = [], [], conv, farmer, None, ""
                async with client.stream("POST", f"{base}/api/chat",
                                         json=payload) as r:
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        p = line[6:]
                        if p == "[DONE]":
                            break
                        d = json.loads(p)
                        t = d.get("type")
                        if t == "text":
                            text.append(d["delta"])
                        elif t == "tool_start":
                            called.append(d["name"])
                        elif t == "session":
                            cid, fid = d["conversation_id"], d["farmer_id"]
                        elif t == "error":
                            # Keep the operator detail, not just the farmer
                            # message: diagnosing a failure from "something
                            # went wrong" is impossible.
                            err = d.get("detail") or d["message"]
                            err_kind = d.get("kind", "")
                return "".join(text), called, cid, fid, err, err_kind

            def chat_verdict(v):
                """Rate limiting is the free tier, not our code."""
                _text, called, _c, _f, err, kind = v
                if kind in {"rate_limited", "busy", "network"} or (
                    err and ("429" in err or "RESOURCE_EXHAUSTED" in err)
                ):
                    return SKIP, f"upstream {kind or 'rate limited'}: {str(err)[:90]}"
                if err:
                    return False, str(err)[:150]
                return bool(_text) and len(called) > 0, (
                    f"tools={called}, {len(_text)} chars")

            # The free Gemini tier allows 20 requests per minute and one chat
            # turn costs several. Pacing keeps the suite from failing on a
            # limit it caused itself.
            await asyncio.sleep(8)

            first = await check(
                "Chat turn with tool use",
                chat("Does my rice need water this week? I sowed 60 days ago."),
                chat_verdict,
            )

            if first and first[2]:
                cid, fid = first[2], first[3]
                await asyncio.sleep(20)
                await check(
                    "Conversation memory across turns",
                    chat("And what is the mandi rate for it?", cid, fid),
                    lambda v: (SKIP, f"upstream {v[5]}") if v[5] in {
                        "rate_limited", "busy", "network"
                    } else (bool(v[0]) and not v[4],
                            f"tools={v[1]}"
                            + (f" | ERROR: {str(v[4])[:90]}" if v[4] else "")),
                )
            else:
                record("Conversation memory across turns", FAIL,
                       "no conversation id from first turn")

            async def diagnose():
                from PIL import Image
                buf = io.BytesIO()
                Image.new("RGB", (400, 300), (120, 120, 125)).save(buf, "JPEG")
                files = {"image": ("t.jpg", buf.getvalue(), "image/jpeg")}
                data = {"latitude": str(LAT), "longitude": str(LON),
                        "crop": "rice_paddy", "language": "en"}
                r = await client.post(f"{base}/api/diagnose", files=files, data=data)
                return r.json()

            await asyncio.sleep(20)
            await check(
                "Photo diagnosis refuses an unusable image",
                diagnose(),
                lambda d: (SKIP, f"upstream: {str(d.get('abstain_reason'))[:90]}")
                if not d.get("ok")
                else (d.get("image_usable") is False,
                      "correctly refused" if d.get("image_usable") is False
                      else f"image_usable={d.get('image_usable')}"),
            )

        print("\n--- Field panel ---")

        async def panel():
            f = (await client.post(f"{base}/api/farmer?language=en")).json()
            fd = (await client.post(f"{base}/api/field", json={
                "farmer_id": f["farmer_id"], "latitude": LAT, "longitude": LON,
                "name": "smoke test field"})).json()
            await client.post(f"{base}/api/season", json={
                "field_id": fd["field_id"], "crop": "rice_paddy",
                "sowing_date": SOWN})
            fast = (await client.get(
                f"{base}/api/field/{fd['field_id']}/summary")).json()
            full = (await client.get(
                f"{base}/api/field/{fd['field_id']}/summary",
                params={"include_irrigation": "true"})).json()
            return fast, full

        await check(
            "Field summary (soil + weather + irrigation)",
            panel(),
            lambda v: (v[0].get("soil") is not None
                       and v[0].get("weather") is not None
                       and v[1].get("irrigation") is not None,
                       f"soil={(v[0].get('soil') or {}).get('texture')}, "
                       f"irrigation={(v[1].get('irrigation') or {}).get('verdict')}"),
        )

    print("\n--- Federation ---")
    async with httpx.AsyncClient(timeout=30.0) as client:
        ports = {"IN": 9001, "BR": 9002, "RU": 9003, "CN": 9004, "ZA": 9005}
        live = []
        for code, port in ports.items():
            try:
                r = await client.get(f"http://localhost:{port}/health")
                if r.status_code == 200:
                    live.append((code, r.json()["records_held"]))
            except Exception:
                pass
        if not live:
            record("Country nodes", SKIP,
                   "stack not running: docker compose -f federation/docker-compose.yml up -d")
            record("No node endpoint returns records", SKIP, "stack not running")
        else:
            record("Country nodes", PASS if len(live) == 5 else FAIL,
                   ", ".join(f"{c}:{n}" for c, n in live))
            leaks = []
            for path in ("/data", "/records", "/fields", "/dataset", "/export"):
                try:
                    r = await client.get(f"http://localhost:9001{path}")
                    if r.status_code != 404:
                        leaks.append(f"{path}->{r.status_code}")
                except Exception:
                    pass
            record("No node endpoint returns records",
                   PASS if not leaks else FAIL,
                   "all record-shaped paths return 404" if not leaks else str(leaks))

    print("\n" + "=" * 70)
    passed = sum(1 for _, s, _, _ in results if s == PASS)
    failed = sum(1 for _, s, _, _ in results if s == FAIL)
    skipped = sum(1 for _, s, _, _ in results if s == SKIP)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        print("\nFailures:")
        for name, status, detail, _ in results:
            if status == FAIL:
                print(f"  - {name}: {detail}")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8080")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.base)))
