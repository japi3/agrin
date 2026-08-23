"""
Seed each country node's data directory from the cached dataset.

Without this, every node builds its national dataset on first start by
fetching SoilGrids and twenty years of ERA5 for its sites. Five nodes doing
that at once takes roughly half an hour and hammers two free public services,
which is a poor first experience and poor manners.

Each country's file is written to its own directory under
`federation/nodedata/`, bind-mounted read-write into that node alone. The
isolation is the same as with named volumes but you can see it in the
filesystem, which for a demo about data sovereignty is the point.
"""

import pickle
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".dataset_cache.pkl"
NODEDATA = HERE / "nodedata"
COUNTRIES = ["IN", "BR", "RU", "CN", "ZA"]


def main() -> None:
    if not CACHE.exists():
        sys.exit(
            "No cached dataset found. Build one first:\n"
            "    python federation/run_experiment.py"
        )

    datasets = pickle.loads(CACHE.read_bytes())
    for code in COUNTRIES:
        if code not in datasets:
            print(f"  {code}: absent from cache — node will build its own")
            continue
        X, y = datasets[code]
        target = NODEDATA / code
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{code}.pkl").write_bytes(pickle.dumps((X, y)))
        print(f"  {code}: seeded {X.shape[0]} records -> {target}/{code}.pkl")

    print(f"\nEach directory under {NODEDATA} is mounted into that country's")
    print("node only. No node can read another's data.")


if __name__ == "__main__":
    main()
