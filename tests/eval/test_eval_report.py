import json
from datetime import date

import pytest
from eval_files import is_sha256, report_path, safe_label, write_json
from eval_report import (
    REPORT_KIND,
    ResourcePeaks,
    blank_review,
    build_report,
    build_summary,
    llm_summary,
    manual_review_summary,
    parse_docker_size,
    parse_docker_stats,
    parse_meminfo_swap_used,
    question_record,
    rate,
    resummarize,
    stats,
    titles_from_query_result,
)
from eval_scoring import (
    ROUTE_AGENT,
    ROUTE_DIRECT,
    SOURCE_BASIS_RETRIEVAL,
    STOPPED_BY_WATCHDOG,
)

ALL_DOCUMENTS = [
    "1_Q4_2025_Financial_Report.md",
    "2_Employee_Handbook.md",
    "3_Compliance_Guidelines.md",
    "5_IT_Security_Policy.md",
    "4_Expense_Policy.md",
]


@pytest.fixture
def lookup_item(make_item):
    return make_item(id="exp-01")


@pytest.fixture
def direct_item(make_item):
    return make_item(
        id="direct-04",
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
        "conversation_id": 7,
        "task_id": "t-1",
        "observed_route": ROUTE_AGENT,
        "timing_source": "websocket",
        "submit_http_s": 0.4,
        "first_event_s": 0.6,
        "ttft_s": 3.5,
        "total_s": 12.0,
        "answer": "The US limit is **$250/night**.",
        "retrieval_steps": 1,
        "retrieved_sources": [["4_Expense_Policy.md", "2_Employee_Handbook.md"]],
        "cited_sources": None,
    }
    outcome.update(overrides)
    return outcome


