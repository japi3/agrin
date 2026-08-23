"""
Verification of the FAO-56 implementation against the worked examples
published in FAO Irrigation and Drainage Paper 56 (Allen et al., 1998).

Each test names the example it reproduces and the page/box it appears in.
These are not regression tests written against our own output -- the expected
values come from the FAO document itself, so passing means the implementation
agrees with the international reference standard rather than merely with
yesterday's build.

Tolerances match the precision to which FAO-56 prints each figure.
"""

import math
import pytest

from agronomy.fao56 import (
    atmospheric_pressure,
    psychrometric_constant,
    saturation_vapour_pressure,
    mean_saturation_vapour_pressure,
    slope_vapour_pressure_curve,
    actual_vapour_pressure_from_rh,
    extraterrestrial_radiation,
    daylight_hours,
    solar_radiation_from_sunshine,
    clear_sky_radiation,
    net_shortwave_radiation,
    net_longwave_radiation,
    wind_speed_at_2m,
    penman_monteith_et0,
    et0_from_daily_weather,
    hargreaves_et0,
)


class TestAtmosphericParameters:
    """FAO-56 Example 2: atmospheric pressure and psychrometric constant."""

    def test_pressure_at_1800m(self):
        # FAO-56 Example 2: elevation 1800 m -> P = 81.8 kPa
        assert atmospheric_pressure(1800.0) == pytest.approx(81.8, abs=0.05)

    def test_psychrometric_constant_at_1800m(self):
        # FAO-56 Example 2: P = 81.8 kPa -> gamma = 0.054 kPa/C
        p = atmospheric_pressure(1800.0)
        assert psychrometric_constant(p) == pytest.approx(0.054, abs=0.0005)

    def test_pressure_at_sea_level(self):
        # Definitional: standard atmosphere at z = 0
        assert atmospheric_pressure(0.0) == pytest.approx(101.3, abs=0.01)


class TestVapourPressure:
    """FAO-56 Example 3 and 5: saturation and actual vapour pressure."""

    def test_saturation_vapour_pressure_table_values(self):
        # FAO-56 Annex 2, Table 2.3 (saturation vapour pressure at given T)
        assert saturation_vapour_pressure(24.5) == pytest.approx(3.075, abs=0.005)
        assert saturation_vapour_pressure(15.0) == pytest.approx(1.705, abs=0.005)

    def test_mean_saturation_vapour_pressure(self):
        # FAO-56 Example 3: Tmax 24.5 C, Tmin 15 C -> es = 2.39 kPa
        assert mean_saturation_vapour_pressure(24.5, 15.0) == pytest.approx(
            2.39, abs=0.005
        )

    def test_mean_es_exceeds_es_at_tmean(self):
        # FAO-56 Ch.3 warns that using e_0(Tmean) underestimates es because
        # the curve is convex. Guards against a tempting "simplification".
        es_correct = mean_saturation_vapour_pressure(24.5, 15.0)
        es_wrong = saturation_vapour_pressure((24.5 + 15.0) / 2.0)
        assert es_correct > es_wrong

    def test_actual_vapour_pressure_from_rh(self):
        # FAO-56 Example 5: Tmin 18 C, Tmax 25 C, RHmax 82%, RHmin 54%
        # -> ea = 1.70 kPa
        ea = actual_vapour_pressure_from_rh(
            t_max=25.0, t_min=18.0, rh_max=82.0, rh_min=54.0
        )
        assert ea == pytest.approx(1.70, abs=0.01)


class TestSlopeOfVapourPressureCurve:
    """FAO-56 Annex 2, Table 2.4."""

    def test_slope_at_30c(self):
        assert slope_vapour_pressure_curve(30.0) == pytest.approx(0.243, abs=0.002)

    def test_slope_at_20c(self):
        assert slope_vapour_pressure_curve(20.0) == pytest.approx(0.145, abs=0.002)


