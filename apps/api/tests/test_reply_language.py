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
