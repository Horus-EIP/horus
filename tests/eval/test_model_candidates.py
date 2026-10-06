import copy
import json
from pathlib import Path

import pytest
from bench_llama import BENCH_IMAGE, FETCH_IMAGE, KNOWN_MODELS
from model_candidates import (
    CANDIDATE_CONTAINER,
    DEFAULT_CATALOG,
    REPORT_KIND,
    Variant,
    all_variants,
    bench_speeds,
    build_number,
    build_report,
    candidate_network,
    candidate_run_command,
    catalog_problems,
    contract_headline,
    download_url,
    eval_headline,
    load_catalog,
    markdown_summary,
    parse_container_env,
    parse_container_inspect,
    parse_memory_limit,
    parse_process_memory,
    response_cache_finding,
    select_variants,
    server_args,
    setting_enabled,
    variant_gate,
    variant_summary,
    written_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "models" / "manifest.json"
PLAN_CANDIDATES = {"Spark-X2.5-4B", "NeoHorse-1-4B", "Agents-A1-4B", "Ling-3.0-tiny", "gemma-4-E4B"}
STACK_ARGS = [
    "--model", "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
    "--alias", "qwen3-4b",
    "--host", "0.0.0.0",
    "--port", "8080",
    "--ctx-size", "8192",
    "--parallel", "1",
    "--cache-type-k", "f16",
    "--cache-type-v", "f16",
    "--flash-attn", "auto",
    "--load-mode", "mmap",
    "--cache-ram", "1024",
    "--threads", "4",
    "--metrics",
]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(DEFAULT_CATALOG)


def variant_by_id(catalog, gguf_id):
    return next(v for v in all_variants(catalog) if v.id == gguf_id)


class TestCatalog:
    def test_the_versioned_catalog_is_valid(self, catalog):
        assert catalog_problems(catalog) == []

    def test_it_holds_the_baseline_and_the_five_plan_candidates(self, catalog):
        names = {c["plan_name"] for c in catalog["candidates"] if c["role"] == "candidate"}
        assert names == PLAN_CANDIDATES
        baseline = [c for c in catalog["candidates"] if c["role"] == "baseline"]
        assert [c["model_repo"] for c in baseline] == ["Qwen/Qwen3-4B-Instruct-2507"]
        assert {g["quant"] for g in baseline[0]["ggufs"]} == {"Q4_K_M", "Q5_K_M"}

    def test_the_baseline_files_are_the_ones_the_stack_and_b91_use(self, catalog):
        baseline = next(c for c in catalog["candidates"] if c["role"] == "baseline")
        for gguf in baseline["ggufs"]:
            known = KNOWN_MODELS[gguf["file"]]
            assert (gguf["size_bytes"], gguf["sha256"], download_url(gguf)) == (known.size_bytes, known.sha256, known.url)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        q4 = next(m for m in manifest["models"] if m["id"] == "qwen3-4b-q4km")
        assert download_url(baseline["ggufs"][0]) in q4["mirrors"]

    def test_the_pinned_build_is_the_stacks(self, catalog):
        assert catalog["llama_cpp"]["bench_image"] == BENCH_IMAGE
        assert catalog["llama_cpp"]["server_image"] == FETCH_IMAGE
        compose = (REPO_ROOT / "src" / "infra" / "docker-compose.cpu.yml").read_text(encoding="utf-8")
        assert catalog["llama_cpp"]["server_image"] in compose

    def test_every_licence_is_allowed_and_every_card_statement_is_recorded(self, catalog):
        assert catalog["licences_allowed"] == ["Apache-2.0", "MIT"]
        for variant in all_variants(catalog):
            assert variant_gate(variant, catalog) == []
        assert {c["id"]: c["licence"] for c in catalog["candidates"]}["ling-3.0-tiny"] == "MIT"

    def test_the_architectures_the_plan_names(self, catalog):
        by_name = {c["plan_name"]: c for c in catalog["candidates"]}
        assert by_name["Ling-3.0-tiny"]["gguf_architecture"] == "bailingmoe3"
        assert by_name["Ling-3.0-tiny"]["active_parameters"] == 1_300_000_000
        assert by_name["Spark-X2.5-4B"]["llama_cpp"]["since_build"] == 10828
        pinned = build_number(catalog["llama_cpp"]["pinned_build"])
        assert pinned == 11382
        assert all((c["llama_cpp"]["since_build"] or 0) <= pinned for c in catalog["candidates"])

    def test_every_candidate_has_one_default_from_its_own_publisher(self, catalog):
        for candidate in catalog["candidates"]:
            if candidate["role"] != "candidate":
                continue
            defaults = [g for g in candidate["ggufs"] if g["default"]]
            assert len(defaults) == 1, candidate["id"]
            assert defaults[0]["publisher"] == "model author", candidate["id"]

    def test_download_urls_pin_the_revision(self, catalog):
        for variant in all_variants(catalog):
            gguf = variant.gguf
            assert variant.url == f"https://huggingface.co/{gguf['repo']}/resolve/{gguf['revision']}/{gguf['upstream_file']}"


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
        assert "gguf files must be unique: qwen3-4b-instruct-2507-Q4_K_M.gguf" in problems
        assert "candidate ids must be unique: spark-x2.5-4b" in problems

    def test_a_build_newer_than_the_pin_is_refused(self, catalog):
        problems = self.broken(catalog, lambda c: c["candidates"][1]["llama_cpp"].update(since_build=99999))
        assert problems == ["candidate spark-x2.5-4b: needs llama.cpp b99999, newer than the pinned b11382"]

    def test_hashes_revisions_and_sizes_are_checked(self, catalog):
        def damage(c):
            gguf = c["candidates"][1]["ggufs"][0]
            gguf.update(sha256="ABC", revision="main", size_bytes=0, file="../x.gguf", default="yes")

        problems = self.broken(catalog, damage)
        label = "candidate spark-x2.5-4b gguf spark-x2.5-4b-q4km"
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
        assert "candidate spark-x2.5-4b: missing licence_statement" in problems
        assert "the catalog needs a baseline candidate" in problems
        assert "llama_cpp.bench_image must be tagged with the pinned build b11382" in problems

    def test_a_candidate_without_a_default_gguf_is_reported(self, catalog):
        def no_default(c):
            for gguf in c["candidates"][2]["ggufs"]:
                gguf["default"] = False

        assert self.broken(catalog, no_default) == ["candidate neohorse-1-4b: at least one gguf must be a default"]

    def test_a_licence_outside_the_list_is_gated(self, catalog):
        copied = copy.deepcopy(catalog)
        copied["candidates"][5]["licence"] = "Gemma"
        variant = next(v for v in all_variants(copied) if v.candidate["id"] == "gemma-4-e4b-it")
        assert variant_gate(variant, copied) == ["the licence Gemma is not one of Apache-2.0, MIT"]


class TestSelection:
    def test_defaults_are_both_baseline_quants_and_one_file_per_candidate(self, catalog):
        ids = [v.id for v in select_variants(catalog)]
        assert ids == [
            "qwen3-4b-q4km",
            "qwen3-4b-q5km",
            "spark-x2.5-4b-q4km",
            "neohorse-1-4b-q4km",
            "agents-a1-4b-q4km",
            "ling-3.0-tiny-q4km",
            "gemma-4-e4b-it-qat-q4_0",
        ]

    def test_only_takes_candidate_or_gguf_ids(self, catalog):
        assert [v.id for v in select_variants(catalog, ["neohorse-1-4b"])] == ["neohorse-1-4b-q4km"]
        assert [v.id for v in select_variants(catalog, ["neohorse-1-4b"], all_quants=True)] == [
            "neohorse-1-4b-q4km",
            "neohorse-1-4b-q5km",
        ]
        assert [v.id for v in select_variants(catalog, ["gemma-4-e4b-it-q5km", "qwen3-4b-q4km"])] == [
            "qwen3-4b-q4km",
            "gemma-4-e4b-it-q5km",
        ]

    def test_an_unknown_id_is_an_error(self, catalog):
        with pytest.raises(ValueError, match="unknown candidate or gguf id: phi-5"):
            select_variants(catalog, ["phi-5"])

    def test_all_quants_selects_every_file(self, catalog):
        assert len(select_variants(catalog, all_quants=True)) == 14


class TestServerCommand:
    def test_the_stack_arguments_are_kept_with_the_candidate_model_and_reasoning(self):
        args = server_args(STACK_ARGS, "ling-3.0-tiny-Q4_K_M.gguf", "off")
        assert args[:2] == ["--model", "/models/ling-3.0-tiny-Q4_K_M.gguf"]
        assert args[2:-2] == STACK_ARGS[2:]
        assert args[-2:] == ["--reasoning", "off"]

    def test_short_and_equals_forms_and_an_earlier_reasoning_flag_are_replaced(self):
        args = server_args(["-m", "/models/a.gguf", "--port=8080", "--reasoning=on", "-rea", "auto"], "b.gguf", "auto")
        assert args == ["--model", "/models/b.gguf", "--port=8080", "--reasoning", "auto"]
        assert server_args(["--model=/models/a.gguf", "--metrics"], "b.gguf", "on") == [
            "--model", "/models/b.gguf", "--metrics", "--reasoning", "on",
        ]

    def test_without_a_model_flag_one_is_added(self):
        assert server_args(["--port", "8080"], "b.gguf", "off") == [
            "--model", "/models/b.gguf", "--port", "8080", "--reasoning", "off",
        ]

    def test_the_candidate_joins_the_stack_network_as_llm(self):
        command = candidate_run_command(
            image="ghcr.io/ggml-org/llama.cpp:server-b11382",
            network="infra_horus-net",
            models_dir="/srv/horus/models",
            args=["--model", "/models/x.gguf"],
            memory_bytes=6 * 2**30,
        )
        assert command == [
            "docker", "run", "-d", "--name", CANDIDATE_CONTAINER,
            "--network", "infra_horus-net", "--network-alias", "llm",
            "--memory", str(6 * 2**30), "--memory-swap", str(6 * 2**30),
            "-v", "/srv/horus/models:/models:ro",
            "ghcr.io/ggml-org/llama.cpp:server-b11382", "--model", "/models/x.gguf",
        ]
        unlimited = candidate_run_command(image="i", network="n", models_dir="m", args=[], memory_bytes=None)
        assert "--memory" not in unlimited

    def test_the_network_prefers_horus_net(self):
        assert candidate_network(["bridge", "infra_horus-net"]) == "infra_horus-net"
        assert candidate_network(["custom"]) == "custom"
        assert candidate_network([]) is None


def test_parse_container_inspect_reads_what_the_runner_reuses():
    text = json.dumps(
        [
            {
                "Name": "/llm",
                "RestartCount": 0,
                "State": {"Running": True, "OOMKilled": False},
                "Config": {"Image": "ghcr.io/ggml-org/llama.cpp:server-b11382", "Cmd": STACK_ARGS},
                "HostConfig": {"Memory": 6442450944},
                "NetworkSettings": {"Networks": {"infra_horus-net": {}}},
                "Mounts": [{"Source": "/home/u/horus/models", "Destination": "/models"}],
            }
        ]
    )
    assert parse_container_inspect(text) == {
        "name": "llm",
        "image": "ghcr.io/ggml-org/llama.cpp:server-b11382",
        "args": STACK_ARGS,
        "networks": ["infra_horus-net"],
        "memory_bytes": 6442450944,
        "running": True,
        "oom_killed": False,
        "restart_count": 0,
        "models_source": "<models-dir>",
    }
    assert parse_container_inspect("[]") is None
    assert parse_container_inspect(None) is None
    assert parse_container_inspect(json.dumps([{"HostConfig": {"Memory": 0}}]))["memory_bytes"] is None
    assert parse_container_inspect(json.dumps([{"Mounts": []}]))["models_source"] is None
    volume = {"Type": "volume", "Name": "infra_llm_models", "Source": "/var/lib/docker/volumes/infra_llm_models/_data", "Destination": "/models"}
    assert parse_container_inspect(json.dumps([{"Mounts": [volume]}]))["models_source"] == "infra_llm_models"


def test_parse_container_env_reads_the_variables_the_container_was_given():
    text = json.dumps([{"Config": {"Env": ["PATH=/usr/bin", "AGENT_RESPONSE_CACHE=1", "EMPTY=", "LLM_VLLM_URL=http://llm:8080/v1?a=b", "BARE"]}}])
    assert parse_container_env(text) == {
        "PATH": "/usr/bin",
        "AGENT_RESPONSE_CACHE": "1",
        "EMPTY": "",
        "LLM_VLLM_URL": "http://llm:8080/v1?a=b",
    }
    assert parse_container_env(json.dumps([{"Config": {"Env": None}}])) == {}
    assert parse_container_env("[]") is None
    assert parse_container_env(None) is None


@pytest.mark.parametrize(
    ("value", "enabled"),
    [("1", True), ("true", True), (" Yes ", True), ("ON", True), ("0", False), ("false", False), ("", False), (None, False), ("2", False)],
)
def test_setting_enabled_reads_a_flag_as_the_agent_does(value, enabled):
    assert setting_enabled(value) is enabled


def test_response_cache_finding_names_a_cache_that_is_on_or_cannot_be_checked():
    assert response_cache_finding({}, "agent") is None
    assert response_cache_finding({"AGENT_RESPONSE_CACHE": "0"}, "agent") is None
    assert response_cache_finding({"AGENT_RESPONSE_CACHE": "on"}, "agent") == (
        "the agent's response cache is on (AGENT_RESPONSE_CACHE=on): its key does not change with the model, "
        "so the evaluation could score answers cached for another model"
    )
    assert response_cache_finding(None, "horus-agent") == (
        "could not read the environment of the 'horus-agent' container to see whether its response cache is off"
    )


def test_parse_process_memory_reads_the_peak_and_the_mapped_model():
    status = "Name:\tllama-server\nVmHWM:\t 5242880 kB\nVmRSS:\t 4194304 kB\nRssAnon:\t 1048576 kB\nRssFile:\t 3145728 kB\n"
    assert parse_process_memory(status) == {
        "name": "llama-server",
        "vm_hwm_bytes": 5 * 2**30,
        "vm_rss_bytes": 4 * 2**30,
        "rss_anon_bytes": 2**30,
        "rss_file_bytes": 3 * 2**30,
    }
    assert parse_process_memory("") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("6g", 6 * 2**30), ("6144m", 6 * 2**30), ("6442450944", 6442450944), ("1.5G", int(1.5 * 2**30)), ("6gb", 6 * 2**30), ("lots", None), (None, None)],
)
def test_parse_memory_limit(text, expected):
    assert parse_memory_limit(text) == expected


