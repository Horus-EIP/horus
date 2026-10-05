import pytest
from eval_scoring import (
    ROUTE_AGENT,
    ROUTE_DIRECT,
    SOURCE_BASIS_CITED,
    SOURCE_BASIS_RETRIEVAL,
    STOPPED_BY_WATCHDOG,
    answer_correct,
    detect_fallback,
    expected_route,
    final_status,
    missing_patterns,
    normalize_answer,
    route_correct,
    source_check,
    source_key,
    source_ranks,
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
ALL_DOCUMENTS = [
    "1_Q4_2025_Financial_Report.md",
    "2_Employee_Handbook.md",
    "3_Compliance_Guidelines.md",
    "5_IT_Security_Policy.md",
    "4_Expense_Policy.md",
]


class TestNormalizeAnswer:
    def test_full_width_digits_and_ideographic_stop_are_folded(self):
        assert normalize_answer("Ｑ４ ２０２５ $4。2M") == "Q4 2025 $4.2M"

    def test_markdown_emphasis_and_curly_quotes_are_removed(self):
        assert normalize_answer("**$4.2M** — it’s `final`") == "$4.2M — it's final"

    def test_empty_values_become_empty_text(self):
        assert normalize_answer(None) == ""
        assert normalize_answer("") == ""


class TestAnswerCorrect:
    def test_all_patterns_must_match(self, make_item):
        item = make_item(answer_patterns=[r"Sarah\s+Johnson", r"December\s+12"])
        assert answer_correct(item, "Approved by Sarah Johnson on December 12, 2025.")
        assert not answer_correct(item, "Approved by Sarah Johnson.")

    def test_matching_ignores_case_and_markdown(self, make_item):
        item = make_item(answer_patterns=[r"\b4\.2\s*(m\b|million)"])
        assert answer_correct(item, "Revenue was **$4.2 Million**.")

    def test_full_width_answers_still_match(self, make_item):
        item = make_item(answer_patterns=[r"\b4\.2\s*(m\b|million)"])
        assert answer_correct(item, "$４。２M")

    def test_blank_answer_is_never_correct(self, make_item):
        item = make_item(answer_patterns=[r".*"])
        assert not answer_correct(item, "   ")
        assert not answer_correct(item, None)

    @pytest.mark.parametrize("fallback", [SPIRAL_FALLBACK, TIMEOUT_FALLBACK, WATCHDOG_MESSAGE])
    def test_agent_fallback_text_is_never_correct(self, make_item, fallback):
        item = make_item(answer_patterns=[r".*"])
        assert not answer_correct(item, fallback)

    def test_missing_patterns_lists_what_did_not_match(self):
        patterns = [r"Acme\s+Bank", r"Kestrel\s+Capital"]
        assert missing_patterns(patterns, "Acme Bank and Meridian") == [r"Kestrel\s+Capital"]


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


class TestRoutes:
    def test_direct_items_expect_direct_answer_and_others_an_agent(self, make_item):
        assert expected_route(make_item(category="direct")) == ROUTE_DIRECT
        assert expected_route(make_item(category="not_in_corpus")) == ROUTE_AGENT
        assert expected_route(make_item(category="multi_hop")) == ROUTE_AGENT

    def test_route_correct_compares_with_the_observed_route(self, make_item):
        assert route_correct(make_item(category="direct"), ROUTE_DIRECT) is True
        assert route_correct(make_item(category="direct"), ROUTE_AGENT) is False
        assert route_correct(make_item(), None) is None


class TestSourceRanks:
    def test_source_titles_compare_by_file_stem(self):
        assert source_key("4_Expense_Policy.md") == "4_expense_policy"
        assert source_key("docs\\4_Expense_Policy.MD") == "4_expense_policy"
        assert source_key("4_Expense_Policy") == "4_expense_policy"

    def test_rank_is_the_position_among_distinct_documents(self, make_item):
        ranking = ["2_Employee_Handbook.md", "2_Employee_Handbook", "4_Expense_Policy.md"]
        assert source_ranks(make_item(), [ranking]) == [2]

    def test_best_rank_over_every_retrieval_of_a_chain(self, make_item):
        rankings = [ALL_DOCUMENTS, ["4_Expense_Policy.md", "2_Employee_Handbook.md"]]
        assert source_ranks(make_item(), rankings) == [1]

    def test_document_never_retrieved_has_no_rank(self, make_item):
        item = make_item(expected_source=["1_Q4_2025_Financial_Report.md", "4_Expense_Policy.md"])
        assert source_ranks(item, [["1_Q4_2025_Financial_Report.md"], []]) == [1, None]


class TestSourceCheck:
    def test_expected_document_ranked_first_is_correct(self, make_item):
        ranking = ["4_Expense_Policy.md", "2_Employee_Handbook.md"]
        assert source_check(make_item(), retrieval_steps=1, retrieved_sources=[ranking]) == {
            "source_basis": SOURCE_BASIS_RETRIEVAL,
            "source_ranks": [1],
            "source_correct_auto": True,
        }

    def test_whole_corpus_returned_with_the_document_last_is_not_correct(self, make_item):
        result = source_check(make_item(), retrieved_sources=[ALL_DOCUMENTS])
        assert result["source_ranks"] == [5]
        assert result["source_correct_auto"] is False

    def test_cross_document_item_needs_every_document_in_the_top_two(self, make_item):
        item = make_item(expected_source=["1_Q4_2025_Financial_Report.md", "4_Expense_Policy.md"])
        top_two = ["4_Expense_Policy", "1_Q4_2025_Financial_Report.md", "2_Employee_Handbook.md"]
        only_one = [["4_Expense_Policy.md"]]
        assert source_check(item, retrieved_sources=[top_two])["source_correct_auto"] is True
        assert source_check(item, retrieved_sources=[ALL_DOCUMENTS])["source_correct_auto"] is False
        assert source_check(item, retrieved_sources=only_one)["source_ranks"] == [None, 1]

    def test_live_retrieval_without_titles_is_not_observable(self, make_item):
        assert source_check(make_item(), retrieval_steps=1, retrieved_sources=None) == {
            "source_basis": None,
            "source_ranks": None,
            "source_correct_auto": None,
        }

    def test_incomplete_event_stream_cannot_prove_a_wrong_source(self, make_item):
        missed = source_check(make_item(), retrieved_sources=[], events_complete=False)
        assert missed["source_correct_auto"] is None
        seen = source_check(
            make_item(), retrieved_sources=[["4_Expense_Policy.md"]], events_complete=False
        )
        assert seen["source_correct_auto"] is True

    def test_answer_citations_take_precedence_over_retrieval(self, make_item):
        result = source_check(
            make_item(), retrieved_sources=[ALL_DOCUMENTS], cited_sources=["4_Expense_Policy.md"]
        )
        assert result == {
            "source_basis": SOURCE_BASIS_CITED,
            "source_ranks": None,
            "source_correct_auto": True,
        }
        wrong = source_check(make_item(), cited_sources=["2_Employee_Handbook.md"])
        assert wrong["source_correct_auto"] is False

    def test_direct_item_is_correct_only_when_nothing_was_retrieved(self, make_item):
        item = make_item(category="direct", expected_source=None)
        cited = ["4_Expense_Policy.md"]
        assert source_check(item, retrieval_steps=0)["source_correct_auto"] is True
        assert source_check(item, retrieval_steps=1)["source_correct_auto"] is False
        assert source_check(item, retrieval_steps=0, cited_sources=cited)["source_correct_auto"] is False

    def test_direct_item_with_an_incomplete_stream_is_not_scored(self, make_item):
        item = make_item(category="direct", expected_source=None)
        incomplete = source_check(item, retrieval_steps=0, events_complete=False)
        assert incomplete["source_correct_auto"] is None
        assert source_check(item, retrieval_steps=None)["source_correct_auto"] is None

    def test_not_in_corpus_items_are_not_scored(self, make_item):
        item = make_item(category="not_in_corpus", expected_source=None)
        assert source_check(item, retrieval_steps=1, retrieved_sources=[ALL_DOCUMENTS]) == {
            "source_basis": None,
            "source_ranks": None,
            "source_correct_auto": None,
        }
