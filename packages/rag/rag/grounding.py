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
_SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")

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


def _normalised(text: str) -> str:
    """Lowercased, with spelled-out units written as symbols."""
    text = (text or "").lower()
    for pattern, symbol in _SPELLED:
        text = re.sub(pattern, symbol, text, flags=re.I)
    return text


def _placed(text: str) -> list[tuple[str, int]]:
    """Every quantity and where in the text it sits.

    Positions are what makes a claim-level check possible: knowing that a
    passage contains "14 days" somewhere is nearly worthless, and knowing
    that it contains it next to the word "deworming" is the whole question.
    """
    text = _normalised(text)
    out = [(_canonical(m.group(1), m.group(2)), m.start())
           for m in _QUANTITY.finditer(text)]
    for m in _RANGE.finditer(text):
        out.append((_canonical(m.group(1), m.group(3)), m.start()))
        out.append((_canonical(m.group(2), m.group(3)), m.start()))
    return out


def quantities(text: str) -> set[str]:
    """Every quantity in a piece of text, in a comparable form."""
    text = _normalised(text)
    found = {q for q, _ in _placed(text)}
    for phrase, (number, unit) in _WORDS.items():
        if phrase in text:
            found.add(_canonical(number, unit))
    return found


# How far from a quantity a word may sit and still be about it. Roughly a
# sentence either side: wide enough that "Albendazole (Dose: 10 mg/kg Body
# weight)" counts, narrow enough that a number in the next paragraph does
# not.
CONTEXT_WINDOW = 170

# Words too common to tie a number to a subject.
_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "should", "which",
    "your", "their", "will", "can", "may", "are", "was", "were", "been",
    "also", "then", "than", "when", "where", "what", "into", "over", "per",
    "about", "after", "before", "during", "while", "each", "every", "some",
    "give", "given", "giving", "used", "using", "use", "done", "being",
}


def _subject_words(sentence: str) -> set[str]:
    """The words that say what a sentence is about."""
    return {
        w for w in re.findall(r"[a-z]{4,}", _normalised(sentence))
        if w not in _STOP
    }


def unsupported_quantities(answer: str, passages: list[str]) -> set[str]:
    """Quantities the answer states that no passage supports.

    Supported means more than "this number appears somewhere in the
    retrieved text". That weaker test is what the first version did, and it
    passed a fabricated calf-deworming schedule of day 14, day 35 and day 56
    because the corpus happened to contain "35 days after sowing" in a rice
    herbicide passage and "7-14 days" in one about microgreens. 119 passages
    in this corpus mention those intervals and not one is about calves. With
    passages this long, almost any plausible number finds a coincidence.

    So a quantity counts as supported only where it appears in a passage
    *near a word the answer used around it*. "10 mg/kg" beside "Albendazole"
    is evidence; "35 days" beside "bispyribac sodium" is not, however much
    the digits agree.

    An empty result means every figure can be pointed at in the source. It
    does not mean the answer is right -- prose can still mislead -- only
    that the numbers were not invented.
    """
    placed = [(_normalised(p), _placed(p)) for p in passages]

    def supported(quantity: str, subject: set[str]) -> bool:
        for text, positions in placed:
            for found, at in positions:
                if found != quantity:
                    continue
                if not subject:
                    return True      # nothing to corroborate against
                window = text[max(0, at - CONTEXT_WINDOW):at + CONTEXT_WINDOW]
                if any(word in window for word in subject):
                    return True
        return False

    missing: set[str] = set()
    for sentence in _SENTENCE.split(answer or ""):
        subject = _subject_words(sentence)
        for quantity in {q for q, _ in _placed(sentence)}:
            if not supported(quantity, subject):
                missing.add(quantity)
    return missing


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
