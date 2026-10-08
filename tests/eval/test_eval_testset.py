import re
from collections import Counter

from eval_testset import (
    CANNED_NON_ANSWERS,
    CATEGORIES,
    absent_term_errors,
    corpus_errors,
    corpus_problems,
    duplicate_errors,
    expected_sources,
    grounding_errors,
    schema_errors,
    self_consistency_errors,
    validate_testset,
)


class TestShippedTestset:
    def test_has_exactly_100_items(self, items):
        assert len(items) == 100

    def test_ids_are_unique(self, items):
        ids = [item["id"] for item in items]
        assert len(set(ids)) == 100

    def test_every_item_matches_the_schema(self, testset):
        assert schema_errors(testset) == []

    def test_ids_and_questions_are_not_duplicated(self, testset):
        assert duplicate_errors(testset) == []

    def test_expected_sources_exist_and_corpus_hashes_match(self, testset, corpus):
        assert corpus_errors(testset, corpus) == []

    def test_in_corpus_answer_patterns_match_their_source_document(self, testset, documents):
        assert grounding_errors(testset, documents) == []

    def test_not_in_corpus_terms_are_absent_from_every_document(self, testset, documents):
        assert absent_term_errors(testset, documents) == []

    def test_expected_answers_pass_their_own_patterns_and_non_answers_fail(self, testset):
        assert self_consistency_errors(testset) == []

    def test_full_validation_reports_no_errors(self, testset, corpus):
        assert validate_testset(testset, corpus) == []

    def test_about_ten_questions_are_not_in_the_corpus(self, items):
        count = Counter(item["category"] for item in items)["not_in_corpus"]
        assert 8 <= count <= 12

    def test_greetings_and_arithmetic_expect_a_direct_answer_with_no_source(self, items):
        direct = [item for item in items if item["category"] == "direct"]
        assert len(direct) >= 3
        assert all(item["expected_source"] is None for item in direct)

    def test_every_category_and_document_is_covered(self, testset, items):
        assert {item["category"] for item in items} == set(CATEGORIES)
        cited = {source for item in items for source in expected_sources(item)}
        assert cited == set(testset["corpus"])

    def test_cross_document_items_name_every_document_they_need(self, items):
        multi_source = [item for item in items if len(expected_sources(item)) > 1]
        assert multi_source
        assert all(item["category"] == "multi_hop" for item in multi_source)

    def test_numeric_alternatives_start_at_a_word_boundary(self, items):
        unanchored = re.compile(r"(?:^|(?<!\\)\|)\d")
        offenders = [
            (item["id"], pattern)
            for item in items
            for pattern in item["answer_patterns"]
            if unanchored.search(pattern)
        ]
        assert offenders == []

    def test_version_is_semantic(self, testset):
        major, minor, patch = str(testset["version"]).split(".")
        assert all(part.isdigit() for part in (major, minor, patch))


class TestAgentNonAnswers:
    def test_patterns_that_accept_an_agent_non_answer_are_reported(self, make_testset, make_item):
        item = make_item(answer_patterns=[r"information"], expected_answer="information")
        errors = self_consistency_errors(make_testset([item]))
        assert errors == [f"x-01: answer_patterns accept the non-answer {text!r}" for text in CANNED_NON_ANSWERS]


class TestCorpusProblems:
    def test_missing_and_duplicated_documents_are_reported(self):
        problems = corpus_problems(["a.md", "b.md", "c.md"], ["a.md", "b.md", "b.md"])
        assert problems == [
            "c.md is not in the knowledge store",
            "b.md is stored 2 times; delete the duplicates so retrieval is not skewed",
        ]

    def test_complete_corpus_has_no_problem(self):
        assert corpus_problems(["a.md"], ["a.md", "other.pdf"]) == []
