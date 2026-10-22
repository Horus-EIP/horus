import json

import pytest
from eval_report import (
    REPORT_KIND,
    ResourcePeaks,
    blank_review,
    build_report,
    build_summary,
    llm_mapped_outside_docker_stats,
    llm_summary,
    parse_docker_size,
    parse_docker_stats,
    parse_meminfo_swap_used,
    question_record,
    questions_peak_checks,
    resummarize,
    routing_summary,
    titles_from_query_result,
)
from eval_scoring import ROUTE_AGENT, STOPPED_BY_WATCHDOG

GIB = 2**30
RECORD_KEYS = [
    "id",
    "category",
    "difficulty",
    "question",
    "expected_answer",
    "expected_source",
    "expected_route",
    "status",
    "error",
    "conversation_id",
    "task_id",
    "observed_route",
    "answered_by",
    "models",
    "devices",
    "timing_source",
    "submit_http_s",
    "first_event_s",
    "dispatch_s",
    "routing_decision",
    "retrieval_s",
    "reasoning_start_s",
    "ttft_s",
    "total_s",
    "llm",
    "resources",
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
    "dispatch_s",
    "routing",
    "llm",
    "manual_review",
    "by_category",
]
REPORT_KEYS = [
    "kind",
    "schema_version",
    "label",
    "run",
    "testset",
    "llama_cpp",
    "model",
    "machine",
    "resources",
    "summary",
    "questions",
]


