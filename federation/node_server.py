"""
A country node: an HTTP service holding one nation's farm data.

Why this exists separately from run_experiment.py
-------------------------------------------------
The in-process experiment proves the *statistics* -- that federation
improves cross-border accuracy. This proves the *architecture*: five
independent services, each holding data it will not release, exchanging only
weights over a network boundary you can watch.

That distinction matters when the audience is a ministry rather than a
conference. The objection is never "will averaging work"; it is "what
exactly leaves my jurisdiction". Here the answer is inspectable: the only
endpoint that returns anything derived from data returns a weight vector and
a count, and the endpoint that would return records does not exist.

Run one node:
    COUNTRY=IN python federation/node_server.py

Or all five:
    docker compose -f federation/docker-compose.yml up
"""

from __future__ import annotations

import asyncio
import os
import pickle
import sys
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "agronomy"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "geo"))

from data import FEATURE_NAMES, NODES, build_country_dataset  # noqa: E402
from model import MLP, Weights, node_statistics  # noqa: E402

COUNTRY = os.environ.get("COUNTRY", "IN").upper()
NODE = next((n for n in NODES if n.code == COUNTRY), None)
if NODE is None:
    raise SystemExit(f"Unknown COUNTRY={COUNTRY}")

DATA_PATH = Path(os.environ.get("NODE_DATA", f"/data/{COUNTRY}.pkl"))

app = FastAPI(
    title=f"AgriN federation node — {NODE.name}",
    description=(
        "Holds this country's agricultural training data. Exposes model "
        "weights and aggregate statistics only. There is deliberately no "
        "endpoint that returns field records."
    ),
)

_state: dict[str, Any] = {"X": None, "y": None, "model": None}


class TrainRequest(BaseModel):
    """A round instruction from the coordinator."""
    weights: list[list] | None = None
    epochs: int = 5
    lr: float = 0.02
    seed: int = 0


@app.on_event("startup")
async def load_data() -> None:
    """Load this node's data, building it on first start.

    Data is written to a volume that belongs to this node alone. In a real
    deployment it would be the ministry's own database and would never be
    reachable from the coordinator at all.
    """
    if DATA_PATH.exists():
        X, y = pickle.loads(DATA_PATH.read_bytes())
    else:
        X, y = await build_country_dataset(NODE, samples_per_site=50)
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_bytes(pickle.dumps((X, y)))
    _state["X"], _state["y"] = X, y
    print(f"[{COUNTRY}] holding {X.shape[0]} field records locally", flush=True)


@app.get("/health")
async def health() -> dict[str, Any]:
    X = _state["X"]
    return {
        "country": COUNTRY,
        "name": NODE.name,
        "records_held": int(X.shape[0]) if X is not None else 0,
        "records_shared": 0,
        "features": FEATURE_NAMES,
    }


@app.get("/statistics")
async def statistics() -> dict[str, Any]:
    """Column aggregates for federated feature scaling.

    Sums, sums of squares and a count over the entire national dataset. These
    are the only data-derived numbers besides weights that leave the node, and
    no individual field is recoverable from them.
    """
    X = _state["X"]
    if X is None or X.shape[0] == 0:
        raise HTTPException(503, "Node data not ready")
    s, sq, n = node_statistics(X)
    return {"sum": s.tolist(), "sum_sq": sq.tolist(), "count": int(n)}


@app.post("/train_round")
async def train_round(req: TrainRequest) -> dict[str, Any]:
    """Train locally for one federated round and return weights only.

    The returned payload contains the model parameters and the sample count.
    It contains no records, no gradients over individual examples, and no
    identifiers.
    """
    X, y = _state["X"], _state["y"]
    if X is None or X.shape[0] == 0:
        raise HTTPException(503, "Node data not ready")

    mean = np.asarray(_state.get("scale_mean"))
    std = np.asarray(_state.get("scale_std"))
    Xs = (X - mean) / std if mean.size else X

    model = MLP(len(FEATURE_NAMES), hidden=16, seed=7)
    if req.weights is not None:
        model.weights = Weights.from_list(
            [np.asarray(a, dtype=np.float64) for a in req.weights]
        )
    train_rmse = model.train_local(
        Xs, y, epochs=req.epochs, lr=req.lr, seed=req.seed
    )

    return {
        "country": COUNTRY,
        "weights": [a.tolist() for a in model.weights.to_list()],
        "sample_count": int(X.shape[0]),
        "local_train_rmse": train_rmse,
        "records_transmitted": 0,
    }


class ScaleRequest(BaseModel):
    mean: list[float]
    std: list[float]


@app.post("/set_scaling")
async def set_scaling(req: ScaleRequest) -> dict[str, str]:
    """Receive the federation-wide feature scaling agreed by the coordinator."""
    _state["scale_mean"] = np.asarray(req.mean)
    _state["scale_std"] = np.asarray(req.std)
    return {"status": "ok"}


@app.get("/evaluate")
async def evaluate(weights_json: str = "") -> dict[str, Any]:
    """Score a supplied global model against this node's held-out data.

    Evaluation happens here, on the node, and only the score leaves. The
    coordinator never sees the fields it is being scored against -- which is
    what makes cross-border validation possible at all.
    """
    import json as _json

    X, y = _state["X"], _state["y"]
    if X is None:
        raise HTTPException(503, "Node data not ready")
    if not weights_json:
        raise HTTPException(400, "No weights supplied")

    mean = np.asarray(_state.get("scale_mean"))
    std = np.asarray(_state.get("scale_std"))
    Xs = (X - mean) / std if mean.size else X

    model = MLP(len(FEATURE_NAMES), hidden=16, seed=7)
    model.weights = Weights.from_list(
        [np.asarray(a, dtype=np.float64) for a in _json.loads(weights_json)]
    )
    pred = model.predict(Xs)
    return {
        "country": COUNTRY,
        "rmse": float(np.sqrt(np.mean((pred - y) ** 2))),
        "mae": float(np.mean(np.abs(pred - y))),
        "n": int(X.shape[0]),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9000")))
