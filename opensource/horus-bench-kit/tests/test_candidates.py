# SPDX-License-Identifier: Apache-2.0
import copy
import json

import pytest

from conftest import GIB
from horus_bench_kit.candidates import (
    NAME_COLUMNS,
    REPORT_KIND,
    CandidatesProfile,
    Column,
    MarkdownTexts,
    Variant,
    all_variants,
    bench_speeds,
    build_number,
    build_report,
    catalog_problems,
    contract_headline,
    download_url,
    eval_headline,
    known_models_of,
    load_catalog,
    markdown_summary,
    rate_cell,
    select_variants,
    variant_gate,
    variant_summary,
    written_report,
)


def variant_by_id(catalog, gguf_id):
    return next(v for v in all_variants(catalog) if v.id == gguf_id)


class TestCatalog:
    def test_the_synthetic_catalog_is_valid(self, catalog):
        assert catalog_problems(catalog) == []

    def test_the_example_catalog_is_valid_and_the_same_in_yaml_and_json(self, examples):
        from_json = load_catalog(examples / "catalog.json")
        assert catalog_problems(from_json) == []
        pytest.importorskip("yaml")
        assert load_catalog(examples / "catalog.yaml") == from_json

    def test_download_urls_pin_the_revision(self, catalog):
        variant = variant_by_id(catalog, "beta-2b-q4km")
        assert (
            variant.url
            == f"https://huggingface.co/example/models-GGUF/resolve/{'1' * 40}/beta_2b_Q4_K_M.gguf"
        )
        assert download_url(variant.gguf) == variant.url
        assert variant.known_model().sha256 == "b1" * 32

    def test_known_models_cover_every_gguf(self, catalog):
        known = known_models_of(catalog)
        assert len(known) == 5
        assert known["alpha-1b-Q5_K_M.gguf"].size_bytes == 900_000_000

    def test_an_older_catalog_may_call_the_name_plan_name(self, catalog):
        older = copy.deepcopy(catalog)
        for entry in older["candidates"]:
            entry["plan_name"] = entry.pop("name")
        assert catalog_problems(older) == []
        assert variant_by_id(older, "beta-2b-q4km").name == "Beta-2B"
        del older["candidates"][1]["plan_name"]
        assert catalog_problems(older) == ["candidate beta-2b: missing name"]

    def test_a_product_can_require_its_own_name_key(self, catalog):
        assert catalog_problems(catalog, "label") == [
            f"candidate {candidate['id']}: missing label" for candidate in catalog["candidates"]
        ]
        labelled = copy.deepcopy(catalog)
        for entry in labelled["candidates"]:
            entry["label"] = entry["name"].upper()
        assert catalog_problems(labelled, "label") == []
        assert {v.name for v in select_variants(labelled, name_key="label")} == {
            "ALPHA-1B",
            "BETA-2B",
            "GAMMA-3B",
        }
        assert {v.name for v in all_variants(labelled)} == {"Alpha-1B", "Beta-2B", "Gamma-3B"}
        labelled["candidates"][0]["label"] = " "
        assert catalog_problems(labelled, "label") == [
            "candidate alpha-1b: label must be a non-empty string"
        ]

    def test_build_number(self):
        assert build_number("b11382") == 11382
        assert build_number("11382") is None
        assert build_number(None) is None