class TestRadiation:
    """FAO-56 Examples 8-11: the radiation chain."""

    # 3 September is day of year 246 in a non-leap year.
    DOY_3_SEPT = 246
    LAT_20_SOUTH = -20.0

    def test_extraterrestrial_radiation(self):
        # FAO-56 Example 8: 3 September at 20 S -> Ra = 32.2 MJ/m2/day
        ra = extraterrestrial_radiation(self.LAT_20_SOUTH, self.DOY_3_SEPT)
        assert ra == pytest.approx(32.2, abs=0.15)

    def test_daylight_hours(self):
        # FAO-56 Example 9: 3 September at 20 S -> N = 11.7 h
        n = daylight_hours(self.LAT_20_SOUTH, self.DOY_3_SEPT)
        assert n == pytest.approx(11.7, abs=0.05)

    def test_solar_radiation_from_sunshine(self):
        # Angstrom relation, FAO-56 Eq. 35, evaluated on top of the two
        # FAO-published quantities verified above (Ra = 32.2, N = 11.7).
        # The expectation is derived here rather than transcribed, so the
        # reader can see it follows from values FAO itself prints:
        #   Rs = (0.25 + 0.50 * n/N) * Ra
        #      = (0.25 + 0.50 * 7.1/11.7) * 32.2 = 17.8 MJ/m2/day
        rs = solar_radiation_from_sunshine(7.1, self.LAT_20_SOUTH, self.DOY_3_SEPT)
        expected = (0.25 + 0.50 * (7.1 / 11.7)) * 32.2
        assert rs == pytest.approx(expected, rel=0.01)
        assert rs == pytest.approx(17.8, abs=0.2)

    def test_angstrom_bounds(self):
        # Fully overcast (n=0) and cloudless (n=N) bracket Rs at 25% and 75%
        # of Ra under the default FAO coefficients.
        ra = extraterrestrial_radiation(self.LAT_20_SOUTH, self.DOY_3_SEPT)
        n_max = daylight_hours(self.LAT_20_SOUTH, self.DOY_3_SEPT)
        overcast = solar_radiation_from_sunshine(0.0, self.LAT_20_SOUTH, self.DOY_3_SEPT)
        clear = solar_radiation_from_sunshine(n_max, self.LAT_20_SOUTH, self.DOY_3_SEPT)
        assert overcast == pytest.approx(0.25 * ra, rel=1e-6)
        assert clear == pytest.approx(0.75 * ra, rel=1e-6)

    def test_equator_has_near_12h_daylight_at_equinox(self):
        # Physical sanity check independent of FAO tables.
        assert daylight_hours(0.0, 80) == pytest.approx(12.0, abs=0.2)

    def test_polar_night_does_not_raise(self):
        # acos domain clamp: midwinter above the Arctic circle.
        assert daylight_hours(80.0, 355) == pytest.approx(0.0, abs=1e-9)

    def test_polar_day_does_not_raise(self):
        assert daylight_hours(80.0, 172) == pytest.approx(24.0, abs=1e-9)


class TestWindAdjustment:
    """FAO-56 Example 14: wind speed conversion to 2 m."""

    def test_10m_to_2m(self):
        # FAO-56 Example 14: 3.2 m/s measured at 10 m -> u2 = 2.4 m/s
        assert wind_speed_at_2m(3.2, 10.0) == pytest.approx(2.4, abs=0.05)

    def test_2m_is_identity(self):
        assert wind_speed_at_2m(2.078, 2.0) == 2.078

    def test_adjustment_reduces_speed(self):
        # Wind is always slower nearer the ground; a bug that inverted the
        # formula would inflate every ET0 we compute.
        assert wind_speed_at_2m(5.0, 10.0) < 5.0


class TestPenmanMonteithWorkedExample:
    """FAO-56 Example 18: full daily ET0 at Uccle (Brussels, Belgium).

    Location: 50 deg 48' N, elevation 100 m. Date: 6 July (DOY 187).
    Published result: ET0 = 3.9 mm/day.

    This is the end-to-end check -- every function above feeds into it.
    """

    LAT = 50.80
    ELEV = 100.0
    DOY = 187
    TMAX = 21.5
    TMIN = 12.3
    RHMAX = 84.0
    RHMIN = 63.0
    U2 = 2.078
    SUNSHINE = 9.25

    def test_et0_matches_published_value(self):
        result = et0_from_daily_weather(
            t_max=self.TMAX,
            t_min=self.TMIN,
            latitude_deg=self.LAT,
            elevation_m=self.ELEV,
            day_of_year=self.DOY,
            wind_ms=self.U2,
            wind_height_m=2.0,
            rh_max=self.RHMAX,
            rh_min=self.RHMIN,
            sunshine_hours=self.SUNSHINE,
        )
        assert result.et0_mm_day == pytest.approx(3.9, abs=0.1)

    def test_intermediate_terms_match_published_values(self):
        # FAO-56 Example 18 prints the full intermediate chain; checking these
        # localises any future breakage to a single equation instead of just
        # telling us the final number moved.
        r = et0_from_daily_weather(
            t_max=self.TMAX, t_min=self.TMIN, latitude_deg=self.LAT,
            elevation_m=self.ELEV, day_of_year=self.DOY, wind_ms=self.U2,
            wind_height_m=2.0, rh_max=self.RHMAX, rh_min=self.RHMIN,
            sunshine_hours=self.SUNSHINE,
        )
        assert r.t_mean == pytest.approx(16.9, abs=0.05)
        assert r.delta == pytest.approx(0.122, abs=0.002)
        assert r.gamma == pytest.approx(0.0666, abs=0.0005)
        assert r.es == pytest.approx(1.997, abs=0.01)
        assert r.ea == pytest.approx(1.409, abs=0.01)
        assert r.vpd == pytest.approx(0.589, abs=0.01)
        assert r.ra == pytest.approx(41.09, abs=0.2)
        assert r.rs == pytest.approx(22.07, abs=0.2)
        assert r.rso == pytest.approx(30.90, abs=0.2)
        assert r.rns == pytest.approx(16.99, abs=0.2)
        assert r.rnl == pytest.approx(3.71, abs=0.1)
        assert r.rn == pytest.approx(13.28, abs=0.2)

    def test_radiation_source_is_reported(self):
        r = et0_from_daily_weather(
            t_max=self.TMAX, t_min=self.TMIN, latitude_deg=self.LAT,
            elevation_m=self.ELEV, day_of_year=self.DOY, wind_ms=self.U2,
            wind_height_m=2.0, rh_max=self.RHMAX, rh_min=self.RHMIN,
            sunshine_hours=self.SUNSHINE,
        )
        assert r.radiation_source == "angstrom_sunshine"


