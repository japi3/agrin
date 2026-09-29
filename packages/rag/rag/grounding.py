"""
Checking that a quoted answer only says what the source said.

Retrieval was supposed to make invented specifics impossible. It does not.
What it removes is the need to invent; what it adds is authority, and those
are not the same thing. Asked how to deworm a buffalo calf, the assistant
retrieved real ICAR passages saying Albendazole at 10 mg/kg, and then wrote
back a dosing schedule -- day 14, day 35, day 56, monthly until six months --
together with a second drug and its dose. None of that was in any passage.
It told the farmer the government advisory said so.

That is worse than the same answer with no citation, because the citation is
what makes it look checked. Someone can dose an animal on it.

Two rounds of prompt-writing did not stop it, and there is a reason to
expect that. The instruction competes with everything else the model is
trying to do -- be helpful, be complete, sound like it knows -- and it
competes afresh on every token. A check does not compete. It runs after the
answer exists and compares it against the passages, and its verdict does not
depend on the model having been persuaded.

So this module answers one narrow, decidable question: **does every quantity
in the answer appear in the passages it came from?**

Narrow on purpose. Prose cannot be verified this way -- paraphrase is
legitimate and a model may reasonably say "spray again after a fortnight"
where the source says "14 days". Quantities are different. They are the part
a farmer acts on, they are what an invented answer gets wrong, and they are
comparable without understanding the sentence around them. A dose that
appears nowhere in the source is a defect whatever the prose does.

The comparison is deliberately forgiving about form and strict about value.
"10mg/kg", "10 mg / kg" and "10 mg per kg" are the same quantity; 7.5 and 10
are not. Being forgiving about form is what keeps this from crying wolf on
every answer, and crying wolf is how a check like this gets switched off.
"""

from __future__ import annotations

import re

# A number and the unit attached to it. Units are the ones that appear in
# agricultural and veterinary advice: doses, rates, areas, intervals.
_UNIT = (
    r"%|mg\s*(?:/|per\s+)\s*kg|ml\s*(?:/|per\s+)\s*(?:kg|l|litre)|"
    r"mg|ml|gm|g|kg|litres?|l|"
    r"days?|weeks?|months?|years?|hours?|"
    r"cm|mm|m|acres?|ha|hectares?|quintals?|kgs?"
)
# The ordinal suffix is optional and discarded: an answer saying "the 14th
# day" and a source saying "14 days" are the same interval. Missing this let
# a fabricated schedule -- day 14, day 35, day 56 -- pass the check untouched
# on the first run of these tests.
_QUANTITY = re.compile(
    rf"(\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s*({_UNIT})\b", re.I)

# Units as a model writes them when it is being readable. The answer that
# prompted this module said "7.5 to 10 milligrams per kilogram" where the
# source said "10 mg/kg", so without this the invented lower bound was
# invisible.
_SPELLED = [
    (r"milligrams?\s+per\s+kilograms?", "mg/kg"),
    (r"millilitres?\s+per\s+(?:kilogram|kg|litre|l)\b", "ml/l"),
    (r"milligrams?", "mg"),
    (r"millilitres?|milliliters?", "ml"),
    (r"kilograms?", "kg"),
    (r"grams?", "g"),
    (r"litres?|liters?", "l"),
    (r"hectares?", "ha"),
    (r"centimetres?|centimeters?", "cm"),
    (r"millimetres?|millimeters?", "mm"),
]

# "7.5 to 10 mg/kg" states two quantities, and only the second one sits next
# to the unit. A range whose lower bound is invented reads as authoritative
# precision, so both ends are checked.
_RANGE = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:to|-|–|—|and)\s*(\d+(?:\.\d+)?)\s*({_UNIT})\b",
    re.I,
)

# Written-out intervals a model uses in place of a figure. "A fortnight" for
# "14 days" is a translation, not an invention, so these are normalised
# rather than flagged.
_WORDS = {
    "fortnight": ("14", "day"),
    "a week": ("7", "day"),
    "one week": ("7", "day"),
    "two weeks": ("14", "day"),
    "three weeks": ("21", "day"),
    "a month": ("1", "month"),
    "six months": ("6", "month"),
    "a year": ("1", "year"),
}

# Units that mean the same thing once the number is fixed, so that a source
# writing "10 mg/kg" covers an answer writing "10 mg per kg".
_UNIT_ALIAS = {
    "gm": "g", "kgs": "kg", "litre": "l", "litres": "l",
    "hectares": "ha", "hectare": "ha",
    "days": "day", "weeks": "week", "months": "month", "years": "year",
    "hours": "hour", "acres": "acre", "quintals": "quintal",
}


def _canonical(number: str, unit: str) -> str:
    unit = re.sub(r"\s+", "", unit.lower()).replace("per", "/")
    unit = _UNIT_ALIAS.get(unit, unit)
    value = float(number)
    # 10 and 10.0 are one quantity.
    number = str(int(value)) if value == int(value) else str(value)
    return f"{number}{unit}"


def quantities(text: str) -> set[str]:
    """Every quantity in a piece of text, in a comparable form."""
    text = (text or "").lower()
    for pattern, symbol in _SPELLED:
        text = re.sub(pattern, symbol, text, flags=re.I)
    found = {_canonical(n, u) for n, u in _QUANTITY.findall(text)}
    for low, high, unit in _RANGE.findall(text):
        found.add(_canonical(low, unit))
        found.add(_canonical(high, unit))
    for phrase, (number, unit) in _WORDS.items():
        if phrase in text:
            found.add(_canonical(number, unit))
    return found


def unsupported_quantities(answer: str, passages: list[str]) -> set[str]:
    """Quantities the answer states that no passage supports.

    An empty result means every figure in the answer can be pointed at in the
    source. It does not mean the answer is right -- prose can still mislead --
    only that the numbers were not made up.
    """
    supported: set[str] = set()
    for passage in passages:
        supported |= quantities(passage)
    return quantities(answer) - supported


# What to say when the check fails.
#
# Addressed to the farmer, not the developer, because the failure reaches
# them: they are holding an answer with a government source attached and part
# of it is not in that source. It does not try to say which part -- the check
# knows which quantity is unsupported but not which sentence a listener
# should distrust, and a precise-sounding warning that points at the wrong
# line is its own kind of dishonesty.
WARNING = (
    "Some figures above could not be matched to the published source. "
    "Please confirm any dose, interval or quantity with your KVK, a "
    "veterinarian or your agriculture officer before acting on it."
)
