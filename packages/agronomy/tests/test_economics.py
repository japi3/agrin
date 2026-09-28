"""
Tests for what the standing crop is worth.

The arithmetic here is simple. What these tests mostly pin down is the
restraint: that a range is never collapsed to a point, that a floor price is
never invented for a crop that has none, and that nothing in the output can
be read as a prediction of what prices will do.

A farmer deciding when to sell on a number this app made up could lose a
season's income. Everything else in this platform traces to a published
model or a live measurement, and this must too.
"""

import pytest

from agronomy.economics import (
    YIELD_BAND,
    _msp_table,
    estimate_yield,
    msp_for,
    msp_is_verified,
    value_at_todays_price,
)


class TestYieldFollowsTheWaterBalance:
    def test_no_water_stress_leaves_the_attainable_yield(self):
        e = estimate_yield(attainable=20.0, relative_loss=0.0, basis="theirs")
        assert e.midpoint == pytest.approx(20.0)

    def test_stress_reduces_it_by_the_fao_fraction(self):
        """FAO-33: a 12% relative loss is 12% off the attainable yield."""
        e = estimate_yield(attainable=24.0, relative_loss=0.12, basis="theirs")
        assert e.midpoint == pytest.approx(24.0 * 0.88)

    def test_a_total_loss_is_no_crop_rather_than_a_negative_one(self):
        e = estimate_yield(attainable=20.0, relative_loss=1.0, basis="theirs")
        assert e.low == 0.0 and e.high == 0.0

    def test_a_loss_beyond_total_is_clamped(self):
        """The model can overshoot; a farmer cannot harvest less than nothing."""
        e = estimate_yield(attainable=20.0, relative_loss=1.4, basis="theirs")
        assert e.low == 0.0

    def test_the_answer_is_always_a_range(self):
        """A single number would imply precision the model does not have."""
        e = estimate_yield(attainable=20.0, relative_loss=0.1, basis="theirs")
        assert e.low < e.high
        assert e.as_dict()["low"] != e.as_dict()["high"]
        spread = (e.high - e.low) / e.midpoint
        assert spread == pytest.approx(2 * YIELD_BAND, rel=0.01)

    def test_an_impossible_baseline_is_refused(self):
        with pytest.raises(ValueError):
            estimate_yield(attainable=0.0, relative_loss=0.1, basis="theirs")

    def test_where_the_baseline_came_from_is_carried_through(self):
        """A farmer's own figure and a district average are not the same
        claim, and the answer has to say which it used."""
        e = estimate_yield(20.0, 0.1, basis="the farmer's own figure")
        assert "farmer" in e.as_dict()["basis"]


class TestMoneyIsTodaysPriceOnly:
    def _estimate(self):
        return estimate_yield(attainable=20.0, relative_loss=0.1, basis="theirs")

    def test_revenue_scales_with_area(self):
        one = value_at_todays_price(self._estimate(), 1.0, price_today=2000)
        two = value_at_todays_price(self._estimate(), 2.0, price_today=2000)
        assert two.revenue_low == pytest.approx(one.revenue_low * 2)

    def test_no_price_means_no_revenue_rather_than_a_guess(self):
        """Out of season, or a crop nobody trades, leaves the rupees blank."""
        m = value_at_todays_price(self._estimate(), 2.0, price_today=None)
        assert m.revenue_low is None
        assert m.as_dict()["revenue"] is None
        # The quintals are still useful on their own.
        assert m.as_dict()["quintals"][0] > 0

    def test_output_never_claims_to_be_a_forecast(self):
        """The property this whole module exists to preserve."""
        m = value_at_todays_price(self._estimate(), 2.0, price_today=2000)
        assert m.as_dict()["is_forecast"] is False

    def test_a_better_market_is_stated_in_rupees_for_this_much_crop(self):
        """Per-quintal differences are easy to dismiss; the total is not."""
        m = value_at_todays_price(
            self._estimate(), 2.0, price_today=2000,
            best_market="Kalvan", best_market_price=2200,
        )
        better = m.as_dict()["better_market"]
        assert better["market"] == "Kalvan"
        assert better["extra_rupees"] > 0

    def test_a_worse_market_is_not_advertised_as_better(self):
        m = value_at_todays_price(
            self._estimate(), 2.0, price_today=2000,
            best_market="Somewhere", best_market_price=1800,
        )
        assert "better_market" not in m.as_dict()

    def test_margin_appears_only_when_the_farmer_supplies_costs(self):
        """Inventing a cost of cultivation would make the margin fiction."""
        without = value_at_todays_price(self._estimate(), 2.0, price_today=2000)
        assert "margin" not in without.as_dict()

        with_cost = value_at_todays_price(
            self._estimate(), 2.0, price_today=2000, cost_per_acre=15000,
        )
        assert with_cost.as_dict()["margin"][0] == pytest.approx(
            with_cost.revenue_low - 30000, abs=1
        )

    def test_a_loss_is_reported_as_a_loss(self):
        """Costs above revenue must show a negative margin, not be hidden."""
        m = value_at_todays_price(
            self._estimate(), 1.0, price_today=500, cost_per_acre=40000,
        )
        assert m.as_dict()["margin"][0] < 0


