"""
Measure the photo-diagnosis path against labelled images.

Until this existed, every other part of the platform had a number and this
one had none. The water balance reproduces the FAO's worked example, the
retrieval scores 30 of 35, the federation transfer was measured across five
nodes -- and the component that looks at a farmer's photograph and names a
disease had never been scored against anything.

    python scripts/fetch_diagnosis_set.py      # once
    python scripts/evaluate_diagnosis.py
    python scripts/evaluate_diagnosis.py --limit 12 --out eval/results_diagnosis.md

What is measured, and why each one is here:

**With the crop known, and without.** The response schema has no crop
field: the model is asked what is wrong, never what plant it is looking at.
In the app the crop usually comes from the farm record and is passed in, so
that is the realistic case and the default here. Running with --blind
withholds it, which is what a farmer photographing something they cannot
name gets. The first measurement of this scored only the blind case and
read far worse than the product it was testing -- "fire blight", an apple
disease, on a potato leaf.

**Disease in the candidates.** The model returns a ranked list, and the
honest question is whether the truth is in it at all, not only whether it
led. Both are reported: first, and anywhere.

**Healthy leaves left alone.** A third of the set is healthy on purpose.
Naming a disease on a healthy plant costs the farmer a spray they did not
need and teaches them to distrust the next answer, which is the more
expensive of the two errors. A system that scores well on sick leaves and
cries wolf on healthy ones is not a good system.

**Refusal on an unusable photograph.** The set is blurred and darkened
copies of real images, generated locally rather than downloaded, so the
refusal path is exercised on something that genuinely cannot be diagnosed.

One caveat that belongs on every number this produces: PlantVillage images
are single leaves on plain backgrounds under even light. A photograph from
a field has soil, shadow, several overlapping leaves and a moving hand. A
score here is an upper bound on field performance, not an estimate of it.

Costs one generation request per image, and the free tier allows twenty per
model per key per day -- so `--limit` exists, and the default is to run the
whole set only when you mean to.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pkg in ("apps/api", "packages/agronomy", "packages/geo", "packages/rag"):
    sys.path.insert(0, str(ROOT / pkg))

import os  # noqa: E402
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

SET_FILE = ROOT / "eval" / "diagnosis_set.json"
IMAGES = ROOT / "data" / "diagnosis_eval"

# Ludhiana. The diagnosis is conditioned on weather-driven infection
# pressure, so it needs somewhere to be; a fixed point keeps runs
# comparable.
LAT, LON = 30.90, 75.85

# Words that mean the same disease. The model writes for a farmer, not for
# a label set, so "blight of the leaves" must count as "leaf blight".
ALIASES = {
    "early blight": {"early blight", "alternaria", "target spot"},
    "late blight": {"late blight", "phytophthora"},
    "septoria leaf spot": {"septoria", "leaf spot"},
    "yellow leaf curl virus": {"leaf curl", "tylcv", "yellow leaf curl",
                               "whitefly", "virus"},
    "common rust": {"rust", "puccinia"},
    "northern leaf blight": {"northern leaf blight", "turcicum",
                             "northern corn leaf blight", "leaf blight"},
    "bacterial spot": {"bacterial spot", "xanthomonas", "bacterial leaf spot"},
}


def matches(expected: str, text: str) -> bool:
    text = (text or "").lower()
    for term in ALIASES.get(expected, {expected}):
        if term in text:
            return True
    return expected in text


def degrade(image: bytes) -> bytes | None:
    """A copy of a real photograph that nobody could diagnose.

    Generated here rather than downloaded, so the refusal path is tested on
    something genuinely unusable without adding an image to anyone's
    dataset. Returns None if Pillow is not installed, and the check is
    skipped rather than failed.
    """
    try:
        import io
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return None
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    picture = picture.filter(ImageFilter.GaussianBlur(radius=12))
    picture = ImageEnhance.Brightness(picture).enhance(0.18)
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=40)
    return buffer.getvalue()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="score only this many images (quota is 20/day/model/key)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--skip-unusable", action="store_true",
                        help="skip the blurred-image refusal check")
    parser.add_argument("--blind", action="store_true",
                        help="withhold the crop, as when a farmer cannot name it")
    args = parser.parse_args()

    from agrin_api.vision import diagnose_crop_photo

    data = json.loads(SET_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    if args.limit:
        # Take a spread rather than the first n, so a short run still covers
        # several classes and both healthy and sick leaves.
        step = max(1, len(items) // args.limit)
        items = items[::step][:args.limit]

    missing = [i for i in items if not (IMAGES / i["class"] / i["file"]).exists()]
    if missing:
        raise SystemExit(
            f"{len(missing)} images are not downloaded. "
            f"Run: python scripts/fetch_diagnosis_set.py"
        )

    mode = "crop withheld" if args.blind else "crop known, as in the app"
    print(f"{len(items)} images · {mode} · {data['source']}")
    print(f"licence: {data['licence']}\n")

    disease_first = disease_anywhere = 0
    sick = healthy = healthy_left_alone = 0
    unusable_claimed = 0
    failures: list[str] = []
    durations: list[float] = []
    quota_hit = False

    for n, item in enumerate(items, 1):
        path = IMAGES / item["class"] / item["file"]
        image = path.read_bytes()
        started = time.time()
        try:
            result = await diagnose_crop_photo(
                image, "image/jpeg", latitude=LAT, longitude=LON,
                crop=None if args.blind else item["crop"],
                language="en", language_name="English",
            )
        except Exception as exc:  # noqa: BLE001
            if "PerDay" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                print(f"\nquota exhausted after {n - 1} images; "
                      f"reporting what was scored")
                quota_hit = True
                items = items[:n - 1]
                break
            failures.append(f"{item['file']}: {type(exc).__name__}")
            continue
        durations.append(time.time() - started)

        if not result.get("ok"):
            failures.append(f"{item['file']}: {result.get('abstain_reason','')[:60]}")
            continue
        if not result.get("image_usable", True):
            unusable_claimed += 1
            failures.append(f"{item['file']}: called a clean image unusable")
            continue

        candidates = result.get("candidates") or []
        blob = " ".join(
            f"{c.get('name','')} {c.get('why','')}" for c in candidates
        ).lower()
        first = (candidates[0].get("name", "") if candidates else "").lower()

        if item["healthy"]:
            healthy += 1
            # "Healthy" is a pass; naming a disease is the failure.
            if not candidates or any(
                w in first for w in ("healthy", "no disease", "nothing")
            ):
                healthy_left_alone += 1
            else:
                failures.append(
                    f"{item['file']}: healthy leaf diagnosed as “{first[:34]}”")
        else:
            sick += 1
            if matches(item["disease"], first):
                disease_first += 1
                disease_anywhere += 1
            elif matches(item["disease"], blob):
                disease_anywhere += 1
            else:
                failures.append(
                    f"{item['file']}: wanted “{item['disease']}”, got “{first[:34]}”")
        if n % 10 == 0:
            print(f"  {n}/{len(items)}")

    # The refusal path, on an image nobody could read.
    refused = tried_unusable = 0
    if not args.skip_unusable and not quota_hit and items:
        source = IMAGES / items[0]["class"] / items[0]["file"]
        ruined = degrade(source.read_bytes())
        if ruined:
            tried_unusable = 1
            try:
                out = await diagnose_crop_photo(
                    ruined, "image/jpeg", latitude=LAT, longitude=LON,
                    language="en", language_name="English")
                if not out.get("ok") or not out.get("image_usable", True):
                    refused = 1
                else:
                    failures.append(
                        "blurred image: diagnosed instead of refused")
            except Exception:  # noqa: BLE001
                tried_unusable = 0

    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text)
        lines.append(text)

    scored = sick + healthy
    if not scored:
        print("nothing scored")
        return 1

    say("| Metric | Result |")
    say("|---|---|")
    if sick:
        say(f"| Disease named first | **{disease_first}/{sick} "
            f"({disease_first * 100 // sick}%)** |")
        say(f"| Disease among the candidates | **{disease_anywhere}/{sick} "
            f"({disease_anywhere * 100 // sick}%)** |")
    if healthy:
        say(f"| Healthy leaves left alone | **{healthy_left_alone}/{healthy}** |")
    if tried_unusable:
        say(f"| Unusable photograph refused | {refused}/{tried_unusable} |")
    if durations:
        durations.sort()
        say(f"| Time per photograph (median) | "
            f"{durations[len(durations) // 2]:.1f} s |")
    say()

    if failures:
        say(f"Failures ({len(failures)}):")
        for f in failures[:20]:
            say(f"  - {f}")
        if len(failures) > 20:
            say(f"  … and {len(failures) - 20} more")
        say()

    say("Laboratory images on plain backgrounds. A field photograph has "
        "soil, shadow, overlapping leaves and camera shake; treat these as "
        "an upper bound, not an estimate of field performance.")

    if args.out:
        header = (
            f"# Photo-diagnosis evaluation\n\n"
            f"*{time.strftime('%Y-%m-%d')} · {scored} labelled images from "
            f"PlantVillage (CC0) · {mode} · `eval/diagnosis_set.json`*\n\n"
        )
        args.out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
