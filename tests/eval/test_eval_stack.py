import json

from eval_stack import (
    build_tag,
    llm_usage,
    parse_cgroup_bytes,
    parse_memory_events,
    parse_prometheus,
    parse_props,
    parse_server_args,
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

COMPOSE_CPU_COMMAND = [
    "--model", "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
    "--alias", "qwen3-4b",
    "--host", "0.0.0.0",
    "--port", "8080",
    "--ctx-size", "8192",
    "--parallel", "1",
    "--load-mode", "mmap",
    "--cache-ram", "1024",
    "--threads", "6",
    "--metrics",
]


class TestPrometheus:
    def test_counters_are_read_and_comments_skipped(self):
        values = parse_prometheus(METRICS_BEFORE)
        assert values["llamacpp:prompt_tokens_total"] == 1200.0
        assert values["llamacpp:prompt_seconds_total"] == 30.5
        assert "# HELP" not in "".join(values)

    def test_labelled_and_malformed_lines_are_skipped(self):
        text = 'llamacpp:x{slot="0"} 4\nnot a metric line here\nllamacpp:y NaN\nllamacpp:z abc\n'
        values = parse_prometheus(text)
        assert "llamacpp:x" not in values
        assert "llamacpp:z" not in values
        assert values["llamacpp:y"] != values["llamacpp:y"]

    def test_nothing_read_gives_an_empty_dict(self):
        assert parse_prometheus(None) == {}


class TestLlmUsage:
    def test_question_usage_is_the_counter_difference(self):
        usage = llm_usage(parse_prometheus(METRICS_BEFORE), parse_prometheus(METRICS_AFTER))
        assert usage == {
            "prompt_tokens": 2000,
            "prompt_s": 40.0,
            "generated_tokens": 160,
            "generation_s": 16.0,
            "decode_calls": 162,
            "prompt_tps": 50.0,
            "generation_tps": 10.0,
        }

    def test_counters_going_down_mean_the_server_restarted(self):
        usage = llm_usage(parse_prometheus(METRICS_AFTER), parse_prometheus(METRICS_BEFORE))
        assert usage == {"restarted": True}

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


class TestServerArgs:
    def test_compose_command_of_the_cpu_overlay(self):
        settings = parse_server_args(COMPOSE_CPU_COMMAND)
        assert settings == {
            "model": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "alias": "qwen3-4b",
            "port": 8080,
            "ctx_size": 8192,
            "parallel": 1,
            "load_mode": "mmap",
            "cache_ram_mib": 1024,
            "threads": 6,
            "cache_type_k": "f16",
            "cache_type_v": "f16",
        }

    def test_short_flags_and_equals_form_set_the_kv_cache(self):
        settings = parse_server_args(["-c", "4096", "-ctk", "q8_0", "--cache-type-v=q8_0", "-fa", "on"])
        assert settings["ctx_size"] == 4096
        assert settings["cache_type_k"] == "q8_0"
        assert settings["cache_type_v"] == "q8_0"
        assert settings["flash_attn"] == "on"

    def test_unknown_switches_do_not_swallow_the_next_flag(self):
        settings = parse_server_args(["--metrics", "--threads", "4", "--jinja"])
        assert settings["threads"] == 4

    def test_no_arguments_mean_the_default_kv_cache(self):
        assert parse_server_args(None) == {"cache_type_k": "f16", "cache_type_v": "f16"}


class TestProps:
    def test_build_model_and_context_are_read(self):
        props = {
            "build_info": "b11382-11fe0215",
            "model_path": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "total_slots": 1,
            "default_generation_settings": {"n_ctx": 8192},
        }
        assert parse_props(json.dumps(props)) == {
            "build_info": "b11382-11fe0215",
            "model_path": "/models/qwen3-4b-instruct-2507-Q4_K_M.gguf",
            "n_ctx": 8192,
            "total_slots": 1,
        }

    def test_unreadable_props_give_nothing(self):
        assert parse_props(None) == {}
        assert parse_props("[1, 2]") == {}

    def test_build_tag_from_build_info_and_image_tags(self):
        assert build_tag("b11382-11fe0215") == "b11382"
        assert build_tag("server-b11382") == "b11382"
        assert build_tag("11382 (11fe0215)") == "b11382"
        assert build_tag("latest") is None
        assert build_tag(None) is None


class TestCgroup:
    def test_memory_peak_in_bytes(self):
        assert parse_cgroup_bytes("4294967296\n") == 4294967296
        assert parse_cgroup_bytes("max") is None
        assert parse_cgroup_bytes(None) is None

    def test_memory_events_count_oom_kills(self):
        events = "low 0\nhigh 0\nmax 12\noom 1\noom_kill 1\noom_group_kill 0\n"
        assert parse_memory_events(events)["oom_kill"] == 1
        assert parse_memory_events(None) == {}