class TestCatalogProblems:
    def broken(self, catalog, mutate):
        copied = copy.deepcopy(catalog)
        mutate(copied)
        return catalog_problems(copied)

    def test_duplicate_files_and_ids_are_refused(self, catalog):
        def duplicate(c):
            c["candidates"][1]["ggufs"][0]["file"] = c["candidates"][0]["ggufs"][0]["file"]
            c["candidates"][2]["id"] = c["candidates"][1]["id"]

        problems = self.broken(catalog, duplicate)
        assert "gguf files must be unique: alpha-1b-Q4_K_M.gguf" in problems
        assert "candidate ids must be unique: beta-2b" in problems

    def test_a_build_newer_than_the_pin_is_refused(self, catalog):
        problems = self.broken(
            catalog, lambda c: c["candidates"][1]["llama_cpp"].update(since_build=99999)
        )
        assert problems == [
            "candidate beta-2b: needs llama.cpp b99999, newer than the pinned b11382"
        ]

    def test_hashes_revisions_and_sizes_are_checked(self, catalog):
        def damage(c):
            c["candidates"][1]["ggufs"][0].update(
                sha256="ABC", revision="main", size_bytes=0, file="../x.gguf", default="yes"
            )

        problems = self.broken(catalog, damage)
        label = "candidate beta-2b gguf beta-2b-q4km"
        assert f"{label}: sha256 must be 64 lower-case hexadecimal characters" in problems
        assert f"{label}: revision must be a 40-character commit id" in problems
        assert f"{label}: size_bytes must be a positive whole number" in problems
        assert f"{label}: file must be a plain .gguf file name" in problems
        assert f"{label}: default must be true or false" in problems

    def test_missing_fields_images_and_baseline_are_reported(self, catalog):
        def strip(c):
            del c["candidates"][1]["licence_statement"]
            c["candidates"][0]["role"] = "candidate"
            c["llama_cpp"]["bench_image"] = "ghcr.io/ggml-org/llama.cpp:full"

        problems = self.broken(catalog, strip)
        assert "candidate beta-2b: missing licence_statement" in problems
        assert "the catalog needs a baseline candidate" in problems
        assert "llama_cpp.bench_image must be tagged with the pinned build b11382" in problems

    def test_a_candidate_without_a_default_gguf_is_reported(self, catalog):
        def no_default(c):
            for entry in c["candidates"][2]["ggufs"]:
                entry["default"] = False

        assert self.broken(catalog, no_default) == [
            "candidate gamma-3b: at least one gguf must be a default"
        ]

    def test_other_shapes_are_refused(self):
        assert catalog_problems([]) == ["the catalog must be a mapping"]
        assert catalog_problems({"version": "1"})[0] == "missing top-level llama_cpp"


class TestSelectionAndGate:
    def test_defaults_are_one_file_per_candidate(self, catalog):
        assert [v.id for v in select_variants(catalog)] == [
            "alpha-1b-q4km",
            "beta-2b-q4km",
            "gamma-3b-q4km",
        ]

    def test_only_takes_candidate_or_gguf_ids(self, catalog):
        assert [v.id for v in select_variants(catalog, ["gamma-3b"])] == ["gamma-3b-q4km"]
        assert [v.id for v in select_variants(catalog, ["gamma-3b"], all_quants=True)] == [
            "gamma-3b-q4km",
            "gamma-3b-q8",
        ]
        assert [v.id for v in select_variants(catalog, ["gamma-3b-q8", "alpha-1b-q4km"])] == [
            "alpha-1b-q4km",
            "gamma-3b-q8",
        ]

    def test_an_unknown_id_is_an_error(self, catalog):
        with pytest.raises(ValueError, match="unknown candidate or gguf id: delta-4b"):
            select_variants(catalog, ["delta-4b"])

    def test_all_quants_selects_every_file(self, catalog):
        assert len(select_variants(catalog, all_quants=True)) == 5

    def test_a_licence_outside_the_list_or_a_newer_build_is_gated(self, catalog):
        copied = copy.deepcopy(catalog)
        copied["candidates"][2]["licence"] = "Custom"
        copied["candidates"][2]["llama_cpp"]["since_build"] = 12000
        variant = variant_by_id(copied, "gamma-3b-q4km")
        assert variant_gate(variant, copied) == [
            "the licence Custom is not one of Apache-2.0, MIT",
            "needs llama.cpp b12000, the catalog pins b11382",
        ]
        assert (
            variant_gate(variant, copied, "needs b{since}, pinned b{pinned}")[1]
            == "needs b12000, pinned b11382"
        )
        assert variant_gate(variant_by_id(catalog, "beta-2b-q4km"), catalog) == []


