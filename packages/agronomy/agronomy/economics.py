"""
What the crop in the ground is worth, at today's prices.

Deliberately not a price forecast. Everything else in this platform traces
to a published model or a live measurement, and a farmer deciding when to
sell on an invented forecast can lose a season's income. So this reports
three things that are true right now and checkable:

  - how much crop there is likely to be, from the season's actual water
    balance;
  - what a quintal is fetching today, and the spread between markets;
  - the announced minimum support price, which is a floor rather than a
    prediction and the single most plannable number a farmer has.

What prices will do between now and harvest is not here, and should not be.

Yield comes from FAO-33 (Doorenbos & Kassam 1979), the water-production
function the water balance already computes a loss fraction with:

    (1 - Ya/Ym) = Ky * (1 - ETa/ETc)

Ky is the crop's yield response factor, already carried on every crop. What
the loss fraction needs is something to be a fraction *of*: an attainable
yield for this field in a good year. The farmer's own figure is preferred
over any district statistic, because they know their land and a district
average silently mixes irrigated and rainfed, good soil and bad.
"""

from __future__ import annotations

from dataclasses import dataclass

# How wide to draw the band around a yield estimate.
#
# The Ky relation is a linear approximation to a response that is not linear
# at the extremes, the attainable yield it scales is itself remembered rather
# than measured, and nothing here knows about pests, hail or a bad patch of
# the field. A single number would imply a precision that does not exist.
# Fifteen per cent is wide enough to be honest and narrow enough to decide
# with; the band is always shown, never the midpoint alone.
YIELD_BAND = 0.15


@dataclass
class YieldEstimate:
    """A range, never a point."""
    attainable: float
    relative_loss: float
    low: float
    high: float
    basis: str
    unit: str = "quintal per acre"

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0

    def as_dict(self) -> dict:
        return {
            "low": round(self.low, 1),
            "high": round(self.high, 1),
            "unit": self.unit,
            "attainable_in_a_good_year": round(self.attainable, 1),
            "lost_to_water_stress_percent": round(self.relative_loss * 100, 1),
            "basis": self.basis,
        }


def estimate_yield(
    attainable: float,
    relative_loss: float,
    basis: str,
    band: float = YIELD_BAND,
) -> YieldEstimate:
    """Apply a water-stress loss fraction to an attainable yield.

    `relative_loss` is what WaterBalance.estimated_yield_loss returns: the
    FAO-33 fraction of yield given up to water deficit over the season.
    """
    if attainable <= 0:
        raise ValueError("attainable yield must be positive")
    loss = min(max(relative_loss, 0.0), 1.0)
    expected = attainable * (1.0 - loss)
    return YieldEstimate(
        attainable=attainable,
        relative_loss=loss,
        low=max(0.0, expected * (1.0 - band)),
        high=expected * (1.0 + band),
        basis=basis,
    )


@dataclass
class Money:
    """What the crop is worth at today's rates. Rupees."""
    quintals_low: float
    quintals_high: float
    price_today: float | None
    price_market: str | None
    price_date: str | None
    revenue_low: float | None
    revenue_high: float | None
    msp: float | None
    msp_year: str | None
    best_market: str | None = None
    best_market_price: float | None = None
    extra_if_sold_there: float | None = None
    cost: float | None = None
    margin_low: float | None = None
    margin_high: float | None = None

    def as_dict(self) -> dict:
        out = {
            "quintals": [round(self.quintals_low, 1), round(self.quintals_high, 1)],
            "price_today": self.price_today,
            "price_market": self.price_market,
            "price_date": self.price_date,
            "revenue": (
                [round(self.revenue_low), round(self.revenue_high)]
                if self.revenue_low is not None else None
            ),
            "msp": self.msp,
            "msp_year": self.msp_year,
            "above_msp": (
                None if (self.msp is None or self.price_today is None)
                else self.price_today >= self.msp
            ),
            "is_forecast": False,
        }
        if self.best_market and self.extra_if_sold_there:
            out["better_market"] = {
                "market": self.best_market,
                "price": self.best_market_price,
                "extra_rupees": round(self.extra_if_sold_there),
            }
        if self.cost is not None:
            out["cost"] = round(self.cost)
            out["margin"] = [round(self.margin_low), round(self.margin_high)]
        return out


def value_at_todays_price(
    estimate: YieldEstimate,
    acres: float,
    price_today: float | None,
    price_market: str | None = None,
    price_date: str | None = None,
    msp: float | None = None,
    msp_year: str | None = None,
    best_market: str | None = None,
    best_market_price: float | None = None,
    cost_per_acre: float | None = None,
) -> Money:
    """Revenue for a whole field at a price that is quoted, not predicted.

    Every rupee figure here is "if you sold today at this rate". Nothing
    estimates what the rate will be at harvest.
    """
    quintals_low = estimate.low * acres
    quintals_high = estimate.high * acres

    revenue_low = revenue_high = None
    if price_today is not None:
        revenue_low = quintals_low * price_today
        revenue_high = quintals_high * price_today

    # The spread between markets is the actionable part of a price report: a
    # farmer who learns a mandi two districts away pays appreciably more can
    # weigh the transport against the gain. Worth stating in rupees for this
    # much crop rather than as a difference per quintal, which is easy to
    # dismiss as small.
    extra = None
    if (best_market_price is not None and price_today is not None
            and best_market_price > price_today):
        extra = (best_market_price - price_today) * quintals_low

    cost = margin_low = margin_high = None
    if cost_per_acre is not None and revenue_low is not None:
        cost = cost_per_acre * acres
        margin_low = revenue_low - cost
        margin_high = revenue_high - cost

    return Money(
        quintals_low=quintals_low,
        quintals_high=quintals_high,
        price_today=price_today,
        price_market=price_market,
        price_date=price_date,
        revenue_low=revenue_low,
        revenue_high=revenue_high,
        msp=msp,
        msp_year=msp_year,
        best_market=best_market,
        best_market_price=best_market_price,
        extra_if_sold_there=extra,
        cost=cost,
        margin_low=margin_low,
        margin_high=margin_high,
    )


# --------------------------------------------------------------------------
# Minimum support price
# --------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

_MSP_FILE = _Path(__file__).parent / "data" / "msp.json"
_msp_cache: dict | None = None


def _msp_table() -> dict:
    global _msp_cache
    if _msp_cache is None:
        try:
            _msp_cache = _json.loads(_MSP_FILE.read_text())
        except Exception:  # noqa: BLE001
            # No table is a normal state, not an error: the feature simply
            # stops mentioning MSP. Better than a stale or wrong floor price.
            _msp_cache = {"seasons": {}}
    return _msp_cache


def msp_for(crop_key: str) -> tuple[float | None, str | None]:
    """The announced floor price for a crop, and which marketing year it is.

    Returns (None, None) for anything outside the MSP list -- fruit,
    vegetables, and most of what a smallholder actually grows. Saying
    nothing is correct there; inventing a floor would be worse than silence.
    """
    table = _msp_table()
    for season in table.get("seasons", {}).values():
        crops = season.get("crops", {})
        if crop_key in crops:
            return float(crops[crop_key]), season.get("marketing_year")
    return None, None


def msp_is_verified() -> bool:
    """Whether a human has checked these figures against CACP.

    Entered by hand from a source that changes every season, so the app
    should say they are unverified until someone confirms them.
    """
    return bool(_msp_table().get("verified_on"))
