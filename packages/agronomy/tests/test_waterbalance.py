"""
Tests for the crop coefficient model, soil texture classification and the
daily root-zone water balance.

Three kinds of check appear here:

1. Agreement with FAO-56 published tables and equations.
2. Conservation of mass -- every millimetre of water entering the root zone
   must leave it as evapotranspiration, drainage, or stored depletion change.
   A balance that does not close is wrong no matter how plausible its output.
3. Agronomic behaviour -- sandy soils need shorter irrigation intervals than
   clay, stress reduces yield, forecast rain defers pumping. These encode the
   decisions a farmer would actually challenge us on.
"""

from datetime import date, timedelta

import pytest

from agronomy.crops import (
    CROPS,
    GrowthStage,
    adjust_kc_for_climate,
    crop_coefficient,
    readily_available_water,
    soil_from_texture,
    total_available_water,
    usda_texture_class,
    water_stress_coefficient,
    yield_loss_from_water_deficit,
)
from agronomy.waterbalance import (
    DailyWeather,
    curve_number_runoff,
    next_irrigation_advice,
    simulate,
)


class TestTextureClassification:
    """USDA textural triangle (Soil Survey Manual, Handbook 18)."""

    @pytest.mark.parametrize(
        "sand,silt,clay,expected",
        [
            (92.0, 5.0, 3.0, "sand"),
            (80.0, 12.0, 8.0, "loamy_sand"),
            (65.0, 25.0, 10.0, "sandy_loam"),
            (40.0, 40.0, 20.0, "loam"),
            (20.0, 60.0, 20.0, "silt_loam"),
            (8.0, 86.0, 6.0, "silt"),
            (20.0, 30.0, 50.0, "clay"),
            (10.0, 45.0, 45.0, "silty_clay"),
            (55.0, 10.0, 35.0, "clay_loam"),
        ],
    )
    def test_known_texture_points(self, sand, silt, clay, expected):
        assert usda_texture_class(sand, silt, clay) == expected

    def test_fractions_are_normalised(self):
        # SoilGrids fractions do not always sum to exactly 100.
        assert usda_texture_class(40.0, 40.0, 19.0) == usda_texture_class(
            40.0, 40.0, 20.0
        )

    def test_zero_total_raises(self):
        with pytest.raises(ValueError):
            usda_texture_class(0.0, 0.0, 0.0)

    def test_clay_holds_more_water_than_sand(self):
        sandy = soil_from_texture(90.0, 7.0, 3.0)
        clayey = soil_from_texture(20.0, 30.0, 50.0)
        assert clayey.available_water_fraction > sandy.available_water_fraction


