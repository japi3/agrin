"""
Crop disease diagnosis from a photograph, using Gemini multimodal vision.

The design problem
------------------
The obvious build is: send the photo to a vision model, ask "what disease is
this?", print the answer. It demos well and it is quietly dangerous. Foliar
symptoms are genuinely ambiguous -- nutrient deficiency, herbicide drift,
mite damage, sun scorch and half a dozen pathogens all produce chlorotic
lesions -- and a vision model asked to name one disease will confidently name
one. The farmer then buys a fungicide for a potassium deficiency.

Three things are done differently here.

**1. The diagnosis is conditioned on what the weather permitted.**
Before the image is examined, `packages/agronomy/disease.py` computes
infection pressure for every pathogen of that crop from three weeks of
hourly weather. Late blight is not a candidate in a fortnight of 38 C dry
heat, whatever the lesion looks like. That prior is supplied to the model as
evidence, not as an instruction to obey -- a photograph showing unmistakable
sporulation should still win.

**2. The output is a differential, not a verdict.**
The model returns ranked candidates, each with a *distinguishing check the
farmer can perform themselves*: turn the leaf over, look for white fuzz;
split the stem, look for browning. This converts an unfalsifiable claim into
something the farmer can confirm in thirty seconds, standing in the field.
It also degrades honestly -- an uncertain diagnosis reads as uncertain.

**3. It refuses bad photographs.**
Blurry, too distant, wrong subject, or nothing visibly wrong: the model is
required to say so and ask for a specific better photo. Guessing from an
unusable image is the failure mode most likely to cause real loss.

On chemical recommendations
---------------------------
The model names the active-ingredient class where one is genuinely
warranted, and never a dose, a spray interval, or a brand. Dosage depends on
formulation concentration, equipment, crop stage and local resistance status;
it is printed on the label and set by state agriculture departments. An LLM
inventing "spray 2 ml per litre" is both unsafe and, in India, offering
advice it has no standing to give. The prompt is explicit about this and the
schema has no field for a dose.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from google.genai import types

_ROOT = Path(__file__).resolve().parents[3]
for pkg in ("packages/agronomy", "packages/geo"):
    p = str(_ROOT / pkg)
    if p not in sys.path:
        sys.path.insert(0, p)

from agronomy.crops import CROPS  # noqa: E402
from agronomy.disease import assess_all_for_crop  # noqa: E402
from geo.weather import fetch_forecast  # noqa: E402

from . import llm  # noqa: E402

# Accepted image types. Phone cameras produce JPEG or HEIC; HEIC is converted
# client-side because Gemini does not accept it directly.
ACCEPTED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


DIAGNOSIS_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["image_usable", "candidates", "farmer_summary"],
    properties={
        "image_usable": types.Schema(
            type=types.Type.BOOLEAN,
            description=(
                "False if the photo is too blurry, too far away, too dark, "
                "shows no plant, or shows no visible problem."
            ),
        ),
        "image_problem": types.Schema(
            type=types.Type.STRING,
            description=(
                "If unusable, what is wrong with the photo and exactly what "
                "to photograph instead. Written to be read aloud."
            ),
        ),
        "affected_part": types.Schema(
            type=types.Type.STRING,
            description="leaf, stem, sheath, panicle, fruit, root, or whole plant",
        ),
        "candidates": types.Schema(
            type=types.Type.ARRAY,
            description=(
                "Ranked possible causes, most likely first. Include at least "
                "two whenever the image is usable; a single candidate implies "
                "a certainty foliar symptoms rarely support."
            ),
            items=types.Schema(
                type=types.Type.OBJECT,
                required=["name", "confidence", "why", "farmer_check"],
                properties={
                    "name": types.Schema(
                        type=types.Type.STRING,
                        description="Common name of the disease, pest or disorder.",
                    ),
                    "scientific_name": types.Schema(type=types.Type.STRING),
                    "category": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "fungal, bacterial, viral, pest, nutrient_deficiency, "
                            "chemical_damage, or abiotic_stress"
                        ),
                    ),
                    "confidence": types.Schema(
                        type=types.Type.STRING,
                        description="high, moderate, or low",
                    ),
                    "why": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "What in the image supports this, and whether the "
                            "recent weather made it possible."
                        ),
                    ),
                    "farmer_check": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "One concrete thing the farmer can do right now in "
                            "the field to confirm or rule this out. Must be "
                            "doable with bare hands and eyes."
                        ),
                    ),
                    "weather_consistent": types.Schema(
                        type=types.Type.BOOLEAN,
                        description=(
                            "Whether recent weather was favourable for this "
                            "cause, per the supplied infection-pressure data."
                        ),
                    ),
                },
            ),
        ),
        "immediate_actions": types.Schema(
            type=types.Type.ARRAY,
            description=(
                "Non-chemical steps to take today: roguing, drainage, stopping "
                "nitrogen, removing debris, adjusting irrigation. No doses."
            ),
            items=types.Schema(type=types.Type.STRING),
        ),
        "active_ingredient_class": types.Schema(
            type=types.Type.STRING,
            description=(
                "Chemical class only if genuinely warranted, e.g. "
                "'a triazole fungicide'. Never a dose, interval or brand. "
                "Empty if chemical control is not warranted yet."
            ),
        ),
        "urgency": types.Schema(
            type=types.Type.STRING,
            description="today, this_week, monitor, or no_action",
        ),
        "refer_to_expert": types.Schema(
            type=types.Type.BOOLEAN,
            description=(
                "True when the diagnosis is genuinely uncertain, the damage is "
                "severe, or a quarantine pest is possible."
            ),
        ),
        "farmer_summary": types.Schema(
            type=types.Type.STRING,
            description=(
                "Three to five short sentences for the farmer, in their "
                "language. Lead with what to do. Plain words, no jargon, no "
                "markdown -- this is read aloud."
            ),
        ),
    },
)


VISION_PROMPT = """\
You are diagnosing a crop problem from a photograph taken by a farmer.

