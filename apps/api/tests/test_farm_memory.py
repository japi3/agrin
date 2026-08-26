"""
Tests for the farm record: what a farmer tells us, and what we show back.

The feature exists because an assistant that forgets between sessions asks a
farmer to repeat themselves forever. These tests defend the properties that
make the record trustworthy rather than merely present:

  * a farmer can state several crops in one sentence and have all of them
    recorded,
  * dates are sanity-checked, because a sowing date in the wrong year does
    not fail loudly -- it silently produces a water balance for a crop that
    would already have been harvested,
  * what the farmer said stays attributable to the farmer, and
  * the field being written to is chosen by the server, never by the model.
"""

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[1]
_ROOT = Path(__file__).resolve().parents[3]
for _p in (_API, _ROOT / "packages" / "agronomy", _ROOT / "packages" / "geo"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture()
def field_id(monkeypatch):
    """A fresh database and one field, per test."""
    db = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("AGRIN_DB", db)
    import importlib
    from agrin_api import storage
    importlib.reload(storage)
    storage.init_db()
    farmer = storage.create_farmer("pa")
    return storage.add_field(farmer, 31.4520, 74.9280)


class TestRecordingWhatAFarmerSays:
    async def test_several_crops_in_one_statement(self, field_id):
        """"I have sown maize and paddy" must record both.

        Accepting one crop per call meant this sentence was filed as a
        general note with no crop attached to either, so no stage or
        irrigation advice was possible for a farm that had just said exactly
        what was in the ground.
        """
        from agrin_api import storage, tools
        r = await tools.remember_about_my_farm(
            field_id=field_id, crops=["maize_grain", "rice_paddy"],
            sowing_date=(date.today() - timedelta(days=60)).isoformat(),
        )
        assert r["ok"]
        assert {s["crop"] for s in storage.active_seasons(field_id)} == {
            "maize_grain", "rice_paddy"
        }

    async def test_acres_are_stored_as_hectares_and_read_back_as_acres(self, field_id):
        # Farmers speak in acres; every agronomic model uses hectares.
        from agrin_api import tools
        await tools.remember_about_my_farm(field_id=field_id, area_acres=5)
        farm = await tools.get_my_farm(field_id=field_id)
        assert farm["field"]["area_acres"] == pytest.approx(5.0, abs=0.01)
        assert farm["field"]["area_hectares"] == pytest.approx(2.023, abs=0.01)

    async def test_irrigation_is_recorded_in_pump_hours(self, field_id):
        # Farmers measure irrigation in hours of pumping far more often than
        # in millimetres.
        from agrin_api import tools
        when = (date.today() - timedelta(days=7)).isoformat()
        await tools.remember_about_my_farm(
            field_id=field_id, irrigated_on=when, hours_pumped=3.0,
            irrigation_method="flood",
        )
        farm = await tools.get_my_farm(field_id=field_id)
        assert farm["last_irrigation"]["days_ago"] == 7
        assert farm["last_irrigation"]["hours_pumped"] == 3.0

    async def test_recording_the_same_crop_twice_does_not_duplicate(self, field_id):
        from agrin_api import storage, tools
        for _ in range(3):
            await tools.remember_about_my_farm(field_id=field_id, crop="maize_grain")
        assert len(storage.active_seasons(field_id)) == 1

    async def test_unknown_crop_is_refused_rather_than_stored(self, field_id):
        # Storing a crop with no agronomic parameters would let the farmer
        # believe calculated advice is coming when none is possible.
        from agrin_api import tools
        r = await tools.remember_about_my_farm(field_id=field_id, crops=["dragonfruit"])
        assert r["ok"] is False
        assert "dragonfruit" in r["abstain_reason"]

    async def test_nothing_to_record_is_reported(self, field_id):
        from agrin_api import tools
        assert (await tools.remember_about_my_farm(field_id=field_id))["ok"] is False


class TestDateSanity:
    """A date in the wrong year corrupts the water balance silently."""

    async def test_date_two_years_stale_is_refused(self, field_id):
        from agrin_api import tools
        r = await tools.remember_about_my_farm(
            field_id=field_id, irrigated_on="2024-08-19"
        )
        assert r["ok"] is False
        assert "mistake in working out the year" in r["abstain_reason"]
        # The correct date must be in the message, so the model can retry.
        assert date.today().isoformat() in r["abstain_reason"]

    async def test_far_future_date_is_refused(self, field_id):
        from agrin_api import tools
        future = (date.today() + timedelta(days=200)).isoformat()
        assert (await tools.remember_about_my_farm(
            field_id=field_id, irrigated_on=future))["ok"] is False

    async def test_recent_past_is_accepted(self, field_id):
        from agrin_api import tools
        recent = (date.today() - timedelta(days=9)).isoformat()
        assert (await tools.remember_about_my_farm(
            field_id=field_id, irrigated_on=recent))["ok"]

    async def test_a_sowing_date_last_season_is_accepted(self, field_id):
        # Sowing genuinely can be ~300 days back for a long-duration crop.
        from agrin_api import tools
        assert (await tools.remember_about_my_farm(
            field_id=field_id, crop="sugarcane",
            sowing_date=(date.today() - timedelta(days=300)).isoformat()))["ok"]

    async def test_unparseable_date_is_refused(self, field_id):
        from agrin_api import tools
        r = await tools.remember_about_my_farm(
            field_id=field_id, irrigated_on="last Tuesday")
        assert r["ok"] is False


class TestWhatAReturningFarmerSees:
    async def test_missing_details_are_listed(self, field_id):
        from agrin_api import tools
        farm = await tools.get_my_farm(field_id=field_id)
        assert "field size" in farm["missing"]
        assert "what is planted" in farm["missing"]

    async def test_missing_shrinks_as_facts_arrive(self, field_id):
        from agrin_api import tools
        before = (await tools.get_my_farm(field_id=field_id))["missing"]
        await tools.remember_about_my_farm(
            field_id=field_id, area_acres=5, crops=["maize_grain"],
            sowing_date=(date.today() - timedelta(days=40)).isoformat(),
            irrigated_on=(date.today() - timedelta(days=5)).isoformat(),
        )
        after = (await tools.get_my_farm(field_id=field_id))["missing"]
        assert len(after) < len(before)
        assert after == []

    async def test_growth_stage_is_computed_per_crop(self, field_id):
        from agrin_api import tools
        await tools.remember_about_my_farm(
            field_id=field_id, crops=["maize_grain"],
            sowing_date=(date.today() - timedelta(days=60)).isoformat())
        farm = await tools.get_my_farm(field_id=field_id)
        crop = farm["crops_growing"][0]
        assert crop["days_after_sowing"] == 60
        assert crop["growth_stage"]
        assert crop["days_to_harvest"] > 0

    async def test_farmer_statements_stay_attributed(self, field_id):
        # The farmer's own account must never be merged into model output.
        from agrin_api import tools
        await tools.remember_about_my_farm(
            field_id=field_id, soil_observation="light and sandy")
        farm = await tools.get_my_farm(field_id=field_id)
        said = [n["said"] for n in farm["farmer_said"]]
        assert "light and sandy" in said

    async def test_no_field_is_an_honest_refusal(self):
        from agrin_api import tools
        for fn in (tools.get_my_farm, tools.remember_about_my_farm):
            r = await fn(field_id=None)
            assert r["ok"] is False
            assert "abstain_reason" in r


class TestFieldScoping:
    """The model must not be able to choose which farm it writes to."""

    def test_field_scoped_tools_are_declared(self):
        from agrin_api.orchestrator import FIELD_SCOPED_TOOLS, TOOL_REGISTRY
        assert "remember_about_my_farm" in FIELD_SCOPED_TOOLS
        assert "get_my_farm" in FIELD_SCOPED_TOOLS
        for name in FIELD_SCOPED_TOOLS:
            assert name in TOOL_REGISTRY

    async def test_model_supplied_field_id_is_overridden(self, field_id):
        """A hallucinated identifier must not reach another farmer's land."""
        from agrin_api import storage
        from agrin_api.orchestrator import _run_tool

        other_farmer = storage.create_farmer("en")
        other_field = storage.add_field(other_farmer, 20.0, 77.0)

        # The model asks to write to someone else's field; the server injects
        # the real one from the active conversation.
        await _run_tool(
            "remember_about_my_farm",
            {"field_id": other_field, "area_acres": 99},
            field_id=field_id,
        )
        assert storage.get_field(other_field).get("area_hectares") is None
        assert storage.get_field(field_id).get("area_hectares") is not None
