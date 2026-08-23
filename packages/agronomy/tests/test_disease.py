"""
Tests for the weather-driven disease infection models.

The load-bearing claim these tests defend is that the model can say *no*.
A disease-risk model that reports elevated risk under every weather pattern
is worse than useless in this platform, because its output is fed to a vision
model as a prior -- an always-on risk signal would push the diagnosis toward
whatever disease was listed first, on every photograph.

So most of what follows checks that hot dry weather suppresses wet-loving
pathogens, cold weather suppresses warm-loving ones, and the seasonal
patterns of the Indian plains produce the diseases those seasons actually
produce.
"""

from datetime import date, timedelta

import pytest

from agronomy.disease import (
    DISEASES,
    RiskLevel,
    assess_all_for_crop,
    assess_disease_risk,
    leaf_wetness_hours_from_rh,
    required_wetness_hours,
    smith_period,
    temperature_response,
)


class TestTemperatureResponse:
    """Analytis (1977) beta function."""

    def test_peaks_at_optimum(self):
        r = temperature_response(18.0, t_min=4.0, t_opt=18.0, t_max=26.0)
        assert r == pytest.approx(1.0, abs=1e-6)

    def test_zero_at_and_beyond_cardinals(self):
        assert temperature_response(4.0, 4.0, 18.0, 26.0) == 0.0
        assert temperature_response(26.0, 4.0, 18.0, 26.0) == 0.0
        assert temperature_response(-5.0, 4.0, 18.0, 26.0) == 0.0
        assert temperature_response(40.0, 4.0, 18.0, 26.0) == 0.0

    def test_bounded_zero_to_one(self):
        for t in range(-10, 45):
            assert 0.0 <= temperature_response(float(t), 4.0, 18.0, 26.0) <= 1.0

    def test_rises_then_falls(self):
        below = temperature_response(10.0, 4.0, 18.0, 26.0)
        at = temperature_response(18.0, 4.0, 18.0, 26.0)
        above = temperature_response(23.0, 4.0, 18.0, 26.0)
        assert below < at and above < at

    def test_asymmetric_shape(self):
        # The curve is not symmetric about the optimum; fungal response falls
        # off faster above Topt than below it. A symmetric approximation
        # would overstate risk in hot weather.
        span = 6.0
        cooler = temperature_response(18.0 - span, 4.0, 18.0, 26.0)
        warmer = temperature_response(18.0 + span, 4.0, 18.0, 26.0)
        assert cooler != pytest.approx(warmer, abs=0.05)

    def test_degenerate_cardinals_do_not_raise(self):
        assert temperature_response(15.0, 10.0, 10.0, 20.0) == 0.0


class TestWetnessRequirement:
    def test_optimum_needs_base_hours(self):
        p = DISEASES["late_blight"]
        assert required_wetness_hours(p.t_opt, p) == pytest.approx(
            p.min_wetness_hours, abs=1e-6
        )

    def test_away_from_optimum_needs_longer(self):
        p = DISEASES["late_blight"]
        assert required_wetness_hours(10.0, p) > p.min_wetness_hours

    def test_impossible_outside_range(self):
        p = DISEASES["late_blight"]
        assert required_wetness_hours(35.0, p) is None
        assert required_wetness_hours(0.0, p) is None


class TestLeafWetness:
    def test_counts_hours_above_threshold(self):
        rh = [95.0] * 8 + [70.0] * 16
        assert leaf_wetness_hours_from_rh(rh, 90.0) == 8.0

    def test_handles_missing_values(self):
        rh = [95.0, None, 92.0, 60.0]
        assert leaf_wetness_hours_from_rh(rh, 90.0) == 2.0

    def test_threshold_is_inclusive(self):
        assert leaf_wetness_hours_from_rh([90.0], 90.0) == 1.0


class TestSmithPeriod:
    """Smith (1956): two consecutive qualifying days."""

    def test_two_consecutive_qualifying_days(self):
        assert smith_period([(12.0, 14.0), (11.0, 12.0)]) is True

    def test_single_qualifying_day_is_not_enough(self):
        assert smith_period([(12.0, 14.0), (11.0, 4.0)]) is False

    def test_non_consecutive_days_do_not_qualify(self):
        assert smith_period([(12.0, 14.0), (11.0, 2.0), (12.0, 13.0)]) is False

    def test_cold_nights_block_it(self):
        # Minimum temperature below 10 C fails regardless of humidity.
        assert smith_period([(8.0, 20.0), (7.0, 20.0)]) is False

    def test_empty_input(self):
        assert smith_period([]) is False