Be honest about uncertainty. Foliar symptoms are ambiguous: nutrient
deficiency, herbicide drift, mite damage, sun scorch and several pathogens
all produce similar discoloured lesions. Give ranked possibilities with a
check the farmer can perform, not a single confident verdict.

If the photograph cannot support a diagnosis -- blurry, too far away, too
dark, not a plant, or nothing visibly wrong -- set image_usable to false and
say precisely what to photograph instead. Do not guess from an unusable
image. Ask for a close photograph of an affected leaf, in daylight, with the
underside shown.

Weight your candidates against the infection-pressure data supplied below.
It is computed from three weeks of hourly weather at this exact field using
published epidemiological models, and it tells you what was meteorologically
possible. A disease the weather ruled out is unlikely regardless of
appearance. But it is evidence, not an order: unmistakable visual signs
override it, and you should say so when they do.

Never state a dose, a spray concentration, an interval, or a product brand.
Name a chemical class only where control is genuinely warranted. Doses depend
on formulation, equipment and local resistance, they are on the label, and
they are set by the state agriculture department. Tell the farmer to follow
the label and confirm with their KVK or extension officer.

Prefer non-chemical action first where it is genuinely effective: roguing
infected plants, improving drainage, stopping nitrogen, widening spacing,
removing crop debris.

