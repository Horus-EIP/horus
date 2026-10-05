import re
from collections import Counter

import pytest
from eval_testset import (
    CATEGORIES,
    IN_CORPUS_CATEGORIES,
    absent_term_errors,
    corpus_errors,
    corpus_problems,
    duplicate_errors,
    expected_sources,
    grounding_errors,
    schema_errors,
    select_items,
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


class TestValidators:
    def test_schema_flags_missing_fields_and_unknown_values(self, make_testset, make_item):
        broken = make_item(category="trivia", difficulty="extreme")
        del broken["expected_answer"]
        errors = schema_errors(make_testset([broken]))
        assert any("missing field 'expected_answer'" in e for e in errors)
        assert any("unknown category 'trivia'" in e for e in errors)
        assert any("unknown difficulty 'extreme'" in e for e in errors)

    def test_schema_flags_invalid_regex(self, make_testset, make_item):
        errors = schema_errors(make_testset([make_item(answer_patterns=["(unclosed"])]))
        assert any("invalid regex" in e for e in errors)

    def test_schema_requires_a_source_for_in_corpus_items(self, make_testset, make_item):
        errors = schema_errors(make_testset([make_item(expected_source=None)]))
        assert any("needs expected_source" in e for e in errors)

    def test_schema_requires_absent_terms_and_null_source_outside_the_corpus(
        self, make_testset, make_item
    ):
        item = make_item(category="not_in_corpus")
        errors = schema_errors(make_testset([item]))
        assert any("expected_source: null" in e for e in errors)
        assert any("absent_terms" in e for e in errors)

    def test_schema_limits_evidence_patterns_to_derived_answers(self, make_testset, make_item):
        item = make_item(evidence_patterns=[r"\$250"])
        errors = schema_errors(make_testset([item]))
        assert any("evidence_patterns is only for derived" in e for e in errors)

    def test_duplicates_are_reported(self, make_testset, make_item):
        errors = duplicate_errors(make_testset([make_item(), make_item()]))
        assert "duplicate id: 'x-01'" in errors
        assert any(e.startswith("duplicate question") for e in errors)

    def test_unknown_source_file_is_reported(self, make_testset, make_item, corpus):
        item = make_item(expected_source="6_Missing.md")
        errors = corpus_errors(make_testset([item]), corpus)
        assert errors == ["x-01: expected_source '6_Missing.md' is not in corpus"]

    def test_changed_document_is_reported(self, make_testset, corpus):
        testset = make_testset([])
        testset["corpus"] = {**testset["corpus"], "4_Expense_Policy.md": "0" * 64}
        errors = corpus_errors(testset, corpus)
        assert len(errors) == 1 and "4_Expense_Policy.md changed" in errors[0]

    def test_pattern_not_in_the_source_document_is_reported(
        self, make_testset, make_item, documents
    ):
        item = make_item(answer_patterns=[r"\$275/night \(US\)"])
        errors = grounding_errors(make_testset([item]), documents)
        assert len(errors) == 1 and "does not match 4_Expense_Policy.md" in errors[0]

    def test_derived_answers_are_grounded_by_evidence_patterns(
        self, make_testset, make_item, documents
    ):
        item = make_item(
            category="numeric",
            answer_patterns=[r"\b140\b"],
            evidence_patterns=[r"Breakfast \| \$25/person", r"Lunch \| \$99/person"],
        )
        errors = grounding_errors(make_testset([item]), documents)
        assert len(errors) == 1
        assert errors[0].startswith("x-01: evidence_patterns") and "Lunch" in errors[0]

    def test_absent_term_found_in_a_document_is_reported(self, make_testset, make_item, documents):
        item = make_item(category="not_in_corpus", expected_source=None, absent_terms=["YubiKey"])
        errors = absent_term_errors(make_testset([item]), documents)
        assert errors == ["x-01: absent term 'YubiKey' appears in 5_IT_Security_Policy.md"]

    def test_absent_terms_match_whole_words_only(self, make_testset, make_item, documents):
        item = make_item(category="not_in_corpus", expected_source=None, absent_terms=["pet"])
        assert absent_term_errors(make_testset([item]), documents) == []

    def test_patterns_that_accept_a_refusal_are_reported(self, make_testset, make_item):
        item = make_item(answer_patterns=[r"information"], expected_answer="information")
        errors = self_consistency_errors(make_testset([item]))
        assert any("accept the non-answer" in e for e in errors)

    def test_expected_answer_must_pass_its_own_patterns(self, make_testset, make_item):
        item = make_item(expected_answer="$300 per night.")
        errors = self_consistency_errors(make_testset([item]))
        assert errors == ["x-01: expected_answer fails its own answer_patterns"]


class TestCorpusProblems:
    def test_missing_and_duplicated_documents_are_reported(self):
        problems = corpus_problems(["a.md", "b.md", "c.md"], ["a.md", "b.md", "b.md"])
        assert problems == [
            "c.md is not in the knowledge store",
            "b.md is stored 2 times; delete the duplicates so retrieval is not skewed",
        ]

    def test_complete_corpus_has_no_problem(self):
        assert corpus_problems(["a.md"], ["a.md", "other.pdf"]) == []


class TestSelectItems:
    @pytest.fixture
    def pool(self, make_item):
        return [
            make_item(id="a", category="lookup"),
            make_item(id="b", category="direct"),
            make_item(id="c", category="lookup"),
        ]

    def test_without_filters_keeps_everything_in_order(self, pool):
        assert [i["id"] for i in select_items(pool)] == ["a", "b", "c"]

    def test_filters_by_id_category_and_limit(self, pool):
        assert [i["id"] for i in select_items(pool, ids=["b", "c"])] == ["b", "c"]
        assert [i["id"] for i in select_items(pool, categories=["lookup"])] == ["a", "c"]
        assert [i["id"] for i in select_items(pool, categories=["lookup"], limit=1)] == ["a"]

    def test_in_corpus_categories_exclude_direct_and_refusals(self):
        assert IN_CORPUS_CATEGORIES == {"lookup", "numeric", "multi_hop"}
