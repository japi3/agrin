"""
Tests for the RothC-26.3 soil organic carbon model.

Validation strategy: RothC's published parameter values are checked directly,
then the model is exercised against the qualitative behaviours the Rothamsted
long-term experiments established over 170 years -- continuous arable without
inputs loses carbon, farmyard manure builds it, clay soils retain more, and
equilibrium is approached slowly. A model that reproduces those signs and
magnitudes is usable for practice advice; one that does not is not.
"""

import math
import pytest

from agronomy.carbon import (
    CarbonPools,
    MonthlyInput,
    co2_to_biohum_ratio,
    initialise_pools,
    inert_organic_matter,
    maximum_tsmd,
    project,
    rate_modifying_factor_cover,
    rate_modifying_factor_moisture,
    rate_modifying_factor_temperature,
    soc_percent_to_t_ha,
    step_month,
)


class TestRateModifiers:
    """Coleman & Jenkinson (2014) Eq. 1-3."""

    def test_temperature_factor_published_points(self):
        # a = 47.91 / (1 + exp(106.06/(T + 18.27)))
        # Evaluated directly from the published equation.
        for t in [0.0, 10.0, 15.0, 20.0, 30.0]:
            expected = 47.91 / (1.0 + math.exp(106.06 / (t + 18.27)))
            assert rate_modifying_factor_temperature(t) == pytest.approx(expected)

    def test_temperature_factor_increases_with_warmth(self):
        vals = [rate_modifying_factor_temperature(t) for t in range(-10, 40, 5)]
        assert all(b > a for a, b in zip(vals, vals[1:]))

    def test_frozen_soil_does_not_decompose(self):
        assert rate_modifying_factor_temperature(-20.0) == 0.0
        assert rate_modifying_factor_temperature(-18.27) == 0.0

    def test_temperature_factor_is_near_one_at_reference(self):
        # RothC is normalised so a ~= 1 around 9-10 C.
        assert rate_modifying_factor_temperature(9.25) == pytest.approx(1.0, abs=0.05)

    def test_moisture_factor_is_one_in_wet_soil(self):
        max_def = maximum_tsmd(clay_percent=20.0)
        assert rate_modifying_factor_moisture(0.0, max_def) == 1.0

    def test_moisture_factor_floors_at_point_two(self):
        max_def = maximum_tsmd(clay_percent=20.0)
        assert rate_modifying_factor_moisture(max_def, max_def) == pytest.approx(0.2)

    def test_moisture_factor_is_bounded(self):
        max_def = maximum_tsmd(clay_percent=30.0)
        for frac in [0.0, 0.2, 0.444, 0.6, 0.8, 1.0]:
            b = rate_modifying_factor_moisture(frac * max_def, max_def)
            assert 0.2 <= b <= 1.0

    def test_cover_slows_decomposition(self):
        assert rate_modifying_factor_cover(True) < rate_modifying_factor_cover(False)

    def test_bare_soil_dries_further_than_covered_soil(self):
        # The 1.8 divisor: bare soil reaches a deeper moisture deficit.
        covered = maximum_tsmd(25.0, vegetated=True)
        bare = maximum_tsmd(25.0, vegetated=False)
        assert bare > covered  # both negative; bare is closer to zero
        assert covered == pytest.approx(bare * 1.8)


class TestClayProtection:
    """Coleman & Jenkinson (2014) Eq. 4."""

    def test_ratio_published_formula(self):
        for clay in [5.0, 20.0, 40.0, 60.0]:
            expected = 1.67 * (1.85 + 1.60 * math.exp(-0.0786 * clay))
            assert co2_to_biohum_ratio(clay) == pytest.approx(expected)

    def test_clay_soils_retain_more_carbon(self):
        # Higher clay -> lower x -> larger retained fraction 1/(x+1).
        sandy_x = co2_to_biohum_ratio(5.0)
        clayey_x = co2_to_biohum_ratio(50.0)
        assert clayey_x < sandy_x
        assert 1.0 / (clayey_x + 1.0) > 1.0 / (sandy_x + 1.0)


