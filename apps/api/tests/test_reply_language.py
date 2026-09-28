"""
Which language the assistant is told to reply in.

Two rules, and the second is the one that was missing. A farmer who picks a
language gets that language, whatever they type. A farmer who has not picked
one gets the language of their latest message -- not of the conversation.

Without the second rule the model inferred a language from the whole history.
Observed: a farmer wrote once in Roman-script Punjabi, then twice in plain
English, and got Gurmukhi back both times. One earlier turn was enough to
capture every later reply.
"""

from agrin_api.prompts import build_system_prompt


class TestAChosenLanguageIsEnforced:
    def test_punjabi_is_required_even_for_english_input(self):
        prompt = build_system_prompt(language_hint="pa")
        assert "Punjabi" in prompt or "ਪੰਜਾਬੀ" in prompt
        assert "even when their message is in English" in prompt


class TestNoChoiceMeansFollowTheLatestMessage:
    def test_english_default_follows_the_latest_message(self):
        prompt = build_system_prompt(language_hint="en")
        assert "most recent message" in prompt

    def test_earlier_turns_do_not_carry_over(self):
        """The actual bug: history pulling later replies into its language."""
        prompt = build_system_prompt(language_hint="en")
        assert "does not carry over" in prompt

    def test_english_in_means_english_out(self):
        prompt = build_system_prompt(language_hint="en")
        assert "written in English gets an answer in English" in prompt

    def test_no_hint_at_all_behaves_like_english_default(self):
        """A request with no language field must not fall through to nothing."""
        prompt = build_system_prompt(language_hint=None)
        assert "most recent message" in prompt


class TestTheRulesDoNotCollide:
    def test_a_chosen_language_does_not_also_get_the_follow_rule(self):
        """Contradictory instructions would let the model pick either."""
        prompt = build_system_prompt(language_hint="pa")
        assert "most recent message" not in prompt


from agrin_api.prompts import dominant_script


class TestScriptIsDetectedNotInferred:
    """Telling the model to follow the latest message was not enough.

    Asked "how the weather at patiala?" in plain English, with English
    selected, it replied in Gurmukhi: the field is in Punjab, earlier turns
    had been Punjabi, and the instruction lost to that weight.
    """

    def test_plain_english_reads_as_latin(self):
        assert dominant_script("how the weather at patiala?") == "Latin"

    def test_each_indian_script_is_told_apart(self):
        assert dominant_script("ਕੀ ਪਾਣੀ ਲਾਉਣਾ ਹੈ?") == "Gurmukhi"
        assert dominant_script("क्या पानी देना है?") == "Devanagari"
        assert dominant_script("আমার জমিতে জল লাগবে?") == "Bengali"

    def test_romanised_punjabi_stays_latin(self):
        """The case the whole design turns on.

        Someone typing Punjabi in Latin letters must get an answer they can
        read back. Constraining the script rather than the language is what
        preserves that -- forcing English on every Latin message would not.
        """
        assert dominant_script("pani kado launa hai") == "Latin"

    def test_a_message_with_nothing_to_go_on_gives_no_answer(self):
        """A photo with no caption must not force a script."""
        assert dominant_script("") is None
        assert dominant_script("2") is None

    def test_a_stray_english_word_does_not_flip_the_script(self):
        """Farmers mix in words like 'urea' and 'DAP' constantly."""
        assert dominant_script("ਮੇਰੀ ਕਣਕ ਵਿੱਚ urea ਪਾਉਣਾ ਹੈ") == "Gurmukhi"


class TestTheDetectedScriptReachesThePrompt:
    def test_it_is_stated_as_a_rule_not_a_preference(self):
        prompt = build_system_prompt(language_hint="en", reply_script="Latin")
        assert "Latin script" in prompt
        assert "do not override it" in prompt

    def test_without_detection_the_softer_rule_still_stands(self):
        prompt = build_system_prompt(language_hint="en")
        assert "most recent message" in prompt

    def test_a_chosen_language_is_not_overridden_by_the_script(self, ):
        """Choosing Punjabi and typing English must still answer in Punjabi."""
        prompt = build_system_prompt(language_hint="pa", reply_script="Latin")
        assert "Latin script" not in prompt
