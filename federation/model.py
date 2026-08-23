"""
The shared model and federated averaging.

Deliberately a small numpy MLP rather than a deep-learning framework. Three
reasons, all practical rather than aesthetic:

  * A national agriculture ministry can audit two hundred lines of numpy. It
    cannot realistically audit a training stack, and "trust our model" is
    exactly the thing cross-border data sharing founders on.
  * The weight vector is small enough to print. Being able to *show* a
    sceptical partner precisely what crosses the border -- a few thousand
    floats, no records -- is worth more than accuracy here.
  * It runs on a laptop and inside a 700 MB container with no GPU.

Federated averaging is FedAvg (McMahan et al., 2017): each node trains on
its own data for some local epochs, sends only its weights and its sample
count, and the coordinator returns the sample-weighted mean. No gradients
over individual records, no records, no identifiers.

Reference:
    McMahan, B., Moore, E., Ramage, D., Hampson, S., Aguera y Arcas, B.
    (2017). "Communication-Efficient Learning of Deep Networks from
    Decentralized Data." AISTATS 54:1273-1282.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Weights:
    """A complete model parameter set. This, and only this, crosses a border."""
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray

    def to_list(self) -> list[np.ndarray]:
        return [self.w1, self.b1, self.w2, self.b2]

    @staticmethod
    def from_list(arrays: list[np.ndarray]) -> "Weights":
        return Weights(*arrays)

    def size(self) -> int:
        """Number of scalar parameters -- what actually goes over the wire."""
        return sum(a.size for a in self.to_list())

    def copy(self) -> "Weights":
        return Weights(*(a.copy() for a in self.to_list()))


class MLP:
    """One hidden layer, ReLU, scalar regression output.

    Small on purpose. The target (seasonal irrigation requirement) is a smooth
    function of a handful of physical inputs, and a larger network would
    memorise its node's local records -- which in a federated setting is not
    merely overfitting but a privacy problem, since memorised weights can leak
    the records they memorised.
    """

    def __init__(self, n_features: int, hidden: int = 16, seed: int = 0):
        rng = np.random.default_rng(seed)
        # He initialisation, appropriate for ReLU.
        self.weights = Weights(
            w1=rng.normal(0, np.sqrt(2.0 / n_features), (n_features, hidden)),
            b1=np.zeros(hidden),
            w2=rng.normal(0, np.sqrt(2.0 / hidden), (hidden, 1)),
            b2=np.zeros(1),
        )

    def forward(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        z1 = X @ self.weights.w1 + self.weights.b1
        a1 = np.maximum(z1, 0.0)
        out = a1 @ self.weights.w2 + self.weights.b2
        return out.ravel(), a1

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.forward(X)[0]

    def train_local(
        self, X: np.ndarray, y: np.ndarray, epochs: int = 40,
        lr: float = 0.01, batch_size: int = 32, seed: int = 0,
    ) -> float:
        """Train on local data only. Returns final training RMSE.

        Plain mini-batch SGD on mean squared error. Gradients are clipped:
        a single node with an unusual field can otherwise produce an update
        large enough to dominate the federated average, which is both a
        stability problem and an attack surface.
        """
        rng = np.random.default_rng(seed)
        n = X.shape[0]
        if n == 0:
            return float("nan")

        for _ in range(epochs):
            order = rng.permutation(n)
            for start in range(0, n, batch_size):
                idx = order[start:start + batch_size]
                xb, yb = X[idx], y[idx]
                m = xb.shape[0]

                pred, a1 = self.forward(xb)
                error = (pred - yb).reshape(-1, 1)          # dL/dout
                g_w2 = a1.T @ error / m
                g_b2 = error.mean(axis=0)
                d_a1 = error @ self.weights.w2.T
                d_z1 = d_a1 * (a1 > 0)
                g_w1 = xb.T @ d_z1 / m
                g_b1 = d_z1.mean(axis=0)

                for grad in (g_w1, g_b1, g_w2, g_b2):
                    norm = np.linalg.norm(grad)
                    if norm > 5.0:
                        grad *= 5.0 / norm

                self.weights.w1 -= lr * g_w1
                self.weights.b1 -= lr * g_b1
                self.weights.w2 -= lr * g_w2
                self.weights.b2 -= lr * g_b2

        return float(np.sqrt(np.mean((self.predict(X) - y) ** 2)))


def federated_average(
    updates: list[tuple[Weights, int]], dp_noise_std: float = 0.0,
    seed: int = 0,
) -> Weights:
    """FedAvg: sample-count-weighted mean of node weights.

    Weighting by sample count is what stops a node with forty fields having
    the same influence as one with four thousand. It is also the one number
    besides the weights that leaves a node, and it is an aggregate over the
    whole national dataset, so it carries no information about any farm.

    `dp_noise_std` adds Gaussian noise to the averaged weights. This is not a
    formal differential-privacy guarantee -- that needs per-example gradient
    clipping and a spent privacy budget -- and it is labelled as such
    everywhere it surfaces. It is included because it is the hook a real
    deployment would attach DP-SGD to, and because showing partners a working
    noise knob is how that conversation starts.
    """
    if not updates:
        raise ValueError("No updates to aggregate")

    total = sum(n for _, n in updates)
    if total == 0:
        raise ValueError("All nodes reported zero samples")

    stacked = [
        sum(w.to_list()[i] * (n / total) for w, n in updates)
        for i in range(4)
    ]

    if dp_noise_std > 0:
        rng = np.random.default_rng(seed)
        stacked = [a + rng.normal(0, dp_noise_std, a.shape) for a in stacked]

    return Weights.from_list(stacked)


@dataclass
class Standardiser:
    """Feature scaling agreed across the federation.

    Scaling has to be shared, or every node's weights describe a different
    input space and averaging them is meaningless. But computing it centrally
    would require pooling the data, which is the thing we are avoiding.

    So the mean and variance are themselves computed federatedly: each node
    reports only its column sums, sums of squares, and count -- aggregates
    over its entire national dataset, from which no individual field can be
    recovered.
    """
    mean: np.ndarray
    std: np.ndarray

    def transform(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.std

    @staticmethod
    def from_node_statistics(
        stats: list[tuple[np.ndarray, np.ndarray, int]]
    ) -> "Standardiser":
        """Build from per-node (sum, sum_of_squares, count) triples."""
        total_n = sum(n for _, _, n in stats)
        if total_n == 0:
            raise ValueError("No samples across the federation")
        total_sum = sum(s for s, _, _ in stats)
        total_sq = sum(sq for _, sq, _ in stats)
        mean = total_sum / total_n
        var = np.maximum(total_sq / total_n - mean ** 2, 1e-9)
        return Standardiser(mean=mean, std=np.sqrt(var))


def node_statistics(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """The only summary a node publishes for scaling. No records leave."""
    return X.sum(axis=0), (X ** 2).sum(axis=0), X.shape[0]


def rmse(pred: np.ndarray, actual: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - actual) ** 2)))


def mae(pred: np.ndarray, actual: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - actual)))
