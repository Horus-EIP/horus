# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit import __version__
from horus_bench_kit.cli.compare import chosen_files, main
from horus_bench_kit.compare import (
    LLAMA_BENCH_ROWS,
    BenchSelection,
    CompareProfile,
    Family,
    bench_metrics,
    build_side,
    compare_markdown,
    container_total,
    count_total,
    gib,
    load_document,
    methods_text,
    rate_metric,
    stat_metric,
)
from horus_bench_kit.llama_bench import BENCH_IMAGE, build_report, model_records, summary_rows
from horus_bench_kit.markdown import Metric, MetricRow
from horus_bench_kit.report import build_report as build_eval_report
from horus_bench_kit.report import question_record

SMALL = "alpha-1b-Q4_K_M.gguf"
LARGE = "alpha-1b-Q5_K_M.gguf"
GIB = 2**30
MACHINE = {
    "reference": "bench-01",
    "cpu_model": "Example CPU 6C",
    "physical_cores": 6,
    "avx2": True,
    "ram": "16 GiB installed",
    "ram_type": "DDR4",
    "ram_speed": "3200 MT/s",
    "disk_type": "NVMe SSD",
    "docker": {"mem_total_bytes": 15 * GIB},
}


def bench_rows():
    rows = []
    for model in (SMALL, LARGE):
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
                    speed *= 0.8 if model == LARGE else 1.0
                    speed *= 0.5 if depth else 1.0
                    rows.append(
                        {
                            "build_number": 11382,
                            "build_commit": "0a1b2c3d",
                            "model_filename": f"/models/{model}",
                            "model_type": "alpha 1B",
                            "n_threads": threads,
                            "type_k": type_kv,
                            "type_v": type_kv,
                            "flash_attn": -1,
                            "n_prompt": prompt,
                            "n_gen": generated,
                            "n_depth": depth,
                            "avg_ts": speed,
                            "stddev_ts": 1.0,
                        }
                    )
    return rows


def llama_bench_report(rows=None, label="bench-01"):
    rows = rows or bench_rows()
    return build_report(
        label=label,
        run={
            "started_at": "2026-10-08T09:00:00Z",
            "finished_at": "2026-10-08T09:30:00Z",
            "command": None,
        },
        image=BENCH_IMAGE,
        image_digest=None,
        rows=rows,
        models=model_records(
            [SMALL, LARGE], {SMALL: 1, LARGE: 2}, {SMALL: "a1" * 32, LARGE: "a2" * 32}
        ),
        machine=MACHINE,
    )


def kit_eval(make_item, totals, *, label="first-run", sha="d" * 64, reviewed=True, completed=True):
    item = make_item()
    records = []
    for index, total in enumerate(totals):
        outcome = {
            "mode": "chat",
            "status": "ok",
            "answer": "Fourteen lanterns." if index else "Twelve lanterns.",
            "timing_source": "http",
            "total_s": total,
            "ttft_s": total / 4,
            "models": ["alpha-1b"],
        }
        record = question_record(item, outcome)
        if reviewed:
            for slot in record["review"]:
                slot.update(reviewer="ana", answer_correct=bool(index))
        records.append(record)
    return build_eval_report(
        label=label,
        run={
            "target": "openai",
            "model": "alpha-1b",
            "started_at": "2026-10-08T10:00:00Z",
            "completed": completed,
        },
        testset={"version": "1.0.0", "sha256": sha},
        records=records,
    )


def write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def table_row(markdown, label):
    for line in markdown.splitlines():
        if line.startswith(f"| {label} |") or line.startswith(f"| {label} ("):
            return [cell.strip() for cell in line.strip("|").split(" | ")]
    raise AssertionError(f"no row {label!r} in:\n{markdown}")


