# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit.llama_server import (
    CANDIDATE_CONTAINER,
    build_tag,
    candidate_network,
    candidate_run_command,
    llm_usage,
    parse_container_env,
    parse_container_inspect,
    parse_memory_events,
    parse_memory_limit,
    parse_memory_stat,
    parse_process_memory,
    parse_process_status,
    parse_prometheus,
    parse_props,
    parse_server_args,
    parse_whole_number,
    server_args,
)

METRICS_BEFORE = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 1200
llamacpp:prompt_seconds_total 30.5
llamacpp:tokens_predicted_total 300
llamacpp:tokens_predicted_seconds_total 25
llamacpp:n_decode_total 310
llamacpp:requests_processing 0
"""

METRICS_AFTER = """llamacpp:prompt_tokens_total 3200
llamacpp:prompt_seconds_total 70.5
llamacpp:tokens_predicted_total 460
llamacpp:tokens_predicted_seconds_total 41
llamacpp:n_decode_total 472
llamacpp:requests_processing 1
"""

MEMORY_STAT = """anon 1879048192
file 2621440000
kernel 41943040
file_mapped 2550136832
active_anon 1879048192
active_file 52428800
inactive_file 2569011200
"""

SERVER_STATUS = """Name:\tllama-server
Umask:\t0022
State:\tS (sleeping)
VmHWM:\t 5242880 kB
VmRSS:\t 4194304 kB
RssAnon:\t 1048576 kB
RssFile:\t 3145728 kB
Threads:\t8
"""

SERVER_COMMAND = [
    "--model", "/models/alpha-1b-Q4_K_M.gguf",
    "--alias", "alpha",
    "--host", "0.0.0.0",
    "--port", "8080",
    "--ctx-size", "16384",
    "--parallel", "2",
    "--cache-type-k", "q8_0",
    "--cache-type-v", "q8_0",
    "--load-mode", "mmap",
    "--cache-ram", "2048",
    "--threads", "12",
    "--metrics",
]


class TestPrometheus:
    def test_counters_are_read_and_comments_skipped(self):
        values = parse_prometheus(METRICS_BEFORE)
        assert values["llamacpp:prompt_tokens_total"] == 1200.0
        assert values["llamacpp:prompt_seconds_total"] == 30.5
        assert "# HELP" not in "".join(values)

    def test_labelled_and_malformed_lines_are_skipped(self):
        values = parse_prometheus('llamacpp:x{slot="0"} 4\nnot a metric line here\nllamacpp:y NaN\nllamacpp:z abc\n')
        assert "llamacpp:x" not in values
        assert "llamacpp:z" not in values
        assert values["llamacpp:y"] != values["llamacpp:y"]

    def test_nothing_read_gives_an_empty_dict(self):
        assert parse_prometheus(None) == {}


class TestLlmUsage:
    def test_usage_is_the_counter_difference(self):
        assert llm_usage(parse_prometheus(METRICS_BEFORE), parse_prometheus(METRICS_AFTER)) == {
            "prompt_tokens": 2000,
            "prompt_s": 40.0,
            "generated_tokens": 160,
            "generation_s": 16.0,
            "decode_calls": 162,
            "prompt_tps": 50.0,
            "generation_tps": 10.0,
        }

    def test_counters_going_down_mean_the_server_restarted(self):
        assert llm_usage(parse_prometheus(METRICS_AFTER), parse_prometheus(METRICS_BEFORE)) == {"restarted": True}

    def test_missing_scrape_gives_no_usage(self):
        assert llm_usage(None, parse_prometheus(METRICS_AFTER)) is None
        assert llm_usage(parse_prometheus(METRICS_BEFORE), {}) is None
        assert llm_usage({"other": 1.0}, {"other": 2.0}) is None

    def test_idle_server_has_no_rates(self):
        before = parse_prometheus(METRICS_BEFORE)
        usage = llm_usage(before, dict(before))
        assert usage["prompt_tokens"] == 0
        assert usage["prompt_tps"] is None
        assert usage["generation_tps"] is None


class TestServerSettings:
    def test_a_full_command_line(self):
        assert parse_server_args(SERVER_COMMAND) == {
            "model": "/models/alpha-1b-Q4_K_M.gguf",
            "alias": "alpha",
            "port": 8080,
            "ctx_size": 16384,
            "parallel": 2,
            "cache_type_k": "q8_0",
            "cache_type_v": "q8_0",
            "load_mode": "mmap",
            "cache_ram_mib": 2048,
            "threads": 12,
        }

    def test_short_flags_and_equals_form_set_the_kv_cache(self):
        settings = parse_server_args(["-c", "4096", "-ctk", "q8_0", "--cache-type-v=q8_0", "-fa", "on"])
        assert settings["ctx_size"] == 4096
        assert (settings["cache_type_k"], settings["cache_type_v"]) == ("q8_0", "q8_0")
        assert settings["flash_attn"] == "on"

    def test_unknown_switches_do_not_swallow_the_next_flag(self):
        assert parse_server_args(["--metrics", "--threads", "4", "--jinja"])["threads"] == 4

    def test_no_arguments_mean_the_default_kv_cache(self):
        assert parse_server_args(None) == {"cache_type_k": "f16", "cache_type_v": "f16"}


class TestProps:
    def test_build_model_and_context_are_read(self):
        props = {
            "build_info": "b11382-0a1b2c3d",
            "model_path": "/models/alpha-1b-Q4_K_M.gguf",
            "total_slots": 1,
            "default_generation_settings": {"n_ctx": 8192},
        }
        assert parse_props(json.dumps(props)) == {
            "build_info": "b11382-0a1b2c3d",
            "model_path": "/models/alpha-1b-Q4_K_M.gguf",
            "n_ctx": 8192,
            "total_slots": 1,
        }

    def test_unreadable_props_give_nothing(self):
        assert parse_props(None) == {}
        assert parse_props("[1, 2]") == {}

    def test_build_tag_from_build_info_and_image_tags(self):
        assert build_tag("b11382-0a1b2c3d") == "b11382"
        assert build_tag("server-b11382") == "b11382"
        assert build_tag("11382 (0a1b2c3d)") == "b11382"
        assert build_tag("latest") is None
        assert build_tag(None) is None


class TestCgroupAndProc:
    def test_whole_numbers(self):
        assert parse_whole_number("4294967296\n") == 4294967296
        assert parse_whole_number("max") is None
        assert parse_whole_number(None) is None

    def test_memory_events_count_oom_kills(self):
        assert parse_memory_events("low 0\nhigh 0\nmax 12\noom 1\noom_kill 1\n")["oom_kill"] == 1
        assert parse_memory_events(None) == {}

    def test_memory_stat_keeps_the_page_cache_split(self):
        assert parse_memory_stat(MEMORY_STAT) == {
            "anon": 1879048192,
            "file": 2621440000,
            "active_file": 52428800,
            "inactive_file": 2569011200,
            "file_mapped": 2550136832,
        }
        assert parse_memory_stat("total_cache 100\n") is None

    def test_process_status_and_memory(self):
        assert parse_process_status(SERVER_STATUS) == {"name": "llama-server", "rss_file_bytes": 3 * 2**30}
        assert parse_process_status("Name:\tllama-server\nVmRSS:\t 100 kB\n")["rss_file_bytes"] is None
        assert parse_process_status("") is None
        assert parse_process_memory(SERVER_STATUS) == {
            "name": "llama-server",
            "vm_hwm_bytes": 5 * 2**30,
            "vm_rss_bytes": 4 * 2**30,
            "rss_anon_bytes": 2**30,
            "rss_file_bytes": 3 * 2**30,
        }
        assert parse_process_memory("") is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("6g", 6 * 2**30),
            ("6144m", 6 * 2**30),
            ("6442450944", 6442450944),
            ("1.5G", int(1.5 * 2**30)),
            ("6gb", 6 * 2**30),
            ("lots", None),
            (None, None),
        ],
    )
    def test_memory_limits(self, text, expected):
        assert parse_memory_limit(text) == expected


class TestServerCommand:
    def test_the_arguments_are_kept_with_the_candidate_model_and_reasoning(self):
        args = server_args(SERVER_COMMAND, "beta-2b-Q4_K_M.gguf", "off")
        assert args[:2] == ["--model", "/models/beta-2b-Q4_K_M.gguf"]
        assert args[2:-2] == SERVER_COMMAND[2:]
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

    def test_a_standalone_candidate_publishes_a_port(self):
        command = candidate_run_command(
            image="ghcr.io/ggml-org/llama.cpp:server-b11382",
            models_dir="/srv/models",
            args=["--model", "/models/x.gguf"],
            memory_bytes=None,
            publish="127.0.0.1:18080:8080",
        )
        assert command == [
            "docker", "run", "-d", "--name", CANDIDATE_CONTAINER, "-p", "127.0.0.1:18080:8080",
            "-v", "/srv/models:/models:ro", "ghcr.io/ggml-org/llama.cpp:server-b11382", "--model", "/models/x.gguf",
        ]

    def test_a_candidate_can_join_a_network_under_an_alias(self):
        command = candidate_run_command(
            image="server-image",
            models_dir="/srv/models",
            args=[],
            memory_bytes=6 * 2**30,
            name="bench-candidate",
            network="lab_bench-net",
            alias="model-server",
        )
        assert command == [
            "docker", "run", "-d", "--name", "bench-candidate",
            "--network", "lab_bench-net", "--network-alias", "model-server",
            "--memory", str(6 * 2**30), "--memory-swap", str(6 * 2**30),
            "-v", "/srv/models:/models:ro", "server-image",
        ]

    def test_the_network_can_prefer_a_suffix(self):
        assert candidate_network(["bridge", "lab_bench-net"], "bench-net") == "lab_bench-net"
        assert candidate_network(["bridge", "lab_bench-net"]) == "bridge"
        assert candidate_network(["custom"], "bench-net") == "custom"
        assert candidate_network([]) is None


def test_parse_container_inspect_reads_what_a_runner_reuses():
    text = json.dumps(
        [
            {
                "Name": "/model-server",
                "RestartCount": 0,
                "State": {"Running": True, "OOMKilled": False},
                "Config": {"Image": "ghcr.io/ggml-org/llama.cpp:server-b11382", "Cmd": SERVER_COMMAND},
                "HostConfig": {"Memory": 6442450944},
                "NetworkSettings": {"Networks": {"lab_bench-net": {}}},
                "Mounts": [{"Source": "/home/u/models", "Destination": "/models"}],
            }
        ]
    )
    assert parse_container_inspect(text) == {
        "name": "model-server",
        "image": "ghcr.io/ggml-org/llama.cpp:server-b11382",
        "args": SERVER_COMMAND,
        "networks": ["lab_bench-net"],
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
    volume = {"Type": "volume", "Name": "bench_models", "Source": "/var/lib/docker/volumes/bench_models/_data", "Destination": "/models"}
    assert parse_container_inspect(json.dumps([{"Mounts": [volume]}]))["models_source"] == "bench_models"


def test_parse_container_env_reads_the_variables_the_container_was_given():
    text = json.dumps([{"Config": {"Env": ["PATH=/usr/bin", "CACHE=1", "EMPTY=", "URL=http://x:8080/v1?a=b", "BARE"]}}])
    assert parse_container_env(text) == {"PATH": "/usr/bin", "CACHE": "1", "EMPTY": "", "URL": "http://x:8080/v1?a=b"}
    assert parse_container_env(json.dumps([{"Config": {"Env": None}}])) == {}
    assert parse_container_env("[]") is None
    assert parse_container_env(None) is None