class TestTheSupportPriceIsAFloorNotAForecast:
    def test_an_msp_crop_has_one(self):
        price, year = msp_for("wheat_rabi")
        assert price and price > 0 and year

    def test_a_crop_outside_the_list_says_nothing(self):
        """Most of what a smallholder grows has no MSP. Silence is correct."""
        assert msp_for("onion") == (None, None)
        assert msp_for("dragon_fruit") == (None, None)

    def test_whether_todays_price_beats_the_floor_is_stated(self):
        e = estimate_yield(20.0, 0.0, basis="theirs")
        above = value_at_todays_price(e, 1.0, price_today=2500, msp=2400)
        below = value_at_todays_price(e, 1.0, price_today=2300, msp=2400)
        assert above.as_dict()["above_msp"] is True
        assert below.as_dict()["above_msp"] is False

    def test_no_comparison_is_made_without_both_numbers(self):
        e = estimate_yield(20.0, 0.0, basis="theirs")
        m = value_at_todays_price(e, 1.0, price_today=None, msp=2400)
        assert m.as_dict()["above_msp"] is None

    def test_the_table_records_that_it_was_checked_and_against_what(self):
        """These figures were once a full season out of date -- the 2025-26
        column sitting under a 2025-26 label while 2026-27 was in force, every
        one of the fourteen wrong. The file now carries the date it was
        checked and the Cabinet releases it was checked against, so the next
        person can tell at a glance whether it has gone stale again."""
        assert msp_is_verified() is True
        table = _msp_table()
        assert table["verified_on"]
        assert any("PIB Release" in cite for cite in table["verified_from"])

    def test_every_season_says_which_marketing_year_it_is(self):
        """A floor price without its year is unusable: the farmer cannot tell
        whether it is this season's number or last season's."""
        for season in _msp_table()["seasons"].values():
            assert season["marketing_year"]

    def test_the_announced_figures_are_pinned(self):
        """Pinned deliberately. These are rupee floors a farmer may hold out
        for, and changing one should take an edit to this test as well as to
        the table -- not a quiet keystroke.

        Kharif MS 2026-27 (PIB 2260617); Rabi RMS 2026-27 (PIB 2173567).
        """
        assert msp_for("rice_paddy")[0] == 2441
        assert msp_for("cotton")[0] == 8267
        assert msp_for("wheat_rabi")[0] == 2585
        assert msp_for("mustard")[0] == 6200

    def test_the_lower_grade_is_carried_where_two_are_announced(self):
        """Paddy common over Grade A, cotton medium staple over long. The
        crop keys here do not distinguish the grades, and quoting a floor too
        high is the harmful direction: a farmer holding out for a price
        nobody will pay loses the season."""
        assert msp_for("rice_paddy")[0] < 2461      # Grade A
        assert msp_for("cotton")[0] < 8667          # long staple
        assert msp_for("sorghum")[0] < 4073         # maldandi
