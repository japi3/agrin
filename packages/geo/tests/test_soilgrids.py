"""
Tests for the SoilGrids urban-mask ring search.

These exercise the search logic, not ISRIC. Every test substitutes a stub for
the single-point fetch, so the behaviour under test is how the search reacts
to points that answer, points that are masked, and a service that is slow --
none of which can be provoked reliably against the live endpoint.

Why this file exists: on 20 September 2026 the search returned an empty soil
profile for coordinates that were perfectly well mapped. The point query was
merely slow, the client timeout was shorter than the service's response time,
and a timeout was indistinguishable from "no soil here". Nothing failed
loudly. The cases below pin down the parts of that behaviour that are ours.
"""

import asyncio

from geo import soilgrids
from geo.soilgrids import (
    SoilLayer,
    SoilProfile,
    fetch_soil_profile_resilient,
)


def _profile(lat: float, lon: float, *, with_data: bool) -> SoilProfile:
    """A profile that either carries a reading or is masked."""
    layers = []
    if with_data:
        layers = [
            SoilLayer(
                property_name="clay",
                depth="0-5cm",
                mean=28.0,
                q05=24.0,
                q95=33.0,
                unit="%",
                label="Clay",
            )
        ]
    return SoilProfile(latitude=lat, longitude=lon, layers=layers)


class TestThePointItself:
    def test_a_point_with_soil_is_returned_without_searching(self, monkeypatch):
        """The common case must cost exactly one query.

        The search used to speculate four extra queries on every cache miss.
        That was a reasonable trade when a query took five seconds and a poor
        one when it took ninety, so the point is now asked about alone.
        """
        calls = []

        async def stub(lat, lon, *args, **kwargs):
            calls.append((lat, lon))
            return _profile(lat, lon, with_data=True)

        monkeypatch.setattr(soilgrids, "fetch_soil_profile", stub)
        profile = asyncio.run(fetch_soil_profile_resilient(30.9, 75.85))

        assert profile.has_data
        assert len(calls) == 1
        assert profile.displaced_km is None

    def test_a_masked_point_falls_back_to_the_ring(self, monkeypatch):
        """A pin on a village centre is masked; its fields are not."""

        async def stub(lat, lon, *args, **kwargs):
            masked = (lat, lon) == (30.9, 75.85)
            return _profile(lat, lon, with_data=not masked)

        monkeypatch.setattr(soilgrids, "fetch_soil_profile", stub)
        profile = asyncio.run(fetch_soil_profile_resilient(30.9, 75.85))

        assert profile.has_data
        # Substituted soil must say so: silently passing off a neighbour's
        # soil as this field's would be the wrong trade.
        assert profile.displaced_km is not None
        assert profile.displaced_km > 0
        assert profile.displaced_from == (30.9, 75.85)

    def test_a_failing_point_query_does_not_raise(self, monkeypatch):
        """An upstream failure becomes an abstention, never an exception."""

        async def stub(lat, lon, *args, **kwargs):
            raise soilgrids.SoilGridsError("service unavailable")

        monkeypatch.setattr(soilgrids, "fetch_soil_profile", stub)
        profile = asyncio.run(fetch_soil_profile_resilient(30.9, 75.85))

        assert not profile.has_data
        assert profile.search_exhausted


class TestTheSearchBudget:
    def test_a_slow_service_cannot_hang_the_caller(self, monkeypatch):
        """Five rings of eight bearings is forty-one queries.

        Unbounded, a slow upstream turns that into a wait no farmer would sit
        through. The budget makes the search give up and abstain instead.
        """

        async def slow_and_masked(lat, lon, *args, **kwargs):
            await asyncio.sleep(0.05)
            return _profile(lat, lon, with_data=False)

        monkeypatch.setattr(soilgrids, "fetch_soil_profile", slow_and_masked)

        async def run():
            started = asyncio.get_running_loop().time()
            profile = await fetch_soil_profile_resilient(30.9, 75.85, budget_s=0.15)
            return profile, asyncio.get_running_loop().time() - started

        profile, elapsed = asyncio.run(run())

        assert not profile.has_data
        assert profile.search_exhausted
        # Generous headroom: the point is that it stops, not that it stops
        # to the millisecond.
        assert elapsed < 2.0

    def test_the_budget_does_not_cut_a_search_that_succeeds(self, monkeypatch):
        """A hit in the first ring must survive a budget that is merely finite."""

        async def stub(lat, lon, *args, **kwargs):
            masked = (lat, lon) == (30.9, 75.85)
            return _profile(lat, lon, with_data=not masked)

        monkeypatch.setattr(soilgrids, "fetch_soil_profile", stub)
        profile = asyncio.run(
            fetch_soil_profile_resilient(30.9, 75.85, budget_s=30.0)
        )

        assert profile.has_data


class TestConfiguration:
    def test_the_timeout_exceeds_observed_service_latency(self):
        """The bug was a 30 second budget against a 26-115 second service."""
        assert soilgrids.SOILGRIDS_TIMEOUT_S >= 120.0

    def test_concurrency_stays_low_enough_not_to_be_shed(self):
        """ISRIC sheds load rather than queueing it."""
        assert soilgrids._ISRIC_CONCURRENCY._value <= 2
