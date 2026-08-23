"""
The federation coordinator.

Orchestrates FedAvg across the country nodes. Holds no data of its own and
has no means of obtaining any -- the nodes expose no endpoint that returns
records, so a compromised coordinator leaks weights, not farms. That property
is the entire architectural argument, and it is worth being able to point at
in the code rather than in a slide.

Run against the compose stack:
    python federation/coordinator.py --rounds 15
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import httpx
import numpy as np

DEFAULT_NODES = {
    "IN": "http://localhost:9001",
    "BR": "http://localhost:9002",
    "RU": "http://localhost:9003",
    "CN": "http://localhost:9004",
    "ZA": "http://localhost:9005",
}


def node_urls() -> dict[str, str]:
    """Node addresses, overridable for the compose network."""
    override = os.environ.get("FEDERATION_NODES", "").strip()
    if not override:
        return DEFAULT_NODES
    # Format: IN=http://in:9000,BR=http://br:9000
    out = {}
    for part in override.split(","):
        code, _, url = part.partition("=")
        if code and url:
            out[code.strip()] = url.strip()
    return out


async def wait_for_nodes(
    client: httpx.AsyncClient, nodes: dict[str, str], timeout: float = 900.0
) -> dict[str, str]:
    """Wait until nodes report ready.

    First start is slow: each node builds its national dataset from live
    SoilGrids and ERA5, which takes minutes. Polling with a generous timeout
    is correct here rather than failing fast -- the alternative is a demo that
    reliably fails the first time it is run.
    """
    ready: dict[str, str] = {}
    deadline = time.time() + timeout
    print("Waiting for country nodes to come up...")
    while time.time() < deadline and len(ready) < len(nodes):
        for code, url in nodes.items():
            if code in ready:
                continue
            try:
                r = await client.get(f"{url}/health", timeout=10.0)
                if r.status_code == 200 and r.json().get("records_held", 0) > 0:
                    info = r.json()
                    ready[code] = url
                    print(f"  {code} {info['name']:14s} ready — "
                          f"{info['records_held']} records held locally, "
                          f"{info['records_shared']} shared")
            except Exception:
                pass
        if len(ready) < len(nodes):
            await asyncio.sleep(5)
    return ready


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--local-epochs", type=int, default=5)
    parser.add_argument("--dp-noise", type=float, default=0.0)
    args = parser.parse_args()

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model import MLP, Standardiser, Weights, federated_average  # noqa: E402
    from data import FEATURE_NAMES  # noqa: E402

    async with httpx.AsyncClient(timeout=120.0) as client:
        nodes = await wait_for_nodes(client, node_urls())
        if len(nodes) < 2:
            print("Need at least two nodes for a federation. Aborting.")
            return

        # --- Federated feature scaling --------------------------------
        print("\nAgreeing feature scaling from node aggregates "
              "(sums and counts only; no records)...")
        stats = []
        for code, url in nodes.items():
            s = (await client.get(f"{url}/statistics")).json()
            stats.append((
                np.asarray(s["sum"]), np.asarray(s["sum_sq"]), s["count"]
            ))
        scaler = Standardiser.from_node_statistics(stats)
        for url in nodes.values():
            await client.post(f"{url}/set_scaling", json={
                "mean": scaler.mean.tolist(), "std": scaler.std.tolist(),
            })
        print("  scaling distributed to all nodes")

        # --- Federated rounds ------------------------------------------
        model = MLP(len(FEATURE_NAMES), hidden=16, seed=7)
        total_bytes = 0

        print(f"\nRunning {args.rounds} federated rounds "
              f"({args.local_epochs} local epochs each)")
        for rnd in range(1, args.rounds + 1):
            payload = {
                "weights": [a.tolist() for a in model.weights.to_list()],
                "epochs": args.local_epochs,
                "lr": 0.02,
                "seed": rnd,
            }
            responses = await asyncio.gather(*[
                client.post(f"{url}/train_round", json=payload)
                for url in nodes.values()
            ], return_exceptions=True)

            updates = []
            for resp in responses:
                if isinstance(resp, BaseException) or resp.status_code != 200:
                    continue
                d = resp.json()
                assert d["records_transmitted"] == 0
                total_bytes += len(resp.content)
                updates.append((
                    Weights.from_list([np.asarray(a) for a in d["weights"]]),
                    d["sample_count"],
                ))

            if not updates:
                print(f"  round {rnd}: no nodes responded; aborting")
                return

            model.weights = federated_average(
                updates, dp_noise_std=args.dp_noise, seed=rnd
            )

            if rnd % max(1, args.rounds // 5) == 0 or rnd == args.rounds:
                weights_json = json.dumps(
                    [a.tolist() for a in model.weights.to_list()]
                )
                # Evaluation happens on each node, against data the
                # coordinator never sees. Only the score comes back.
                scores = await asyncio.gather(*[
                    client.get(f"{url}/evaluate", params={"weights_json": weights_json})
                    for url in nodes.values()
                ], return_exceptions=True)
                values = [
                    s.json()["rmse"] for s in scores
                    if not isinstance(s, BaseException) and s.status_code == 200
                ]
                print(f"  round {rnd:3d}   mean RMSE across nodes: "
                      f"{np.mean(values):6.1f} mm")

        print("\n" + "=" * 66)
        print("FEDERATION COMPLETE")
        print("=" * 66)
        print(f"  Participating countries:   {len(nodes)}")
        print(f"  Field records transmitted: 0")
        print(f"  Model parameters shared:   {model.weights.size():,} per node per round")
        print(f"  Total network traffic:     {total_bytes / 1024:,.0f} KB")
        print("\n  Every node trained on data that never left its jurisdiction.")


if __name__ == "__main__":
    asyncio.run(main())
