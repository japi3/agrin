"""
Tests for the government scheme navigator.

These cannot verify that the scheme facts are true -- no test can check
against a government portal that changes each financial year. What they can
do is enforce the properties that make wrong information survivable:

  * every record carries a real portal and helpline, so the authoritative
    answer is always one step away from whatever we said,
  * staleness is detectable rather than silent,
  * nothing is phrased as an entitlement, and
  * the ranking surfaces the right scheme for how a farmer actually describes
    a problem.

The last one matters more than it looks. A farmer who does not know PMFBY
exists will never ask for it by name; they will say their crop was flattened
by hail. If the ranking only responds to scheme vocabulary, the feature is
useless to exactly the people it is for.
"""

import re
from datetime import date, timedelta

import pytest

from agronomy.schemes import (
    SCHEMES,
    Scheme,
    SchemeCategory,
    schemes_for_situation,
    score_schemes,
)


class TestRecordIntegrity:
    def test_every_scheme_has_an_official_portal(self):
        for key, s in SCHEMES.items():
            assert s.official_url.startswith("https://"), key
            assert " " not in s.official_url, key

    def test_every_scheme_has_a_helpline_or_named_office(self):
        # A farmer must always have somewhere real to go. An empty helpline
        # would leave them with our word and nothing else.
        for key, s in SCHEMES.items():
            assert s.helpline.strip(), key
            assert len(s.helpline) > 4, key

    def test_every_scheme_states_how_to_apply(self):
        for key, s in SCHEMES.items():
            assert len(s.apply_through) > 20, key
            assert s.documents_usually_needed, key

    def test_every_scheme_has_screening_questions(self):
        # Screening questions are what let a farmer decide for themselves
        # whether the trip is worth it. Without them the tool is a brochure.
        for key, s in SCHEMES.items():
            assert len(s.screening_questions) >= 2, key
            for q in s.screening_questions:
                assert q.strip().endswith("?"), f"{key}: {q!r}"

    def test_every_scheme_lists_common_disqualifiers(self):
        for key, s in SCHEMES.items():
            assert s.common_exclusions, key

    def test_keys_are_consistent(self):
        for key, s in SCHEMES.items():
            assert s.key == key

    def test_categories_are_valid(self):
        for s in SCHEMES.values():
            assert isinstance(s.category, SchemeCategory)


class TestStalenessIsVisible:
    """Scheme rules change annually; silence about age is the danger."""

    def _scheme(self, verified: date) -> Scheme:
        base = SCHEMES["pm_kisan"]
        return Scheme(
            key=base.key, name=base.name, short_name=base.short_name,
            category=base.category, ministry=base.ministry,
            what_it_does=base.what_it_does,
            screening_questions=base.screening_questions,
            common_exclusions=base.common_exclusions,
            key_facts=base.key_facts, official_url=base.official_url,
            helpline=base.helpline, apply_through=base.apply_through,
            documents_usually_needed=base.documents_usually_needed,
            last_verified=verified,
        )

    def test_recent_record_is_not_stale(self):
        s = self._scheme(date.today() - timedelta(days=30))
        assert s.is_stale() is False

    def test_old_record_is_stale(self):
        s = self._scheme(date.today() - timedelta(days=500))
        assert s.is_stale() is True

    def test_boundary(self):
        assert self._scheme(date.today() - timedelta(days=400)).is_stale()
        assert not self._scheme(date.today() - timedelta(days=200)).is_stale()

    def test_shipped_records_carry_a_verification_date(self):
        for key, s in SCHEMES.items():
            assert isinstance(s.last_verified, date), key
            assert s.last_verified <= date.today(), (
                f"{key} claims to have been verified in the future"
            )


