import importlib.util
import json
import sys
from pathlib import Path

import pytest
from bench_compare import BenchSelection, compare_markdown, load_document
from eval_report import build_report, question_record

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = REPO_ROOT / "benchmarks"
BASELINE = BENCHMARKS / "cpu-transformers-2026-09-01.json"
Q4 = "qwen3-4b-instruct-2507-Q4_K_M.gguf"
Q5 = "qwen3-4b-instruct-2507-Q5_K_M.gguf"
GIB = 2**30


def eval_report(
    make_item,
    totals,
    *,
    kv="f16",
    testset_sha="a" * 64,
    label="eval-cpu16",
    reviewed=True,
    unsampled=None,
    oom_kills=None,
    restarts=None,
    stack_peak=11 * GIB + GIB // 2,
    samples_without_llm_pages=0,
):
    item = make_item(id="exp-01")
    records = []
    for index, total in enumerate(totals):
        method, seconds = ("embedding", 0.012) if index else ("llm", 2.4)
        outcome = {
            "mode": "chat",
            "status": "ok",
            "answer": "$250 per night" if index else "$300",
            "timing_source": "websocket",
            "observed_route": "AGENT",
            "total_s": total,
            "ttft_s": total / 4,
            "dispatch_s": 0.25,
            "routing_decision": {"decisions": 1, "methods": {method: 1}, "seconds": seconds},
            "retrieval_steps": 1,
            "retrieved_sources": [["4_Expense_Policy.md"]],
            "llm": {
                "prompt_s": total / 2,
                "prompt_tokens": 1000,
                "generation_s": total / 4,
                "generated_tokens": 100,
            },
        }
        record = question_record(item, outcome)
        if reviewed:
            for slot in record["review"]:
                slot.update(reviewer="ana", answer_correct=bool(index))
        records.append(record)
    return build_report(
        label=label,
        run={"mode": "chat", "started_at": "2026-10-06T08:00:00Z", "completed": True},
        testset={"version": "1.0.0", "sha256": testset_sha},
        records=records,
        llama_cpp_build="b11382",
        llama_server={"settings": {"cache_type_k": kv, "cache_type_v": kv}},
        model={"file": Q4, "sha256": "3605803b982c" + "0" * 52},
        machine={
            "reference": "cpu16",
            "cpu_model": "AMD Ryzen 5 5600U",
            "physical_cores": 6,
            "avx2": True,
            "ram": "16 GiB installed",
            "docker": {"mem_total_bytes": 15 * GIB},
        },
        resources={
            "samples": 40,
            "container_peak_mem_bytes": {"llm": 4 * GIB, "mas": GIB},
            "containers_sum_peak_mem_bytes": 9 * GIB,
            "llm_mapped_outside_docker_stats_bytes": 2 * GIB + GIB // 2,
            "stack_peak_mem_bytes": stack_peak,
            "samples_without_llm_pages": samples_without_llm_pages,
            "swap_peak_used_bytes": 0,
            "docker_host_swap_peak_used_bytes": GIB // 2,
            "container_lifetime_peak_mem_bytes": {"llm": 5 * GIB},
            "container_oom_kills": {"llm": 0, "agent": 1} if oom_kills is None else oom_kills,
            "container_restarts": {"llm": 0, "agent": 0} if restarts is None else restarts,
            "docker_host_swap_growth_bytes": GIB // 4,
            "unsampled_peak_excess_bytes": unsampled or {},
        },
    )


def bench_rows():
    rows = []
    for model in (Q4, Q5):
        for type_kv in ("f16", "q8_0"):
            for threads in (4, 8):
                for prompt, generated, depth in (
                    (512, 0, 0),
                    (0, 128, 0),
                    (512, 0, 4096),
                    (0, 128, 4096),
                ):
                    speed = (
                        (100.0 if prompt else 10.0)
                        * (threads / 4)
                        * (0.9 if type_kv == "q8_0" else 1.0)
                    )
                    speed *= 0.8 if model == Q5 else 1.0
                    speed *= 0.5 if depth else 1.0
                    rows.append(
                        {
                            "build_number": 11382,
                            "model_filename": f"/models/{model}",
                            "n_threads": threads,
                            "type_k": type_kv,
                            "type_v": type_kv,
                            "n_prompt": prompt,
                            "n_gen": generated,
                            "n_depth": depth,
                            "avg_ts": speed,
                            "stddev_ts": 1.0,
                        }
                    )
    return rows


def write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def table_row(markdown, label):
    for line in markdown.splitlines():
        if line.startswith(f"| {label} |") or line.startswith(f"| {label} ("):
            return [cell.strip() for cell in line.strip("|").split(" | ")]
    raise AssertionError(f"no row {label!r} in:\n{markdown}")