def test_written_report_takes_the_last_path_a_tool_printed():
    lines = ["[info] 94 question(s), writing /b/x-eval-2026-10-06.json", "[ 1/94] ...", "[done] wrote /b/x-eval-2026-10-06.json"]
    assert written_report(lines) == "/b/x-eval-2026-10-06.json"
    assert written_report(["[info] 5 question(s), writing C:\\b\\y.json", "[error] stopped"]) == "C:\\b\\y.json"
    assert written_report(["nothing"]) is None


def bench_report(file):
    rows = []
    for threads, scale in ((4, 1.0), (8, 1.5)):
        for test, depth, tps in (("pp512", 0, 60.0), ("pp512", 4096, 40.0), ("pp2048", 0, 50.0), ("tg128", 0, 9.0), ("tg128", 4096, 7.0)):
            rows.append({"model": file, "test": test, "n_depth": depth, "type_k": "f16", "type_v": "f16", "n_threads": threads, "avg_ts": tps * scale, "stddev_ts": 0.5})
        rows.append({"model": file, "test": "tg128", "n_depth": 0, "type_k": "q8_0", "type_v": "q8_0", "n_threads": threads, "avg_ts": 99.0, "stddev_ts": 0.1})
    return {
        "kind": "horus-llama-bench",
        "llama_cpp": {"build": "b11382"},
        "models": [{"file": file, "sha256": "246d67d45f5b0c7447ca0ce0bdb8b46b8a47b593c5068635dc16422c051d7be9"}],
        "summary": rows,
    }


