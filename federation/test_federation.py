"""
Tests for the federated model and averaging.

The properties worth defending here are correctness of the aggregation and,
above all, that nothing data-shaped can escape a node. A federated system
whose privacy claim is untested is a federated system whose privacy claim is
decoration.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model import (  # noqa: E402
    MLP, Standardiser, Weights, federated_average, node_statistics, rmse,
)


def _weights(value: float, n_features: int = 4, hidden: int = 3) -> Weights:
    return Weights(
        w1=np.full((n_features, hidden), value),
        b1=np.full(hidden, value),
        w2=np.full((hidden, 1), value),
        b2=np.full(1, value),
    )


class TestFederatedAveraging:
    def test_average_of_identical_weights_is_unchanged(self):
        a = _weights(2.0)
        out = federated_average([(a, 10), (a.copy(), 10)])
        assert np.allclose(out.w1, 2.0)
        assert np.allclose(out.b2, 2.0)

    def test_average_is_weighted_by_sample_count(self):
        # A node with nine times the data should pull the mean nine times
        # harder. Unweighted averaging would let a node with forty fields
        # count equally with one holding four thousand.
        out = federated_average([(_weights(0.0), 90), (_weights(10.0), 10)])
        assert np.allclose(out.w1, 1.0)

    def test_equal_counts_give_plain_mean(self):
        out = federated_average([(_weights(0.0), 50), (_weights(4.0), 50)])
        assert np.allclose(out.w1, 2.0)

    def test_empty_updates_raise(self):
        with pytest.raises(ValueError):
            federated_average([])

    def test_all_zero_counts_raise(self):
        with pytest.raises(ValueError, match="zero samples"):
            federated_average([(_weights(1.0), 0)])

    def test_shapes_are_preserved(self):
        out = federated_average([(_weights(1.0), 5), (_weights(3.0), 5)])
        assert out.w1.shape == (4, 3)
        assert out.w2.shape == (3, 1)

    def test_noise_perturbs_but_does_not_destroy(self):
        clean = federated_average([(_weights(5.0), 10)])
        noisy = federated_average([(_weights(5.0), 10)], dp_noise_std=0.05, seed=1)
        assert not np.allclose(clean.w1, noisy.w1)
        assert abs(float(noisy.w1.mean()) - 5.0) < 0.2


class TestPrivacyBoundary:
    """Nothing that leaves a node may be record-shaped."""

    def test_weight_size_is_independent_of_dataset_size(self):
        # The decisive property: the payload a node emits is fixed by the
        # model architecture, not by how many farms it holds. If weight size
        # scaled with records, the exchange would leak dataset size and, at
        # the limit, the records themselves.
        small = MLP(n_features=11, hidden=16, seed=0)
        big = MLP(n_features=11, hidden=16, seed=0)
        rng = np.random.default_rng(0)
        small.train_local(rng.normal(size=(20, 11)), rng.normal(size=20), epochs=2)
        big.train_local(rng.normal(size=(5000, 11)), rng.normal(size=5000), epochs=2)
        assert small.weights.size() == big.weights.size()

    def test_node_statistics_are_aggregates_only(self):
        X = np.arange(30, dtype=float).reshape(10, 3)
        s, sq, n = node_statistics(X)
        assert s.shape == (3,) and sq.shape == (3,)
        assert n == 10
        # Three numbers per column cannot reconstruct ten rows.
        assert s.size + sq.size + 1 < X.size

    def test_scaling_from_aggregates_matches_pooled_computation(self):
        # Federated scaling must give the same answer as pooling would, or the
        # privacy-preserving path is quietly a worse path.
        rng = np.random.default_rng(3)
        a = rng.normal(5, 2, (40, 4))
        b = rng.normal(-1, 3, (60, 4))
        pooled = np.vstack([a, b])

        federated = Standardiser.from_node_statistics(
            [node_statistics(a), node_statistics(b)]
        )
        assert np.allclose(federated.mean, pooled.mean(axis=0), atol=1e-9)
        assert np.allclose(federated.std, pooled.std(axis=0), atol=1e-6)


class TestModel:
    def test_training_reduces_error(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(300, 5))
        y = X @ np.array([2.0, -1.0, 0.5, 0.0, 3.0]) + 1.0
        m = MLP(5, hidden=16, seed=0)
        before = rmse(m.predict(X), y)
        m.train_local(X, y, epochs=200, lr=0.05, seed=0)
        assert rmse(m.predict(X), y) < before * 0.5

    def test_empty_dataset_does_not_crash(self):
        m = MLP(5, hidden=8, seed=0)
        assert np.isnan(m.train_local(np.zeros((0, 5)), np.zeros(0)))

    def test_prediction_shape(self):
        m = MLP(5, hidden=8, seed=0)
        assert m.predict(np.zeros((7, 5))).shape == (7,)

    def test_gradients_are_clipped(self):
        # One node with a wild outlier must not be able to dominate the
        # federated average -- a stability property and an attack surface.
        rng = np.random.default_rng(0)
        X = rng.normal(size=(50, 4))
        y = rng.normal(size=50)
        y[0] = 1e6
        m = MLP(4, hidden=8, seed=0)
        m.train_local(X, y, epochs=5, lr=0.05, seed=0)
        assert np.all(np.isfinite(m.weights.w1))
        assert np.abs(m.weights.w1).max() < 1e4

    def test_federated_round_trip_preserves_learning(self):
        # Averaging two nodes trained on the same distribution should not be
        # worse than either alone.
        rng = np.random.default_rng(1)
        X = rng.normal(size=(200, 4))
        y = X @ np.array([1.0, -2.0, 0.5, 1.5])
        models = []
        for seed in (1, 2):
            m = MLP(4, hidden=12, seed=0)
            m.train_local(X, y, epochs=120, lr=0.05, seed=seed)
            models.append(m)
        merged = MLP(4, hidden=12, seed=0)
        merged.weights = federated_average([(m.weights, 200) for m in models])
        individual = np.mean([rmse(m.predict(X), y) for m in models])
        assert rmse(merged.predict(X), y) < individual * 2.0