@pytest.fixture
def lookup_item(make_item):
    return make_item(id="exp-01")


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
    def test_the_record_keeps_the_horus_eval_keys_in_order(self, lookup_item):
        assert list(question_record(lookup_item, chat_outcome())) == RECORD_KEYS

    def test_record_keeps_dispatch_time_routing_server_metrics_and_question_resources(
        self, lookup_item
    ):
        llm = {
            "prompt_s": 41.5,
            "prompt_tokens": 2100,
            "generation_s": 30.2,
            "generated_tokens": 160,
        }
        decision = {"decisions": 1, "methods": {"embedding": 1}, "seconds": 0.012}
        resources = {"samples": 4, "containers_sum_peak_mem_bytes": 9 * 2**30}
        outcome = chat_outcome(
            dispatch_s=0.8, routing_decision=decision, llm=llm, resources=resources
        )
        record = question_record(lookup_item, outcome)
        assert record["dispatch_s"] == 0.8
        assert record["routing_decision"] == decision
        assert record["llm"] == llm
        assert record["resources"] == resources

    def test_record_without_probes_has_null_server_metrics(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        assert record["dispatch_s"] is None
        assert record["routing_decision"] is None
        assert record["llm"] is None
        assert record["resources"] is None

    def test_watchdog_message_is_recorded_as_a_timeout(self, lookup_item):
        watchdog = "This request exceeded the maximum processing time (1800s) and was stopped."
        record = question_record(lookup_item, chat_outcome(answer=watchdog))
        assert record["status"] == "timeout"
        assert record["error"] == STOPPED_BY_WATCHDOG
        assert record["fallback"] == "task_timeout"
        assert record["answer_correct_auto"] is False

    def test_spiral_fallback_is_flagged_and_wrong(self, lookup_item):
        outcome = chat_outcome(
            answer="I couldn't extract a consistent answer from the retrieved content. 250"
        )
        record = question_record(lookup_item, outcome)
        assert record["fallback"] == "spiral"
        assert record["answer_correct_auto"] is False


class TestResummarize:
    def review(self, first, second):
        slots = blank_review()
        slots[0].update(reviewer="ana", answer_correct=first)
        slots[1].update(reviewer="ben", answer_correct=second)
        return slots

    def test_resummarize_picks_up_filled_verdicts(self, lookup_item):
        record = question_record(lookup_item, chat_outcome())
        report = build_report(label="cpu16", run={}, testset={}, records=[record])
        report["questions"][0]["review"] = self.review(True, True)
        refreshed = resummarize(json.loads(json.dumps(report)))
        assert refreshed["summary"]["manual_review"]["answer_correct_pct"] == 100.0
        assert report["summary"]["manual_review"]["reviewed"] == 0

    def test_resummarize_rejects_other_json(self):
        with pytest.raises(ValueError, match=r"^not a horus-eval report \(kind='llama-bench'\)$"):
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

    def test_the_stack_sections_sit_between_the_test_set_and_the_summary(self):
        assert list(build_report(label="x", run={}, testset={}, records=[])) == REPORT_KEYS


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
            "llm_mapped_outside_docker_stats_bytes": None,
            "stack_peak_mem_bytes": None,
            "samples_without_llm_pages": 0,
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


def memory_stat(inactive_file=0, active_file=0, file_mapped=0, anon=GIB):
    return {
        "anon": anon,
        "file": inactive_file + active_file,
        "active_file": active_file,
        "inactive_file": inactive_file,
        "file_mapped": file_mapped,
    }


class TestQuestionsPeakChecks:
    @staticmethod
    def resources(lifetime, sampled, memory_stats=None, swap_peak=None):
        return {
            "container_peak_mem_bytes": sampled,
            "container_lifetime_peak_mem_bytes": lifetime,
            "container_memory_stat": memory_stats or {},
            "docker_host_swap_peak_used_bytes": swap_peak,
        }

    def test_only_a_peak_reached_during_the_questions_counts_against_the_samples(self):
        at_start = {
            "container_lifetime_peak_mem_bytes": {
                "knowledge_store": 5 * GIB,
                "llm": 3 * GIB,
                "mas": GIB,
            },
            "docker_host_swap_used_bytes": GIB // 4,
        }
        resources = self.resources(
            lifetime={"knowledge_store": 5 * GIB, "llm": 4 * GIB + GIB // 2, "mas": GIB + 100},
            sampled={"knowledge_store": 2 * GIB, "llm": 3 * GIB, "mas": GIB + 200},
            memory_stats={
                "knowledge_store": memory_stat(inactive_file=3 * GIB),
                "llm": memory_stat(inactive_file=GIB // 2),
                "mas": memory_stat(),
            },
        )
        checks = questions_peak_checks(resources, at_start, GIB // 2)
        assert checks["unsampled_peak_excess_bytes"] == {"llm": GIB}
        assert checks["docker_host_swap_growth_bytes"] == GIB // 4
        assert checks["at_questions_start"] is at_start

    def test_inactive_page_cache_that_stays_put_is_no_excess(self):
        at_start = {
            "container_lifetime_peak_mem_bytes": {"knowledge_store": 5 * GIB, "llm": 3 * GIB}
        }
        resources = self.resources(
            lifetime={"knowledge_store": 5 * GIB + 2**20, "llm": 5 * GIB + 3 * GIB // 10},
            sampled={"knowledge_store": 2 * GIB, "llm": 3 * GIB},
            memory_stats={
                "knowledge_store": memory_stat(inactive_file=3 * GIB + GIB // 10),
                "llm": memory_stat(
                    inactive_file=2 * GIB + 3 * GIB // 10, file_mapped=2 * GIB + 3 * GIB // 10
                ),
            },
        )
        assert questions_peak_checks(resources, at_start, None)["unsampled_peak_excess_bytes"] == {}

    def test_an_unread_memory_stat_leaves_the_check_open(self):
        at_start = {"container_lifetime_peak_mem_bytes": {"llm": 3 * GIB}}
        resources = self.resources(
            lifetime={"llm": 4 * GIB}, sampled={"llm": 3 * GIB}, memory_stats={"llm": None}
        )
        assert questions_peak_checks(resources, at_start, None)["unsampled_peak_excess_bytes"] == {
            "llm": None
        }

    def test_an_unread_memory_peak_at_the_start_or_the_end_leaves_the_check_open(self):
        at_start = {"container_lifetime_peak_mem_bytes": {"llm": None, "agent": GIB}}
        resources = self.resources(
            lifetime={"llm": 2 * GIB, "agent": None, "web_client": GIB},
            sampled={"llm": GIB, "agent": 5, "web_client": 10},
            memory_stats={
                "llm": memory_stat(),
                "agent": memory_stat(),
                "web_client": memory_stat(),
            },
        )
        checks = questions_peak_checks(resources, at_start, None)
        assert checks["unsampled_peak_excess_bytes"] == {
            "agent": None,
            "llm": None,
            "web_client": None,
        }

    def test_a_container_docker_stats_never_sampled_is_not_judged(self):
        at_start = {"container_lifetime_peak_mem_bytes": {"llm": GIB}}
        resources = self.resources(lifetime={"llm": 2 * GIB}, sampled={})
        checks = questions_peak_checks(resources, at_start, None)
        assert checks["unsampled_peak_excess_bytes"] == {}
        assert checks["docker_host_swap_growth_bytes"] is None

    def test_swap_growth_counts_only_from_the_first_question(self):
        at_start = {
            "container_lifetime_peak_mem_bytes": {},
            "docker_host_swap_used_bytes": GIB // 4,
        }
        resources = self.resources({}, {}, swap_peak=GIB)
        assert (
            questions_peak_checks(resources, at_start, GIB // 2)["docker_host_swap_growth_bytes"]
            == GIB // 4
        )

    def test_swap_that_shrank_is_no_growth(self):
        at_start = {"container_lifetime_peak_mem_bytes": {}, "docker_host_swap_used_bytes": GIB}
        checks = questions_peak_checks(self.resources({}, {}), at_start, GIB // 2)
        assert checks["docker_host_swap_growth_bytes"] == 0

    def test_without_a_start_snapshot_nothing_is_judged(self):
        assert questions_peak_checks(self.resources({"llm": GIB}, {"llm": 1}), None, GIB) == {
            "at_questions_start": None,
            "unsampled_peak_excess_bytes": None,
            "docker_host_swap_growth_bytes": None,
        }


class TestLlmPagesOutsideDockerStats:
    LLAMA_SERVER = {"name": "llama-server", "rss_file_bytes": 2 * GIB + 4 * GIB // 10}

    def test_model_pages_on_the_inactive_list_are_left_out_of_docker_stats(self):
        llm_stat = memory_stat(
            inactive_file=2 * GIB + 4 * GIB // 10,
            active_file=GIB // 20,
            file_mapped=2 * GIB + 4 * GIB // 10,
        )
        assert (
            llm_mapped_outside_docker_stats(self.LLAMA_SERVER, llm_stat)
            == 2 * GIB + 4 * GIB // 10 - GIB // 20
        )

    def test_model_pages_charged_to_the_container_that_downloaded_them_are_left_out(self):
        llm_stat = memory_stat(active_file=GIB // 5, file_mapped=GIB // 50)
        assert (
            llm_mapped_outside_docker_stats(self.LLAMA_SERVER, llm_stat)
            == 2 * GIB + 4 * GIB // 10 - GIB // 50
        )

    def test_model_pages_on_the_active_list_are_already_in_docker_stats(self):
        llm_stat = memory_stat(active_file=2 * GIB + GIB // 2, file_mapped=2 * GIB + GIB // 2)
        assert llm_mapped_outside_docker_stats(self.LLAMA_SERVER, llm_stat) == 0

    @pytest.mark.parametrize(
        ("process", "llm_stat"),
        [
            ({"name": "sh", "rss_file_bytes": GIB}, memory_stat()),
            ({"name": "llama-server", "rss_file_bytes": None}, memory_stat()),
            (None, memory_stat()),
            (LLAMA_SERVER, None),
        ],
    )
    def test_without_the_llama_server_figures_nothing_is_known(self, process, llm_stat):
        assert llm_mapped_outside_docker_stats(process, llm_stat) is None


class TestStackPeak:
    def test_p_is_the_largest_total_of_one_sample_with_the_model_pages_of_that_sample(self):
        peaks = ResourcePeaks()
        peaks.add(
            {"llm": 4 * GIB, "knowledge_store": 5 * GIB}, llm_container="llm", llm_mapped_outside=0
        )
        peaks.add(
            {"llm": 2 * GIB, "knowledge_store": 4 * GIB + GIB // 2},
            llm_container="llm",
            llm_mapped_outside=2 * GIB,
        )
        peaks.add(
            {"llm": 2 * GIB, "knowledge_store": 4 * GIB},
            llm_container="llm",
            llm_mapped_outside=2 * GIB,
        )
        resources = peaks.as_dict()
        assert resources["containers_sum_peak_mem_bytes"] == 9 * GIB
        assert resources["stack_peak_mem_bytes"] == 9 * GIB
        assert resources["llm_mapped_outside_docker_stats_bytes"] == 0
        assert resources["samples_without_llm_pages"] == 0

    def test_model_pages_left_out_in_the_peak_sample_are_added_to_p(self):
        peaks = ResourcePeaks()
        peaks.add(
            {"llm": 2 * GIB, "knowledge_store": 7 * GIB},
            llm_container="llm",
            llm_mapped_outside=2 * GIB,
        )
        peaks.add(
            {"llm": 4 * GIB, "knowledge_store": 4 * GIB}, llm_container="llm", llm_mapped_outside=0
        )
        resources = peaks.as_dict()
        assert resources["stack_peak_mem_bytes"] == 11 * GIB
        assert resources["llm_mapped_outside_docker_stats_bytes"] == 2 * GIB

    def test_a_sample_whose_llm_pages_could_not_be_read_is_counted_and_left_out_of_p(self):
        peaks = ResourcePeaks()
        peaks.add({"llm": 4 * GIB, "mas": 6 * GIB}, llm_container="llm", llm_mapped_outside=None)
        peaks.add({"llm": 4 * GIB, "mas": GIB}, llm_container="llm", llm_mapped_outside=GIB)
        peaks.add({"mas": GIB}, llm_container="llm", llm_mapped_outside=None)
        resources = peaks.as_dict()
        assert resources["containers_sum_peak_mem_bytes"] == 10 * GIB
        assert resources["stack_peak_mem_bytes"] == 6 * GIB
        assert resources["samples_without_llm_pages"] == 1

    @pytest.mark.parametrize("llm_container", ["llm", None])
    def test_without_the_llm_figures_in_any_sample_p_is_unknown(self, llm_container):
        peaks = ResourcePeaks()
        peaks.add(
            {"llm": 4 * GIB, "mas": GIB}, llm_container=llm_container, llm_mapped_outside=None
        )
        resources = peaks.as_dict()
        assert resources["stack_peak_mem_bytes"] is None
        assert resources["llm_mapped_outside_docker_stats_bytes"] is None
        assert resources["samples_without_llm_pages"] == (1 if llm_container else 0)


class TestServerSideSummary:
    @staticmethod
    def record(llm=None, dispatch_s=None, **outcome):
        return {"llm": llm, "dispatch_s": dispatch_s, **outcome}

    def test_totals_give_the_throughput_over_all_questions(self):
        records = [
            self.record(
                {
                    "prompt_s": 10.0,
                    "prompt_tokens": 1000,
                    "generation_s": 20.0,
                    "generated_tokens": 200,
                }
            ),
            self.record(
                {
                    "prompt_s": 30.0,
                    "prompt_tokens": 2000,
                    "generation_s": 20.0,
                    "generated_tokens": 200,
                }
            ),
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
            self.record(
                {"prompt_s": 4.0, "prompt_tokens": 400, "generation_s": 2.0, "generated_tokens": 20}
            ),
            self.record({"restarted": True}),
        ]
        summary = llm_summary(records)
        assert summary["questions"] == 1
        assert summary["server_restarts"] == 1
        assert summary["prompt_tps"] == 100.0

    def test_no_server_metrics_give_no_llm_summary(self):
        assert llm_summary([self.record(), self.record()]) is None

    def test_summary_has_dispatch_time_routing_and_llm_blocks(self, lookup_item):
        decision = {"decisions": 1, "methods": {"rules": 1}, "seconds": 0.002}
        records = [
            question_record(
                lookup_item,
                chat_outcome(dispatch_s=0.2, llm={"prompt_s": 1.0, "prompt_tokens": 50}),
            ),
            question_record(lookup_item, chat_outcome(dispatch_s=0.4, routing_decision=decision)),
        ]
        summary = build_summary(records)
        assert list(summary) == SUMMARY_KEYS
        assert summary["dispatch_s"]["n"] == 2
        assert summary["dispatch_s"]["max"] == 0.4
        assert summary["routing"]["methods"] == {"rules": 1}
        assert summary["llm"]["questions"] == 1


class TestRoutingSummary:
    @staticmethod
    def record(decision):
        return {"routing_decision": decision}

    @staticmethod
    def decided(method, seconds):
        return {"decisions": 1, "methods": {method: 1}, "seconds": seconds}

    def test_router_time_method_share_and_llm_fallback_rate(self):
        records = [
            self.record(self.decided("rules", 0.001)),
            self.record(self.decided("embedding", 0.012)),
            self.record(self.decided("embedding", 0.018)),
            self.record(self.decided("llm", 2.5)),
            self.record({"decisions": 0, "methods": {}, "seconds": 0.0}),
            self.record({"decisions": 2, "methods": {"embedding": 1, "llm": 1}, "seconds": 3.0}),
            self.record({"restarted": True}),
            self.record(None),
        ]
        summary = routing_summary(records)
        assert summary["questions"] == 6
        assert summary["mas_restarts"] == 1
        assert summary["decided_once"] == 4
        assert summary["without_decision"] == 1
        assert summary["several_decisions"] == 1
        assert summary["methods"] == {"embedding": 2, "llm": 1, "rules": 1}
        assert summary["llm_pct"] == 25.0
        assert summary["decision_s"]["median"] == 0.015
        assert summary["decision_s"]["max"] == 2.5
        assert summary["decision_s_without_llm"]["max"] == 0.018

    def test_no_router_metrics_give_no_routing_summary(self):
        assert routing_summary([self.record(None), {}]) is None

    def test_questions_without_a_decision_leave_the_rates_empty(self):
        summary = routing_summary([self.record({"decisions": 0, "methods": {}, "seconds": 0.0})])
        assert summary["decided_once"] == 0
        assert summary["llm_pct"] is None
        assert summary["decision_s"] == {"n": 0}


class TestQueryResultTitles:
    def test_titles_come_from_chroma_metadatas_in_rank_order(self):
        raw = {
            "ids": [["a", "b", "c"]],
            "metadatas": [
                [
                    {"title": "4_Expense_Policy.md"},
                    {"title": "2_Employee_Handbook.md"},
                    {"title": "4_Expense_Policy.md"},
                ]
            ],
        }
        assert titles_from_query_result(raw) == ["4_Expense_Policy.md", "2_Employee_Handbook.md"]

    def test_unexpected_shapes_give_no_titles(self):
        assert titles_from_query_result({}) == []
        assert titles_from_query_result({"metadatas": [[None, {"other": 1}]]}) == []
        assert titles_from_query_result(None) == []
