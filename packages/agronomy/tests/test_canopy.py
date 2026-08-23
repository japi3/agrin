"""
Tests for NDVI to canopy-cover conversion and crop status interpretation.

The behaviours that matter most here are the ones that prevent false alarms.
A satellite monitoring tool that cries wolf at emergence and again at harvest
- twice every season, on every field - gets ignored, and then it is worse
than useless because it is also ignored on the one occasion it is right.
"""

import pytest

from agronomy.canopy import (
    looks_like_annual_cropland,
    representative_ndvi,
    NDVI_BARE_SOIL,
    NDVI_FULL_CANOPY,
    CropStatus,
    assess_canopy,
    calibrate_endpoints,
    detect_emergence,
    expected_fractional_cover,
    fractional_cover_from_ndvi,
    reconcile_sowing_date,
)
from datetime import date, timedelta
from agronomy.crops import CROPS, GrowthStage


class TestFractionalCover:
    """Carlson & Ripley (1997)."""

    def test_bare_soil_is_zero_cover(self):
        assert fractional_cover_from_ndvi(NDVI_BARE_SOIL) == 0.0

    def test_full_canopy_is_full_cover(self):
        assert fractional_cover_from_ndvi(NDVI_FULL_CANOPY) == pytest.approx(1.0)

    def test_below_soil_ndvi_clamps_to_zero(self):
        # Water and cloud shadow give NDVI below the soil endpoint.
        assert fractional_cover_from_ndvi(-0.2) == 0.0
        assert fractional_cover_from_ndvi(0.0) == 0.0

    def test_above_canopy_ndvi_clamps_to_one(self):
        assert fractional_cover_from_ndvi(0.99) == pytest.approx(1.0)

    def test_monotonic(self):
        values = [fractional_cover_from_ndvi(n / 100) for n in range(15, 91, 5)]
        assert all(b >= a for a, b in zip(values, values[1:]))

    def test_squared_form_is_below_linear(self):
        # The square matters: the linear form overestimates cover at
        # intermediate NDVI, which would make a struggling crop look adequate
        # exactly when intervention still helps.
        ndvi = 0.5
        linear = (ndvi - NDVI_BARE_SOIL) / (NDVI_FULL_CANOPY - NDVI_BARE_SOIL)
        assert fractional_cover_from_ndvi(ndvi) < linear

    def test_degenerate_endpoints(self):
        assert fractional_cover_from_ndvi(0.5, ndvi_soil=0.9, ndvi_veg=0.15) == 0.0