def _days(n: int, t_min: float, t_max: float, rh_wet_hours: int):
    """Build a synthetic weather window with a given daily wetness duration."""
    start = date(2026, 1, 1)
    out = []
    for i in range(n):
        hourly = [95.0] * rh_wet_hours + [60.0] * (24 - rh_wet_hours)
        out.append({
            "date": start + timedelta(days=i),
            "t_min": t_min, "t_max": t_max, "t_mean": (t_min + t_max) / 2,
            "hourly_rh": hourly,
        })
    return out


class TestRiskDiscrimination:
    """The model must be able to say no. These are the tests that matter."""

    def test_hot_dry_weather_gives_no_late_blight_risk(self):
        # 38 C and dry: Phytophthora infestans cannot establish. If this
        # returns anything but NONE, the vision model gets a false prior.
        risk = assess_disease_risk(DISEASES["late_blight"], _days(14, 24.0, 38.0, 0))
        assert risk.level == RiskLevel.NONE
        assert risk.favourable_days == 0
        assert any("hot" in d.lower() or "dry" in d.lower() for d in risk.drivers)

    def test_cool_wet_weather_gives_high_late_blight_risk(self):
        risk = assess_disease_risk(DISEASES["late_blight"], _days(14, 11.0, 20.0, 16))
        assert risk.level in (RiskLevel.HIGH, RiskLevel.SEVERE)
        assert risk.smith_periods > 0

    def test_yellow_rust_needs_cool_weather(self):
        cool = assess_disease_risk(DISEASES["yellow_rust"], _days(14, 6.0, 16.0, 10))
        hot = assess_disease_risk(DISEASES["yellow_rust"], _days(14, 26.0, 38.0, 10))
        assert cool.level in (RiskLevel.HIGH, RiskLevel.SEVERE)
        assert hot.level == RiskLevel.NONE

    def test_sheath_blight_needs_warm_weather(self):
        warm = assess_disease_risk(DISEASES["sheath_blight"], _days(14, 26.0, 34.0, 14))
        cold = assess_disease_risk(DISEASES["sheath_blight"], _days(14, 4.0, 12.0, 14))
        assert warm.level in (RiskLevel.HIGH, RiskLevel.SEVERE)
        assert cold.level == RiskLevel.NONE

    def test_powdery_mildew_does_not_require_free_water(self):
        # Distinctive epidemiology: humid air, dry leaves. A model that
        # applied a wetness criterion here would miss it entirely.
        p = DISEASES["powdery_mildew"]
        assert p.min_wetness_hours == 0.0
        humid_no_rain = [{
            "date": date(2026, 2, 1) + timedelta(days=i),
            "t_min": 14.0, "t_max": 26.0, "t_mean": 20.0,
            "hourly_rh": [78.0] * 14 + [55.0] * 10,   # never reaches 90
        } for i in range(14)]
        risk = assess_disease_risk(p, humid_no_rain)
        assert risk.level in (RiskLevel.HIGH, RiskLevel.SEVERE)

    def test_dry_air_suppresses_powdery_mildew(self):
        arid = [{
            "date": date(2026, 2, 1) + timedelta(days=i),
            "t_min": 14.0, "t_max": 26.0, "t_mean": 20.0,
            "hourly_rh": [25.0] * 24,
        } for i in range(14)]
        assert assess_disease_risk(DISEASES["powdery_mildew"], arid).level == RiskLevel.NONE

    def test_intermediate_weather_gives_intermediate_risk(self):
        # A few favourable days in a fortnight should not read as severe.
        mixed = _days(4, 12.0, 20.0, 16) + _days(10, 24.0, 36.0, 0)
        risk = assess_disease_risk(DISEASES["late_blight"], mixed)
        assert risk.level in (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH)
        assert risk.level != RiskLevel.NONE