def test_written_report_takes_the_last_path_a_tool_printed():
    lines = [
        "[info] 9 question(s), writing /b/x-eval-2026-10-08.json",
        "[ 1/9] ...",
        "[done] wrote /b/x-eval-2026-10-08.json",
    ]
    assert written_report(lines) == "/b/x-eval-2026-10-08.json"
    assert (
        written_report(["[info] 5 question(s), writing D:\\b\\y.json", "[error] stopped"])
        == "D:\\b\\y.json"
    )
    assert written_report(["nothing"]) is None


def bench_report(file):
    rows = []
    for threads, scale in ((4, 1.0), (8, 1.5)):
        for test, depth, tps in (
            ("pp512", 0, 60.0),
            ("pp512", 4096, 40.0),
            ("pp2048", 0, 50.0),
            ("tg128", 0, 9.0),
            ("tg128", 4096, 7.0),
        ):
            rows.append(
                {
                    "model": file,
                    "test": test,
                    "n_depth": depth,
                    "type_k": "f16",
                    "type_v": "f16",
                    "n_threads": threads,
                    "avg_ts": tps * scale,
                    "stddev_ts": 0.5,
                }
            )
        rows.append(
            {
                "model": file,
                "test": "tg128",
                "n_depth": 0,
                "type_k": "q8_0",
                "type_v": "q8_0",
                "n_threads": threads,
                "avg_ts": 99.0,
                "stddev_ts": 0.1,
            }
        )
    return {
        "kind": "horus-llama-bench",
        "llama_cpp": {"build": "b11382"},
        "models": [{"file": file, "sha256": "b1" * 32}],
        "summary": rows,
    }


def kit_eval_report():
    return {
        "kind": "horus-bench-kit-eval",
        "run": {"completed": True},
        "summary": {
            "questions": 9,
            "status": {"ok": 9},
            "answer_correct_auto": {"n": 9, "correct": 7, "pct": 77.8},
            "source_correct_auto": {"n": 0, "correct": 0, "pct": None},
            "route_correct": {"n": 0, "correct": 0, "pct": None},
            "manual_review": {"answer_correct_pct": 66.7, "pending": 0},
            "fallbacks": {},
            "total_s": {"n": 9, "median": 4.25, "p90": 9.0},
            "ttft_s": {"n": 9, "median": 0.61},
        },
    }


def contract_report():
    return {
        "kind": "horus-contract-probe",
        "summary": {
            "replies": 8,
            "json_valid": {"n": 8, "correct": 7, "pct": 87.5},
            "expected_correct": {"n": 8, "correct": 6, "pct": 75.0},
            "patterns_correct": {"n": 4, "correct": 3, "pct": 75.0},
            "failures": {"truncated": 1},
            "thought_first": 0,
            "truncated": 1,
            "wall_s": {"n": 8, "median": 2.4},
            "completion_tokens": {"n": 8, "median": 41},
            "prompt_tps": 51.2,
            "generation_tps": 9.4,
            "by_category": {},
        },
    }