class TestInertOrganicMatter:
    """Falloon et al. (1998)."""

    def test_iom_formula(self):
        assert inert_organic_matter(50.0) == pytest.approx(0.049 * 50.0 ** 1.139)

    def test_iom_is_a_minority_of_soc(self):
        for soc in [20.0, 50.0, 100.0]:
            assert 0.0 < inert_organic_matter(soc) < 0.35 * soc

    def test_zero_soc_zero_iom(self):
        assert inert_organic_matter(0.0) == 0.0


class TestPoolInitialisation:
    def test_pools_sum_to_total_soc(self):
        pools = initialise_pools(45.0, clay_percent=25.0)
        assert pools.total == pytest.approx(45.0, abs=1e-9)

    def test_humus_dominates(self):
        # Long-term arable soils are overwhelmingly humified carbon.
        pools = initialise_pools(45.0, clay_percent=25.0)
        assert pools.hum > 0.6 * pools.total

    def test_active_excludes_iom(self):
        pools = initialise_pools(45.0, clay_percent=25.0)
        assert pools.active == pytest.approx(pools.total - pools.iom)


class TestUnitConversion:
    def test_soc_percent_to_stock(self):
        # 1.2% SOC, bulk density 1.3 g/cm3, 30 cm depth
        # = 0.012 * 1.3 * 30 * 100 = 46.8 t C/ha
        assert soc_percent_to_t_ha(1.2, 1.3, 30.0) == pytest.approx(46.8, abs=0.01)

    def test_stock_scales_with_depth(self):
        assert soc_percent_to_t_ha(1.0, 1.4, 60.0) == pytest.approx(
            2.0 * soc_percent_to_t_ha(1.0, 1.4, 30.0)
        )

    def test_typical_arable_stock_is_plausible(self):
        # Indo-Gangetic plain topsoils run 0.4-0.8% SOC; 30 cm stocks of
        # 15-35 t C/ha. A conversion error shows up immediately here.
        stock = soc_percent_to_t_ha(0.55, 1.45, 30.0)
        assert 15.0 <= stock <= 35.0


def _forcing(
    carbon_input: float, vegetated_months: int = 8, fym: float = 0.0,
    temp_base: float = 22.0,
) -> list[MonthlyInput]:
    """A stylised sub-tropical year: warm, monsoonal, cropped most of the year."""
    rain = [15, 15, 20, 25, 60, 150, 260, 240, 160, 60, 15, 10]
    evap = [90, 110, 150, 180, 200, 150, 100, 95, 110, 120, 95, 80]
    temps = [temp_base - 8, temp_base - 5, temp_base, temp_base + 5,
             temp_base + 8, temp_base + 6, temp_base + 2, temp_base + 1,
             temp_base + 1, temp_base - 1, temp_base - 5, temp_base - 8]
    months = []
    for i in range(12):
        months.append(
            MonthlyInput(
                mean_temp_c=temps[i],
                rainfall_mm=float(rain[i]),
                open_pan_evaporation_mm=float(evap[i]),
                carbon_input_t_ha=carbon_input / max(vegetated_months, 1)
                if i < vegetated_months else 0.0,
                is_vegetated=i < vegetated_months,
                farmyard_manure_t_ha=fym / 12.0,
            )
        )
    return months


