import pytest
from eval_scoring import (
    STOPPED_BY_WATCHDOG,
    answer_correct,
    detect_fallback,
    final_status,
)

SPIRAL_FALLBACK = (
    "I couldn't extract a consistent answer from the retrieved content for this step. "
    "The chunks pulled from the knowledge store appear fragmented or contradictory."
)
TIMEOUT_FALLBACK = (
    "The model took too long to respond (no answer within 900s). Try a shorter question."
)
WATCHDOG_MESSAGE = (
    "This request exceeded the maximum processing time (1800s) and was stopped. "
    "Try a shorter or simpler question, or ask an administrator to raise TASK_TIMEOUT "
    "for long-running models."
)


class TestAnswerCorrect:
    @pytest.mark.parametrize("fallback", [SPIRAL_FALLBACK, TIMEOUT_FALLBACK, WATCHDOG_MESSAGE])
    def test_agent_fallback_text_is_never_correct(self, make_item, fallback):
        item = make_item(answer_patterns=[r".*"])
        assert not answer_correct(item, fallback)


class TestShippedPatterns:
    def test_refusal_patterns_accept_common_not_found_phrasings(self, testset):
        item = {"answer_patterns": testset["refusal_patterns"]}
        for phrasing in (
            "The retrieved content does not contain this information.",
            "The documents don't mention a parental leave policy.",
            "I couldn't find that in the provided documents.",
            "There is no information about a dress code.",
            "This is not specified in the knowledge store.",
        ):
            assert answer_correct(item, phrasing), phrasing

    def test_refusal_patterns_reject_answers_and_agent_fallbacks(self, testset):
        item = {"answer_patterns": testset["refusal_patterns"]}
        for text in (
            "FinCorp's CEO is Sarah Johnson.",
            SPIRAL_FALLBACK,
            TIMEOUT_FALLBACK,
            WATCHDOG_MESSAGE,
        ):
            assert not answer_correct(item, text), text

    def test_number_patterns_do_not_match_inside_larger_numbers(self, items):
        by_id = {item["id"]: item for item in items}
        assert not answer_correct(by_id["fin-14"], "Facilities cost $185,000.")
        assert not answer_correct(by_id["cross-02"], "Sarah Johnson approved $265,000.")
        assert answer_correct(by_id["fin-14"], "The Horus deployment cost $85K.")


class TestFallbackDetection:
    def test_spiral_and_timeout_fallbacks_are_named(self):
        assert detect_fallback(SPIRAL_FALLBACK) == "spiral"
        assert detect_fallback(TIMEOUT_FALLBACK) == "timeout"

    def test_mas_task_timeout_watchdog_message_is_named(self):
        assert detect_fallback(WATCHDOG_MESSAGE) == "task_timeout"

    def test_regular_answers_have_no_fallback(self):
        assert detect_fallback("$4.2M") is None
        assert detect_fallback(None) is None


class TestFinalStatus:
    def test_watchdog_message_turns_an_ok_answer_into_a_timeout(self):
        assert final_status("ok", None, WATCHDOG_MESSAGE) == ("timeout", STOPPED_BY_WATCHDOG)

    def test_agent_fallbacks_and_regular_answers_keep_their_status(self):
        assert final_status("ok", None, TIMEOUT_FALLBACK) == ("ok", None)
        assert final_status("ok", None, "$4.2M") == ("ok", None)
        assert final_status("error", "task failed", WATCHDOG_MESSAGE) == ("error", "task failed")