Write farmer_summary, why, farmer_check, immediate_actions and image_problem in {language_name}, in its native script, in short plain sentences, leading
with what to do today. It will be read aloud, so use no markdown, no bullet
characters and no technical vocabulary the farmer would not use.
"""


async def diagnose_crop_photo(
    image_bytes: bytes,
    mime_type: str,
    latitude: float | None = None,
    longitude: float | None = None,
    crop: str | None = None,
    sowing_date: str | None = None,
    farmer_note: str = "",
    language: str = "en",
    language_name: str = "English",
) -> dict[str, Any]:
    """Diagnose a crop photograph, conditioned on local infection pressure."""
    if mime_type not in ACCEPTED_MIME:
        return {
            "ok": False,
            "abstain_reason": (
                f"Image type {mime_type} is not supported. Please send a JPEG "
                f"or PNG photo."
            ),
        }
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {
            "ok": False,
            "abstain_reason": "That photo is too large. Please send a smaller one.",
        }

    # --- Infection pressure -------------------------------------------
    pressure: list[dict] = []
    pressure_note = ""
    weather_evidence: dict[str, Any] = {}

    if latitude is not None and longitude is not None and crop in CROPS:
        try:
            series = await fetch_forecast(
                latitude, longitude, days_ahead=1, past_days=21,
                include_hourly=True,
            )
            days = [
                {
                    "date": d.day, "t_min": d.t_min, "t_max": d.t_max,
                    "t_mean": d.t_mean, "hourly_rh": d.hourly_rh,
                }
                for d in series.days if d.hourly_rh and d.t_mean is not None
            ]
            if days:
                risks = assess_all_for_crop(crop, days)
                pressure = [r.to_dict() for r in risks]
                weather_evidence = series.evidence()
                lines = [
                    f"- {r['name']}: {r['risk_level'].upper()} "
                    f"({r['favourable_days']} of {r['days_assessed']} recent "
                    f"days had weather suitable for infection)"
                    for r in pressure
                ]
                pressure_note = (
                    "Infection pressure at this field over the last three "
                    "weeks, from published epidemiological models driven by "
                    "hourly weather:\n" + "\n".join(lines)
                )
        except Exception as exc:  # noqa: BLE001
            # Diagnosis still proceeds without the prior; it is an
            # enhancement, not a prerequisite. But say so, so the model does
            # not imply it checked the weather when it could not.
            pressure_note = (
                f"Local infection-pressure data could not be retrieved "
                f"({type(exc).__name__}). Judge from the image alone and say "
                f"that recent weather could not be checked."
            )

    # --- Context -------------------------------------------------------
    context_lines = []
    if crop in CROPS:
        context_lines.append(f"Crop: {CROPS[crop].name_en}")
    if sowing_date:
        try:
            das = (date.today() - date.fromisoformat(sowing_date)).days
            context_lines.append(f"Sown {das} days ago")
            if crop in CROPS:
                from agronomy.crops import crop_coefficient
                _, stage = crop_coefficient(CROPS[crop], das)
                context_lines.append(f"Growth stage: {stage.value.replace('_', ' ')}")
        except ValueError:
            pass
    if latitude is not None:
        context_lines.append(f"Field at {latitude:.3f}, {longitude:.3f}")
    if farmer_note:
        context_lines.append(f"The farmer says: {farmer_note}")

    prompt = VISION_PROMPT.format(language_name=language_name)
    if context_lines:
        prompt += "\n\nField context:\n" + "\n".join(f"- {c}" for c in context_lines)
    if pressure_note:
        prompt += "\n\n" + pressure_note

    # --- Call Gemini ---------------------------------------------------
    try:
        client = llm.build_client()
    except llm.LLMNotConfigured as exc:
        return {"ok": False, "abstain_reason": str(exc)}

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                types.Part(text=prompt),
            ],
        )
    ]
    config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=DIAGNOSIS_SCHEMA,
        max_output_tokens=2048,
    )

    last_error: Exception | None = None
    for candidate_model in llm.model_candidates(llm.VISION_MODEL):
        try:
            response = await client.aio.models.generate_content(
                model=candidate_model, contents=contents, config=config
            )
            parsed = response.parsed
            if parsed is None:
                import json
                parsed = json.loads(response.text)

            return {
                "ok": True,
                **parsed,
                "model_used": candidate_model,
                "infection_pressure": pressure,
                "evidence": {
                    "vision_model": candidate_model,
                    "method": (
                        "Gemini multimodal diagnosis, conditioned on "
                        "weather-driven infection pressure computed with "
                        "published epidemiological models (Smith 1956; "
                        "Analytis 1977; Magarey et al. 2005)."
                    ),
                    "weather": weather_evidence,
                    "limitations": [
                        "A photograph cannot distinguish some diseases from "
                        "nutrient or chemical damage; confirm with the "
                        "suggested field checks",
                        "No dose or product is recommended: follow the label "
                        "and your state agriculture department's advice",
                        "Soil-borne and root problems are frequently invisible "
                        "in a leaf photograph",
                    ],
                },
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if llm.is_retryable(exc):
                continue
            break

    return {
        "ok": False,
        "abstain_reason": (
            f"The diagnosis service is unavailable right now "
            f"({type(last_error).__name__}). Please try again shortly."
        ),
    }