class TestSeasonalRealism:
    """Indian cropping seasons must produce the diseases they actually produce."""

    def test_rabi_wheat_in_north_india_favours_yellow_rust_over_brown(self):
        # Punjab in January: cold nights, mild days, morning fog. Yellow rust
        # is the operational threat; brown rust arrives later as it warms.
        january = _days(14, 6.0, 18.0, 12)
        risks = {r.disease.key: r for r in assess_all_for_crop("wheat_spring", january)}
        yellow = risks["yellow_rust"]
        brown = risks["brown_rust"]
        assert yellow.favourable_days > brown.favourable_days

    def test_march_warmth_shifts_wheat_risk_to_brown_rust(self):
        march = _days(14, 18.0, 30.0, 10)
        risks = {r.disease.key: r for r in assess_all_for_crop("wheat_spring", march)}
        assert risks["brown_rust"].favourable_days > risks["yellow_rust"].favourable_days

    def test_kharif_monsoon_favours_rice_diseases(self):
        # August in the paddy belt: warm, saturated, long leaf wetness.
        monsoon = _days(14, 25.0, 33.0, 18)
        risks = assess_all_for_crop("rice_paddy", monsoon)
        assert risks[0].level in (RiskLevel.HIGH, RiskLevel.SEVERE)
        top = {r.disease.key for r in risks if r.level in
               (RiskLevel.HIGH, RiskLevel.SEVERE)}
        assert {"sheath_blight", "bacterial_leaf_blight"} & top

    def test_hot_dry_spell_favours_cotton_leaf_curl(self):
        # Whitefly-borne: risk tracks vector activity, which peaks hot and dry.
        hot_dry = [{
            "date": date(2026, 5, 1) + timedelta(days=i),
            "t_min": 27.0, "t_max": 42.0, "t_mean": 34.0,
            "hourly_rh": [45.0] * 24,
        } for i in range(14)]
        risk = assess_disease_risk(DISEASES["cotton_leaf_curl"], hot_dry)
        assert risk.level in (RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.SEVERE)

    def test_ranking_is_ordered_by_severity(self):
        risks = assess_all_for_crop("rice_paddy", _days(14, 25.0, 33.0, 18))
        levels = [r.level for r in risks]
        order = {RiskLevel.SEVERE: 4, RiskLevel.HIGH: 3, RiskLevel.MODERATE: 2,
                 RiskLevel.LOW: 1, RiskLevel.NONE: 0}
        scores = [order[l] for l in levels]
        assert scores == sorted(scores, reverse=True)


class TestRobustness:
    def test_empty_window_is_none_risk(self):
        risk = assess_disease_risk(DISEASES["late_blight"], [])
        assert risk.level == RiskLevel.NONE
        assert risk.total_days == 0

    def test_missing_temperature_days_are_skipped(self):
        days = [{"date": date(2026, 1, 1), "hourly_rh": [95.0] * 20}]
        risk = assess_disease_risk(DISEASES["late_blight"], days)
        assert risk.total_days == 0

    def test_daily_rh_fallback_without_hourly(self):
        days = [{
            "date": date(2026, 1, 1) + timedelta(days=i),
            "t_min": 11.0, "t_max": 20.0, "t_mean": 15.5, "rh_max": 96.0,
        } for i in range(10)]
        risk = assess_disease_risk(DISEASES["late_blight"], days)
        assert risk.total_days == 10
        assert risk.favourable_days > 0

    def test_unknown_crop_returns_empty(self):
        assert assess_all_for_crop("dragonfruit", _days(10, 20.0, 30.0, 12)) == []

    def test_every_disease_has_field_signs(self):
        # These strings are read aloud to a farmer so they can check the
        # diagnosis themselves. A missing one is a silent product failure.
        for key, p in DISEASES.items():
            assert p.field_signs.strip(), key
            assert len(p.field_signs) > 40, key
            assert p.crops, key
            assert p.t_min < p.t_opt < p.t_max, key

    def test_serialisation_is_complete(self):
        risk = assess_disease_risk(DISEASES["rice_blast"], _days(10, 22.0, 30.0, 14))
        d = risk.to_dict()
        for key in ("disease", "name", "risk_level", "favourable_days",
                    "days_assessed", "drivers", "field_signs"):
            assert key in d
