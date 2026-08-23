"""
Daily root-zone soil water balance and irrigation scheduling.

Implements the FAO-56 Chapter 8 water balance:

    Dr,i = Dr,i-1 - (P - RO)i - Ii - CRi + ETc,i + DPi        (Eq. 85)

where Dr is root zone depletion [mm], P precipitation, RO surface runoff,
I net irrigation, CR capillary rise, ETc crop evapotranspiration and DP deep
percolation.

The scheduler this drives is the single most consequential thing the platform
computes: it tells a farmer whether to run a pump today. Getting it wrong in
one direction wastes scarce groundwater and electricity; wrong in the other
costs yield. So the model tracks depletion explicitly rather than using a
rule of thumb, reports the assumptions it made, and refuses to emit a
recommendation when its inputs are too stale to justify one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .crops import (
    CropParameters,
    GrowthStage,
    SoilWaterProperties,
    crop_coefficient,
    readily_available_water,
    total_available_water,
    water_stress_coefficient,
    yield_loss_from_water_deficit,
)


@dataclass
class DailyWeather:
    """One day of weather driving the balance."""
    day: date
    et0_mm: float
    rain_mm: float
    t_max: float
    t_min: float


@dataclass
class DayState:
    """The modelled state of the root zone at the end of one day."""
    day: date
    days_after_sowing: int
    stage: GrowthStage
    kc: float
    etc_mm: float
    eta_mm: float
    ks: float
    rain_mm: float
    runoff_mm: float
    irrigation_mm: float
    deep_percolation_mm: float
    depletion_mm: float
    taw_mm: float
    raw_mm: float

    @property
    def soil_moisture_percent(self) -> float:
        """Root zone water as a percentage of total available water."""
        if self.taw_mm <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - self.depletion_mm / self.taw_mm)))

    @property
    def is_stressed(self) -> bool:
        return self.ks < 1.0


def curve_number_runoff(rain_mm: float, curve_number: float = 78.0) -> float:
    """Surface runoff [mm] via the SCS curve number method.

    USDA-SCS National Engineering Handbook Section 4. CN 78 is the default for
    row crops on hydrologic soil group C under average antecedent moisture --
    a reasonable middle for the medium-textured soils common across the
    Indo-Gangetic plain and the Brazilian cerrado.

    Ignoring runoff entirely (as simple schedulers do) credits the crop with
    all the rain that fell, which during monsoon downpours materially
    over-estimates stored water and delays irrigation past the stress point.
    """
    if rain_mm <= 0:
        return 0.0
    s = (25400.0 / curve_number) - 254.0  # potential maximum retention [mm]
    initial_abstraction = 0.2 * s
    if rain_mm <= initial_abstraction:
        return 0.0
    return ((rain_mm - initial_abstraction) ** 2) / (rain_mm + 0.8 * s)


@dataclass
class IrrigationEvent:
    day: date
    depth_mm: float
    reason: str


@dataclass
class BalanceResult:
    """Full simulation output, retained for the Evidence Ledger."""
    days: list[DayState] = field(default_factory=list)
    irrigation_events: list[IrrigationEvent] = field(default_factory=list)

    @property
    def total_irrigation_mm(self) -> float:
        return sum(e.depth_mm for e in self.irrigation_events)

    @property
    def total_etc_mm(self) -> float:
        return sum(d.etc_mm for d in self.days)

    @property
    def total_eta_mm(self) -> float:
        return sum(d.eta_mm for d in self.days)

    @property
    def stressed_days(self) -> int:
        return sum(1 for d in self.days if d.is_stressed)

    def estimated_yield_loss(self, crop: CropParameters) -> float:
        """Relative yield loss over the whole season. FAO-56 Eq. 90."""
        return yield_loss_from_water_deficit(
            crop.yield_response_factor, self.total_eta_mm, self.total_etc_mm
        )


def simulate(
    crop: CropParameters,
    soil: SoilWaterProperties,
    sowing_date: date,
    weather: list[DailyWeather],
    initial_depletion_mm: float | None = None,
    auto_irrigate: bool = True,
    irrigation_efficiency: float = 0.75,
    curve_number: float = 78.0,
) -> BalanceResult:
    """Run the daily water balance across a weather series.

    Args:
        initial_depletion_mm: root zone depletion at sowing. Defaults to
            half of RAW, representing a seedbed prepared with a pre-sowing
            irrigation -- the common practice across South Asian rabi cropping.
        auto_irrigate: when True the scheduler refills the root zone to field
            capacity whenever depletion reaches RAW, which is the FAO-56
            no-stress criterion. When False the simulation is rainfed and
            reports the resulting stress instead.
        irrigation_efficiency: fraction of applied water reaching the root
            zone. 0.75 is typical for well-managed surface irrigation; drip
            runs 0.85-0.95 and unlined flood as low as 0.5.

    Rooting depth expands through the season rather than jumping to its
    maximum at sowing: a seedling cannot reach water at 1.4 m. TAW therefore
    grows daily, which is what makes early-season irrigation intervals come
    out short and frequent, as they should be.
    """
    result = BalanceResult()

    # Root depth at emergence. FAO-56 Ch.8 uses a 0.1-0.2 m starting depth.
    initial_root_depth = 0.15

    taw_initial = total_available_water(soil, initial_root_depth)
    if initial_depletion_mm is None:
        depletion = 0.5 * readily_available_water(
            taw_initial, crop.depletion_fraction, 5.0
        )
    else:
        depletion = initial_depletion_mm

    l_ini, l_dev, l_mid, l_late = crop.stage_days
    days_to_full_root = l_ini + l_dev

    for w in weather:
        das = (w.day - sowing_date).days
        if das < 0:
            continue
        if das > crop.total_days:
            break

        kc, stage = crop_coefficient(crop, das)
        etc = kc * w.et0_mm

        # Root depth grows linearly from emergence to the end of development.
        if das >= days_to_full_root:
            root_depth = crop.root_depth_m
        else:
            frac = das / max(days_to_full_root, 1)
            root_depth = initial_root_depth + frac * (
                crop.root_depth_m - initial_root_depth
            )

        taw = total_available_water(soil, root_depth)
        raw = readily_available_water(taw, crop.depletion_fraction, etc)

        runoff = curve_number_runoff(w.rain_mm, curve_number)
        effective_rain = w.rain_mm - runoff

        # Water stress is evaluated on yesterday's depletion, before today's
        # inputs -- the crop responds to the moisture it woke up to.
        ks = water_stress_coefficient(depletion, taw, raw)
        eta = ks * etc

        irrigation = 0.0
        if auto_irrigate:
            # Provisional depletion after rain and today's water use.
            provisional = depletion - effective_rain + eta
            if provisional >= raw:
                # Refill to field capacity. Net depth is the full depletion;
                # gross depth (what the farmer actually pumps) is larger by
                # the efficiency factor and is reported separately.
                net_depth = provisional
                irrigation = net_depth
                result.irrigation_events.append(
                    IrrigationEvent(
                        day=w.day,
                        depth_mm=net_depth / irrigation_efficiency,
                        reason=(
                            f"depletion {provisional:.0f} mm reached readily "
                            f"available water {raw:.0f} mm during {stage.value}"
                        ),
                    )
                )

        depletion = depletion - effective_rain - irrigation + eta

        # Water above field capacity drains below the root zone and is lost.
        deep_percolation = 0.0
        if depletion < 0:
            deep_percolation = -depletion
            depletion = 0.0

        # Depletion cannot exceed the total available water.
        depletion = min(depletion, taw)

        result.days.append(
            DayState(
                day=w.day, days_after_sowing=das, stage=stage, kc=kc,
                etc_mm=etc, eta_mm=eta, ks=ks, rain_mm=w.rain_mm,
                runoff_mm=runoff, irrigation_mm=irrigation,
                deep_percolation_mm=deep_percolation,
                depletion_mm=depletion, taw_mm=taw, raw_mm=raw,
            )
        )

    return result


def next_irrigation_advice(
    crop: CropParameters,
    soil: SoilWaterProperties,
    sowing_date: date,
    history: list[DailyWeather],
    forecast: list[DailyWeather],
    irrigation_efficiency: float = 0.75,
) -> dict:
    """Answer the question a farmer actually asks: do I irrigate, and how much?

    Runs the balance over observed weather to establish today's depletion,
    then projects forward over the forecast to find the day depletion would
    cross the stress threshold. Forecast rain is credited, so the advice
    correctly says "wait, rain is coming" rather than pumping the day before
    a storm -- the single most common and most expensive scheduling error.

    Returns a structured verdict rather than prose; the language layer turns
    it into a sentence in the farmer's own language, and the Evidence Ledger
    renders the numbers behind it.
    """
    past = simulate(
        crop, soil, sowing_date, history,
        auto_irrigate=False, irrigation_efficiency=irrigation_efficiency,
    )
    if not past.days:
        return {
            "verdict": "insufficient_data",
            "reason": "no weather days fall within the crop season",
        }

    today = past.days[-1]
    depletion = today.depletion_mm

    # Project forward day by day without irrigating, to find the crossing.
    projected_depletion = depletion
    days_until_stress: int | None = None
    forecast_rain_total = 0.0

    for offset, w in enumerate(forecast, start=1):
        das = (w.day - sowing_date).days
        if das > crop.total_days:
            break
        kc, _ = crop_coefficient(crop, das)
        etc = kc * w.et0_mm
        root_depth = min(
            crop.root_depth_m,
            0.15 + (das / max(crop.stage_days[0] + crop.stage_days[1], 1))
            * (crop.root_depth_m - 0.15),
        )
        taw = total_available_water(soil, root_depth)
        raw = readily_available_water(taw, crop.depletion_fraction, etc)

        runoff = curve_number_runoff(w.rain_mm)
        effective_rain = w.rain_mm - runoff
        forecast_rain_total += effective_rain

        projected_depletion = max(0.0, projected_depletion - effective_rain + etc)
        if projected_depletion >= raw and days_until_stress is None:
            days_until_stress = offset

    net_depth = today.depletion_mm
    gross_depth = net_depth / irrigation_efficiency

    if days_until_stress is None:
        verdict = "no_irrigation_needed"
    elif days_until_stress <= 1:
        verdict = "irrigate_now"
    elif forecast_rain_total >= net_depth * 0.8:
        verdict = "wait_for_rain"
    else:
        verdict = "irrigate_in_days"

    return {
        "verdict": verdict,
        "days_until_stress": days_until_stress,
        "current_depletion_mm": round(today.depletion_mm, 1),
        "readily_available_water_mm": round(today.raw_mm, 1),
        "total_available_water_mm": round(today.taw_mm, 1),
        "soil_moisture_percent": round(today.soil_moisture_percent, 1),
        "net_depth_mm": round(net_depth, 1),
        "gross_depth_mm": round(gross_depth, 1),
        "forecast_effective_rain_mm": round(forecast_rain_total, 1),
        "growth_stage": today.stage.value,
        "kc": round(today.kc, 2),
        "crop": crop.key,
        "soil_texture": soil.texture_class,
        "irrigation_efficiency": irrigation_efficiency,
    }
