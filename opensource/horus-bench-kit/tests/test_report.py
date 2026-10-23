# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit.report import (
    DEFAULT_PROFILE,
    REPORT_KIND,
    SCHEMA_VERSION,
    Profile,
    blank_review,
    build_report,
    build_summary,
    field_stats,
    manual_review_summary,
    question_record,
    rank_summary,
    resummarize,
    usage_summary,
)
from horus_bench_kit.scoring import ROUTE_AGENT, ROUTE_DIRECT, SOURCE_BASIS_RETRIEVAL

ALL_DOCUMENTS = [
    "ferry-timetable.md",
    "harbour-rules.md",
    "lighthouse.md",
    "fish-market.md",
    "north-pier.md",
]
CORE_ITEM_KEYS = [
    "id",
    "category",
    "difficulty",
    "question",
    "expected_answer",
    "expected_source",
    "expected_route",
    "status",
    "error",
]
SCORE_KEYS = [
    "answer",
    "retrieval_steps",
    "retrieved_sources",
    "cited_sources",
    "fallback",
    "answer_correct_auto",
    "missing_patterns",
    "source_basis",
    "source_ranks",
    "source_correct_auto",
    "route_correct",
    "review",
]
OUTCOME_KEYS = ["observed_route", "models", "timing_source", "ttft_s", "total_s", "usage"]
SUMMARY_KEYS = [
    "questions",
    "answer_correct_auto",
    "source_correct_auto",
    "source_rank",
    "route_correct",
    "total_s",
    "status",
    "fallbacks",
    "source_basis",
    "ttft_s",
    "usage",
    "manual_review",
    "by_category",
]


@pytest.fixture
def lookup_item(make_item):
    return make_item(id="pier-01")


@pytest.fixture
def direct_item(make_item):
    return make_item(
        id="direct-01",
        category="direct",
        question="What is 2 + 2?",
        expected_answer="4",
        expected_source=None,
        answer_patterns=[r"\b4\b"],
    )


def chat_outcome(**overrides):
    outcome = {
        "mode": "chat",
        "status": "ok",
        "observed_route": ROUTE_AGENT,
        "models": ["harbour-7b"],
        "timing_source": "http",
        "ttft_s": 0.8,
        "total_s": 4.0,
        "usage": {"prompt_tokens": 300, "completion_tokens": 20},
        "answer": "**Fourteen** lanterns hang there.",
        "retrieval_steps": 1,
        "retrieved_sources": [["north-pier.md", "harbour-rules.md"]],
        "cited_sources": None,
    }
    outcome.update(overrides)
    return outcome


def retrieval_outcome(ranking):
    return {
        "mode": "retrieval",
        "status": "ok",
        "timing_source": "http",
        "total_s": 0.08,
        "retrieved_sources": [ranking],
    }