class TestExpectedCover:
    def test_near_zero_at_sowing(self):
        maize = CROPS["maize_grain"]
        assert expected_fractional_cover(maize, 0) < 0.05

    def test_rises_through_development(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, _, _ = maize.stage_days
        values = [
            expected_fractional_cover(maize, l_ini + d)
            for d in range(0, l_dev + 1, 5)
        ]
        assert all(b >= a for a, b in zip(values, values[1:]))

    def test_peaks_at_mid_season(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, _ = maize.stage_days
        mid = expected_fractional_cover(maize, l_ini + l_dev + l_mid // 2)
        early = expected_fractional_cover(maize, l_ini // 2)
        assert mid > early
        assert mid == pytest.approx(0.85, abs=0.02)

    def test_declines_through_senescence(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, l_late = maize.stage_days
        start_late = l_ini + l_dev + l_mid
        values = [
            expected_fractional_cover(maize, start_late + d)
            for d in range(0, l_late + 1, 5)
        ]
        assert values[-1] < values[0]

    def test_bounded_for_every_crop_across_the_season(self):
        for key, crop in CROPS.items():
            for das in range(0, crop.total_days + 10, 5):
                fc = expected_fractional_cover(crop, das)
                assert 0.0 <= fc <= 1.0, f"{key} at {das} days -> {fc}"


class TestStatusInterpretation:
    def test_unknown_crop_returns_none(self):
        assert assess_canopy("dragonfruit", 50, 0.6) is None

    def test_early_season_gives_no_verdict(self):
        # The satellite is looking at soil, not crop. A "severely behind"
        # alarm here would fire on every field every season.
        a = assess_canopy("maize_grain", 5, 0.18)
        assert a.status == CropStatus.NOT_EMERGED
        assert "too young" in a.explanation.lower()

    def test_healthy_mid_season_is_on_track(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, _ = maize.stage_days
        das = l_ini + l_dev + l_mid // 2
        # NDVI that maps to roughly the expected 0.85 cover.
        expected = expected_fractional_cover(maize, das)
        ndvi = NDVI_BARE_SOIL + (expected ** 0.5) * (NDVI_FULL_CANOPY - NDVI_BARE_SOIL)
        a = assess_canopy("maize_grain", das, ndvi)
        assert a.status == CropStatus.ON_TRACK

    def test_bare_field_at_mid_season_is_severely_behind(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, _ = maize.stage_days
        das = l_ini + l_dev + l_mid // 2
        a = assess_canopy("maize_grain", das, 0.20)
        assert a.status == CropStatus.SEVERELY_BEHIND

    def test_senescence_is_not_reported_as_failure(self):
        # The second false-alarm trap: every crop loses greenness at harvest.
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, l_late = maize.stage_days
        das = l_ini + l_dev + l_mid + int(l_late * 0.8)
        a = assess_canopy("maize_grain", das, 0.30)
        assert a.status == CropStatus.SENESCING
        assert "normal" in a.explanation.lower()

    def test_vigorous_crop_reads_ahead(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev = maize.stage_days[0], maize.stage_days[1]
        das = l_ini + l_dev // 2
        a = assess_canopy("maize_grain", das, 0.88)
        assert a.status == CropStatus.AHEAD

    def test_status_ordering_across_ndvi(self):
        maize = CROPS["maize_grain"]
        das = maize.stage_days[0] + maize.stage_days[1] + 10
        order = {
            CropStatus.SEVERELY_BEHIND: 0, CropStatus.BEHIND: 1,
            CropStatus.SLIGHTLY_BEHIND: 2, CropStatus.ON_TRACK: 3,
            CropStatus.AHEAD: 4,
        }
        scores = [
            order[assess_canopy("maize_grain", das, n / 100).status]
            for n in range(25, 90, 8)
        ]
        assert scores == sorted(scores)

    def test_patchiness_is_called_out(self):
        maize = CROPS["maize_grain"]
        das = maize.stage_days[0] + maize.stage_days[1] + 10
        patchy = assess_canopy("maize_grain", das, 0.45, uniformity=0.5)
        even = assess_canopy("maize_grain", das, 0.45, uniformity=0.95)
        assert "patchy" in patchy.explanation.lower()
        assert "patchy" not in even.explanation.lower()

    def test_falling_trend_is_flagged_during_expansion(self):
        maize = CROPS["maize_grain"]
        das = maize.stage_days[0] + maize.stage_days[1] // 2
        a = assess_canopy("maize_grain", das, 0.45, trend_per_day=-0.006)
        assert "falling" in a.explanation.lower()

    def test_falling_trend_not_flagged_when_senescing(self):
        maize = CROPS["maize_grain"]
        l_ini, l_dev, l_mid, l_late = maize.stage_days
        das = l_ini + l_dev + l_mid + int(l_late * 0.7)
        a = assess_canopy("maize_grain", das, 0.30, trend_per_day=-0.01)
        assert a.status == CropStatus.SENESCING

    def test_serialisation_is_complete(self):
        a = assess_canopy("rice_paddy", 60, 0.62, uniformity=0.8, trend_per_day=0.001)
        d = a.to_dict()
        for key in ("ndvi", "canopy_cover_percent", "expected_cover_percent",
                    "status", "growth_stage", "explanation"):
            assert key in d

    def test_gap_signs(self):
        maize = CROPS["maize_grain"]
        das = maize.stage_days[0] + maize.stage_days[1] + 10
        poor = assess_canopy("maize_grain", das, 0.30)
        good = assess_canopy("maize_grain", das, 0.85)
        assert poor.cover_gap < 0 and poor.relative_gap < 0
        assert good.cover_gap > 0


class TestLocalCalibration:
    """Gutman & Ignatov (1998) local scaling.

    Global NDVI endpoints assume every field's bare soil and full canopy look
    alike. They do not, and using constants made a healthy Punjab paddy field
    read as 50 percent cover at its seasonal peak -- a false failure alarm.
    """

    def test_too_little_history_falls_back_to_defaults(self):
        assert calibrate_endpoints([0.3, 0.5, 0.7]) == (NDVI_BARE_SOIL, NDVI_FULL_CANOPY)

    def test_calibrates_from_a_full_seasonal_range(self):
        history = [0.12, 0.14, 0.15, 0.25, 0.40, 0.55, 0.70, 0.80, 0.84, 0.78,
                   0.60, 0.35, 0.18, 0.13]
        soil, veg = calibrate_endpoints(history)
        assert soil < 0.2
        assert veg > 0.75
        assert (soil, veg) != (NDVI_BARE_SOIL, NDVI_FULL_CANOPY)

    def test_narrow_range_falls_back(self):
        # A field only ever observed mid-season never shows bare soil, so the
        # endpoints are too close together to scale against.
        history = [0.55, 0.56, 0.58, 0.60, 0.59, 0.61, 0.57, 0.62, 0.60, 0.58]
        assert calibrate_endpoints(history) == (NDVI_BARE_SOIL, NDVI_FULL_CANOPY)

    def test_percentiles_resist_outliers(self):
        # Residual cloud edge survives masking as an extreme value; anchoring
        # the scale to min/max would be worse than using constants.
        clean = [0.12, 0.15, 0.30, 0.45, 0.60, 0.72, 0.80, 0.83, 0.70, 0.40,
                 0.20, 0.14]
        with_outliers = clean + [-0.6, 0.99]
        a = calibrate_endpoints(clean)
        b = calibrate_endpoints(with_outliers)
        assert abs(a[0] - b[0]) < 0.12
        assert abs(a[1] - b[1]) < 0.12

    def test_endpoints_are_clamped_to_plausible_values(self):
        soil, veg = calibrate_endpoints([0.0] * 8 + [0.99] * 8)
        assert 0.0 <= soil <= 0.35
        assert 0.5 <= veg <= 0.95

    def test_calibration_raises_cover_for_a_real_field(self):
        # The Moga case: seasonal peak 0.80, bare soil around 0.13.
        history = [0.13, 0.14, 0.16, 0.28, 0.44, 0.62, 0.75, 0.80, 0.79, 0.66,
                   0.42, 0.22, 0.15, 0.13]
        soil, veg = calibrate_endpoints(history)
        global_cover = fractional_cover_from_ndvi(0.80)
        local_cover = fractional_cover_from_ndvi(0.80, soil, veg)
        assert local_cover > global_cover
        # At its own seasonal peak the field should read as near-full canopy.
        assert local_cover > 0.9

    def test_ignores_invalid_values(self):
        history = [0.12, None, 0.15, 5.0, 0.40, 0.60, 0.75, 0.82, 0.70, 0.30,
                   0.18, 0.13]
        soil, veg = calibrate_endpoints([v for v in history if v is not None])
        assert 0.0 <= soil <= 0.35 and 0.5 <= veg <= 0.95


class TestEmergenceDetection:
    """Sowing dates come from recall; the satellite record is independent."""

    def _series(self, greenup_index: int, n: int = 12):
        start = date(2026, 6, 1)
        out = []
        for i in range(n):
            ndvi = 0.15 if i < greenup_index else min(0.85, 0.20 + 0.09 * (i - greenup_index + 1))
            out.append((start + timedelta(days=i * 5), ndvi))
        return out

    def test_detects_greenup(self):
        obs = self._series(greenup_index=4)
        emergence = detect_emergence(obs)
        assert emergence is not None
        assert date(2026, 6, 18) <= emergence <= date(2026, 7, 2)

    def test_returns_none_for_bare_field(self):
        obs = [(date(2026, 6, 1) + timedelta(days=i * 5), 0.14) for i in range(12)]
        assert detect_emergence(obs) is None

    def test_returns_none_for_too_few_observations(self):
        assert detect_emergence([(date(2026, 6, 1), 0.5)]) is None

    def test_single_bright_observation_is_not_emergence(self):
        # An imperfectly masked cloud edge produces one high value. Requiring
        # the rise to persist prevents dating a crop from a bad pixel.
        obs = [(date(2026, 6, 1) + timedelta(days=i * 5), 0.15) for i in range(10)]
        obs[3] = (obs[3][0], 0.75)
        assert detect_emergence(obs) is None

    def test_agreeing_dates_are_confirmed(self):
        obs = self._series(greenup_index=4)
        emergence = detect_emergence(obs)
        stated = emergence - timedelta(days=18)
        r = reconcile_sowing_date(stated, obs)
        assert r["source"] == "farmer_confirmed_by_satellite"
        assert r["note"] is None

    def test_large_disagreement_prefers_satellite_and_explains(self):
        obs = self._series(greenup_index=6)
        stated = date(2026, 4, 1)   # far too early
        r = reconcile_sowing_date(stated, obs)
        assert r["source"] == "satellite"
        assert r["sowing_date"] != stated
        assert "resown" in r["note"].lower()
        assert abs(r["disagreement_days"]) > 14

    def test_no_satellite_evidence_keeps_farmer_date(self):
        stated = date(2026, 6, 15)
        bare = [(date(2026, 6, 1) + timedelta(days=i * 5), 0.13) for i in range(12)]
        r = reconcile_sowing_date(stated, bare)
        assert r["sowing_date"] == stated
        assert r["source"] == "farmer"


class TestCroplandGating:
    """Stage verdicts assume the greenness belongs to the named crop."""

    def test_annual_cropping_is_recognised(self):
        # Bare between seasons, full canopy in season: the classic signature.
        history = [0.13, 0.15, 0.30, 0.55, 0.75, 0.80, 0.60, 0.25, 0.14,
                   0.18, 0.45, 0.72]
        assert looks_like_annual_cropland(history) is True

    def test_permanent_vegetation_is_rejected(self):
        # An orchard or roadside tree cover never goes bare.
        history = [0.62, 0.65, 0.68, 0.70, 0.66, 0.64, 0.67, 0.69, 0.71,
                   0.66, 0.63, 0.65]
        assert looks_like_annual_cropland(history) is False

    def test_sparse_history_does_not_doubt_the_farmer(self):
        assert looks_like_annual_cropland([0.5, 0.6, 0.55]) is True

    def test_peri_urban_case(self):
        # The real failure this guards: a point with permanent greenery read
        # as "ahead of expected" for a crop that was never planted there.
        history = [0.18, 0.25, 0.32, 0.35, 0.30, 0.28, 0.33, 0.40, 0.45,
                   0.38, 0.30, 0.26]
        assert looks_like_annual_cropland(history) is False


class TestRepresentativeNDVI:
    """Atmospheric contamination almost always lowers NDVI, never raises it."""

    def test_takes_recent_maximum(self):
        obs = [
            (date(2026, 8, 1), 0.70),
            (date(2026, 8, 6), 0.72),
            (date(2026, 8, 11), 0.40),   # hazy scene
        ]
        assert representative_ndvi(obs) == 0.72

    def test_ignores_observations_outside_the_window(self):
        obs = [
            (date(2026, 5, 1), 0.90),    # last season, far outside 30 days
            (date(2026, 8, 6), 0.55),
            (date(2026, 8, 11), 0.58),
        ]
        assert representative_ndvi(obs, within_days=30) == 0.58

    def test_empty_returns_none(self):
        assert representative_ndvi([]) is None

    def test_single_observation(self):
        assert representative_ndvi([(date(2026, 8, 1), 0.44)]) == 0.44

    def test_one_bad_scene_does_not_condemn_a_season(self):
        # The concrete failure: a healthy crop judged on one hazy pass.
        healthy = [(date(2026, 8, 1), 0.78), (date(2026, 8, 6), 0.80),
                   (date(2026, 8, 11), 0.35)]
        assert representative_ndvi(healthy) == 0.80