class TestAggregation:
    def test_bench_speeds_keep_the_fastest_thread_count_for_the_cache_type(self):
        speeds = bench_speeds(bench_report("x.gguf"))
        assert [(s["test"], s["depth"], s["tps"], s["threads"]) for s in speeds] == [
            ("pp512", 0, 90.0, 8),
            ("pp512", 4096, 60.0, 8),
            ("pp2048", 0, 75.0, 8),
            ("tg128", 0, 13.5, 8),
            ("tg128", 4096, 10.5, 8),
        ]
        assert bench_speeds(bench_report("x.gguf"), "q8_0")[0]["tps"] == 99.0
        assert bench_speeds(None) == []

    def test_headlines(self):
        assert eval_headline(kit_eval_report()) == {
            "completed": True,
            "questions": 9,
            "status": {"ok": 9},
            "answer_correct_auto": {"n": 9, "correct": 7, "pct": 77.8},
            "answer_correct_reviewed_pct": 66.7,
            "review_pending": 0,
            "source_correct_auto": {"n": 0, "correct": 0, "pct": None},
            "route_correct": {"n": 0, "correct": 0, "pct": None},
            "fallbacks": {},
            "total_s": {"n": 9, "median": 4.25, "p90": 9.0},
            "ttft_s": {"n": 9, "median": 0.61},
        }
        assert eval_headline(None) is None
        assert contract_headline(contract_report())["expected_correct"]["pct"] == 75.0
        assert "by_category" not in contract_headline(contract_report())
        assert contract_headline(contract_report(), ("replies",)) == {"replies": 8}
        assert contract_headline(None) is None

    def test_variant_summary_and_report(self, catalog):
        variant = variant_by_id(catalog, "beta-2b-q4km")
        summary = variant_summary(
            variant,
            fetch={"status": "verified", "method": "docker"},
            reports={"eval": "model-candidates-2026-10-08/beta-2b-q4km-eval-2026-10-08.json"},
            bench_report=bench_report(variant.file),
            contract_report=contract_report(),
            eval_report=kit_eval_report(),
            server={"build": "b11382"},
            memory={
                "after_probe": {
                    "process": {"vm_hwm_bytes": GIB},
                    "cgroup_peak_bytes": GIB + 7,
                    "oom_kills": 0,
                }
            },
            problems=[],
        )
        assert list(summary) == [
            "id",
            "candidate",
            "role",
            "name",
            "model_repo",
            "licence",
            "licence_flags",
            "gguf_architecture",
            "thinking_default",
            "quant",
            "file",
            "gguf_repo",
            "revision",
            "publisher",
            "size_bytes",
            "sha256",
            "fetch",
            "reports",
            "llama_bench",
            "contract",
            "eval",
            "server",
            "memory",
            "problems",
        ]
        assert summary["name"] == "Beta-2B"
        assert summary["llama_bench"]["sha256_matches_catalog"] is True
        assert summary["reports"] == {
            "llama_bench": None,
            "contract": None,
            "eval": "model-candidates-2026-10-08/beta-2b-q4km-eval-2026-10-08.json",
        }
        report = build_report(
            run={"started_at": "2026-10-08T08:00:00Z"},
            catalog={"version": "1.0.0"},
            machine=None,
            variants=[summary],
        )
        assert list(report) == [
            "kind",
            "schema_version",
            "label",
            "catalog",
            "run",
            "machine",
            "variants",
        ]
        assert (report["kind"], report["schema_version"], report["label"]) == (
            REPORT_KIND,
            1,
            "model-candidates",
        )
        assert report["machine"] == {}
        json.dumps(report)

    def test_a_product_profile_changes_the_kind_and_the_headlines(self, catalog):
        profile = CandidatesProfile(
            kind="acme-model-candidates",
            label="acme-candidates",
            contract_keys=("replies",),
            eval_headline=lambda report: {"own": (report or {}).get("kind")},
        )
        summary = variant_summary(
            variant_by_id(catalog, "alpha-1b-q4km"),
            profile=profile,
            contract_report=contract_report(),
            eval_report={"kind": "acme-eval"},
        )
        assert summary["contract"] == {"replies": 8}
        assert summary["eval"] == {"own": "acme-eval"}
        report = build_report(run={}, catalog={}, machine={}, variants=[summary], profile=profile)
        assert (report["kind"], report["label"]) == ("acme-model-candidates", "acme-candidates")