def eval_report():
    return {
        "kind": "horus-eval",
        "run": {"completed": True},
        "summary": {
            "questions": 100,
            "status": {"ok": 99, "timeout": 1},
            "answer_correct_auto": {"n": 100, "correct": 71, "pct": 71.0},
            "source_correct_auto": {"n": 90, "correct": 80, "pct": 88.9},
            "route_correct": {"n": 100, "correct": 97, "pct": 97.0},
            "manual_review": {"answer_correct_pct": None, "pending": 100},
            "fallbacks": {},
            "total_s": {"n": 100, "median": 61.2, "p90": 140.0},
            "ttft_s": {"n": 0},
            "llm": {"prompt_tps": 48.3, "generation_tps": 9.1},
        },
        "resources": {
            "stack_peak_mem_bytes": 9 * 2**30,
            "containers_sum_peak_mem_bytes": 8 * 2**30,
            "container_peak_mem_bytes": {CANDIDATE_CONTAINER: 5 * 2**30, "mas": 2**30},
            "container_lifetime_peak_mem_bytes": {CANDIDATE_CONTAINER: 6 * 2**30},
            "container_oom_kills": {CANDIDATE_CONTAINER: 0},
            "docker_host_swap_growth_bytes": 0,
        },
    }


def contract_report():
    return {
        "kind": "horus-contract-probe",
        "summary": {
            "replies": 94,
            "json_valid": {"n": 94, "correct": 93, "pct": 98.9},
            "failures": {"truncated": 1},
            "thought_first": 0,
            "truncated": 1,
            "blank_answers": 0,
            "status_correct": {"n": 94, "correct": 85, "pct": 90.4},
            "answer_correct_auto": {"n": 94, "correct": 70, "pct": 74.5},
            "source_correct_auto": {"n": 84, "correct": 75, "pct": 89.3},
            "wall_s": {"n": 94, "median": 22.4},
            "completion_tokens": {"n": 94, "median": 41},
            "prompt_tps": 51.2,
            "generation_tps": 9.4,
        },
    }


