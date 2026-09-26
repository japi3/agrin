"""
The crop-value tool, with its two slow dependencies stubbed.

Soil, weather and the mandi service are all substituted here. What is under
test is the composition -- that a water-stress fraction becomes a yield
range, that a quoted rate becomes rupees, that a dearer market becomes a
number worth acting on, and that each of those disappears cleanly when its
input is missing.

The last part matters most. On the day this was written the government price
service was unreachable, and the right behaviour was to report the quintals
and the support price and simply leave the rupees blank. A tool that filled
that gap with an estimate would be inventing the one number a farmer would
act on.
"""

from datetime import date, timedelta

import pytest

from agrin_api import tools


class _Quote:
    def __init__(self, market, modal):
        self.market = market
        self.modal_price = modal
        self.arrival_date = date.today()


class _Report:
    def __init__(self, quotes):
        self.quotes = quotes


@pytest.fixture
def field(monkeypatch):
    """A field with known soil and a season of adequate rain."""
    from agronomy.waterbalance import DailyWeather

    class _Profile:
        has_data = True
        texture_fractions = (40.0, 35.0, 25.0)

        def evidence(self):
            return {}

    class _Weather:
        elevation_m = 300.0
        latitude = 20.0

        def evidence(self):
            return {}

    async def soil_and_weather(lat, lon):
        return _Profile(), _Weather()

    def to_daily(series, elevation, latitude):
        start = date.today() - timedelta(days=60)
        return [
            DailyWeather(
                day=start + timedelta(days=i),
                t_max=30.0, t_min=20.0,
                rain_mm=6.0,            # comfortably watered: little stress
                et0_mm=4.0,
            )
            for i in range(60)
        ]

    monkeypatch.setattr(tools, "_soil_and_weather", soil_and_weather)
    monkeypatch.setattr(tools, "_to_daily_weather", to_daily)
    return {"latitude": 20.0, "longitude": 74.0,
            "crop": "maize_grain",
            "sowing_date": (date.today() - timedelta(days=55)).isoformat(),
            "acres": 2.0}


async def _value(monkeypatch, field, quotes=None, **kw):
    async def prices(crop, **_):
        if quotes is None:
            raise RuntimeError("price service unreachable")
        return _Report(quotes)

    monkeypatch.setattr(tools, "prices_for_crop", prices)
    return await tools.estimate_crop_value(**field, **kw)


class TestItComposesYieldAndPrice:
    async def test_a_quoted_rate_becomes_rupees_for_the_whole_field(
        self, monkeypatch, field
    ):
        out = await _value(monkeypatch, field,
                           quotes=[_Quote("Nashik", 2000.0)],
                           usual_yield_per_acre=20.0)
        assert out["ok"]
        money = out["money"]
        low_q, high_q = money["quintals"]
        assert money["revenue"][0] == pytest.approx(low_q * 2000, rel=0.01)
        assert money["price_market"] == "Nashik"

    async def test_a_dearer_market_is_reported_with_what_it_is_worth(
        self, monkeypatch, field
    ):
        out = await _value(monkeypatch, field,
                           quotes=[_Quote("Nashik", 2000.0), _Quote("Kalvan", 2300.0)],
                           usual_yield_per_acre=20.0)
        better = out["money"]["better_market"]
        assert better["market"] == "Kalvan"
        assert better["extra_rupees"] > 0

    async def test_costs_the_farmer_gave_become_a_margin(self, monkeypatch, field):
        out = await _value(monkeypatch, field,
                           quotes=[_Quote("Nashik", 2000.0)],
                           usual_yield_per_acre=20.0, cost_per_acre=10000)
        assert "margin" in out["money"]

    async def test_no_costs_means_no_margin_invented(self, monkeypatch, field):
        out = await _value(monkeypatch, field,
                           quotes=[_Quote("Nashik", 2000.0)],
                           usual_yield_per_acre=20.0)
        assert "margin" not in out["money"]


class TestItLeavesGapsRatherThanFillingThem:
    async def test_an_unreachable_price_service_leaves_rupees_blank(
        self, monkeypatch, field
    ):
        """What actually happened the day this was written."""
        out = await _value(monkeypatch, field, quotes=None,
                           usual_yield_per_acre=20.0)
        assert out["ok"]
        assert out["money"]["revenue"] is None
        # The useful half survives.
        assert out["money"]["quintals"][0] > 0
        assert out["money"]["msp"] is not None

    async def test_without_the_farmers_yield_it_asks_instead_of_guessing(
        self, monkeypatch, field
    ):
        out = await _value(monkeypatch, field, quotes=[_Quote("Nashik", 2000.0)])
        assert out["ok"] is False
        assert "usually yields" in out["abstain_reason"]

    async def test_an_uncalibrated_crop_is_refused(self, monkeypatch, field):
        field = {**field, "crop": "dragon_fruit"}
        out = await _value(monkeypatch, field, quotes=None,
                           usual_yield_per_acre=20.0)
        assert out["ok"] is False

    async def test_the_result_never_presents_itself_as_a_forecast(
        self, monkeypatch, field
    ):
        out = await _value(monkeypatch, field,
                           quotes=[_Quote("Nashik", 2000.0)],
                           usual_yield_per_acre=20.0)
        assert out["money"]["is_forecast"] is False
        limits = " ".join(out["evidence"]["limitations"]).lower()
        assert "harvest" in limits
        assert "not a forecast" in out["evidence"]["price_method"].lower()