class TestEndToEnd:
    def test_two_eval_runs_give_values_and_changes(self, tmp_path, make_item):
        before = write(
            tmp_path, "eval-a.json", eval_report(make_item, [20.0, 40.0], label="before")
        )
        after = write(tmp_path, "eval-b.json", eval_report(make_item, [10.0, 20.0], label="after"))
        markdown = compare_markdown([before], [after], BenchSelection())
        assert markdown.startswith("# Benchmark comparison")
        assert table_row(markdown, "Total time, median")[2:] == [
            "30.0 s (n=2)",
            "15.0 s (n=2)",
            "-15.0 s (-50%)",
        ]
        assert table_row(markdown, "Total time, whole run")[2:] == [
            "60.0 s (n=2)",
            "30.0 s (n=2)",
            "-30.0 s (-50%)",
        ]
        assert table_row(markdown, "Time to first token, median")[2:] == [
            "7.50 s (n=2)",
            "3.75 s (n=2)",
            "-3.75 s (-50%)",
        ]
        assert table_row(markdown, "Submit to dispatch, median")[1:3] == [
            "task events, queue wait included",
            "250 ms (n=2)",
        ]
        assert table_row(markdown, "Routing decision, median")[1:3] == [
            "MAS /metrics, B-92 router",
            "1,206 ms (n=2)",
        ]
        assert table_row(markdown, "Routing decision without the LLM, p90")[2] == "12 ms (n=1)"
        assert table_row(markdown, "Routed by the LLM fallback")[2:] == [
            "50.0% (n=2)",
            "50.0% (n=2)",
            "+0.0 pts",
        ]
        assert table_row(markdown, "Routing methods")[2:] == [
            "embedding 1, llm 1",
            "embedding 1, llm 1",
            "same",
        ]
        assert table_row(markdown, "Peak RAM of the stack (ADR-006 P)")[1:3] == [
            "docker stats total + model pages left out, in one sample",
            "11.50 GiB",
        ]
        assert table_row(markdown, "Peak RAM, all containers at once")[1:3] == [
            "docker stats samples",
            "9.00 GiB",
        ]
        assert table_row(markdown, "Model pages docker stats left out")[1:3] == [
            "llama-server RssFile, memory.stat, in the sample of P",
            "2.50 GiB",
        ]
        assert "RssFile" not in markdown.split("## Section 10 metrics")[0]
        assert table_row(markdown, "Peak RAM, llm, since it started")[2] == "5.00 GiB"
        assert table_row(markdown, "Out-of-memory kills")[2] == "1"
        assert table_row(markdown, "Container restarts")[2] == "0"
        assert table_row(markdown, "Peak swap used")[2] == "0.50 GiB"
        assert table_row(markdown, "Swap growth during the questions")[2] == "0.25 GiB"
        assert "memory.peak" not in markdown.split("## Section 10 metrics")[0]
        assert table_row(markdown, "Answer correct, two reviewers")[2:] == [
            "50.0% (n=2)",
            "50.0% (n=2)",
            "+0.0 pts",
        ]
        assert table_row(markdown, "Generation speed in the stack")[2] == "13.3 t/s (n=2)"
        assert table_row(markdown, "Install time without the model")[2:4] == ["—", "—"]
        assert table_row(markdown, "Docker memory")[1:] == ["15.0 GiB", "15.0 GiB"]
        assert table_row(markdown, "Model SHA-256")[1] == "3605803b982c…"

    def test_kv_cache_change_is_called_out_as_the_q8_quality_check(self, tmp_path, make_item):
        before = write(tmp_path, "f16.json", eval_report(make_item, [10.0], kv="f16"))
        after = write(tmp_path, "q8.json", eval_report(make_item, [10.0], kv="q8_0"))
        markdown = compare_markdown([before], [after], BenchSelection())
        assert table_row(markdown, "KV cache K/V (q8_0 quality check)")[2:] == [
            "f16/f16",
            "q8_0/q8_0",
            "changed",
        ]
        assert "The KV cache differs (f16/f16 before, q8_0/q8_0 after)" in markdown

    def test_a_peak_missed_between_samples_asks_for_a_shorter_interval(self, tmp_path, make_item):
        unsampled = {"llm": GIB, "mas": GIB // 2, "web_client": None, "agent": None}
        report = eval_report(make_item, [10.0], unsampled=unsampled)
        markdown = compare_markdown([write(tmp_path, "a.json", report)], None, BenchSelection())
        assert (
            "eval-cpu16: the memory.peak of llm, less its inactive page cache, went 1.00 GiB above its docker "
            "stats peak during the questions: a spike fell between two samples. Repeat the run with "
            "--sample-interval 2 before taking ADR-006's P from it."
        ) in markdown
        assert (
            "eval-cpu16: no sampling check for agent, web_client: a memory.peak or memory.stat could not be "
            "read (memory.peak needs cgroup v2 and Linux 5.19 or later), so a spike between two samples "
            "cannot be ruled out."
        ) in markdown
        assert "memory.peak of mas" not in markdown

    @pytest.mark.parametrize(
        ("stack_peak", "warning"),
        [
            (
                11 * GIB,
                "eval-cpu16: llama-server's RssFile or the llm memory.stat could not be read in 3 samples: "
                "ADR-006's P leaves them out.",
            ),
            (
                None,
                "eval-cpu16: llama-server's RssFile or the llm memory.stat could not be read in any of the 3 "
                "samples taken while llm ran, so ADR-006's P is unknown: fix the read and run again.",
            ),
        ],
    )
    def test_samples_without_the_llm_pages_are_called_out(
        self, tmp_path, make_item, stack_peak, warning
    ):
        report = eval_report(make_item, [10.0], stack_peak=stack_peak, samples_without_llm_pages=3)
        markdown = compare_markdown([write(tmp_path, "a.json", report)], None, BenchSelection())
        assert warning in markdown

    def test_unread_oom_kills_or_restarts_leave_their_rows_empty(self, tmp_path, make_item):
        report = eval_report(
            make_item, [10.0], oom_kills={"llm": 0, "agent": None, "mas": None}, restarts={}
        )
        markdown = compare_markdown([write(tmp_path, "a.json", report)], None, BenchSelection())
        assert table_row(markdown, "Out-of-memory kills")[2] == "—"
        assert table_row(markdown, "Container restarts")[2] == "—"
        assert (
            "eval-cpu16: the OOM kills of agent, mas could not be read, so its row stays empty."
            in markdown
        )
        assert (
            "eval-cpu16: the restart count of every container could not be read, so its row stays empty."
            in markdown
        )

    def test_pending_reviews_and_incomplete_runs_are_flagged(self, tmp_path, make_item):
        report = eval_report(make_item, [10.0], reviewed=False)
        report["run"]["completed"] = False
        markdown = compare_markdown([write(tmp_path, "a.json", report)], None, BenchSelection())
        assert "eval-cpu16: the run did not complete." in markdown
        assert "eval-cpu16: 1 answers still wait for the two reviewers." in markdown

    def test_the_recorded_2026_09_01_baseline_against_a_run(self, tmp_path, make_item):
        after = write(tmp_path, "eval.json", eval_report(make_item, [60.0, 120.0]))
        markdown = compare_markdown([BASELINE], [after], BenchSelection())
        assert table_row(markdown, "Total time, median")[2:] == [
            "854.0 s (n=1, 14m 14s)",
            "90.0 s (n=2)",
            "-764.0 s (-89%)",
        ]
        assert (
            table_row(markdown, "Answer correct, two reviewers")[2] == "0.0% (n=1, judged by hand)"
        )
        assert (
            table_row(markdown, "Total time, whole run")[4]
            == "not comparable: different question counts"
        )
        assert table_row(markdown, "Run started")[1] == "2026-09-01"
        assert table_row(markdown, "llama.cpp / runtime")[1:] == [
            "Transformers in-process (no llama.cpp)",
            "b11382",
        ]
        assert "cpu-transformers is a recorded result" in markdown
        assert "The two sides come from different machines." in markdown
        assert "## Notes" in markdown


class TestLlamaBench:
    def test_a_report_written_by_run_llama_bench_compares(self):
        markdown = compare_markdown(
            [BENCHMARKS / "cpu-laptop-2026-10-06.json"], None, BenchSelection()
        )
        assert markdown.startswith("# Benchmark\n")
        assert table_row(markdown, "Label")[1] == "cpu-laptop"
        assert table_row(markdown, "Prompt processing pp512")[2:] == ["172.6 t/s (t=12)"]

    def test_one_side_may_hold_a_bench_file_and_an_eval_file(self, tmp_path, make_item):
        bench = write(tmp_path, "cpu16.json", bench_rows())
        run = write(tmp_path, "eval.json", eval_report(make_item, [10.0]))
        markdown = compare_markdown([bench, run], None, BenchSelection())
        assert markdown.startswith("# Benchmark\n")
        assert table_row(markdown, "Generation tg128")[2] == "20.0 t/s (t=8)"
        assert table_row(markdown, "Total time, median")[2] == "10.0 s (n=1)"
        assert "Change" not in markdown.split("## Section 10 metrics")[1].splitlines()[2]


class TestInputs:
    def test_the_committed_baseline_is_a_recorded_result(self):
        document = load_document(BASELINE)
        assert document["kind"] == "horus-recorded"
        assert document["metrics"]["total_median_s"]["value"] == 854.0
        assert document["recorded"]["date"] == "2026-09-01"


@pytest.fixture(scope="module")
def compare_cli():
    path = REPO_ROOT / "scripts" / "benchmarks" / "compare-benchmarks.py"
    spec = importlib.util.spec_from_file_location("compare_benchmarks", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["compare_benchmarks"] = module
    spec.loader.exec_module(module)
    return module


class TestCommandLine:
    def test_main_prints_and_writes_the_section_10_markdown(
        self, compare_cli, tmp_path, make_item, capsys
    ):
        run = write(tmp_path, "eval.json", eval_report(make_item, [10.0]))
        out = tmp_path / "compare.md"
        assert compare_cli.main([str(BASELINE), str(run), "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert printed.startswith("# Benchmark comparison")
        assert "\n## Section 10 metrics\n" in printed
        assert out.read_text(encoding="utf-8") == printed
