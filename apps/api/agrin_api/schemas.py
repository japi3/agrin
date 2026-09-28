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
        "name": "remember_about_my_farm",
        "description": (
            "Record durable facts the farmer states about their own land, so "
            "the next conversation does not start from nothing.\n\n"
            "Call this whenever a farmer volunteers something lasting: how "
            "big the holding is, what is planted and roughly when, when they "
            "last watered and for how many hours, what the soil is like in "
            "their own words, where their water comes from.\n\n"
            "Call it in passing, as part of answering. Do NOT interrogate "
            "them to fill fields, do not ask for details they have not "
            "offered, and do not read the saved list back to them. A "
            "conversation that turns into a form is the thing this interface "
            "exists to avoid.\n\n"
            "Acreage is recorded in acres, as farmers state it. Sowing dates "
            "may be approximate — 'just after the rains' is worth recording "
            "as a best-guess date, since a rough date beats none.\n\n"
            "A farmer's account of their own soil is valuable even where it "
            "disagrees with the soil map: they have dug that field. Record "
            "it and let both stand."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "area_acres": {"type": "number", "description": "Holding size in acres."},
                "field_name": {"type": "string", "description": "What they call this field."},
                "crops": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Crop keys currently in the ground, e.g. "
                        "[\"maize_grain\", \"rice_paddy\"]. Pass ALL of them "
                        "in one call — a holding often carries two or three "
                        "crops at once."
                    ),
                },
                "crop": {
                    "type": "string",
                    "description": "A single crop key. Prefer `crops` when there are several.",
                },
                "sowing_date": {"type": "string", "description": "YYYY-MM-DD, approximate is fine."},
                "irrigated_on": {"type": "string", "description": "YYYY-MM-DD they last watered."},
                "hours_pumped": {
                    "type": "number",
                    "description": "Hours of pumping — how farmers usually measure irrigation.",
                },
                "irrigation_method": {
                    "type": "string",
                    "description": "flood, furrow, drip, sprinkler.",
                },
                "soil_observation": {
                    "type": "string",
                    "description": "Their own description of the soil, in their words.",
                },
                "water_source": {
                    "type": "string",
                    "description": "borewell, canal, tubewell, rain-fed, pond.",
                },
                "general_note": {
                    "type": "string",
                    "description": "Anything else lasting and worth remembering.",
                },
                "field_is_at_named_place": {
                    "type": "boolean",
                    "description": (
                        "True when the farmer says their field is at the place "
                        "just looked up with find_place, and it differs from the "
                        "saved field. Moves the field there. Coordinates come "
                        "from the lookup automatically."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_my_farm",
        "description": (
            "Everything on record about this farmer's land: size, which "
            "crops are growing and at what stage, when they last watered, "
            "what they have told us about the soil, and what is still "
            "unknown.\n\n"
            "Use this at the start of a returning conversation to ground "
            "yourself before answering, and whenever the farmer asks about "
            "their farm generally. It costs nothing and it is what lets you "
            "avoid asking for the third time what they already told you.\n\n"
            "The result separates what the FARMER said from what the MODELS "
            "computed. Keep that distinction when you speak: 'you told me the "
            "soil is sandy' is a different claim from 'the soil map says clay "
            "loam', and where they disagree the farmer is usually right about "
            "their own field."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "find_place",
        "description": (
            "Turn a place name into coordinates: a village, town, tehsil or "
            "district in India.\n\n"
            "Use this the moment a farmer names where they are. Every other "
            "tool needs latitude and longitude, and farmers give place names "
            "— 'Dharamgarh Bohli, Jind, Haryana', not decimal degrees. Call "
            "this first, then pass the coordinates it returns to the other "
            "tools in the same turn.\n\n"
            "Never ask a farmer for latitude and longitude. If the name is "
            "ambiguous the result says so; ask which district they meant "
            "rather than guessing, because village names repeat across India "
            "and the wrong match gives confidently wrong advice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Place name as the farmer said it, including district "
                        "and state when given."
                    ),
                },
            },
            "required": ["query"],
        },
    },
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
                        "Crop key. One of: rice_paddy, wheat_rabi, "
                        "wheat_winter, wheat_spring, maize_grain, soybean, "
                        "cotton, sugarcane, chickpea, mustard, groundnut, "
                        "pearl_millet, sorghum, potato, sunflower, barley.\n"
                        "For wheat in India, Pakistan, Bangladesh or Nepal "
                        "use wheat_rabi: the South Asian rabi crop runs about "
                        "150 days, materially longer than the generic spring "
                        "wheat entry, and using the wrong one makes the model "
                        "think the crop is senescing while it is still "
                        "filling grain."
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
            "unsuitable crops; it does not predict yield.\n\n"
            "Pass sowing_month whenever the farmer is asking what to sow "
            "now, next, or after the current crop. Without it the answer "
            "covers the whole year, which will list crops belonging to a "
            "different season than the one they are asking about."
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
                "sowing_month": {
                    "type": "integer",
                    "description": (
                        "Month number 1-12 the farmer would sow in. Set it "
                        "for 'what should I sow now' or 'what comes after "
                        "this crop' -- use the month they would actually "
                        "plant, which for a question about the next season "
                        "is the start of that season, not today. Omit only "
                        "when the question really is about the whole year."
                    ),
                },
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "estimate_crop_value",
        "description": (
            "How much the standing crop is likely to yield, and what that is "
            "worth at today's mandi rate.\n\n"
            "Use for 'what will I get from this crop', 'is it worth "
            "harvesting', 'will I make a profit', 'how much will I earn'.\n\n"
            "Yield comes from this season's own water balance (FAO-33 Ky "
            "applied to the farmer's normal yield), so it reflects the "
            "stress this crop actually took. Rupee figures are today's rate "
            "for this much crop.\n\n"
            "It does NOT forecast prices, and you must not either. If asked "
            "what prices will be at harvest, say plainly that nobody can "
            "know, and give what is knowable instead: today's rate, the "
            "support price floor, and that prices usually fall when arrivals "
            "peak at harvest.\n\n"
            "Requires the farmer's usual yield per acre. If you do not have "
            "it, ask -- their own figure is better than any average, and "
            "without it the tool abstains. Pass cost_per_acre only if they "
            "have told you their costs; margin is never estimated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_LOCATION_PROPS,
                "crop": {"type": "string", "description": "Crop key."},
                "sowing_date": {
                    "type": "string",
                    "description": "ISO date the crop was sown.",
                },
                "acres": {
                    "type": "number",
                    "description": "Area of the field in acres.",
                },
                "usual_yield_per_acre": {
                    "type": "number",
                    "description": (
                        "Quintals per acre the farmer normally gets in a "
                        "good year. Ask them; do not guess."
                    ),
                },
                "cost_per_acre": {
                    "type": "number",
                    "description": (
                        "Rupees per acre spent this season, only if the "
                        "farmer stated it. Omit otherwise."
                    ),
                },
            },
            "required": ["latitude", "longitude", "crop", "sowing_date", "acres"],
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
        "name": "find_government_schemes",
        "description": (
            "Find Indian government schemes relevant to a farmer's "
            "situation: income support, crop insurance, credit, soil "
            "testing, micro-irrigation subsidy, and online mandi selling.\n\n"
            "Use this whenever money, loss, risk, subsidy, insurance, a soil "
            "test or credit comes up — and proactively when a farmer "
            "describes crop damage, water shortage or trouble affording "
            "inputs, because most farmers do not know which schemes exist.\n\n"
            "This returns navigation, NOT an eligibility ruling. Never tell "
            "a farmer they qualify or do not qualify: that is decided by "
            "their state agriculture department. Give them the screening "
            "questions to check themselves, the common disqualifiers, and "
            "the official portal and helpline.\n\n"
            "Never invent a scheme name, an amount, an office address or a "
            "helpline number. If a scheme is not in the result, say you do "
            "not have it and point to myscheme.gov.in. If a record is marked "
            "may_be_out_of_date, say so."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "concern": {
                    "type": "string",
                    "description": (
                        "What the farmer is dealing with, in their words: "
                        "'crop damaged by hail', 'cannot afford fertiliser', "
                        "'borewell running dry', 'want a soil test'."
                    ),
                },
                "owns_land": {
                    "type": "boolean",
                    "description": (
                        "Whether the farmer owns land in their own name, if "
                        "known. Do not ask directly just to fill this in."
                    ),
                },
                "has_water_source": {
                    "type": "boolean",
                    "description": "Whether an assured water source exists, if known.",
                },
                "scheme_key": {
                    "type": "string",
                    "description": (
                        "Look up one scheme by key: pm_kisan, pmfby, "
                        "soil_health_card, kcc, pmksy, enam."
                    ),
                },
            },
            "required": [],
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
    {
        "name": "look_up_official_guidance",
        "description": (
            "Search India's published agricultural advisory material and "
            "return the actual passages, with their source.\n\n"
            "Use this for anything written down rather than computed: "
            "varieties suited to a region, seed treatment, spacing and seed "
            "rate, nursery practice, pest and disease management, storage, "
            "post-harvest handling, scheme eligibility and paperwork, "
            "livestock and fisheries practice.\n\n"
            "Use it whenever you would otherwise be recalling a specific "
            "figure -- a dose, a spacing, a variety name, a waiting period. "
            "Those are exactly the details that sound right when invented, "
            "and a farmer cannot check them.\n\n"
            "Do NOT use it for anything the computed tools cover: water, "
            "irrigation timing, soil properties at this field, weather, "
            "carbon, crop health from satellite, or prices. Those measure "
            "this field; this only reports what is published in general.\n\n"
            "State only what the returned passages say, and name the source. "
            "If the tool abstains, say you have no published source and do "
            "not fill the gap from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "What to look up, as a full question. Include the "
                        "crop and the topic. Searching works across "
                        "languages, but an English question matches the "
                        "library best."
                    ),
                },
                "passages": {
                    "type": "integer",
                    "description": "How many passages to return. Default 4.",
                },
            },
            "required": ["question"],
        },
    },
]


def tool_names() -> list[str]:
    return [t["name"] for t in TOOL_DEFINITIONS]
