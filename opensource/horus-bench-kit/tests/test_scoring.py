# SPDX-License-Identifier: Apache-2.0
import pytest

from horus_bench_kit.scoring import (
    NO_FALLBACKS,
    ROUTE_AGENT,
    ROUTE_DIRECT,
    SOURCE_BASIS_CITED,
    SOURCE_BASIS_RETRIEVAL,
    answer_correct,
    detect_fallback,
    expected_route,
    expected_sources,
    missing_patterns,
    normalize_answer,
    route_correct,
    source_check,
    source_key,
    source_ranks,
)

MARKERS = {
    "loop": "could not settle on one answer",
    "timeout": "ran out of time",
}
LOOP_TEXT = "I could not settle on one answer from these passages. 14"
TIMEOUT_TEXT = "The model ran out of time before answering (14 lanterns?)."
ALL_DOCUMENTS = [
    "ferry-timetable.md",
    "harbour-rules.md",
    "lighthouse.md",
    "fish-market.md",
    "north-pier.md",
]


class TestNormalizeAnswer:
    def test_full_width_digits_and_ideographic_stop_are_folded(self):
        assert normalize_answer("Ｑ４ ２０２５ $4。2M") == "Q4 2025 $4.2M"

    def test_markdown_emphasis_curly_quotes_and_no_break_spaces_are_removed(self):
        assert normalize_answer("**$4.2M** — it’s `final`") == "$4.2M — it's final"

    def test_empty_values_become_empty_text(self):
        assert normalize_answer(None) == ""
        assert normalize_answer("") == ""


class TestAnswerCorrect:
    def test_all_patterns_must_match(self, make_item):
        item = make_item(answer_patterns=[r"Odile\s+Brandt", r"harbour\s+master"])
        assert answer_correct(item, "The harbour master is Odile Brandt.")
        assert not answer_correct(item, "It is Odile Brandt.")

    def test_matching_ignores_case_and_markdown(self, make_item):
        item = make_item(answer_patterns=[r"\b4\.2\s*(m\b|million)"])
        assert answer_correct(item, "Takings were **$4.2 Million**.")

    def test_full_width_answers_still_match(self, make_item):
        item = make_item(answer_patterns=[r"\b4\.2\s*(m\b|million)"])
        assert answer_correct(item, "$４。２M")

    def test_blank_answer_is_never_correct(self, make_item):
        item = make_item(answer_patterns=[r".*"])
        assert not answer_correct(item, "   ")
        assert not answer_correct(item, None)

    @pytest.mark.parametrize("fallback", [LOOP_TEXT, TIMEOUT_TEXT])
    def test_a_fallback_text_is_never_correct_even_when_the_patterns_match(
        self, make_item, fallback
    ):
        item = make_item()
        assert answer_correct(item, fallback)
        assert not answer_correct(item, fallback, MARKERS)

    def test_missing_patterns_lists_what_did_not_match(self):
        patterns = [r"Island\s+run", r"Lighthouse\s+run"]
        assert missing_patterns(patterns, "Island run and the sunset cruise") == [
            r"Lighthouse\s+run"
        ]


class TestFallbackDetection:
    def test_without_markers_nothing_is_a_fallback(self):
        assert NO_FALLBACKS == {}
        assert detect_fallback(LOOP_TEXT) is None

    def test_the_marker_name_is_reported(self):
        assert detect_fallback(LOOP_TEXT, MARKERS) == "loop"
        assert detect_fallback(TIMEOUT_TEXT, MARKERS) == "timeout"

    def test_markers_match_after_normalisation_and_in_marker_order(self):
        both = "**Ran out of time** and could not settle on one answer."
        assert detect_fallback(both, MARKERS) == "loop"
        assert detect_fallback(both, dict(reversed(list(MARKERS.items())))) == "timeout"

    def test_regular_answers_have_no_fallback(self):
        assert detect_fallback("Fourteen lanterns.", MARKERS) is None
        assert detect_fallback(None, MARKERS) is None


class TestRoutes:
    def test_direct_items_expect_a_direct_answer_and_others_retrieval(self, make_item):
        assert expected_route(make_item(category="direct")) == ROUTE_DIRECT
        assert expected_route(make_item(category="not_in_corpus")) == ROUTE_AGENT
        assert expected_route(make_item(category="multi_hop")) == ROUTE_AGENT

    def test_route_correct_compares_with_the_observed_route(self, make_item):
        assert route_correct(make_item(category="direct"), ROUTE_DIRECT) is True
        assert route_correct(make_item(category="direct"), ROUTE_AGENT) is False
        assert route_correct(make_item(), None) is None