class TestLlamaBench:
    def test_headline_rows_use_f16_kv_the_first_model_and_the_fastest_threads(self):
        metrics, choice = bench_metrics(summary_rows(bench_rows()), BenchSelection())
        assert metrics["pp512"] == Metric(200.0, note="t=8")
        assert metrics["tg128@d4096"] == Metric(10.0, note="t=8")
        assert "pp2048" not in metrics
        assert choice == f"{SMALL}, KV f16/f16, the fastest thread count"

    def test_selection_by_model_threads_and_kv(self):
        selection = BenchSelection(model="q5_k_m", threads=4, cache_type="q8_0")
        metrics, choice = bench_metrics(summary_rows(bench_rows()), selection)
        assert metrics["pp512"].value == 72.0
        assert choice == f"{LARGE}, KV q8_0/q8_0, 4 threads"

    def test_unknown_model_selects_nothing(self):
        metrics, choice = bench_metrics(summary_rows(bench_rows()), BenchSelection(model="omega"))
        assert metrics == {}
        assert choice.startswith("no matching model")

    def test_a_report_written_by_hbk_llama_bench_compares(self, tmp_path):
        report = llama_bench_report()
        assert isinstance(report["summary"], list)
        path = write(tmp_path, "bench-01-2026-10-08.json", report)
        markdown = compare_markdown([path], None, BenchSelection())
        assert markdown.startswith("# Benchmark\n")
        assert table_row(markdown, "Label")[1] == "bench-01"
        assert table_row(markdown, "Machine")[1] == "bench-01: Example CPU 6C (6 cores, AVX2)"
        assert table_row(markdown, "RAM")[1] == "16 GiB installed, DDR4, 3200 MT/s"
        assert table_row(markdown, "Docker memory")[1] == "15.0 GiB"
        assert table_row(markdown, "llama.cpp / runtime")[1] == "b11382"
        assert table_row(markdown, "Model")[1] == f"{SMALL}, {LARGE}"
        assert table_row(markdown, "Model SHA-256")[1] == "a1a1a1a1a1a1…, a2a2a2a2a2a2…"
        assert table_row(markdown, "Run started")[1] == "2026-10-08T09:00:00Z"
        assert table_row(markdown, "Prompt processing pp512")[2] == "200.0 t/s (t=8)"
        assert table_row(markdown, "Questions")[2] == "—"
        assert "\n- " not in markdown.split("## Metrics")[0]

    def test_a_real_shaped_report_and_an_evaluation_side_by_side(self, tmp_path, make_item):
        before = write(tmp_path, "bench-01-2026-10-08.json", llama_bench_report())
        after_bench = write(
            tmp_path,
            "bench-02-2026-10-08.json",
            llama_bench_report(
                [{**r, "avg_ts": r["avg_ts"] * 2} for r in bench_rows()], "bench-02"
            ),
        )
        after_eval = write(tmp_path, "first-run-2026-10-08.json", kit_eval(make_item, [10.0, 20.0]))
        markdown = compare_markdown([before], [after_bench, after_eval], BenchSelection())
        assert markdown.startswith("# Benchmark comparison\n")
        assert table_row(markdown, "Label")[1:] == ["bench-01", "bench-02 + first-run"]
        assert table_row(markdown, "Generation tg128")[2:] == [
            "20.0 t/s (t=8)",
            "40.0 t/s (t=8)",
            "+20.0 t/s (+100%)",
        ]
        assert table_row(markdown, "Total time, median")[2:] == ["—", "15.0 s (n=2)", "—"]

    def test_raw_and_enriched_files_compare_row_by_row(self, tmp_path):
        raw = write(tmp_path, "bench-raw.json", bench_rows())
        slower = [{**row, "avg_ts": row["avg_ts"] / 2} for row in bench_rows()]
        enriched = write(tmp_path, "bench-01-2026-10-08.json", llama_bench_report(slower))
        markdown = compare_markdown([raw], [enriched], BenchSelection())
        assert table_row(markdown, "Prompt processing pp512")[2:] == [
            "200.0 t/s (t=8)",
            "100.0 t/s (t=8)",
            "-100.0 t/s (-50%)",
        ]
        assert "## llama-bench, every configuration" in markdown
        detail = [
            line
            for line in markdown.splitlines()
            if line.startswith(f"| {LARGE} | tg128 | 4096 | q8_0/q8_0 | 4 |")
        ]
        assert detail == [
            f"| {LARGE} | tg128 | 4096 | q8_0/q8_0 | 4 | 3.60 t/s (± 1.0) | 1.80 t/s (± 1.0) | -1.80 t/s (-50%) |"
        ]
        assert table_row(markdown, "Label")[1] == "bench-raw"