class TestQuestionRecord:
    def test_correct_answer_with_its_source(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is True
        assert record["route_correct"] is True
        assert record["missing_patterns"] == []
        assert record["expected_source"] == ["4_Expense_Policy.md"]
        assert record["expected_route"] == ROUTE_AGENT
        assert record["source_basis"] == SOURCE_BASIS_RETRIEVAL
        assert record["source_ranks"] == [1]
        assert record["retrieval_steps"] == 1
        assert record["retrieved_sources"] == [["4_Expense_Policy.md", "2_Employee_Handbook.md"]]
        assert record["total_s"] == 12.0
        assert record["ttft_s"] == 3.5
        assert record["fallback"] is None

    def test_record_keeps_routing_time_server_metrics_and_question_resources(self, lookup_item):
        llm = {"prompt_s": 41.5, "prompt_tokens": 2100, "generation_s": 30.2, "generated_tokens": 160}
        resources = {"samples": 4, "containers_sum_peak_mem_bytes": 9 * 2**30}
        record = question_record(lookup_item, chat_outcome(routing_s=0.8, llm=llm, resources=resources))
        assert record["routing_s"] == 0.8
        assert record["llm"] == llm
        assert record["resources"] == resources

    def test_record_without_probes_has_null_server_metrics(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        assert record["routing_s"] is None
        assert record["llm"] is None
        assert record["resources"] is None

    def test_record_keeps_empty_slots_for_two_reviewers(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        assert record["review"] == [
            {"reviewer": None, "answer_correct": None, "comment": None},
            {"reviewer": None, "answer_correct": None, "comment": None},
        ]

    def test_wrong_answer_and_wrong_source(self, lookup_item):
        ranking = ["2_Employee_Handbook.md", "4_Expense_Policy.md"]
        outcome = chat_outcome(answer="It is $300.", retrieved_sources=[ranking])
        record = question_record(lookup_item, outcome)
        assert record["answer_correct_auto"] is False
        assert record["missing_patterns"] == [r"\b250\b"]
        assert record["source_correct_auto"] is False
        assert record["source_ranks"] == [2]

    def test_live_agent_retrieval_without_titles_leaves_the_source_unscored(self, lookup_item):
        outcome = chat_outcome(retrieval_steps=1, retrieved_sources=None)
        record = question_record(lookup_item, outcome)
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is None
        assert record["source_basis"] is None
        assert record["source_ranks"] is None

    def test_failed_question_counts_as_a_wrong_answer_and_leaves_the_source_open(self, lookup_item):
        outcome = {
            "mode": "chat",
            "status": "timeout",
            "error": "no final answer",
            "retrieval_steps": 0,
            "retrieved_sources": [],
        }
        record = question_record(lookup_item, outcome)
        assert record["status"] == "timeout"
        assert record["answer_correct_auto"] is False
        assert record["source_correct_auto"] is None
        assert record["route_correct"] is None

    def test_watchdog_message_is_recorded_as_a_timeout(self, lookup_item):
        watchdog = "This request exceeded the maximum processing time (1800s) and was stopped."
        record = question_record(lookup_item, chat_outcome(answer=watchdog))
        assert record["status"] == "timeout"
        assert record["error"] == STOPPED_BY_WATCHDOG
        assert record["fallback"] == "task_timeout"
        assert record["answer_correct_auto"] is False

    def test_direct_answer_without_sources(self, direct_item):
        outcome = chat_outcome(
            observed_route=ROUTE_DIRECT,
            timing_source="http",
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

    def test_direct_item_sent_to_an_agent_that_retrieved_has_a_wrong_source(self, direct_item):
        outcome = chat_outcome(answer="4", retrieval_steps=1, retrieved_sources=None)
        record = question_record(direct_item, outcome)
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is False
        assert record["route_correct"] is False

    def test_spiral_fallback_is_flagged_and_wrong(self, lookup_item):
        outcome = chat_outcome(answer="I couldn't extract a consistent answer from the retrieved content. 250")
        record = question_record(lookup_item, outcome)
        assert record["fallback"] == "spiral"
        assert record["answer_correct_auto"] is False

    def retrieval_outcome(self, ranking):
        return {
            "mode": "retrieval",
            "status": "ok",
            "timing_source": "http",
            "total_s": 0.08,
            "retrieved_sources": [ranking],
        }

    def test_retrieval_mode_scores_only_the_source(self, lookup_item):
        record = question_record(lookup_item, self.retrieval_outcome(["4_Expense_Policy.md"]))
        assert record["answer_correct_auto"] is None
        assert record["missing_patterns"] is None
        assert record["route_correct"] is None
        assert record["source_correct_auto"] is True
        assert record["source_ranks"] == [1]
        assert record["retrieval_steps"] is None
        assert record["review"] is None

    def test_retrieval_mode_with_the_whole_corpus_ranked_needs_the_document_first(self, lookup_item):
        record = question_record(lookup_item, self.retrieval_outcome(ALL_DOCUMENTS))
        assert record["source_correct_auto"] is False
        assert record["source_ranks"] == [5]

    def test_retrieval_mode_does_not_score_direct_items(self, direct_item):
        record = question_record(direct_item, self.retrieval_outcome(ALL_DOCUMENTS))
        assert record["source_correct_auto"] is None


class TestSummary:
    def test_rate_ignores_unscored_values(self):
        assert rate([True, False, None, True]) == {"n": 3, "correct": 2, "pct": 66.7}
        assert rate([None]) == {"n": 0, "correct": 0, "pct": None}

    def test_stats_of_known_values(self):
        result = stats([3.0, None, 1.0, 2.0])
        assert result["n"] == 3
        assert result["median"] == 2.0
        assert result["min"] == 1.0 and result["max"] == 3.0
        assert result["sum"] == 6.0
        assert stats([None]) == {"n": 0}

    def test_summary_totals_and_categories(self, lookup_item, direct_item):
        records = [
            question_record(lookup_item, chat_outcome()),
            question_record(lookup_item, chat_outcome(answer="$300", retrieved_sources=[ALL_DOCUMENTS])),
            question_record(lookup_item, chat_outcome(retrieved_sources=None)),
            question_record(
                direct_item,
                chat_outcome(
                    observed_route=ROUTE_DIRECT,
                    timing_source="http",
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
        assert summary["source_rank"]["not_retrieved"] == 0
        assert summary["source_basis"] == {"retrieval": 3, "not_observable": 1}
        assert summary["status"] == {"ok": 4}
        assert summary["total_s"]["n"] == 4
        assert summary["ttft_s"]["n"] == 3
        assert set(summary["by_category"]) == {"lookup", "direct"}
        assert summary["by_category"]["lookup"]["answer_correct_auto"]["correct"] == 2
        assert summary["by_category"]["lookup"]["source_rank"]["n"] == 2
        assert summary["manual_review"]["pending"] == 4

    def test_rank_summary_counts_expected_documents_never_retrieved(self, make_item):
        item = make_item(expected_source=["1_Q4_2025_Financial_Report.md", "4_Expense_Policy.md"])
        outcome = chat_outcome(retrieved_sources=[["4_Expense_Policy.md", "2_Employee_Handbook.md"]])
        summary = build_summary([question_record(item, outcome)])
        assert summary["source_rank"]["n"] == 1
        assert summary["source_rank"]["not_retrieved"] == 1
        assert summary["source_correct_auto"]["correct"] == 0


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

    def test_resummarize_picks_up_filled_verdicts(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        report = build_report(label="cpu16", run={}, testset={}, records=[record])
        report["questions"][0]["review"] = self.review(True, True)
        refreshed = resummarize(json.loads(json.dumps(report)))
        assert refreshed["summary"]["manual_review"]["answer_correct_pct"] == 100.0
        assert report["summary"]["manual_review"]["reviewed"] == 0

    def test_resummarize_rejects_other_json(self):
        with pytest.raises(ValueError):
            resummarize({"kind": "llama-bench"})


class TestBuildReport:
    def test_report_carries_build_number_model_hash_and_machine(self, lookup_item):
        report = build_report(
            label="cpu16-q4km",
            run={"mode": "chat"},
            testset={"version": "1.0.0"},
            records=[question_record(lookup_item, chat_outcome())],
            llama_cpp_build="b6500",
            model={"name": "qwen3-4b", "sha256": "ab" * 32},
            machine={"reference": "cpu16"},
        )
        assert report["kind"] == REPORT_KIND
        assert report["schema_version"] == 2
        assert report["llama_cpp"] == {"build": "b6500", "server": None}
        assert report["model"] == {"name": "qwen3-4b", "file": None, "sha256": "ab" * 32}
        assert report["machine"] == {"reference": "cpu16"}
        assert report["summary"]["questions"] == 1
        assert report["questions"][0]["id"] == "exp-01"
        json.dumps(report)

    def test_missing_build_and_model_stay_as_empty_fields(self):
        report = build_report(label="x", run={}, testset={}, records=[])
        assert report["llama_cpp"] == {"build": None, "server": None}
        assert report["model"] == {"name": None, "file": None, "sha256": None}


class TestReportPath:
    def test_path_is_label_and_date(self, tmp_path):
        path = report_path(tmp_path, "cpu16-baseline", date(2026, 10, 5))
        assert path == tmp_path / "cpu16-baseline-2026-10-05.json"

    def test_existing_report_is_never_overwritten(self, tmp_path):
        (tmp_path / "gpu8-2026-10-05.json").write_text("{}")
        (tmp_path / "gpu8-2026-10-05-2.json").write_text("{}")
        path = report_path(tmp_path, "gpu8", date(2026, 10, 5))
        assert path.name == "gpu8-2026-10-05-3.json"

    def test_label_is_made_safe_for_a_file_name(self):
        assert safe_label(" cpu16 / q8_0 kv ") == "cpu16-q8_0-kv"
        with pytest.raises(ValueError):
            safe_label("///")


class TestSha256:
    def test_accepts_64_hex_characters_in_any_case(self):
        assert is_sha256("A" * 64)
        assert is_sha256("0123456789abcdef" * 4)

    def test_rejects_other_values(self):
        assert not is_sha256("abc")
        assert not is_sha256("g" * 64)
        assert not is_sha256(None)


class TestResources:
    def test_docker_sizes_in_binary_and_decimal_units(self):
        assert parse_docker_size("1.5GiB") == int(1.5 * 2**30)
        assert parse_docker_size("512MiB ") == 512 * 2**20
        assert parse_docker_size("800kB") == 800_000
        assert parse_docker_size("12B") == 12
        assert parse_docker_size("n/a") is None

    def test_docker_stats_lines_give_used_memory_per_container(self):
        output = "mas\t1.2GiB / 14GiB\nagent\t6.5GiB / 15.5GiB\nbroken line\n"
        assert parse_docker_stats(output) == {"mas": int(1.2 * 2**30), "agent": int(6.5 * 2**30)}

    def test_meminfo_swap_used(self):
        meminfo = "MemTotal: 16000000 kB\nSwapTotal: 4194300 kB\nSwapFree: 4094300 kB\n"
        assert parse_meminfo_swap_used(meminfo) == 100000 * 1024
        assert parse_meminfo_swap_used("MemTotal: 1 kB") is None

    def test_peaks_keep_the_maximum_of_each_container_and_of_the_sum(self):
        peaks = ResourcePeaks()
        peaks.add({"mas": 100, "agent": 500}, swap_used=0, docker_host_swap_used=10)
        peaks.add({"mas": 300, "agent": 200}, swap_used=50, docker_host_swap_used=70)
        peaks.add({}, swap_used=None)
        assert peaks.as_dict() == {
            "samples": 3,
            "container_peak_mem_bytes": {"agent": 500, "mas": 300},
            "containers_sum_peak_mem_bytes": 600,
            "swap_peak_used_bytes": 50,
            "docker_host_swap_peak_used_bytes": 70,
        }

    def test_docker_host_swap_stays_unknown_when_never_read(self):
        peaks = ResourcePeaks()
        peaks.add({"llm": 4 * 2**30}, swap_used=0)
        assert peaks.as_dict()["docker_host_swap_peak_used_bytes"] is None

    def test_question_window_keeps_the_sum_and_swap_peaks(self):
        window = ResourcePeaks()
        window.add({"llm": 400, "mas": 100}, swap_used=5, docker_host_swap_used=7)
        window.add({"llm": 450, "mas": 100}, swap_used=5, docker_host_swap_used=9)
        assert window.window_dict() == {
            "samples": 2,
            "containers_sum_peak_mem_bytes": 550,
            "swap_peak_used_bytes": 5,
            "docker_host_swap_peak_used_bytes": 9,
        }

    def test_question_window_without_a_sample_is_null(self):
        assert ResourcePeaks().window_dict() is None


class TestServerSideSummary:
    @staticmethod
    def record(llm=None, routing_s=None, **outcome):
        return {"llm": llm, "routing_s": routing_s, **outcome}

    def test_totals_give_the_throughput_over_all_questions(self):
        records = [
            self.record({"prompt_s": 10.0, "prompt_tokens": 1000, "generation_s": 20.0, "generated_tokens": 200}),
            self.record({"prompt_s": 30.0, "prompt_tokens": 2000, "generation_s": 20.0, "generated_tokens": 200}),
        ]
        summary = llm_summary(records)
        assert summary["questions"] == 2
        assert summary["server_restarts"] == 0
        assert summary["prompt_tps"] == 75.0
        assert summary["generation_tps"] == 10.0
        assert summary["prompt_s"]["median"] == 20.0
        assert summary["generated_tokens"]["sum"] == 400

    def test_a_restarted_server_is_counted_and_left_out_of_the_rates(self):
        records = [
            self.record({"prompt_s": 4.0, "prompt_tokens": 400, "generation_s": 2.0, "generated_tokens": 20}),
            self.record({"restarted": True}),
        ]
        summary = llm_summary(records)
        assert summary["questions"] == 1
        assert summary["server_restarts"] == 1
        assert summary["prompt_tps"] == 100.0

    def test_no_server_metrics_give_no_llm_summary(self):
        assert llm_summary([self.record(), self.record()]) is None

    def test_summary_has_routing_time_and_llm_blocks(self, lookup_item):
        records = [
            question_record(lookup_item, chat_outcome(routing_s=0.2, llm={"prompt_s": 1.0, "prompt_tokens": 50})),
            question_record(lookup_item, chat_outcome(routing_s=0.4)),
        ]
        summary = build_summary(records)
        assert summary["routing_s"]["n"] == 2
        assert summary["routing_s"]["max"] == 0.4
        assert summary["llm"]["questions"] == 1


class TestFiles:
    def test_json_is_written_whole_and_no_part_file_is_left(self, tmp_path):
        path = tmp_path / "nested" / "cpu16-2026-10-05.json"
        write_json(path, {"kind": "horus-eval", "label": "café"})
        assert json.loads(path.read_text(encoding="utf-8")) == {"kind": "horus-eval", "label": "café"}
        assert list(path.parent.iterdir()) == [path]


class TestQueryResultTitles:
    def test_titles_come_from_chroma_metadatas_in_rank_order(self):
        raw = {
            "ids": [["a", "b", "c"]],
            "metadatas": [[{"title": "4_Expense_Policy.md"}, {"title": "2_Employee_Handbook.md"}, {"title": "4_Expense_Policy.md"}]],
        }
        assert titles_from_query_result(raw) == ["4_Expense_Policy.md", "2_Employee_Handbook.md"]

    def test_unexpected_shapes_give_no_titles(self):
        assert titles_from_query_result({}) == []
        assert titles_from_query_result({"metadatas": [[None, {"other": 1}]]}) == []
        assert titles_from_query_result(None) == []