class TestCropCoefficient:
    """FAO-56 Chapter 6, Figure 25."""

    def test_initial_stage_is_flat_at_kc_ini(self):
        wheat = CROPS["wheat_spring"]
        kc_day5, stage = crop_coefficient(wheat, 5)
        kc_day15, _ = crop_coefficient(wheat, 15)
        assert kc_day5 == pytest.approx(wheat.kc_ini)
        assert kc_day15 == pytest.approx(wheat.kc_ini)
        assert stage == GrowthStage.INITIAL

    def test_mid_season_is_flat_at_kc_mid(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, _ = maize.stage_days
        kc, stage = crop_coefficient(maize, l_ini + l_dev + 10)
        assert kc == pytest.approx(maize.kc_mid)
        assert stage == GrowthStage.MID_SEASON

    def test_development_interpolates_monotonically(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, _, _ = maize.stage_days
        values = [crop_coefficient(maize, l_ini + d)[0] for d in range(1, l_dev + 1)]
        assert all(b >= a for a, b in zip(values, values[1:]))
        assert values[-1] == pytest.approx(maize.kc_mid, abs=1e-9)

    def test_late_season_ends_at_kc_end(self):
        maize = CROPS["maize_grain"]
        kc, stage = crop_coefficient(maize, maize.total_days)
        assert kc == pytest.approx(maize.kc_end, abs=1e-9)
        assert stage == GrowthStage.LATE_SEASON

    def test_climate_adjustment_raises_kc_in_dry_windy_air(self):
        # FAO-56 Eq. 62: arid, windy conditions push Kc_mid above the table value.
        base = 1.20
        arid = adjust_kc_for_climate(base, rh_min=20.0, wind_2m_ms=4.0, plant_height_m=2.0)
        assert arid > base

    def test_climate_adjustment_is_identity_at_reference_conditions(self):
        # Table values are defined at RHmin 45%, u2 2 m/s.
        base = 1.20
        assert adjust_kc_for_climate(
            base, rh_min=45.0, wind_2m_ms=2.0, plant_height_m=2.0
        ) == pytest.approx(base)

    def test_every_crop_has_coherent_parameters(self):
        for key, crop in CROPS.items():
            assert crop.key == key
            assert crop.total_days > 0
            assert all(d > 0 for d in crop.stage_days), key
            assert 0.0 < crop.kc_ini <= 1.5, key
            assert 0.5 <= crop.kc_mid <= 1.5, key
            assert 0.1 <= crop.depletion_fraction <= 0.8, key
            assert 0.1 <= crop.root_depth_m <= 3.0, key


class TestAvailableWater:
    """FAO-56 Eq. 82-84."""

    def test_taw_scales_with_root_depth(self):
        soil = soil_from_texture(40.0, 40.0, 20.0)
        assert total_available_water(soil, 1.0) == pytest.approx(
            2.0 * total_available_water(soil, 0.5)
        )

    def test_taw_matches_hand_calculation(self):
        # loam: FC 0.28, WP 0.14 -> AW 0.14 m3/m3; Zr 1.0 m -> TAW 140 mm
        soil = soil_from_texture(40.0, 40.0, 20.0)
        assert soil.texture_class == "loam"
        assert total_available_water(soil, 1.0) == pytest.approx(140.0, abs=0.5)

    def test_raw_is_a_fraction_of_taw(self):
        raw = readily_available_water(140.0, 0.55, etc_mm_day=5.0)
        assert raw == pytest.approx(0.55 * 140.0)

    def test_high_evaporative_demand_lowers_p(self):
        # FAO-56 Table 22 note: crops stress earlier under high ETc.
        raw_mild = readily_available_water(140.0, 0.55, etc_mm_day=2.0)
        raw_harsh = readily_available_water(140.0, 0.55, etc_mm_day=9.0)
        assert raw_harsh < raw_mild

    def test_p_is_clamped(self):
        assert readily_available_water(100.0, 0.55, etc_mm_day=-50.0) <= 0.8 * 100.0
        assert readily_available_water(100.0, 0.10, etc_mm_day=50.0) >= 0.1 * 100.0

    def test_ks_is_one_above_raw(self):
        assert water_stress_coefficient(30.0, taw=140.0, raw=77.0) == 1.0

    def test_ks_declines_linearly_below_raw(self):
        ks = water_stress_coefficient(depletion_mm=108.5, taw=140.0, raw=77.0)
        assert ks == pytest.approx((140.0 - 108.5) / (140.0 - 77.0))

    def test_ks_is_zero_at_wilting_point(self):
        assert water_stress_coefficient(140.0, taw=140.0, raw=77.0) == 0.0


class TestRunoff:
    """SCS curve number method."""

    def test_small_rain_all_infiltrates(self):
        # Below the initial abstraction threshold nothing runs off.
        assert curve_number_runoff(3.0, curve_number=78.0) == 0.0

    def test_heavy_rain_produces_runoff(self):
        assert curve_number_runoff(120.0, curve_number=78.0) > 0.0

    def test_runoff_never_exceeds_rainfall(self):
        for rain in [1, 5, 20, 50, 100, 250, 500]:
            assert curve_number_runoff(float(rain)) <= rain

    def test_higher_curve_number_yields_more_runoff(self):
        # CN rises with imperviousness and antecedent wetness.
        assert curve_number_runoff(60.0, 90.0) > curve_number_runoff(60.0, 65.0)

    def test_zero_rain_zero_runoff(self):
        assert curve_number_runoff(0.0) == 0.0


def _weather(start: date, n: int, et0: float, rain: float = 0.0) -> list[DailyWeather]:
    return [
        DailyWeather(
            day=start + timedelta(days=i), et0_mm=et0, rain_mm=rain,
            t_max=32.0, t_min=20.0,
        )
        for i in range(n)
    ]


class TestWaterBalanceConservation:
    """Mass balance must close. This is the load-bearing correctness test."""

    def test_balance_closes_rainfed(self):
        crop = CROPS["maize_grain"]
        soil = soil_from_texture(40.0, 40.0, 20.0)
        sow = date(2026, 6, 15)
        weather = _weather(sow, crop.total_days, et0=5.0, rain=4.0)

        r = simulate(crop, soil, sow, weather, initial_depletion_mm=20.0,
                     auto_irrigate=False)

        inflow = sum(d.rain_mm - d.runoff_mm for d in r.days)
        outflow = sum(d.eta_mm + d.deep_percolation_mm for d in r.days)
        storage_change = r.days[-1].depletion_mm - 20.0

        # inflow - outflow = -(change in depletion)
        assert inflow - outflow == pytest.approx(-storage_change, abs=0.5)

    def test_balance_closes_with_irrigation(self):
        crop = CROPS["wheat_spring"]
        soil = soil_from_texture(65.0, 25.0, 10.0)
        sow = date(2026, 11, 10)
        weather = _weather(sow, crop.total_days, et0=4.0, rain=0.5)

        r = simulate(crop, soil, sow, weather, initial_depletion_mm=10.0,
                     auto_irrigate=True)

        net_irrigation = sum(d.irrigation_mm for d in r.days)
        inflow = sum(d.rain_mm - d.runoff_mm for d in r.days) + net_irrigation
        outflow = sum(d.eta_mm + d.deep_percolation_mm for d in r.days)
        storage_change = r.days[-1].depletion_mm - 10.0

        assert inflow - outflow == pytest.approx(-storage_change, abs=0.5)

    def test_depletion_never_negative_or_above_taw(self):
        crop = CROPS["potato"]
        soil = soil_from_texture(40.0, 40.0, 20.0)
        sow = date(2026, 1, 5)
        # Alternating drought and downpour, to stress the clamps.
        weather = [
            DailyWeather(
                day=sow + timedelta(days=i), et0_mm=7.0,
                rain_mm=(120.0 if i % 11 == 0 else 0.0),
                t_max=35.0, t_min=18.0,
            )
            for i in range(crop.total_days)
        ]
        r = simulate(crop, soil, sow, weather, auto_irrigate=False)
        for d in r.days:
            assert 0.0 <= d.depletion_mm <= d.taw_mm + 1e-9
            assert 0.0 <= d.ks <= 1.0
            assert 0.0 <= d.soil_moisture_percent <= 100.0


class TestAgronomicBehaviour:
    """Behaviour a farmer or agronomist would challenge us on."""

    def test_sandy_soil_needs_more_frequent_irrigation(self):
        crop = CROPS["maize_grain"]
        sow = date(2026, 6, 15)
        weather = _weather(sow, crop.total_days, et0=6.0, rain=0.0)

        sandy = simulate(crop, soil_from_texture(90.0, 7.0, 3.0), sow, weather)
        clayey = simulate(crop, soil_from_texture(20.0, 30.0, 50.0), sow, weather)

        assert len(sandy.irrigation_events) > len(clayey.irrigation_events)

    def test_auto_irrigation_prevents_stress(self):
        crop = CROPS["maize_grain"]
        soil = soil_from_texture(40.0, 40.0, 20.0)
        sow = date(2026, 6, 15)
        weather = _weather(sow, crop.total_days, et0=6.0, rain=0.0)

        irrigated = simulate(crop, soil, sow, weather, auto_irrigate=True)
        rainfed = simulate(crop, soil, sow, weather, auto_irrigate=False)

        assert irrigated.stressed_days < rainfed.stressed_days
        assert irrigated.estimated_yield_loss(crop) < rainfed.estimated_yield_loss(crop)

    def test_drought_causes_yield_loss(self):
        crop = CROPS["maize_grain"]
        soil = soil_from_texture(65.0, 25.0, 10.0)
        sow = date(2026, 6, 15)
        weather = _weather(sow, crop.total_days, et0=8.0, rain=0.0)
        r = simulate(crop, soil, sow, weather, auto_irrigate=False)
        assert r.estimated_yield_loss(crop) > 0.2

    def test_ample_rain_needs_no_irrigation(self):
        crop = CROPS["maize_grain"]
        soil = soil_from_texture(40.0, 40.0, 20.0)
        sow = date(2026, 6, 15)
        weather = _weather(sow, crop.total_days, et0=4.0, rain=9.0)
        r = simulate(crop, soil, sow, weather, auto_irrigate=True)
        assert len(r.irrigation_events) == 0
        assert r.estimated_yield_loss(crop) == pytest.approx(0.0, abs=1e-6)

    def test_gross_depth_exceeds_net_depth(self):
        # Application losses mean the farmer pumps more than the crop receives.
        crop = CROPS["cotton"]
        soil = soil_from_texture(65.0, 25.0, 10.0)
        sow = date(2026, 5, 1)
        weather = _weather(sow, crop.total_days, et0=7.0, rain=0.0)
        r = simulate(crop, soil, sow, weather, irrigation_efficiency=0.6)
        assert r.irrigation_events
        for event, day in zip(r.irrigation_events, [d for d in r.days if d.irrigation_mm > 0]):
            assert event.depth_mm > day.irrigation_mm


class TestIrrigationAdvice:
    """The decision surface the assistant actually calls."""

    def _setup(self, forecast_rain: float, history_et0: float = 6.0):
        crop = CROPS["maize_grain"]
        soil = soil_from_texture(40.0, 40.0, 20.0)
        sow = date(2026, 6, 15)
        history = _weather(sow, 45, et0=history_et0, rain=0.0)
        fc_start = sow + timedelta(days=45)
        forecast = _weather(fc_start, 7, et0=5.0, rain=forecast_rain)
        return crop, soil, sow, history, forecast

    def test_dry_forecast_recommends_irrigation(self):
        crop, soil, sow, history, forecast = self._setup(forecast_rain=0.0)
        advice = next_irrigation_advice(crop, soil, sow, history, forecast)
        assert advice["verdict"] in {"irrigate_now", "irrigate_in_days"}
        assert advice["gross_depth_mm"] > advice["net_depth_mm"]

    def test_heavy_forecast_rain_defers_irrigation(self):
        # The expensive mistake: pumping the day before a storm.
        crop, soil, sow, history, forecast = self._setup(forecast_rain=40.0)
        advice = next_irrigation_advice(crop, soil, sow, history, forecast)
        assert advice["verdict"] in {"wait_for_rain", "no_irrigation_needed"}

    def test_advice_reports_its_inputs(self):
        crop, soil, sow, history, forecast = self._setup(forecast_rain=0.0)
        advice = next_irrigation_advice(crop, soil, sow, history, forecast)
        # The Evidence Ledger needs every number behind the verdict.
        for key in [
            "current_depletion_mm", "readily_available_water_mm",
            "total_available_water_mm", "soil_moisture_percent",
            "growth_stage", "kc", "crop", "soil_texture",
        ]:
            assert key in advice, key

    def test_out_of_season_returns_insufficient_data(self):
        crop = CROPS["maize_grain"]
        soil = soil_from_texture(40.0, 40.0, 20.0)
        sow = date(2026, 6, 15)
        stale = _weather(date(2025, 1, 1), 10, et0=5.0)
        advice = next_irrigation_advice(crop, soil, sow, stale, [])
        assert advice["verdict"] == "insufficient_data"


class TestYieldResponse:
    """FAO-56 Eq. 90."""

    def test_no_deficit_no_loss(self):
        assert yield_loss_from_water_deficit(1.25, 400.0, 400.0) == 0.0

    def test_loss_scales_with_ky(self):
        sensitive = yield_loss_from_water_deficit(1.25, 300.0, 400.0)
        tolerant = yield_loss_from_water_deficit(0.85, 300.0, 400.0)
        assert sensitive > tolerant

    def test_loss_is_bounded(self):
        assert yield_loss_from_water_deficit(1.25, 0.0, 400.0) == 1.0
