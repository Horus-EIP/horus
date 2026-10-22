# SPDX-License-Identifier: Apache-2.0
import json
import sys

import pytest

from horus_bench_kit.testset import (
    CATEGORIES,
    DEFAULT_NON_ANSWERS,
    IN_CORPUS_CATEGORIES,
    absent_term_errors,
    corpus_errors,
    corpus_root,
    declared_non_answers,
    duplicate_errors,
    file_sha256,
    grounding_errors,
    load_testset,
    read_documents,
    schema_errors,
    select_items,
    self_consistency_errors,
    validate_testset,
)


class TestValidators:
    def test_schema_flags_missing_fields_and_unknown_values(self, make_testset, make_item):
        broken = make_item(category="trivia", difficulty="extreme")
        del broken["expected_answer"]
        errors = schema_errors(make_testset([broken]))
        assert "t-01: missing field 'expected_answer'" in errors
        assert "t-01: unknown category 'trivia'" in errors
        assert "t-01: unknown difficulty 'extreme'" in errors

    def test_schema_flags_missing_top_level_keys(self):
        assert schema_errors({"items": []}) == [
            "testset: missing top-level key 'version'",
            "testset: missing top-level key 'corpus_dir'",
            "testset: missing top-level key 'corpus'",
        ]

    def test_schema_flags_invalid_regex(self, make_testset, make_item):
        errors = schema_errors(make_testset([make_item(answer_patterns=["(unclosed"])]))
        assert any("invalid regex '(unclosed' in answer_patterns" in e for e in errors)

    def test_schema_requires_a_source_for_in_corpus_items(self, make_testset, make_item):
        errors = schema_errors(make_testset([make_item(expected_source=None)]))
        assert errors == ["t-01: an in-corpus item needs expected_source"]

    def test_schema_requires_absent_terms_and_null_source_outside_the_corpus(
        self, make_testset, make_item
    ):
        errors = schema_errors(make_testset([make_item(category="not_in_corpus")]))
        assert errors == [
            "t-01: a not_in_corpus item must have expected_source: null",
            "t-01: a not_in_corpus item needs a non-empty absent_terms list",
        ]

    def test_schema_limits_evidence_patterns_to_derived_answers(self, make_testset, make_item):
        errors = schema_errors(make_testset([make_item(evidence_patterns=[r"\$12"])]))
        assert errors == [
            "t-01: evidence_patterns is only for derived numeric or multi_hop answers"
        ]

    def test_schema_checks_the_optional_context_file_and_non_answers(self, make_testset, make_item):
        testset = make_testset([make_item(context_file=" ")], non_answers=["ok", ""])
        assert schema_errors(testset) == [
            "testset: non_answers must be a non-empty list of non-empty strings",
            "t-01: context_file must be a non-empty string",
        ]
        assert schema_errors(make_testset([make_item(context_file="context/t-01.txt")])) == []

    def test_duplicates_are_reported(self, make_testset, make_item):
        errors = duplicate_errors(
            make_testset(
                [make_item(), make_item(question=" HOW many lanterns hang on the north pier? ")]
            )
        )
        assert errors == [
            "duplicate id: 't-01'",
            "duplicate question: ' HOW many lanterns hang on the north pier? '",
        ]

    def test_unknown_source_file_is_reported(self, make_testset, make_item, corpus):
        errors = corpus_errors(make_testset([make_item(expected_source="lighthouse.md")]), corpus)
        assert errors == ["t-01: expected_source 'lighthouse.md' is not in corpus"]

    def test_missing_and_changed_documents_are_reported(self, make_testset, corpus):
        testset = make_testset([])
        testset["corpus"] = {
            **testset["corpus"],
            "north-pier.md": "0" * 64,
            "lighthouse.md": "1" * 64,
        }
        errors = corpus_errors(testset, corpus)
        assert len(errors) == 2
        assert errors[0].startswith("corpus: north-pier.md changed (sha256 ")
        assert errors[1].startswith("corpus: lighthouse.md does not exist under ")

    def test_document_hashes_ignore_windows_line_endings(self, tmp_path):
        (tmp_path / "lf.txt").write_bytes(b"one\ntwo\n")
        (tmp_path / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
        assert file_sha256(tmp_path / "lf.txt") == file_sha256(tmp_path / "crlf.txt")

    def test_pattern_not_in_the_source_document_is_reported(
        self, make_testset, make_item, documents
    ):
        item = make_item(answer_patterns=[r"\bsixteen\b"])
        assert grounding_errors(make_testset([item]), documents) == [
            "t-01: answer_patterns '\\\\bsixteen\\\\b' does not match north-pier.md"
        ]

    def test_derived_answers_are_grounded_by_evidence_patterns(
        self, make_testset, make_item, documents
    ):
        item = make_item(
            category="numeric",
            question="What do two adults pay for the island run and back?",
            expected_answer="$24.",
            expected_source="ferry-timetable.md",
            answer_patterns=[r"\b24\b"],
            evidence_patterns=[r"Island run \| \$6/adult", r"Return \| \$12/adult"],
        )
        errors = grounding_errors(make_testset([item]), documents)
        assert len(errors) == 1
        assert errors[0].startswith("t-01: evidence_patterns") and "Return" in errors[0]

    def test_items_whose_document_is_missing_are_not_grounded(
        self, make_testset, make_item, documents
    ):
        item = make_item(expected_source="lighthouse.md", answer_patterns=[r"\bnowhere\b"])
        assert grounding_errors(make_testset([item]), documents) == []

    def test_absent_term_found_in_a_document_is_reported(self, make_testset, make_item, documents):
        item = make_item(category="not_in_corpus", expected_source=None, absent_terms=["Lanterns"])
        assert absent_term_errors(make_testset([item]), documents) == [
            "t-01: absent term 'Lanterns' appears in north-pier.md"
        ]

    def test_absent_terms_match_whole_words_only(self, make_testset, make_item, documents):
        item = make_item(
            category="not_in_corpus", expected_source=None, absent_terms=["pie", "harbo"]
        )
        assert absent_term_errors(make_testset([item]), documents) == []

    def test_patterns_that_accept_a_non_answer_are_reported(self, make_testset, make_item):
        item = make_item(answer_patterns=[r"know"], expected_answer="I know.")
        assert self_consistency_errors(make_testset([item])) == [
            't-01: answer_patterns accept the non-answer "I don\'t know."'
        ]

    def test_a_test_set_can_declare_its_own_non_answers(self, make_testset, make_item):
        item = make_item(answer_patterns=[r"\bpier\b"], expected_answer="On the north pier.")
        testset = make_testset([item], non_answers=["Ask at the pier office."])
        assert declared_non_answers(testset) == ("Ask at the pier office.",)
        assert declared_non_answers(make_testset([item])) == DEFAULT_NON_ANSWERS
        assert self_consistency_errors(testset) == [
            "t-01: answer_patterns accept the non-answer 'Ask at the pier office.'"
        ]
        assert self_consistency_errors(testset, non_answers=["No idea."]) == []

    def test_not_in_corpus_items_may_accept_non_answers(self, make_testset, make_item):
        item = make_item(
            category="not_in_corpus",
            expected_source=None,
            expected_answer="I don't know.",
            answer_patterns=[r"know"],
            absent_terms=["kayak"],
        )
        assert self_consistency_errors(make_testset([item])) == []

    def test_fallback_markers_make_an_expected_answer_fail(self, make_testset, make_item):
        item = make_item(expected_answer="14, but I ran out of time.")
        testset = make_testset([item])
        assert self_consistency_errors(testset) == []
        assert self_consistency_errors(testset, markers={"timeout": "ran out of time"}) == [
            "t-01: expected_answer fails its own answer_patterns"
        ]

    def test_expected_answer_must_pass_its_own_patterns(self, make_testset, make_item):
        item = make_item(expected_answer="Twelve lanterns.")
        assert self_consistency_errors(make_testset([item])) == [
            "t-01: expected_answer fails its own answer_patterns"
        ]

    def test_a_valid_test_set_has_no_problem(self, make_testset, make_item, corpus):
        items = [
            make_item(),
            make_item(
                id="t-02",
                category="multi_hop",
                difficulty="medium",
                question="Who is the harbour master, and when does the first ferry leave?",
                expected_answer="Odile Brandt; the first ferry leaves at 06:40.",
                expected_source=["harbour-rules.md", "ferry-timetable.md"],
                answer_patterns=[r"Brandt", r"06:40"],
            ),
            make_item(
                id="t-03",
                category="not_in_corpus",
                question="Is there a kayak rental?",
                expected_answer="The documents do not say.",
                expected_source=None,
                answer_patterns=[r"do\s+not\s+say"],
                absent_terms=["kayak"],
            ),
        ]
        assert validate_testset(make_testset(items), corpus) == []

    def test_validation_stops_at_schema_errors(self, make_testset, make_item, corpus):
        assert validate_testset(make_testset([make_item(category="trivia")]), corpus) == [
            "t-01: unknown category 'trivia'"
        ]

    @pytest.mark.parametrize(
        ("items", "message"),
        [
            (["t-01"], "item #0: must be a mapping of fields"),
            ({"t-01": {}}, "testset: items must be a list of questions"),
            ("t-01", "testset: items must be a list of questions"),
        ],
    )
    def test_items_of_the_wrong_shape_are_reported(self, make_testset, corpus, items, message):
        testset = make_testset(items)
        assert schema_errors(testset) == [message]
        assert validate_testset(testset, corpus) == [message]

    @pytest.mark.parametrize("corpus_value", [["north-pier.md"], "north-pier.md", {1: "0" * 64}])
    def test_a_corpus_that_is_not_a_mapping_of_file_names_is_reported(
        self, make_testset, make_item, corpus, corpus_value
    ):
        testset = {**make_testset([make_item()]), "corpus": corpus_value}
        message = "testset: corpus must map document file names to their SHA-256"
        assert validate_testset(testset, corpus) == [message]

    @pytest.mark.parametrize("source", [5, 2.5, True, {"north-pier.md": 1}])
    def test_an_expected_source_of_the_wrong_type_is_reported(
        self, make_testset, make_item, corpus, source
    ):
        expected = ["t-01: expected_source must be null, a file name or a list of file names"]
        assert (
            validate_testset(make_testset([make_item(expected_source=source)]), corpus) == expected
        )

    def test_a_category_of_the_wrong_type_is_an_unknown_category(self, make_testset, make_item):
        assert schema_errors(make_testset([make_item(category=["lookup"])])) == [
            "t-01: unknown category ['lookup']"
        ]


class TestLoadTestset:
    def test_json_test_sets_need_no_extra_package(
        self, tmp_path, monkeypatch, make_testset, make_item
    ):
        monkeypatch.setitem(sys.modules, "yaml", None)
        path = tmp_path / "harbour.JSON"
        path.write_text(json.dumps(make_testset([make_item()])), encoding="utf-8")
        assert load_testset(path)["items"][0]["id"] == "t-01"

    def test_yaml_without_pyyaml_explains_what_to_install(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "yaml", None)
        path = tmp_path / "harbour.yaml"
        path.write_text("version: 1.0.0\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match=r"horus-bench-kit\[yaml\]"):
            load_testset(path)

    def test_yaml_test_sets_load_with_pyyaml(self, tmp_path):
        pytest.importorskip("yaml")
        path = tmp_path / "harbour.yml"
        path.write_text("version: 1.0.0\nitems: []\n", encoding="utf-8")
        assert load_testset(path) == {"version": "1.0.0", "items": []}

    def test_yaml_only_reads_a_json_file_as_yaml(self, tmp_path):
        pytest.importorskip("yaml")
        path = tmp_path / "harbour.json"
        path.write_text('{"version": "1.0.0", "items": [],}\n', encoding="utf-8")
        with pytest.raises(ValueError):
            load_testset(path)
        assert load_testset(path, yaml_only=True) == {"version": "1.0.0", "items": []}

    def test_corpus_root_is_relative_to_the_test_set(self, tmp_path):
        assert (
            corpus_root({"corpus_dir": "../docs"}, tmp_path / "sets" / "t.json")
            == (tmp_path / "docs").resolve()
        )


class TestExamples:
    def test_the_json_example_is_valid(self, examples):
        testset = load_testset(examples / "testset.json")
        assert validate_testset(testset, corpus_root(testset, examples / "testset.json")) == []

    def test_the_yaml_example_is_the_same_test_set(self, examples):
        pytest.importorskip("yaml")
        assert load_testset(examples / "testset.yaml") == load_testset(examples / "testset.json")

    def test_the_example_covers_every_category_and_has_a_context_for_each_document_question(
        self, examples
    ):
        testset = load_testset(examples / "testset.json")
        assert {item["category"] for item in testset["items"]} == set(CATEGORIES)
        for item in testset["items"]:
            has_context = (examples / "context" / f"{item['id']}.txt").is_file()
            assert has_context == (item["category"] != "direct"), item["id"]

    def test_example_documents_are_read_with_their_text(self, examples):
        testset = load_testset(examples / "testset.json")
        documents = read_documents(testset, corpus_root(testset, examples / "testset.json"))
        assert sorted(documents) == sorted(testset["corpus"])


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
        assert CATEGORIES == ("lookup", "numeric", "multi_hop", "not_in_corpus", "direct")