class TestQuestionRecord:
    def test_keys_follow_the_item_the_outcome_fields_then_the_scores(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        assert list(record) == CORE_ITEM_KEYS + OUTCOME_KEYS + SCORE_KEYS

    def test_correct_answer_with_its_source(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is True
        assert record["route_correct"] is True
        assert record["missing_patterns"] == []
        assert record["expected_source"] == ["north-pier.md"]
        assert record["expected_route"] == ROUTE_AGENT
        assert record["source_basis"] == SOURCE_BASIS_RETRIEVAL
        assert record["source_ranks"] == [1]
        assert record["models"] == ["harbour-7b"]
        assert record["usage"] == {"prompt_tokens": 300, "completion_tokens": 20}
        assert record["total_s"] == 4.0
        assert record["ttft_s"] == 0.8
        assert record["fallback"] is None

    def test_record_keeps_empty_slots_for_two_reviewers(self, lookup_item):
        assert question_record(lookup_item, chat_outcome())["review"] == [
            {"reviewer": None, "answer_correct": None, "comment": None},
            {"reviewer": None, "answer_correct": None, "comment": None},
        ]

    def test_wrong_answer_and_wrong_source(self, lookup_item):
        outcome = chat_outcome(
            answer="Twelve.", retrieved_sources=[["harbour-rules.md", "north-pier.md"]]
        )
        record = question_record(lookup_item, outcome)
        assert record["answer_correct_auto"] is False
        assert record["missing_patterns"] == [r"\b(?:14|fourteen)\b"]
        assert record["source_correct_auto"] is False
        assert record["source_ranks"] == [2]

    def test_a_target_that_cannot_see_sources_leaves_them_unscored(self, lookup_item):
        outcome = chat_outcome(retrieval_steps=None, retrieved_sources=None, observed_route=None)
        record = question_record(lookup_item, outcome)
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is None
        assert record["source_basis"] is None
        assert record["route_correct"] is None

    def test_failed_question_counts_as_a_wrong_answer_and_leaves_the_source_open(self, lookup_item):
        outcome = {
            "mode": "chat",
            "status": "timeout",
            "error": "no answer",
            "timing_source": "poll",
        }
        record = question_record(lookup_item, outcome)
        assert record["status"] == "timeout"
        assert record["error"] == "no answer"
        assert record["answer_correct_auto"] is False
        assert record["source_correct_auto"] is None
        assert record["route_correct"] is None
        assert record["models"] == []

    def test_an_outcome_without_status_is_an_error(self, lookup_item):
        assert question_record(lookup_item, {})["status"] == "error"

    def test_direct_answer_without_sources(self, direct_item):
        outcome = chat_outcome(
            observed_route=ROUTE_DIRECT,
            answer="4",
            retrieval_steps=0,
            retrieved_sources=[],
            ttft_s=None,
        )
        record = question_record(direct_item, outcome)
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is True
        assert record["route_correct"] is True
        assert record["expected_source"] is None

    def test_direct_item_sent_to_retrieval_has_a_wrong_source_and_route(self, direct_item):
        record = question_record(direct_item, chat_outcome(answer="4", retrieved_sources=None))
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is False
        assert record["route_correct"] is False

    def test_retrieval_mode_scores_only_the_source(self, lookup_item):
        record = question_record(lookup_item, retrieval_outcome(["north-pier.md"]))
        assert record["answer_correct_auto"] is None
        assert record["missing_patterns"] is None
        assert record["route_correct"] is None
        assert record["source_correct_auto"] is True
        assert record["source_ranks"] == [1]
        assert record["retrieval_steps"] is None
        assert record["review"] is None

    def test_retrieval_mode_with_the_whole_corpus_ranked_needs_the_document_first(
        self, lookup_item
    ):
        record = question_record(lookup_item, retrieval_outcome(ALL_DOCUMENTS))
        assert record["source_correct_auto"] is False
        assert record["source_ranks"] == [5]

    def test_retrieval_mode_does_not_score_direct_items(self, direct_item):
        assert (
            question_record(direct_item, retrieval_outcome(ALL_DOCUMENTS))["source_correct_auto"]
            is None
        )


class TestProfile:
    def test_the_default_profile_is_the_kit_report(self):
        assert DEFAULT_PROFILE.kind == REPORT_KIND == "horus-bench-kit-eval"
        assert DEFAULT_PROFILE.schema_version == SCHEMA_VERSION == 1
        assert dict(DEFAULT_PROFILE.fallback_markers) == {}

    def test_outcome_fields_are_copied_in_profile_order_and_lists_are_copied(self, lookup_item):
        profile = Profile(outcome_fields=("session", "devices", "total_s"))
        devices = ["cpu"]
        record = question_record(lookup_item, chat_outcome(session="s-9", devices=devices), profile)
        assert list(record) == CORE_ITEM_KEYS + ["session", "devices", "total_s"] + SCORE_KEYS
        assert record["devices"] == ["cpu"] and record["devices"] is not devices
        assert record["session"] == "s-9"

    def test_fallback_markers_flag_the_answer_and_make_it_wrong(self, lookup_item):
        profile = Profile(fallback_markers={"loop": "could not settle"})
        outcome = chat_outcome(answer="I could not settle on one answer. 14")
        assert question_record(lookup_item, outcome)["answer_correct_auto"] is True
        record = question_record(lookup_item, outcome, profile)
        assert record["fallback"] == "loop"
        assert record["answer_correct_auto"] is False

    def test_final_status_can_rewrite_a_status_before_scoring(self, lookup_item):
        def watchdog(status, error, answer):
            if status == "ok" and "stopped" in (answer or ""):
                return "timeout", error or "stopped by the watchdog"
            return status, error

        profile = Profile(final_status=watchdog)
        record = question_record(lookup_item, chat_outcome(answer="Request stopped."), profile)
        assert (record["status"], record["error"]) == ("timeout", "stopped by the watchdog")
        assert question_record(lookup_item, chat_outcome(), profile)["status"] == "ok"

    def test_summary_sections_sit_between_ttft_and_manual_review(self, lookup_item):
        profile = Profile(
            summary_sections=(("queue_s", field_stats("queue_s")), ("extra", lambda r: len(r)))
        )
        record = question_record(lookup_item, chat_outcome(), Profile(outcome_fields=("queue_s",)))
        record["queue_s"] = 0.5
        summary = build_summary([record], profile)
        keys = list(summary)
        assert keys[keys.index("ttft_s") + 1 : keys.index("manual_review")] == ["queue_s", "extra"]
        assert summary["queue_s"]["median"] == 0.5
        assert summary["extra"] == 1

    def test_categories_order_the_per_category_summary(self, make_item):
        records = [
            question_record(
                make_item(id="d", category="direct", expected_source=None), chat_outcome()
            ),
            question_record(make_item(id="l"), chat_outcome()),
        ]
        assert list(build_summary(records)["by_category"]) == ["lookup", "direct"]
        reverse = Profile(categories=("direct", "lookup"))
        assert list(build_summary(records, reverse)["by_category"]) == ["direct", "lookup"]


class TestSummary:
    def test_summary_keys_with_the_default_profile(self, lookup_item):
        assert list(build_summary([question_record(lookup_item, chat_outcome())])) == SUMMARY_KEYS

    def test_summary_totals_and_categories(self, lookup_item, direct_item):
        records = [
            question_record(lookup_item, chat_outcome()),
            question_record(
                lookup_item, chat_outcome(answer="Twelve", retrieved_sources=[ALL_DOCUMENTS])
            ),
            question_record(lookup_item, chat_outcome(retrieved_sources=None)),
            question_record(
                direct_item,
                chat_outcome(
                    observed_route=ROUTE_DIRECT,
                    answer="4",
                    retrieval_steps=0,
                    retrieved_sources=[],
                    total_s=1.0,
                    ttft_s=None,
                ),
            ),
        ]
        summary = build_summary(records)
        assert summary["questions"] == 4
        assert summary["answer_correct_auto"] == {"n": 4, "correct": 3, "pct": 75.0}
        assert summary["source_correct_auto"] == {"n": 3, "correct": 2, "pct": 66.7}
        assert summary["source_rank"]["n"] == 2
        assert summary["source_rank"]["first"] == 1
        assert summary["source_rank"]["max"] == 5
        assert summary["source_basis"] == {"retrieval": 3, "not_observable": 1}
        assert summary["status"] == {"ok": 4}
        assert summary["total_s"]["n"] == 4
        assert summary["ttft_s"]["n"] == 3
        assert summary["usage"]["questions"] == 4
        assert set(summary["by_category"]) == {"lookup", "direct"}
        assert summary["by_category"]["lookup"]["answer_correct_auto"]["correct"] == 2
        assert summary["manual_review"]["pending"] == 4

    def test_not_in_corpus_items_have_no_source_basis(self, make_item):
        item = make_item(category="not_in_corpus", expected_source=None, absent_terms=["kayak"])
        assert build_summary([question_record(item, chat_outcome())])["source_basis"] == {}

    def test_status_and_fallback_counts_keep_their_first_seen_order(self, lookup_item):
        profile = Profile(fallback_markers={"loop": "could not settle", "slow": "too slow"})
        records = [
            question_record(lookup_item, chat_outcome(status="timeout", answer=None), profile),
            question_record(lookup_item, chat_outcome(answer="Too slow, sorry."), profile),
            question_record(lookup_item, chat_outcome(answer="I could not settle."), profile),
            question_record(lookup_item, chat_outcome(answer="Too slow again."), profile),
        ]
        summary = build_summary(records, profile)
        assert list(summary["status"].items()) == [("timeout", 1), ("ok", 3)]
        assert list(summary["fallbacks"].items()) == [("slow", 2), ("loop", 1)]

    def test_rank_summary_counts_expected_documents_never_retrieved(self, make_item):
        item = make_item(expected_source=["ferry-timetable.md", "north-pier.md"])
        record = question_record(
            item, chat_outcome(retrieved_sources=[["north-pier.md", "harbour-rules.md"]])
        )
        assert rank_summary([record]) == {
            "n": 1,
            "mean": 1,
            "median": 1,
            "p90": 1,
            "min": 1,
            "max": 1,
            "sum": 1,
            "first": 1,
            "not_retrieved": 1,
        }

    def test_usage_summary_needs_a_usage_block(self):
        assert usage_summary([{"usage": None}, {}]) is None
        summary = usage_summary(
            [{"usage": {"prompt_tokens": 10, "completion_tokens": 4}}, {"usage": {}}]
        )
        assert summary["questions"] == 2
        assert summary["prompt_tokens"]["n"] == 1
        assert summary["completion_tokens"]["sum"] == 4


class TestManualReview:
    def review(self, first, second):
        slots = blank_review()
        slots[0].update(reviewer="ana", answer_correct=first)
        slots[1].update(reviewer="ben", answer_correct=second)
        return slots

    def test_counts_agreement_disagreement_and_pending(self):
        records = [
            {"id": "a", "review": self.review(True, True)},
            {"id": "b", "review": self.review(True, False)},
            {"id": "c", "review": self.review(False, False)},
            {"id": "d", "review": self.review(True, None)},
        ]
        assert manual_review_summary(records) == {
            "reviewed": 3,
            "pending": 1,
            "agreed_correct": 1,
            "disagreements": ["b"],
            "answer_correct_pct": 33.3,
        }

    def test_nothing_reviewed_has_no_percentage(self):
        summary = manual_review_summary([{"id": "a", "review": blank_review()}])
        assert summary["answer_correct_pct"] is None and summary["pending"] == 1

    def test_records_without_review_slots_are_not_pending(self):
        summary = manual_review_summary([{"id": "a", "review": None}])
        assert summary["pending"] == 0 and summary["reviewed"] == 0


class TestBuildReport:
    def test_top_level_keys_and_kind(self, lookup_item):
        report = build_report(
            label="harbour-7b",
            run={"target": "openai"},
            testset={"version": "1.0.0"},
            records=[question_record(lookup_item, chat_outcome())],
        )
        assert list(report) == [
            "kind",
            "schema_version",
            "label",
            "run",
            "testset",
            "summary",
            "questions",
        ]
        assert (report["kind"], report["schema_version"]) == ("horus-bench-kit-eval", 1)
        assert report["summary"]["questions"] == 1
        json.dumps(report)

    def test_product_sections_sit_between_the_test_set_and_the_summary(self):
        profile = Profile(kind="acme-eval", schema_version=3)
        report = build_report(
            label="x",
            run={},
            testset={},
            records=[],
            sections={"model": {"name": "m"}, "machine": {}},
            profile=profile,
        )
        assert list(report) == [
            "kind",
            "schema_version",
            "label",
            "run",
            "testset",
            "model",
            "machine",
            "summary",
            "questions",
        ]
        assert (report["kind"], report["schema_version"]) == ("acme-eval", 3)


class TestResummarize:
    def review(self):
        slots = blank_review()
        for slot, name in zip(slots, ("ana", "ben"), strict=True):
            slot.update(reviewer=name, answer_correct=True)
        return slots

    def test_resummarize_picks_up_filled_verdicts(self, lookup_item):
        report = build_report(
            label="x", run={}, testset={}, records=[question_record(lookup_item, chat_outcome())]
        )
        report["questions"][0]["review"] = self.review()
        refreshed = resummarize(json.loads(json.dumps(report)))
        assert refreshed["summary"]["manual_review"]["answer_correct_pct"] == 100.0
        assert report["summary"]["manual_review"]["reviewed"] == 0
        assert list(refreshed) == list(report)

    def test_resummarize_rejects_other_kinds(self):
        with pytest.raises(
            ValueError, match=r"not a horus-bench-kit-eval report \(kind='llama-bench'\)"
        ):
            resummarize({"kind": "llama-bench"})

    def test_resummarize_uses_the_profile_kind(self, lookup_item):
        profile = Profile(kind="acme-eval", schema_version=2)
        report = build_report(label="x", run={}, testset={}, records=[], profile=profile)
        assert resummarize(report, profile)["kind"] == "acme-eval"
        with pytest.raises(ValueError):
            resummarize(report)

    def test_resummarize_refuses_a_newer_schema_version_and_reads_older_ones(self):
        newer = {"kind": REPORT_KIND, "schema_version": SCHEMA_VERSION + 1, "questions": []}
        with pytest.raises(ValueError, match="newer"):
            resummarize(newer)
        older = {"kind": REPORT_KIND, "schema_version": 0, "questions": []}
        assert resummarize(older)["summary"]["questions"] == 0
