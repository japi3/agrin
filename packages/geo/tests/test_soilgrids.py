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


import pytest


@pytest.fixture(autouse=True)
def _no_local_map(monkeypatch, request):
    """Keep the network-path tests about the network path.

    Inside the container the real India map is present, and it would answer
    before any stubbed fetch was reached. Tests of the local map opt back in.
    """
    if "local_map" in request.keywords:
        return
    monkeypatch.setattr(soilgrids, "_local_dataset", None)
    monkeypatch.setattr(soilgrids, "_local_unavailable", True)


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


# --------------------------------------------------------------------------
# The local India map
# --------------------------------------------------------------------------

def _write_map(path, *, masked_centre=False, half_masked_centre=False):
    """A tiny stand-in for the real map: 5 x 5 cells over 1 degree.

    Same band layout as scripts/build_india_soil.py writes -- property and
    depth in the band description, integers in SoilGrids' mapped units --
    so the reader is tested against the format it will actually meet.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    props = ["clay", "sand", "silt", "phh2o", "soc", "bdod", "nitrogen", "cec"]
    depths = ["0-5cm", "5-15cm", "15-30cm"]
    # Mapped units: clay 280 g/kg -> 28 %, pH 72 -> 7.2, bdod 145 -> 1.45.
    mapped = {"clay": 280, "sand": 400, "silt": 320, "phh2o": 72,
              "soc": 95, "bdod": 145, "nitrogen": 110, "cec": 180}
    bands = [(p, d) for p in props for d in depths]
    data = np.zeros((len(bands), 5, 5), dtype=np.int16)
    for i, (p, _) in enumerate(bands):
        data[i] = mapped[p]
    if masked_centre:
        data[:, 2, 2] = -32768          # a town: no soil at the pin itself
    if half_masked_centre:
        # The edge of a town: some properties mapped, texture not. Seen for
        # real in Ranchi -- bulk density and carbon present, clay, sand,
        # silt and pH absent.
        for i, (p, _) in enumerate(bands):
            if p not in ("bdod", "soc"):
                data[i, 2, 2] = -32768

    with rasterio.open(
        path, "w", driver="GTiff", width=5, height=5, count=len(bands),
        dtype="int16", crs="EPSG:4326",
        transform=from_origin(75.0, 31.0, 0.2, 0.2), nodata=-32768,
    ) as dst:
        dst.write(data)
        for i, (p, d) in enumerate(bands, start=1):
            dst.set_band_description(i, f"{p}_{d}")


def _use_map(monkeypatch, path):
    monkeypatch.setattr(soilgrids, "INDIA_SOIL_PATH", str(path))
    monkeypatch.setattr(soilgrids, "_local_dataset", None)
    monkeypatch.setattr(soilgrids, "_local_unavailable", False)


@pytest.mark.local_map
class TestTheLocalIndiaMap:
    def test_a_point_is_read_and_converted_to_real_units(self, tmp_path, monkeypatch):
        """Mapped integers must come out in the units the rest of the app uses."""
        path = tmp_path / "india.tif"
        _write_map(path)
        _use_map(monkeypatch, path)

        profile = soilgrids.local_soil_profile(30.5, 75.5)

        assert profile is not None and profile.has_data
        by = {(l.property_name, l.depth): l.mean for l in profile.layers}
        assert by[("clay", "0-5cm")] == pytest.approx(28.0)
        assert by[("phh2o", "0-5cm")] == pytest.approx(7.2)
        assert by[("bdod", "15-30cm")] == pytest.approx(1.45)
        assert profile.resolution_m == 1000

    def test_every_depth_the_app_asks_for_is_present(self, tmp_path, monkeypatch):
        path = tmp_path / "india.tif"
        _write_map(path)
        _use_map(monkeypatch, path)

        profile = soilgrids.local_soil_profile(30.5, 75.5)
        depths = {l.depth for l in profile.layers}
        assert depths == set(soilgrids.DEFAULT_DEPTHS)

    def test_a_local_reading_is_reported_as_uncertain(self, tmp_path, monkeypatch):
        """A 1 km regional average is not a measurement of one field.

        The aggregate has no prediction intervals, so every layer reads as
        low confidence and the app suggests a KVK soil test -- which is the
        honest thing to say about a regional estimate.
        """
        path = tmp_path / "india.tif"
        _write_map(path)
        _use_map(monkeypatch, path)

        profile = soilgrids.local_soil_profile(30.5, 75.5)
        assert all(not layer.is_confident for layer in profile.layers)

    def test_outside_the_map_falls_through_to_the_network(self, tmp_path, monkeypatch):
        path = tmp_path / "india.tif"
        _write_map(path)
        _use_map(monkeypatch, path)

        assert soilgrids.local_soil_profile(51.5, -0.1) is None   # London

    def test_a_masked_pin_is_resolved_locally_and_says_so(self, tmp_path, monkeypatch):
        """The case that used to cost minutes: a pin on a town centre."""
        path = tmp_path / "india.tif"
        _write_map(path, masked_centre=True)
        _use_map(monkeypatch, path)

        # The centre cell of the tiny map is masked.
        assert soilgrids.local_soil_profile(30.5, 75.5) is None

        profile = soilgrids._local_resilient(30.5, 75.5, max_search_km=30.0)
        assert profile is not None and profile.has_data
        # Substituted soil is disclosed, exactly as on the network path.
        assert profile.displaced_km is not None and profile.displaced_km > 0

    def test_the_resilient_fetch_never_touches_the_network_for_india(
        self, tmp_path, monkeypatch
    ):
        """With the map present, a point in India must not wait on ISRIC."""
        path = tmp_path / "india.tif"
        _write_map(path)
        _use_map(monkeypatch, path)

        async def network(*args, **kwargs):
            raise AssertionError("network was called for a point the map covers")

        monkeypatch.setattr(soilgrids, "fetch_soil_profile", network)
        profile = asyncio.run(fetch_soil_profile_resilient(30.5, 75.5))
        assert profile.has_data

    def test_a_missing_map_costs_nothing(self, tmp_path, monkeypatch):
        """A fresh checkout has no map, and must simply use the network."""
        _use_map(monkeypatch, tmp_path / "does-not-exist.tif")
        assert soilgrids.local_soil_profile(30.5, 75.5) is None

    def test_a_half_masked_cell_is_not_mistaken_for_soil(self, tmp_path, monkeypatch):
        """Some properties present is not the same as soil being known.

        A Ranchi cell with carbon and bulk density but no texture passed an
        "any data" check, skipped the ring search, and the farmer was told
        their soil could not be resolved. It must count as masked, so the
        search moves to a complete neighbour.
        """
        path = tmp_path / "india.tif"
        _write_map(path, half_masked_centre=True)
        _use_map(monkeypatch, path)

        assert soilgrids.local_soil_profile(30.5, 75.5) is None

        profile = soilgrids._local_resilient(30.5, 75.5, max_search_km=30.0)
        assert profile is not None
        texture = {l.property_name for l in profile.layers if l.mean is not None}
        assert {"clay", "sand", "silt", "phh2o"} <= texture
        assert profile.displaced_km and profile.displaced_km > 0