class TestProjection:
    def test_requires_twelve_months(self):
        with pytest.raises(ValueError, match="12 months"):
            project(40.0, 25.0, _forcing(3.0)[:6], years=5)

    def test_residue_removal_depletes_carbon(self):
        # Burning or removing all residue: near-zero return of carbon.
        p = project(40.0, 25.0, _forcing(carbon_input=0.2), years=20)
        assert p.delta_soc < 0
        assert p.final_soc < p.initial_soc

    def test_residue_retention_builds_carbon(self):
        # Retaining residue plus a cover crop.
        p = project(40.0, 25.0, _forcing(carbon_input=6.0, vegetated_months=11), years=20)
        assert p.delta_soc > 0

    def test_manure_builds_more_carbon_than_residue_alone(self):
        residue = project(40.0, 25.0, _forcing(carbon_input=3.0), years=20)
        manured = project(40.0, 25.0, _forcing(carbon_input=3.0, fym=10.0), years=20)
        assert manured.final_soc > residue.final_soc

    def test_clay_soil_retains_more_than_sandy_under_same_management(self):
        sandy = project(40.0, 5.0, _forcing(carbon_input=4.0), years=25)
        clayey = project(40.0, 45.0, _forcing(carbon_input=4.0), years=25)
        assert clayey.final_soc > sandy.final_soc

    def test_cooler_climate_retains_more_carbon(self):
        # The reason Russian chernozems hold far more carbon than Indian
        # alluvium under comparable inputs.
        warm = project(40.0, 25.0, _forcing(4.0, temp_base=28.0), years=25)
        cool = project(40.0, 25.0, _forcing(4.0, temp_base=8.0), years=25)
        assert cool.final_soc > warm.final_soc

    def test_change_is_slow_and_bounded(self):
        # HUM turns over at 2%/yr. Anything claiming a doubling in a few
        # seasons is not RothC. Guard against a rate-constant unit error.
        p = project(40.0, 25.0, _forcing(carbon_input=6.0, vegetated_months=11), years=5)
        annual_rate = p.delta_soc / 5.0
        assert 0.0 < annual_rate < 2.0  # t C/ha/yr

    def test_trajectory_is_monotonic_under_constant_management(self):
        p = project(40.0, 25.0, _forcing(carbon_input=6.0, vegetated_months=11), years=30)
        # Approaching a new equilibrium from below: monotonically increasing.
        assert all(b >= a - 1e-9 for a, b in zip(p.soc_by_year, p.soc_by_year[1:]))

    def test_approaches_equilibrium_asymptotically(self):
        # Gains decelerate: the first decade adds more than the third.
        p = project(40.0, 25.0, _forcing(carbon_input=6.0, vegetated_months=11), years=30)
        first_decade = p.soc_by_year[9] - p.initial_soc
        third_decade = p.soc_by_year[29] - p.soc_by_year[19]
        assert first_decade > third_decade

    def test_co2e_conversion(self):
        p = project(40.0, 25.0, _forcing(carbon_input=6.0, vegetated_months=11), years=20)
        assert p.co2e_sequestered_t_ha == pytest.approx(p.delta_soc * 44.0 / 12.0)

    def test_iom_is_conserved(self):
        # Inert carbon must never decompose, in any scenario.
        pools = initialise_pools(40.0, 25.0)
        iom0 = pools.iom
        tsmd = 0.0
        for m in _forcing(3.0) * 10:
            pools, tsmd = step_month(pools, m, 25.0, tsmd)
        assert pools.iom == pytest.approx(iom0)

    def test_pools_never_go_negative(self):
        pools = initialise_pools(40.0, 25.0)
        tsmd = 0.0
        # Hot, wet, zero input: maximum decomposition pressure.
        harsh = [
            MonthlyInput(mean_temp_c=35.0, rainfall_mm=300.0,
                         open_pan_evaporation_mm=50.0, carbon_input_t_ha=0.0,
                         is_vegetated=False)
        ] * 12
        for m in harsh * 30:
            pools, tsmd = step_month(pools, m, 25.0, tsmd)
            assert pools.dpm >= -1e-9
            assert pools.rpm >= -1e-9
            assert pools.bio >= -1e-9
            assert pools.hum >= -1e-9


class TestPracticeComparison:
    """The actual decision surface: which practice change builds most carbon?"""

    def test_practices_rank_as_agronomy_expects(self):
        baseline = project(40.0, 25.0, _forcing(1.0, vegetated_months=6), years=20)
        residue = project(40.0, 25.0, _forcing(4.0, vegetated_months=6), years=20)
        cover = project(40.0, 25.0, _forcing(5.5, vegetated_months=11), years=20)
        cover_manure = project(
            40.0, 25.0, _forcing(5.5, vegetated_months=11, fym=8.0), years=20
        )
        ranking = [baseline.final_soc, residue.final_soc, cover.final_soc,
                   cover_manure.final_soc]
        assert ranking == sorted(ranking)