class TestEvaluations:
    def test_two_runs_give_values_and_changes(self, tmp_path, make_item):
        before = write(tmp_path, "a.json", kit_eval(make_item, [20.0, 40.0], label="before"))
        after = write(tmp_path, "b.json", kit_eval(make_item, [10.0, 20.0], label="after"))
        markdown = compare_markdown([before], [after], BenchSelection())
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
        assert table_row(markdown, "Answer correct, two reviewers")[2:] == [
            "50.0% (n=2)",
            "50.0% (n=2)",
            "+0.0 pts",
        ]
        assert table_row(markdown, "Answer correct, automatic")[2] == "50.0% (n=2)"
        assert table_row(markdown, "Fallback answers")[2] == "0 (n=2)"
        assert table_row(markdown, "Model")[1:] == ["alpha-1b", "alpha-1b"]
        assert table_row(markdown, "Test set")[1] == "1.0.0 (dddddddddddd…)"

    def test_unfinished_runs_pending_reviews_and_other_test_sets_are_flagged(
        self, tmp_path, make_item
    ):
        before = write(
            tmp_path,
            "a.json",
            kit_eval(make_item, [10.0], label="first", reviewed=False, completed=False),
        )
        after = write(tmp_path, "b.json", kit_eval(make_item, [10.0], label="second", sha="e" * 64))
        markdown = compare_markdown([before], [after], BenchSelection())
        assert "- first: the run did not complete." in markdown
        assert "- first: 1 answers still wait for the two reviewers." in markdown
        assert (
            "- The two runs used different test sets: the answer and source rates are not comparable."
            in markdown
        )

    def test_different_machines_are_flagged(self, tmp_path):
        other = {**MACHINE, "cpu_model": "Example CPU 12C"}
        before = write(tmp_path, "a.json", llama_bench_report())
        after = write(tmp_path, "b.json", {**llama_bench_report(), "machine": other})
        assert "The two sides come from different machines." in compare_markdown(
            [before], [after], BenchSelection()
        )


def acme_metrics(document):
    return {
        "queue_s": Metric(document["summary"]["queue_s"], n=document["summary"]["n"]),
        "kv_cache": Metric(document["kv"]),
    }


ACME = CompareProfile(
    rows=(
        *LLAMA_BENCH_ROWS,
        MetricRow("queue_s", "Queue time", "acme scheduler", "s"),
        MetricRow("kv_cache", "KV cache", "server", "text"),
    ),
    families=(
        Family(
            "acme-eval",
            2,
            acme_metrics,
            warnings=lambda document: [f"{document['label']}: acme warning"],
            build=lambda document: document.get("runtime"),
            started=lambda document: document.get("date"),
            model=lambda document: (document.get("engine"), None),
        ),
    ),
    heading="## Acme metrics",
)


def acme(label, queue, kv="f16/f16", version=2):
    return {
        "kind": "acme-eval",
        "schema_version": version,
        "label": label,
        "runtime": "acme-runtime 3",
        "date": "2026-10-01",
        "engine": "acme-engine",
        "kv": kv,
        "summary": {"queue_s": queue, "n": 3},
        "notes": ["measured by hand"],
    }


class TestProductFamilies:
    def test_a_product_registers_its_kind_rows_warnings_and_header_values(self, tmp_path):
        before = write(tmp_path, "a.json", acme("old", 2.0))
        after = write(tmp_path, "b.json", acme("new", 1.0, kv="q8_0/q8_0"))
        markdown = compare_markdown([before], [after], BenchSelection(), ACME)
        assert "## Acme metrics" in markdown
        assert table_row(markdown, "Queue time")[1:] == [
            "acme scheduler",
            "2.00 s (n=3)",
            "1.00 s (n=3)",
            "-1.00 s (-50%)",
        ]
        assert table_row(markdown, "llama.cpp / runtime")[1:] == [
            "acme-runtime 3",
            "acme-runtime 3",
        ]
        assert table_row(markdown, "Run started")[1] == "2026-10-01"
        assert table_row(markdown, "Model")[1] == "acme-engine"
        assert "- old: acme warning" in markdown
        assert "The KV cache differs (f16/f16 before, q8_0/q8_0 after)" in markdown
        assert "## Notes\n\n- old: measured by hand\n- new: measured by hand" in markdown

    def test_the_kits_own_evaluation_kind_is_unknown_to_a_profile_that_drops_it(
        self, tmp_path, make_item
    ):
        path = write(tmp_path, "first.json", kit_eval(make_item, [1.0]))
        with pytest.raises(ValueError, match="not a benchmark file"):
            load_document(path, ACME)