class TestMarkdown:
    def report(self, catalog):
        done = variant_summary(
            variant_by_id(catalog, "alpha-1b-q4km"),
            bench_report=bench_report("alpha-1b-Q4_K_M.gguf"),
            contract_report=contract_report(),
            eval_report=kit_eval_report(),
            memory={
                "after_eval": {
                    "process": {"vm_hwm_bytes": 3 * GIB},
                    "cgroup_peak_bytes": 4 * GIB,
                    "oom_kills": 0,
                }
            },
        )
        failed = variant_summary(
            variant_by_id(catalog, "beta-2b-q4km"),
            fetch={"status": "failed", "error": "HTTP 404"},
            problems=["download failed: HTTP 404"],
        )
        return build_report(
            run={
                "started_at": "2026-10-08T08:00:00Z",
                "steps": ["fetch", "bench", "probe", "eval"],
                "reasoning": "off",
                "completed": True,
            },
            catalog={"path": "catalog.yaml", "version": "1.0.0", "pinned_build": "b11382"},
            machine={
                "reference": "bench-01",
                "cpu_model": "Example CPU 6C",
                "ram": "16 GiB installed",
            },
            variants=[done, failed],
        )

    def test_rows_show_measured_values_and_dashes_for_the_rest(self, catalog):
        text = markdown_summary(self.report(catalog))
        lines = text.splitlines()
        assert lines[0] == "# Model candidates, 2026-10-08"
        assert lines[2] == (
            "Catalog `catalog.yaml` version 1.0.0, llama.cpp b11382, reasoning `off`, steps fetch, bench, probe, eval. "
            "Machine: bench-01, Example CPU 6C, 16 GiB installed. Run completed."
        )
        assert "evaluation columns from the 9-question evaluation." in text
        rows = [line for line in lines if line.startswith("| Alpha-1B (baseline)")]
        assert rows[0] == (
            "| Alpha-1B (baseline) | Q4_K_M, community | Apache-2.0 | 7/8 (87.5%) | 0 | 6/8 (75.0%) | "
            "3/4 (75.0%) | 7/9 (77.8%) | 66.7% | – |"
        )
        assert rows[1] == (
            "| Alpha-1B (baseline) | Q4_K_M, community | 0.84 GiB | 90.0 | 75.0 | 13.5 | 10.5 | 2.4 | 4.2 | 0.6 | "
            "3.00 GiB | 4.00 GiB | 0 |"
        )
        failed = [line for line in lines if line.startswith("| Beta-2B")]
        assert failed[0].count("–") == 7
        assert "- `beta-2b-q4km`: download failed: HTTP 404" in lines
        assert "- Beta-2B: The licence is only in the card metadata." in lines

    def test_texts_and_columns_come_from_the_profile(self, catalog):
        texts = MarkdownTexts(
            title="# Screening {date}",
            quality_intro="Answers from {evaluation}.",
            quality_columns=(*NAME_COLUMNS, Column("Valid", rate_cell("contract", "json_valid"))),
            speed_heading="## Speed",
            speed_intro="Fast or not.",
            speed_columns=NAME_COLUMNS,
        )
        text = markdown_summary(self.report(catalog), texts)
        assert text.startswith("# Screening 2026-10-08\n")
        assert "Answers from the 9-question evaluation." in text
        assert (
            "| Model | GGUF | Valid |\n|---|---|---:|\n| Alpha-1B (baseline) | Q4_K_M, community | 7/8 (87.5%) |"
            in text
        )
        assert "## Speed\n\nFast or not.\n\n| Model | GGUF |" in text

    def test_the_evaluation_name_follows_the_question_counts(self, catalog):
        report = self.report(catalog)
        report["variants"][1]["eval"] = {"questions": 20}
        assert "from the evaluation (9 to 20 questions)." in markdown_summary(report)
        for variant in report["variants"]:
            variant["eval"] = None
        assert "evaluation columns from the evaluation." in markdown_summary(report)

    def test_licence_flags_are_listed_once_per_candidate(self, catalog):
        report = self.report(catalog)
        report["variants"].append(dict(report["variants"][1]))
        assert (
            markdown_summary(report).count("- Beta-2B: The licence is only in the card metadata.")
            == 1
        )


def test_a_variant_is_a_candidate_and_one_of_its_files(catalog):
    variant = Variant(catalog["candidates"][0], catalog["candidates"][0]["ggufs"][1])
    assert (variant.id, variant.file, variant.name) == (
        "alpha-1b-q5km",
        "alpha-1b-Q5_K_M.gguf",
        "Alpha-1B",
    )