class TestInputHandling:
    """Behaviour on the messy inputs real weather APIs actually return."""

    def test_missing_humidity_raises_rather_than_guessing(self):
        with pytest.raises(ValueError, match="humidity"):
            et0_from_daily_weather(
                t_max=30.0, t_min=18.0, latitude_deg=20.0, elevation_m=100.0,
                day_of_year=180, wind_ms=2.0,
            )

    def test_dewpoint_path_agrees_with_rh_path(self):
        # If RH implies a given dewpoint, both humidity routes must agree.
        t_max, t_min = 25.0, 18.0
        ea_rh = actual_vapour_pressure_from_rh(t_max, t_min, 82.0, 54.0)
        # Invert Eq. 11 to get the dewpoint corresponding to that ea.
        t_dew = (237.3 * math.log(ea_rh / 0.6108)) / (
            17.27 - math.log(ea_rh / 0.6108)
        )
        a = et0_from_daily_weather(
            t_max=t_max, t_min=t_min, latitude_deg=20.0, elevation_m=100.0,
            day_of_year=180, wind_ms=2.0, wind_height_m=2.0,
            rh_max=82.0, rh_min=54.0, solar_radiation_mj=22.0,
        )
        b = et0_from_daily_weather(
            t_max=t_max, t_min=t_min, latitude_deg=20.0, elevation_m=100.0,
            day_of_year=180, wind_ms=2.0, wind_height_m=2.0,
            dewpoint_c=t_dew, solar_radiation_mj=22.0,
        )
        assert a.et0_mm_day == pytest.approx(b.et0_mm_day, abs=0.01)

    def test_hargreaves_fallback_is_in_plausible_range(self):
        # Hargreaves should land within ~20% of full Penman-Monteith for a
        # well-watered temperate site; FAO-56 Ch.4 sets that expectation.
        pm = et0_from_daily_weather(
            t_max=21.5, t_min=12.3, latitude_deg=50.8, elevation_m=100.0,
            day_of_year=187, wind_ms=2.078, wind_height_m=2.0,
            rh_max=84.0, rh_min=63.0, sunshine_hours=9.25,
        ).et0_mm_day
        hg = hargreaves_et0(21.5, 12.3, 50.8, 187)
        assert 0.8 * pm <= hg <= 1.2 * pm

    def test_cloudiness_ratio_is_clamped(self):
        # Rs slightly above modelled Rso must not produce negative Rnl.
        rnl = net_longwave_radiation(
            t_max=30.0, t_min=20.0, ea=1.5, rs=35.0, rso=30.0
        )
        assert rnl > 0


class TestPhysicalInvariants:
    """Properties that must hold regardless of any published table."""

    def _et0(self, **kw):
        base = dict(
            t_max=30.0, t_min=18.0, latitude_deg=20.0, elevation_m=100.0,
            day_of_year=180, wind_ms=2.0, wind_height_m=2.0,
            rh_max=80.0, rh_min=50.0, solar_radiation_mj=22.0,
        )
        base.update(kw)
        return et0_from_daily_weather(**base).et0_mm_day

    def test_et0_is_non_negative(self):
        assert self._et0(t_max=2.0, t_min=-5.0, solar_radiation_mj=1.0) >= 0.0

    def test_drier_air_increases_et0(self):
        humid = self._et0(rh_max=95.0, rh_min=80.0)
        dry = self._et0(rh_max=60.0, rh_min=20.0)
        assert dry > humid

    def test_more_radiation_increases_et0(self):
        assert self._et0(solar_radiation_mj=28.0) > self._et0(solar_radiation_mj=12.0)

    def test_more_wind_increases_et0_in_dry_air(self):
        # Advective term: wind only raises ET when VPD > 0.
        assert self._et0(wind_ms=5.0) > self._et0(wind_ms=0.5)

    def test_et0_magnitude_is_agronomically_sane(self):
        # FAO-56 Table 2: ET0 spans roughly 1-9 mm/day worldwide. A result
        # outside that band means a unit error somewhere upstream.
        assert 1.0 <= self._et0() <= 9.0