class TestNoEntitlementLanguage:
    """The tool navigates. It never rules on eligibility.

    Eligibility is determined by a state agriculture department. Any wording
    that reads as a promise invites a farmer to plan around money that may
    never arrive.
    """

    FORBIDDEN = re.compile(
        r"\b(you will (get|receive)|you are eligible|guaranteed|"
        r"you qualify|entitled to)\b",
        re.IGNORECASE,
    )

    def test_no_scheme_text_promises_an_outcome(self):
        for key, s in SCHEMES.items():
            blob = " ".join([
                s.what_it_does, *s.key_facts, *s.screening_questions,
                *s.common_exclusions, s.apply_through,
            ])
            match = self.FORBIDDEN.search(blob)
            assert match is None, (
                f"{key} contains entitlement language: {match.group(0)!r}"
            )

    def test_screening_questions_are_questions_not_assertions(self):
        for key, s in SCHEMES.items():
            for q in s.screening_questions:
                assert not q.lower().startswith("you "), f"{key}: {q!r}"


class TestRankingUsesFarmerVocabulary:
    """A farmer describes a problem; they do not name a scheme."""

    def _top(self, concern: str, **kwargs) -> str:
        return schemes_for_situation(concern=concern, **kwargs)[0].key

    @pytest.mark.parametrize("concern,expected", [
        ("my crop was damaged by hail", "pmfby"),
        ("the flood destroyed my whole field", "pmfby"),
        ("drought has ruined the crop", "pmfby"),
        ("my borewell is running dry", "pmksy"),
        ("there is not enough water for irrigation", "pmksy"),
        ("I want to sell at a better price", "enam"),
        ("what rate will I get at the mandi", "enam"),
        ("my soil is getting weak", "soil_health_card"),
        ("I have not received my instalment", "pm_kisan"),
    ])
    def test_natural_phrasing_surfaces_the_right_scheme(self, concern, expected):
        assert self._top(concern) == expected

    def test_credit_surfaces_for_affordability(self):
        # "afford" is how this is said; "credit facility" is not.
        top_three = [
            s.key for s in schemes_for_situation(
                concern="I cannot afford fertiliser this season")[:3]
        ]
        assert "kcc" in top_three

    def test_ranking_is_deterministic(self):
        # Two identical sessions must not show different advice.
        a = [s.key for s in schemes_for_situation(concern="hail damage")]
        b = [s.key for s in schemes_for_situation(concern="hail damage")]
        assert a == b

    def test_nothing_is_ever_filtered_out(self):
        # Tenants are eligible for PMFBY and KCC and are routinely told
        # otherwise. Ranking down is recoverable; hiding is not.
        result = schemes_for_situation(owns_land=False, concern="crop loss")
        assert len(result) == len(SCHEMES)
        assert "pmfby" in [s.key for s in result]
        assert "kcc" in [s.key for s in result]

    def test_land_ownership_ranks_pm_kisan_down_not_out(self):
        without = [s.key for s in schemes_for_situation(owns_land=False)]
        with_land = [s.key for s in schemes_for_situation(owns_land=True)]
        assert "pm_kisan" in without
        assert with_land.index("pm_kisan") < without.index("pm_kisan")

    def test_no_water_source_penalises_the_irrigation_subsidy(self):
        """The subsidy buys equipment to distribute water, not to find it.

        It is still ranked first for a water problem even without a source,
        and that is correct -- it remains the most relevant scheme we have,
        and its own screening question asks about the water source. What must
        hold is that the absence of a source counts against it, which shows up
        against a competing concern rather than in isolation.
        """
        def pmksy_score(has_source: bool | None) -> float:
            return next(
                score for score, s in score_schemes(
                    has_water_source=has_source, concern="water problem")
                if s.key == "pmksy"
            )

        assert pmksy_score(False) < pmksy_score(True)
        assert pmksy_score(False) < pmksy_score(None)

    def test_empty_concern_still_returns_everything(self):
        assert len(schemes_for_situation(concern="")) == len(SCHEMES)
        assert len(schemes_for_situation()) == len(SCHEMES)
