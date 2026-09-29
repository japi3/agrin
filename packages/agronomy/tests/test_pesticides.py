"""
Tests for naming a pesticide India has banned.

The platform already refuses to state a dose, which stops it telling anyone
*how much* endosulfan to use. It did not stop it engaging with the question,
and a farmer who asks whether to spray a banned product and gets a helpful
answer about timing has been helped to break the law and poison themselves.

Most of what follows guards the other direction. This check speaks about the
law, so being wrong is expensive in a way that a missed detection is not:
telling a cotton grower that the drum in their shed is illegal, when it is
lawful on cotton and banned only on vegetables, is a false statement about
the law and spends the credibility the real warnings depend on.
"""

from agronomy.pesticides import find_regulated, is_verified, notice


def names(text: str) -> set[str]:
    return {f.name for f in find_regulated(text)}


def status_of(text: str, name: str) -> str | None:
    for f in find_regulated(text):
        if f.name == name:
            return f.status
    return None


class TestItCatchesWhatIsBanned:
    def test_a_banned_active_in_the_question(self):
        assert "Endosulfan" in names("Should I spray endosulfan on brinjal?")

    def test_in_gurmukhi(self):
        assert "Endosulfan" in names("ਕੀ ਮੈਂ ਐਂਡੋਸਲਫਾਨ ਵਰਤ ਸਕਦਾ ਹਾਂ?")

    def test_in_devanagari(self):
        assert "Endosulfan" in names("क्या मैं एंडोसल्फान का छिड़काव करूं?")

    def test_a_trade_name_off_the_packet(self):
        """Farmers buy Nuvan, not dichlorvos. The shop label is what they
        have in front of them."""
        assert "Dichlorovos" in names("I have some Nuvan left in the shed")

    def test_a_common_misspelling(self):
        assert "Endosulfan" in names("is endosulphan allowed")

    def test_case_does_not_matter(self):
        assert names("PHORATE") == names("phorate")


class TestItDoesNotOverstateTheLaw:
    def test_monocrotophos_is_restricted_not_banned(self):
        """It appears on every informal "banned in India" list, and it is
        not banned — only on vegetables. Getting this wrong tells a lawful
        user their product is illegal."""
        assert status_of("can I use monocrotophos on cotton", "Monocrotophos") \
            == "restricted"

    def test_and_the_restriction_is_stated_rather_than_implied(self):
        text = notice(find_regulated("monocrotophos on cotton"))
        assert "vegetables" in text
        assert "banned in India" not in text

    def test_a_withdrawn_registration_is_not_called_banned(self):
        assert status_of("simazine", "Simazine") == "withdrawn"

    def test_a_restricted_product_says_how_it_may_be_used(self):
        text = notice(find_regulated("aluminium phosphide for grain storage"))
        assert "pest control operators" in text

    def test_an_ordinary_question_triggers_nothing(self):
        assert find_regulated("How much urea should I apply to wheat?") == []

    def test_an_approved_pesticide_triggers_nothing(self):
        """Imidacloprid and mancozeb are registered. Warning about them
        would make every spraying question carry a scary sentence."""
        assert find_regulated("imidacloprid and mancozeb spray") == []

    def test_a_word_that_merely_contains_a_banned_name_is_not_a_match(self):
        assert find_regulated("the endosulfanation process") == []


class TestTheLongerNameWins:
    def test_methyl_parathion_is_not_read_as_ethyl_parathion(self):
        assert "Methyl Parathion" in names("methyl parathion")
        assert "Ethyl Parathion" not in names("methyl parathion")

    def test_paraquat_resolves_to_the_registered_banned_name(self):
        """The list bans Paraquat Dimethyl Sulphate; farmers say paraquat."""
        assert "Paraquat Dimethyl Sulphate" in names("paraquat in my orchard")


class TestWhatTheFarmerIsTold:
    def test_the_notice_names_who_to_ask_instead(self):
        """A warning that only says "banned" leaves them with a pest and no
        plan."""
        text = notice(find_regulated("endosulfan"))
        assert "KVK" in text or "agriculture officer" in text

    def test_nothing_regulated_means_no_notice(self):
        assert notice(find_regulated("urea and DAP")) is None

    def test_the_table_records_that_it_was_checked(self):
        """Entered by hand from a list the Registration Committee revises."""
        assert is_verified() is True

    def test_banned_is_stated_before_restricted(self):
        """If both appear, the one that makes the answer unlawful leads."""
        found = find_regulated("endosulfan or monocrotophos")
        assert found[0].status == "banned"