class TestInputs:
    def test_two_files_of_the_same_family_on_one_side_are_refused(self, tmp_path, make_item):
        documents = [
            load_document(write(tmp_path, f"{name}.json", kit_eval(make_item, [1.0])))
            for name in "ab"
        ]
        with pytest.raises(
            ValueError, match="at most one llama-bench file and one end-to-end file"
        ):
            build_side("before", documents, BenchSelection())

    def test_other_json_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="not a benchmark file"):
            load_document(write(tmp_path, "x.json", {"kind": "something"}))

    def test_a_newer_schema_version_is_refused(self, tmp_path, make_item):
        newer = {**llama_bench_report(), "schema_version": 2}
        with pytest.raises(ValueError, match="schema_version 2 is newer than the 1"):
            load_document(write(tmp_path, "new.json", newer))
        with pytest.raises(ValueError, match="newer than the 2"):
            load_document(write(tmp_path, "acme.json", acme("x", 1.0, version=3)), ACME)


class TestCommandLine:
    def test_file_choices(self):
        parse = (
            __import__("horus_bench_kit.cli.compare", fromlist=["build_parser"])
            .build_parser()
            .parse_args
        )
        assert chosen_files(parse(["a.json", "b.json"])) == (["a.json"], ["b.json"])
        assert chosen_files(parse(["a.json"])) == (["a.json"], [])
        assert chosen_files(parse(["--before", "a.json", "b.json", "--after", "c.json"])) == (
            ["a.json", "b.json"],
            ["c.json"],
        )
        for argv in (
            [],
            ["a.json", "b.json", "c.json"],
            ["a.json", "--before", "b.json"],
            ["--after", "a.json"],
        ):
            with pytest.raises(ValueError):
                chosen_files(parse(argv))

    def test_main_prints_and_writes_the_markdown(self, tmp_path, capsys):
        bench = write(tmp_path, "bench.json", llama_bench_report())
        out = tmp_path / "compare.md"
        assert main([str(bench), "--out", str(out), "--kv", "q8_0", "--threads", "4"]) == 0
        printed = capsys.readouterr().out
        assert printed.startswith("# Benchmark\n")
        assert out.read_text(encoding="utf-8") == printed
        assert (
            table_row(printed, "llama-bench rows shown")[1] == f"{SMALL}, KV q8_0/q8_0, 4 threads"
        )

    def test_main_reports_a_missing_file(self, tmp_path, capsys):
        assert main([str(tmp_path / "missing.json")]) == 2
        assert capsys.readouterr().out.startswith("[error]")

    def test_the_version_option_can_be_left_out(self, capsys):
        with pytest.raises(SystemExit) as stopped:
            main(["--version"])
        assert (stopped.value.code, capsys.readouterr().out.strip()) == (
            0,
            f"hbk-compare {__version__}",
        )
        with pytest.raises(SystemExit) as refused:
            main(["--version"], version_option=False)
        assert refused.value.code == 2


def test_metric_helpers_for_product_families():
    assert stat_metric(
        {"total_s": {"n": 3, "median": 0.0123}}, "total_s", "median", 1000.0
    ) == Metric(12.3, 3)
    assert stat_metric({}, "total_s", "median") == Metric(None, None)
    assert rate_metric({"n": 4, "correct": 3, "pct": 75.0}) == Metric(75.0, 4)
    assert rate_metric(None) == Metric(None, None)
    assert count_total({"timeout": 2, "too_long": 1}) == 3
    assert count_total(None) is None
    assert container_total({"a": 1, "b": 0}) == 1
    assert container_total({"a": 1, "b": None}) is None
    assert container_total({}) is None
    assert gib(3 * GIB // 2) == 1.5
    assert gib("x") is None
    assert methods_text({"rules": 2, "embedding": 5}) == "embedding 5, rules 2"
    assert methods_text({}) is None
