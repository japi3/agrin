"""
Tool definitions exposed to the model.

Descriptions here are written for the model, not for a developer. Each one
states what the tool does, when to reach for it, and — importantly — what it
will refuse to do. Telling the model up front that a tool abstains on
uncalibrated crops prevents it from trying to talk its way around the refusal.

Location is a parameter on every field-specific tool rather than ambient
state. That is deliberate: it keeps the model's reasoning explicit and
auditable, and it means a conversation that moves between two of a farmer's
plots cannot silently apply one plot's soil to the other.
"""

from __future__ import annotations

from typing import Any

_LOCATION_PROPS = {
    "latitude": {
        "type": "number",
        "description": "Latitude of the field in decimal degrees, WGS84.",
    },
    "longitude": {
        "type": "number",
        "description": "Longitude of the field in decimal degrees, WGS84.",
    },
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_soil_profile",
        "description": (
            "Look up soil properties for a field: texture (sand/silt/clay), "
            "USDA class, pH, organic carbon, nitrogen, cation exchange "
            "capacity, bulk density, and how much water the soil can hold.\n\n"
            "Use this whenever soil comes up — fertility questions, what to "
            "plant, why a crop is struggling, whether to lime.\n\n"
            "Data is ISRIC SoilGrids at 250 m resolution. It is a model "
            "prediction, not a soil test of this exact field, and the result "
            "reports its own confidence. If the point falls on a town or "
            "water body the tool searches nearby and tells you how far it "
            "moved. If no soil is mapped within 20 km it abstains."
        ),
        "input_schema": {
            "type": "object",
            "properties": dict(_LOCATION_PROPS),
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_weather",
        "description": (
            "Recent observed weather and a forecast of up to 16 days for a "
            "field, including daily maximum and minimum temperature, "
            "rainfall, and reference evapotranspiration computed with FAO-56 "
            "Penman-Monteith.\n\n"
            "Use this for any question about rain, heat, cold, or when to do "
            "a field operation. Also use it before advising on spraying, "
            "sowing, or harvest timing, since all three depend on the "
            "coming weather."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "days_ahead": {
                    "type": "integer",
                    "description": "Forecast days to return, 1 to 16. Default 14.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_irrigation_advice",
        "description": (
            "Decide whether a field needs irrigating now, how many days until "
            "the crop becomes water-stressed, and how much water to apply — "
            "both the net depth the crop needs and the gross depth the farmer "
            "must actually pump after application losses.\n\n"
            "This runs a daily FAO-56 root-zone water balance over real "
            "observed and forecast weather and the field's own soil. It "
            "accounts for forecast rain, so it will correctly tell a farmer "
            "to wait when rain is coming.\n\n"
            "Requires the crop and roughly when it was sown. If you do not "
            "know the sowing date, ask for it in ordinary terms ('roughly "
            "when did you sow?') rather than demanding a calendar date.\n\n"
            "Abstains if the crop is not in the calibrated set, rather than "
            "producing a guess."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "crop": {
                    "type": "string",
                    "description": (
                        "Crop key. One of: rice_paddy, wheat_winter, "
                        "wheat_spring, maize_grain, soybean, cotton, "
                        "sugarcane, chickpea, mustard, groundnut, "
                        "pearl_millet, sorghum, potato, sunflower, barley."
                    ),
                },
                "sowing_date": {
                    "type": "string",
                    "description": "Sowing date as YYYY-MM-DD.",
                },
                "irrigation_efficiency": {
                    "type": "number",
                    "description": (
                        "Fraction of pumped water reaching the root zone. "
                        "0.5 unlined flood, 0.75 well-managed surface "
                        "(default), 0.9 drip."
                    ),
                },
            },
            "required": ["latitude", "longitude", "crop", "sowing_date"],
        },
    },
    {
        "name": "assess_crop_suitability",
        "description": (
            "Score which crops suit a field, using its soil pH, texture, "
            "available growing degree-days, and the rainfall that actually "
            "falls during each crop's own growing season in that hemisphere.\n\n"
            "Use this for 'what should I plant', crop diversification, and "
            "whether a crop the farmer is considering will work.\n\n"
            "Separates constraints a farmer can fix with an input (acidity, "
            "correctable with a stated tonnage of lime) from hard climate "
            "limits (insufficient heat to reach maturity). It screens out "
            "unsuitable crops; it does not predict yield."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "candidate_crops": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional subset of crop keys to assess. Omit to "
                        "assess all calibrated crops."
                    ),
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_crop_health",
        "description": (
            "Read the crop's actual condition from Sentinel-2 satellite "
            "imagery: greenness (NDVI) over the last four months, how evenly "
            "the field is growing, and whether greenness is rising or "
            "falling.\n\n"
            "When the crop and sowing date are known it also reports whether "
            "the canopy is ahead of, on track with, or behind what a healthy "
            "crop should have reached at this growth stage — which is what "
            "makes the number mean anything.\n\n"
            "Use this for 'how is my crop doing', suspected stress, patchy "
            "growth, or to check a problem the farmer has noticed. Also "
            "useful alongside a photo diagnosis: patchiness visible from "
            "space points to a cause the farmer can walk to.\n\n"
            "Images are cloud-screened. During heavy monsoon there may be no "
            "usable image for weeks, and the tool says so rather than "
            "reporting stale data as current."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "crop": {
                    "type": "string",
                    "description": "Crop key, if known. Enables interpretation.",
                },
                "sowing_date": {
                    "type": "string",
                    "description": "Sowing date as YYYY-MM-DD, if known.",
                },
                "field_size_m": {
                    "type": "number",
                    "description": (
                        "Approximate width of the field in metres, default "
                        "200. Sets the area sampled around the point."
                    ),
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "get_mandi_prices",
        "description": (
            "Today's prices for a crop at Indian regulated markets (APMC "
            "mandis), from the government Agmarknet feed. Returns the local "
            "rate, the best rate in range, and how far apart markets are.\n\n"
            "Use this for 'what is the rate', 'where should I sell', whether "
            "to hold or sell, and when comparing which crop is worth growing "
            "— yield advice without price answers half the question.\n\n"
            "Prices are rupees per QUINTAL (100 kg). Always say the unit; a "
            "farmer hearing a per-kg figure when it is per-quintal is out by "
            "a hundredfold.\n\n"
            "Agmarknet lists only markets that actually traded that day, so "
            "an out-of-season crop legitimately has no local rate. These are "
            "spot prices, not forecasts — never predict where prices will go."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "crop": {
                    "type": "string",
                    "description": "Crop key, e.g. rice_paddy, wheat_spring, cotton.",
                },
                "latitude": {"type": "number", "description": "Field latitude."},
                "longitude": {"type": "number", "description": "Field longitude."},
                "state": {
                    "type": "string",
                    "description": "Indian state name, if known. Otherwise inferred.",
                },
            },
            "required": ["crop"],
        },
    },
    {
        "name": "compare_regenerative_practices",
        "description": (
            "Project soil organic carbon over time under four managements — "
            "residue burned or removed, residue retained, residue plus a "
            "cover crop, and residue plus cover crop plus farmyard manure — "
            "using the RothC-26.3 model with the field's own soil and a "
            "20-year local climate record.\n\n"
            "Use this for questions about soil health, residue burning, "
            "cover cropping, manure, regenerative practice, and carbon "
            "credits. Returns tonnes of CO2 equivalent per hectare, which is "
            "the unit carbon registries transact in.\n\n"
            "RothC changes slowly by design. Expect gains of a fraction of a "
            "tonne of carbon per hectare per year, not dramatic jumps. Report "
            "what it returns; do not inflate it to sound more compelling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "years": {
                    "type": "integer",
                    "description": "Years to project. Default 20.",
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
]


def tool_names() -> list[str]:
    return [t["name"] for t in TOOL_DEFINITIONS]
