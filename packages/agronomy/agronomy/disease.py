"""
Plant disease infection-risk models driven by weather.

Why this module exists
----------------------
A photograph tells you what a lesion looks like. It does not tell you what
was epidemiologically possible. Those are different questions, and answering
the second one changes the answer to the first.

Late blight cannot establish without sustained high humidity and mild
temperatures. If the last fortnight in that field was hot and dry, a
confident "late blight" read off a photograph is very probably wrong -- the
lesion is more likely early blight, a nutrient disorder, or spray scorch.
Conversely, if the field has just passed through two Smith Periods, a
borderline photograph deserves a much stronger prior.

So this module computes what the weather permitted, and the vision model is
given that as context rather than judging pixels alone. It is the same
commitment as everywhere else in the platform: the language model reasons,
validated models supply the quantities.

Sources
-------
Smith, L.P. (1956). "Potato blight forecasting by 90 per cent humidity
    criteria." Plant Pathology 5:83-87.  [Smith Period]
Analytis, S. (1977). "Uber die Relation zwischen biologischer Entwicklung
    und Temperatur bei phytopathogenen Pilzen." Journal of Phytopathology
    90:64-76.  [beta temperature-response function]
Magarey, R.D., Sutton, T.B., Thayer, C.L. (2005). "A simple generic
    infection model for foliar fungal plant pathogens." Phytopathology
    95:92-100.  [generic wetness-duration infection model]
Hwang, B.K., Koh, Y.J., Chung, H.S. (1987). "Effects of adult-plant
    resistance on blast severity and yield of rice." Plant Disease 71:1035-8.
Kim, C.K. (1986). Rice blast epidemiology and the leaf-wetness requirement.
De Wolf, E.D., Madden, L.V., Lipps, P.E. (2003). "Risk assessment models for
    wheat Fusarium head blight epidemics." Phytopathology 93:428-435.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    SEVERE = "severe"


@dataclass(frozen=True)
class DiseaseProfile:
    """Epidemiological requirements for one pathogen.

    Attributes:
        key / name: identifiers.
        crops: crop keys this pathogen affects.
        t_min/t_opt/t_max: cardinal temperatures for infection [C].
        min_wetness_hours: leaf wetness required at the optimum temperature
            for an infection event to establish.
        rh_threshold: relative humidity above which leaf wetness is inferred.
        notes: what distinguishes this disease in the field, written for a
            farmer to check rather than for a pathologist to read.
    """
    key: str
    name: str
    crops: tuple[str, ...]
    t_min: float
    t_opt: float
    t_max: float
    min_wetness_hours: float
    rh_threshold: float = 90.0
    field_signs: str = ""


# Pathogens selected for economic weight in Indian cropping systems. Between
# them these account for the large majority of avoidable foliar yield loss
# in the rice-wheat, cotton and horticultural belts.
DISEASES: dict[str, DiseaseProfile] = {
    "late_blight": DiseaseProfile(
        key="late_blight", name="Late blight (Phytophthora infestans)",
        crops=("potato",),
        t_min=4.0, t_opt=18.0, t_max=26.0, min_wetness_hours=10.0,
        field_signs=(
            "Dark water-soaked patches on leaf tips and edges, with a pale "
            "green halo. White fuzzy growth on the leaf underside in the "
            "morning. Spreads very fast in cool wet weather."
        ),
    ),
    "early_blight": DiseaseProfile(
        key="early_blight", name="Early blight (Alternaria solani)",
        crops=("potato",),
        t_min=8.0, t_opt=27.0, t_max=35.0, min_wetness_hours=6.0,
        field_signs=(
            "Brown spots with rings inside them, like a target. Starts on "
            "the older lower leaves. Common in warm weather with dew."
        ),
    ),
    "rice_blast": DiseaseProfile(
        key="rice_blast", name="Rice blast (Magnaporthe oryzae)",
        crops=("rice_paddy",),
        t_min=15.0, t_opt=25.0, t_max=32.0, min_wetness_hours=9.0,
        field_signs=(
            "Spindle-shaped spots with grey centres and brown edges on the "
            "leaves. At the neck of the panicle it turns black and the grain "
            "does not fill."
        ),
    ),
    "bacterial_leaf_blight": DiseaseProfile(
        key="bacterial_leaf_blight",
        name="Bacterial leaf blight (Xanthomonas oryzae)",
        crops=("rice_paddy",),
        t_min=20.0, t_opt=30.0, t_max=36.0, min_wetness_hours=8.0,
        field_signs=(
            "Yellow wavy streaks from the leaf tip downward, drying to straw "
            "colour. Worse after heavy wind and rain, and where nitrogen is "
            "heavy."
        ),
    ),
    "sheath_blight": DiseaseProfile(
        key="sheath_blight", name="Sheath blight (Rhizoctonia solani)",
        crops=("rice_paddy",),
        t_min=22.0, t_opt=30.0, t_max=35.0, min_wetness_hours=10.0,
        field_signs=(
            "Oval greenish-grey patches on the sheath near the water line, "
            "later with a brown border. Worst in a dense, heavily fertilised "
            "crop."
        ),
    ),
    "yellow_rust": DiseaseProfile(
        key="yellow_rust", name="Yellow / stripe rust (Puccinia striiformis)",
        crops=("wheat_winter", "wheat_spring", "barley"),
        t_min=2.0, t_opt=12.0, t_max=23.0, min_wetness_hours=6.0,
        field_signs=(
            "Bright yellow powder in neat stripes running along the leaf "
            "veins. Rubs off on your finger. A cool-weather disease of the "
            "northern plains and hills."
        ),
    ),
    "brown_rust": DiseaseProfile(
        key="brown_rust", name="Brown / leaf rust (Puccinia triticina)",
        crops=("wheat_winter", "wheat_spring"),
        t_min=10.0, t_opt=20.0, t_max=30.0, min_wetness_hours=6.0,
        field_signs=(
            "Orange-brown round dots scattered over the leaf, not in stripes. "
            "Appears later in the season as the weather warms."
        ),
    ),
    "powdery_mildew": DiseaseProfile(
        key="powdery_mildew", name="Powdery mildew (Erysiphe / Blumeria)",
        crops=("wheat_winter", "wheat_spring", "barley", "chickpea", "mustard"),
        # Distinctive: needs humid air but NOT free water on the leaf.
        t_min=5.0, t_opt=20.0, t_max=30.0, min_wetness_hours=0.0,
        rh_threshold=70.0,
        field_signs=(
            "White powder, like flour dusted on the leaf, that wipes off. "
            "Grows in humid air but does not need rain."
        ),
    ),
    "cotton_leaf_curl": DiseaseProfile(
        key="cotton_leaf_curl", name="Cotton leaf curl virus (whitefly-borne)",
        crops=("cotton",),
        # Vector-driven: risk tracks whitefly activity, which is hot and dry.
        t_min=20.0, t_opt=32.0, t_max=40.0, min_wetness_hours=0.0,
        rh_threshold=0.0,
        field_signs=(
            "Leaves curl upward and thicken, with veins swelling on the "
            "underside. Small white flies rise in a cloud when you shake the "
            "plant. Worst in hot dry spells."
        ),
    ),
    "chickpea_wilt": DiseaseProfile(
        key="chickpea_wilt", name="Fusarium wilt (Fusarium oxysporum)",
        crops=("chickpea",),
        t_min=15.0, t_opt=25.0, t_max=35.0, min_wetness_hours=0.0,
        rh_threshold=0.0,
        field_signs=(
            "Whole plant or one side droops and dries while nearby plants "
            "stay green. Split the stem near the ground: the inside is "
            "discoloured brown. A soil disease, worse in warm dry soil."
        ),
    ),
    "groundnut_leaf_spot": DiseaseProfile(
        key="groundnut_leaf_spot", name="Tikka leaf spot (Cercospora)",
        crops=("groundnut",),
        t_min=16.0, t_opt=26.0, t_max=32.0, min_wetness_hours=8.0,
        field_signs=(
            "Round dark spots with a yellow ring around them. Heavy "
            "leaf-fall late in the season."
        ),
    ),
    "maize_leaf_blight": DiseaseProfile(
        key="maize_leaf_blight", name="Turcicum leaf blight (Exserohilum)",
        crops=("maize_grain",),
        t_min=15.0, t_opt=24.0, t_max=30.0, min_wetness_hours=8.0,
        field_signs=(
            "Long grey-green cigar-shaped lesions running along the leaf. "
            "Starts low and moves up the plant."
        ),
    ),
}


# --------------------------------------------------------------------------
# Temperature response
# --------------------------------------------------------------------------

def temperature_response(
    t_celsius: float, t_min: float, t_opt: float, t_max: float
) -> float:
    """Relative infection efficiency at a given temperature, 0-1.

    Analytis (1977) beta function, as generalised by Magarey et al. (2005):

        f(T) = [ (Tmax - T)/(Tmax - Topt) ] * [ (T - Tmin)/(Topt - Tmin) ]^k
        k    = (Topt - Tmin) / (Tmax - Topt)

    Returns 0 outside the cardinal range. This shape matters: fungal
    infection is not linear in temperature, and a linear approximation
    overstates risk near the extremes, which is exactly where a farmer would
    be told to spray unnecessarily.
    """
    if t_celsius <= t_min or t_celsius >= t_max:
        return 0.0
    if t_opt <= t_min or t_max <= t_opt:
        return 0.0

    k = (t_opt - t_min) / (t_max - t_opt)
    term1 = (t_max - t_celsius) / (t_max - t_opt)
    term2 = ((t_celsius - t_min) / (t_opt - t_min)) ** k
    return max(0.0, min(1.0, term1 * term2))


def required_wetness_hours(
    t_celsius: float, profile: DiseaseProfile
) -> float | None:
    """Leaf wetness hours needed for infection at this temperature.

    The optimum requirement is scaled by the inverse of the temperature
    response: away from the optimum, a pathogen needs proportionally longer
    wetness to achieve the same infection. Returns None where infection is
    impossible at this temperature.
    """
    response = temperature_response(
        t_celsius, profile.t_min, profile.t_opt, profile.t_max
    )
    if response <= 0.01:
        return None
    return profile.min_wetness_hours / response


# --------------------------------------------------------------------------
# Leaf wetness
# --------------------------------------------------------------------------

def leaf_wetness_hours_from_rh(
    hourly_rh: list[float], threshold: float = 90.0
) -> float:
    """Estimate hours of leaf wetness from hourly relative humidity.

    Direct leaf-wetness sensors are rare outside research stations, so RH is
    the standard proxy: the canopy is taken to be wet whenever ambient RH
    exceeds ~90 percent. Crude, and it under-counts dew on clear calm nights
    when screen-height RH reads lower than the leaf surface, so risk from
    this path is treated as a lower bound rather than a precise figure.
    """
    return float(sum(1 for rh in hourly_rh if rh is not None and rh >= threshold))


def smith_period(
    daily: list[tuple[float, float]], min_temp: float = 10.0,
    min_hours_rh90: float = 11.0,
) -> bool:
    """Whether a Smith Period occurred. Smith (1956).

    A Smith Period is two consecutive days each having a minimum temperature
    of at least 10 C and at least 11 hours with relative humidity at or above
    90 percent. It remains the operational trigger for potato blight warnings
    across UK and Indian advisory services because it is simple, and because
    it errs toward warning.

    Args:
        daily: [(min_temp_c, hours_rh_at_or_above_90), ...] in date order.
    """
    qualifying = [
        (t >= min_temp and h >= min_hours_rh90) for t, h in daily
    ]
    return any(a and b for a, b in zip(qualifying, qualifying[1:]))


# --------------------------------------------------------------------------
# Risk assessment
# --------------------------------------------------------------------------

@dataclass
class DayRisk:
    day: date
    infection_favourable: bool
    temperature_response: float
    wetness_hours: float
    required_hours: float | None
    mean_temp: float


@dataclass
class DiseaseRisk:
    """Computed infection pressure for one disease over a recent window."""
    disease: DiseaseProfile
    level: RiskLevel
    favourable_days: int
    total_days: int
    smith_periods: int
    drivers: list[str] = field(default_factory=list)
    daily: list[DayRisk] = field(default_factory=list)

    @property
    def favourable_fraction(self) -> float:
        return self.favourable_days / self.total_days if self.total_days else 0.0

    def to_dict(self) -> dict:
        return {
            "disease": self.disease.key,
            "name": self.disease.name,
            "risk_level": self.level.value,
            "favourable_days": self.favourable_days,
            "days_assessed": self.total_days,
            "smith_periods": self.smith_periods,
            "drivers": self.drivers,
            "field_signs": self.disease.field_signs,
        }


def assess_disease_risk(
    profile: DiseaseProfile,
    days: list[dict],
) -> DiseaseRisk:
    """Score infection pressure for one disease over a window of days.

    Args:
        days: dicts with keys `date`, `t_min`, `t_max`, `t_mean`, and either
            `hourly_rh` (list of hourly RH) or `rh_max`/`rh_mean`.

    A day counts as favourable when the temperature permits infection and
    estimated leaf wetness meets the temperature-adjusted requirement.
    Diseases with no wetness requirement (powdery mildew, vector-borne virus,
    soil-borne wilt) are scored on temperature and humidity alone, because
    applying a wetness criterion to them would suppress genuine risk.
    """
    day_risks: list[DayRisk] = []
    smith_input: list[tuple[float, float]] = []

    for d in days:
        t_mean = d.get("t_mean")
        if t_mean is None:
            t_min, t_max = d.get("t_min"), d.get("t_max")
            if t_min is None or t_max is None:
                continue
            t_mean = (t_min + t_max) / 2.0

        hourly = d.get("hourly_rh") or []
        if hourly:
            wetness = leaf_wetness_hours_from_rh(hourly, profile.rh_threshold)
            rh90 = leaf_wetness_hours_from_rh(hourly, 90.0)
        else:
            # Without hourly data, approximate wetness duration from the daily
            # RH maximum. Deliberately conservative -- this path is a fallback
            # and should not manufacture confident risk.
            rh_max = d.get("rh_max") or d.get("rh_mean") or 0.0
            wetness = 12.0 if rh_max >= profile.rh_threshold else (
                6.0 if rh_max >= profile.rh_threshold - 10 else 0.0
            )
            rh90 = 12.0 if rh_max >= 90 else 0.0

        response = temperature_response(
            t_mean, profile.t_min, profile.t_opt, profile.t_max
        )
        required = required_wetness_hours(t_mean, profile)

        if profile.min_wetness_hours <= 0.0:
            # Non-wetness pathogens: temperature plus ambient humidity.
            favourable = response > 0.35 and wetness > 0
        else:
            favourable = (
                required is not None and wetness >= required and response > 0.1
            )

        day_risks.append(DayRisk(
            day=d.get("date"), infection_favourable=favourable,
            temperature_response=response, wetness_hours=wetness,
            required_hours=required, mean_temp=t_mean,
        ))
        smith_input.append((d.get("t_min", t_mean), rh90))

    favourable_days = sum(1 for r in day_risks if r.infection_favourable)
    total = len(day_risks)

    # Count Smith Periods across the window (potato blight only).
    #
    # Counted as distinct *spells*, not as overlapping pairs. A run of four
    # consecutive qualifying days contains three overlapping two-day pairs,
    # but it is one weather event, and tallying pairs triples the count.
    # That inflation matters: two Smith Periods escalate the risk band to
    # severe, so pair-counting turned a single mild wet spell into a spray
    # recommendation.
    smith_count = 0
    if profile.key == "late_blight":
        run = 0
        for t_min_day, hours_rh90 in smith_input:
            if t_min_day >= 10.0 and hours_rh90 >= 11.0:
                run += 1
            else:
                if run >= 2:
                    smith_count += 1
                run = 0
        if run >= 2:
            smith_count += 1

    fraction = favourable_days / total if total else 0.0
    if total == 0:
        level = RiskLevel.NONE
    elif fraction >= 0.55 or smith_count >= 2:
        level = RiskLevel.SEVERE
    elif fraction >= 0.35 or smith_count >= 1:
        level = RiskLevel.HIGH
    elif fraction >= 0.18:
        level = RiskLevel.MODERATE
    elif fraction > 0:
        level = RiskLevel.LOW
    else:
        level = RiskLevel.NONE

    drivers: list[str] = []
    if total:
        mean_temp = sum(r.mean_temp for r in day_risks) / total
        mean_wet = sum(r.wetness_hours for r in day_risks) / total
        if level in (RiskLevel.NONE, RiskLevel.LOW):
            if mean_temp > profile.t_max:
                drivers.append(
                    f"Too hot: average {mean_temp:.0f} C against an upper "
                    f"limit of {profile.t_max:.0f} C for this pathogen"
                )
            elif mean_temp < profile.t_min:
                drivers.append(
                    f"Too cold: average {mean_temp:.0f} C against a lower "
                    f"limit of {profile.t_min:.0f} C"
                )
            elif profile.min_wetness_hours > 0 and mean_wet < profile.min_wetness_hours:
                drivers.append(
                    f"Too dry: about {mean_wet:.0f} h of leaf wetness a day "
                    f"against roughly {profile.min_wetness_hours:.0f} h needed"
                )
        else:
            drivers.append(
                f"{favourable_days} of the last {total} days had weather "
                f"suitable for infection"
            )
            if smith_count:
                drivers.append(
                    f"{smith_count} Smith Period(s) recorded — the standard "
                    f"blight warning trigger"
                )
            drivers.append(
                f"Average temperature {mean_temp:.0f} C "
                f"(optimum {profile.t_opt:.0f} C), about {mean_wet:.0f} h of "
                f"leaf wetness a day"
            )

    return DiseaseRisk(
        disease=profile, level=level, favourable_days=favourable_days,
        total_days=total, smith_periods=smith_count, drivers=drivers,
        daily=day_risks,
    )


def assess_all_for_crop(crop: str, days: list[dict]) -> list[DiseaseRisk]:
    """Assess every disease relevant to a crop, ordered by risk."""
    order = {
        RiskLevel.SEVERE: 4, RiskLevel.HIGH: 3, RiskLevel.MODERATE: 2,
        RiskLevel.LOW: 1, RiskLevel.NONE: 0,
    }
    risks = [
        assess_disease_risk(profile, days)
        for profile in DISEASES.values()
        if crop in profile.crops
    ]
    risks.sort(key=lambda r: (order[r.level], r.favourable_fraction), reverse=True)
    return risks
