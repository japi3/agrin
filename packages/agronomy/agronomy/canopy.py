"""
Interpreting satellite vegetation indices against expected crop development.

The problem with raw NDVI
------------------------
An NDVI of 0.45 is meaningless on its own. For a maize crop three weeks after
sowing it is healthy and exactly on track. For the same crop at tasselling it
means something has gone badly wrong. Every "satellite crop monitoring"
product that shows a farmer a coloured map and an index number is asking them
to supply that judgement themselves.

So this module converts NDVI into fractional canopy cover, computes what
cover the crop *should* have reached at its current growth stage, and reports
the gap. That gap is the actionable quantity.

Method
------
NDVI to fractional cover follows Carlson & Ripley (1997):

    fc = [ (NDVI - NDVI_soil) / (NDVI_veg - NDVI_soil) ]^2

The square is not decoration. The linear form systematically overestimates
cover at intermediate NDVI, because reflectance saturates as leaf area
climbs; using it would make a struggling crop look adequate at exactly the
point when intervention still helps.

Expected cover is derived from the FAO-56 crop coefficient curve. Kc and
canopy cover both track canopy development through the season and share the
same four-stage shape (FAO-56 Ch. 6; Allen & Pereira 2009 relate Kc directly
to fraction of ground covered), so the normalised Kc curve is used as the
expected-cover trajectory.

References
----------
Carlson, T.N. & Ripley, D.A. (1997). "On the relation between NDVI,
    fractional vegetation cover, and leaf area index." Remote Sensing of
    Environment 62:241-252.
Gutman, G. & Ignatov, A. (1998). "The derivation of the green vegetation
    fraction from NOAA/AVHRR data." International Journal of Remote Sensing
    19:1533-1543.
Allen, R.G. & Pereira, L.S. (2009). "Estimating crop coefficients from
    fraction of ground cover and height." Irrigation Science 28:17-34.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .crops import CROPS, CropParameters, GrowthStage, crop_coefficient

# Typical NDVI endpoints for the Carlson & Ripley scaling.
# Bare soil varies with moisture and roughness; 0.15 is a common value for
# the tilled alluvial and black soils in scope here. Full green canopy
# saturates around 0.90 for Sentinel-2 at 10 m.
NDVI_BARE_SOIL = 0.15
NDVI_FULL_CANOPY = 0.90

# Cover reached by the end of the initial stage, i.e. an emerged but still
# tiny crop. The development curve must continue from this value rather than
# restart from zero, or the expected trajectory contains a step down exactly
# where the canopy should be expanding fastest.
EMERGENCE_COVER = 0.15

# Peak fractional cover a healthy crop reaches at mid-season. Row crops do
# not reach 1.0 even at full canopy; FAO-56 Table 12 canopy assumptions.
PEAK_COVER = {
    "rice_paddy": 0.95, "wheat_winter": 0.90, "wheat_spring": 0.90,
    "barley": 0.90, "maize_grain": 0.85, "soybean": 0.90, "cotton": 0.80,
    "sugarcane": 0.95, "chickpea": 0.75, "mustard": 0.80, "groundnut": 0.85,
    "pearl_millet": 0.70, "sorghum": 0.80, "potato": 0.85, "sunflower": 0.80,
}


class CropStatus(str, Enum):
    """Verdict on observed canopy against expectation."""
    AHEAD = "ahead_of_expected"
    ON_TRACK = "on_track"
    SLIGHTLY_BEHIND = "slightly_behind"
    BEHIND = "behind"
    SEVERELY_BEHIND = "severely_behind"
    NOT_EMERGED = "not_emerged"
    SENESCING = "senescing_normally"


def looks_like_annual_cropland(ndvi_history: list[float]) -> bool:
    """Whether a field's NDVI history behaves like annual cropland.

    Annual cropping has a characteristic signature: the ground goes bare
    between seasons, so NDVI swings through a wide amplitude every year.
    Orchards, plantations, permanent grassland, scrub and peri-urban tree
    cover stay green and swing narrowly.

    This matters because every stage-based judgement in this module assumes
    the greenness it sees belongs to the crop the farmer named. Over
    permanent vegetation that assumption is simply false, and the output is
    confidently meaningless -- a peri-urban point with roadside trees read as
    "ahead of expected" for a maize crop that was never there.

    Returning False does not mean the field is worthless; it means canopy
    should be reported without a stage verdict, and the farmer asked to
    confirm the boundary.
    """
    values = [v for v in ndvi_history if v is not None and -1.0 <= v <= 1.0]
    if len(values) < 8:
        return True  # Not enough evidence to doubt the farmer.
    ordered = sorted(values)
    low = ordered[int(0.05 * (len(ordered) - 1))]
    high = ordered[int(0.95 * (len(ordered) - 1))]
    # Annual cropland typically swings by 0.35 or more between bare soil and
    # full canopy; a permanently vegetated pixel rarely does.
    return (high - low) >= 0.30


def representative_ndvi(
    observations: list[tuple["date", float]], within_days: int = 30
) -> float | None:
    """The NDVI to judge the crop by: the best recent observation.

    A single latest reading is fragile. Thin cirrus that survives the cloud
    mask, an off-nadir view, or haze all depress one scene, and judging a
    season on it produces a failure verdict for a healthy crop.

    Taking the maximum over recent passes is the standard compositing
    approach in vegetation monitoring for exactly this reason: atmospheric
    effects almost always reduce NDVI, so the maximum is the observation
    least contaminated by them.
    """
    if not observations:
        return None
    ordered = sorted(observations, key=lambda o: o[0])
    latest_day = ordered[-1][0]
    from datetime import timedelta
    cutoff = latest_day - timedelta(days=within_days)
    window = [v for d, v in ordered if d >= cutoff]
    if not window:
        window = [ordered[-1][1]]
    return max(window)


def calibrate_endpoints(
    ndvi_history: list[float],
    fallback_soil: float = NDVI_BARE_SOIL,
    fallback_veg: float = NDVI_FULL_CANOPY,
) -> tuple[float, float]:
    """Derive per-field NDVI endpoints from the field's own history.

    Gutman & Ignatov (1998) specify *local* scaling rather than global
    constants, and this is why it matters here. Global endpoints assume every
    field's bare soil and full canopy look alike, and they do not: a Punjab
    alluvial soil, a Vertisol and a laterite have visibly different bare-soil
    NDVI, and canopy saturation differs by crop and by sensor geometry.

    Using fixed constants at Moga mapped a seasonal peak of 0.68 to only 50
    percent cover, which would have raised a "crop failing" alarm on a
    perfectly healthy paddy field. Calibrating against what this field
    actually achieves over a year of imagery removes that whole class of
    error, and it is the published method rather than a workaround.

    The 5th and 95th percentiles are used rather than min and max: extremes
    in a satellite series are usually residual cloud edge or shadow that
    survived masking, and anchoring the scale to them would be worse than
    using constants.

    Falls back to the global defaults when there is too little history to
    calibrate, since a handful of observations from one season cannot span
    bare soil to full canopy.
    """
    values = sorted(v for v in ndvi_history if v is not None and -1.0 <= v <= 1.0)
    if len(values) < 8:
        return fallback_soil, fallback_veg

    def percentile(p: float) -> float:
        idx = int(round(p * (len(values) - 1)))
        return values[max(0, min(len(values) - 1, idx))]

    soil = percentile(0.05)
    veg = percentile(0.95)

    # A field observed only mid-season may never show bare soil, leaving the
    # endpoints too close together to scale against. Keep the defaults there.
    if veg - soil < 0.25:
        return fallback_soil, fallback_veg

    # Guard against implausible calibration from a bad series.
    soil = max(0.0, min(0.35, soil))
    veg = max(0.5, min(0.95, veg))
    return soil, veg


def fractional_cover_from_ndvi(
    ndvi: float,
    ndvi_soil: float = NDVI_BARE_SOIL,
    ndvi_veg: float = NDVI_FULL_CANOPY,
) -> float:
    """Fractional green canopy cover [0-1] from NDVI. Carlson & Ripley (1997)."""
    if ndvi_veg <= ndvi_soil:
        return 0.0
    scaled = (ndvi - ndvi_soil) / (ndvi_veg - ndvi_soil)
    scaled = max(0.0, min(1.0, scaled))
    return scaled ** 2


def expected_fractional_cover(crop: CropParameters, days_after_sowing: int) -> float:
    """Fractional cover a healthy crop should show at this point in the season.

    Derived from the normalised FAO-56 Kc curve, scaled to the crop's peak
    canopy cover. Before emergence the expectation is essentially bare soil,
    which is why an NDVI reading in week one carries no information about
    crop health -- and the caller is told so rather than being handed a
    misleading "severely behind".
    """
    peak = PEAK_COVER.get(crop.key, 0.85)
    kc, stage = crop_coefficient(crop, days_after_sowing)

    denominator = crop.kc_mid - crop.kc_ini
    if denominator <= 0:
        return peak if stage == GrowthStage.MID_SEASON else 0.1

    if stage == GrowthStage.INITIAL:
        # Emergence: cover climbs from nearly nothing across the initial stage.
        l_ini = crop.stage_days[0]
        fraction = days_after_sowing / max(l_ini, 1)
        return max(0.0, min(EMERGENCE_COVER, EMERGENCE_COVER * fraction))

    if stage == GrowthStage.LATE_SEASON:
        # Senescence: green cover falls away as the crop matures. The decline
        # is expected, and flagging it as a problem would produce an alarm on
        # every field every season at harvest.
        l_ini, l_dev, l_mid, l_late = crop.stage_days
        into_late = days_after_sowing - (l_ini + l_dev + l_mid)
        fraction = max(0.0, min(1.0, into_late / max(l_late, 1)))
        end_cover = peak * 0.25
        return peak + fraction * (end_cover - peak)

    # Development and mid-season: interpolate from the emergence cover up to
    # the crop's peak, following the normalised Kc curve. Starting from
    # EMERGENCE_COVER rather than zero keeps the trajectory continuous across
    # the stage boundary.
    normalised = max(0.0, min(1.0, (kc - crop.kc_ini) / denominator))
    return EMERGENCE_COVER + normalised * (peak - EMERGENCE_COVER)


@dataclass
class CanopyAssessment:
    """Observed canopy against expectation, with a verdict."""
    observed_ndvi: float
    observed_cover: float
    expected_cover: float
    status: CropStatus
    days_after_sowing: int
    growth_stage: GrowthStage
    uniformity: float | None
    trend_per_day: float | None
    explanation: str

    @property
    def cover_gap(self) -> float:
        """Observed minus expected cover. Negative means behind."""
        return self.observed_cover - self.expected_cover

    @property
    def relative_gap(self) -> float:
        if self.expected_cover <= 0.01:
            return 0.0
        return self.cover_gap / self.expected_cover

    def to_dict(self) -> dict:
        return {
            "ndvi": round(self.observed_ndvi, 3),
            "canopy_cover_percent": round(self.observed_cover * 100, 1),
            "expected_cover_percent": round(self.expected_cover * 100, 1),
            "status": self.status.value,
            "days_after_sowing": self.days_after_sowing,
            "growth_stage": self.growth_stage.value,
            "uniformity_percent": (
                round(self.uniformity * 100, 1) if self.uniformity is not None else None
            ),
            "ndvi_trend_per_day": (
                round(self.trend_per_day, 4) if self.trend_per_day is not None else None
            ),
            "explanation": self.explanation,
        }


def assess_canopy(
    crop_key: str,
    days_after_sowing: int,
    ndvi: float,
    uniformity: float | None = None,
    trend_per_day: float | None = None,
    ndvi_soil: float = NDVI_BARE_SOIL,
    ndvi_veg: float = NDVI_FULL_CANOPY,
) -> CanopyAssessment | None:
    """Compare an observed NDVI against expected development for the crop.

    Returns None for an uncalibrated crop rather than guessing -- the
    comparison is only meaningful against a known phenology.
    """
    crop = CROPS.get(crop_key)
    if crop is None:
        return None

    observed = fractional_cover_from_ndvi(ndvi, ndvi_soil, ndvi_veg)
    expected = expected_fractional_cover(crop, days_after_sowing)
    _, stage = crop_coefficient(crop, days_after_sowing)

    # Very early in the season NDVI reflects the soil, not the crop, so no
    # health verdict is possible. Saying so is more useful than a false alarm.
    if days_after_sowing < 12 or expected < 0.08:
        status = CropStatus.NOT_EMERGED
        explanation = (
            "The crop is too young for satellite readings to say much yet. "
            "At this stage the satellite is mostly seeing bare soil."
        )
        return CanopyAssessment(
            ndvi, observed, expected, status, days_after_sowing, stage,
            uniformity, trend_per_day, explanation,
        )

    if stage == GrowthStage.LATE_SEASON and observed < expected:
        # Falling cover late in the season is maturity, not stress.
        status = CropStatus.SENESCING
        explanation = (
            "The crop is drying down as it matures. Falling greenness is "
            "normal and expected at this stage."
        )
        return CanopyAssessment(
            ndvi, observed, expected, status, days_after_sowing, stage,
            uniformity, trend_per_day, explanation,
        )

    gap = observed - expected
    relative = gap / expected if expected > 0.01 else 0.0

    if relative >= 0.12:
        status = CropStatus.AHEAD
        explanation = (
            "Your crop is greener and fuller than usual for this stage. "
            "That is a good sign."
        )
    elif relative >= -0.12:
        status = CropStatus.ON_TRACK
        explanation = "Your crop is growing about as it should for this stage."
    elif relative >= -0.28:
        status = CropStatus.SLIGHTLY_BEHIND
        explanation = (
            "Your crop is a little thinner than usual for this stage. Worth "
            "walking the field to see why."
        )
    elif relative >= -0.5:
        status = CropStatus.BEHIND
        explanation = (
            "Your crop is noticeably behind where it should be. Common "
            "causes at this stage are water shortage, low nitrogen, or a "
            "pest problem."
        )
    else:
        status = CropStatus.SEVERELY_BEHIND
        explanation = (
            "Your crop is far behind what is normal for this stage. This "
            "needs looking at soon."
        )

    # Patchiness changes the advice, so it is called out separately: a
    # uniformly thin crop and a patchy one have different causes and
    # different fixes.
    if uniformity is not None and uniformity < 0.7 and status != CropStatus.AHEAD:
        explanation += (
            " The field is also patchy rather than evenly affected, which "
            "usually points to a specific cause you can find by walking it — "
            "a blocked water channel, a salty patch, or a pest focus."
        )

    # A falling trend while the canopy should still be expanding is the
    # earliest actionable remote signal there is.
    if (
        trend_per_day is not None
        and trend_per_day < -0.002
        and stage in (GrowthStage.DEVELOPMENT, GrowthStage.MID_SEASON)
    ):
        explanation += (
            " Greenness has also been falling over recent weeks, when it "
            "should still be rising. Check water and nitrogen first."
        )

    return CanopyAssessment(
        ndvi, observed, expected, status, days_after_sowing, stage,
        uniformity, trend_per_day, explanation,
    )


# --------------------------------------------------------------------------
# Emergence detection
# --------------------------------------------------------------------------

# NDVI at which a field has visibly greened up. Below this the signal is
# dominated by soil; above it there is a crop establishing.
GREENUP_NDVI = 0.28


def detect_emergence(
    observations: list[tuple["date", float]],
    threshold: float = GREENUP_NDVI,
) -> "date | None":
    """Estimate when the current crop emerged, from an NDVI time series.

    Why this exists
    ---------------
    Every stage-based judgement in this module depends on the sowing date,
    and sowing dates come from farmers recalling them weeks later, often in
    a season rather than a date ("just after the rains came"). A date that is
    three weeks out turns a healthy crop into a "severely behind" alarm,
    which is both wrong and exactly the kind of false alarm that teaches
    people to ignore the tool.

    The satellite record settles it independently. A field that was bare in
    late June and green by mid-July was sown in early July, whatever anyone
    remembers.

    Method: find the last sustained rise through the green-up threshold, and
    return the date of the crossing. The *last* crossing rather than the
    first, because a season may contain a previous crop's decline followed by
    this crop's establishment -- taking the first would date the wrong crop.
    """
    if len(observations) < 3:
        return None

    ordered = sorted(observations, key=lambda o: o[0])

    crossing = None
    for i in range(1, len(ordered)):
        prev_day, prev_ndvi = ordered[i - 1]
        day, ndvi = ordered[i]
        if prev_ndvi < threshold <= ndvi:
            # Require the rise to persist, so a single bright observation or
            # an imperfectly masked cloud edge does not register as a crop.
            later = [v for _, v in ordered[i:]]
            if sum(1 for v in later if v >= threshold) >= max(1, len(later) // 2):
                # Linear interpolation between the bracketing passes; Sentinel-2
                # revisits every ~5 days, so the crossing rarely lands on one.
                span_days = (day - prev_day).days
                if span_days > 0 and ndvi > prev_ndvi:
                    fraction = (threshold - prev_ndvi) / (ndvi - prev_ndvi)
                    from datetime import timedelta
                    crossing = prev_day + timedelta(days=round(span_days * fraction))
                else:
                    crossing = day
    return crossing


def reconcile_sowing_date(
    stated_sowing: "date",
    observations: list[tuple["date", float]],
    typical_days_to_greenup: int = 18,
) -> dict:
    """Cross-check a farmer's stated sowing date against the satellite record.

    Returns the date that should actually be used, plus whether the two
    disagree enough to matter. Emergence to visible green-up takes roughly
    two to three weeks for most field crops, so the implied sowing date is
    the green-up crossing minus that lag.

    The satellite is treated as the better witness when they disagree by more
    than a fortnight, but the disagreement is always surfaced rather than
    silently overriding what the farmer said -- they may have replanted after
    a failed stand, which is exactly the kind of thing the record cannot see
    but they know.
    """
    from datetime import timedelta

    emergence = detect_emergence(observations)
    if emergence is None:
        return {
            "sowing_date": stated_sowing,
            "source": "farmer",
            "disagreement_days": None,
            "note": None,
        }

    implied = emergence - timedelta(days=typical_days_to_greenup)
    delta = (implied - stated_sowing).days

    if abs(delta) <= 14:
        return {
            "sowing_date": stated_sowing,
            "source": "farmer_confirmed_by_satellite",
            "disagreement_days": delta,
            "note": None,
        }

    later = delta > 0
    return {
        "sowing_date": implied,
        "source": "satellite",
        "disagreement_days": delta,
        "note": (
            f"The satellite record shows this field greened up around "
            f"{emergence.isoformat()}, which suggests sowing around "
            f"{implied.isoformat()} — about {abs(delta)} days "
            f"{'later' if later else 'earlier'} than the date given. "
            f"Assessment uses the satellite date. If the field was resown "
            f"after a failed stand, say so and the original date will be used."
        ),
    }
