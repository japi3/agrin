"""
The federated learning experiment.

The claim being tested
----------------------
BRICS agricultural cooperation founders on data sovereignty. No country will
export farm-level records, and every proposal that requires it stalls. The
technical counter-claim is that they do not have to: models can be trained
across borders while records stay home.

That is easy to assert and worth measuring. This experiment measures three
things:

  1. **Does a locally-trained model transfer?** Train on one country, test on
     the others. If it transfers well, federation buys little and the honest
     answer is that a shared model is unnecessary.
  2. **Does federation actually help?** Compare each country's local model
     against the federated model, evaluated on that country's own held-out
     fields and on the others'.
  3. **What actually crosses the border?** Count the bytes, and compare
     against what pooling the data would have required.

Run:
    python federation/run_experiment.py

The first run fetches real soil and climate for 16 sites across five
countries and takes several minutes; results are cached afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data import FEATURE_NAMES, NODES, build_all  # noqa: E402
from model import (  # noqa: E402
    MLP, Standardiser, Weights, federated_average, mae, node_statistics, rmse,
)

CACHE = Path(__file__).resolve().parent / ".dataset_cache.pkl"


def split(X: np.ndarray, y: np.ndarray, test_fraction: float = 0.25, seed: int = 0):
    rng = np.random.default_rng(seed)
    idx = rng.permutation(X.shape[0])
    cut = int(X.shape[0] * (1 - test_fraction))
    tr, te = idx[:cut], idx[cut:]
    return X[tr], y[tr], X[te], y[te]


async def load_datasets(samples_per_site: int, refresh: bool):
    if CACHE.exists() and not refresh:
        print(f"Using cached datasets ({CACHE.name}); pass --refresh to rebuild.\n")
        return pickle.loads(CACHE.read_bytes())
    print("Building datasets from real soil and climate data.")
    print("This fetches SoilGrids and 20-year ERA5 normals per site and is slow "
          "the first time.\n")
    datasets = await build_all(samples_per_site=samples_per_site)
    CACHE.write_bytes(pickle.dumps(datasets))
    return datasets


def run(datasets, rounds: int, local_epochs: int, dp_noise: float) -> dict:
    codes = [n.code for n in NODES if datasets.get(n.code, (None,))[0] is not None
             and datasets[n.code][0].shape[0] > 20]
    names = {n.code: n.name for n in NODES}

    splits = {}
    for code in codes:
        X, y = datasets[code]
        splits[code] = split(X, y)

    # --- Federated feature scaling ------------------------------------
    # Computed from per-node aggregates only; no records pooled.
    stats = [node_statistics(splits[c][0]) for c in codes]
    scaler = Standardiser.from_node_statistics(stats)
    for c in codes:
        Xtr, ytr, Xte, yte = splits[c]
        splits[c] = (scaler.transform(Xtr), ytr, scaler.transform(Xte), yte)

    n_features = len(FEATURE_NAMES)
    results: dict = {"countries": {}, "matrix": {}, "federated": {}}

    # --- 1. Local-only models -----------------------------------------
    print("=" * 74)
    print("LOCAL-ONLY MODELS  (each country trains on its own fields alone)")
    print("=" * 74)
    local_models: dict[str, MLP] = {}
    for c in codes:
        Xtr, ytr, Xte, yte = splits[c]
        m = MLP(n_features, hidden=16, seed=7)
        m.train_local(Xtr, ytr, epochs=rounds * local_epochs, lr=0.02, seed=7)
        local_models[c] = m
        own = rmse(m.predict(Xte), yte)
        results["countries"][c] = {"local_rmse_own": own, "n_train": int(Xtr.shape[0])}
        print(f"  {c} {names[c]:14s} trained on {Xtr.shape[0]:4d} fields   "
              f"RMSE on own fields: {own:6.1f} mm")

    # --- 2. Cross-country transfer ------------------------------------
    print()
    print("=" * 74)
    print("TRANSFER  (rows: model trained here.  columns: tested there.  RMSE mm)")
    print("=" * 74)
    header = "        " + "".join(f"{c:>9s}" for c in codes)
    print(header)
    for src in codes:
        row = f"  {src:5s} "
        for dst in codes:
            _, _, Xte, yte = splits[dst]
            score = rmse(local_models[src].predict(Xte), yte)
            results["matrix"].setdefault(src, {})[dst] = score
            marker = "*" if src == dst else " "
            row += f"{score:8.1f}{marker}"
        print(row)
    print("  * = tested on the country's own held-out fields")

    # --- 3. Federated training ----------------------------------------
    print()
    print("=" * 74)
    print(f"FEDERATED  (FedAvg, {rounds} rounds x {local_epochs} local epochs)")
    if dp_noise > 0:
        print(f"           noise std {dp_noise} added to averaged weights")
    print("=" * 74)

    global_model = MLP(n_features, hidden=16, seed=7)
    bytes_per_round = 0

    for rnd in range(1, rounds + 1):
        updates: list[tuple[Weights, int]] = []
        for c in codes:
            Xtr, ytr, _, _ = splits[c]
            # Each node starts the round from the current global weights,
            # trains only on its own data, and returns only weights.
            node_model = MLP(n_features, hidden=16, seed=7)
            node_model.weights = global_model.weights.copy()
            node_model.train_local(Xtr, ytr, epochs=local_epochs, lr=0.02, seed=rnd)
            updates.append((node_model.weights, int(Xtr.shape[0])))

        bytes_per_round = sum(w.size() for w, _ in updates) * 8
        global_model.weights = federated_average(
            updates, dp_noise_std=dp_noise, seed=rnd
        )

        if rnd % max(1, rounds // 5) == 0 or rnd == rounds:
            scores = [
                rmse(global_model.predict(splits[c][2]), splits[c][3]) for c in codes
            ]
            print(f"  round {rnd:3d}   mean RMSE across all countries: "
                  f"{np.mean(scores):6.1f} mm")

    # --- 3b. Federated pre-training then local fine-tuning ------------
    #
    # The plain FedAvg model above is a *general* model, and it is worse on
    # any single country's fields than that country's own specialised model.
    # That is not a failure of federation; it is what averaging does, and
    # reporting it as a win would be dishonest.
    #
    # The remedy is the standard one and it is what a real deployment would
    # do: use the federated model as a starting point, then fine-tune briefly
    # on local data. Each country then gets a model that has seen five
    # countries' agronomy and is still tuned to its own -- without any
    # records having moved.
    print()
    print("=" * 74)
    print("FEDERATED + LOCAL FINE-TUNING  (each country adapts the shared model)")
    print("=" * 74)
    finetuned: dict[str, float] = {}
    for c in codes:
        Xtr, ytr, Xte, yte = splits[c]
        m = MLP(n_features, hidden=16, seed=7)
        m.weights = global_model.weights.copy()
        # Short and gentle: enough to specialise, not enough to forget what
        # the other four countries contributed.
        m.train_local(Xtr, ytr, epochs=local_epochs * 4, lr=0.01, seed=11)
        finetuned[c] = rmse(m.predict(Xte), yte)
        print(f"  {c} {names[c]:14s} RMSE on own fields after fine-tuning: "
              f"{finetuned[c]:6.1f} mm")

    # --- 4. Comparison -------------------------------------------------
    print()
    print("=" * 74)
    print("RESULT  (RMSE in mm of seasonal irrigation requirement; lower is better)")
    print("=" * 74)
    print(f"  {'':16s}{'local only':>12s}{'federated':>12s}{'fed+tuned':>12s}"
          f"{'best':>10s}")

    improved = 0
    for c in codes:
        _, _, Xte, yte = splits[c]
        local_score = results["countries"][c]["local_rmse_own"]
        fed_score = rmse(global_model.predict(Xte), yte)
        tuned_score = finetuned[c]
        results["federated"][c] = {
            "rmse": fed_score, "finetuned_rmse": tuned_score,
            "local_rmse": local_score,
        }
        if tuned_score < local_score:
            improved += 1
        best = min(
            [("local", local_score), ("federated", fed_score),
             ("fed+tuned", tuned_score)], key=lambda t: t[1]
        )[0]
        print(f"  {names[c]:16s}{local_score:12.1f}{fed_score:12.1f}"
              f"{tuned_score:12.1f}{best:>10s}")

    # Cross-border generalisation: how each model does on *other* countries.
    mean_foreign_local = float(np.mean([
        results["matrix"][src][dst]
        for src in codes for dst in codes if src != dst
    ]))
    mean_foreign_fed = float(np.mean([
        rmse(global_model.predict(splits[c][2]), splits[c][3]) for c in codes
    ]))

    mean_local_own = float(np.mean([
        results["countries"][c]["local_rmse_own"] for c in codes
    ]))
    mean_tuned = float(np.mean([finetuned[c] for c in codes]))

    print()
    print("  The comparison that matters is not federated-vs-local on your own")
    print("  fields. It is what happens where there is no local training data")
    print("  at all -- a new district, a crop nobody here has records for, a")
    print("  smallholder region that has never been surveyed.")
    print()
    print(f"  A local model on its OWN fields:                  "
          f"{mean_local_own:6.1f} mm")
    print(f"  A local model on ANOTHER country's fields:        "
          f"{mean_foreign_local:6.1f} mm   <- the cooperation problem")
    print(f"  The federated model, anywhere:                    "
          f"{mean_foreign_fed:6.1f} mm")
    print(f"  Federated then fine-tuned locally, on own fields: "
          f"{mean_tuned:6.1f} mm")

    # --- 5. What actually crossed the border ---------------------------
    total_records = sum(splits[c][0].shape[0] for c in codes)
    record_bytes = total_records * (len(FEATURE_NAMES) + 1) * 8
    weights_bytes = bytes_per_round * rounds

    print()
    print("=" * 74)
    print("WHAT CROSSED A BORDER")
    print("=" * 74)
    print(f"  Field records shared:                 0")
    print(f"  Model parameters per node per round:  "
          f"{global_model.weights.size():,}")
    print(f"  Total weight traffic over {rounds} rounds:  "
          f"{weights_bytes / 1024:,.0f} KB")
    print(f"  Traffic if data had been pooled:      "
          f"{record_bytes / 1024:,.0f} KB "
          f"({total_records:,} field records)")
    print()
    # Being straight about this: at demo scale the weights are BIGGER than the
    # data, because there are only a few hundred synthetic records. Presenting
    # that as a bandwidth win would be a lie, and an easily checked one.
    if weights_bytes > record_bytes:
        print("  Note: at this demo's scale the weight traffic exceeds the data")
        print("  itself, because there are only a few hundred records. Federated")
        print("  learning is not a bandwidth optimisation and this is not the")
        print("  argument for it. At national scale -- millions of field records")
        print("  against a fixed 209-parameter model -- the comparison inverts.")
        print()
    print("  The argument is legal, not technical: the second row is a number")
    print("  no agriculture ministry will authorise across a border, and the")
    print("  first is a number that needs no treaty at all.")

    results["summary"] = {
        "mean_local_on_own_rmse": mean_local_own,
        "mean_finetuned_rmse": mean_tuned,
        "countries_improved_by_finetuning": improved,
        "countries_total": len(codes),
        "mean_local_on_foreign_rmse": mean_foreign_local,
        "mean_federated_rmse": mean_foreign_fed,
        "records_shared": 0,
        "parameters_exchanged": global_model.weights.size(),
    }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--local-epochs", type=int, default=5)
    parser.add_argument("--samples-per-site", type=int, default=60)
    parser.add_argument("--dp-noise", type=float, default=0.0,
                        help="Gaussian noise std added to averaged weights. "
                             "Not a formal DP guarantee.")
    parser.add_argument("--refresh", action="store_true",
                        help="Rebuild datasets from the live data sources.")
    parser.add_argument("--json", type=str, default="",
                        help="Write results to this path as JSON.")
    args = parser.parse_args()

    started = time.time()
    datasets = asyncio.run(load_datasets(args.samples_per_site, args.refresh))
    results = run(datasets, args.rounds, args.local_epochs, args.dp_noise)
    print(f"\nCompleted in {time.time() - started:.1f}s")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=float))
        print(f"Results written to {args.json}")


if __name__ == "__main__":
    main()