class TestAggregation:
    def test_bench_speeds_keep_the_fastest_thread_count_for_the_catalogs_cache_type(self):
        speeds = bench_speeds(bench_report("x.gguf"))
        assert [(s["test"], s["depth"], s["tps"], s["threads"]) for s in speeds] == [
            ("pp512", 0, 90.0, 8),
            ("pp512", 4096, 60.0, 8),
            ("pp2048", 0, 75.0, 8),
            ("tg128", 0, 13.5, 8),
            ("tg128", 4096, 10.5, 8),
        ]
        assert bench_speeds(None) == []

    def test_eval_headline_reads_the_candidate_container(self):
        headline = eval_headline(eval_report())
        assert headline["answer_correct_auto"]["pct"] == 71.0
        assert headline["llm_peak_mem_bytes"] == 5 * 2**30
        assert headline["llm_lifetime_peak_mem_bytes"] == 6 * 2**30
        assert headline["llm_oom_kills"] == 0
        assert headline["stack_peak_mem_bytes"] == 9 * 2**30
        assert headline["llm_generation_tps"] == 9.1
        assert eval_headline(None) is None

    def test_variant_summary_and_report(self, catalog):
        variant = variant_by_id(catalog, "ling-3.0-tiny-q4km")
        memory = {
            "after_probe": {"process": {"vm_hwm_bytes": 5 * 2**30}, "cgroup_peak_bytes": 5 * 2**30 + 7, "oom_kills": 0},
            "after_eval": {"process": {"vm_hwm_bytes": 5 * 2**30 + 9}, "cgroup_peak_bytes": None, "oom_kills": 0},
        }
        summary = variant_summary(
            variant,
            fetch={"status": "verified", "method": "installer"},
            reports={"eval": "model-candidates-2026-10-06/ling-3.0-tiny-q4km-eval-2026-10-06.json"},
            bench_report=bench_report(variant.file),
            contract_report=contract_report(),
            eval_report=eval_report(),
            server={"build": "b11382"},
            memory=memory,
            problems=[],
        )
        assert summary["id"] == "ling-3.0-tiny-q4km"
        assert summary["licence"] == "MIT"
        assert summary["licence_flags"]
        assert summary["llama_bench"]["sha256_matches_catalog"] is True
        assert summary["contract"]["json_valid"]["pct"] == 98.9
        assert summary["reports"] == {
            "llama_bench": None,
            "contract": None,
            "eval": "model-candidates-2026-10-06/ling-3.0-tiny-q4km-eval-2026-10-06.json",
        }
        report = build_report(run={"started_at": "2026-10-06T08:00:00Z", "steps": ["probe"]}, catalog={"version": "1.0.0"}, machine=None, variants=[summary])
        assert report["kind"] == REPORT_KIND
        assert report["machine"] == {}
        json.dumps(report)

    def test_contract_headline_is_none_without_a_probe(self):
        assert contract_headline(None) is None


