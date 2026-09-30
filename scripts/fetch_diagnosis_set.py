"""
Download the labelled images the diagnosis evaluation runs on.

The images are not in this repository and should not be. They belong to the
PlantVillage dataset, released CC0, and the right thing to do with somebody
else's dataset is name it and fetch it rather than copy it into your own
history. It also keeps the repository small and makes the set reproducible:
eval/diagnosis_set.json records which files, chosen with a fixed seed, so
two people running this get the same sixty images.

    python scripts/fetch_diagnosis_set.py

Lands in data/diagnosis_eval/, which is gitignored. Already-downloaded files
are skipped, so a re-run costs nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SET_FILE = ROOT / "eval" / "diagnosis_set.json"
OUT = ROOT / "data" / "diagnosis_eval"

# Named, because a public dataset host should be able to see who is pulling
# from it and why.
USER_AGENT = (
    "AgriN/0.1 (+https://github.com/japi3/agrin; "
    "agricultural advisory evaluation; contact via repository)"
)


def main() -> int:
    data = json.loads(SET_FILE.read_text(encoding="utf-8"))
    base = data["base_url"]
    items = data["items"]
    OUT.mkdir(parents=True, exist_ok=True)

    print(f"{len(items)} images from {data['source']}")
    print(f"licence: {data['licence']}\n")

    fetched = skipped = failed = 0
    with httpx.Client(timeout=90.0, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        for i, item in enumerate(items, 1):
            local = OUT / item["class"] / item["file"]
            if local.exists() and local.stat().st_size > 0:
                skipped += 1
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            url = f"{base}/{item['class']}/{item['file']}"
            try:
                response = client.get(url)
                response.raise_for_status()
                local.write_bytes(response.content)
                fetched += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ! {type(exc).__name__} {item['class']}/{item['file']}")
            if i % 20 == 0:
                print(f"  {i}/{len(items)}")

    print(f"\nfetched {fetched}, already had {skipped}, failed {failed}")
    print(f"in {OUT}")
    if failed:
        print("Re-run to retry the failures; existing files are skipped.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
