"""
Tests for catching an answer that says more than its source did.

The case at the centre of this file is real and was found in the running
app, not imagined. Asked how to deworm a buffalo calf, the assistant
retrieved genuine ICAR passages saying Albendazole at 10 mg/kg and replied
with a dosing schedule of day 14, day 35 and day 56, monthly thereafter,
plus a second drug at a dose -- none of it in any passage -- and attributed
the whole thing to the government advisory.

Two rounds of prompt-writing did not stop it. This check does not ask the
model to behave; it reads the finished answer and compares the figures
against the passages. That is why it is worth having, and why the tests
below are mostly about the two ways it could become useless: missing a real
invention, or crying wolf on a legitimate paraphrase until someone switches
it off.
"""

from rag.grounding import quantities, unsupported_quantities

# Abridged from the passages the tool actually returned.
ICAR = [
    "Deworming of all the adult stock with broad spectrum antihelmintic, "
    "Albendazole (Dose: 10 mg/ kg Body weight) during Last week of September. "
    "Dry fodder: 7 Kg, Green fodder: 10 -15 kg, concentrate mixture: 2Kg.",
    "Deworm your animals with Albendazole or Fenbendazole @ 10mg/kg body "
    "weight. Protect your birds from coccidiosis by giving cordinal powder "
    "@ 1g/litre of drinking water.",
]


class TestTheAnswerThatPromptedThis:
    def test_the_invented_schedule_is_caught(self):
        """Day 14, 35 and 56 appear in no passage."""
        answer = (
            "First deworming is done on the 14th day of age, followed by the "
            "35th day and the 56th day. After that, repeat monthly until the "
            "calf is six months old."
        )
        missing = unsupported_quantities(answer, ICAR)
        assert missing, "the fabricated schedule must not pass"
        assert any("35" in m for m in missing)

    def test_the_invented_dose_is_caught(self):
        """The sources say 10 mg/kg. 7.5 is not in them."""
        answer = "Albendazole at a dose of 7.5 to 10 milligrams per kilogram."
        assert unsupported_quantities(answer, ICAR)

    def test_the_real_dose_alone_passes(self):
        """The part that was genuinely supported must not be flagged, or the
        warning appears on correct answers and stops being believed."""
        answer = (
            "The advisory says to deworm with Albendazole at 10 mg/kg of body "
            "weight, in the last week of September."
        )
        assert unsupported_quantities(answer, ICAR) == set()


class TestItDoesNotCryWolf:
    def test_the_same_quantity_written_differently_is_the_same_quantity(self):
        for phrasing in ("10 mg/kg", "10mg/kg", "10 mg / kg", "10 mg per kg"):
            assert unsupported_quantities(
                f"Give {phrasing} of Albendazole.", ICAR) == set()

    def test_a_trailing_zero_is_not_a_new_number(self):
        assert unsupported_quantities("Use 10.0 mg/kg.", ICAR) == set()

    def test_a_fortnight_is_fourteen_days(self):
        """A model saying 'after a fortnight' where the source says 14 days
        is translating, which is its job, not inventing."""
        assert unsupported_quantities(
            "Spray again after a fortnight.", ["Repeat the spray after 14 days."]
        ) == set()

    def test_prose_without_figures_is_never_flagged(self):
        """Paraphrase is legitimate; only quantities are checkable."""
        answer = ("Deworm the animals regularly, and ask your veterinarian "
                  "which medicine suits your herd.")
        assert unsupported_quantities(answer, ICAR) == set()

    def test_an_answer_with_no_sources_is_not_checked_here(self):
        """With nothing retrieved there is nothing to check against, and
        flagging every figure would make the warning meaningless."""
        assert unsupported_quantities("Apply 40 kg per acre.", []) == {"40kg"}


class TestExtraction:
    def test_it_reads_doses_rates_and_intervals(self):
        found = quantities("Apply 13 ml in 400 ml water, 40 kg seed, after 21 days.")
        assert {"13ml", "400ml", "40kg", "21day"} <= found

    def test_units_written_either_way_collapse_together(self):
        assert quantities("100 gm") == quantities("100 g")
        assert quantities("2 litres") == quantities("2 l")

    def test_a_bare_number_is_not_a_quantity(self):
        """Step numbers and years would flood the check with noise."""
        assert quantities("First, do this. Second, do that.") == set()

    def test_it_is_case_insensitive(self):
        assert quantities("10 MG/KG") == quantities("10 mg/kg")


# The passages actually retrieved for the buffalo-calf question, abridged but
# verbatim. The last two are the ones that defeated the first version of this
# check: they are about rice herbicide timing and microgreens, and they
# supplied "35 days" and "14 days" to a claim about deworming calves.
RETRIEVED = [
    "Deworming of all the adult stock with broad spectrum antihelmintic, "
    "Albendazole (Dose: 10 mg/ kg Body weight) during Last week of September. "
    "Dry fodder: 7 Kg, Green fodder: 10 -15 kg, concentrate mixture: 2Kg.",
    "Deworm your animals with Albendazole or Fenbendazole @ 10mg/kg body "
    "weight. Protect your birds from coccidiosis with cordinal powder @ 1g/litre.",
    "post-emergence herbicide application (bispyribac sodium 25g/ha) at 25-35 "
    "days after sowing or hand weeding at 35-45 days after sowing.",
    "Microgreens are harvested in a gap of 7-14 days under tropical conditions.",
]


class TestANumberNeedsTheRightNeighbours:
    """The failure that a bag-of-quantities check cannot see.

    The first version asked only whether a number appeared somewhere in the
    retrieved text. It does: 119 passages in this corpus mention 14, 35 or
    56 days, none of them about calves. So a fabricated dosing schedule
    passed, with a government citation attached.
    """

    def test_the_fabricated_schedule_is_caught(self):
        answer = ("Calves should be dewormed on the 14th day, 35th day and "
                  "56th day of life.")
        missing = unsupported_quantities(answer, RETRIEVED)
        assert {"14day", "35day", "56day"} <= missing

    def test_a_coincidence_in_an_unrelated_passage_does_not_vouch_for_it(self):
        """"35 days after sowing", about rice herbicide, must not support a
        claim about deworming."""
        answer = "Deworm the calf on the 35th day."
        assert "35day" in unsupported_quantities(answer, RETRIEVED)

    def test_the_real_dose_beside_the_real_drug_still_passes(self):
        """The check has to stay quiet on correct answers or it gets
        ignored, and then it protects nobody."""
        answer = ("Deworm with Albendazole at 10 mg/kg of body weight in the "
                  "last week of September.")
        assert unsupported_quantities(answer, RETRIEVED) == set()

    def test_a_figure_is_judged_by_the_sentence_it_is_in(self):
        """Two claims, both supported, each by a different passage."""
        answer = ("Deworm with Albendazole at 10 mg/kg. Give 7 kg of dry "
                  "fodder daily.")
        assert unsupported_quantities(answer, RETRIEVED) == set()

    def test_a_sentence_with_no_subject_words_falls_back_to_presence(self):
        """Nothing to corroborate against is not evidence of invention, so
        the weaker test applies rather than a flag the writer cannot act on."""
        assert unsupported_quantities("10 mg/kg.", RETRIEVED) == set()
