"""
orchestration/greeting.py — the pure-greeting detector added so "Hi"/"Hello
Kriton"/"good morning" get a warm reply instead of the confusing
"could not find sufficient sources... clarify your jurisdiction" message
(a plain greeting retrieves zero document context, which used to trip the
§2 no-unsupported-answering rule).
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.orchestration.greeting import is_pure_greeting


def test_recognizes_the_reported_greeting_variants():
    for query in ("Hii", "hello", "goodmorning", "hii kriton", "hello kriton", "hey", "whatsup"):
        assert is_pure_greeting(query), f"{query!r} should be recognized as a pure greeting"
    print("test_recognizes_the_reported_greeting_variants: PASSED")


def test_recognizes_punctuation_and_case_variants():
    for query in ("Hi!", "Hello Kriton!", "good morning", "Good Afternoon", "what's up", "Hey Kriton?", "Yo"):
        assert is_pure_greeting(query), f"{query!r} should be recognized as a pure greeting"
    print("test_recognizes_punctuation_and_case_variants: PASSED")


def test_does_not_flag_a_real_question_that_starts_with_a_greeting():
    """The whole-string anchor is what matters here — 'Hi' plus a real
    question must go through the normal grounded pipeline, not get
    short-circuited into a canned greeting reply."""
    for query in (
        "Hi, can you calculate my VAT?",
        "Hello, what is IFRS 16?",
        "hey what is the current UK unemployment rate",
    ):
        assert not is_pure_greeting(query), f"{query!r} should NOT be treated as a pure greeting"
    print("test_does_not_flag_a_real_question_that_starts_with_a_greeting: PASSED")


def test_does_not_flag_unrelated_queries():
    assert not is_pure_greeting("Calculate UK VAT on £15,000")
    assert not is_pure_greeting("What is the Saver's Credit?")
    print("test_does_not_flag_unrelated_queries: PASSED")


def main():
    test_recognizes_the_reported_greeting_variants()
    test_recognizes_punctuation_and_case_variants()
    test_does_not_flag_a_real_question_that_starts_with_a_greeting()
    test_does_not_flag_unrelated_queries()
    print("All tests passed successfully!")


if __name__ == "__main__":
    main()