class TestMarkdown:
    def report(self, catalog):
        done = variant_summary(
            variant_by_id(catalog, "qwen3-4b-q4km"),
            bench_report=bench_report("qwen3-4b-instruct-2507-Q4_K_M.gguf"),
            contract_report=contract_report(),
            eval_report=eval_report(),
            memory={"after_eval": {"process": {"vm_hwm_bytes": 3 * 2**30}, "cgroup_peak_bytes": 4 * 2**30, "oom_kills": 0}},
        )
        failed = variant_summary(
            variant_by_id(catalog, "agents-a1-4b-q4km"),
            fetch={"status": "failed", "error": "HTTP 404"},
            problems=["download failed: HTTP 404"],
        )
        return build_report(
            run={"started_at": "2026-10-06T08:00:00Z", "steps": ["fetch", "bench", "probe", "eval"], "reasoning": "off", "completed": True},
            catalog={"path": "scripts/benchmarks/model-candidates.yaml", "version": "1.0.0", "pinned_build": "b11382"},
            machine={"reference": "cpu16", "cpu_model": "AMD Ryzen 5 5600U", "ram": "16 GiB installed"},
            variants=[done, failed],
        )

    def test_rows_show_measured_values_and_dashes_for_the_rest(self, catalog):
        text = markdown_summary(self.report(catalog))
        lines = text.splitlines()
        assert lines[0] == "# Model candidates, 2026-10-06"
        assert "reasoning `off`" in lines[2]
        assert "AMD Ryzen 5 5600U" in lines[2]
        quality = [line for line in lines if line.startswith("| Qwen3-4B-Instruct-2507 (baseline)")]
        assert quality[0] == (
            "| Qwen3-4B-Instruct-2507 (baseline) | Q4_K_M, community | Apache-2.0 | 93/94 (98.9%) | 0 | "
            "85/94 (90.4%) | 70/94 (74.5%) | 75/84 (89.3%) | 71/100 (71.0%) | – | 80/90 (88.9%) |"
        )
        assert quality[1] == (
            "| Qwen3-4B-Instruct-2507 (baseline) | Q4_K_M, community | 2.33 GiB | 90.0 | 75.0 | 13.5 | 10.5 | "
            "22.4 | 61.2 | – | 3.00 GiB | 4.00 GiB | 9.00 GiB | 0 |"
        )
        failed = [line for line in lines if line.startswith("| Agents-A1-4B")]
        assert failed[0].count("–") == 8
        assert "- `agents-a1-4b-q4km`: download failed: HTTP 404" in lines
        assert "stack peak: the evaluation's `stack_peak_mem_bytes`, the ADR-005 `P`: the peak memory of the whole stack" in text
        assert any(line.startswith("- Agents-A1-4B: The licence is only in the card metadata") for line in lines)

    def test_licence_flags_are_listed_once_per_candidate(self, catalog):
        report = self.report(catalog)
        report["variants"].append(variant_summary(variant_by_id(catalog, "agents-a1-4b-q5km")))
        text = markdown_summary(report)
        assert text.count("- Agents-A1-4B: No base model is declared") == 1
