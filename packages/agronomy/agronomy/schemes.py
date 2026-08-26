"""
Government scheme navigator for Indian farmers.

The design problem
------------------
Scheme information is the single most dangerous thing an agricultural
assistant can get wrong. A farmer told they qualify for something they do not
wastes a day and a bus fare they cannot spare. A farmer told an amount that
is out of date plans around a number that will not arrive. And a hallucinated
scheme name, office address or helpline is worse than saying nothing at all,
because it sends someone on a journey to a place that does not exist.

Language models are especially bad at this. Scheme details are exactly the
kind of plausible, specific, frequently-changing fact they will confidently
invent.

So this module is deliberately **not** a database of entitlements. It is a
navigator. It holds:

  * which schemes exist and what problem each solves,
  * a screening question set that tells a farmer whether it is worth their
    time to apply,
  * the official portal and helpline for each, so the authoritative answer is
    always one step away,
  * and a `last_verified` date on every record.

Figures are included where they are structural and long-standing (the PMFBY
premium caps are set in the scheme's own operational guidelines, and the
PM-KISAN instalment structure has been unchanged since launch), but every one
is returned alongside its source and a requirement to confirm. Nothing here
is presented as this farmer's guaranteed entitlement, because that
determination is made by the state agriculture department and nobody else.

Maintenance note: these records need reviewing each financial year. The
`last_verified` field exists so that staleness is visible rather than
silent, and `is_stale()` surfaces it in the tool output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class SchemeCategory(str, Enum):
    INCOME_SUPPORT = "income_support"
    INSURANCE = "insurance"
    CREDIT = "credit"
    SOIL_HEALTH = "soil_health"
    IRRIGATION = "irrigation"
    MECHANISATION = "mechanisation"
    MARKET = "market"


@dataclass(frozen=True)
class Scheme:
    """One government scheme.

    `key_facts` are structural features of the scheme, each written so it can
    be checked against the cited source. They are NOT a promise to this
    farmer.
    """
    key: str
    name: str
    short_name: str
    category: SchemeCategory
    ministry: str
    what_it_does: str
    # Plain-language screening. Answering yes to all of these means applying
    # is probably worth the trip; it does not mean the farmer qualifies.
    screening_questions: tuple[str, ...]
    # Things that commonly disqualify people, so a farmer can rule themselves
    # out before spending a day on it.
    common_exclusions: tuple[str, ...]
    key_facts: tuple[str, ...]
    official_url: str
    helpline: str
    apply_through: str
    documents_usually_needed: tuple[str, ...]
    last_verified: date
    # Crops or situations that make this scheme particularly relevant.
    relevant_when: tuple[str, ...] = ()

    def is_stale(self, today: date | None = None, months: int = 12) -> bool:
        """Whether this record is old enough that it must not be trusted alone."""
        today = today or date.today()
        age_days = (today - self.last_verified).days
        return age_days > months * 30


# Verified against the official scheme portals. Every figure here is one that
# appears in the scheme's own guidelines rather than in secondary reporting.
_VERIFIED = date(2026, 8, 24)

SCHEMES: dict[str, Scheme] = {
    "pm_kisan": Scheme(
        key="pm_kisan",
        name="Pradhan Mantri Kisan Samman Nidhi",
        short_name="PM-KISAN",
        category=SchemeCategory.INCOME_SUPPORT,
        ministry="Ministry of Agriculture & Farmers Welfare",
        what_it_does=(
            "Direct income support paid straight into a landholding farmer's "
            "bank account in three instalments a year."
        ),
        screening_questions=(
            "Do you own cultivable land in your own name?",
            "Is your land recorded in the revenue records of your state?",
            "Do you have an Aadhaar-linked bank account?",
        ),
        common_exclusions=(
            "Land held only as a tenant or sharecropper, without ownership "
            "recorded in your name",
            "Anyone in the household paying income tax",
            "Serving or retired government employees above certain grades, "
            "and professionals such as doctors, engineers and lawyers in "
            "practice",
        ),
        key_facts=(
            "Paid in three equal instalments across the year",
            "Requires Aadhaar seeding and eKYC to be completed, which is the "
            "most common reason instalments stop",
            "Land records must be updated in your name after inheritance or "
            "purchase, or payments will not start",
        ),
        official_url="https://pmkisan.gov.in",
        helpline="155261 / 011-24300606",
        apply_through=(
            "The PM-KISAN portal, a Common Service Centre (CSC), or your "
            "village patwari or agriculture office"
        ),
        documents_usually_needed=(
            "Aadhaar card", "Land ownership records (khasra/khatauni)",
            "Bank passbook with IFSC",
        ),
        last_verified=_VERIFIED,
        relevant_when=("landowner",),
    ),
    "pmfby": Scheme(
        key="pmfby",
        name="Pradhan Mantri Fasal Bima Yojana",
        short_name="PMFBY",
        category=SchemeCategory.INSURANCE,
        ministry="Ministry of Agriculture & Farmers Welfare",
        what_it_does=(
            "Crop insurance against yield loss from drought, flood, pest, "
            "disease, hail and other natural causes. Farmers pay a small "
            "capped share of the premium; governments pay the rest."
        ),
        screening_questions=(
            "Are you growing a crop that is notified for insurance in your "
            "district this season?",
            "Can you enrol before the cut-off date for this season?",
            "Do you cultivate the land, whether as an owner, tenant or "
            "sharecropper?",
        ),
        common_exclusions=(
            "Crops not notified for your district in this season",
            "Enrolment after the seasonal cut-off date, which is strict",
            "Losses from causes the scheme excludes, such as war, nuclear "
            "risk, or deliberate damage",
        ),
        key_facts=(
            "The farmer's premium share is capped at 2 percent of the sum "
            "insured for kharif food and oilseed crops, 1.5 percent for rabi "
            "food and oilseed crops, and 5 percent for annual commercial and "
            "horticultural crops",
            "Tenants and sharecroppers are eligible, not only landowners",
            "Losses must be reported within 72 hours of the event, usually "
            "through the Crop Insurance app or the insurer's helpline",
            "Enrolment cut-off dates differ by state and season and are the "
            "most common reason claims fail",
        ),
        official_url="https://pmfby.gov.in",
        helpline="14447",
        apply_through=(
            "The PMFBY portal, your bank if you have a crop loan, a CSC, or "
            "the insurance company's local agent"
        ),
        documents_usually_needed=(
            "Aadhaar card", "Bank account details",
            "Land records or a tenancy/sowing certificate",
            "Sowing declaration",
        ),
        last_verified=_VERIFIED,
        relevant_when=("any_crop",),
    ),
    "soil_health_card": Scheme(
        key="soil_health_card",
        name="Soil Health Card Scheme",
        short_name="Soil Health Card",
        category=SchemeCategory.SOIL_HEALTH,
        ministry="Ministry of Agriculture & Farmers Welfare",
        what_it_does=(
            "A free laboratory test of your soil, reporting its nutrient "
            "status and giving fertiliser recommendations for your specific "
            "field rather than a general rate."
        ),
        screening_questions=(
            "Do you cultivate land?",
            "Is there a Krishi Vigyan Kendra or soil testing laboratory "
            "serving your district?",
        ),
        common_exclusions=(
            "None in practice; the scheme is open to all cultivators",
        ),
        key_facts=(
            "The test is free of cost to the farmer",
            "It reports nitrogen, phosphorus, potassium, organic carbon, pH, "
            "electrical conductivity and micronutrients",
            "A soil test measures your actual field. Any satellite or map "
            "estimate, including the one this assistant uses, is a model "
            "prediction and is no substitute for it",
        ),
        official_url="https://soilhealth.dac.gov.in",
        helpline="Contact your district Krishi Vigyan Kendra",
        apply_through=(
            "Your village agriculture officer, the nearest Krishi Vigyan "
            "Kendra, or a soil testing laboratory"
        ),
        documents_usually_needed=("Land details", "Identity proof"),
        last_verified=_VERIFIED,
        relevant_when=("soil_problem", "fertiliser_question", "any_crop"),
    ),
    "kcc": Scheme(
        key="kcc",
        name="Kisan Credit Card",
        short_name="KCC",
        category=SchemeCategory.CREDIT,
        ministry="Ministry of Agriculture & Farmers Welfare / RBI",
        what_it_does=(
            "A credit line for crop inputs and short-term needs at a "
            "concessional interest rate, so farmers are not forced to borrow "
            "from informal lenders at far higher rates."
        ),
        screening_questions=(
            "Do you cultivate land, as an owner, tenant, sharecropper or "
            "part of a joint liability group?",
            "Do you have a bank account?",
        ),
        common_exclusions=(
            "An existing default on an agricultural loan",
            "Land not verifiable through revenue records or a tenancy "
            "agreement",
        ),
        key_facts=(
            "Carries an interest subvention, and a further rebate for prompt "
            "repayment, so the effective rate is well below an ordinary loan",
            "Also covers animal husbandry and fisheries, not only crops",
            "Tenants and oral lessees are eligible in many states, though "
            "banks vary in how readily they lend to them",
        ),
        official_url="https://www.myscheme.gov.in/schemes/kcc",
        helpline="Your bank branch, or the district lead bank",
        apply_through="Any commercial bank, regional rural bank, or cooperative bank",
        documents_usually_needed=(
            "Aadhaar card", "Land records or tenancy proof",
            "Passport photographs", "Bank account",
        ),
        last_verified=_VERIFIED,
        relevant_when=("input_cost", "credit_need"),
    ),
    "pmksy": Scheme(
        key="pmksy",
        name="Pradhan Mantri Krishi Sinchayee Yojana — Per Drop More Crop",
        short_name="PMKSY (micro-irrigation)",
        category=SchemeCategory.IRRIGATION,
        ministry="Ministry of Agriculture & Farmers Welfare",
        what_it_does=(
            "Subsidy on drip and sprinkler irrigation equipment, which cuts "
            "water use substantially compared with flood irrigation."
        ),
        screening_questions=(
            "Do you have an assured water source, such as a borewell, canal "
            "or pond?",
            "Are you willing to move from flood irrigation to drip or "
            "sprinkler?",
        ),
        common_exclusions=(
            "No assured water source",
            "Having already claimed the subsidy for the same plot within the "
            "scheme's cooling-off period",
        ),
        key_facts=(
            "Subsidy rates are higher for small and marginal farmers than for "
            "other farmers, and the exact percentage is set by each state",
            "Drip irrigation typically reaches 85 to 95 percent application "
            "efficiency against roughly 50 to 60 percent for unlined flood, "
            "which is where the water saving comes from",
            "Equipment must usually be bought from an empanelled supplier for "
            "the subsidy to apply",
        ),
        official_url="https://pmksy.gov.in",
        helpline="Your district horticulture or agriculture office",
        apply_through=(
            "The state horticulture or agriculture department, often through "
            "a state-specific online portal"
        ),
        documents_usually_needed=(
            "Land records", "Water source proof", "Aadhaar card",
            "Bank account", "Quotation from an empanelled supplier",
        ),
        last_verified=_VERIFIED,
        relevant_when=("water_scarcity", "irrigation_question"),
    ),
    "enam": Scheme(
        key="enam",
        name="National Agriculture Market",
        short_name="e-NAM",
        category=SchemeCategory.MARKET,
        ministry="Ministry of Agriculture & Farmers Welfare",
        what_it_does=(
            "An online trading platform linking APMC mandis across states, so "
            "produce can be sold to buyers beyond the local mandi."
        ),
        screening_questions=(
            "Is your local mandi integrated with e-NAM?",
            "Do you have produce to sell in marketable quantity?",
        ),
        common_exclusions=(
            "Mandis not yet integrated with the platform",
        ),
        key_facts=(
            "Lets buyers from other mandis and states bid on your lot, which "
            "matters most when the local mandi is paying below the rate "
            "elsewhere",
            "Assaying facilities at integrated mandis grade produce, which "
            "can raise the price a good lot fetches",
        ),
        official_url="https://enam.gov.in",
        helpline="1800-270-0224",
        apply_through="Registration at an integrated mandi, or on the e-NAM portal",
        documents_usually_needed=("Aadhaar card", "Bank account", "Mobile number"),
        last_verified=_VERIFIED,
        relevant_when=("selling", "price_question"),
    ),
}


# Keyword sets written from how farmers actually describe a problem, not from
# scheme vocabulary. Nobody says "I require micro-irrigation subsidy"; they
# say the borewell is running dry. Matching on scheme words instead of farmer
# words was the first version of this and it ranked income support above
# irrigation for "my borewell is running dry".
_CONCERN_KEYWORDS: dict[SchemeCategory, tuple[str, ...]] = {
    SchemeCategory.INSURANCE: (
        "loss", "lost", "damage", "damaged", "destroy", "ruin", "insur",
        "flood", "drought", "hail", "storm", "cyclone", "pest attack",
        "crop failed", "failure", "wiped",
    ),
    SchemeCategory.CREDIT: (
        "afford", "cannot buy", "cant buy", "money", "loan", "credit",
        "borrow", "debt", "expensive", "cost", "price of fertiliser",
        "no cash", "interest", "sahukar", "moneylender",
    ),
    SchemeCategory.IRRIGATION: (
        "water", "irrigat", "borewell", "bore well", "tubewell", "tube well",
        "well is dry", "running dry", "pump", "canal", "drip", "sprinkler",
        "water table", "groundwater", "not enough water",
    ),
    SchemeCategory.SOIL_HEALTH: (
        "soil", "fertil", "urea", "dap", "nutrient", "nitrogen", "potash",
        "yield falling", "land is weak", "soil test", "ph",
    ),
    SchemeCategory.MARKET: (
        "sell", "sold", "price", "rate", "mandi", "market", "buyer",
        "trader", "arhtiya", "better price",
    ),
    SchemeCategory.INCOME_SUPPORT: (
        "income", "support", "instal", "kisan nidhi", "pm kisan",
        "payment not received", "not getting",
    ),
}


def score_schemes(
    *,
    owns_land: bool | None = None,
    has_water_source: bool | None = None,
    concern: str | None = None,
) -> list[tuple[float, Scheme]]:
    """Score every scheme for relevance, highest first.

    Exposed separately from `schemes_for_situation` so the scoring itself is
    testable. Rank alone hides the signal: a penalty can correctly reduce a
    scheme's score without moving its position when nothing happens to score
    in between, and a test written against rank then reads as a failure when
    the behaviour is right.
    """
    concern_text = (concern or "").lower()
    scored: list[tuple[float, int, Scheme]] = []

    for index, scheme in enumerate(SCHEMES.values()):
        score = 0.0

        # Match the farmer's words against this scheme's category vocabulary.
        for keyword in _CONCERN_KEYWORDS.get(scheme.category, ()):
            if keyword in concern_text:
                score += 1.5
                break

        # Secondary signal from the scheme's own relevance tags.
        for topic in scheme.relevant_when:
            if topic.replace("_", " ") in concern_text:
                score += 0.6

        if scheme.key == "pm_kisan":
            if owns_land is False:
                # Ownership genuinely gates this one, so rank it down -- but
                # do not remove it, since the farmer may own land they have
                # not mentioned.
                score -= 1.2
            elif owns_land:
                score += 0.4

        if scheme.key == "pmksy" and has_water_source is False:
            # The subsidy is for equipment to distribute water, not to find
            # it. Without a source it is the wrong answer.
            score -= 1.0

        # Soil Health Card is free and useful to nearly everyone, so it earns
        # a small floor rather than competing on keywords alone.
        if scheme.key == "soil_health_card":
            score += 0.2

        # `index` breaks ties deterministically, so identical inputs always
        # produce identical output -- a ranking that reshuffles between calls
        # looks broken to anyone comparing two sessions.
        scored.append((score, -index, scheme))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [(score, scheme) for score, _, scheme in scored]


def schemes_for_situation(
    *,
    owns_land: bool | None = None,
    has_water_source: bool | None = None,
    concern: str | None = None,
) -> list[Scheme]:
    """Rank schemes by relevance to what the farmer is actually dealing with.

    Ranking, not filtering: a farmer who does not own land is still shown
    PMFBY and KCC, because tenants are eligible for both and are routinely
    and wrongly told otherwise. Ranking something down is recoverable by the
    farmer mentioning one more detail; hiding it is not.
    """
    return [
        scheme for _, scheme in score_schemes(
            owns_land=owns_land,
            has_water_source=has_water_source,
            concern=concern,
        )
    ]