class TestExpectedSources:
    def test_one_name_a_list_or_none(self, make_item):
        assert expected_sources(make_item()) == ["north-pier.md"]
        assert expected_sources(make_item(expected_source=["a.md", "b.md"])) == ["a.md", "b.md"]
        assert expected_sources(make_item(expected_source=None)) == []


class TestSourceRanks:
    def test_source_titles_compare_by_file_stem(self):
        assert source_key("north-pier.md") == "north-pier"
        assert source_key("docs\\North-Pier.MD") == "north-pier"
        assert source_key("north-pier") == "north-pier"

    def test_rank_is_the_position_among_distinct_documents(self, make_item):
        ranking = ["harbour-rules.md", "harbour-rules", "north-pier.md"]
        assert source_ranks(make_item(), [ranking]) == [2]

    def test_best_rank_over_every_retrieval(self, make_item):
        rankings = [ALL_DOCUMENTS, ["north-pier.md", "harbour-rules.md"]]
        assert source_ranks(make_item(), rankings) == [1]

    def test_document_never_retrieved_has_no_rank(self, make_item):
        item = make_item(expected_source=["ferry-timetable.md", "north-pier.md"])
        assert source_ranks(item, [["ferry-timetable.md"], []]) == [1, None]


class TestSourceCheck:
    def test_expected_document_ranked_first_is_correct(self, make_item):
        ranking = ["north-pier.md", "harbour-rules.md"]
        assert source_check(make_item(), retrieval_steps=1, retrieved_sources=[ranking]) == {
            "source_basis": SOURCE_BASIS_RETRIEVAL,
            "source_ranks": [1],
            "source_correct_auto": True,
        }

    def test_whole_corpus_returned_with_the_document_last_is_not_correct(self, make_item):
        result = source_check(make_item(), retrieved_sources=[ALL_DOCUMENTS])
        assert result["source_ranks"] == [5]
        assert result["source_correct_auto"] is False

    def test_two_document_item_needs_both_documents_in_the_top_two(self, make_item):
        item = make_item(expected_source=["ferry-timetable.md", "north-pier.md"])
        top_two = ["north-pier", "ferry-timetable.md", "harbour-rules.md"]
        assert source_check(item, retrieved_sources=[top_two])["source_correct_auto"] is True
        assert source_check(item, retrieved_sources=[ALL_DOCUMENTS])["source_correct_auto"] is False
        assert source_check(item, retrieved_sources=[["north-pier.md"]])["source_ranks"] == [
            None,
            1,
        ]

    def test_retrieval_without_titles_is_not_observable(self, make_item):
        assert source_check(make_item(), retrieval_steps=1, retrieved_sources=None) == {
            "source_basis": None,
            "source_ranks": None,
            "source_correct_auto": None,
        }

    def test_incomplete_event_stream_cannot_prove_a_wrong_source(self, make_item):
        missed = source_check(make_item(), retrieved_sources=[], events_complete=False)
        assert missed["source_correct_auto"] is None
        seen = source_check(
            make_item(), retrieved_sources=[["north-pier.md"]], events_complete=False
        )
        assert seen["source_correct_auto"] is True

    def test_citations_take_precedence_over_retrieval(self, make_item):
        result = source_check(
            make_item(), retrieved_sources=[ALL_DOCUMENTS], cited_sources=["north-pier.md"]
        )
        assert result == {
            "source_basis": SOURCE_BASIS_CITED,
            "source_ranks": None,
            "source_correct_auto": True,
        }
        assert (
            source_check(make_item(), cited_sources=["harbour-rules.md"])["source_correct_auto"]
            is False
        )

    def test_direct_item_is_correct_only_when_nothing_was_retrieved(self, make_item):
        item = make_item(category="direct", expected_source=None)
        assert source_check(item, retrieval_steps=0)["source_correct_auto"] is True
        assert source_check(item, retrieval_steps=1)["source_correct_auto"] is False
        cited = ["north-pier.md"]
        assert (
            source_check(item, retrieval_steps=0, cited_sources=cited)["source_correct_auto"]
            is False
        )

    def test_direct_item_with_an_incomplete_stream_or_unknown_retrieval_is_not_scored(
        self, make_item
    ):
        item = make_item(category="direct", expected_source=None)
        assert (
            source_check(item, retrieval_steps=0, events_complete=False)["source_correct_auto"]
            is None
        )
        assert source_check(item, retrieval_steps=None)["source_correct_auto"] is None

    def test_not_in_corpus_items_are_not_scored(self, make_item):
        item = make_item(category="not_in_corpus", expected_source=None)
        assert source_check(item, retrieval_steps=1, retrieved_sources=[ALL_DOCUMENTS]) == {
            "source_basis": None,
            "source_ranks": None,
            "source_correct_auto": None,
        }
